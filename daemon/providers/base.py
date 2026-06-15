"""
Abstract base class for LLM provider status providers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ProviderStatus:
    name: str           # "Claude" | "Gemini" | "OpenAI"
    budget_usd: float   # configured total credits
    spent_total: float  # cumulative usage
    spent_today: float  # today's usage
    updated_at: float   # unix timestamp

    @property
    def remaining(self) -> float:
        return max(0.0, self.budget_usd - self.spent_total)

    @property
    def remaining_pct(self) -> float:
        if self.budget_usd <= 0:
            return 0.0
        return self.remaining / self.budget_usd * 100


# Checked in order; first match wins.
MODEL_PREFIX_MAP: list[tuple[str, str]] = [
    ("claude-",  "Claude"),
    ("gemini-",  "Gemini"),
    ("gpt-",     "OpenAI"),
    ("o1-",      "OpenAI"),
    ("o3-",      "OpenAI"),
    ("o4-",      "OpenAI"),
    ("chatgpt-", "OpenAI"),
    ("codex-",   "OpenAI"),
    ("copilot-", "Copilot"),
]


def model_to_provider(model_name: str) -> str:
    lower = model_name.lower()
    for prefix, provider in MODEL_PREFIX_MAP:
        if lower.startswith(prefix):
            return provider
    return "Other"


class AbstractProvider(ABC):
    @abstractmethod
    async def fetch_status(self) -> ProviderStatus:
        """Call the API and return current status. Raise on unrecoverable failure."""
        ...
