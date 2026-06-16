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
    from tkinter import messagebox, ttk
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
    ("claude",  "Claude"),
    ("gemini",  "Gemini"),
    ("openai",  "OpenAI"),
]

DEFAULTS: dict = {
    "poll_interval": 60,
    "ipc_host": "127.0.0.1",
    "ipc_port": 37891,
    "db_path": "",
    "budgets": {"claude": 20.0, "gemini": 15.0, "openai": 10.0},
}


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
    for key, _ in PROVIDERS:
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
        return True, "Daemon restarted successfully."
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
        self._root.resizable(False, False)
        self._build_ui()

    def _build_ui(self) -> None:
        pad = {"padx": 16, "pady": 8}
        g = self._raw.get("general", {})
        b = self._raw.get("budgets", {})

        # ── General section ──
        frm_gen = ttk.LabelFrame(self._root, text="General", padding=10)
        frm_gen.pack(fill="x", **pad)

        ttk.Label(frm_gen, text="Poll interval (seconds):").grid(
            row=0, column=0, sticky="w", pady=4
        )
        self._poll_var = tk.IntVar(value=int(g.get("poll_interval", DEFAULTS["poll_interval"])))
        ttk.Spinbox(frm_gen, from_=10, to=3600, increment=10,
                    textvariable=self._poll_var, width=8).grid(row=0, column=1, sticky="w")

        # ── Budget section ──
        frm_bud = ttk.LabelFrame(self._root, text="Monthly Budgets (USD)", padding=10)
        frm_bud.pack(fill="x", **pad)
        ttk.Label(frm_bud, text="Set to 0 to hide a provider.", foreground="gray").grid(
            row=0, column=0, columnspan=3, sticky="w"
        )

        self._budget_vars: dict[str, tk.DoubleVar] = {}
        for row, (key, label) in enumerate(PROVIDERS, start=1):
            ttk.Label(frm_bud, text="$").grid(row=row, column=0, sticky="e")
            ttk.Label(frm_bud, text=f"{label}:").grid(row=row, column=1, sticky="w", padx=4)
            val = float(b.get(key, DEFAULTS["budgets"].get(key, 0.0)))
            var = tk.DoubleVar(value=val)
            self._budget_vars[key] = var
            ttk.Spinbox(frm_bud, from_=0.0, to=10000.0, increment=1.0,
                        textvariable=var, width=10, format="%.2f").grid(
                row=row, column=2, sticky="w", pady=2
            )

        # ── Status bar ──
        self._status_var = tk.StringVar()
        status_lbl = ttk.Label(self._root, textvariable=self._status_var, foreground="gray")
        status_lbl.pack(fill="x", padx=16)
        self._status_lbl = status_lbl

        # ── Buttons ──
        frm_btn = ttk.Frame(self._root)
        frm_btn.pack(fill="x", padx=16, pady=(4, 16))

        ttk.Button(frm_btn, text="Cancel", command=self._root.destroy).pack(
            side="right", padx=4
        )
        ttk.Button(frm_btn, text="Save", command=self._on_save).pack(
            side="right", padx=4
        )

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
        self._status_lbl.configure(foreground="red" if error else "gray")

    def run(self) -> None:
        self._root.mainloop()


def main() -> None:
    win = SettingsWindow()
    win.run()


if __name__ == "__main__":
    main()
