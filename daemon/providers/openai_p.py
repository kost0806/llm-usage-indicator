"""
OpenAI provider for llm-credit-monitor.

Credit balance:
  GET https://api.openai.com/v1/dashboard/billing/credit_grants
  Docs: https://platform.openai.com/docs/api-reference/usage
  NOTE: This endpoint may require an org-level API key. If unavailable,
        falls back to budget_usd - local cumulative tracking.

Daily usage:
  GET https://api.openai.com/v1/usage?date=YYYY-MM-DD
  Docs: https://platform.openai.com/docs/api-reference/usage
  NOTE: This is an undocumented/legacy endpoint; may return 404 for new orgs.

TPS:
  Estimated from last completion_tokens / latency stored in SQLite.
  External push via socket `push_tps` command is also supported.
"""

import time
import logging
from typing import Optional

import aiohttp

from .base import AbstractProvider, ProviderStatus
from ..store import Store

logger = logging.getLogger(__name__)

CREDIT_GRANTS_URL = "https://api.openai.com/v1/dashboard/billing/credit_grants"
USAGE_URL = "https://api.openai.com/v1/usage"


class OpenAIProvider(AbstractProvider):
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
        return {"Authorization": f"Bearer {self._api_key}"}

    async def _fetch_credit_grants(self) -> tuple[float, float]:
        """
        Returns (total_available, total_used).
        Falls back to (0.0, 0.0) on API failure.
        Docs: https://platform.openai.com/docs/api-reference/usage
        """
        try:
            async with self._session.get(
                CREDIT_GRANTS_URL, headers=self._headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    available = float(data.get("total_available", 0.0))
                    used = float(data.get("total_used", 0.0))
                    return available, used
                elif resp.status in (401, 403, 404):
                    logger.warning(
                        "OpenAI credit grants API not available (HTTP %d) — "
                        "falling back to budget tracking. "
                        "Ref: https://platform.openai.com/docs/api-reference/usage",
                        resp.status,
                    )
                    return 0.0, 0.0
                else:
                    logger.warning("OpenAI credit grants API returned HTTP %d", resp.status)
                    return 0.0, 0.0
        except Exception as exc:
            logger.warning("OpenAI credit grants fetch failed: %s", exc)
            return 0.0, 0.0

    async def _fetch_today_usage(self) -> float:
        """
        Returns today's usage in USD.
        Uses GET /v1/usage?date=YYYY-MM-DD (undocumented legacy endpoint).
        Falls back to SQLite delta on failure.
        """
        import datetime
        date_str = datetime.date.today().isoformat()
        try:
            async with self._session.get(
                USAGE_URL,
                headers=self._headers,
                params={"date": date_str},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Response contains a list of model usage; sum costs.
                    total_cost = 0.0
                    for item in data.get("data", []):
                        # Fields: n_context_tokens_total, n_generated_tokens_total, etc.
                        # Cost fields vary; attempt to use snapshot_id or cost if present.
                        total_cost += float(item.get("cost", 0.0))
                    return total_cost
                elif resp.status in (401, 403, 404):
                    logger.warning(
                        "OpenAI daily usage API not available (HTTP %d) — "
                        "falling back to SQLite delta",
                        resp.status,
                    )
                    return await self._store.get_today_spent("openai")
                else:
                    logger.warning("OpenAI usage API returned HTTP %d", resp.status)
                    return await self._store.get_today_spent("openai")
        except Exception as exc:
            logger.warning("OpenAI today usage fetch failed: %s", exc)
            return await self._store.get_today_spent("openai")

    async def fetch_status(self) -> ProviderStatus:
        if not self._api_key:
            raise ValueError("OpenAI API key not configured")

        available, spent_total = await self._fetch_credit_grants()
        today_spent = await self._fetch_today_usage()
        last_tps = await self._store.get_last_tps("openai")

        # If credit grants API worked, use its values directly.
        # Otherwise, use budget_usd - local cumulative tracking.
        if spent_total == 0.0 and available == 0.0:
            # Fallback: use budget minus latest snapshot spent_total from DB.
            snap = await self._store.get_latest_snapshot("openai")
            spent_total = snap["spent_total"] if snap else 0.0
            budget = self._budget_usd
        else:
            # API returned real data; treat total_granted as budget.
            total_granted = available + spent_total
            budget = total_granted if total_granted > 0 else self._budget_usd

        now = time.time()
        status = ProviderStatus(
            name="OpenAI",
            budget_usd=budget,
            spent_total=spent_total,
            spent_today=today_spent,
            last_tps=last_tps,
            updated_at=now,
        )

        await self._store.save_snapshot("openai", spent_total, today_spent, last_tps)
        self._last_status = status
        return status


if __name__ == "__main__":
    import asyncio
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent.parent))
    from daemon.store import Store
    from pathlib import Path

    async def _test() -> None:
        store = Store(Path("/tmp/test-openai.db"))
        await store.open()
        async with aiohttp.ClientSession() as session:
            provider = OpenAIProvider(
                api_key="sk-test",
                budget_usd=10.0,
                store=store,
                session=session,
            )
            try:
                status = await provider.fetch_status()
                print(f"OpenAI status: remaining=${status.remaining:.2f}, today=${status.spent_today:.4f}")
            except Exception as e:
                print(f"Error (expected with test key): {e}")
        await store.close()

    asyncio.run(_test())
