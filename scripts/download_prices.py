"""
Download daily stock prices from Yahoo Finance.

Saves one CSV per ticker:
  data/{Sector}/{TICKER}/price.csv

The script reads tickers from the sector CSV files in the tickers directory.
It prefers the existing data/ticker_sector_mapping.csv sectors so prices
are saved next to already downloaded fundamental data.
"""

from __future__ import annotations

import argparse
import csv
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from tqdm import tqdm

try:
    import yfinance as yf
except ImportError as exc:
    raise SystemExit(
        "Package yfinance is not installed. Install it with:\n"
        "  python -m pip install yfinance\n"
        "or for a specific Python version:\n"
        "  py -3.12 -m pip install yfinance"
    ) from exc


PROJECT_DIR = Path(__file__).resolve().parent.parent
TICKERS_DIR = PROJECT_DIR / "tickers"
DATA_DIR = PROJECT_DIR / "data"
LOG_FILE = PROJECT_DIR / "download_prices_log.txt"
MAPPING_FILE = DATA_DIR / "ticker_sector_mapping.csv"

START_DATE = "2005-01-01"
PRICE_FILE_NAME = "price.csv"
MAX_WORKERS = 8
RETRY_ATTEMPTS = 3
RETRY_DELAY = 3
DEFAULT_SECTOR = "Unknown"
DEFAULT_TICKER_FILES = [
    "consumer-staples-list.csv",
    "energy-list.csv",
    "industrials-list.csv",
]


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def normalize_ticker(ticker: str) -> str:
    """Normalize ticker symbols read from source CSV files."""
    return ticker.strip().strip('"').upper()


def yahoo_symbol(ticker: str) -> str:
    """Yahoo Finance uses '-' instead of '.' for share classes."""
    return ticker.replace(".", "-")


def normalize_sector(sector: str | None) -> str:
    if not sector:
        return DEFAULT_SECTOR
    sector = sector.strip().strip('"')
    if sector.lower() in {"nan", "none"}:
        return DEFAULT_SECTOR
    return sector if sector else DEFAULT_SECTOR


def load_sector_mapping(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    mapping_df = pd.read_csv(path)
    if not {"ticker", "sector"}.issubset(mapping_df.columns):
        return {}

    mapping_df["ticker"] = mapping_df["ticker"].astype(str).map(normalize_ticker)
    mapping_df["sector"] = mapping_df["sector"].astype(str).map(normalize_sector)
    return dict(zip(mapping_df["ticker"], mapping_df["sector"]))


def load_tickers_from_file(path: Path) -> list[tuple[str, str | None]]:
    tickers: list[tuple[str, str | None]] = []

    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        first_row = next(reader, [])
        if not first_row:
            return tickers

        normalized_header = [col.strip().lower() for col in first_row]
        if "symbol" in normalized_header:
            ticker_idx = normalized_header.index("symbol")
            sector_idx = (
                normalized_header.index("sector")
                if "sector" in normalized_header
                else None
            )
            rows = reader
        else:
            ticker_idx = 3
            sector_idx = None
            rows = [first_row, *reader]

        for row in rows:
            if len(row) <= ticker_idx:
                continue

            ticker = normalize_ticker(row[ticker_idx])
            if not ticker or ticker in {"SYMBOL", "TICKER"}:
                continue

            sector = None
            if sector_idx is not None and len(row) > sector_idx:
                sector = normalize_sector(row[sector_idx])

            tickers.append((ticker, sector))

    logger.info("%s: loaded tickers: %s", path.name, len(tickers))
    return tickers


def load_tickers(paths: list[Path], sector_mapping: dict[str, str]) -> list[tuple[str, str]]:
    tickers: list[tuple[str, str]] = []
    seen: set[str] = set()

    for path in paths:
        for ticker, source_sector in load_tickers_from_file(path):
            if ticker in seen:
                continue
            seen.add(ticker)
            sector = sector_mapping.get(ticker) or source_sector or DEFAULT_SECTOR
            tickers.append((ticker, normalize_sector(sector)))

    logger.info("Unique tickers: %s", len(tickers))
    return tickers


def flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df.columns, pd.MultiIndex):
        return df

    # yf.download can return a MultiIndex even for a single ticker.
    df = df.copy()
    price_columns = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
    normalized_columns = []
    for col in df.columns.to_flat_index():
        parts = [str(part) for part in col if str(part)]
        normalized_columns.append(
            next((part for part in parts if part in price_columns), parts[0] if parts else "")
        )

    df.columns = normalized_columns
    return df


def normalize_price_df(df: pd.DataFrame) -> pd.DataFrame:
    df = flatten_columns(df)
    if df.empty:
        return df

    df = df.reset_index()
    rename_map = {
        "Date": "date",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Adj Close": "adj_close",
        "Volume": "volume",
    }
    df.rename(columns=rename_map, inplace=True)
    df = df.loc[:, ~df.columns.duplicated()]

    expected_columns = ["date", "open", "high", "low", "close", "adj_close", "volume"]
    available_columns = [col for col in expected_columns if col in df.columns]
    df = df[available_columns]

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)

    return df


def download_prices(ticker: str, start_date: str) -> pd.DataFrame:
    symbol = yahoo_symbol(ticker)

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            df = yf.download(
                symbol,
                start=start_date,
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            return normalize_price_df(df)
        except Exception as exc:
            logger.warning(
                "[%s] attempt %s/%s failed: %s",
                ticker,
                attempt,
                RETRY_ATTEMPTS,
                exc,
            )
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY * attempt)

    return pd.DataFrame()


def save_prices(ticker: str, sector: str, prices: pd.DataFrame) -> Path:
    output_path = DATA_DIR / sector / ticker / PRICE_FILE_NAME
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prices.to_csv(output_path, index=False, encoding="utf-8-sig")
    return output_path


def process_ticker(ticker: str, sector: str, start_date: str, skip_existing: bool) -> tuple[str, str, int]:
    output_path = DATA_DIR / sector / ticker / PRICE_FILE_NAME
    if skip_existing and output_path.exists():
        return ticker, "skipped", 0

    prices = download_prices(ticker, start_date)
    if prices.empty:
        logger.warning("[%s] no price data returned", ticker)
        return ticker, "empty", 0

    save_prices(ticker, sector, prices)
    logger.info("[%s] saved %s rows -> %s", ticker, len(prices), output_path)
    return ticker, "saved", len(prices)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download daily prices from Yahoo Finance.")
    parser.add_argument("--start", default=START_DATE, help="Start date, YYYY-MM-DD.")
    parser.add_argument(
        "--ticker-files",
        nargs="+",
        default=DEFAULT_TICKER_FILES,
        help="Ticker CSV file names from the tickers directory.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=MAX_WORKERS,
        help="Number of parallel downloads.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Do not redownload tickers that already have price.csv.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Download only the first N tickers, useful for a test run.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ticker_files = [TICKERS_DIR / file_name for file_name in args.ticker_files]
    missing_files = [path for path in ticker_files if not path.exists()]
    if missing_files:
        missing = ", ".join(str(path) for path in missing_files)
        raise SystemExit(f"Ticker files not found: {missing}")

    sector_mapping = load_sector_mapping(MAPPING_FILE)
    tickers = load_tickers(ticker_files, sector_mapping)

    if args.limit is not None:
        tickers = tickers[: args.limit]

    logger.info("Start date: %s", args.start)
    logger.info("Parallel workers: %s", args.workers)
    logger.info("Skip existing: %s", args.skip_existing)

    stats = {"saved": 0, "empty": 0, "skipped": 0, "failed": 0}

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_ticker = {
            executor.submit(
                process_ticker,
                ticker,
                sector,
                args.start,
                args.skip_existing,
            ): ticker
            for ticker, sector in tickers
        }

        with tqdm(total=len(future_to_ticker), desc="Downloading prices", unit="ticker") as pbar:
            for future in as_completed(future_to_ticker):
                ticker = future_to_ticker[future]
                try:
                    _, status, _ = future.result()
                    stats[status] = stats.get(status, 0) + 1
                except Exception as exc:
                    stats["failed"] += 1
                    logger.error("[FATAL] %s: %s", ticker, exc, exc_info=True)
                finally:
                    pbar.update(1)

    logger.info("Done. Stats: %s", stats)


if __name__ == "__main__":
    main()
