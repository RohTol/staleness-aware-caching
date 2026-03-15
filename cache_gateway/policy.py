"""
Caching policy implementations.

Each policy decides:
  1. Whether to check the cache before calling upstream (should_cache)
  2. What TTL to assign when storing a new result (get_ttl)

Adding a new policy later: subclass Policy and register it in get_policy().
"""

from abc import ABC, abstractmethod
from config import Settings
import math


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

class WorkflowAwareTTLPolicy(Policy):
    """
    Tightens TTL for tool calls that have a higher number of downstream dependenies in the workflow DAG. 
    
    Uses two factors to drive adjustment: 
        - downstream_dependents: How many nodes in DAG depend on this call? We use log(1 + dependents) so 
        the penalty grows meaningfully but doesn't collapse the TTL to near-zero for moderately connected nodes
        - workflow_step: Depth: 0 = first_step executed, higher number = closer to leaf. Earlier steps are 
        more damaging when stale because their errors propagate further.
    
    Logic: 
        base_ttl       = fixed TTL for this tool type (same starting point as FixedTTLPolicy)
        dep_factor     = log(1 + downstream_dependents) / log(2)
        position_boost = position_weight   if workflow_step == 0 else 1.0
        adjusted_ttl   = base_ttl / (dep_factor * position_boost)
        final_ttl      = clamp(adjusted_ttl, min_ttl_fraction * base_ttl, base_ttl)

    """

    def __init__(self, settings: Settings) -> None:
        # Base TTLs — same starting point as FixedTTLPolicy so comparisons are fair
        self._base_ttls = {
            "price":          settings.ttl_price_s,
            "trend":          settings.ttl_trend_s,
            "weather":        settings.ttl_weather_s,
            "news_sentiment": settings.ttl_sentiment_s,
        }
        self._position_weight  = settings.wa_position_weight
        self._min_ttl_fraction = settings.wa_min_ttl_fraction
 
    def should_cache(self) -> bool:
        return True
 
    def get_ttl(self, tool: str, workflow_step: int, downstream_dependents: int) -> float:
        base_ttl = self._base_ttls.get(tool, 30.0)
 
        # downstream dependent factor (uses log2 scale, and min dependents = 1, so log never is 0 or neg)
        deps       = max(1, downstream_dependents)
        dep_factor = math.log(1 + deps) / math.log(2)

        # workflow position factor
        position_boost = self._position_weight if workflow_step == 0 else 1.0
 
        # calculating ttl based on two factors
        adjusted_ttl = base_ttl / (dep_factor * position_boost)
        min_ttl      = base_ttl * self._min_ttl_fraction
        final_ttl    = max(min_ttl, min(adjusted_ttl, base_ttl))
 
        return round(final_ttl, 2)


def get_policy(settings: Settings) -> Policy:
    if settings.policy == "none":
        return NoCachePolicy()
    if settings.policy == "fixed_ttl":
        return FixedTTLPolicy(settings)
    if settings.policy == "workflow_aware":
        return WorkflowAwareTTLPolicy(settings)
    raise ValueError(f"Unknown policy: {settings.policy}")
