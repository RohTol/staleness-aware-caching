from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gateway_url: str = "http://localhost:8002"
    simulator_url: str = "http://localhost:8001"
    n_trials: int = 0           # 0 = run indefinitely; >0 = stop after this many total trials
    workflow: str = "investment_decision"  # or "portfolio_rebalancing"
    output_csv: str = "results.csv"
    interval_seconds: float = 0.0  # seconds to sleep between rounds; 0 = run continuously

    model_config = {"env_prefix": "AGENT_"}


settings = Settings()
