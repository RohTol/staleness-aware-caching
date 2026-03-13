from typing import Literal
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Which caching policy to run. Set at startup via env var.
    #   none      — always call upstream, never cache (correctness baseline)
    #   fixed_ttl — one TTL per tool type, ignores workflow context
    policy: Literal["none", "fixed_ttl"] = "none"

    # Fixed TTL values per tool (seconds). Only used under fixed_ttl policy.
    # Ordered slowest→fastest change rate to make the mismatch obvious in experiments.
    ttl_trend_s: float = 600.0    # 10 min — trend changes ~every 15 min
    ttl_weather_s: float = 180.0  # 3 min  — weather changes ~every 3 min
    ttl_sentiment_s: float = 45.0 # 45s    — sentiment changes ~every 50s
    ttl_price_s: float = 20.0     # 20s    — price changes ~every 20s

    # URL of the API simulator
    simulator_url: str = "http://localhost:8001"

    # Port this gateway listens on
    port: int = 8002

    class Config:
        env_prefix = "GW_"
        env_file = ".env"
