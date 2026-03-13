"""
Caching policy implementations.

Each policy decides:
  1. Whether to check the cache before calling upstream (should_check_cache)
  2. What TTL to assign when storing a new result (get_ttl)

Adding a new policy later: subclass Policy and register it in get_policy().
"""

from abc import ABC, abstractmethod
from config import Settings


class Policy(ABC):
    @abstractmethod
    def should_cache(self) -> bool:
        """Whether this policy uses the cache at all."""

    @abstractmethod
    def get_ttl(self, tool: str, workflow_step: int, downstream_dependents: int) -> float:
        """Return the TTL in seconds to assign to a cached result."""


class NoCachePolicy(Policy):
    """Always calls upstream. Never reads or writes the cache. Correctness baseline."""

    def should_cache(self) -> bool:
        return False

    def get_ttl(self, tool: str, workflow_step: int, downstream_dependents: int) -> float:
        return 0.0


class FixedTTLPolicy(Policy):
    """
    One fixed TTL per tool type. Ignores workflow position entirely.
    This is the standard baseline — equivalent to what Redis would do out of the box.
    """

    def __init__(self, settings: Settings) -> None:
        self._ttls = {
            "price":         settings.ttl_price_s,
            "trend":         settings.ttl_trend_s,
            "weather":       settings.ttl_weather_s,
            "news_sentiment": settings.ttl_sentiment_s,
        }

    def should_cache(self) -> bool:
        return True

    def get_ttl(self, tool: str, workflow_step: int, downstream_dependents: int) -> float:
        # workflow_step and downstream_dependents are intentionally ignored here.
        # That's the point — this policy is blind to workflow structure.
        return self._ttls.get(tool, 30.0)


def get_policy(settings: Settings) -> Policy:
    if settings.policy == "none":
        return NoCachePolicy()
    if settings.policy == "fixed_ttl":
        return FixedTTLPolicy(settings)
    raise ValueError(f"Unknown policy: {settings.policy}")
