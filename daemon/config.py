"""
Configuration loader for llm-credit-monitor.
Reads TOML config from ~/.config/llm-credit-monitor/config.toml,
falling back to ./config.toml in the current directory.
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomllib  # type: ignore[no-redef]  # provided by tomllib package


@dataclass
class ProviderConfig:
    enabled: bool = False
    api_key: str = ""
    budget_usd: float = 0.0


@dataclass
class GeneralConfig:
    poll_interval_credits: int = 300
    poll_interval_usage: int = 60
    waybar_refresh: int = 30
    socket_path: str = "/tmp/llm-monitor.sock"
    db_path: str = "~/.local/share/llm-credit-monitor/data.db"


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    claude: ProviderConfig = field(default_factory=ProviderConfig)
    gemini: ProviderConfig = field(default_factory=ProviderConfig)
    openai: ProviderConfig = field(default_factory=ProviderConfig)

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
    return user_config  # will fail gracefully below


def _provider_from_dict(data: dict, env_key: str) -> ProviderConfig:
    # Environment variable overrides config file API key for security.
    api_key = os.environ.get(env_key, data.get("api_key", ""))
    return ProviderConfig(
        enabled=data.get("enabled", False),
        api_key=api_key,
        budget_usd=float(data.get("budget_usd", 0.0)),
    )


def load_config() -> Config:
    path = _resolve_config_path()
    raw: dict = {}
    if path.exists():
        with open(path, "rb") as f:
            raw = tomllib.load(f)

    general_raw = raw.get("general", {})
    providers_raw = raw.get("providers", {})

    general = GeneralConfig(
        poll_interval_credits=int(general_raw.get("poll_interval_credits", 300)),
        poll_interval_usage=int(general_raw.get("poll_interval_usage", 60)),
        waybar_refresh=int(general_raw.get("waybar_refresh", 30)),
        socket_path=general_raw.get("socket_path", "/tmp/llm-monitor.sock"),
        db_path=general_raw.get("db_path", "~/.local/share/llm-credit-monitor/data.db"),
    )

    return Config(
        general=general,
        claude=_provider_from_dict(providers_raw.get("claude", {}), "ANTHROPIC_API_KEY"),
        gemini=_provider_from_dict(providers_raw.get("gemini", {}), "GOOGLE_API_KEY"),
        openai=_provider_from_dict(providers_raw.get("openai", {}), "OPENAI_API_KEY"),
    )


if __name__ == "__main__":
    cfg = load_config()
    print(f"General: {cfg.general}")
    print(f"Claude enabled: {cfg.claude.enabled}, budget: ${cfg.claude.budget_usd}")
    print(f"Gemini enabled: {cfg.gemini.enabled}, budget: ${cfg.gemini.budget_usd}")
    print(f"OpenAI enabled: {cfg.openai.enabled}, budget: ${cfg.openai.budget_usd}")
    print(f"DB path: {cfg.db_path_expanded}")
