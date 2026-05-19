"""
Baseline value-investing strategy pipeline.

This script is intentionally self-contained so the whole baseline can be run
from the project root without changing the exploratory notebook.

Main outputs are written to strategy_output/:
  data_quality.csv
  dividends_download_report.csv
  factors.csv
  selected_portfolios.csv
  trades.csv
  equity_curve.csv
  metrics.csv
  report.html
"""

from __future__ import annotations

import argparse
import csv
import html
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm

try:
    import yfinance as yf
except ImportError:
    yf = None


PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
TICKERS_DIR = PROJECT_DIR / "tickers"
OUTPUT_DIR = PROJECT_DIR / "strategy_output"
MAPPING_FILE = DATA_DIR / "ticker_sector_mapping.csv"

DEFAULT_TICKER_FILES = [
    "consumer-staples-list.csv",
    "energy-list.csv",
    "industrials-list.csv",
]

PRICE_COLUMNS = ["date", "open", "high", "low", "close", "adj_close", "volume"]
REPORT_FILES = [
    "overview.csv",
    "income_statement_quarterly.csv",
    "balance_sheet_quarterly.csv",
    "cash_flow_quarterly.csv",
    "earnings_quarterly.csv",
]


@dataclass
class StrategyConfig:
    start_date: str = "2007-01-01"
    reporting_lag_days: int = 60
    rebalance_frequency: str = "1M"
    n_stocks: int = 20
    max_per_sector: int = 10
    initial_capital: float = 100_000.0
    transaction_cost_bps: float = 10.0
    profit_target: Optional[float] = 0.50
    stop_loss: Optional[float] = -0.30
    score_drop_threshold: float = 0.30
    hold_min_periods: int = 1
    rebalance_band: float = 0.05
    benchmark_sector: str = "Benchmark"
    benchmark_components: List[Tuple[str, float]] = field(
        default_factory=lambda: [("XLE", 1 / 3), ("XLI", 1 / 3), ("XLP", 1 / 3)]
    )
    sp500_benchmark_ticker: str = "SPY"
    dividend_reinvestment: str = "cash_until_rebalance"
    min_market_cap: float = 500_000_000.0
    min_momentum_12_1: float = 0.0
    require_price_above_200dma: bool = True
    require_positive_fcf: bool = True
    max_debt_to_ebitda: float = 4.0
    min_interest_coverage: float = 2.0
    factor_weights: Dict[str, float] = field(
        default_factory=lambda: {
            "earnings_yield": 0.08,
            "book_to_market": 0.05,
            "fcf_yield": 0.12,
            "ebitda_ev": 0.08,
            "roic": 0.15,
            "gross_profitability": 0.12,
            "piotroski": 0.12,
            "interest_coverage": 0.08,
            "debt_to_ebitda_inv": 0.08,
            "mom_12_1": 0.12,
        }
    )


def normalize_ticker(value: object) -> str:
    return str(value).strip().strip('"').upper()


def normalize_sector(value: object) -> str:
    sector = str(value).strip().strip('"')
    if not sector or sector.lower() in {"nan", "none"}:
        return "Unknown"
    return sector


def yahoo_symbol(ticker: str) -> str:
    return ticker.replace(".", "-")


def safe_numeric(series: pd.Series) -> pd.Series:
    cleaned = series.replace({"None": np.nan, "-": np.nan, "nan": np.nan})
    return pd.to_numeric(cleaned, errors="coerce")


def read_csv_if_exists(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, **kwargs)
    except Exception:
        return pd.DataFrame()


def load_sector_mapping() -> Dict[str, str]:
    mapping = {}
    df = read_csv_if_exists(MAPPING_FILE)
    if not df.empty and {"ticker", "sector"}.issubset(df.columns):
        for _, row in df.iterrows():
            mapping[normalize_ticker(row["ticker"])] = normalize_sector(row["sector"])
    return mapping


def is_excluded_security_type(ticker: str, name: str) -> bool:
    text = f"{ticker} {name}".lower()
    excluded_terms = [
        "warrant",
        " right",
        " rights",
        " unit",
        " units",
        "preferred",
        "preference",
        "depositary share",
    ]
    if any(term in text for term in excluded_terms):
        return True
    return len(ticker) >= 5 and ticker.endswith(("W", "WS", "WT", "U", "R"))


def load_ticker_file(path: Path) -> List[Tuple[str, str, str]]:
    tickers: List[Tuple[str, str, str]] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        if not header:
            return tickers

        normalized_header = [col.strip().lower() for col in header]
        if "symbol" in normalized_header:
            ticker_idx = normalized_header.index("symbol")
            name_idx = normalized_header.index("name") if "name" in normalized_header else None
            sector_idx = normalized_header.index("sector") if "sector" in normalized_header else None
            rows = reader
        else:
            ticker_idx = 3
            name_idx = 1
            sector_idx = None
            rows = [header, *reader]

        for row in rows:
            if len(row) <= ticker_idx:
                continue
            ticker = normalize_ticker(row[ticker_idx])
            if not ticker or ticker in {"SYMBOL", "TICKER"}:
                continue
            name = row[name_idx].strip().strip('"') if name_idx is not None and len(row) > name_idx else ""
            sector = "Unknown"
            if sector_idx is not None and len(row) > sector_idx:
                sector = normalize_sector(row[sector_idx])
            tickers.append((ticker, sector, name))
    return tickers


def load_universe(ticker_files: Sequence[str]) -> pd.DataFrame:
    mapping = load_sector_mapping()
    rows = []
    seen = set()
    for file_name in ticker_files:
        path = TICKERS_DIR / file_name
        for ticker, source_sector, name in load_ticker_file(path):
            if ticker in seen:
                continue
            seen.add(ticker)
            if is_excluded_security_type(ticker, name):
                continue
            rows.append(
                {
                    "ticker": ticker,
                    "sector": normalize_sector(mapping.get(ticker) or source_sector),
                    "security_name": name,
                    "source_file": file_name,
                }
            )
    return pd.DataFrame(rows)


def find_ticker_dir(ticker: str, preferred_sector: Optional[str] = None) -> Optional[Path]:
    if preferred_sector:
        candidate = DATA_DIR / preferred_sector / ticker
        if candidate.exists():
            return candidate
    matches = list(DATA_DIR.glob(f"*/{ticker}"))
    return matches[0] if matches else None


def resolve_ticker_dir(ticker: str, sector: str) -> Path:
    existing = find_ticker_dir(ticker, sector)
    return existing if existing is not None else DATA_DIR / sector / ticker


def load_prices(ticker: str, sector: str) -> pd.DataFrame:
    ticker_dir = find_ticker_dir(ticker, sector)
    if ticker_dir is None:
        return pd.DataFrame()
    prices = read_csv_if_exists(ticker_dir / "price.csv")
    if prices.empty:
        return prices
    prices.columns = [str(col).strip() for col in prices.columns]
    if "date" in prices.columns:
        prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
        prices = prices.dropna(subset=["date"]).sort_values("date")
    for col in ["open", "high", "low", "close", "adj_close", "volume"]:
        if col in prices.columns:
            prices[col] = safe_numeric(prices[col])
    return prices.drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)


def load_report(ticker: str, sector: str, file_name: str) -> pd.DataFrame:
    ticker_dir = find_ticker_dir(ticker, sector)
    if ticker_dir is None:
        return pd.DataFrame()
    df = read_csv_if_exists(ticker_dir / file_name)
    if df.empty:
        return df
    if "fiscalDateEnding" in df.columns:
        df["fiscalDateEnding"] = pd.to_datetime(df["fiscalDateEnding"], errors="coerce")
        df = df.dropna(subset=["fiscalDateEnding"]).sort_values("fiscalDateEnding")
    return df.reset_index(drop=True)


def run_data_quality(universe: pd.DataFrame, output_dir: Path) -> pd.DataFrame:
    rows = []
    for row in tqdm(universe.itertuples(index=False), total=len(universe), desc="Data quality"):
        ticker = row.ticker
        sector = row.sector
        ticker_dir = find_ticker_dir(ticker, sector)
        prices = load_prices(ticker, sector)
        missing_reports = []
        report_rows = {}
        for file_name in REPORT_FILES:
            df = load_report(ticker, sector, file_name)
            report_rows[file_name.replace(".csv", "_rows")] = len(df)
            if df.empty:
                missing_reports.append(file_name)

        issues = []
        if ticker_dir is None:
            issues.append("missing_ticker_dir")
        if prices.empty:
            issues.append("missing_price")
        else:
            missing_price_cols = [col for col in PRICE_COLUMNS if col not in prices.columns]
            if missing_price_cols:
                issues.append("missing_price_columns:" + ",".join(missing_price_cols))
            if prices["date"].duplicated().any():
                issues.append("duplicate_price_dates")
            if "adj_close" in prices.columns and (prices["adj_close"] <= 0).any():
                issues.append("non_positive_adj_close")
            if "volume" in prices.columns and (prices["volume"] < 0).any():
                issues.append("negative_volume")
            if len(prices) < 252:
                issues.append("short_price_history")
        if missing_reports:
            issues.append("missing_reports:" + ",".join(missing_reports))

        rows.append(
            {
                "ticker": ticker,
                "sector": sector,
                "ticker_dir": str(ticker_dir) if ticker_dir else "",
                "price_rows": len(prices),
                "price_start": prices["date"].min().date().isoformat() if not prices.empty else "",
                "price_end": prices["date"].max().date().isoformat() if not prices.empty else "",
                "passed": not issues,
                "issues": ";".join(issues),
                **report_rows,
            }
        )

    quality = pd.DataFrame(rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    quality.to_csv(output_dir / "data_quality.csv", index=False, encoding="utf-8-sig")
    return quality


def normalize_dividends(dividends: pd.Series) -> pd.DataFrame:
    if dividends is None or dividends.empty:
        return pd.DataFrame(columns=["date", "dividend"])
    df = dividends.rename("dividend").reset_index()
    date_col = df.columns[0]
    df.rename(columns={date_col: "date"}, inplace=True)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.tz_localize(None)
    df["dividend"] = safe_numeric(df["dividend"]).fillna(0.0)
    df = df.dropna(subset=["date"])
    df = df[df["dividend"] > 0].sort_values("date")
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return df[["date", "dividend"]]


def flatten_yahoo_columns(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df.columns, pd.MultiIndex):
        return df
    price_columns = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
    result = df.copy()
    result.columns = [
        next((str(part) for part in col if str(part) in price_columns), str(col[0]))
        for col in result.columns.to_flat_index()
    ]
    return result


def normalize_yahoo_prices(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    df = flatten_yahoo_columns(df).reset_index()
    df.rename(
        columns={
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        },
        inplace=True,
    )
    df = df.loc[:, ~df.columns.duplicated()]
    available = [col for col in PRICE_COLUMNS if col in df.columns]
    df = df[available].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return df


def download_benchmark_price(ticker: str, sector: str, start_date: str, skip_existing: bool = True) -> Tuple[str, str, int]:
    if yf is None:
        raise RuntimeError("yfinance is not installed")
    ticker_dir = resolve_ticker_dir(ticker, sector)
    output_path = ticker_dir / "price.csv"
    if skip_existing and output_path.exists():
        df = read_csv_if_exists(output_path)
        return ticker, "benchmark_price_skipped", len(df)
    raw = yf.download(
        yahoo_symbol(ticker),
        start=start_date,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    prices = normalize_yahoo_prices(raw)
    ticker_dir.mkdir(parents=True, exist_ok=True)
    prices.to_csv(output_path, index=False, encoding="utf-8-sig")
    return ticker, "benchmark_price_saved", len(prices)


def download_dividend_file(ticker: str, sector: str, skip_existing: bool = True) -> Tuple[str, str, int]:
    if yf is None:
        raise RuntimeError("yfinance is not installed")
    ticker_dir = resolve_ticker_dir(ticker, sector)
    output_path = ticker_dir / "dividends.csv"
    if skip_existing and output_path.exists():
        df = read_csv_if_exists(output_path)
        return ticker, "skipped", len(df)
    try:
        dividends = yf.Ticker(yahoo_symbol(ticker)).dividends
        df = normalize_dividends(dividends)
        ticker_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        return ticker, "saved", len(df)
    except Exception as exc:
        return ticker, f"failed:{exc}", 0


def download_dividends(
    universe: pd.DataFrame,
    output_dir: Path,
    benchmark_components: Sequence[Tuple[str, float]],
    benchmark_sector: str = "Benchmark",
    sp500_benchmark_ticker: str = "SPY",
    start_date: str = "2005-01-01",
    skip_existing: bool = True,
    sleep_seconds: float = 0.0,
) -> pd.DataFrame:
    rows = []
    benchmark_tickers = [ticker for ticker, _ in benchmark_components]
    benchmark_price_tickers = list(dict.fromkeys([*benchmark_tickers, sp500_benchmark_ticker]))
    for benchmark_ticker in benchmark_price_tickers:
        try:
            ticker, status, rows_saved = download_benchmark_price(
                benchmark_ticker,
                benchmark_sector,
                start_date=start_date,
                skip_existing=skip_existing,
            )
            rows.append({"ticker": ticker, "sector": benchmark_sector, "status": status, "rows": rows_saved})
        except Exception as exc:
            rows.append(
                {
                    "ticker": benchmark_ticker,
                    "sector": benchmark_sector,
                    "status": f"failed:{exc}",
                    "rows": 0,
                }
            )

    all_tickers = list(universe[["ticker", "sector"]].itertuples(index=False, name=None))
    all_tickers.extend((ticker, benchmark_sector) for ticker in benchmark_price_tickers)
    for ticker, sector in tqdm(all_tickers, desc="Dividends"):
        result_ticker, status, rows_saved = download_dividend_file(ticker, sector, skip_existing=skip_existing)
        rows.append({"ticker": result_ticker, "sector": sector, "status": status, "rows": rows_saved})
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    report = pd.DataFrame(rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    report.to_csv(output_dir / "dividends_download_report.csv", index=False, encoding="utf-8-sig")
    return report


def latest_before(df: pd.DataFrame, date_col: str, as_of: pd.Timestamp) -> pd.Series:
    subset = df[df[date_col] <= as_of]
    if subset.empty:
        return pd.Series(dtype="float64")
    return subset.iloc[-1]


def add_available_dates(
    fundamentals: pd.DataFrame,
    earnings: pd.DataFrame,
    reporting_lag_days: int,
) -> pd.DataFrame:
    if fundamentals.empty or "fiscalDateEnding" not in fundamentals.columns:
        return fundamentals
    df = fundamentals.copy()
    df["available_date"] = df["fiscalDateEnding"] + pd.to_timedelta(reporting_lag_days, unit="D")
    if not earnings.empty and {"fiscalDateEnding", "reportedDate"}.issubset(earnings.columns):
        report_dates = earnings[["fiscalDateEnding", "reportedDate"]].copy()
        report_dates["reportedDate"] = pd.to_datetime(report_dates["reportedDate"], errors="coerce")
        report_dates = report_dates.dropna(subset=["reportedDate"])
        if not report_dates.empty:
            df = df.merge(report_dates, on="fiscalDateEnding", how="left")
            df["available_date"] = df["reportedDate"].fillna(df["available_date"])
            df.drop(columns=["reportedDate"], inplace=True)
    return df.sort_values(["available_date", "fiscalDateEnding"]).reset_index(drop=True)


def numeric_columns(df: pd.DataFrame, exclude: Iterable[str]) -> pd.DataFrame:
    result = df.copy()
    for col in result.columns:
        if col not in exclude:
            result[col] = safe_numeric(result[col])
    return result


def prepare_quarterly_statement(
    ticker: str,
    sector: str,
    file_name: str,
    earnings: pd.DataFrame,
    reporting_lag_days: int,
) -> pd.DataFrame:
    df = load_report(ticker, sector, file_name)
    if df.empty:
        return df
    df = numeric_columns(df, exclude={"fiscalDateEnding", "reportedCurrency"})
    return add_available_dates(df, earnings, reporting_lag_days)


def build_ticker_pit_rows(ticker: str, sector: str, config: StrategyConfig) -> pd.DataFrame:
    earnings = load_report(ticker, sector, "earnings_quarterly.csv")
    income = prepare_quarterly_statement(
        ticker, sector, "income_statement_quarterly.csv", earnings, config.reporting_lag_days
    )
    balance = prepare_quarterly_statement(
        ticker, sector, "balance_sheet_quarterly.csv", earnings, config.reporting_lag_days
    )
    cash_flow = prepare_quarterly_statement(
        ticker, sector, "cash_flow_quarterly.csv", earnings, config.reporting_lag_days
    )
    if income.empty and balance.empty and cash_flow.empty:
        return pd.DataFrame()

    all_dates = pd.Series(dtype="datetime64[ns]")
    for df in [income, balance, cash_flow]:
        if not df.empty and "fiscalDateEnding" in df.columns:
            all_dates = pd.concat([all_dates, df["fiscalDateEnding"]])
    fiscal_dates = sorted(all_dates.dropna().drop_duplicates())

    rows = []
    for fiscal_date in fiscal_dates:
        income_row = (
            income[income["fiscalDateEnding"] == fiscal_date]
            if "fiscalDateEnding" in income.columns
            else pd.DataFrame()
        )
        balance_row = (
            balance[balance["fiscalDateEnding"] == fiscal_date]
            if "fiscalDateEnding" in balance.columns
            else pd.DataFrame()
        )
        cash_row = (
            cash_flow[cash_flow["fiscalDateEnding"] == fiscal_date]
            if "fiscalDateEnding" in cash_flow.columns
            else pd.DataFrame()
        )
        available_dates = []
        for df in [income_row, balance_row, cash_row]:
            if not df.empty and "available_date" in df.columns:
                available_dates.append(df.iloc[0]["available_date"])
        if not available_dates:
            continue
        rows.append({"fiscalDateEnding": fiscal_date, "available_date": max(available_dates)})

    base = pd.DataFrame(rows).sort_values("fiscalDateEnding")
    if base.empty:
        return base

    def attach(statement: pd.DataFrame, prefix: str, fields: Sequence[str]) -> pd.DataFrame:
        if statement.empty:
            return base
        cols = ["fiscalDateEnding"] + [col for col in fields if col in statement.columns]
        renamed = statement[cols].copy()
        renamed.rename(columns={col: f"{prefix}_{col}" for col in cols if col != "fiscalDateEnding"}, inplace=True)
        return base.merge(renamed, on="fiscalDateEnding", how="left")

    data = base.copy()
    data = data.merge(
        attach(
            income,
            "is",
            [
                "totalRevenue",
                "grossProfit",
                "operatingIncome",
                "ebit",
                "ebitda",
                "netIncome",
                "interestExpense",
                "incomeTaxExpense",
                "incomeBeforeTax",
            ],
        ).drop(columns=["available_date"], errors="ignore"),
        on="fiscalDateEnding",
        how="left",
    )
    data = data.merge(
        attach(
            cash_flow,
            "cf",
            ["operatingCashflow", "capitalExpenditures", "dividendPayoutCommonStock", "netIncome"],
        ).drop(columns=["available_date"], errors="ignore"),
        on="fiscalDateEnding",
        how="left",
    )
    data = data.merge(
        attach(
            balance,
            "bs",
            [
                "totalAssets",
                "totalLiabilities",
                "totalShareholderEquity",
                "cashAndCashEquivalentsAtCarryingValue",
                "cashAndShortTermInvestments",
                "shortLongTermDebtTotal",
                "shortTermDebt",
                "longTermDebt",
                "currentDebt",
                "commonStockSharesOutstanding",
            ],
        ).drop(columns=["available_date"], errors="ignore"),
        on="fiscalDateEnding",
        how="left",
    )

    flow_cols = [
        "is_totalRevenue",
        "is_grossProfit",
        "is_operatingIncome",
        "is_ebit",
        "is_ebitda",
        "is_netIncome",
        "is_interestExpense",
        "is_incomeTaxExpense",
        "is_incomeBeforeTax",
        "cf_operatingCashflow",
        "cf_capitalExpenditures",
        "cf_netIncome",
    ]
    for col in flow_cols:
        if col in data.columns:
            data[f"{col}_ttm"] = data[col].rolling(4, min_periods=4).sum()

    data["ticker"] = ticker
    data["sector"] = sector
    return data.sort_values("available_date").reset_index(drop=True)


def build_pit_dataset(universe: pd.DataFrame, config: StrategyConfig, output_dir: Path) -> pd.DataFrame:
    frames = []
    for row in tqdm(universe.itertuples(index=False), total=len(universe), desc="PIT/TTM"):
        pit = build_ticker_pit_rows(row.ticker, row.sector, config)
        if not pit.empty:
            frames.append(pit)
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    output_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_dir / "pit_fundamentals.csv", index=False, encoding="utf-8-sig")
    return result


def first_trading_days(prices_by_ticker: Dict[str, pd.DataFrame], start_date: str, frequency: str) -> List[pd.Timestamp]:
    period_by_frequency = {"M": "M", "1M": "M", "Q": "Q", "1Q": "Q", "Y": "Y", "1Y": "Y"}
    normalized_frequency = frequency.strip().upper()
    if normalized_frequency not in period_by_frequency:
        raise ValueError(f"Unsupported rebalance frequency: {frequency}")

    all_dates = sorted(
        set(
            pd.concat([df["date"] for df in prices_by_ticker.values() if not df.empty], ignore_index=True)
            .dropna()
            .tolist()
        )
    )
    if not all_dates:
        return []
    calendar = pd.DataFrame({"date": pd.to_datetime(all_dates)})
    calendar = calendar[calendar["date"] >= pd.to_datetime(start_date)].copy()
    if calendar.empty:
        return []
    calendar["period"] = calendar["date"].dt.to_period(period_by_frequency[normalized_frequency])
    return calendar.groupby("period")["date"].min().sort_values().tolist()


def price_asof(prices: pd.DataFrame, as_of: pd.Timestamp, date_col: str = "date") -> Optional[pd.Series]:
    subset = prices[prices[date_col] <= as_of]
    if subset.empty:
        return None
    return subset.iloc[-1]


def trailing_return(prices: pd.DataFrame, end_date: pd.Timestamp, months_back: int, skip_recent_months: int = 0) -> float:
    if prices.empty:
        return np.nan
    end_anchor = end_date - pd.DateOffset(months=skip_recent_months)
    start_anchor = end_date - pd.DateOffset(months=months_back)
    end_row = price_asof(prices, end_anchor)
    start_row = price_asof(prices, start_anchor)
    if end_row is None or start_row is None:
        return np.nan
    start_price = start_row.get("adj_close", np.nan)
    end_price = end_row.get("adj_close", np.nan)
    if pd.isna(start_price) or start_price <= 0 or pd.isna(end_price):
        return np.nan
    return float(end_price / start_price - 1.0)


def trailing_volatility(prices: pd.DataFrame, end_date: pd.Timestamp, window: int = 252) -> float:
    subset = prices[prices["date"] <= end_date].tail(window + 1).copy()
    if len(subset) < window // 2:
        return np.nan
    returns = subset["adj_close"].pct_change().dropna()
    if returns.empty:
        return np.nan
    return float(returns.std() * math.sqrt(252))


def trailing_moving_average(
    prices: pd.DataFrame,
    end_date: pd.Timestamp,
    window: int = 200,
    price_col: str = "close",
) -> float:
    subset = prices[prices["date"] <= end_date].tail(window)
    if len(subset) < window // 2 or price_col not in subset.columns:
        return np.nan
    return float(subset[price_col].mean())


def piotroski_score(current: pd.Series, previous: Optional[pd.Series]) -> float:
    score = 0
    ni = current.get("is_netIncome_ttm", np.nan)
    cfo = current.get("cf_operatingCashflow_ttm", np.nan)
    assets = current.get("bs_totalAssets", np.nan)
    debt = current.get("bs_shortLongTermDebtTotal", np.nan)
    current_ratio_num = current.get("bs_totalAssets", np.nan)
    current_ratio_den = current.get("bs_totalLiabilities", np.nan)
    shares = current.get("bs_commonStockSharesOutstanding", np.nan)
    gross_margin = np.nan
    if current.get("is_totalRevenue_ttm", np.nan):
        gross_margin = current.get("is_grossProfit_ttm", np.nan) / current.get("is_totalRevenue_ttm", np.nan)

    if pd.notna(ni) and ni > 0:
        score += 1
    if pd.notna(cfo) and cfo > 0:
        score += 1
    if pd.notna(cfo) and pd.notna(ni) and cfo > ni:
        score += 1

    if previous is not None and not previous.empty:
        prev_assets = previous.get("bs_totalAssets", np.nan)
        prev_debt = previous.get("bs_shortLongTermDebtTotal", np.nan)
        prev_shares = previous.get("bs_commonStockSharesOutstanding", np.nan)
        prev_revenue = previous.get("is_totalRevenue_ttm", np.nan)
        prev_gross = previous.get("is_grossProfit_ttm", np.nan)
        prev_ratio_num = previous.get("bs_totalAssets", np.nan)
        prev_ratio_den = previous.get("bs_totalLiabilities", np.nan)

        roa = ni / assets if pd.notna(ni) and pd.notna(assets) and assets else np.nan
        prev_roa = (
            previous.get("is_netIncome_ttm", np.nan) / prev_assets
            if pd.notna(previous.get("is_netIncome_ttm", np.nan)) and pd.notna(prev_assets) and prev_assets
            else np.nan
        )
        if pd.notna(roa) and pd.notna(prev_roa) and roa > prev_roa:
            score += 1
        if pd.notna(debt) and pd.notna(prev_debt) and debt < prev_debt:
            score += 1
        current_ratio = current_ratio_num / current_ratio_den if pd.notna(current_ratio_den) and current_ratio_den else np.nan
        prev_ratio = prev_ratio_num / prev_ratio_den if pd.notna(prev_ratio_den) and prev_ratio_den else np.nan
        if pd.notna(current_ratio) and pd.notna(prev_ratio) and current_ratio > prev_ratio:
            score += 1
        if pd.notna(shares) and pd.notna(prev_shares) and shares <= prev_shares:
            score += 1
        prev_gross_margin = prev_gross / prev_revenue if pd.notna(prev_revenue) and prev_revenue else np.nan
        if pd.notna(gross_margin) and pd.notna(prev_gross_margin) and gross_margin > prev_gross_margin:
            score += 1

    return float(score)


def build_factor_rows(
    universe: pd.DataFrame,
    pit: pd.DataFrame,
    config: StrategyConfig,
    output_dir: Path,
) -> pd.DataFrame:
    prices_by_ticker = {
        row.ticker: load_prices(row.ticker, row.sector)
        for row in universe.itertuples(index=False)
    }
    rebalance_dates = first_trading_days(prices_by_ticker, config.start_date, config.rebalance_frequency)
    pit_by_ticker = {ticker: df.sort_values("available_date") for ticker, df in pit.groupby("ticker")}

    rows = []
    for rebalance_date in tqdm(rebalance_dates, desc="Factors"):
        for row in universe.itertuples(index=False):
            ticker = row.ticker
            sector = row.sector
            prices = prices_by_ticker.get(ticker, pd.DataFrame())
            price_row = price_asof(prices, rebalance_date) if not prices.empty else None
            if price_row is None:
                continue

            ticker_pit = pit_by_ticker.get(ticker, pd.DataFrame())
            if ticker_pit.empty or "available_date" not in ticker_pit.columns:
                continue
            available = ticker_pit[ticker_pit["available_date"] <= rebalance_date]
            if available.empty:
                continue
            current = available.iloc[-1]
            previous = available.iloc[-5] if len(available) >= 5 else None

            price = price_row.get("close", np.nan)
            shares = current.get("bs_commonStockSharesOutstanding", np.nan)
            debt = current.get("bs_shortLongTermDebtTotal", np.nan)
            if pd.isna(debt):
                debt = (
                    (current.get("bs_shortTermDebt", 0) or 0)
                    + (current.get("bs_currentDebt", 0) or 0)
                    + (current.get("bs_longTermDebt", 0) or 0)
                )
            cash = current.get("bs_cashAndShortTermInvestments", np.nan)
            if pd.isna(cash):
                cash = current.get("bs_cashAndCashEquivalentsAtCarryingValue", 0)
            market_cap = price * shares if pd.notna(price) and pd.notna(shares) else np.nan
            enterprise_value = market_cap + (debt if pd.notna(debt) else 0) - (cash if pd.notna(cash) else 0)
            capex = current.get("cf_capitalExpenditures_ttm", np.nan)
            fcf = current.get("cf_operatingCashflow_ttm", np.nan) - abs(capex) if pd.notna(capex) else np.nan
            ebitda = current.get("is_ebitda_ttm", np.nan)
            revenue = current.get("is_totalRevenue_ttm", np.nan)
            gross_profit = current.get("is_grossProfit_ttm", np.nan)
            assets = current.get("bs_totalAssets", np.nan)
            equity = current.get("bs_totalShareholderEquity", np.nan)
            ebit = current.get("is_ebit_ttm", np.nan)
            tax_expense = current.get("is_incomeTaxExpense_ttm", np.nan)
            pretax = current.get("is_incomeBeforeTax_ttm", np.nan)
            tax_rate = tax_expense / pretax if pd.notna(tax_expense) and pd.notna(pretax) and pretax > 0 else 0.21
            nopat = ebit * (1 - min(max(tax_rate, 0), 0.5)) if pd.notna(ebit) else np.nan
            invested_capital = equity + debt - cash if pd.notna(equity) else np.nan
            interest = abs(current.get("is_interestExpense_ttm", np.nan))
            debt_to_ebitda = debt / ebitda if pd.notna(ebitda) and ebitda > 0 else np.nan
            interest_coverage = ebit / interest if pd.notna(interest) and interest > 0 else np.nan
            mom_12_1 = trailing_return(prices, rebalance_date, months_back=12, skip_recent_months=1)
            volatility_1y = trailing_volatility(prices, rebalance_date)
            ma_200 = trailing_moving_average(prices, rebalance_date, window=200, price_col="close")
            above_200dma = pd.notna(price) and pd.notna(ma_200) and price >= ma_200
            market_cap_pass = pd.notna(market_cap) and market_cap >= config.min_market_cap
            fcf_pass = (not config.require_positive_fcf) or (pd.notna(fcf) and fcf > 0)
            leverage_pass = (
                (pd.notna(debt) and debt <= 0)
                or (pd.notna(debt_to_ebitda) and debt_to_ebitda <= config.max_debt_to_ebitda)
            )
            interest_pass = (
                (pd.notna(debt) and debt <= 0)
                or (pd.notna(interest_coverage) and interest_coverage >= config.min_interest_coverage)
            )
            momentum_pass = pd.notna(mom_12_1) and mom_12_1 >= config.min_momentum_12_1
            trend_pass = (not config.require_price_above_200dma) or above_200dma
            eligible = market_cap_pass and fcf_pass and leverage_pass and interest_pass and momentum_pass and trend_pass

            rows.append(
                {
                    "date": rebalance_date,
                    "ticker": ticker,
                    "sector": sector,
                    "price": price,
                    "market_cap": market_cap,
                    "enterprise_value": enterprise_value,
                    "fcf_ttm": fcf,
                    "ebitda_ttm": ebitda,
                    "earnings_yield": current.get("is_netIncome_ttm", np.nan) / market_cap
                    if market_cap and market_cap > 0
                    else np.nan,
                    "book_to_market": equity / market_cap if market_cap and market_cap > 0 else np.nan,
                    "fcf_yield": fcf / market_cap if market_cap and market_cap > 0 else np.nan,
                    "ebitda_ev": ebitda / enterprise_value
                    if enterprise_value and enterprise_value > 0
                    else np.nan,
                    "roic": nopat / invested_capital
                    if pd.notna(invested_capital) and invested_capital > 0
                    else np.nan,
                    "gross_profitability": gross_profit / assets
                    if pd.notna(gross_profit) and pd.notna(assets) and assets > 0
                    else np.nan,
                    "piotroski": piotroski_score(current, previous),
                    "debt_to_equity": debt / equity if pd.notna(equity) and equity > 0 else np.nan,
                    "debt_to_ebitda": debt_to_ebitda,
                    "debt_to_ebitda_inv": 1 / debt_to_ebitda
                    if pd.notna(debt_to_ebitda) and debt_to_ebitda > 0
                    else np.nan,
                    "interest_coverage": interest_coverage,
                    "mom_12_1": mom_12_1,
                    "volatility_1y": volatility_1y,
                    "ma_200": ma_200,
                    "above_200dma": above_200dma,
                    "market_cap_pass": market_cap_pass,
                    "positive_fcf_pass": fcf_pass,
                    "leverage_pass": leverage_pass,
                    "interest_coverage_pass": interest_pass,
                    "momentum_pass": momentum_pass,
                    "trend_pass": trend_pass,
                    "eligible": eligible,
                }
            )

    factors = pd.DataFrame(rows)
    if factors.empty:
        output_dir.mkdir(parents=True, exist_ok=True)
        factors.to_csv(output_dir / "factors.csv", index=False, encoding="utf-8-sig")
        return factors

    factor_cols = list(config.factor_weights.keys())
    factors = normalize_factor_scores(factors, factor_cols, config.factor_weights)
    output_dir.mkdir(parents=True, exist_ok=True)
    factors.to_csv(output_dir / "factors.csv", index=False, encoding="utf-8-sig")
    return factors


def normalize_factor_scores(
    factors: pd.DataFrame,
    factor_cols: Sequence[str],
    weights: Dict[str, float],
) -> pd.DataFrame:
    scored = factors.copy()
    for col in factor_cols:
        if col not in scored.columns:
            scored[f"{col}_rank"] = np.nan
            continue
        winsorized = []
        for _, group in scored.groupby("date"):
            values = group[col]
            lower = values.quantile(0.01)
            upper = values.quantile(0.99)
            winsorized.append(values.clip(lower=lower, upper=upper))
        scored[f"{col}_winsor"] = pd.concat(winsorized).sort_index()
        scored[f"{col}_rank"] = scored.groupby(["date", "sector"])[f"{col}_winsor"].rank(
            pct=True, na_option="keep"
        )
    scored["rule_based_score"] = 0.0
    total_weight = sum(weights.values())
    for col, weight in weights.items():
        scored["rule_based_score"] += scored[f"{col}_rank"].fillna(0.5) * (weight / total_weight)
    scored["ml_score"] = np.nan
    scored["final_score"] = scored["rule_based_score"]
    scored["score_percentile"] = scored.groupby("date")["final_score"].rank(pct=True)
    return scored


def select_targets_for_date(date_factors: pd.DataFrame, n_stocks: int, max_per_sector: int) -> pd.DataFrame:
    selected = []
    sector_counts: Dict[str, int] = {}
    eligible_factors = (
        date_factors[date_factors["eligible"] == True]
        if "eligible" in date_factors.columns
        else date_factors
    )
    ranked = eligible_factors.sort_values("final_score", ascending=False)
    for row in ranked.itertuples(index=False):
        sector = row.sector
        if sector_counts.get(sector, 0) >= max_per_sector:
            continue
        selected.append(row._asdict())
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        if len(selected) >= n_stocks:
            break
    return pd.DataFrame(selected)


def build_selected_portfolios(factors: pd.DataFrame, config: StrategyConfig, output_dir: Path) -> pd.DataFrame:
    frames = []
    if factors.empty:
        return pd.DataFrame()
    for date, group in factors.groupby("date"):
        targets = select_targets_for_date(group, config.n_stocks, config.max_per_sector)
        if targets.empty:
            continue
        targets["target_weight"] = 1.0 / len(targets)
        columns = [
            "date",
            "ticker",
            "sector",
            "market_cap",
            "final_score",
            "score_percentile",
            "target_weight",
            "fcf_yield",
            "roic",
            "debt_to_ebitda",
            "interest_coverage",
            "mom_12_1",
            "above_200dma",
        ]
        frames.append(targets[[col for col in columns if col in targets.columns]])
    portfolios = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    output_dir.mkdir(parents=True, exist_ok=True)
    portfolios.to_csv(output_dir / "selected_portfolios.csv", index=False, encoding="utf-8-sig")
    return portfolios


def load_dividends(ticker: str, sector: str) -> pd.DataFrame:
    ticker_dir = find_ticker_dir(ticker, sector)
    if ticker_dir is None:
        return pd.DataFrame(columns=["date", "dividend"])
    dividends = read_csv_if_exists(ticker_dir / "dividends.csv")
    if dividends.empty:
        return pd.DataFrame(columns=["date", "dividend"])
    dividends["date"] = pd.to_datetime(dividends["date"], errors="coerce")
    dividends["dividend"] = safe_numeric(dividends["dividend"]).fillna(0.0)
    return dividends.dropna(subset=["date"]).sort_values("date")


@dataclass
class Position:
    shares: float
    entry_price: float
    entry_date: pd.Timestamp
    holding_periods: int = 0


def run_backtest(
    universe: pd.DataFrame,
    factors: pd.DataFrame,
    selected_portfolios: pd.DataFrame,
    config: StrategyConfig,
    output_dir: Path,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    prices_by_ticker = {row.ticker: load_prices(row.ticker, row.sector) for row in universe.itertuples(index=False)}
    sectors = dict(zip(universe["ticker"], universe["sector"]))
    dividends_by_ticker = {row.ticker: load_dividends(row.ticker, row.sector) for row in universe.itertuples(index=False)}
    price_dates = sorted(
        set(
            pd.concat([df["date"] for df in prices_by_ticker.values() if not df.empty], ignore_index=True)
            .dropna()
            .tolist()
        )
    )
    if not price_dates or selected_portfolios.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    start_date = max(pd.to_datetime(config.start_date), pd.to_datetime(selected_portfolios["date"]).min())
    calendar = [date for date in price_dates if date >= start_date]
    rebalance_dates = set(pd.to_datetime(selected_portfolios["date"]).tolist())
    target_by_date = {
        pd.to_datetime(date): group.set_index("ticker")
        for date, group in selected_portfolios.groupby("date")
    }
    factors_by_date = {
        pd.to_datetime(date): group.set_index("ticker")
        for date, group in factors.groupby("date")
    }

    cash = float(config.initial_capital)
    positions: Dict[str, Position] = {}
    equity_rows = []
    trade_rows = []
    cost_rate = config.transaction_cost_bps / 10_000

    def current_price(ticker: str, date: pd.Timestamp) -> float:
        row = price_asof(prices_by_ticker.get(ticker, pd.DataFrame()), date)
        if row is None:
            return np.nan
        return float(row.get("close", np.nan))

    for date in tqdm(calendar, desc="Backtest"):
        # Cash dividends on ex-date.
        for ticker, position in list(positions.items()):
            sector = sectors.get(ticker, "Unknown")
            dividends = dividends_by_ticker.get(ticker, pd.DataFrame())
            if dividends.empty:
                continue
            todays_divs = dividends[dividends["date"] == date]
            if not todays_divs.empty:
                cash += float(todays_divs["dividend"].sum()) * position.shares

        position_value = 0.0
        for ticker, position in positions.items():
            price = current_price(ticker, date)
            if pd.notna(price):
                position_value += position.shares * price
        total_value = cash + position_value

        if date in rebalance_dates:
            for position in positions.values():
                position.holding_periods += 1

            date_targets = target_by_date[date]
            date_factors = factors_by_date.get(date, pd.DataFrame())
            sell_tickers = []
            for ticker, position in list(positions.items()):
                price = current_price(ticker, date)
                if pd.isna(price):
                    continue
                period_return = price / position.entry_price - 1 if position.entry_price > 0 else 0.0
                factor_row = (
                    date_factors.loc[ticker]
                    if not date_factors.empty and ticker in date_factors.index
                    else pd.Series(dtype="float64")
                )
                score_pct = (
                    float(factor_row.get("score_percentile", 0.0))
                    if not factor_row.empty
                    else 0.0
                )
                target_missing = ticker not in date_targets.index
                if not target_missing:
                    continue
                can_exit = position.holding_periods >= config.hold_min_periods
                hit_profit = config.profit_target is not None and period_return >= config.profit_target
                hit_stop = config.stop_loss is not None and period_return <= config.stop_loss
                score_drop = score_pct < config.score_drop_threshold
                fundamental_deterioration = (
                    not bool(factor_row.get("eligible", True))
                    or not bool(factor_row.get("positive_fcf_pass", True))
                    or not bool(factor_row.get("leverage_pass", True))
                    or not bool(factor_row.get("interest_coverage_pass", True))
                    or not bool(factor_row.get("trend_pass", True))
                    or not bool(factor_row.get("momentum_pass", True))
                )
                if can_exit and (
                    hit_profit
                    or hit_stop
                    or score_drop
                    or target_missing
                    or fundamental_deterioration
                ):
                    sell_tickers.append(ticker)

            for ticker in sell_tickers:
                position = positions.pop(ticker)
                price = current_price(ticker, date)
                gross = position.shares * price
                cost = gross * cost_rate
                cash += gross - cost
                trade_rows.append(
                    {
                        "date": date,
                        "ticker": ticker,
                        "side": "SELL",
                        "shares": position.shares,
                        "price": price,
                        "gross_value": gross,
                        "transaction_cost": cost,
                    }
                )

            # Recalculate total after exits.
            position_value = 0.0
            for ticker, position in positions.items():
                price = current_price(ticker, date)
                if pd.notna(price):
                    position_value += position.shares * price
            total_value = cash + position_value

            for ticker, target in date_targets.iterrows():
                target_weight = float(target["target_weight"])
                target_value = total_value * target_weight
                price = current_price(ticker, date)
                if pd.isna(price) or price <= 0:
                    continue
                current_shares = positions[ticker].shares if ticker in positions else 0.0
                current_value = current_shares * price
                if ticker in positions and abs(current_value / total_value - target_weight) < config.rebalance_band:
                    continue
                trade_value = target_value - current_value
                if trade_value > 0:
                    max_affordable = cash / (1 + cost_rate)
                    trade_value = min(trade_value, max_affordable)
                if abs(trade_value) < 1:
                    continue
                shares_delta = trade_value / price
                cost = abs(trade_value) * cost_rate
                cash -= trade_value + cost
                if ticker in positions:
                    positions[ticker].shares += shares_delta
                else:
                    positions[ticker] = Position(
                        shares=shares_delta,
                        entry_price=price,
                        entry_date=date,
                        holding_periods=0,
                    )
                trade_rows.append(
                    {
                        "date": date,
                        "ticker": ticker,
                        "side": "BUY" if trade_value > 0 else "SELL",
                        "shares": shares_delta,
                        "price": price,
                        "gross_value": abs(trade_value),
                        "transaction_cost": cost,
                    }
                )

        position_value = 0.0
        for ticker, position in positions.items():
            price = current_price(ticker, date)
            if pd.notna(price):
                position_value += position.shares * price
        total_value = cash + position_value
        equity_rows.append(
            {
                "date": date,
                "portfolio_value": total_value,
                "cash": cash,
                "positions_value": position_value,
                "n_positions": len(positions),
            }
        )

    equity = pd.DataFrame(equity_rows)
    trades = pd.DataFrame(trade_rows)
    holdings = selected_portfolios.copy()
    output_dir.mkdir(parents=True, exist_ok=True)
    equity.to_csv(output_dir / "equity_curve.csv", index=False, encoding="utf-8-sig")
    trades.to_csv(output_dir / "trades.csv", index=False, encoding="utf-8-sig")
    holdings.to_csv(output_dir / "portfolio_targets.csv", index=False, encoding="utf-8-sig")
    return equity, trades, holdings


def max_drawdown(series: pd.Series) -> float:
    running_max = series.cummax()
    drawdown = series / running_max - 1
    return float(drawdown.min()) if not drawdown.empty else np.nan


def build_sector_benchmark_series(
    components: Sequence[Tuple[str, float]],
    benchmark_sector: str,
) -> pd.DataFrame:
    frames = []
    for ticker, weight in components:
        prices = load_prices(ticker, benchmark_sector)
        if prices.empty or "adj_close" not in prices.columns:
            continue
        component = prices[["date", "adj_close"]].copy()
        component.rename(columns={"adj_close": ticker}, inplace=True)
        component[ticker] = component[ticker] / component[ticker].iloc[0]
        frames.append((ticker, weight, component))

    if not frames:
        return pd.DataFrame(columns=["date", "sector_benchmark_value", "sector_benchmark_return"])

    benchmark = frames[0][2]
    for _, _, component in frames[1:]:
        benchmark = benchmark.merge(component, on="date", how="inner")

    total_weight = sum(weight for ticker, weight, _ in frames)
    benchmark["sector_benchmark_value"] = 0.0
    for ticker, weight, _ in frames:
        benchmark["sector_benchmark_value"] += benchmark[ticker] * (weight / total_weight)

    benchmark["sector_benchmark_return"] = benchmark["sector_benchmark_value"].pct_change()
    return benchmark[["date", "sector_benchmark_value", "sector_benchmark_return"]]


def build_single_benchmark_series(
    ticker: str,
    benchmark_sector: str,
    value_col: str,
    return_col: str,
) -> pd.DataFrame:
    prices = load_prices(ticker, benchmark_sector)
    if prices.empty or "adj_close" not in prices.columns:
        return pd.DataFrame(columns=["date", value_col, return_col])

    benchmark = prices[["date", "adj_close"]].copy()
    benchmark.rename(columns={"adj_close": value_col}, inplace=True)
    benchmark[value_col] = benchmark[value_col] / benchmark[value_col].iloc[0]
    benchmark[return_col] = benchmark[value_col].pct_change()
    return benchmark[["date", value_col, return_col]]


def annualized_return(total_return: float, days: int) -> float:
    if pd.isna(total_return) or total_return <= -1:
        return np.nan
    return (1 + total_return) ** (365.25 / max(days, 1)) - 1


def annualized_volatility(returns: pd.Series) -> float:
    return returns.std() * math.sqrt(252)


def annualized_downside(returns: pd.Series) -> float:
    return returns[returns < 0].std() * math.sqrt(252)


def compute_benchmark_metric_rows(
    equity: pd.DataFrame,
    benchmark_series: pd.DataFrame,
    value_col: str,
    return_col: str,
    metric_prefix: str,
    comparison_suffix: str,
    strategy_cagr: float,
) -> List[Dict[str, float]]:
    if benchmark_series.empty:
        return []

    merged = equity[["date", "daily_return"]].merge(benchmark_series, on="date", how="inner")
    merged = merged.dropna(subset=[return_col])
    if len(merged) <= 2:
        return []

    benchmark_total = merged[value_col].iloc[-1] / merged[value_col].iloc[0] - 1
    benchmark_days = max((merged["date"].max() - merged["date"].min()).days, 1)
    benchmark_cagr = annualized_return(benchmark_total, benchmark_days)
    benchmark_volatility = annualized_volatility(merged[return_col])
    benchmark_downside = annualized_downside(merged[return_col])
    benchmark_sharpe = (
        benchmark_cagr / benchmark_volatility
        if benchmark_volatility and not pd.isna(benchmark_volatility)
        else np.nan
    )
    benchmark_sortino = (
        benchmark_cagr / benchmark_downside
        if benchmark_downside and not pd.isna(benchmark_downside)
        else np.nan
    )
    benchmark_mdd = max_drawdown(merged[value_col])

    covariance = np.cov(merged["daily_return"], merged[return_col])[0, 1]
    benchmark_variance = np.var(merged[return_col])
    beta = covariance / benchmark_variance if benchmark_variance else np.nan
    alpha = strategy_cagr - beta * benchmark_cagr if pd.notna(beta) else np.nan
    active_return = merged["daily_return"] - merged[return_col]
    tracking_error = annualized_volatility(active_return)
    information_ratio = (
        (active_return.mean() * 252) / tracking_error
        if tracking_error and pd.notna(tracking_error)
        else np.nan
    )

    return [
        {"metric": f"{metric_prefix}_total_return", "value": benchmark_total},
        {"metric": f"{metric_prefix}_cagr", "value": benchmark_cagr},
        {"metric": f"{metric_prefix}_volatility", "value": benchmark_volatility},
        {"metric": f"{metric_prefix}_max_drawdown", "value": benchmark_mdd},
        {"metric": f"{metric_prefix}_sharpe", "value": benchmark_sharpe},
        {"metric": f"{metric_prefix}_sortino", "value": benchmark_sortino},
        {"metric": f"beta_vs_{comparison_suffix}", "value": beta},
        {"metric": f"alpha_vs_{comparison_suffix}", "value": alpha},
        {"metric": f"tracking_error_vs_{comparison_suffix}", "value": tracking_error},
        {"metric": f"information_ratio_vs_{comparison_suffix}", "value": information_ratio},
    ]


def compute_metrics(
    equity: pd.DataFrame,
    trades: pd.DataFrame,
    output_dir: Path,
    benchmark_components: Sequence[Tuple[str, float]],
    benchmark_sector: str = "Benchmark",
    sp500_benchmark_ticker: str = "SPY",
) -> pd.DataFrame:
    if equity.empty:
        metrics = pd.DataFrame()
        metrics.to_csv(output_dir / "metrics.csv", index=False, encoding="utf-8-sig")
        return metrics
    equity = equity.copy()
    equity["date"] = pd.to_datetime(equity["date"])
    equity["daily_return"] = equity["portfolio_value"].pct_change().fillna(0.0)
    days = max((equity["date"].max() - equity["date"].min()).days, 1)
    total_return = equity["portfolio_value"].iloc[-1] / equity["portfolio_value"].iloc[0] - 1
    cagr = annualized_return(total_return, days)
    volatility = annualized_volatility(equity["daily_return"])
    downside = annualized_downside(equity["daily_return"])
    sharpe = cagr / volatility if volatility and not pd.isna(volatility) else np.nan
    sortino = cagr / downside if downside and not pd.isna(downside) else np.nan
    mdd = max_drawdown(equity["portfolio_value"])
    calmar = cagr / abs(mdd) if mdd and not pd.isna(mdd) else np.nan
    buy_trades = trades[trades["side"] == "BUY"] if not trades.empty else pd.DataFrame()
    sell_trades = trades[trades["side"] == "SELL"] if not trades.empty else pd.DataFrame()

    metric_rows = [
        {"metric": "total_return", "value": total_return},
        {"metric": "cagr", "value": cagr},
        {"metric": "volatility", "value": volatility},
        {"metric": "max_drawdown", "value": mdd},
        {"metric": "calmar", "value": calmar},
        {"metric": "sharpe", "value": sharpe},
        {"metric": "sortino", "value": sortino},
        {"metric": "n_buy_trades", "value": len(buy_trades)},
        {"metric": "n_sell_trades", "value": len(sell_trades)},
        {"metric": "avg_positions", "value": equity["n_positions"].mean()},
    ]

    benchmark_series = build_sector_benchmark_series(benchmark_components, benchmark_sector)
    metric_rows.extend(
        compute_benchmark_metric_rows(
            equity,
            benchmark_series,
            "sector_benchmark_value",
            "sector_benchmark_return",
            "sector_benchmark",
            "sector_benchmark",
            cagr,
        )
    )

    sp500_series = build_single_benchmark_series(
        sp500_benchmark_ticker,
        benchmark_sector,
        "sp500_value",
        "sp500_return",
    )
    metric_rows.extend(
        compute_benchmark_metric_rows(
            equity,
            sp500_series,
            "sp500_value",
            "sp500_return",
            "sp500",
            "sp500",
            cagr,
        )
    )

    metrics = pd.DataFrame(metric_rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(output_dir / "metrics.csv", index=False, encoding="utf-8-sig")
    return metrics


def render_report(
    output_dir: Path,
    quality: pd.DataFrame,
    dividend_report: pd.DataFrame,
    factors: pd.DataFrame,
    portfolios: pd.DataFrame,
    equity: pd.DataFrame,
    trades: pd.DataFrame,
    metrics: pd.DataFrame,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.html"

    def format_number(value: object) -> str:
        if pd.isna(value):
            return ""
        if isinstance(value, (int, np.integer)):
            return f"{value:,}"
        if isinstance(value, (float, np.floating)):
            if not np.isfinite(value):
                return ""
            abs_value = abs(float(value))
            if abs_value >= 1:
                formatted = f"{float(value):,.6f}"
            else:
                formatted = f"{float(value):.10f}"
            return formatted.rstrip("0").rstrip(".")
        return str(value)

    def table(df: pd.DataFrame, max_rows: int = 20) -> str:
        if df.empty:
            return "<p>No data.</p>"
        view = df.head(max_rows).copy()
        formatters = {
            col: format_number
            for col in view.columns
            if pd.api.types.is_numeric_dtype(view[col])
        }
        return view.to_html(index=False, escape=True, formatters=formatters)

    def metric_table(metric_names: Sequence[str]) -> str:
        if metrics.empty or "metric" not in metrics.columns:
            return "<p>No data.</p>"
        view = metrics[metrics["metric"].isin(metric_names)].copy()
        if view.empty:
            return "<p>No data.</p>"
        view["metric"] = pd.Categorical(view["metric"], categories=metric_names, ordered=True)
        view = view.sort_values("metric")
        return table(view, len(metric_names))

    strategy_metric_names = [
        "total_return",
        "cagr",
        "volatility",
        "max_drawdown",
        "calmar",
        "sharpe",
        "sortino",
        "n_buy_trades",
        "n_sell_trades",
        "avg_positions",
    ]
    sector_metric_names = [
        "sector_benchmark_total_return",
        "sector_benchmark_cagr",
        "sector_benchmark_volatility",
        "sector_benchmark_max_drawdown",
        "sector_benchmark_sharpe",
        "sector_benchmark_sortino",
        "beta_vs_sector_benchmark",
        "alpha_vs_sector_benchmark",
        "tracking_error_vs_sector_benchmark",
        "information_ratio_vs_sector_benchmark",
    ]
    sp500_metric_names = [
        "sp500_total_return",
        "sp500_cagr",
        "sp500_volatility",
        "sp500_max_drawdown",
        "sp500_sharpe",
        "sp500_sortino",
        "beta_vs_sp500",
        "alpha_vs_sp500",
        "tracking_error_vs_sp500",
        "information_ratio_vs_sp500",
    ]

    passed = int(quality["passed"].sum()) if not quality.empty and "passed" in quality.columns else 0
    total = len(quality)
    body = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Value Strategy Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; line-height: 1.4; }}
    table {{ border-collapse: collapse; margin: 12px 0; font-size: 12px; }}
    th, td {{ border: 1px solid #ddd; padding: 4px 8px; }}
    th {{ background: #f3f3f3; }}
    .metric {{ display: inline-block; margin: 8px 16px 8px 0; }}
  </style>
</head>
<body>
  <h1>Value Strategy Baseline Report</h1>
  <h2>Data Quality</h2>
  <p>Passed tickers: {passed} / {total}</p>
  {table(quality[quality["passed"] == False] if not quality.empty and "passed" in quality.columns else quality)}
  <h2>Dividends</h2>
  {table(dividend_report)}
  <h2>Strategy Metrics</h2>
  {metric_table(strategy_metric_names)}
  <h2>Sector Benchmark Comparison</h2>
  {metric_table(sector_metric_names)}
  <h2>S&amp;P 500 Comparison</h2>
  {metric_table(sp500_metric_names)}
  <h2>Latest Portfolio Targets</h2>
  {table(portfolios.sort_values("date").tail(30) if not portfolios.empty else portfolios, 30)}
  <h2>Recent Trades</h2>
  {table(trades.tail(30) if not trades.empty else trades, 30)}
  <h2>Recent Equity Curve</h2>
  {table(equity.tail(30) if not equity.empty else equity, 30)}
  <h2>Factor Sample</h2>
  {table(factors.tail(30) if not factors.empty else factors, 30)}
</body>
</html>
"""
    report_path.write_text(body, encoding="utf-8")
    return report_path


def parse_args() -> argparse.Namespace:
    default_config = StrategyConfig()
    parser = argparse.ArgumentParser(description="Run baseline value strategy pipeline.")
    parser.add_argument(
        "command",
        choices=["quality", "dividends", "pit", "factors", "portfolio", "backtest", "report", "run-all"],
        help="Pipeline step to run.",
    )
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--start-date", default=default_config.start_date)
    parser.add_argument(
        "--rebalance-frequency",
        default=default_config.rebalance_frequency,
        choices=["Y", "1Y", "Q", "1Q", "M", "1M"],
    )
    parser.add_argument("--reporting-lag-days", type=int, default=default_config.reporting_lag_days)
    parser.add_argument("--n-stocks", type=int, default=default_config.n_stocks)
    parser.add_argument("--max-per-sector", type=int, default=default_config.max_per_sector)
    parser.add_argument("--initial-capital", type=float, default=default_config.initial_capital)
    parser.add_argument("--transaction-cost-bps", type=float, default=default_config.transaction_cost_bps)
    parser.add_argument(
        "--benchmark-components",
        nargs="+",
        default=["XLE", "XLI", "XLP"],
        help="Equal-weighted ETF tickers used for the sector benchmark.",
    )
    parser.add_argument(
        "--sp500-benchmark-ticker",
        default="SPY",
        help="ETF/index ticker used as the S&P 500 benchmark.",
    )
    parser.add_argument("--min-market-cap", type=float, default=500_000_000)
    parser.add_argument("--min-momentum-12-1", type=float, default=0.0)
    parser.add_argument("--max-debt-to-ebitda", type=float, default=4.0)
    parser.add_argument("--min-interest-coverage", type=float, default=2.0)
    parser.add_argument("--allow-below-200dma", action="store_true")
    parser.add_argument("--allow-negative-fcf", action="store_true")
    parser.add_argument("--no-skip-existing-dividends", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="Limit universe for smoke tests.")
    return parser.parse_args()


def config_from_args(args: argparse.Namespace) -> StrategyConfig:
    return StrategyConfig(
        start_date=args.start_date,
        reporting_lag_days=args.reporting_lag_days,
        rebalance_frequency=args.rebalance_frequency,
        n_stocks=args.n_stocks,
        max_per_sector=args.max_per_sector,
        initial_capital=args.initial_capital,
        transaction_cost_bps=args.transaction_cost_bps,
        benchmark_components=[
            (ticker.strip().upper(), 1 / len(args.benchmark_components))
            for ticker in args.benchmark_components
        ],
        sp500_benchmark_ticker=args.sp500_benchmark_ticker.strip().upper(),
        min_market_cap=args.min_market_cap,
        min_momentum_12_1=args.min_momentum_12_1,
        require_price_above_200dma=not args.allow_below_200dma,
        require_positive_fcf=not args.allow_negative_fcf,
        max_debt_to_ebitda=args.max_debt_to_ebitda,
        min_interest_coverage=args.min_interest_coverage,
    )


def load_existing_or_build_pit(universe: pd.DataFrame, config: StrategyConfig, output_dir: Path) -> pd.DataFrame:
    path = output_dir / "pit_fundamentals.csv"
    if path.exists():
        df = pd.read_csv(path)
        for col in ["fiscalDateEnding", "available_date"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
        return df
    return build_pit_dataset(universe, config, output_dir)


def load_existing_or_build_factors(
    universe: pd.DataFrame,
    config: StrategyConfig,
    output_dir: Path,
) -> pd.DataFrame:
    path = output_dir / "factors.csv"
    if path.exists():
        df = pd.read_csv(path)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df
    pit = load_existing_or_build_pit(universe, config, output_dir)
    return build_factor_rows(universe, pit, config, output_dir)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    config = config_from_args(args)
    universe = load_universe(DEFAULT_TICKER_FILES)
    if args.limit:
        universe = universe.head(args.limit).copy()

    quality = pd.DataFrame()
    dividend_report = pd.DataFrame()
    pit = pd.DataFrame()
    factors = pd.DataFrame()
    portfolios = pd.DataFrame()
    equity = pd.DataFrame()
    trades = pd.DataFrame()
    metrics = pd.DataFrame()

    if args.command in {"quality", "run-all"}:
        quality = run_data_quality(universe, output_dir)
    elif (output_dir / "data_quality.csv").exists():
        quality = pd.read_csv(output_dir / "data_quality.csv")

    if args.command in {"dividends", "run-all"}:
        dividend_report = download_dividends(
            universe,
            output_dir,
            benchmark_components=config.benchmark_components,
            benchmark_sector=config.benchmark_sector,
            sp500_benchmark_ticker=config.sp500_benchmark_ticker,
            start_date="2005-01-01",
            skip_existing=not args.no_skip_existing_dividends,
        )
    elif (output_dir / "dividends_download_report.csv").exists():
        dividend_report = pd.read_csv(output_dir / "dividends_download_report.csv")

    if args.command in {"pit", "run-all"}:
        pit = build_pit_dataset(universe, config, output_dir)
    elif args.command in {"factors", "portfolio", "backtest", "report"}:
        pit = load_existing_or_build_pit(universe, config, output_dir)

    if args.command in {"factors", "run-all"}:
        if pit.empty:
            pit = load_existing_or_build_pit(universe, config, output_dir)
        factors = build_factor_rows(universe, pit, config, output_dir)
    elif args.command in {"portfolio", "backtest", "report"}:
        factors = load_existing_or_build_factors(universe, config, output_dir)

    if args.command in {"portfolio", "run-all"}:
        if factors.empty:
            factors = load_existing_or_build_factors(universe, config, output_dir)
        portfolios = build_selected_portfolios(factors, config, output_dir)
    elif args.command in {"backtest", "report"} and (output_dir / "selected_portfolios.csv").exists():
        portfolios = pd.read_csv(output_dir / "selected_portfolios.csv")
        portfolios["date"] = pd.to_datetime(portfolios["date"], errors="coerce")

    if args.command in {"backtest", "run-all"}:
        if factors.empty:
            factors = load_existing_or_build_factors(universe, config, output_dir)
        if portfolios.empty:
            portfolios = build_selected_portfolios(factors, config, output_dir)
        equity, trades, _ = run_backtest(universe, factors, portfolios, config, output_dir)
        metrics = compute_metrics(
            equity,
            trades,
            output_dir,
            config.benchmark_components,
            config.benchmark_sector,
            config.sp500_benchmark_ticker,
        )
    elif args.command == "report":
        if (output_dir / "equity_curve.csv").exists():
            equity = pd.read_csv(output_dir / "equity_curve.csv")
        if (output_dir / "trades.csv").exists():
            trades = pd.read_csv(output_dir / "trades.csv")
        if (output_dir / "metrics.csv").exists():
            metrics = pd.read_csv(output_dir / "metrics.csv")
        if not equity.empty and (
            metrics.empty
            or "metric" not in metrics.columns
            or not metrics["metric"].eq("sp500_total_return").any()
        ):
            metrics = compute_metrics(
                equity,
                trades,
                output_dir,
                config.benchmark_components,
                config.benchmark_sector,
                config.sp500_benchmark_ticker,
            )

    if args.command in {"report", "run-all"}:
        if quality.empty and (output_dir / "data_quality.csv").exists():
            quality = pd.read_csv(output_dir / "data_quality.csv")
        if dividend_report.empty and (output_dir / "dividends_download_report.csv").exists():
            dividend_report = pd.read_csv(output_dir / "dividends_download_report.csv")
        if factors.empty and (output_dir / "factors.csv").exists():
            factors = pd.read_csv(output_dir / "factors.csv")
        if portfolios.empty and (output_dir / "selected_portfolios.csv").exists():
            portfolios = pd.read_csv(output_dir / "selected_portfolios.csv")
        if equity.empty and (output_dir / "equity_curve.csv").exists():
            equity = pd.read_csv(output_dir / "equity_curve.csv")
        if trades.empty and (output_dir / "trades.csv").exists():
            trades = pd.read_csv(output_dir / "trades.csv")
        if metrics.empty and (output_dir / "metrics.csv").exists():
            metrics = pd.read_csv(output_dir / "metrics.csv")
        report_path = render_report(output_dir, quality, dividend_report, factors, portfolios, equity, trades, metrics)
        print(f"Report saved to {report_path}")


if __name__ == "__main__":
    main()
