"""
Unix domain socket JSON server for llm-credit-monitor.
Listens on /tmp/llm-monitor.sock (configurable) and serves provider status.

Protocol: newline-delimited JSON — one request line, one response line.

Commands:
  {"cmd": "status"}
    → returns all provider statuses + aggregate totals
"""

import asyncio
import json
import logging
import os
import stat
import time
from typing import Any, Callable, Awaitable

from .store import Store
from .providers.base import ProviderStatus

logger = logging.getLogger(__name__)

StatusGetter = Callable[[], Awaitable[list[ProviderStatus]]]


class SocketServer:
    def __init__(
        self,
        socket_path: str,
        store: Store,
        get_cached_statuses: StatusGetter,
    ) -> None:
        self._socket_path = socket_path
        self._store = store
        self._get_cached_statuses = get_cached_statuses
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)

        self._server = await asyncio.start_unix_server(
            self._handle_client, path=self._socket_path
        )
        # Restrict socket to owner only (security: 600).
        os.chmod(self._socket_path, stat.S_IRUSR | stat.S_IWUSR)
        logger.info("Socket server listening on %s", self._socket_path)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)

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


if __name__ == "__main__":
    import asyncio
    from pathlib import Path

    async def _test() -> None:
        store = Store(Path("/tmp/test-server.db"))
        await store.open()

        dummy_statuses: list[ProviderStatus] = [
            ProviderStatus("Claude", 20.0, 7.6, 0.23, time.time()),
            ProviderStatus("Gemini", 15.0, 6.9, 0.05, time.time()),
            ProviderStatus("OpenAI", 10.0, 5.8, 1.10, time.time()),
        ]

        async def get_statuses() -> list[ProviderStatus]:
            return dummy_statuses

        server = SocketServer("/tmp/test-llm-monitor.sock", store, get_statuses)
        await server.start()
        print("Server started. Test with:")
        print("  echo '{\"cmd\":\"status\"}' | python3 -c \"import socket,sys; ...")
        await asyncio.sleep(30)
        await server.stop()
        await store.close()

    asyncio.run(_test())
