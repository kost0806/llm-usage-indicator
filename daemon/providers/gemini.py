"""
Google Gemini provider for llm-credit-monitor.

Credit balance:
  Google AI Studio does NOT provide a public credit balance API as of 2024.
  Ref: https://ai.google.dev/gemini-api/docs/quickstart
  Workaround: budget_usd - local SQLite cumulative tracking.

Usage tracking:
  No official usage reporting API for Google AI Studio free/paid tiers.
  Ref: https://ai.google.dev/gemini-api/docs/models
  Workaround: accumulate locally in SQLite.
  If Google Cloud Vertex AI is used instead, billing API is available:
  Ref: https://cloud.google.com/billing/docs/reference/rest

Token pricing (Gemini 1.5 Pro baseline, update as needed):
  Input:  $3.50 per 1M tokens  (>128k context)
  Output: $10.50 per 1M tokens
  Ref: https://ai.google.dev/pricing
"""

import time
import logging
from typing import Optional

import aiohttp

from .base import AbstractProvider, ProviderStatus
from ..store import Store

logger = logging.getLogger(__name__)

# Pricing constants — Gemini 1.5 Pro baseline.
# TODO: Make configurable per model in config.toml.
INPUT_COST_PER_M = 3.50    # USD per 1M input tokens (>128k context window)
OUTPUT_COST_PER_M = 10.50  # USD per 1M output tokens

# NOTE: No official usage endpoint exists for Google AI Studio.
# This URL is a placeholder — will return 404.
# If Google adds a usage API, update here.
USAGE_URL = "https://generativelanguage.googleapis.com/v1beta/usage"


class GeminiProvider(AbstractProvider):
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

    async def _fetch_usage(self) -> Optional[tuple[float, float]]:
        """
        Attempt to fetch usage from Google AI API.
        Returns (input_tokens, output_tokens) or None if unavailable.
        NOTE: No official API exists; this will likely return 404.
        """
        try:
            async with self._session.get(
                USAGE_URL,
                params={"key": self._api_key},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    input_tokens = float(data.get("totalInputTokenCount", 0))
                    output_tokens = float(data.get("totalOutputTokenCount", 0))
                    return input_tokens, output_tokens
                elif resp.status in (401, 403, 404):
                    logger.warning(
                        "WARNING: Gemini usage API not available (HTTP %d) — "
                        "credits will show as '--'. "
                        "Ref: https://ai.google.dev/gemini-api/docs/quickstart",
                        resp.status,
                    )
                    return None
                else:
                    logger.warning("Gemini usage API returned HTTP %d", resp.status)
                    return None
        except Exception as exc:
            logger.warning("Gemini usage fetch failed: %s", exc)
            return None

    def _tokens_to_usd(self, input_tokens: float, output_tokens: float) -> float:
        return (
            input_tokens / 1_000_000 * INPUT_COST_PER_M
            + output_tokens / 1_000_000 * OUTPUT_COST_PER_M
        )

    async def fetch_status(self) -> ProviderStatus:
        if not self._api_key:
            raise ValueError("Gemini API key not configured")

        usage = await self._fetch_usage()
        if usage is not None:
            input_tokens, output_tokens = usage
            spent_total = self._tokens_to_usd(input_tokens, output_tokens)
        else:
            # API unavailable — use last known value from SQLite.
            snap = await self._store.get_latest_snapshot("gemini")
            spent_total = snap["spent_total"] if snap else 0.0

        today_spent = await self._store.get_today_spent("gemini")

        now = time.time()
        status = ProviderStatus(
            name="Gemini",
            budget_usd=self._budget_usd,
            spent_total=spent_total,
            spent_today=today_spent,
            updated_at=now,
        )

        await self._store.save_snapshot("gemini", spent_total, today_spent)
        self._last_status = status
        return status


if __name__ == "__main__":
    import asyncio
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent.parent))
    from daemon.store import Store
    from pathlib import Path

    async def _test() -> None:
        store = Store(Path("/tmp/test-gemini.db"))
        await store.open()
        async with aiohttp.ClientSession() as session:
            provider = GeminiProvider(
                api_key="AIza-test",
                budget_usd=15.0,
                store=store,
                session=session,
            )
            try:
                status = await provider.fetch_status()
                print(f"Gemini status: remaining=${status.remaining:.2f}, today=${status.spent_today:.4f}")
            except Exception as e:
                print(f"Error (expected with test key): {e}")
        await store.close()

    asyncio.run(_test())
