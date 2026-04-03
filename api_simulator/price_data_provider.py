"""
Replay compressed stock price data at fixed intervals from a local CSV.
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path


class PriceDataError(Exception):
    """Base class for price playback failures."""


class UnknownTickerError(PriceDataError):
    """Raised when a requested ticker is not present in the CSV."""


class PriceDataExhaustedError(PriceDataError):
    """Raised when playback runs past the final CSV row."""


@dataclass(frozen=True)
class PriceSnapshot:
    value: float
    version: int
    last_changed_at: float


class PriceDataProvider:
    def __init__(
        self,
        csv_path: Path,
        step_seconds: float,
        playback_start_time: float | None = None,
    ):
        if step_seconds <= 0:
            raise ValueError("price playback step_seconds must be positive")

        self._csv_path = Path(csv_path)
        self._step_seconds = float(step_seconds)
        self._prices_by_ticker = self._load_prices(self._csv_path)
        self._row_count = len(next(iter(self._prices_by_ticker.values())))
        self._playback_start_time = (
            time.time() if playback_start_time is None else playback_start_time
        )

    def get_snapshot(self, ticker: str, now: float | None = None) -> PriceSnapshot:
        if ticker not in self._prices_by_ticker:
            raise UnknownTickerError(
                f"ticker {ticker!r} is not available in {self._csv_path.name}"
            )

        current_time = time.time() if now is None else now
        row_index = self._active_row_index(current_time)
        prices = self._prices_by_ticker[ticker]

        return PriceSnapshot(
            value=prices[row_index],
            version=row_index + 1,
            last_changed_at=self._playback_start_time + row_index * self._step_seconds,
        )

    def _active_row_index(self, now: float) -> int:
        elapsed = max(0.0, now - self._playback_start_time)
        row_index = int(elapsed // self._step_seconds)

        if row_index >= self._row_count:
            duration_s = self._row_count * self._step_seconds
            raise PriceDataExhaustedError(
                "price playback exhausted after "
                f"{self._row_count} rows (~{duration_s:.0f}s) from "
                f"{self._csv_path.name}"
            )

        return row_index

    @staticmethod
    def _load_prices(csv_path: Path) -> dict[str, list[float]]:
        if not csv_path.exists():
            raise FileNotFoundError(f"price data file not found: {csv_path}")

        with csv_path.open(newline="", encoding="utf-8") as src:
            reader = csv.reader(src)
            try:
                header = next(reader)
            except StopIteration as exc:
                raise ValueError(f"price data file is empty: {csv_path}") from exc

            tickers = header[1:]
            if not tickers:
                raise ValueError(f"price data file has no ticker columns: {csv_path}")

            prices_by_ticker = {ticker: [] for ticker in tickers}
            for row_number, row in enumerate(reader, start=2):
                if len(row) != len(header):
                    raise ValueError(
                        f"row {row_number} in {csv_path} has {len(row)} columns; "
                        f"expected {len(header)}"
                    )

                for ticker, raw_value in zip(tickers, row[1:]):
                    if raw_value == "":
                        if not prices_by_ticker[ticker]:
                            raise ValueError(
                                f"row {row_number} in {csv_path} starts with a blank "
                                f"value for ticker {ticker}"
                            )
                        value = prices_by_ticker[ticker][-1]
                    else:
                        value = float(raw_value)

                    prices_by_ticker[ticker].append(value)

        row_count = len(next(iter(prices_by_ticker.values())))
        if row_count == 0:
            raise ValueError(f"price data file has no rows: {csv_path}")

        return prices_by_ticker
