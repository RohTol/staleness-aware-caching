from typing import Literal
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Which caching policy to run. Set at startup via env var.
    #   none           — always call upstream, never cache (correctness baseline)
    #   fixed_ttl      — one TTL per tool type, ignores workflow context
    #   workflow_aware — tighten TTL based on downstream dependent count + workflow position
    policy: Literal["none", "fixed_ttl", "workflow_aware"] = "none"

    # Fixed TTL values per tool (seconds). Only used under fixed_ttl policy.
    # Ordered slowest→fastest change rate to make the mismatch obvious in experiments.
    ttl_trend_s: float = 600.0    # 10 min — trend changes ~every 15 min
    ttl_weather_s: float = 180.0  # 3 min  — weather changes ~every 3 min
    ttl_sentiment_s: float = 45.0 # 45s    — sentiment changes ~every 50s
    ttl_price_s: float = 20.0     # 20s    — price changes ~every 20s

    # Workflow-aware policy tuning factors (only used when policy = "workflow_aware")
    # Extra TTL tightening multiplier applied to step-0 (root) tool calls.
    # Set to 1.0 to disable position-based tightening.
    # Value of 1.5 means root calls get their TTL divided by 1.5× on top of the dependency penalty.
    wa_position_weight: float = 1.5
 
    # Floor on TTL as a fraction of the base TTL.
    # Prevents the policy from tightening TTL below this fraction 
    # no matter how many downstream dependents a call has.
    # Default 0.2 = no more than 5× tighter than the fixed baseline for that tool.
    wa_min_ttl_fraction: float = 0.2

    # URL of the API simulator
    simulator_url: str = "http://localhost:8001"

    # Port this gateway listens on
    port: int = 8002

    class Config:
        env_prefix = "GW_"
        env_file = ".env"
