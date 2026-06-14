"""
Configuration loader for llm-credit-monitor.
Reads TOML config from ~/.config/llm-credit-monitor/config.toml,
falling back to ./config.toml in the current directory.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomllib  # type: ignore[no-redef]


# Maps lowercase config keys to canonical provider names used in ProviderStatus.
_BUDGET_KEY_MAP: dict[str, str] = {
    "claude": "Claude",
    "gemini": "Gemini",
    "openai": "OpenAI",
    "copilot": "Copilot",
    "other": "Other",
}


@dataclass
class GeneralConfig:
    poll_interval: int = 60
    socket_path: str = "/tmp/llm-monitor.sock"
    db_path: str = "~/.local/share/llm-credit-monitor/data.db"
    ccusage_cmd: str = "npx ccusage@latest"


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    budgets: dict = field(default_factory=dict)  # {"Claude": 20.0, ...}

    @property
    def db_path_expanded(self) -> Path:
        return Path(self.general.db_path).expanduser()

    @property
    def socket_path(self) -> str:
        return self.general.socket_path


def _resolve_config_path() -> Path:
    user_config = Path.home() / ".config" / "llm-credit-monitor" / "config.toml"
    if user_config.exists():
        return user_config
    local_config = Path("config.toml")
    if local_config.exists():
        return local_config
    return user_config


def load_config() -> Config:
    path = _resolve_config_path()
    raw: dict = {}
    if path.exists():
        with open(path, "rb") as f:
            raw = tomllib.load(f)

    general_raw = raw.get("general", {})
    budgets_raw = raw.get("budgets", {})

    general = GeneralConfig(
        poll_interval=int(general_raw.get("poll_interval", 60)),
        socket_path=general_raw.get("socket_path", "/tmp/llm-monitor.sock"),
        db_path=general_raw.get("db_path", "~/.local/share/llm-credit-monitor/data.db"),
        ccusage_cmd=general_raw.get("ccusage_cmd", "npx ccusage@latest"),
    )

    budgets = {
        _BUDGET_KEY_MAP.get(k.lower(), k.title()): float(v)
        for k, v in budgets_raw.items()
    }

    return Config(general=general, budgets=budgets)


if __name__ == "__main__":
    cfg = load_config()
    print(f"General: {cfg.general}")
    print(f"Budgets: {cfg.budgets}")
    print(f"DB path: {cfg.db_path_expanded}")
