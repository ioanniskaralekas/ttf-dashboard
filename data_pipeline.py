"""
TTF gas market data pipeline.

Pulls two daily series and merges them into a single dataset:
  * Dutch TTF front-month natural gas futures (Yahoo Finance, ticker TTF=F)
  * EU-aggregate gas storage levels (GIE AGSI+ transparency platform)

Also provides a 5-year seasonal storage norm and realized price volatility.

Usage:
    python data_pipeline.py

Requires an AGSI+ API key in a local .env file (see .env.example).
"""

import os
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

TTF_TICKER = "TTF=F"
AGSI_URL = "https://agsi.gie.eu/api"
AGSI_EARLIEST = date(2011, 1, 1)  # first gas day in the AGSI+ EU aggregate
AGSI_MAX_RETRIES = 4
OUTPUT_CSV = "ttf_dataset.csv"
TRADING_DAYS_PER_YEAR = 252

load_dotenv()


def get_ttf_price(period: str = "max") -> pd.DataFrame:
    """Fetch daily TTF front-month futures settlement prices.

    Yahoo's continuous TTF=F series starts in October 2017, so "max" returns
    roughly nine years rather than the full history of the contract.

    Args:
        period: Lookback window in yfinance format (e.g. "6mo", "5y", "max").

    Returns:
        DataFrame with columns: date, ttf_price_eur_mwh, volume.
    """
    history = yf.Ticker(TTF_TICKER).history(period=period, auto_adjust=False)
    if history.empty:
        raise RuntimeError(f"No price data returned from Yahoo Finance for {TTF_TICKER}")

    df = history.reset_index()[["Date", "Close", "Volume"]]
    df.columns = ["date", "ttf_price_eur_mwh", "volume"]
    # Drop the exchange timezone so dates line up with the AGSI gas-day calendar
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    _print_coverage(f"Yahoo Finance {TTF_TICKER}", df["date"])
    return df


def _agsi_get(params: dict, headers: dict) -> dict:
    """GET one AGSI+ page, retrying with exponential backoff on 429/5xx or timeouts."""
    for attempt in range(AGSI_MAX_RETRIES):
        try:
            resp = requests.get(AGSI_URL, params=params, headers=headers, timeout=30)
            if resp.status_code != 429 and resp.status_code < 500:
                resp.raise_for_status()
                return resp.json()
        except (requests.ConnectionError, requests.Timeout):
            if attempt == AGSI_MAX_RETRIES - 1:
                raise
        time.sleep(2 ** attempt)
    resp.raise_for_status()  # out of retries on a 429/5xx: surface the HTTP error


def _fetch_agsi_storage(start: date, end: date, api_key: str | None = None) -> pd.DataFrame:
    """Fetch EU-aggregate daily storage from AGSI+ for an explicit date range.

    Returns:
        DataFrame with columns: date, storage_pct_full, storage_twh.
    """
    api_key = api_key or os.getenv("AGSI_API_KEY")
    if not api_key:
        raise ValueError("AGSI_API_KEY not set — add it to .env (see .env.example)")

    params = {
        "from": start.isoformat(),
        "to": end.isoformat(),
        # EU aggregate lives under type=EU; country= only accepts member-state codes
        "type": "EU",
        "size": 300,
        "page": 1,
    }
    headers = {"x-key": api_key}

    # The API caps pages at 300 rows, so full history takes ~20 requests
    records = []
    while True:
        payload = _agsi_get(params, headers)
        records.extend(payload.get("data", []))
        if params["page"] >= int(payload.get("last_page", 1)):
            break
        params["page"] += 1
        time.sleep(0.2)  # stay well clear of AGSI+ rate limits

    if not records:
        raise RuntimeError(f"No storage data returned from AGSI+ for {start} to {end}")

    df = pd.DataFrame(records)[["gasDayStart", "full", "gasInStorage"]]
    df.columns = ["date", "storage_pct_full", "storage_twh"]
    df["date"] = pd.to_datetime(df["date"])
    # AGSI returns numbers as strings; blanks become NaN
    for col in ("storage_pct_full", "storage_twh"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def get_eu_storage(days_back: int | None = None, api_key: str | None = None) -> pd.DataFrame:
    """Fetch daily EU-aggregate gas storage levels from AGSI+.

    Args:
        days_back: Number of calendar days of history to request. None (the
            default) pulls everything back to the first AGSI+ gas day, 2011-01-01.
        api_key: AGSI+ API key. Defaults to the AGSI_API_KEY environment variable.

    Returns:
        DataFrame with columns: date, storage_pct_full, storage_twh.
    """
    end = date.today()
    start = AGSI_EARLIEST if days_back is None else max(end - timedelta(days=days_back), AGSI_EARLIEST)
    df = _fetch_agsi_storage(start, end, api_key)
    _print_coverage("AGSI+ EU storage", df["date"])
    return df


def day_of_year(dates: pd.Series) -> pd.Series:
    """Map dates onto a fixed 365-day calendar so leap years line up.

    Feb 29 maps to the same day as Feb 28; every later date in a leap year
    is shifted back by one so e.g. 1 Oct is always day 274.
    """
    doy = dates.dt.dayofyear
    after_feb28 = dates.dt.is_leap_year & (doy > 59)
    return doy - after_feb28.astype(int)


def compute_storage_norms(storage: pd.DataFrame, years: int = 5) -> pd.DataFrame:
    """Trailing seasonal storage norm for every year in the history.

    Each year is compared against the `years` complete calendar years before
    it (e.g. 2026 against 2021-2025), so historical dates are never judged
    against a norm built from their own future.

    Args:
        storage: Daily storage with columns date and storage_pct_full.
        years: Number of prior years in the norm.

    Returns:
        DataFrame with columns: year, day_of_year, storage_min, storage_max,
        storage_avg. Years without a full `years` of prior history are omitted.
    """
    df = storage.dropna(subset=["storage_pct_full"])
    df = df.assign(year=df["date"].dt.year, day_of_year=day_of_year(df["date"]))
    # year x day-of-year grid; Feb 28/29 share a slot and are averaged
    grid = df.pivot_table(index="year", columns="day_of_year", values="storage_pct_full")
    grid = grid.reindex(range(grid.index.min(), date.today().year + 1))

    prior = grid.shift(1).rolling(years, min_periods=years)
    stats = {"storage_min": prior.min(), "storage_max": prior.max(), "storage_avg": prior.mean()}
    norms = pd.concat({name: frame.stack() for name, frame in stats.items()}, axis=1)
    return norms.dropna().rename_axis(["year", "day_of_year"]).reset_index()


def get_storage_5y_range(
    years: int = 5, api_key: str | None = None, storage: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Seasonal storage norm for the current year from the last `years` complete years.

    Args:
        years: Number of prior complete calendar years in the norm.
        api_key: AGSI+ API key, used only if `storage` is not supplied.
        storage: Daily storage history to reuse instead of fetching it again.

    Returns:
        DataFrame with columns: day_of_year, storage_min, storage_max, storage_avg.
    """
    current_year = date.today().year
    if storage is None:
        storage = _fetch_agsi_storage(date(current_year - years, 1, 1), date.today(), api_key)
    norms = compute_storage_norms(storage, years)
    return norms[norms["year"] == current_year].drop(columns="year").reset_index(drop=True)


def compute_realized_volatility(df: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    """Rolling annualized realized volatility of TTF prices.

    Uses daily log returns over `window` trading days, annualized with
    sqrt(252). Non-trading days (NaN prices) are dropped first so weekends
    don't create gaps in the return series.

    Returns:
        DataFrame with columns: date, realized_vol_pct.
    """
    prices = df.dropna(subset=["ttf_price_eur_mwh"]).sort_values("date")
    log_returns = np.log(prices["ttf_price_eur_mwh"]).diff()
    vol = log_returns.rolling(window).std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100
    return pd.DataFrame({"date": prices["date"], "realized_vol_pct": vol}).dropna()


def _print_coverage(source: str, dates: pd.Series) -> None:
    """Report the date span a source actually returned."""
    first, last = dates.min(), dates.max()
    years = (last - first).days / 365.25
    print(f"{source}: {first:%Y-%m-%d} to {last:%Y-%m-%d} ({years:.1f} years, {len(dates)} rows)")


def build_dataset(
    prices: pd.DataFrame | None = None, storage: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Merge TTF prices and EU storage on date (outer join, sorted by date).

    Storage is reported every calendar day while futures only trade on
    business days, so weekend rows will have NaN prices.
    """
    prices = get_ttf_price() if prices is None else prices
    storage = get_eu_storage() if storage is None else storage
    merged = pd.merge(prices, storage, on="date", how="outer")
    return merged.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    prices = get_ttf_price()
    print(f"TTF front-month prices ({TTF_TICKER}) — last 5 rows:")
    print(prices.tail(5).to_string(index=False), end="\n\n")

    storage = get_eu_storage()
    print("EU gas storage (AGSI+) — last 5 rows:")
    print(storage.tail(5).to_string(index=False), end="\n\n")

    dataset = build_dataset(prices, storage)
    dataset.to_csv(OUTPUT_CSV, index=False)
    print(f"Saved {len(dataset)} rows "
          f"({dataset['date'].min():%Y-%m-%d} to {dataset['date'].max():%Y-%m-%d}) "
          f"to {OUTPUT_CSV}")
