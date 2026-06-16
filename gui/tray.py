"""
Cross-platform system tray indicator for llm-usage-indicator.

Uses pystray (Windows: Win32 NotifyIcon, Linux: GTK StatusIcon,
macOS: Cocoa) + Pillow for icon rendering.

Required:
  pip install pystray Pillow
"""

import json
import logging
import math
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

# Brand colors and emoji per provider
PROVIDER_BRAND: dict[str, dict] = {
    "Claude":  {"bg": (209, 90,  42),  "ring": (232, 130, 80)},   # Anthropic orange
    "OpenAI":  {"bg": (16,  163, 127), "ring": (80,  200, 160)},  # OpenAI green
    "Gemini":  {"bg": (66,  133, 244), "ring": (130, 170, 255)},  # Google blue
    "Copilot": {"bg": (0,   120, 212), "ring": (80,  170, 240)},  # Microsoft blue
    "Other":   {"bg": (100, 100, 100), "ring": (160, 160, 160)},
}

PROVIDER_EMOJI: dict[str, str] = {
    "Claude":  "🟠",
    "OpenAI":  "🟢",
    "Gemini":  "🔵",
    "Copilot": "🟦",
    "Other":   "⚪",
}


def _logo_claude(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, color: tuple) -> None:
    """Anthropic asterisk: 6 thick lines radiating from center."""
    w = max(2, r // 4)
    for i in range(6):
        angle = math.radians(i * 60 - 90)
        x1 = cx + (r * 0.28) * math.cos(angle)
        y1 = cy + (r * 0.28) * math.sin(angle)
        x2 = cx + r * math.cos(angle)
        y2 = cy + r * math.sin(angle)
        draw.line([(x1, y1), (x2, y2)], fill=color, width=w)


def _logo_openai(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, color: tuple) -> None:
    """OpenAI gear-ring: outer ring + 6 small nodes + center dot."""
    w = max(2, r // 5)
    draw.arc([cx - r, cy - r, cx + r, cy + r], 0, 360, fill=color, width=w)
    nr = max(2, r // 6)
    for i in range(6):
        angle = math.radians(i * 60)
        mx = int(cx + r * math.cos(angle))
        my = int(cy + r * math.sin(angle))
        draw.ellipse([mx - nr, my - nr, mx + nr, my + nr], fill=color)
    cr = max(2, r // 5)
    draw.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=color)


def _logo_gemini(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, color: tuple) -> None:
    """Gemini 4-pointed star."""
    points = []
    for i in range(8):
        angle = math.radians(i * 45 - 90)
        radius = r if i % 2 == 0 else r * 0.28
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    draw.polygon(points, fill=color)


def _logo_copilot(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, _color: tuple) -> None:
    """Microsoft Copilot: 2×2 colored squares."""
    colors = [(243, 59, 86), (255, 185, 0), (0, 183, 154), (0, 120, 212)]
    s = max(3, r // 2 - 1)
    gap = max(1, r // 8)
    positions = [
        (cx - s - gap, cy - s - gap),
        (cx + gap,     cy - s - gap),
        (cx - s - gap, cy + gap),
        (cx + gap,     cy + gap),
    ]
    for (px, py), c in zip(positions, colors):
        draw.rounded_rectangle([px, py, px + s, py + s], radius=max(1, s // 4), fill=c)


_LOGO_FN = {
    "Claude":  _logo_claude,
    "OpenAI":  _logo_openai,
    "Gemini":  _logo_gemini,
    "Copilot": _logo_copilot,
}


def _single_provider_icon(name: str, warning: bool, error: bool) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    brand = PROVIDER_BRAND.get(name, PROVIDER_BRAND["Other"])

    if error:
        ring = (180, 60, 60)
    elif warning:
        ring = (220, 160, 30)
    else:
        ring = brand["ring"]

    # Filled circle background
    draw.ellipse([3, 3, 61, 61], fill=brand["bg"] + (255,))
    # Status ring
    draw.arc([1, 1, 63, 63], 0, 360, fill=ring + (255,), width=3)

    logo_fn = _LOGO_FN.get(name)
    if logo_fn:
        logo_fn(draw, 32, 32, 19, (255, 255, 255))
    else:
        # Generic: circle outline
        draw.arc([13, 13, 51, 51], 0, 360, fill=(255, 255, 255), width=3)

    return img


def _small_provider_badge(name: str, size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    brand = PROVIDER_BRAND.get(name, PROVIDER_BRAND["Other"])
    cx = cy = size // 2
    r = cx - 2
    draw.ellipse([2, 2, size - 3, size - 3], fill=brand["bg"] + (255,))
    logo_fn = _LOGO_FN.get(name)
    if logo_fn:
        logo_fn(draw, cx, cy, max(3, r - 3), (255, 255, 255))
    return img


def _make_robot_icon(warning: bool = False, error: bool = False) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if error:
        body = (180, 60, 60, 255)
    elif warning:
        body = (200, 140, 40, 255)
    else:
        body = (60, 160, 90, 255)
    draw.rounded_rectangle([6, 8, 58, 52], radius=8, fill=body)
    draw.ellipse([16, 18, 28, 30], fill=(220, 240, 220))
    draw.ellipse([36, 18, 48, 30], fill=(220, 240, 220))
    draw.ellipse([19, 21, 25, 27], fill=(20, 20, 20))
    draw.ellipse([39, 21, 45, 27], fill=(20, 20, 20))
    draw.arc([18, 34, 46, 50], start=10, end=170, fill=(220, 240, 220), width=3)
    draw.line([32, 8, 32, 2], fill=body, width=3)
    draw.ellipse([29, 0, 35, 6], fill=body)
    return img


def _make_icon(
    warning: bool = False,
    error: bool = False,
    providers: list[dict] | None = None,
) -> Image.Image:
    budgeted = [p for p in (providers or []) if p.get("budget_usd", 0) > 0]

    if error or not budgeted:
        return _make_robot_icon(warning=warning, error=error)

    if len(budgeted) == 1:
        return _single_provider_icon(budgeted[0]["name"], warning, error)

    # Multiple providers: tile small badges
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    shown = budgeted[:4]
    count = len(shown)

    if count == 2:
        badge_size, positions = 28, [(2, 18), (34, 18)]
    elif count == 3:
        badge_size, positions = 20, [(2, 22), (22, 2), (42, 22)]
    else:
        badge_size, positions = 28, [(2, 2), (34, 2), (2, 34), (34, 34)]

    for p, pos in zip(shown, positions):
        badge = _small_provider_badge(p["name"], badge_size)
        img.paste(badge, pos, badge)

    return img


# ── Menu construction ─────────────────────────────────────────────────────────

def _build_menu(data: dict | None, on_refresh, on_settings, on_quit) -> pystray.Menu:
    items: list = []
    providers = (data or {}).get("providers", [])

    budgeted = [p for p in providers if p["budget_usd"] > 0]

    if budgeted:
        for p in budgeted:
            label = (
                f"{p['name']}: ↑${p['spent_today']:.4f} / ${p['remaining']:.2f}"
                f" ({p['remaining_pct']:.0f}%)"
            )
            items.append(pystray.MenuItem(label, None, enabled=False))

        items.append(pystray.Menu.SEPARATOR)
        total_r = sum(p["remaining"] for p in budgeted)
        total_t = sum(p["spent_today"] for p in budgeted)
        items.append(pystray.MenuItem(
            f"Total: ↑${total_t:.4f} / ${total_r:.2f} remaining",
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
    budgeted = [p for p in providers if p["budget_usd"] > 0]
    if not budgeted:
        return "LLM Usage Indicator — daemon not running"
    parts = [
        f"{PROVIDER_EMOJI.get(p['name'], '⚙')} {p['name']}: ↑${p['spent_today']:.2f}/${p['remaining']:.2f}"
        for p in budgeted
    ]
    return "\n".join(parts)


# ── Settings launcher ─────────────────────────────────────────────────────────

def _open_settings() -> None:
    import os
    import subprocess

    def _notify_error(msg: str) -> None:
        subprocess.run(
            ["notify-send", "-a", "LLM Usage Indicator", "Settings error", msg],
            capture_output=True,
        )

    if sys.platform == "win32":
        exe_dir = Path(sys.executable).parent
        settings_exe = exe_dir / "llm-monitor-settings.exe"
        if settings_exe.exists():
            subprocess.Popen([str(settings_exe)])
            return
    else:
        settings_bin = Path.home() / ".local" / "bin" / "llm-usage-indicator-settings"
        if settings_bin.exists():
            proc = subprocess.Popen(
                [str(settings_bin)], stderr=subprocess.PIPE
            )
            # Give the window ~1 s to appear; if the process already died, surface the error.
            try:
                proc.wait(timeout=1.0)
                err = (proc.stderr.read() if proc.stderr else b"").decode().strip()
                msg = err or f"Settings exited immediately (code {proc.returncode})."
                logger.warning("Settings failed: %s", msg)
                _notify_error(msg)
            except subprocess.TimeoutExpired:
                pass  # still running — normal
            return

    # Fallback: run settings module directly
    lib = str(Path.home() / ".local" / "lib")
    env = {**os.environ, "PYTHONPATH": lib}
    subprocess.Popen(
        [sys.executable, "-m", "llm_usage_indicator.settings_gui"], env=env
    )


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

        self._icon.icon = _make_icon(warning=warning, error=error, providers=providers)
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
