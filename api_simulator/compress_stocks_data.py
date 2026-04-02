"""
Compress stock CSV timestamps to fixed spacing while preserving all datapoints.

The input CSV is expected to look like:

    Datetime,<ticker1>,<ticker2>,...

The output keeps every stock value unchanged and rewrites only the timestamp
column so row n becomes:

    first_timestamp + (n * step_seconds)

With the default step of 20 seconds, an 8-day 1-minute dataset becomes
roughly 8/3 days long while keeping the same number of rows.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile


SCRIPT_DIR = Path(__file__).resolve().parent
STOCK_DATA_DIR = SCRIPT_DIR / "stock_data"
DEFAULT_STEP_SECONDS = 20
DEFAULT_OUTPUT_NAME = "compressed_stocks_data.csv"


def _parse_timestamp(raw: str) -> datetime:
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"unsupported timestamp format: {raw!r}") from exc


def compress_csv_timestamps(
    input_file: Path,
    output_file: Path,
    step_seconds: int = DEFAULT_STEP_SECONDS,
) -> Path:
    if step_seconds <= 0:
        raise ValueError("step_seconds must be positive")

    input_file = Path(input_file)
    output_file = Path(output_file)

    with input_file.open(newline="") as src:
        reader = csv.reader(src)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError(f"input CSV is empty: {input_file}") from exc

        try:
            first_row = next(reader)
        except StopIteration as exc:
            raise ValueError(f"input CSV has no data rows: {input_file}") from exc

        start_time = _parse_timestamp(first_row[0])
        rows = [first_row, *reader]

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        newline="",
        dir=output_file.parent,
        delete=False,
        encoding="utf-8",
    ) as tmp_file:
        writer = csv.writer(tmp_file)
        writer.writerow(header)

        for index, row in enumerate(rows):
            row_time = start_time + timedelta(seconds=index * step_seconds)
            updated_row = list(row)
            updated_row[0] = row_time.isoformat(sep=" ")
            writer.writerow(updated_row)

        temp_path = Path(tmp_file.name)

    temp_path.replace(output_file)
    return output_file


def _resolve_input_path(input_file: Path) -> Path:
    if input_file.is_absolute():
        return input_file

    direct_path = Path.cwd() / input_file
    if direct_path.exists():
        return direct_path

    return STOCK_DATA_DIR / input_file


def _resolve_output_path(output_file: Path) -> Path:
    if output_file.is_absolute():
        return output_file

    return STOCK_DATA_DIR / output_file


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compress stock CSV timestamps to fixed spacing.",
    )
    parser.add_argument(
        "--input-file",
        type=Path,
        required=True,
        help=(
            "Path to the source stock CSV. Relative paths are resolved against the "
            "current working directory first, then api_simulator/stock_data."
        ),
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=None,
        help=(
            "Path to the output CSV. Relative paths are written under "
            "api_simulator/stock_data. Defaults to compressed_stocks_data.csv there."
        ),
    )
    parser.add_argument(
        "--step-seconds",
        type=int,
        default=DEFAULT_STEP_SECONDS,
        help=f"Spacing between rows in seconds. Default: {DEFAULT_STEP_SECONDS}.",
    )
    args = parser.parse_args()

    input_file = _resolve_input_path(args.input_file)
    output_file = args.output_file
    if output_file is None:
        output_file = STOCK_DATA_DIR / DEFAULT_OUTPUT_NAME
    else:
        output_file = _resolve_output_path(output_file)

    written_file = compress_csv_timestamps(
        input_file=input_file,
        output_file=output_file,
        step_seconds=args.step_seconds,
    )
    print(f"Wrote compressed data to {written_file}")


if __name__ == "__main__":
    main()
