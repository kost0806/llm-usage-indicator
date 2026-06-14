"""
Main asyncio entry point for llm-usage-indicator daemon.

Configuration search order:
  1. ~/.config/llm-usage-indicator/config.toml
  2. ./config.toml (current directory)

Logs: ~/.local/share/llm-usage-indicator/monitor.log (rotating, 1MB x 3 files)
"""

import asyncio
import logging
import logging.handlers
import signal
from pathlib import Path
from typing import Optional

from .config import load_config, Config
from .store import Store
from .server import SocketServer
from .providers.base import ProviderStatus
from .providers.ccusage_p import CcusageProvider


def _setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "monitor.log"
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=1_048_576, backupCount=3
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler, stderr_handler])


logger = logging.getLogger(__name__)


class Daemon:
    def __init__(self) -> None:
        self._cfg: Config = load_config()
        self._store: Store = Store(self._cfg.db_path_expanded)
        self._provider: Optional[CcusageProvider] = None
        self._cached_statuses: list[ProviderStatus] = []
        self._server: Optional[SocketServer] = None
        self._shutdown_event = asyncio.Event()

    async def _poll_all_once(self) -> None:
        assert self._provider is not None
        try:
            statuses = await self._provider.fetch_all_statuses()
            self._cached_statuses = statuses
        except Exception as exc:
            logger.warning("ccusage poll failed: %s", exc)

    async def _get_cached_statuses(self) -> list[ProviderStatus]:
        return list(self._cached_statuses)

    async def _polling_loop(self) -> None:
        interval = self._cfg.general.poll_interval
        logger.info("Polling loop started (interval=%ds)", interval)
        while not self._shutdown_event.is_set():
            await self._poll_all_once()
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(), timeout=float(interval)
                )
            except asyncio.TimeoutError:
                pass

    async def run(self) -> None:
        log_dir = self._cfg.db_path_expanded.parent
        _setup_logging(log_dir)
        logger.info("llm-usage-indicator daemon starting")

        await self._store.open()

        self._provider = CcusageProvider(
            budgets=self._cfg.budgets,
            store=self._store,
            ccusage_cmd=self._cfg.general.ccusage_cmd,
        )

        # Initial poll so status is available immediately.
        await self._poll_all_once()

        self._server = SocketServer(
            socket_path=self._cfg.general.socket_path,
            store=self._store,
            get_cached_statuses=self._get_cached_statuses,
        )
        await self._server.start()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown_event.set)

        try:
            await self._polling_loop()
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        logger.info("Shutting down llm-usage-indicator")
        if self._server:
            await self._server.stop()
        await self._store.close()
        logger.info("Shutdown complete")


def main() -> None:
    daemon = Daemon()
    asyncio.run(daemon.run())


if __name__ == "__main__":
    main()
