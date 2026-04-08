"""
Per-ticker calibrated reference prices for the investment_decision workflow.

Reference price is computed from compressed_stocks_data.csv as:

    reference_price = median(prices) / (1 - PRICE_DROP_THRESHOLD)

This places the median price exactly at the -2% drop boundary, so roughly
50% of simulated-time intervals trigger the news_sentiment branch and ~50%
trigger the trend branch — ensuring both branches are exercised meaningfully
for every ticker.
"""

import csv
import os
import statistics

_CSV_PATH = os.path.join(
    os.path.dirname(__file__),
    "../api_simulator/stock_data/compressed_stocks_data.csv",
)

# All tickers present in compressed_stocks_data.csv.
TICKERS = ["AAPL", "GOOG", "TSLA", "NVDA", "META", "COIN", "MARA", "HUT", "SOUN", "RIOT", "IREN"]

_PRICE_DROP_THRESHOLD = 0.005  # must match investment_decision.PRICE_DROP_THRESHOLD


def _compute() -> dict[str, float]:
    raw: dict[str, list[float]] = {t: [] for t in TICKERS}
    with open(_CSV_PATH, newline="") as f:
        for row in csv.DictReader(f):
            for t in TICKERS:
                val = row.get(t, "").strip()
                if val:
                    try:
                        raw[t].append(float(val))
                    except ValueError:
                        pass
    result: dict[str, float] = {}
    factor = 1.0 - _PRICE_DROP_THRESHOLD  # 0.98
    for t, vals in raw.items():
        if vals:
            result[t] = round(statistics.median(vals) / factor, 4)
    return result


# Loaded once at import time.
TICKER_REFERENCE_PRICES: dict[str, float] = _compute()
