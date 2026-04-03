"""
Download relevant stock data for the API caching experiment using the yfinance library.

See this for downloading data syntax:
https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html

See this for how to get the data via the .history call:
https://ranaroussi.github.io/yfinance/reference/api/yfinance.Tickers.html


To limit data overload, we only download a small set of carefully chosen tickers rather than a huge universe of stock. 

The goal is not to model the full market, but rather to gather enough realistic price series to simulate mock API calls under different cache policies.

In particular, I've chosen a mix of common, recognizable stocks and more volatile stocks (to increase the chance that stale cached prices actually influence correctness/staleness/

The downloaded data will be stored locally and later replayed by the mock API simulator.

This is important because the actual experiment should not depend on live API/library calls as external factors may introduce untwanted noise/latency.

Later, the mock API simulator will replay this saved data as if it were serving real stock-price requests.

"""



# Common Recoganizable Stocks: , Google (GOOG), Tesla (TSLA), Nvidia (NVDA), Meta (META)

# More volatile stocks: Coinbase (COIN), Mara Holdings (MARA), Hut 8 (HUT), SoundHound AI (SOUN), Riot Platforms (RIOT), IREN Limited (IREN)



from __future__ import annotations

from pathlib import Path

import yfinance as yf


STOCK_DATA_DIR = Path(__file__).with_name("stock_data")
OUTPUT_FILE = STOCK_DATA_DIR / "stocks_data.csv"



tickers = ['GOOG', 'TSLA', 'NVDA', 'META', 'AAPL', 'COIN', 'MARA', 'HUT', 'SOUN', 'RIOT', 'IREN']


df = yf.download(
    tickers=tickers,
    period = "8d",
    interval="1m",
    group_by="ticker",
    auto_adjust=False,
    actions=False,
    prepost=False,
)

open_df = df.xs("Open", axis=1, level=1)
STOCK_DATA_DIR.mkdir(parents=True, exist_ok=True)
open_df.to_csv(OUTPUT_FILE)
print(open_df.head())
