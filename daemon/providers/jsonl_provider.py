"""
Native JSONL provider for llm-usage-indicator.

Reads Claude Code conversation logs directly from local JSONL files —
no Node.js or ccusage required.

Scanned path (all platforms): ~/.claude/projects/**/*.jsonl
"""

import asyncio
import datetime
import json
import logging
import time
from pathlib import Path
from typing import Optional

from .base import ProviderStatus, model_to_provider
from ..store import Store

logger = logging.getLogger(__name__)

# USD per 1,000,000 tokens: (input, output, cache_write, cache_read)
# Sourced from ccusage embedded pricing (anthropic.* entries).
# Listed most-specific-first so prefix matching picks the right tier.
_MODEL_PRICING: list[tuple[str, tuple[float, float, float, float]]] = [
    # Claude Fable 5
    ("claude-fable-5",      (10.00, 50.00, 12.50, 1.00)),
    # Claude 4 – Haiku
    ("claude-haiku-4-5",    (1.00,  5.00,  1.25,  0.10)),
    ("claude-haiku-4",      (1.00,  5.00,  1.25,  0.10)),
    # Claude 4 – Opus  (4.5+ repriced vs original 4.0/4.1)
    ("claude-opus-4-8",     (5.00,  25.00, 6.25,  0.50)),
    ("claude-opus-4-7",     (5.00,  25.00, 6.25,  0.50)),
    ("claude-opus-4-6",     (5.00,  25.00, 6.25,  0.50)),
    ("claude-opus-4-5",     (5.00,  25.00, 6.25,  0.50)),
    ("claude-opus-4-1",     (15.00, 75.00, 18.75, 1.50)),
    ("claude-opus-4",       (15.00, 75.00, 18.75, 1.50)),
    # Claude 4 – Sonnet
    ("claude-sonnet-4",     (3.00,  15.00, 3.75,  0.30)),
    # Claude 3.7 / 3.5
    ("claude-3-7-sonnet",   (3.00,  15.00, 3.75,  0.30)),
    ("claude-3-5-sonnet",   (3.00,  15.00, 3.75,  0.30)),
    ("claude-3-5-haiku",    (0.80,  4.00,  1.00,  0.08)),
    # Claude 3
    ("claude-3-opus",       (15.00, 75.00, 18.75, 1.50)),
    ("claude-3-sonnet",     (3.00,  15.00, 3.75,  0.30)),
    ("claude-3-haiku",      (0.25,  1.25,  0.3125, 0.025)),
]

_DEFAULT_PRICING: tuple[float, float, float, float] = (3.00, 15.00, 3.75, 0.30)


def _get_pricing(model: str) -> tuple[float, float, float, float]:
    lower = model.lower()
    for prefix, pricing in _MODEL_PRICING:
        if lower.startswith(prefix):
            return pricing
    return _DEFAULT_PRICING


def _compute_cost(model: str, usage: dict) -> float:
    inp        = int(usage.get("input_tokens", 0))
    out        = int(usage.get("output_tokens", 0))
    cache_w    = int(usage.get("cache_creation_input_tokens", 0))
    cache_r    = int(usage.get("cache_read_input_tokens", 0))
    p_in, p_out, p_cw, p_cr = _get_pricing(model)
    return (inp * p_in + out * p_out + cache_w * p_cw + cache_r * p_cr) / 1_000_000


def _parse_date(timestamp: str) -> Optional[str]:
    """Return local ISO date string (YYYY-MM-DD) or None on error."""
    try:
        ts = timestamp.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(ts)
        return dt.astimezone().date().isoformat()
    except Exception:
        return None


def _claude_projects_root() -> Optional[Path]:
    return Path.home() / ".claude" / "projects"


def _scan_jsonl_files(root_override: Optional[Path] = None) -> list[Path]:
    root = root_override or _claude_projects_root()
    if root is None or not root.exists():
        return []
    return list(root.rglob("*.jsonl"))


def _parse_file(path: Path) -> list[tuple[str, str, str, float]]:
    """Parse one JSONL file. Returns [(request_id, date_str, model, cost_usd), ...]."""
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

                if entry.get("type") != "assistant":
                    continue

                message = entry.get("message", {})
                model = message.get("model") or entry.get("model", "")
                if not model:
                    continue

                timestamp = entry.get("timestamp") or message.get("timestamp", "")
                if not timestamp:
                    continue

                date_str = _parse_date(timestamp)
                if not date_str:
                    continue

                # Dedup key: prefer entry-level requestId, fall back to message id
                request_id = (
                    entry.get("requestId")
                    or message.get("id")
                    or f"{path}:{timestamp}"
                )

                # Use pre-computed cost when available (newer Claude Code versions)
                cost_field = entry.get("costUSD")
                if cost_field is None:
                    cost_field = entry.get("cost_usd")
                if cost_field is None:
                    usage = message.get("usage", {})
                    if not usage:
                        continue
                    cost_field = _compute_cost(model, usage)

                results.append((request_id, date_str, model, float(cost_field)))
    except OSError:
        pass
    return results


def _aggregate(
    files: list[Path],
    budgets: dict[str, float],
    today_str: str,
) -> list[ProviderStatus]:
    month_str = today_str[:7]  # "YYYY-MM"
    month_costs: dict[str, float] = {}
    today_costs: dict[str, float] = {}
    seen_ids: set[str] = set()  # dedup by requestId across all files

    for path in files:
        for request_id, date_str, model, cost in _parse_file(path):
            if request_id in seen_ids:
                continue
            seen_ids.add(request_id)
            provider = model_to_provider(model)
            if date_str.startswith(month_str):
                month_costs[provider] = month_costs.get(provider, 0.0) + cost
            if date_str == today_str:
                today_costs[provider] = today_costs.get(provider, 0.0) + cost

    now = time.time()
    statuses: list[ProviderStatus] = []
    seen: set[str] = set()

    for provider in sorted(month_costs.keys()):
        seen.add(provider)
        statuses.append(ProviderStatus(
            name=provider,
            budget_usd=budgets.get(provider, 0.0),
            spent_total=month_costs[provider],
            spent_today=today_costs.get(provider, 0.0),
            updated_at=now,
        ))

    for provider in sorted(budgets.keys()):
        if provider not in seen and budgets[provider] > 0:
            statuses.append(ProviderStatus(
                name=provider,
                budget_usd=budgets[provider],
                spent_total=0.0,
                spent_today=0.0,
                updated_at=now,
            ))

    return statuses


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
        self._claude_home = claude_home  # override root for testing

    def _zero_statuses(self) -> list[ProviderStatus]:
        now = time.time()
        return [
            ProviderStatus(
                name=provider,
                budget_usd=self._budgets[provider],
                spent_total=0.0,
                spent_today=0.0,
                updated_at=now,
            )
            for provider in sorted(self._budgets.keys())
            if self._budgets[provider] > 0
        ]

    async def fetch_all_statuses(self) -> list[ProviderStatus]:
        today_str = datetime.date.today().isoformat()
        root_override = self._claude_home / "projects" if self._claude_home else None
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
