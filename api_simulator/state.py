"""
Manages per-key state for weather, price, trend, and news_sentiment endpoints.

Each key has:
  - value:           current data (temperature, price, moving average, or sentiment score)
  - version:         monotonically increasing integer (incremented on each change)
  - last_changed_at: UTC timestamp of the last value change

A background asyncio loop drives Poisson-distributed updates for the simulated
weather, trend, and news_sentiment values. Price is replayed deterministically
from a prerecorded CSV at fixed 20-second intervals.

Change rate summary (slowest → fastest):
  trend:         ~1 change per 15 min  (30-day moving average drifts slowly)
  weather:       ~1 change per 3 min   (hourly updates from meteostat)
  news_sentiment:~1 change per 50s     (bursts when news breaks)
  price:         every 20s             (replayed from compressed stock CSV)
"""

import asyncio
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict

from config import Settings
from price_data_provider import PriceDataProvider


@dataclass
class Entry:
    value: float
    version: int
    last_changed_at: float  # Unix timestamp

    def to_dict(self, tool: str, key: str) -> dict:
        return {
            "tool": tool,
            "key": key,
            "value": round(self.value, 4),
            "version": self.version,
            "last_changed_at": datetime.fromtimestamp(
                self.last_changed_at, tz=timezone.utc
            ).isoformat(),
        }


def _make_weather_entry() -> Entry:
    """Initial temperature: uniform 20–95°F."""
    return Entry(
        value=random.uniform(20.0, 95.0),
        version=1,
        last_changed_at=time.time(),
    )


def _make_trend_entry(price: float) -> Entry:
    """Initial 30-day moving average: seeded near the current price ±5%."""
    return Entry(
        value=price * random.uniform(0.95, 1.05),
        version=1,
        last_changed_at=time.time(),
    )


def _make_sentiment_entry() -> Entry:
    """Initial news sentiment: uniform -0.5 to 0.5 (neutral-ish)."""
    return Entry(
        value=random.uniform(-0.5, 0.5),
        version=1,
        last_changed_at=time.time(),
    )


def _next_change_delay(rate: float) -> float:
    """Sample time to next change from Exp(rate)."""
    return random.expovariate(rate)


class SimulatorState:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._price_data = PriceDataProvider(
            csv_path=settings.price_data_path,
            step_seconds=settings.price_step_seconds,
        )
        self._weather: Dict[str, Entry] = {}
        self._trend: Dict[str, Entry] = {}
        self._sentiment: Dict[str, Entry] = {}

        # next_change[tool][key] = absolute time (time.time()) when next change fires
        self._next_weather_change: Dict[str, float] = {}
        self._next_trend_change: Dict[str, float] = {}
        self._next_sentiment_change: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public accessors (lazy init)
    # ------------------------------------------------------------------

    def get_weather(self, city: str) -> Entry:
        if city not in self._weather:
            self._weather[city] = _make_weather_entry()
            self._next_weather_change[city] = time.time() + _next_change_delay(
                self._settings.weather_change_rate
            )
        return self._weather[city]

    def get_price(self, ticker: str) -> Entry:
        snapshot = self._price_data.get_snapshot(ticker, now=time.time())
        return Entry(
            value=snapshot.value,
            version=snapshot.version,
            last_changed_at=snapshot.last_changed_at,
        )

    def get_trend(self, ticker: str) -> Entry:
        """30-day moving average for a ticker. Seeded near the current price."""
        if ticker not in self._trend:
            price = self.get_price(ticker).value
            self._trend[ticker] = _make_trend_entry(price)
            self._next_trend_change[ticker] = time.time() + _next_change_delay(
                self._settings.trend_change_rate
            )
        return self._trend[ticker]

    def get_sentiment(self, ticker: str) -> Entry:
        """News sentiment score for a ticker in [-1.0, 1.0]."""
        if ticker not in self._sentiment:
            self._sentiment[ticker] = _make_sentiment_entry()
            self._next_sentiment_change[ticker] = time.time() + _next_change_delay(
                self._settings.sentiment_change_rate
            )
        return self._sentiment[ticker]

    def reset_all(self) -> None:
        """Reset price playback to row 0 AND clear all mutable state (trend, sentiment, weather).
        Mutable state will be lazily re-initialized on next access, giving each experiment
        a fresh starting point and making cross-policy comparisons fair."""
        self._price_data._playback_start_time = time.time()
        self._weather.clear()
        self._trend.clear()
        self._sentiment.clear()
        self._next_weather_change.clear()
        self._next_trend_change.clear()
        self._next_sentiment_change.clear()

    def reset_price_playback(self) -> None:
        """Reset price CSV playback to row 0 (resets the market clock to now)."""
        self._price_data._playback_start_time = time.time()

    # ------------------------------------------------------------------
    # Background change loop
    # ------------------------------------------------------------------

    async def run_change_loop(self) -> None:
        """Periodically fire value changes for mutable keys."""
        interval = self._settings.change_loop_interval_s
        while True:
            now = time.time()
            self._tick_weather(now)
            self._tick_trend(now)
            self._tick_sentiment(now)
            await asyncio.sleep(interval)

    def _tick_weather(self, now: float) -> None:
        for city in list(self._next_weather_change):
            if now >= self._next_weather_change[city]:
                entry = self._weather[city]
                # Random walk: ±0.5–5°F
                delta = random.uniform(0.5, 5.0) * random.choice([-1, 1])
                entry.value = max(-30.0, min(130.0, entry.value + delta))
                entry.version += 1
                entry.last_changed_at = now
                self._next_weather_change[city] = now + _next_change_delay(
                    self._settings.weather_change_rate
                )

    def _tick_trend(self, now: float) -> None:
        for ticker in list(self._next_trend_change):
            if now >= self._next_trend_change[ticker]:
                entry = self._trend[ticker]
                # Very slow drift: ±0.05–0.2% (moving average lags price significantly)
                pct = random.uniform(0.0005, 0.002) * random.choice([-1, 1])
                entry.value = max(0.01, entry.value * (1 + pct))
                entry.version += 1
                entry.last_changed_at = now
                self._next_trend_change[ticker] = now + _next_change_delay(
                    self._settings.trend_change_rate
                )

    def _tick_sentiment(self, now: float) -> None:
        for ticker in list(self._next_sentiment_change):
            if now >= self._next_sentiment_change[ticker]:
                entry = self._sentiment[ticker]
                # Burst model: sentiment jumps significantly when news breaks (±0.2–0.6)
                delta = random.uniform(0.2, 0.6) * random.choice([-1, 1])
                entry.value = max(-1.0, min(1.0, entry.value + delta))
                entry.version += 1
                entry.last_changed_at = now
                self._next_sentiment_change[ticker] = now + _next_change_delay(
                    self._settings.sentiment_change_rate
                )
