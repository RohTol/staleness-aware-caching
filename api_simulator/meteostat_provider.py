"""
Meteostat-backed weather provider.

This module turns Meteostat lookups into a small, reusable interface that
the API simulator can call later as if it were an external weather service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, Optional, Tuple

from meteostat import Hourly, Point, Stations


@dataclass(frozen=True)
class WeatherObservation:
    lat: float
    lon: float
    station_id: str
    observed_at: datetime
    fetched_at: datetime
    temperature_c: Optional[float]
    precip_mm: Optional[float]
    wind_kph: Optional[float]
    pressure_hpa: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": "weather",
            "location": {
                "lat": self.lat,
                "lon": self.lon,
            },
            "station_id": self.station_id,
            "observed_at": self.observed_at.isoformat(),
            "fetched_at": self.fetched_at.isoformat(),
            "temperature_c": self.temperature_c,
            "precip_mm": self.precip_mm,
            "wind_kph": self.wind_kph,
            "pressure_hpa": self.pressure_hpa,
        }


class MeteostatWeatherProvider:
    """
    Thin adapter around Meteostat for "current weather at simulated time t".

    The provider resolves a nearest station for the given coordinates,
    fetches hourly observations for a configured time window, and returns
    the latest row at or before the requested timestamp.
    """

    def __init__(
        self,
        experiment_start: datetime,
        experiment_end: datetime,
        elevation_m: Optional[float] = None,
        coordinate_precision: int = 4,
    ) -> None:
        if experiment_start >= experiment_end:
            raise ValueError("experiment_start must be before experiment_end")
        self._experiment_start = _to_utc(experiment_start)
        self._experiment_end = _to_utc(experiment_end)
        self._elevation_m = elevation_m
        self._coordinate_precision = coordinate_precision

    def get_current_weather(self, lat: float, lon: float, at: datetime) -> Dict[str, Any]:
        at_utc = _to_utc(at)
        if at_utc < self._experiment_start or at_utc > self._experiment_end:
            raise ValueError(
                "requested time is outside the configured experiment window"
            )

        rounded_lat, rounded_lon = self._normalize_coordinates(lat, lon)
        station_id = self._resolve_station_id(rounded_lat, rounded_lon)
        hourly = self._load_hourly_data(
            station_id,
            self._experiment_start,
            self._experiment_end,
        )

        visible = hourly[hourly.index <= at_utc]
        if visible.empty:
            raise LookupError("no Meteostat observation is available at or before this time")

        row = visible.iloc[-1]
        observed_at = visible.index[-1].to_pydatetime()

        observation = WeatherObservation(
            lat=rounded_lat,
            lon=rounded_lon,
            station_id=station_id,
            observed_at=_to_utc(observed_at),
            fetched_at=at_utc,
            temperature_c=_maybe_float(row.get("temp")),
            precip_mm=_maybe_float(row.get("prcp")),
            wind_kph=_maybe_float(row.get("wspd")),
            pressure_hpa=_maybe_float(row.get("pres")),
        )
        return observation.to_dict()

    def _normalize_coordinates(self, lat: float, lon: float) -> Tuple[float, float]:
        return (
            round(lat, self._coordinate_precision),
            round(lon, self._coordinate_precision),
        )

    @lru_cache(maxsize=256)
    def _resolve_station_id(self, lat: float, lon: float) -> str:
        point = Point(lat, lon, self._elevation_m)
        stations = Stations()
        stations = stations.nearby(point.lat, point.lon)
        nearby = stations.fetch(1)
        if nearby.empty:
            raise LookupError(f"no nearby Meteostat station found for ({lat}, {lon})")
        return str(nearby.index[0])

    @lru_cache(maxsize=256)
    def _load_hourly_data(
        self,
        station_id: str,
        start: datetime,
        end: datetime,
    ):
        return Hourly(station_id, start, end).fetch()


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _maybe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except TypeError:
        pass
    return float(value)
