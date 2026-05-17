"""
Загрузка фундаментальных данных с Alpha Vantage API.

Структура сохранения:
  data/{Sector}/{TICKER}/
    overview.csv
    income_statement_annual.csv
    income_statement_quarterly.csv
    balance_sheet_annual.csv
    balance_sheet_quarterly.csv
    cash_flow_annual.csv
    cash_flow_quarterly.csv
    earnings_annual.csv
    earnings_quarterly.csv

Лимит: 75 запросов в минуту (premium key).
"""

import os
import csv
import time
import json
import logging
import threading
import requests
import pandas as pd
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

API_KEY = "K2F43OVK516APWKU"
BASE_URL = "https://www.alphavantage.co/query"

TICKERS_CSV_FILES = [
    Path(__file__).parent.parent / "tickers" / "consumer-staples-list.csv",
    Path(__file__).parent.parent / "tickers" / "energy-list.csv",
    Path(__file__).parent.parent / "tickers" / "industrials-list.csv",
]
DATA_DIR = Path(__file__).parent.parent / "data"
LOG_FILE = Path(__file__).parent.parent / "download_log.txt"

CALLS_PER_MINUTE = 70        # чуть меньше лимита для надёжности
MAX_WORKERS = 10             # параллельных потоков
RETRY_ATTEMPTS = 3           # повторных попыток при ошибке
RETRY_DELAY = 5              # секунд между повторными попытками
DEFAULT_SECTOR = "Unknown"   # сектор если OVERVIEW не вернул данные

# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate limiter — не превышаем CALLS_PER_MINUTE вызовов в минуту
# ---------------------------------------------------------------------------

class RateLimiter:
    """Контролирует частоту API-запросов глобально по всем потокам."""

    def __init__(self, calls_per_minute: int):
        self._interval = 60.0 / calls_per_minute
        self._lock = threading.Lock()
        self._last_call_ts = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            sleep_for = self._interval - (now - self._last_call_ts)
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._last_call_ts = time.monotonic()


RATE_LIMITER = RateLimiter(CALLS_PER_MINUTE)


# ---------------------------------------------------------------------------
# HTTP-запрос с ретраями
# ---------------------------------------------------------------------------

def api_get(function: str, symbol: str, extra_params: dict | None = None) -> dict:
    """Делает GET-запрос к Alpha Vantage API с rate limiting и ретраями."""
    params = {
        "function": function,
        "symbol": symbol,
        "apikey": API_KEY,
    }
    if extra_params:
        params.update(extra_params)

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            RATE_LIMITER.wait()
            resp = requests.get(BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            # AV возвращает ошибки внутри JSON
            if "Error Message" in data:
                logger.warning(f"[{symbol}] AV error ({function}): {data['Error Message']}")
                return {}
            if "Note" in data:
                # лимит — ждём минуту и повторяем
                logger.warning(f"[{symbol}] Rate limit hit, sleeping 60s...")
                time.sleep(60)
                continue
            if "Information" in data:
                logger.warning(f"[{symbol}] AV info ({function}): {data['Information'][:100]}")
                return {}

            return data

        except requests.RequestException as exc:
            logger.warning(f"[{symbol}] attempt {attempt}/{RETRY_ATTEMPTS} failed: {exc}")
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY * attempt)

    logger.error(f"[{symbol}] All retries exhausted for {function}")
    return {}


# ---------------------------------------------------------------------------
# Парсинг и сохранение
# ---------------------------------------------------------------------------

def save_df(df: pd.DataFrame, path: Path):
    """Сохраняет DataFrame в CSV, создаёт директории при необходимости."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def overview_to_df(data: dict) -> pd.DataFrame:
    """Company Overview → однострочный DataFrame."""
    if not data:
        return pd.DataFrame()
    return pd.DataFrame([data])


def reports_to_df(reports: list[dict]) -> pd.DataFrame:
    """Список отчётных периодов → DataFrame с датой в качестве первого столбца."""
    if not reports:
        return pd.DataFrame()
    df = pd.DataFrame(reports)
    if "fiscalDateEnding" in df.columns:
        df["fiscalDateEnding"] = pd.to_datetime(df["fiscalDateEnding"])
        df.sort_values("fiscalDateEnding", inplace=True)
        df.reset_index(drop=True, inplace=True)
    return df


def earnings_to_df(records: list[dict]) -> pd.DataFrame:
    """Список данных по прибыли на акцию → DataFrame."""
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    if "fiscalDateEnding" in df.columns:
        df["fiscalDateEnding"] = pd.to_datetime(df["fiscalDateEnding"])
        df.sort_values("fiscalDateEnding", inplace=True)
        df.reset_index(drop=True, inplace=True)
    return df


# ---------------------------------------------------------------------------
# Загрузка всех данных по одному тикеру
# ---------------------------------------------------------------------------

def process_ticker(symbol: str) -> tuple[str, str]:
    """
    Загружает все фундаментальные данные для одного тикера.
    Возвращает (symbol, sector).
    """
    sector = DEFAULT_SECTOR

    try:
        # --- OVERVIEW ---
        ov_data = api_get("OVERVIEW", symbol)
        if ov_data:
            sector = ov_data.get("Sector", DEFAULT_SECTOR).title()
            if not sector or sector.strip() == "":
                sector = DEFAULT_SECTOR
        
        ticker_dir = DATA_DIR / sector / symbol

        if ov_data:
            save_df(overview_to_df(ov_data), ticker_dir / "overview.csv")

        # --- INCOME STATEMENT ---
        is_data = api_get("INCOME_STATEMENT", symbol)
        if is_data:
            ann = reports_to_df(is_data.get("annualReports", []))
            qrt = reports_to_df(is_data.get("quarterlyReports", []))
            if not ann.empty:
                save_df(ann, ticker_dir / "income_statement_annual.csv")
            if not qrt.empty:
                save_df(qrt, ticker_dir / "income_statement_quarterly.csv")

        # --- BALANCE SHEET ---
        bs_data = api_get("BALANCE_SHEET", symbol)
        if bs_data:
            ann = reports_to_df(bs_data.get("annualReports", []))
            qrt = reports_to_df(bs_data.get("quarterlyReports", []))
            if not ann.empty:
                save_df(ann, ticker_dir / "balance_sheet_annual.csv")
            if not qrt.empty:
                save_df(qrt, ticker_dir / "balance_sheet_quarterly.csv")

        # --- CASH FLOW ---
        cf_data = api_get("CASH_FLOW", symbol)
        if cf_data:
            ann = reports_to_df(cf_data.get("annualReports", []))
            qrt = reports_to_df(cf_data.get("quarterlyReports", []))
            if not ann.empty:
                save_df(ann, ticker_dir / "cash_flow_annual.csv")
            if not qrt.empty:
                save_df(qrt, ticker_dir / "cash_flow_quarterly.csv")

        # --- EARNINGS ---
        earn_data = api_get("EARNINGS", symbol)
        if earn_data:
            ann = earnings_to_df(earn_data.get("annualEarnings", []))
            qrt = earnings_to_df(earn_data.get("quarterlyEarnings", []))
            if not ann.empty:
                save_df(ann, ticker_dir / "earnings_annual.csv")
            if not qrt.empty:
                save_df(qrt, ticker_dir / "earnings_quarterly.csv")

        logger.info(f"[OK] {symbol} → {sector}")

    except Exception as exc:
        logger.error(f"[FAIL] {symbol}: {exc}", exc_info=True)

    return symbol, sector


# ---------------------------------------------------------------------------
# Чтение тикеров из CSV
# ---------------------------------------------------------------------------

def load_tickers(paths: list[Path]) -> list[str]:
    """Читает список тикеров из CSV-файлов разных форматов."""
    tickers = []
    for path in paths:
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            first_row = next(reader, [])
            if not first_row:
                continue

            normalized_header = [col.strip().lower() for col in first_row]
            if "symbol" in normalized_header:
                ticker_idx = normalized_header.index("symbol")
                rows = reader
            else:
                ticker_idx = 3
                rows = [first_row, *reader]

            file_count = 0
            for row in rows:
                if len(row) <= ticker_idx:
                    continue
                ticker = row[ticker_idx].strip().strip('"')
                if ticker and ticker.upper() not in ("SYMBOL", "TICKER"):
                    tickers.append(ticker)
                    file_count += 1

            logger.info(f"{path.name}: загружено тикеров: {file_count}")

    logger.info(f"Загружено тикеров: {len(tickers)}")
    return tickers


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------

def main():
    tickers = load_tickers(TICKERS_CSV_FILES)

    # Убираем дубли, сохраняем порядок
    seen = set()
    unique_tickers = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            unique_tickers.append(t)

    logger.info(f"Уникальных тикеров: {len(unique_tickers)}")
    logger.info(f"Приблизительное время загрузки: {len(unique_tickers) * 5 / CALLS_PER_MINUTE:.1f} минут")
    logger.info(f"Параллельных потоков: {MAX_WORKERS}")

    results = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_ticker = {
            executor.submit(process_ticker, t): t for t in unique_tickers
        }

        with tqdm(total=len(unique_tickers), desc="Загрузка данных", unit="тикер") as pbar:
            for future in as_completed(future_to_ticker):
                ticker = future_to_ticker[future]
                try:
                    symbol, sector = future.result()
                    results[symbol] = sector
                except Exception as exc:
                    logger.error(f"[FATAL] {ticker}: {exc}")
                    results[ticker] = "Error"
                finally:
                    pbar.update(1)

    # Сохраняем итоговый маппинг тикер → сектор
    mapping_path = DATA_DIR / "ticker_sector_mapping.csv"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    mapping_df = pd.DataFrame(
        sorted(results.items(), key=lambda x: (x[1], x[0])),
        columns=["ticker", "sector"],
    )
    mapping_df.to_csv(mapping_path, index=False, encoding="utf-8-sig")
    logger.info(f"\nГотово! Маппинг сохранён в {mapping_path}")

    # Статистика по секторам
    sector_counts = mapping_df["sector"].value_counts()
    logger.info("\nТикеров по секторам:")
    for sector, count in sector_counts.items():
        logger.info(f"  {sector}: {count}")


if __name__ == "__main__":
    main()
