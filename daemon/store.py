"""
SQLite persistence layer for llm-credit-monitor.
Stores usage snapshots and TPS events using aiosqlite for non-blocking I/O.
"""

import time
from pathlib import Path

import aiosqlite

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    provider    TEXT NOT NULL,
    spent_total REAL NOT NULL,
    spent_today REAL NOT NULL,
    last_tps    REAL NOT NULL DEFAULT 0,
    recorded_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tps_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    provider    TEXT NOT NULL,
    tps         REAL NOT NULL,
    token_count INTEGER NOT NULL,
    recorded_at INTEGER NOT NULL
);
"""

PRUNE_DAYS = 7


class Store:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA_SQL)
        await self._db.commit()
        await self._prune_old_snapshots()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def _prune_old_snapshots(self) -> None:
        cutoff = int(time.time()) - PRUNE_DAYS * 86400
        assert self._db is not None
        await self._db.execute(
            "DELETE FROM snapshots WHERE recorded_at < ?", (cutoff,)
        )
        await self._db.commit()

    async def save_snapshot(
        self,
        provider: str,
        spent_total: float,
        spent_today: float,
        last_tps: float,
    ) -> None:
        assert self._db is not None
        now = int(time.time())
        await self._db.execute(
            """INSERT INTO snapshots (provider, spent_total, spent_today, last_tps, recorded_at)
               VALUES (?, ?, ?, ?, ?)""",
            (provider, spent_total, spent_today, last_tps, now),
        )
        await self._db.commit()

    async def get_today_spent(self, provider: str) -> float:
        """Return usage delta since midnight today (00:00 local time)."""
        assert self._db is not None
        midnight = _today_midnight_ts()

        # First snapshot at or after midnight
        async with self._db.execute(
            """SELECT spent_total FROM snapshots
               WHERE provider = ? AND recorded_at >= ?
               ORDER BY recorded_at ASC LIMIT 1""",
            (provider, midnight),
        ) as cur:
            first_row = await cur.fetchone()

        # Latest snapshot
        async with self._db.execute(
            """SELECT spent_total FROM snapshots
               WHERE provider = ?
               ORDER BY recorded_at DESC LIMIT 1""",
            (provider,),
        ) as cur:
            last_row = await cur.fetchone()

        if first_row is None or last_row is None:
            return 0.0

        delta = float(last_row["spent_total"]) - float(first_row["spent_total"])
        return max(0.0, delta)

    async def record_tps_event(
        self, provider: str, tps: float, token_count: int
    ) -> None:
        assert self._db is not None
        now = int(time.time())
        await self._db.execute(
            """INSERT INTO tps_events (provider, tps, token_count, recorded_at)
               VALUES (?, ?, ?, ?)""",
            (provider, tps, token_count, now),
        )
        await self._db.commit()

    async def get_last_tps(self, provider: str) -> float:
        """Return average TPS from the most recent 5 events."""
        assert self._db is not None
        async with self._db.execute(
            """SELECT tps FROM tps_events
               WHERE provider = ?
               ORDER BY recorded_at DESC LIMIT 5""",
            (provider,),
        ) as cur:
            rows = await cur.fetchall()

        if not rows:
            return 0.0
        return sum(float(r["tps"]) for r in rows) / len(rows)

    async def get_latest_snapshot(self, provider: str) -> dict | None:
        """Return the most recent snapshot for a provider."""
        assert self._db is not None
        async with self._db.execute(
            """SELECT * FROM snapshots WHERE provider = ?
               ORDER BY recorded_at DESC LIMIT 1""",
            (provider,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return dict(row)


def _today_midnight_ts() -> int:
    import datetime
    today = datetime.date.today()
    midnight = datetime.datetime(today.year, today.month, today.day)
    return int(midnight.timestamp())


if __name__ == "__main__":
    import asyncio

    async def _test() -> None:
        store = Store(Path("/tmp/test-llm-monitor.db"))
        await store.open()
        await store.save_snapshot("claude", 5.0, 0.5, 42.0)
        await store.record_tps_event("claude", 42.0, 820)
        today = await store.get_today_spent("claude")
        tps = await store.get_last_tps("claude")
        snap = await store.get_latest_snapshot("claude")
        print(f"Today spent: ${today:.4f}")
        print(f"Last TPS: {tps:.1f}")
        print(f"Latest snapshot: {snap}")
        await store.close()

    asyncio.run(_test())
