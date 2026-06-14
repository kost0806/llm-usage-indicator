#!/usr/bin/env python3
"""
GTK3 settings GUI for llm-usage-indicator.

Reads and writes ~/.config/llm-usage-indicator/config.toml.
Requires: python3-gi (PyGObject), gir1.2-gtk-3.0
"""

import subprocess
import sys
import os
from pathlib import Path

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk, GLib
except ImportError:
    print(
        "ERROR: python3-gi is required.\n"
        "Install with: sudo apt install python3-gi gir1.2-gtk-3.0",
        file=sys.stderr,
    )
    sys.exit(1)

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

CONFIG_PATH = Path.home() / ".config" / "llm-usage-indicator" / "config.toml"

DEFAULTS = {
    "poll_interval": 60,
    "socket_path": "/tmp/llm-monitor.sock",
    "db_path": "~/.local/share/llm-usage-indicator/data.db",
    "ccusage_cmd": "npx ccusage@latest",
    "budgets": {
        "claude": 20.0,
        "gemini": 15.0,
        "openai": 10.0,
        "copilot": 0.0,
    },
}

PROVIDERS = [
    ("claude",  "Claude"),
    ("gemini",  "Gemini"),
    ("openai",  "OpenAI"),
    ("copilot", "Copilot"),
]


def _load_raw() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    return {}


def _write_toml(raw: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    g = raw.get("general", {})
    b = raw.get("budgets", {})

    lines = [
        "[general]",
        f'poll_interval = {int(g.get("poll_interval", DEFAULTS["poll_interval"]))}',
        f'socket_path   = "{g.get("socket_path", DEFAULTS["socket_path"])}"',
        f'db_path       = "{g.get("db_path", DEFAULTS["db_path"])}"',
        f'ccusage_cmd   = "{g.get("ccusage_cmd", DEFAULTS["ccusage_cmd"])}"',
        "",
        "# Monthly credit budgets per provider (USD).",
        "[budgets]",
    ]
    for key, _ in PROVIDERS:
        val = b.get(key, DEFAULTS["budgets"].get(key, 0.0))
        lines.append(f"{key:<8}= {float(val):.2f}")

    CONFIG_PATH.write_text("\n".join(lines) + "\n")
    CONFIG_PATH.chmod(0o600)


def _restart_daemon() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "restart", "llm-usage-indicator"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return True, "Daemon restarted successfully."
        return False, result.stderr.strip() or "Failed to restart daemon."
    except FileNotFoundError:
        return False, "systemctl not found — restart the daemon manually."
    except subprocess.TimeoutExpired:
        return False, "Restart timed out."


class SettingsWindow(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(title="LLM Usage Indicator — Settings")
        self.set_border_width(16)
        self.set_default_size(460, -1)
        self.set_resizable(False)
        self.connect("delete-event", Gtk.main_quit)

        self._raw = _load_raw()
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self.add(outer)

        outer.pack_start(self._build_general_section(), False, False, 0)
        outer.pack_start(self._build_budget_section(), False, False, 0)
        outer.pack_start(self._build_buttons(), False, False, 0)

        self._status_bar = Gtk.Label(label="")
        self._status_bar.set_xalign(0)
        ctx = self._status_bar.get_style_context()
        ctx.add_class("dim-label")
        outer.pack_start(self._status_bar, False, False, 0)

    def _section_label(self, text: str) -> Gtk.Label:
        lbl = Gtk.Label()
        lbl.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
        lbl.set_xalign(0)
        return lbl

    def _build_general_section(self) -> Gtk.Box:
        g = self._raw.get("general", {})

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.pack_start(self._section_label("General"), False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        box.pack_start(grid, False, False, 0)

        # Poll interval
        lbl = Gtk.Label(label="Poll interval (seconds):", xalign=0)
        self._poll_spin = Gtk.SpinButton.new_with_range(10, 3600, 10)
        self._poll_spin.set_value(int(g.get("poll_interval", DEFAULTS["poll_interval"])))
        self._poll_spin.set_tooltip_text("How often the daemon fetches usage data")
        grid.attach(lbl, 0, 0, 1, 1)
        grid.attach(self._poll_spin, 1, 0, 1, 1)

        # ccusage command
        lbl2 = Gtk.Label(label="ccusage command:", xalign=0)
        self._ccusage_entry = Gtk.Entry()
        self._ccusage_entry.set_text(g.get("ccusage_cmd", DEFAULTS["ccusage_cmd"]))
        self._ccusage_entry.set_hexpand(True)
        self._ccusage_entry.set_tooltip_text(
            "Command used to invoke ccusage (requires Node.js 18+)"
        )
        grid.attach(lbl2, 0, 1, 1, 1)
        grid.attach(self._ccusage_entry, 1, 1, 1, 1)

        # Advanced: socket path + db path (collapsed by default)
        expander = Gtk.Expander(label="Advanced paths")
        adv_grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin_top=6)
        expander.add(adv_grid)

        lbl3 = Gtk.Label(label="Socket path:", xalign=0)
        self._socket_entry = Gtk.Entry()
        self._socket_entry.set_text(g.get("socket_path", DEFAULTS["socket_path"]))
        self._socket_entry.set_hexpand(True)
        adv_grid.attach(lbl3, 0, 0, 1, 1)
        adv_grid.attach(self._socket_entry, 1, 0, 1, 1)

        lbl4 = Gtk.Label(label="Database path:", xalign=0)
        self._db_entry = Gtk.Entry()
        self._db_entry.set_text(g.get("db_path", DEFAULTS["db_path"]))
        self._db_entry.set_hexpand(True)
        adv_grid.attach(lbl4, 0, 1, 1, 1)
        adv_grid.attach(self._db_entry, 1, 1, 1, 1)

        box.pack_start(expander, False, False, 0)
        return box

    def _build_budget_section(self) -> Gtk.Box:
        b = self._raw.get("budgets", {})

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.pack_start(self._section_label("Monthly Budgets (USD)"), False, False, 0)

        hint = Gtk.Label(
            label="Set to 0 to hide a provider from the status bar.",
            xalign=0,
        )
        hint.get_style_context().add_class("dim-label")
        box.pack_start(hint, False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        box.pack_start(grid, False, False, 0)

        self._budget_spins: dict[str, Gtk.SpinButton] = {}
        for row, (key, label) in enumerate(PROVIDERS):
            lbl = Gtk.Label(label=f"{label}:", xalign=0)
            spin = Gtk.SpinButton.new_with_range(0.0, 10000.0, 1.0)
            spin.set_digits(2)
            val = float(b.get(key, DEFAULTS["budgets"].get(key, 0.0)))
            spin.set_value(val)
            dollar = Gtk.Label(label="$", xalign=1)
            grid.attach(dollar, 0, row, 1, 1)
            grid.attach(lbl,   1, row, 1, 1)
            grid.attach(spin,  2, row, 1, 1)
            self._budget_spins[key] = spin

        return box

    def _build_buttons(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_halign(Gtk.Align.END)

        btn_cancel = Gtk.Button(label="Cancel")
        btn_cancel.connect("clicked", lambda _: Gtk.main_quit())

        btn_save = Gtk.Button(label="Save")
        btn_save.get_style_context().add_class("suggested-action")
        btn_save.connect("clicked", self._on_save)

        btn_save_restart = Gtk.Button(label="Save & Restart Daemon")
        btn_save_restart.connect("clicked", self._on_save_restart)

        box.pack_start(btn_cancel, False, False, 0)
        box.pack_start(btn_save, False, False, 0)
        box.pack_start(btn_save_restart, False, False, 0)
        return box

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _collect(self) -> dict:
        return {
            "general": {
                "poll_interval": int(self._poll_spin.get_value()),
                "socket_path":   self._socket_entry.get_text().strip(),
                "db_path":       self._db_entry.get_text().strip(),
                "ccusage_cmd":   self._ccusage_entry.get_text().strip(),
            },
            "budgets": {
                key: round(spin.get_value(), 2)
                for key, spin in self._budget_spins.items()
            },
        }

    def _save(self) -> bool:
        data = self._collect()
        if not data["general"]["socket_path"]:
            self._set_status("Socket path cannot be empty.", error=True)
            return False
        if not data["general"]["ccusage_cmd"]:
            self._set_status("ccusage command cannot be empty.", error=True)
            return False
        try:
            _write_toml(data)
            return True
        except OSError as e:
            self._set_status(f"Failed to write config: {e}", error=True)
            return False

    def _on_save(self, _btn: Gtk.Button) -> None:
        if self._save():
            self._set_status(f"Saved to {CONFIG_PATH}")

    def _on_save_restart(self, _btn: Gtk.Button) -> None:
        if not self._save():
            return
        ok, msg = _restart_daemon()
        self._set_status(msg, error=not ok)

    def _set_status(self, msg: str, *, error: bool = False) -> None:
        self._status_bar.set_text(msg)
        ctx = self._status_bar.get_style_context()
        ctx.remove_class("error")
        if error:
            ctx.add_class("error")


def _apply_css() -> None:
    css = b"""
    label.error { color: #e01b24; }
    """
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


def main() -> None:
    _apply_css()
    win = SettingsWindow()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
