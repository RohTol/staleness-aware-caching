from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Weather change rate: Poisson lambda (changes/sec). Default ~1 change per 3 min.
    weather_change_rate: float = 0.005

    # Price playback source and cadence.
    price_data_path: Path = (
        Path(__file__).resolve().parent / "stock_data" / "compressed_stocks_data.csv"
    )
    price_step_seconds: float = 20.0

    # Trend change rate: Poisson lambda (changes/sec). Default ~1 change per 15 min.
    # Represents a 30-day moving average — drifts very slowly relative to spot price.
    trend_change_rate: float = 0.001

    # News sentiment change rate: Poisson lambda (changes/sec). Default ~1 change per 50s.
    # Bursts when news breaks — faster than weather, slower than price.
    sentiment_change_rate: float = 0.02

    # Latency: lognormal parameters (ms). mean/std of the underlying normal distribution.
    weather_latency_mean_ms: float = 80.0
    weather_latency_std_ms: float = 30.0
    price_latency_mean_ms: float = 40.0
    price_latency_std_ms: float = 15.0
    trend_latency_mean_ms: float = 60.0
    trend_latency_std_ms: float = 20.0
    sentiment_latency_mean_ms: float = 50.0
    sentiment_latency_std_ms: float = 20.0

    # Probability of returning a 503 error on any request (0.0 = never)
    error_rate: float = 0.02

    # Optional rate limiting: max requests per second across all endpoints (0 = disabled)
    rate_limit_rps: int = 0

    # How often (seconds) the background change loop ticks
    change_loop_interval_s: float = 0.1

    # Port
    port: int = 8001

    class Config:
        env_prefix = "SIM_"
        env_file = ".env"
