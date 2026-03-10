"""
Manages per-key state for weather and price endpoints.

Each key has:
  - value:           current data (temperature or price)
  - version:         monotonically increasing integer (incremented on each change)
  - last_changed_at: UTC timestamp of the last value change

A background asyncio loop drives Poisson-distributed updates independently
per key. Each key's time-to-next-change is sampled from Exp(lambda).
"""

import asyncio
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict

from config import Settings


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


def _make_price_entry() -> Entry:
    """Initial price: uniform $10–$500."""
    return Entry(
        value=random.uniform(10.0, 500.0),
        version=1,
        last_changed_at=time.time(),
    )


def _next_change_delay(rate: float) -> float:
    """Sample time to next change from Exp(rate)."""
    return random.expovariate(rate)


class SimulatorState:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._weather: Dict[str, Entry] = {}
        self._price: Dict[str, Entry] = {}

        # next_change[tool][key] = absolute time (time.time()) when next change fires
        self._next_weather_change: Dict[str, float] = {}
        self._next_price_change: Dict[str, float] = {}

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
        if ticker not in self._price:
            self._price[ticker] = _make_price_entry()
            self._next_price_change[ticker] = time.time() + _next_change_delay(
                self._settings.price_change_rate
            )
        return self._price[ticker]

    # ------------------------------------------------------------------
    # Background change loop
    # ------------------------------------------------------------------

    async def run_change_loop(self) -> None:
        """Periodically fire value changes for keys whose next-change time has passed."""
        interval = self._settings.change_loop_interval_s
        while True:
            now = time.time()
            self._tick_weather(now)
            self._tick_price(now)
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

    def _tick_price(self, now: float) -> None:
        for ticker in list(self._next_price_change):
            if now >= self._next_price_change[ticker]:
                entry = self._price[ticker]
                # Multiplicative random walk: ±0.1–1.5%
                pct = random.uniform(0.001, 0.015) * random.choice([-1, 1])
                entry.value = max(0.01, entry.value * (1 + pct))
                entry.version += 1
                entry.last_changed_at = now
                self._next_price_change[ticker] = now + _next_change_delay(
                    self._settings.price_change_rate
                )
