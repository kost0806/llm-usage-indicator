"""
TCP JSON server for llm-usage-indicator.
Listens on 127.0.0.1:<port> (default 37891) and serves provider status.

Protocol: newline-delimited JSON — one request line, one response line.

Commands:
  {"cmd": "status"}
    → returns all provider statuses + aggregate totals
"""

import asyncio
import json
import logging
import time
from typing import Any, Callable, Awaitable

from .store import Store
from .providers.base import ProviderStatus

logger = logging.getLogger(__name__)

StatusGetter = Callable[[], Awaitable[list[ProviderStatus]]]


class SocketServer:
    def __init__(
        self,
        host: str,
        port: int,
        store: Store,
        get_cached_statuses: StatusGetter,
    ) -> None:
        self._host = host
        self._port = port
        self._store = store
        self._get_cached_statuses = get_cached_statuses
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, host=self._host, port=self._port
        )
        logger.info("TCP server listening on %s:%d", self._host, self._port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not line:
                return
            request = json.loads(line.decode().strip())
            response = await self._dispatch(request)
            writer.write((json.dumps(response) + "\n").encode())
            await writer.drain()
        except asyncio.TimeoutError:
            logger.warning("Client connection timed out")
        except json.JSONDecodeError as exc:
            error_resp = {"error": f"invalid JSON: {exc}"}
            writer.write((json.dumps(error_resp) + "\n").encode())
            await writer.drain()
        except Exception as exc:
            logger.exception("Error handling client: %s", exc)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _dispatch(self, request: dict) -> dict:
        cmd = request.get("cmd")
        if cmd == "status":
            return await self._handle_status()
        return {"error": f"unknown command: {cmd}"}

    async def _handle_status(self) -> dict[str, Any]:
        statuses = await self._get_cached_statuses()
        providers_out = []
        total_remaining = 0.0
        total_spent_today = 0.0

        for s in statuses:
            providers_out.append({
                "name": s.name,
                "budget_usd": round(s.budget_usd, 2),
                "spent_total": round(s.spent_total, 4),
                "spent_today": round(s.spent_today, 4),
                "remaining": round(s.remaining, 2),
                "remaining_pct": round(s.remaining_pct, 1),
                "updated_at": int(s.updated_at),
            })
            total_remaining += s.remaining
            total_spent_today += s.spent_today

        return {
            "providers": providers_out,
            "total_remaining": round(total_remaining, 2),
            "total_spent_today": round(total_spent_today, 4),
            "server_time": int(time.time()),
        }
