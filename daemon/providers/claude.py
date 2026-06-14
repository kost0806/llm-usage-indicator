"""
Anthropic Claude provider for llm-credit-monitor.

Credit balance:
  Anthropic does NOT provide a public credit balance API as of 2024.
  Ref: https://docs.anthropic.com/en/api/getting-started
  Workaround: Track cumulative usage locally in SQLite.
  If/when Anthropic adds a usage endpoint, update USAGE_URL below.

Usage tracking (unofficial, may change):
  GET https://api.anthropic.com/v1/usage  — NOT officially documented.
  If this returns 404/403, we fall back to local SQLite-only tracking.
  Ref: https://docs.anthropic.com/en/api/messages (official messages API)

Token pricing (Claude Sonnet 3.5 as baseline, update as needed):
  Input:  $3.00 per 1M tokens
  Output: $15.00 per 1M tokens
  Ref: https://www.anthropic.com/pricing
"""

import time
import logging
from typing import Optional

import aiohttp

from .base import AbstractProvider, ProviderStatus
from ..store import Store

logger = logging.getLogger(__name__)

# Pricing constants — Claude Sonnet 3.5 baseline.
# TODO: Make these configurable per model in config.toml.
INPUT_COST_PER_M = 3.00    # USD per 1M input tokens
OUTPUT_COST_PER_M = 15.00  # USD per 1M output tokens

# NOTE: This endpoint is not officially documented. It may return 404/403.
# If Anthropic publishes an official usage API, update this URL.
USAGE_URL = "https://api.anthropic.com/v1/usage"
ANTHROPIC_VERSION = "2023-06-01"


class ClaudeProvider(AbstractProvider):
    def __init__(
        self,
        api_key: str,
        budget_usd: float,
        store: Store,
        session: aiohttp.ClientSession,
    ) -> None:
        self._api_key = api_key
        self._budget_usd = budget_usd
        self._store = store
        self._session = session
        self._last_status: Optional[ProviderStatus] = None

    @property
    def _headers(self) -> dict:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        }

    async def _fetch_usage(self) -> Optional[tuple[float, float]]:
        """
        Attempt to fetch cumulative token usage from Anthropic API.
        Returns (input_tokens, output_tokens) or None if API unavailable.
        NOTE: This endpoint is unofficial and may not exist.
        """
        try:
            async with self._session.get(
                USAGE_URL,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    input_tokens = float(data.get("total_input_tokens", 0))
                    output_tokens = float(data.get("total_output_tokens", 0))
                    return input_tokens, output_tokens
                elif resp.status in (401, 403, 404):
                    logger.warning(
                        "WARNING: Claude usage API not available (HTTP %d) — "
                        "credits will show as '--'. "
                        "Ref: https://docs.anthropic.com/en/api/getting-started",
                        resp.status,
                    )
                    return None
                else:
                    logger.warning("Claude usage API returned HTTP %d", resp.status)
                    return None
        except Exception as exc:
            logger.warning("Claude usage fetch failed: %s", exc)
            return None

    def _tokens_to_usd(self, input_tokens: float, output_tokens: float) -> float:
        return (
            input_tokens / 1_000_000 * INPUT_COST_PER_M
            + output_tokens / 1_000_000 * OUTPUT_COST_PER_M
        )

    async def fetch_status(self) -> ProviderStatus:
        if not self._api_key:
            raise ValueError("Claude API key not configured")

        usage = await self._fetch_usage()
        if usage is not None:
            input_tokens, output_tokens = usage
            spent_total = self._tokens_to_usd(input_tokens, output_tokens)
        else:
            # API unavailable — use last known value from SQLite.
            snap = await self._store.get_latest_snapshot("claude")
            spent_total = snap["spent_total"] if snap else 0.0

        today_spent = await self._store.get_today_spent("claude")

        now = time.time()
        status = ProviderStatus(
            name="Claude",
            budget_usd=self._budget_usd,
            spent_total=spent_total,
            spent_today=today_spent,
            updated_at=now,
        )

        await self._store.save_snapshot("claude", spent_total, today_spent)
        self._last_status = status
        return status


if __name__ == "__main__":
    import asyncio
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent.parent))
    from daemon.store import Store
    from pathlib import Path

    async def _test() -> None:
        store = Store(Path("/tmp/test-claude.db"))
        await store.open()
        async with aiohttp.ClientSession() as session:
            provider = ClaudeProvider(
                api_key="sk-ant-test",
                budget_usd=20.0,
                store=store,
                session=session,
            )
            try:
                status = await provider.fetch_status()
                print(f"Claude status: remaining=${status.remaining:.2f}, today=${status.spent_today:.4f}")
            except Exception as e:
                print(f"Error (expected with test key): {e}")
        await store.close()

    asyncio.run(_test())
