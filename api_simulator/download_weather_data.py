from __future__ import annotations

from datetime import datetime
from pathlib import Path

import meteostat as ms
import pandas as pd


# Time range to download
starting_time = datetime(2026, 1, 1, 0)
ending_time = datetime(2026, 3, 30, 0)

# Airport IATA code -> Meteostat station ID
airport_to_station = {
    "ATL": "KFTY0",
    "DFW": "72259",
    "DEN": "72565",
    "ORD": "72530",
    "LAX": "72295",
    "JFK": "74486",
    "CLT": "72314",
    "LAS": "72386",
    "MCO": "72205",
    "MIA": "72202",
    "PHX": "72278",
    "SEA": "72793",
    "SFO": "72494",
    "EWR": "72502",
    "IAH": "72243",
    "BOS": "72509",
    "MSP": "72658",
    "FLL": "74783",
    "LGA": "72503",
    "DTW": "KYIP0",
}


def download_hourly_weather_data(
    airport_code: str,
    station_id: str,
    start_time: datetime,
    end_time: datetime,
) -> pd.DataFrame:
    """
    Download hourly weather data for one airport/station and return it as a DataFrame.
    """
    station = ms.Station(station_id)
    ts = ms.hourly(station, start_time, end_time)
    df = ts.fetch().reset_index()

    df.insert(0, "airport_code", airport_code)
    df.insert(1, "station_id", station_id)

    return df


def main() -> None:
    all_dataframes = []

    for airport_code, station_id in airport_to_station.items():
        try:
            df = download_hourly_weather_data(
                airport_code=airport_code,
                station_id=station_id,
                start_time=starting_time,
                end_time=ending_time,
            )
            all_dataframes.append(df)
            print(f"Downloaded {airport_code} with {len(df)} rows")
        except Exception as e:
            print(f"Failed to download data for {airport_code} ({station_id}): {e}")

    if not all_dataframes:
        print("No data was downloaded.")
        return

    combined_df = pd.concat(all_dataframes, ignore_index=True)

    output_dir = Path("weather_data")
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / "all_airports_hourly_weather.csv"
    combined_df.to_csv(output_file, index=False)

    print(f"Saved combined data to {output_file} with {len(combined_df)} total rows")


if __name__ == "__main__":
    main()