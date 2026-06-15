"""
Cross-platform system tray indicator for llm-usage-indicator.

Uses pystray (Windows: Win32 NotifyIcon, Linux: GTK StatusIcon,
macOS: Cocoa) + Pillow for icon rendering.

Required:
  pip install pystray Pillow
"""

import json
import logging
import signal
import socket
import sys
import threading
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

IPC_HOST = "127.0.0.1"
IPC_PORT = 37891
REFRESH_INTERVAL_S = 30.0
SOCKET_TIMEOUT_S = 3

logger = logging.getLogger(__name__)


# ── Daemon communication ──────────────────────────────────────────────────────

def _fetch_status() -> dict | None:
    try:
        with socket.create_connection((IPC_HOST, IPC_PORT), timeout=SOCKET_TIMEOUT_S) as s:
            s.sendall(b'{"cmd":"status"}\n')
            buf = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if b"\n" in buf:
                    break
        return json.loads(buf.strip())
    except Exception as exc:
        logger.debug("Daemon unreachable: %s", exc)
        return None


# ── Icon rendering ────────────────────────────────────────────────────────────

def _make_icon(warning: bool = False, error: bool = False) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if error:
        body = (180, 60, 60, 255)
    elif warning:
        body = (200, 140, 40, 255)
    else:
        body = (60, 160, 90, 255)
    # Robot head
    draw.rounded_rectangle([6, 8, 58, 52], radius=8, fill=body)
    # Eyes
    draw.ellipse([16, 18, 28, 30], fill=(220, 240, 220))
    draw.ellipse([36, 18, 48, 30], fill=(220, 240, 220))
    draw.ellipse([19, 21, 25, 27], fill=(20, 20, 20))
    draw.ellipse([39, 21, 45, 27], fill=(20, 20, 20))
    # Mouth
    draw.arc([18, 34, 46, 50], start=10, end=170, fill=(220, 240, 220), width=3)
    # Antenna
    draw.line([32, 8, 32, 2], fill=body, width=3)
    draw.ellipse([29, 0, 35, 6], fill=body)
    return img


# ── Menu construction ─────────────────────────────────────────────────────────

def _build_menu(data: dict | None, on_refresh, on_settings, on_quit) -> pystray.Menu:
    items: list = []
    providers = (data or {}).get("providers", [])

    if providers:
        for p in providers:
            if p["budget_usd"] > 0:
                label = (
                    f"{p['name']}: ${p['remaining']:.2f} remaining"
                    f" ({p['remaining_pct']:.0f}%)  ↑${p['spent_today']:.4f} today"
                )
            else:
                label = f"{p['name']}: ↑${p['spent_today']:.4f} today (no budget)"
            items.append(pystray.MenuItem(label, None, enabled=False))

        items.append(pystray.Menu.SEPARATOR)
        total_r = data.get("total_remaining", 0.0)
        total_t = data.get("total_spent_today", 0.0)
        items.append(pystray.MenuItem(
            f"Total: ${total_r:.2f} remaining  ↑${total_t:.4f} today",
            None, enabled=False,
        ))
    else:
        items.append(pystray.MenuItem("Daemon not running", None, enabled=False))

    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem("Settings…", on_settings))
    items.append(pystray.MenuItem("Refresh now", on_refresh))
    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem("Quit", on_quit))

    return pystray.Menu(*items)


def _icon_title(providers: list[dict]) -> str:
    if not providers:
        return "LLM Usage Indicator — daemon not running"
    parts = []
    for p in providers:
        initial = p["name"][0]
        if p["budget_usd"] > 0:
            parts.append(f"{initial}:${p['remaining']:.2f}")
        else:
            parts.append(f"{initial}:↑${p['spent_today']:.2f}")
    return "\U0001f916 " + "  ".join(parts)


# ── Settings launcher ─────────────────────────────────────────────────────────

def _open_settings() -> None:
    import subprocess
    if sys.platform == "win32":
        exe_dir = Path(sys.executable).parent
        settings_exe = exe_dir / "llm-monitor-settings.exe"
        if settings_exe.exists():
            subprocess.Popen([str(settings_exe)])
            return
    else:
        settings_bin = Path.home() / ".local" / "bin" / "llm-usage-indicator-settings"
        if settings_bin.exists():
            subprocess.Popen([str(settings_bin)])
            return
    # Fallback: run settings module directly
    subprocess.Popen([sys.executable, "-m", "gui.settings"])


# ── Tray application ──────────────────────────────────────────────────────────

class TrayApp:
    def __init__(self) -> None:
        self._data: dict | None = None
        self._timer: threading.Timer | None = None
        self._icon = pystray.Icon(
            "llm-usage-indicator",
            _make_icon(),
            "LLM Usage Indicator",
            menu=self._make_menu(),
        )

    def _make_menu(self) -> pystray.Menu:
        return _build_menu(
            self._data,
            on_refresh=lambda: self._refresh(),
            on_settings=lambda: _open_settings(),
            on_quit=lambda: self._quit(),
        )

    def _refresh(self) -> None:
        threading.Thread(target=self._fetch_and_update, daemon=True).start()

    def _fetch_and_update(self) -> None:
        data = _fetch_status()
        self._data = data
        providers = (data or {}).get("providers", [])

        warning = any(
            p["remaining_pct"] < 20 and p["budget_usd"] > 0
            for p in providers
        )
        error = data is None

        self._icon.icon = _make_icon(warning=warning, error=error)
        self._icon.title = _icon_title(providers)
        self._icon.menu = self._make_menu()

        self._timer = threading.Timer(REFRESH_INTERVAL_S, self._refresh)
        self._timer.daemon = True
        self._timer.start()

    def _quit(self) -> None:
        if self._timer:
            self._timer.cancel()
        self._icon.stop()

    def run(self) -> None:
        self._refresh()
        self._icon.run()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = TrayApp()
    app.run()


if __name__ == "__main__":
    main()
