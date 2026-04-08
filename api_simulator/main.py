"""
Dynamic API Simulator

Endpoints:
  GET /weather?city=<city>         — current temperature for a city (meteostat-backed)
  GET /price?ticker=<ticker>       — current stock price (CSV replay-backed)
  GET /trend?ticker=<ticker>       — 30-day moving average for a ticker (simulated)
  GET /news_sentiment?ticker=<t>   — news sentiment score in [-1.0, 1.0] (simulated)

All return:
  {
    "tool":            "weather" | "price" | "trend" | "news_sentiment",
    "key":             <city> | <ticker>,
    "value":           <float>,
    "version":         <int>,
    "last_changed_at": <ISO 8601 UTC>
  }

Change rates (slowest → fastest):
  trend:          ~1 change per 15 min
  weather:        ~1 change per 3 min
  news_sentiment: ~1 change per 50s
  price:          ~1 change per 20s

Configuration is via environment variables prefixed SIM_ (see config.py).
"""

import asyncio
import math
import random
import time

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from config import Settings
from price_data_provider import PriceDataExhaustedError, UnknownTickerError
from state import SimulatorState

settings = Settings()
state = SimulatorState(settings)

app = FastAPI(title="Dynamic API Simulator", version="1.0.0")

# ---------------------------------------------------------------------------
# Rate limiting (token bucket, optional)
# ---------------------------------------------------------------------------

_bucket_tokens: float = 0.0
_bucket_last_refill: float = time.time()


def _check_rate_limit() -> None:
    """Simple token-bucket rate limiter. Raises 429 if over limit."""
    global _bucket_tokens, _bucket_last_refill
    if settings.rate_limit_rps <= 0:
        return
    now = time.time()
    elapsed = now - _bucket_last_refill
    _bucket_last_refill = now
    _bucket_tokens = min(
        float(settings.rate_limit_rps),
        _bucket_tokens + elapsed * settings.rate_limit_rps,
    )
    if _bucket_tokens < 1.0:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    _bucket_tokens -= 1.0


# ---------------------------------------------------------------------------
# Latency injection
# ---------------------------------------------------------------------------

async def _inject_latency(mean_ms: float, std_ms: float) -> None:
    """Sleep for a lognormally distributed duration."""
    if mean_ms <= 0:
        return
    # Convert mean/std to lognormal mu/sigma
    variance = std_ms ** 2
    mu = math.log(mean_ms ** 2 / math.sqrt(variance + mean_ms ** 2))
    sigma = math.sqrt(math.log(1 + variance / mean_ms ** 2))
    delay_ms = random.lognormvariate(mu, sigma)
    await asyncio.sleep(delay_ms / 1000.0)


# ---------------------------------------------------------------------------
# Error injection
# ---------------------------------------------------------------------------

def _maybe_error() -> None:
    if settings.error_rate > 0 and random.random() < settings.error_rate:
        raise HTTPException(status_code=503, detail="Simulated upstream error")


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(UnknownTickerError)
async def handle_unknown_ticker(_: Request, exc: UnknownTickerError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(PriceDataExhaustedError)
async def handle_price_data_exhausted(_: Request, exc: PriceDataExhaustedError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup() -> None:
    asyncio.create_task(state.run_change_loop())


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/weather")
async def get_weather(city: str = Query(..., description="City name")):
    _check_rate_limit()
    _maybe_error()
    await _inject_latency(settings.weather_latency_mean_ms, settings.weather_latency_std_ms)
    entry = state.get_weather(city)
    return entry.to_dict(tool="weather", key=city)


@app.get("/price")
async def get_price(ticker: str = Query(..., description="Ticker symbol")):
    _check_rate_limit()
    _maybe_error()
    await _inject_latency(settings.price_latency_mean_ms, settings.price_latency_std_ms)
    entry = state.get_price(ticker)
    return entry.to_dict(tool="price", key=ticker)


@app.get("/trend")
async def get_trend(ticker: str = Query(..., description="Ticker symbol")):
    """30-day moving average for a ticker. Changes much more slowly than spot price."""
    _check_rate_limit()
    _maybe_error()
    await _inject_latency(settings.trend_latency_mean_ms, settings.trend_latency_std_ms)
    entry = state.get_trend(ticker)
    return entry.to_dict(tool="trend", key=ticker)


@app.get("/news_sentiment")
async def get_news_sentiment(ticker: str = Query(..., description="Ticker symbol")):
    """News sentiment score in [-1.0, 1.0]. Jumps significantly when news breaks."""
    _check_rate_limit()
    _maybe_error()
    await _inject_latency(settings.sentiment_latency_mean_ms, settings.sentiment_latency_std_ms)
    entry = state.get_sentiment(ticker)
    return entry.to_dict(tool="news_sentiment", key=ticker)


@app.post("/reset")
async def reset():
    """Reset price playback to row 0. Call between experiments for reproducibility."""
    state.reset_price_playback()
    return {"status": "reset", "message": "price playback reset to row 0"}


@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=False)
