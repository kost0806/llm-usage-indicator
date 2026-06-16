"""
Configuration loader for llm-usage-indicator.
Reads TOML config from the platform-appropriate user config directory,
falling back to ./config.toml in the current directory.

Config search order:
  1. Platform config dir  (Linux: ~/.config/llm-usage-indicator/config.toml,
                           Windows: %APPDATA%\\llm-usage-indicator\\config.toml)
  2. ./config.toml (current directory)
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]

from platformdirs import user_config_dir, user_data_dir

_APP_NAME = "llm-usage-indicator"

_BUDGET_KEY_MAP: dict[str, str] = {
    "claude":  "Claude",
    "gemini":  "Gemini",
    "openai":  "OpenAI",
    "copilot": "Copilot",
    "other":   "Other",
}


@dataclass
class GeneralConfig:
    poll_interval: int = 60
    ipc_host: str = "127.0.0.1"
    ipc_port: int = 37891
    db_path: str = ""  # empty → resolved via platformdirs at runtime


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    budgets: dict = field(default_factory=dict)  # {"Claude": 20.0, ...}

    @property
    def db_path_expanded(self) -> Path:
        if self.general.db_path:
            return Path(self.general.db_path).expanduser()
        return Path(user_data_dir(_APP_NAME)) / "data.db"


def _resolve_config_path() -> Path:
    user_cfg = Path(user_config_dir(_APP_NAME)) / "config.toml"
    if user_cfg.exists():
        return user_cfg
    local_cfg = Path("config.toml")
    if local_cfg.exists():
        return local_cfg
    return user_cfg


def load_config() -> Config:
    path = _resolve_config_path()
    raw: dict = {}
    if path.exists():
        with open(path, "rb") as f:
            raw = tomllib.load(f)

    g = raw.get("general", {})
    general = GeneralConfig(
        poll_interval=int(g.get("poll_interval", 60)),
        ipc_host=g.get("ipc_host", "127.0.0.1"),
        ipc_port=int(g.get("ipc_port", 37891)),
        db_path=g.get("db_path", ""),
    )

    budgets = {
        _BUDGET_KEY_MAP.get(k.lower(), k.title()): float(v)
        for k, v in raw.get("budgets", {}).items()
    }

    return Config(general=general, budgets=budgets)


if __name__ == "__main__":
    cfg = load_config()
    print(f"General: {cfg.general}")
    print(f"Budgets: {cfg.budgets}")
    print(f"DB path: {cfg.db_path_expanded}")
