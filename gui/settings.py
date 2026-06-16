"""
Cross-platform settings GUI for llm-usage-indicator.

Uses tkinter (Python built-in) — no external GUI dependencies.
Config file is written to the platform-appropriate user config directory.

Linux   : ~/.config/llm-usage-indicator/config.toml
Windows : %APPDATA%\\llm-usage-indicator\\config.toml
"""

import subprocess
import sys
from pathlib import Path

try:
    import tkinter as tk
except ModuleNotFoundError:
    print(
        "ERROR: tkinter is not installed.\n"
        "On Ubuntu/Debian, install it with:\n"
        "  sudo apt install python3-tk",
        file=sys.stderr,
    )
    sys.exit(1)

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]

from platformdirs import user_config_dir

_APP = "llm-usage-indicator"
CONFIG_PATH = Path(user_config_dir(_APP)) / "config.toml"

PROVIDERS = [
    ("claude", "Claude", "#D15A2A"),
    ("gemini", "Gemini", "#4285F4"),
    ("openai", "OpenAI", "#10A37F"),
]

DEFAULTS: dict = {
    "poll_interval": 60,
    "ipc_host": "127.0.0.1",
    "ipc_port": 37891,
    "db_path": "",
    "budgets": {"claude": 20.0, "gemini": 15.0, "openai": 10.0},
}

# ── Design tokens ──────────────────────────────────────────────────────────────
_BG      = "#F1F5F9"   # window background
_CARD    = "#FFFFFF"   # section card
_HEADER  = "#312E81"   # title bar (deep indigo)
_ACCENT  = "#4F46E5"   # primary button
_ACFG    = "#FFFFFF"
_TEXT    = "#0F172A"   # primary text
_MUTED   = "#64748B"   # secondary text
_BORDER  = "#E2E8F0"   # card border / separator
_INPUT   = "#F8FAFC"   # spinbox background
_ERROR   = "#DC2626"

_FF = (
    "Segoe UI"   if sys.platform == "win32"  else
    "SF Pro Text" if sys.platform == "darwin" else
    "Sans"
)
_F      = (_FF, 10)
_F_SM   = (_FF, 9)
_F_BOLD = (_FF, 10, "bold")
_F_H    = (_FF, 11, "bold")
_F_TTL  = (_FF, 13, "bold")


# ── Config I/O ────────────────────────────────────────────────────────────────

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
        f'ipc_host      = "{g.get("ipc_host", DEFAULTS["ipc_host"])}"',
        f'ipc_port      = {int(g.get("ipc_port", DEFAULTS["ipc_port"]))}',
        f'db_path       = "{g.get("db_path", DEFAULTS["db_path"])}"',
        "",
        "# Monthly credit budgets per provider (USD).",
        "[budgets]",
    ]
    for key, _, _color in PROVIDERS:
        val = b.get(key, DEFAULTS["budgets"].get(key, 0.0))
        lines.append(f"{key:<8}= {float(val):.2f}")

    CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if sys.platform != "win32":
        CONFIG_PATH.chmod(0o600)


def _restart_daemon() -> tuple[bool, str]:
    try:
        if sys.platform == "win32":
            cmds = [
                ["sc", "stop", "llm-usage-indicator"],
                ["sc", "start", "llm-usage-indicator"],
            ]
        else:
            cmds = [["systemctl", "--user", "restart", "llm-usage-indicator"]]

        for cmd in cmds:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0 and "already" not in result.stderr.lower():
                return False, result.stderr.strip() or f"Command failed: {' '.join(cmd)}"
        return True, ""
    except FileNotFoundError as e:
        return False, f"Command not found: {e} — restart the daemon manually."
    except subprocess.TimeoutExpired:
        return False, "Restart timed out."


# ── Settings window ───────────────────────────────────────────────────────────

class SettingsWindow:
    def __init__(self) -> None:
        self._raw = _load_raw()
        self._root = tk.Tk()
        self._root.title("LLM Usage Indicator — Settings")
        self._root.configure(bg=_BG)
        self._root.resizable(False, False)
        self._build_ui()

    # ── UI helpers ─────────────────────────────────────────────────────────────

    def _card(self, parent: tk.Widget, **pack_kw) -> tk.Frame:
        """Floating white card with a 1 px border."""
        wrap = tk.Frame(parent, bg=_BORDER, padx=1, pady=1)
        wrap.pack(fill="x", **pack_kw)
        inner = tk.Frame(wrap, bg=_CARD)
        inner.pack(fill="both", expand=True)
        return inner

    def _spinbox(self, parent: tk.Widget, **kw) -> tk.Spinbox:
        return tk.Spinbox(
            parent,
            font=_F,
            bg=_INPUT, fg=_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=_BORDER,
            highlightcolor=_ACCENT,
            buttonbackground=_BORDER,
            insertbackground=_TEXT,
            **kw,
        )

    # ── Main build ─────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = self._root
        g = self._raw.get("general", {})
        b = self._raw.get("budgets", {})

        # ── Header bar ────────────────────────────────────────────────────────
        hdr = tk.Frame(root, bg=_HEADER, height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(
            hdr, text="LLM Usage Indicator",
            font=_F_TTL, bg=_HEADER, fg=_ACFG,
        ).place(relx=0.5, rely=0.5, anchor="center")

        # ── Body ──────────────────────────────────────────────────────────────
        body = tk.Frame(root, bg=_BG)
        body.pack(fill="both", padx=20, pady=16)

        # ── Polling section ───────────────────────────────────────────────────
        tk.Label(body, text="Polling", font=_F_H, bg=_BG, fg=_TEXT,
                 anchor="w").pack(fill="x", pady=(0, 6))

        card_poll = self._card(body, pady=(0, 14))

        row_poll = tk.Frame(card_poll, bg=_CARD)
        row_poll.pack(fill="x", padx=16, pady=12)

        tk.Label(row_poll, text="Refresh interval", font=_F, bg=_CARD,
                 fg=_TEXT, anchor="w").pack(side="left")
        tk.Label(row_poll, text="sec", font=_F_SM, bg=_CARD,
                 fg=_MUTED).pack(side="right", padx=(4, 0))

        self._poll_var = tk.IntVar(
            value=int(g.get("poll_interval", DEFAULTS["poll_interval"]))
        )
        self._spinbox(
            row_poll, from_=10, to=3600, increment=10,
            textvariable=self._poll_var, width=6,
        ).pack(side="right")

        # ── Credits section ───────────────────────────────────────────────────
        tk.Label(body, text="Credits", font=_F_H, bg=_BG,
                 fg=_TEXT, anchor="w").pack(fill="x", pady=(0, 6))

        card_bud = self._card(body, pady=(0, 14))

        tk.Label(
            card_bud,
            text="Monthly credit limit per provider (USD). Set 0 to hide a provider.",
            font=_F_SM, bg=_CARD, fg=_MUTED,
            anchor="w", wraplength=340, justify="left",
        ).pack(fill="x", padx=16, pady=(12, 8))

        # Thin rule below hint
        tk.Frame(card_bud, bg=_BORDER, height=1).pack(fill="x")

        self._budget_vars: dict[str, tk.DoubleVar] = {}
        for i, (key, label, dot_color) in enumerate(PROVIDERS):
            row = tk.Frame(card_bud, bg=_CARD)
            row.pack(fill="x", padx=16, pady=10)

            # Brand dot
            tk.Label(row, text="●", font=(_FF, 11), bg=_CARD,
                     fg=dot_color).pack(side="left", padx=(0, 8))

            tk.Label(row, text=label, font=_F_BOLD, bg=_CARD,
                     fg=_TEXT, width=7, anchor="w").pack(side="left")

            val = float(b.get(key, DEFAULTS["budgets"].get(key, 0.0)))
            var = tk.DoubleVar(value=val)
            self._budget_vars[key] = var
            self._spinbox(
                row, from_=0.0, to=10000.0, increment=1.0,
                textvariable=var, width=9, format="%.2f",
            ).pack(side="right")

            tk.Label(row, text="$", font=_F, bg=_CARD,
                     fg=_MUTED).pack(side="right", padx=(0, 4))

            # Divider between rows (not after last)
            if i < len(PROVIDERS) - 1:
                tk.Frame(card_bud, bg=_BORDER, height=1).pack(fill="x", padx=16)

        # Bottom padding inside card
        tk.Frame(card_bud, bg=_CARD, height=4).pack()

        # ── Status label ──────────────────────────────────────────────────────
        self._status_var = tk.StringVar()
        self._status_lbl = tk.Label(
            body,
            textvariable=self._status_var,
            font=_F_SM, bg=_BG, fg=_MUTED,
            wraplength=360, justify="left", anchor="w",
        )
        self._status_lbl.pack(fill="x", pady=(0, 4))

        # ── Footer buttons ────────────────────────────────────────────────────
        footer = tk.Frame(body, bg=_BG)
        footer.pack(fill="x", pady=(4, 0))

        tk.Button(
            footer, text="Cancel",
            font=_F, bg=_CARD, fg=_TEXT,
            activebackground=_BORDER, activeforeground=_TEXT,
            relief="flat", bd=0, padx=18, pady=7, cursor="hand2",
            command=self._root.destroy,
        ).pack(side="right", padx=(6, 0))

        tk.Button(
            footer, text="  Save  ",
            font=_F_BOLD, bg=_ACCENT, fg=_ACFG,
            activebackground="#4338CA", activeforeground=_ACFG,
            relief="flat", bd=0, padx=18, pady=7, cursor="hand2",
            command=self._on_save,
        ).pack(side="right")

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _collect(self) -> dict:
        g = self._raw.get("general", {})
        return {
            "general": {
                "poll_interval": self._poll_var.get(),
                "ipc_host": g.get("ipc_host", DEFAULTS["ipc_host"]),
                "ipc_port": int(g.get("ipc_port", DEFAULTS["ipc_port"])),
                "db_path": g.get("db_path", DEFAULTS["db_path"]),
            },
            "budgets": {
                key: round(var.get(), 2)
                for key, var in self._budget_vars.items()
            },
        }

    def _on_save(self) -> None:
        data = self._collect()
        try:
            _write_toml(data)
        except OSError as e:
            self._set_status(f"Failed to write config: {e}", error=True)
            return

        ok, msg = _restart_daemon()
        if ok:
            self._root.destroy()
        else:
            self._set_status(f"Saved, but daemon restart failed: {msg}", error=True)

    def _set_status(self, msg: str, *, error: bool = False) -> None:
        self._status_var.set(msg)
        self._status_lbl.configure(fg=_ERROR if error else _MUTED)

    def run(self) -> None:
        self._root.mainloop()


def main() -> None:
    win = SettingsWindow()
    win.run()


if __name__ == "__main__":
    main()
