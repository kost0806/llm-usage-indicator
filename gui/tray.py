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

PROVIDER_EMOJI: dict[str, str] = {
    "Claude":  "🟠",
    "OpenAI":  "🟢",
    "Gemini":  "🔵",
    "Other":   "⚪",
}


def _load_font(size: int):
    """Load a bold system font for the tray number display."""
    from PIL import ImageFont
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _make_icon(
    usage_pct: int = 0,
    error: bool = False,
    providers: list[dict] | None = None,
) -> Image.Image:
    """Render tray icon as a number (0–99) showing total credit usage %."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if error:
        bg = (100, 100, 100)
    elif usage_pct >= 80:
        bg = (180, 40, 40)   # red — high usage
    elif usage_pct >= 60:
        bg = (200, 120, 20)  # orange — medium
    else:
        bg = (40, 140, 80)   # green — low

    draw.rounded_rectangle([1, 1, size - 2, size - 2], radius=14, fill=bg + (255,))

    text = "--" if error else str(min(99, max(0, usage_pct)))
    font = _load_font(34)

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1]
    draw.text((tx, ty), text, fill=(255, 255, 255, 255), font=font)

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

# Brand accent color per provider — used only for the dot (●)
_BRAND: dict[str, str] = {
    "Claude": "#D15A2A",
    "OpenAI": "#10A37F",
    "Gemini": "#4285F4",
    "Other":  _C_OUTLINE,
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

        self._drag_x = 0
        self._drag_y = 0

        self._win = tk.Toplevel(master)
        self._win.withdraw()
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.configure(bg=_C_OUTLINE_VAR)   # 1 px border illusion

        self._shell = tk.Frame(self._win, bg=_C_BG)
        self._shell.pack(padx=1, pady=1, fill="both", expand=True)

        self._win.bind("<FocusOut>", lambda _e: self._win.after(120, self._auto_hide))

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_x = event.x_root - self._win.winfo_x()
        self._drag_y = event.y_root - self._win.winfo_y()

    def _on_drag(self, event: tk.Event) -> None:
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self._win.geometry(f"+{x}+{y}")

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

        lbl = tk.Label(
            hdr, text="LLM Usage",
            font=_F_H, bg=_C_CONT_HIGH, fg=_C_PRIMARY,
            cursor="fleur",
        )
        lbl.pack(side="left", padx=16, pady=14)

        tk.Button(
            hdr, text="✕",
            font=_F_SM,
            bg=_C_CONT_HIGH, fg=_C_ON_SURF_VAR,
            activebackground=_C_CONT, activeforeground=_C_ON_SURF,
            relief="flat", bd=0, padx=8, pady=4,
            cursor="hand2",
            command=self.hide,
        ).pack(side="right", padx=8, pady=10)

        for w in (hdr, lbl):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)

    # ── Provider card ─────────────────────────────────────────────────────────

    def _draw_provider_card(self, p: dict) -> None:
        name      = p["name"]
        today     = p["spent_today"]
        month     = p["spent_total"]
        remaining = p["remaining"]
        pct       = p["remaining_pct"]
        budget    = p.get("budget_usd", 0)

        brand_color = _BRAND.get(name, _BRAND["Other"])
        low = pct < 20 and budget > 0
        bar_color = _C_ERROR if low else _C_PRIMARY
        pct_color = _C_ERROR if low else _C_ON_SURF_VAR

        # Outer padding frame
        wrap = tk.Frame(self._content, bg=_C_BG)
        wrap.pack(fill="x", padx=12, pady=(10, 0))

        card = tk.Frame(wrap, bg=_C_CONT, padx=14, pady=12)
        card.pack(fill="x")

        # Provider name — only the dot uses the brand color
        name_row = tk.Frame(card, bg=_C_CONT)
        name_row.pack(fill="x", pady=(0, 8))
        tk.Label(
            name_row, text="●",
            font=(_FF, 16), bg=_C_CONT, fg=brand_color,
        ).pack(side="left", padx=(0, 6))
        tk.Label(
            name_row, text=name.upper(),
            font=_F_BOLD, bg=_C_CONT, fg=_C_ON_SURF,
        ).pack(side="left")

        # Stat rows: label on left, amount on right
        def stat(label: str, amount: float, bold: bool = False) -> None:
            row = tk.Frame(card, bg=_C_CONT)
            row.pack(fill="x", pady=1)
            tk.Label(
                row, text=label, font=_F,
                bg=_C_CONT, fg=_C_ON_SURF_VAR,
                width=13, anchor="w",
            ).pack(side="left")
            tk.Label(
                row, text=f"${amount:>8.2f}",
                font=_F_BOLD if bold else _F,
                bg=_C_CONT, fg=_C_ON_SURF,
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
        pct_row = tk.Frame(card, bg=_C_CONT)
        pct_row.pack(fill="x")
        tk.Label(
            pct_row, text=f"{pct:.0f}% remaining",
            font=_F_SM, bg=_C_CONT, fg=pct_color,
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
            row, text="Close",
            font=_F,
            bg=_C_BG, fg=_C_ON_SURF_VAR,
            activebackground=_C_CONT, activeforeground=_C_ON_SURF,
            relief="flat", bd=0, padx=12, pady=7,
            cursor="hand2",
            command=self.hide,
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
            _make_icon(usage_pct=0, error=False),
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
        budgeted  = [p for p in providers if p.get("budget_usd", 0) > 0]
        error     = data is None

        total_budget = sum(p["budget_usd"]   for p in budgeted)
        total_spent  = sum(p["spent_total"]  for p in budgeted)
        usage_pct    = int(total_spent / total_budget * 100) if total_budget > 0 else 0

        self._icon.icon  = _make_icon(usage_pct=usage_pct, error=error, providers=providers)
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
