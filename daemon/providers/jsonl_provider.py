"""
Native JSONL provider for llm-usage-indicator.

Cost calculation ported from ccusage (github.com/ccusage/ccusage).
Reads Claude Code conversation logs from all platform-standard paths.
"""

import asyncio
import datetime
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from .base import ProviderStatus, model_to_provider
from ..store import Store

logger = logging.getLogger(__name__)

# ── Pricing ─────────────────────────────────────────────────────────────────────
# USD per million tokens:
#   (input, output, cache_write_5m, cache_read,
#    input_above_200k, output_above_200k, cw_above_200k, cr_above_200k)
# None = no tiered price tier for that field.
# Listed most-specific-first so prefix matching picks the right tier.

_NP = None  # sentinel: no tiered price

_MODEL_PRICING: list[tuple[str, tuple]] = [
    # ── Claude Fable 5 ──────────────────────────────────────────────────────
    ("claude-fable-5",    (10.00, 50.00, 12.50, 1.00,  _NP,  _NP,   _NP,  _NP)),
    # ── Claude Opus 4 ───────────────────────────────────────────────────────
    ("claude-opus-4-8",   (5.00,  25.00, 6.25,  0.50,  _NP,  _NP,   _NP,  _NP)),
    ("claude-opus-4-7",   (5.00,  25.00, 6.25,  0.50,  _NP,  _NP,   _NP,  _NP)),
    ("claude-opus-4-6",   (5.00,  25.00, 6.25,  0.50,  _NP,  _NP,   _NP,  _NP)),
    ("claude-opus-4-5",   (5.00,  25.00, 6.25,  0.50,  _NP,  _NP,   _NP,  _NP)),
    ("claude-opus-4",     (15.00, 75.00, 18.75, 1.50,  _NP,  _NP,   _NP,  _NP)),
    # ── Claude Sonnet 4 (tiered pricing above 200k tokens) ──────────────────
    ("claude-sonnet-4",   (3.00,  15.00, 3.75,  0.30,  6.00, 22.50, 7.50, 0.60)),
    # ── Claude Haiku 4 ──────────────────────────────────────────────────────
    ("claude-haiku-4-5",  (1.00,  5.00,  1.25,  0.10,  _NP,  _NP,   _NP,  _NP)),
    ("claude-haiku-4",    (1.00,  5.00,  1.25,  0.10,  _NP,  _NP,   _NP,  _NP)),
    # ── Claude 3.7 / 3.5 ────────────────────────────────────────────────────
    ("claude-3-7-sonnet", (3.00,  15.00, 3.75,  0.30,  _NP,  _NP,   _NP,  _NP)),
    ("claude-3-5-sonnet", (3.00,  15.00, 3.75,  0.30,  _NP,  _NP,   _NP,  _NP)),
    ("claude-3-5-haiku",  (0.80,  4.00,  1.00,  0.08,  _NP,  _NP,   _NP,  _NP)),
    # ── Claude 3 ────────────────────────────────────────────────────────────
    ("claude-3-opus",     (15.00, 75.00, 18.75, 1.50,  _NP,  _NP,   _NP,  _NP)),
    ("claude-3-sonnet",   (3.00,  15.00, 3.75,  0.30,  _NP,  _NP,   _NP,  _NP)),
    ("claude-3-haiku",    (0.25,  1.25,  0.30,  0.03,  _NP,  _NP,   _NP,  _NP)),
]

_DEFAULT_PRICING: tuple = (3.00, 15.00, 3.75, 0.30, _NP, _NP, _NP, _NP)

# Fast-mode price multipliers — applied when usage.speed == "fast".
_FAST_MULTIPLIERS: list[tuple[str, float]] = [
    ("claude-opus-4-8", 2.0),
    ("claude-opus-4-7", 6.0),
    ("claude-opus-4-6", 6.0),
]

_TIER_THRESHOLD = 200_000


def _get_pricing(model: str) -> tuple:
    lower = model.lower()
    for prefix, pricing in _MODEL_PRICING:
        if lower.startswith(prefix):
            return pricing
    return _DEFAULT_PRICING


def _get_fast_multiplier(model: str) -> float:
    lower = model.lower()
    for prefix, mult in _FAST_MULTIPLIERS:
        if lower.startswith(prefix):
            return mult
    return 1.0


def _tiered(tokens: int, base: float, above: Optional[float]) -> float:
    if tokens <= 0:
        return 0.0
    if above is not None and tokens > _TIER_THRESHOLD:
        return _TIER_THRESHOLD * base + (tokens - _TIER_THRESHOLD) * above
    return tokens * base


def _compute_cost(model: str, usage: dict) -> float:
    """Compute cost from token counts, ported from ccusage calculate_cost_from_tokens.

    NOTE: input_tokens is SEPARATE from cache tokens (not a superset).
    The total token count = input_tokens + cache_creation + cache_read + output_tokens.
    """
    inp     = int(usage.get("input_tokens", 0))
    out     = int(usage.get("output_tokens", 0))
    cache_r = int(usage.get("cache_read_input_tokens", 0))
    speed   = usage.get("speed")

    # Cache creation: new format uses a nested object with per-TTL breakdown;
    # legacy format uses a flat cache_creation_input_tokens field (= 5m TTL).
    cache_obj = usage.get("cache_creation") or {}
    if isinstance(cache_obj, dict) and cache_obj:
        cache_5m = int(cache_obj.get("ephemeral_5m_input_tokens", 0))
        cache_1h = int(cache_obj.get("ephemeral_1h_input_tokens", 0))
        if cache_5m == 0 and cache_1h == 0:
            cache_5m = int(usage.get("cache_creation_input_tokens", 0))
    else:
        cache_5m = int(usage.get("cache_creation_input_tokens", 0))
        cache_1h = 0

    p_in, p_out, p_cw, p_cr, p_in_hi, p_out_hi, p_cw_hi, p_cr_hi = _get_pricing(model)
    # 1h cache TTL is billed at 2× the base input rate (not the 1.25× 5m write rate).
    p_cw_1h = p_in * 2.0

    cost = (
        _tiered(inp,      p_in,  p_in_hi)
        + _tiered(out,    p_out, p_out_hi)
        + _tiered(cache_5m, p_cw, p_cw_hi)
        + cache_1h * p_cw_1h
        + _tiered(cache_r, p_cr, p_cr_hi)
    ) / 1_000_000

    if speed == "fast":
        cost *= _get_fast_multiplier(model)

    return cost


# ── File scanning ────────────────────────────────────────────────────────────────

def _claude_base_dirs() -> list[Path]:
    """Return all base dirs that contain a 'projects/' subdirectory.

    Priority (mirrors ccusage):
    1. CLAUDE_CONFIG_DIR env var (comma-separated) — exclusive if set.
    2. $XDG_CONFIG_HOME/claude  (default: ~/.config/claude)
    3. ~/.claude
    Paths 2 and 3 are de-duplicated by resolved path.
    """
    env_val = os.environ.get("CLAUDE_CONFIG_DIR", "")
    if env_val:
        dirs = []
        for raw in env_val.split(","):
            p = Path(raw.strip()).expanduser()
            if (p / "projects").exists():
                dirs.append(p)
        return dirs

    seen: set[Path] = set()
    dirs: list[Path] = []
    xdg_home = os.environ.get("XDG_CONFIG_HOME", "")
    candidates = [
        (Path(xdg_home).expanduser() if xdg_home else Path.home() / ".config") / "claude",
        Path.home() / ".claude",
    ]
    for p in candidates:
        resolved = p.resolve()
        if resolved not in seen and (p / "projects").exists():
            dirs.append(p)
            seen.add(resolved)
    return dirs


def _scan_jsonl_files(root_override: Optional[Path] = None) -> list[Path]:
    if root_override is not None:
        return list(root_override.rglob("*.jsonl"))
    files: list[Path] = []
    for base in _claude_base_dirs():
        files.extend((base / "projects").rglob("*.jsonl"))
    return files


# ── Entry parsing ─────────────────────────────────────────────────────────────────

def _parse_date(timestamp: str) -> Optional[str]:
    """Return local ISO date string (YYYY-MM-DD) or None on error."""
    try:
        ts = timestamp.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(ts)
        return dt.astimezone().date().isoformat()
    except Exception:
        return None


def _parse_file(path: Path) -> list[tuple[str, str, str, float]]:
    """Parse one JSONL file. Returns [(dedup_key, date_str, model, cost_usd), ...]."""
    results: list[tuple[str, str, str, float]] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Skip subagent sidechain entries: the same cost appears in the
                # parent session's JSONL under the same requestId, so counting
                # sidechain entries would double-count.
                if entry.get("isSidechain") or entry.get("is_sidechain"):
                    continue

                message = entry.get("message") or {}

                # Timestamp is required for date bucketing.
                timestamp = entry.get("timestamp") or message.get("timestamp", "")
                if not timestamp:
                    continue
                date_str = _parse_date(timestamp)
                if not date_str:
                    continue

                # ── Resolve cost ──────────────────────────────────────────────
                # ccusage counts ANY entry with a cost field, not just type=assistant.
                cost_field = entry.get("costUSD")
                if cost_field is None:
                    cost_field = entry.get("cost_usd")

                if cost_field is not None:
                    cost = float(cost_field)
                    if cost <= 0:
                        continue
                else:
                    # Fall back to token-based calculation (older JSONL entries).
                    usage = message.get("usage") or {}
                    if not usage:
                        continue
                    model_for_cost = message.get("model") or entry.get("model", "")
                    cost = _compute_cost(model_for_cost, usage)
                    if cost <= 0:
                        continue

                model = message.get("model") or entry.get("model", "")

                # Dedup key: (message.id, requestId) pair — mirrors ccusage.
                msg_id = message.get("id", "")
                req_id = entry.get("requestId", "")
                dedup_key = f"{msg_id}:{req_id}" if (msg_id or req_id) else f"{path}:{timestamp}"

                results.append((dedup_key, date_str, model, cost))
    except OSError:
        pass
    return results


# ── Aggregation ───────────────────────────────────────────────────────────────────

def _aggregate(
    files: list[Path],
    budgets: dict[str, float],
    today_str: str,
) -> list[ProviderStatus]:
    month_str = today_str[:7]
    month_costs: dict[str, float] = {}
    today_costs: dict[str, float] = {}
    seen_keys: set[str] = set()

    for path in files:
        for dedup_key, date_str, model, cost in _parse_file(path):
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            provider = model_to_provider(model)  # e.g. "Claude", "Gemini"
            if date_str.startswith(month_str):
                month_costs[provider] = month_costs.get(provider, 0.0) + cost
            if date_str == today_str:
                today_costs[provider] = today_costs.get(provider, 0.0) + cost

    now = time.time()
    statuses: list[ProviderStatus] = []
    seen_providers: set[str] = set()

    for provider in sorted(month_costs):
        seen_providers.add(provider)
        statuses.append(ProviderStatus(
            name=provider,
            budget_usd=budgets.get(provider.lower(), 0.0),
            spent_total=month_costs[provider],
            spent_today=today_costs.get(provider, 0.0),
            updated_at=now,
        ))

    # Append configured providers with no recorded usage yet.
    for key in sorted(budgets):
        provider = key.capitalize()
        if provider not in seen_providers and budgets[key] > 0:
            statuses.append(ProviderStatus(
                name=provider,
                budget_usd=budgets[key],
                spent_total=0.0,
                spent_today=0.0,
                updated_at=now,
            ))

    return statuses


# ── Provider class ────────────────────────────────────────────────────────────────

class JsonlProvider:
    """Fetches provider statuses by parsing Claude Code JSONL files directly."""

    def __init__(
        self,
        budgets: dict[str, float],
        store: Store,
        claude_home: Optional[Path] = None,
    ) -> None:
        self._budgets = budgets
        self._store = store
        self._claude_home = claude_home  # path override for testing

    def _zero_statuses(self) -> list[ProviderStatus]:
        now = time.time()
        return [
            ProviderStatus(
                name=k.capitalize(),
                budget_usd=v,
                spent_total=0.0,
                spent_today=0.0,
                updated_at=now,
            )
            for k, v in sorted(self._budgets.items())
            if v > 0
        ]

    async def fetch_all_statuses(self) -> list[ProviderStatus]:
        today_str = datetime.date.today().isoformat()
        root_override = (self._claude_home / "projects") if self._claude_home else None
        files = _scan_jsonl_files(root_override)

        loop = asyncio.get_running_loop()
        try:
            statuses = await loop.run_in_executor(
                None, _aggregate, files, self._budgets, today_str
            )
        except Exception as exc:
            logger.warning("JSONL parsing failed, reporting zero usage: %s", exc)
            return self._zero_statuses()

        for status in statuses:
            await self._store.save_snapshot(
                status.name.lower(), status.spent_total, status.spent_today
            )

        logger.debug("jsonl_provider: %d providers from %d files", len(statuses), len(files))
        return statuses
