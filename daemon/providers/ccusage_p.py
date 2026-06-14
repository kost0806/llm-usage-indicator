"""
ccusage provider for llm-usage-indicator.

Reads local Claude Code / Gemini CLI / OpenAI CLI usage data via
the ccusage CLI tool (https://github.com/ryoppippi/ccusage).
No API keys required — works with web-login-only environments.

ccusage reads JSONL conversation logs from:
  ~/.claude/projects/**/*.jsonl  (Claude Code)
  and similar paths for other tools it supports.
"""

import asyncio
import json
import logging
import time
import datetime
from typing import Optional

from .base import ProviderStatus
from ..store import Store

logger = logging.getLogger(__name__)

# Checked in order; first match wins.
_MODEL_PREFIX_MAP: list[tuple[str, str]] = [
    ("claude-", "Claude"),
    ("gemini-", "Gemini"),
    ("gpt-", "OpenAI"),
    ("o1-", "OpenAI"),
    ("o3-", "OpenAI"),
    ("o4-", "OpenAI"),
    ("chatgpt-", "OpenAI"),
    ("codex-", "OpenAI"),
    ("copilot-", "Copilot"),
]


def _model_to_provider(model_name: str) -> str:
    lower = model_name.lower()
    for prefix, provider in _MODEL_PREFIX_MAP:
        if lower.startswith(prefix):
            return provider
    return "Other"


class CcusageProvider:
    """Fetches all provider statuses from ccusage CLI in a single invocation."""

    def __init__(
        self,
        budgets: dict[str, float],
        store: Store,
        ccusage_cmd: str = "npx ccusage@latest",
    ) -> None:
        self._budgets = budgets       # {"Claude": 20.0, "Gemini": 15.0, ...}
        self._store = store
        self._ccusage_cmd = ccusage_cmd

    async def _run_ccusage(self) -> dict:
        cmd_parts = self._ccusage_cmd.split() + ["daily", "--json"]
        proc = await asyncio.create_subprocess_exec(
            *cmd_parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError("ccusage timed out after 30s")

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            raise RuntimeError(
                f"ccusage exited with code {proc.returncode}: {err}"
            )

        return json.loads(stdout.decode())

    def _parse_daily_data(self, data: dict) -> list[ProviderStatus]:
        today_str = datetime.date.today().isoformat()
        totals: dict[str, float] = {}
        today_costs: dict[str, float] = {}

        for entry in data.get("daily", []):
            period = entry.get("period", "")
            for breakdown in entry.get("modelBreakdowns", []):
                model = breakdown.get("modelName", "")
                cost = float(breakdown.get("cost", 0.0))
                provider = _model_to_provider(model)
                totals[provider] = totals.get(provider, 0.0) + cost
                if period == today_str:
                    today_costs[provider] = today_costs.get(provider, 0.0) + cost

        now = time.time()
        statuses: list[ProviderStatus] = []
        seen: set[str] = set()

        # Providers with actual usage (sorted alphabetically for stable output)
        for provider in sorted(totals.keys()):
            seen.add(provider)
            statuses.append(ProviderStatus(
                name=provider,
                budget_usd=self._budgets.get(provider, 0.0),
                spent_total=totals[provider],
                spent_today=today_costs.get(provider, 0.0),
                updated_at=now,
            ))

        # Providers configured in budget but with zero recorded usage
        for provider in sorted(self._budgets.keys()):
            if provider not in seen and self._budgets[provider] > 0:
                statuses.append(ProviderStatus(
                    name=provider,
                    budget_usd=self._budgets[provider],
                    spent_total=0.0,
                    spent_today=0.0,
                    updated_at=now,
                ))

        return statuses

    def _zero_statuses(self) -> list[ProviderStatus]:
        """Return zero-usage entries for all configured budget providers."""
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
        try:
            data = await self._run_ccusage()
        except Exception as exc:
            logger.warning("ccusage unavailable, reporting zero usage: %s", exc)
            return self._zero_statuses()

        statuses = self._parse_daily_data(data)

        for status in statuses:
            await self._store.save_snapshot(
                status.name.lower(), status.spent_total, status.spent_today
            )

        logger.debug("ccusage: %d providers", len(statuses))
        return statuses
