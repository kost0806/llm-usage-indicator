#!/usr/bin/env python3
"""
System tray indicator for llm-usage-indicator.

On GNOME / Unity: uses AppIndicator3 to show text labels in the status bar.
On X11 (KDE, XFCE, i3, etc.): falls back to Gtk.StatusIcon with a tooltip.

Required:
  sudo apt install python3-gi gir1.2-gtk-3.0
  # For GNOME text labels (optional):
  sudo apt install gir1.2-appindicator3-0.1 gnome-shell-extension-appindicator
"""

import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
from pathlib import Path

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib
except (ImportError, ValueError) as exc:
    print(
        f"ERROR: {exc}\n"
        "Install with: sudo apt install python3-gi gir1.2-gtk-3.0",
        file=sys.stderr,
    )
    sys.exit(1)

_HAVE_APPINDICATOR = False
try:
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3
    _HAVE_APPINDICATOR = True
except (ImportError, ValueError):
    pass

SOCKET_PATH = os.environ.get("LLM_MONITOR_SOCK", "/tmp/llm-monitor.sock")
REFRESH_INTERVAL_MS = 30_000
SOCKET_TIMEOUT_S = 3
_ICON = "utilities-system-monitor"

logger = logging.getLogger(__name__)


# ── Socket helper ─────────────────────────────────────────────────────────────

def _fetch_status() -> dict | None:
    """Query the daemon and return the parsed JSON dict, or None on error."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(SOCKET_TIMEOUT_S)
            s.connect(SOCKET_PATH)
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


# ── Shared helpers ────────────────────────────────────────────────────────────

def _bar_label(providers: list[dict]) -> tuple[str, str]:
    """Return (label, guide) for AppIndicator3 status bar text."""
    if not providers:
        return "🤖 --", "🤖 --"
    parts = []
    for p in providers:
        initial = p["name"][0]
        if p["budget_usd"] > 0:
            parts.append(f"{initial}:${p['remaining']:.2f}")
        else:
            parts.append(f"{initial}:↑${p['spent_today']:.2f}")
    label = "🤖 " + "  ".join(parts)
    guide = "🤖 " + "  ".join(["X:$000.00"] * len(parts))
    return label, guide


def _tooltip(providers: list[dict]) -> str:
    """Return tooltip text for StatusIcon (X11 fallback)."""
    if not providers:
        return "LLM Usage Indicator — daemon not running"
    lines = ["LLM Usage Indicator"]
    for p in providers:
        if p["budget_usd"] > 0:
            lines.append(
                f"  {p['name']}: ${p['remaining']:.2f} remaining"
                f" ({p['remaining_pct']:.0f}%)  ↑ ${p['spent_today']:.4f} today"
            )
        else:
            lines.append(f"  {p['name']}: ${p['spent_today']:.4f} today (no budget)")
    return "\n".join(lines)


def _open_settings(_item=None) -> None:
    settings_bin = Path.home() / ".local" / "bin" / "llm-usage-indicator-settings"
    if settings_bin.exists():
        subprocess.Popen([str(settings_bin)])
    else:
        subprocess.Popen([sys.executable, "-m", "llm_usage_indicator.settings_gui"])


def _build_menu(data: dict | None, on_refresh) -> Gtk.Menu:
    menu = Gtk.Menu()
    providers = (data or {}).get("providers", [])

    if providers:
        for p in providers:
            if p["budget_usd"] > 0:
                line = (
                    f"{p['name']}: ${p['remaining']:.2f} remaining"
                    f" ({p['remaining_pct']:.0f}%)  ↑ ${p['spent_today']:.4f} today"
                )
            else:
                line = f"{p['name']}: ${p['spent_today']:.4f} today (no budget)"
            item = Gtk.MenuItem(label=line)
            item.set_sensitive(False)
            menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
    else:
        no_daemon = Gtk.MenuItem(label="Daemon not running")
        no_daemon.set_sensitive(False)
        menu.append(no_daemon)
        menu.append(Gtk.SeparatorMenuItem())

    item_settings = Gtk.MenuItem(label="Settings…")
    item_settings.connect("activate", _open_settings)
    menu.append(item_settings)

    item_refresh = Gtk.MenuItem(label="Refresh now")
    item_refresh.connect("activate", lambda _: on_refresh())
    menu.append(item_refresh)

    menu.append(Gtk.SeparatorMenuItem())

    item_quit = Gtk.MenuItem(label="Quit")
    item_quit.connect("activate", lambda _: Gtk.main_quit())
    menu.append(item_quit)

    menu.show_all()
    return menu


# ── AppIndicator3 implementation (GNOME / Unity) ──────────────────────────────

class AppIndicatorImpl:
    """Uses AppIndicator3 to show live cost text in the GNOME status bar."""

    def __init__(self) -> None:
        self._ind = AppIndicator3.Indicator.new(
            "llm-usage-indicator",
            _ICON,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self._ind.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self._ind.set_label("🤖 --", "🤖 C:$00.00 G:$00.00")
        self._set_menu(None)
        self._refresh()
        GLib.timeout_add(REFRESH_INTERVAL_MS, self._on_timer)

    def _set_menu(self, data: dict | None) -> None:
        self._ind.set_menu(_build_menu(data, self._refresh))

    def _refresh(self) -> None:
        threading.Thread(target=self._fetch_and_apply, daemon=True).start()

    def _fetch_and_apply(self) -> None:
        GLib.idle_add(self._apply, _fetch_status())

    def _apply(self, data: dict | None) -> bool:
        providers = (data or {}).get("providers", [])
        label, guide = _bar_label(providers)
        self._ind.set_label(label, guide)
        self._set_menu(data)
        return False

    def _on_timer(self) -> bool:
        self._refresh()
        return True


# ── Gtk.StatusIcon fallback (X11 with system tray) ────────────────────────────

class StatusIconImpl:
    """
    Gtk.StatusIcon for X11 environments that don't support AppIndicator3
    (KDE, XFCE, MATE, i3+trayer, etc.).

    Shows current costs in the hover tooltip; right-click opens the menu.
    """

    def __init__(self) -> None:
        self._icon = Gtk.StatusIcon()
        self._icon.set_from_icon_name(_ICON)
        self._icon.set_tooltip_text("LLM Usage Indicator — loading…")
        self._icon.set_visible(True)
        self._icon.connect("popup-menu", self._on_popup)
        self._data: dict | None = None
        self._refresh()
        GLib.timeout_add(REFRESH_INTERVAL_MS, self._on_timer)

    def _refresh(self) -> None:
        threading.Thread(target=self._fetch_and_apply, daemon=True).start()

    def _fetch_and_apply(self) -> None:
        GLib.idle_add(self._apply, _fetch_status())

    def _apply(self, data: dict | None) -> bool:
        self._data = data
        providers = (data or {}).get("providers", [])
        self._icon.set_tooltip_text(_tooltip(providers))
        return False

    def _on_timer(self) -> bool:
        self._refresh()
        return True

    def _on_popup(self, icon, button, activate_time) -> None:
        menu = _build_menu(self._data, self._refresh)
        menu.popup(
            None, None,
            Gtk.StatusIcon.position_menu,
            icon, button, activate_time,
        )


# ── Backend selection ─────────────────────────────────────────────────────────

def _use_appindicator() -> bool:
    """
    True when AppIndicator3 is available AND we're running in a desktop that
    supports it natively (GNOME with appindicator extension, or Unity).
    For all other X11 desktops we use Gtk.StatusIcon instead.
    """
    if not _HAVE_APPINDICATOR:
        return False
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    return any(name in desktop for name in ("GNOME", "UNITY"))


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    if _use_appindicator():
        AppIndicatorImpl()
    else:
        # X11 fallback: works on KDE, XFCE, MATE, i3+trayer, etc.
        StatusIconImpl()

    Gtk.main()


if __name__ == "__main__":
    main()
