from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gateway_url: str = "http://localhost:8002"
    simulator_url: str = "http://localhost:8001"
    n_trials: int = 100
    workflow: str = "investment_decision"  # or "portfolio_rebalancing"

    model_config = {"env_prefix": "AGENT_"}


settings = Settings()
