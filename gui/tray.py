#!/usr/bin/env python3
"""
AppIndicator3 system-tray / GNOME top-bar module for llm-usage-indicator.

Displays live LLM usage as labelled text in the GNOME status area:
  🤖 C:$13.50 G:$14.20 O:$8.30

Requires (Ubuntu):
  sudo apt install python3-gi gir1.2-gtk-3.0 \
       gir1.2-appindicator3-0.1 \
       gnome-shell-extension-appindicator   # or ubuntu-unity-appindicator

The indicator connects to the daemon's Unix socket every <interval> seconds
to fetch current provider statuses.  If the daemon is unreachable it shows
"🤖 --" and retries silently on the next tick.
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
    gi.require_version("AppIndicator3", "0.1")
    gi.require_version("Gtk", "3.0")
    from gi.repository import AppIndicator3, Gtk, GLib
except (ImportError, ValueError) as exc:
    print(
        f"ERROR: {exc}\n"
        "Install with:\n"
        "  sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-appindicator3-0.1\n"
        "  sudo apt install gnome-shell-extension-appindicator",
        file=sys.stderr,
    )
    sys.exit(1)

SOCKET_PATH = os.environ.get("LLM_MONITOR_SOCK", "/tmp/llm-monitor.sock")
REFRESH_INTERVAL_MS = 30_000   # 30 s
SOCKET_TIMEOUT_S = 3


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


# ── Indicator ─────────────────────────────────────────────────────────────────

class LLMIndicator:
    _ICON = "utilities-system-monitor"   # standard freedesktop icon

    def __init__(self) -> None:
        self._ind = AppIndicator3.Indicator.new(
            "llm-usage-indicator",
            self._ICON,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self._ind.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self._ind.set_label("🤖 --", "🤖 C:$00.00 G:$00.00")   # (label, guide)

        self._menu = Gtk.Menu()
        self._ind.set_menu(self._menu)

        # Persistent menu items for providers (rebuilt on each refresh)
        self._provider_items: list[Gtk.MenuItem] = []

        self._add_static_menu_items()
        self._menu.show_all()

        # Initial fetch then schedule repeating refresh
        self._refresh()
        GLib.timeout_add(REFRESH_INTERVAL_MS, self._on_timer)

    # ── Menu construction ──────────────────────────────────────────────────

    def _add_static_menu_items(self) -> None:
        self._sep_top = Gtk.SeparatorMenuItem()
        self._menu.append(self._sep_top)

        item_settings = Gtk.MenuItem(label="Settings…")
        item_settings.connect("activate", self._on_settings)
        self._menu.append(item_settings)

        item_refresh = Gtk.MenuItem(label="Refresh now")
        item_refresh.connect("activate", lambda _: self._refresh())
        self._menu.append(item_refresh)

        self._menu.append(Gtk.SeparatorMenuItem())

        item_quit = Gtk.MenuItem(label="Quit")
        item_quit.connect("activate", self._on_quit)
        self._menu.append(item_quit)

    def _rebuild_provider_items(self, providers: list[dict]) -> None:
        for item in self._provider_items:
            self._menu.remove(item)
        self._provider_items.clear()

        insert_pos = 0   # insert at top, before the separator

        if not providers:
            item = Gtk.MenuItem(label="Daemon not running")
            item.set_sensitive(False)
            self._menu.insert(item, insert_pos)
            self._provider_items.append(item)
            return

        for p in providers:
            budget = p["budget_usd"]
            remaining = "$%.2f remaining" % p["remaining"] if budget > 0 else "no budget set"
            today = "$%.4f today" % p["spent_today"]
            pct = "%.0f%%" % p["remaining_pct"] if budget > 0 else ""
            label = f"{p['name']}: {remaining} {pct}  (↑ {today})"
            item = Gtk.MenuItem(label=label)
            item.set_sensitive(False)
            self._menu.insert(item, insert_pos)
            self._provider_items.append(item)
            insert_pos += 1

        # Total line
        data_ref = [providers]   # closure hack — updated below by caller
        self._provider_items_ref = data_ref

    # ── Refresh logic ──────────────────────────────────────────────────────

    def _refresh(self) -> None:
        """Fetch status in a background thread to avoid blocking the GTK main loop."""
        threading.Thread(target=self._fetch_and_update, daemon=True).start()

    def _fetch_and_update(self) -> None:
        data = _fetch_status()
        GLib.idle_add(self._apply_status, data)

    def _apply_status(self, data: dict | None) -> bool:
        if data is None:
            self._ind.set_label("🤖 --", "🤖 --")
            self._rebuild_provider_items([])
            self._menu.show_all()
            return False

        providers = data.get("providers", [])

        # Build top-bar label: "🤖 C:$13.50 G:$14.20"
        parts = []
        for p in providers:
            initial = p["name"][0]
            if p["budget_usd"] > 0:
                parts.append(f"{initial}:${p['remaining']:.2f}")
            else:
                parts.append(f"{initial}:↑${p['spent_today']:.2f}")

        label = ("🤖 " + "  ".join(parts)) if parts else "🤖 $0.00"
        # guide string = widest expected label (prevents bar from jumping width)
        guide = "🤖 " + "  ".join(["X:$000.00"] * max(len(parts), 1))
        self._ind.set_label(label, guide)

        self._rebuild_provider_items(providers)
        self._menu.show_all()
        return False   # don't repeat via idle_add

    def _on_timer(self) -> bool:
        self._refresh()
        return True   # keep repeating

    # ── Actions ───────────────────────────────────────────────────────────

    def _on_settings(self, _item: Gtk.MenuItem) -> None:
        settings_bin = Path.home() / ".local" / "bin" / "llm-usage-indicator-settings"
        if settings_bin.exists():
            subprocess.Popen([str(settings_bin)])
        else:
            subprocess.Popen([
                sys.executable, "-m", "llm_usage_indicator.settings_gui"
            ])

    @staticmethod
    def _on_quit(_item: Gtk.MenuItem) -> None:
        Gtk.main_quit()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.WARNING)

    # Allow Ctrl-C to quit
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    LLMIndicator()
    Gtk.main()


if __name__ == "__main__":
    main()
