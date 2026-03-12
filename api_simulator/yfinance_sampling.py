"""
This script explains how to use yfinance for the sake of this project and tests basic library calls.

Refer to the yfinance documentation / PyPI page for in-depth explanations.

High level overview of yfinance: it uses ticker symbols to get stock market data
for a span of time. In order to find out the stock you want, enter its ticker
symbol (for example, AAPL for Apple).

"""

from __future__ import annotations

from datetime import datetime

import yfinance as yf


# ticker symbol for the stock you want, here is an example of Apple
TICKER_SYMBOL = "AAPL"

ticker = yf.Ticker(TICKER_SYMBOL)
print(ticker.ticker)


# How to get everything within a specified range
df = ticker.history(
    start="2026-03-02",
    end="2026-03-10",
    interval="1m"
)

# how to get everything within the last period timeframe
# df = ticker.history(period="700d", interval="1h")



print(df)
