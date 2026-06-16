"""
Cross-platform system tray indicator for llm-usage-indicator.

Tray icon: pystray (Win32 / GTK / Cocoa) + Pillow.
Usage panel: custom Material Design 3 tkinter Toplevel window.

Architecture:
  - Main thread  : tkinter event loop (hosts the MD3 popup)
  - Daemon thread: pystray.Icon.run()  (Linux/Windows compatible)
"""

import json
import logging
import math
import signal
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

try:
    import tkinter as tk
except ImportError:
    print("ERROR: tkinter not installed.  sudo apt install python3-tk", file=sys.stderr)
    sys.exit(1)

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


# ── Tray icon rendering ───────────────────────────────────────────────────────

PROVIDER_BRAND: dict[str, dict] = {
    "Claude":  {"bg": (209, 90,  42),  "ring": (232, 130, 80)},
    "OpenAI":  {"bg": (16,  163, 127), "ring": (80,  200, 160)},
    "Gemini":  {"bg": (66,  133, 244), "ring": (130, 170, 255)},
    "Other":   {"bg": (100, 100, 100), "ring": (160, 160, 160)},
}

PROVIDER_EMOJI: dict[str, str] = {
    "Claude":  "🟠",
    "OpenAI":  "🟢",
    "Gemini":  "🔵",
    "Other":   "⚪",
}


def _logo_claude(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, color: tuple) -> None:
    w = max(2, r // 4)
    for i in range(6):
        angle = math.radians(i * 60 - 90)
        x1 = cx + (r * 0.28) * math.cos(angle)
        y1 = cy + (r * 0.28) * math.sin(angle)
        x2 = cx + r * math.cos(angle)
        y2 = cy + r * math.sin(angle)
        draw.line([(x1, y1), (x2, y2)], fill=color, width=w)


def _logo_openai(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, color: tuple) -> None:
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
    points = []
    for i in range(8):
        angle = math.radians(i * 45 - 90)
        radius = r if i % 2 == 0 else r * 0.28
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    draw.polygon(points, fill=color)


_LOGO_FN = {
    "Claude":  _logo_claude,
    "OpenAI":  _logo_openai,
    "Gemini":  _logo_gemini,
}


def _single_provider_icon(name: str, warning: bool, error: bool) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    brand = PROVIDER_BRAND.get(name, PROVIDER_BRAND["Other"])
    ring = (180, 60, 60) if error else (220, 160, 30) if warning else brand["ring"]
    draw.ellipse([3, 3, 61, 61], fill=brand["bg"] + (255,))
    draw.arc([1, 1, 63, 63], 0, 360, fill=ring + (255,), width=3)
    logo_fn = _LOGO_FN.get(name)
    if logo_fn:
        logo_fn(draw, 32, 32, 19, (255, 255, 255))
    else:
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
    body = (180, 60, 60, 255) if error else (200, 140, 40, 255) if warning else (60, 160, 90, 255)
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


def _icon_title(providers: list[dict]) -> str:
    budgeted = [p for p in providers if p["budget_usd"] > 0]
    if not budgeted:
        return "LLM Usage Indicator — daemon not running"
    parts = [
        f"{PROVIDER_EMOJI.get(p['name'], '⚙')} {p['name']}: ↑${p['spent_today']:.2f}/${p['remaining']:.2f}"
        for p in budgeted
    ]
    return "\n".join(parts)


# ── Material Design 3 popup panel ─────────────────────────────────────────────
#
# MD3 Light color scheme
_C_BG          = "#FFFBFE"   # Surface
_C_CONT        = "#F3EDF7"   # Surface Container
_C_CONT_HIGH   = "#ECE6F0"   # Surface Container High
_C_OUTLINE     = "#79747E"   # Outline
_C_OUTLINE_VAR = "#CAC4D0"   # Outline Variant
_C_PRIMARY     = "#6750A4"   # Primary
_C_PRIM_CONT   = "#EADDFF"   # Primary Container
_C_ON_PRIM_CNT = "#21005D"   # On Primary Container
_C_ON_SURF     = "#1C1B1F"   # On Surface
_C_ON_SURF_VAR = "#49454F"   # On Surface Variant
_C_ERROR       = "#B3261E"   # Error
_C_ERR_CONT    = "#F9DEDC"   # Error Container

# Provider brand colors  (fg, card-bg)
_BRAND: dict[str, tuple[str, str]] = {
    "Claude": ("#D15A2A", "#FFF0E8"),
    "OpenAI": ("#10A37F", "#E8F5F0"),
    "Gemini": ("#4285F4", "#E8F0FE"),
    "Other":  (_C_OUTLINE, _C_CONT),
}

_FF = (
    "Segoe UI"    if sys.platform == "win32"  else
    "SF Pro Text" if sys.platform == "darwin" else
    "Sans"
)
_F      = (_FF, 10)
_F_SM   = (_FF, 9)
_F_BOLD = (_FF, 10, "bold")
_F_H    = (_FF, 13, "bold")

POPUP_W = 300   # fixed panel width


class TrayPopup:
    """Material Design 3 floating usage panel."""

    def __init__(self, master: tk.Tk, on_settings, on_quit) -> None:
        self._on_settings = on_settings
        self._on_quit = on_quit
        self._data: dict | None = None
        self._content: tk.Frame | None = None

        self._win = tk.Toplevel(master)
        self._win.withdraw()
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.configure(bg=_C_OUTLINE_VAR)   # 1 px border illusion

        self._shell = tk.Frame(self._win, bg=_C_BG)
        self._shell.pack(padx=1, pady=1, fill="both", expand=True)

        self._win.bind("<FocusOut>", lambda _e: self._win.after(120, self._auto_hide))

    def _auto_hide(self) -> None:
        try:
            if self._win.winfo_viewable() and not self._win.focus_get():
                self._win.withdraw()
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────────────

    def update_data(self, data: dict | None) -> None:
        self._data = data
        if self._win.winfo_viewable():
            self._rebuild()

    def show(self) -> None:
        self._rebuild()
        self._win.update_idletasks()
        sw = self._win.winfo_screenwidth()
        sh = self._win.winfo_screenheight()
        w  = self._win.winfo_reqwidth()
        h  = self._win.winfo_reqheight()
        x  = sw - w - 16
        y  = sh - h - 52
        self._win.geometry(f"+{x}+{y}")
        self._win.deiconify()
        self._win.lift()
        self._win.focus_force()

    def hide(self) -> None:
        self._win.withdraw()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _rebuild(self) -> None:
        if self._content:
            self._content.destroy()

        self._content = tk.Frame(self._shell, bg=_C_BG)
        self._content.pack(fill="x")
        # Anchor minimum width via a 1px-tall strut
        tk.Frame(self._content, width=POPUP_W, height=1, bg=_C_BG).pack()

        self._draw_header()

        data = self._data
        providers = [p for p in (data or {}).get("providers", []) if p.get("budget_usd", 0) > 0]

        if not data or not providers:
            self._draw_error()
        else:
            for p in providers:
                self._draw_provider_card(p)
            self._draw_summary(providers)

        self._draw_actions()

    # ── Header ────────────────────────────────────────────────────────────────

    def _draw_header(self) -> None:
        hdr = tk.Frame(self._content, bg=_C_CONT_HIGH)
        hdr.pack(fill="x")

        tk.Label(
            hdr, text="LLM Usage",
            font=_F_H, bg=_C_CONT_HIGH, fg=_C_PRIMARY,
        ).pack(side="left", padx=16, pady=14)

        tk.Button(
            hdr, text="✕",
            font=_F_SM,
            bg=_C_CONT_HIGH, fg=_C_ON_SURF_VAR,
            activebackground=_C_CONT, activeforeground=_C_ON_SURF,
            relief="flat", bd=0, padx=8, pady=4,
            cursor="hand2",
            command=self.hide,
        ).pack(side="right", padx=8, pady=10)

    # ── Provider card ─────────────────────────────────────────────────────────

    def _draw_provider_card(self, p: dict) -> None:
        name      = p["name"]
        today     = p["spent_today"]
        month     = p["spent_total"]
        remaining = p["remaining"]
        pct       = p["remaining_pct"]
        budget    = p.get("budget_usd", 0)

        brand_fg, brand_card = _BRAND.get(name, _BRAND["Other"])
        low = pct < 20 and budget > 0
        bar_color = _C_ERROR if low else _C_PRIMARY
        pct_color = _C_ERROR if low else _C_ON_SURF_VAR

        # Outer padding frame
        wrap = tk.Frame(self._content, bg=_C_BG)
        wrap.pack(fill="x", padx=12, pady=(10, 0))

        card = tk.Frame(wrap, bg=brand_card, padx=14, pady=12)
        card.pack(fill="x")

        # Provider name
        name_row = tk.Frame(card, bg=brand_card)
        name_row.pack(fill="x", pady=(0, 8))
        tk.Label(
            name_row, text="●",
            font=(_FF, 16), bg=brand_card, fg=brand_fg,
        ).pack(side="left", padx=(0, 6))
        tk.Label(
            name_row, text=name.upper(),
            font=_F_BOLD, bg=brand_card, fg=_C_ON_SURF,
        ).pack(side="left")

        # Stat rows: label on left, amount on right
        def stat(label: str, amount: float, bold: bool = False) -> None:
            row = tk.Frame(card, bg=brand_card)
            row.pack(fill="x", pady=1)
            tk.Label(
                row, text=label, font=_F,
                bg=brand_card, fg=_C_ON_SURF_VAR,
                width=13, anchor="w",
            ).pack(side="left")
            tk.Label(
                row, text=f"${amount:>8.2f}",
                font=_F_BOLD if bold else _F,
                bg=brand_card, fg=_C_ON_SURF,
            ).pack(side="right")

        stat("Today", today)
        stat("This month", month)
        stat("Remaining", remaining, bold=True)

        # Progress bar (Canvas so we can draw proportional fill)
        canvas = tk.Canvas(
            card, height=6,
            bg=_C_OUTLINE_VAR,
            highlightthickness=0, bd=0,
        )
        canvas.pack(fill="x", pady=(10, 4))

        def _draw(event=None, c=canvas, fc=bar_color, pct=pct) -> None:
            w = c.winfo_width()
            if w <= 1:
                return
            c.delete("all")
            c.create_rectangle(0, 0, w, 6, fill=_C_OUTLINE_VAR, outline="")
            filled = max(0, min(w, int(w * pct / 100)))
            if filled:
                c.create_rectangle(0, 0, filled, 6, fill=fc, outline="")

        canvas.bind("<Configure>", _draw)
        canvas.after(80, _draw)

        # Pct label
        pct_row = tk.Frame(card, bg=brand_card)
        pct_row.pack(fill="x")
        tk.Label(
            pct_row, text=f"{pct:.0f}% remaining",
            font=_F_SM, bg=brand_card, fg=pct_color,
        ).pack(side="right")

    # ── Summary footer ────────────────────────────────────────────────────────

    def _draw_summary(self, providers: list[dict]) -> None:
        total_today = sum(p["spent_today"] for p in providers)
        total_rem   = sum(p["remaining"]   for p in providers)

        tk.Frame(self._content, bg=_C_OUTLINE_VAR, height=1).pack(
            fill="x", padx=12, pady=(12, 0),
        )
        row = tk.Frame(self._content, bg=_C_BG)
        row.pack(fill="x", padx=16, pady=(8, 0))
        tk.Label(
            row, text=f"Today  ${total_today:.2f}",
            font=_F_SM, bg=_C_BG, fg=_C_ON_SURF_VAR,
        ).pack(side="left")
        tk.Label(
            row, text=f"Left  ${total_rem:.2f}",
            font=(_FF, 9, "bold"), bg=_C_BG, fg=_C_PRIMARY,
        ).pack(side="right")

    # ── Error state ───────────────────────────────────────────────────────────

    def _draw_error(self) -> None:
        wrap = tk.Frame(self._content, bg=_C_BG)
        wrap.pack(fill="x", padx=12, pady=14)
        card = tk.Frame(wrap, bg=_C_ERR_CONT, padx=14, pady=14)
        card.pack(fill="x")
        tk.Label(
            card, text="⚠  Daemon not running",
            font=_F, bg=_C_ERR_CONT, fg=_C_ERROR,
        ).pack()

    # ── Action buttons ────────────────────────────────────────────────────────

    def _draw_actions(self) -> None:
        tk.Frame(self._content, bg=_C_OUTLINE_VAR, height=1).pack(fill="x")
        row = tk.Frame(self._content, bg=_C_BG)
        row.pack(fill="x", padx=8, pady=(6, 8))

        tk.Button(
            row, text="Settings",
            font=_F_BOLD,
            bg=_C_BG, fg=_C_PRIMARY,
            activebackground=_C_PRIM_CONT, activeforeground=_C_ON_PRIM_CNT,
            relief="flat", bd=0, padx=12, pady=7,
            cursor="hand2",
            command=self._on_settings,
        ).pack(side="left")

        tk.Button(
            row, text="Quit",
            font=_F,
            bg=_C_BG, fg=_C_ON_SURF_VAR,
            activebackground=_C_CONT, activeforeground=_C_ON_SURF,
            relief="flat", bd=0, padx=12, pady=7,
            cursor="hand2",
            command=self._on_quit,
        ).pack(side="right")


# ── Settings launcher ─────────────────────────────────────────────────────────

def _open_settings() -> None:
    import os

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
            proc = subprocess.Popen([str(settings_bin)], stderr=subprocess.PIPE)
            try:
                proc.wait(timeout=1.0)
                err = (proc.stderr.read() if proc.stderr else b"").decode().strip()
                if err:
                    logger.warning("Settings failed: %s", err)
                    _notify_error(err)
            except subprocess.TimeoutExpired:
                pass
            return

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

        # Hidden tkinter root — event loop lives here, popup is a Toplevel
        self._tk = tk.Tk()
        self._tk.withdraw()

        self._popup = TrayPopup(
            self._tk,
            on_settings=lambda: self._tk.after(0, _open_settings),
            on_quit=lambda: self._tk.after(0, self._quit),
        )

        self._icon = pystray.Icon(
            "llm-usage-indicator",
            _make_icon(),
            "LLM Usage Indicator",
            menu=self._make_menu(),
        )

    def _make_menu(self) -> pystray.Menu:
        show = lambda *_: self._tk.after(0, self._popup.show)
        return pystray.Menu(
            pystray.MenuItem("Details", show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Settings…",  lambda *_: self._tk.after(0, _open_settings)),
            pystray.MenuItem("Refresh now", lambda *_: self._tk.after(0, self._refresh)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda *_: self._tk.after(0, self._quit)),
        )

    def _refresh(self) -> None:
        threading.Thread(target=self._fetch_and_update, daemon=True).start()

    def _fetch_and_update(self) -> None:
        data = _fetch_status()
        self._tk.after(0, lambda: self._apply_update(data))

    def _apply_update(self, data: dict | None) -> None:
        self._data = data
        providers = (data or {}).get("providers", [])
        warning = any(p["remaining_pct"] < 20 and p["budget_usd"] > 0 for p in providers)
        error   = data is None

        self._icon.icon  = _make_icon(warning=warning, error=error, providers=providers)
        self._icon.title = _icon_title(providers)
        self._icon.menu  = self._make_menu()
        self._popup.update_data(data)

        self._timer = threading.Timer(
            REFRESH_INTERVAL_S,
            lambda: self._tk.after(0, self._refresh),
        )
        self._timer.daemon = True
        self._timer.start()

    def _quit(self) -> None:
        if self._timer:
            self._timer.cancel()
        try:
            self._icon.stop()
        except Exception:
            pass
        self._tk.quit()

    def run(self) -> None:
        # pystray in daemon thread (works on Linux; macOS needs main thread)
        threading.Thread(target=self._icon.run, daemon=True).start()
        self._tk.after(200, self._refresh)
        self._tk.mainloop()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    TrayApp().run()


if __name__ == "__main__":
    main()
