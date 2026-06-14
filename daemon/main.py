"""
Main asyncio entry point for llm-credit-monitor daemon.

Configuration search order:
  1. ~/.config/llm-credit-monitor/config.toml
  2. ./config.toml (current directory)

Logs: ~/.local/share/llm-credit-monitor/monitor.log (rotating, 1MB x 3 files)
"""

import asyncio
import logging
import logging.handlers
import os
import signal
import time
from pathlib import Path
from typing import Optional

import aiohttp

from .config import load_config, Config, ProviderConfig
from .store import Store
from .server import SocketServer
from .providers.base import ProviderStatus, AbstractProvider
from .providers.claude import ClaudeProvider
from .providers.gemini import GeminiProvider
from .providers.openai_p import OpenAIProvider


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
        self._session: Optional[aiohttp.ClientSession] = None
        self._providers: list[AbstractProvider] = []
        self._cached_statuses: list[ProviderStatus] = []
        self._server: Optional[SocketServer] = None
        self._shutdown_event = asyncio.Event()

    def _build_providers(self) -> list[AbstractProvider]:
        assert self._session is not None
        providers: list[AbstractProvider] = []

        def _maybe_add(
            provider_cfg: ProviderConfig,
            cls: type,
            name: str,
        ) -> None:
            if not provider_cfg.enabled:
                logger.info("Provider %s is disabled, skipping", name)
                return
            if not provider_cfg.api_key or provider_cfg.api_key.endswith("..."):
                logger.warning("Provider %s has no API key configured, skipping", name)
                return
            providers.append(
                cls(
                    api_key=provider_cfg.api_key,
                    budget_usd=provider_cfg.budget_usd,
                    store=self._store,
                    session=self._session,
                )
            )
            logger.info("Provider %s enabled (budget $%.2f)", name, provider_cfg.budget_usd)

        _maybe_add(self._cfg.claude, ClaudeProvider, "Claude")
        _maybe_add(self._cfg.gemini, GeminiProvider, "Gemini")
        _maybe_add(self._cfg.openai, OpenAIProvider, "OpenAI")
        return providers

    async def _poll_provider(self, provider: AbstractProvider) -> Optional[ProviderStatus]:
        """Poll a single provider; return cached status on failure."""
        try:
            status = await provider.fetch_status()
            logger.debug(
                "%s: remaining=$%.2f today=$%.4f tps=%.1f",
                status.name, status.remaining, status.spent_today, status.last_tps,
            )
            return status
        except Exception as exc:
            logger.warning("Provider poll failed (%s): %s", type(provider).__name__, exc)
            return None

    async def _poll_all_once(self) -> None:
        """Poll all providers in parallel; update cache with successful results."""
        results = await asyncio.gather(
            *[self._poll_provider(p) for p in self._providers],
            return_exceptions=False,
        )
        new_statuses = []
        for i, result in enumerate(results):
            if result is not None:
                new_statuses.append(result)
            elif i < len(self._cached_statuses):
                # Keep stale cache value so status is never empty.
                new_statuses.append(self._cached_statuses[i])
        self._cached_statuses = new_statuses

    async def _get_cached_statuses(self) -> list[ProviderStatus]:
        return list(self._cached_statuses)

    async def _polling_loop(self) -> None:
        interval = self._cfg.general.poll_interval_usage
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
        logger.info("llm-credit-monitor daemon starting")

        await self._store.open()

        self._session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=10),
            headers={"User-Agent": "llm-credit-monitor/1.0"},
        )

        self._providers = self._build_providers()
        if not self._providers:
            logger.warning("No providers configured — daemon running with empty status")

        # Initial poll so status is available immediately.
        if self._providers:
            await self._poll_all_once()

        self._server = SocketServer(
            socket_path=self._cfg.general.socket_path,
            store=self._store,
            get_cached_statuses=self._get_cached_statuses,
        )
        await self._server.start()

        # Register signal handlers for graceful shutdown.
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown_event.set)

        try:
            await self._polling_loop()
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        logger.info("Shutting down llm-credit-monitor")
        if self._server:
            await self._server.stop()
        if self._session:
            await self._session.close()
        await self._store.close()
        logger.info("Shutdown complete")


def main() -> None:
    daemon = Daemon()
    asyncio.run(daemon.run())


if __name__ == "__main__":
    main()
