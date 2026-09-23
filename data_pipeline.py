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
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

TTF_TICKER = "TTF=F"
AGSI_URL = "https://agsi.gie.eu/api"
OUTPUT_CSV = "ttf_dataset.csv"
TRADING_DAYS_PER_YEAR = 252

load_dotenv()


def get_ttf_price(period: str = "6mo") -> pd.DataFrame:
    """Fetch daily TTF front-month futures settlement prices.

    Args:
        period: Lookback window in yfinance format (e.g. "1mo", "6mo", "1y").

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
    return df


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

    # Walk through result pages in case the window exceeds the page size
    records = []
    while True:
        resp = requests.get(AGSI_URL, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        records.extend(payload.get("data", []))
        if params["page"] >= int(payload.get("last_page", 1)):
            break
        params["page"] += 1

    if not records:
        raise RuntimeError(f"No storage data returned from AGSI+ for {start} to {end}")

    df = pd.DataFrame(records)[["gasDayStart", "full", "gasInStorage"]]
    df.columns = ["date", "storage_pct_full", "storage_twh"]
    df["date"] = pd.to_datetime(df["date"])
    # AGSI returns numbers as strings; blanks become NaN
    for col in ("storage_pct_full", "storage_twh"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def get_eu_storage(days_back: int = 180, api_key: str | None = None) -> pd.DataFrame:
    """Fetch daily EU-aggregate gas storage levels from AGSI+.

    Args:
        days_back: Number of calendar days of history to request.
        api_key: AGSI+ API key. Defaults to the AGSI_API_KEY environment variable.

    Returns:
        DataFrame with columns: date, storage_pct_full, storage_twh.
    """
    end = date.today()
    return _fetch_agsi_storage(end - timedelta(days=days_back), end, api_key)


def day_of_year(dates: pd.Series) -> pd.Series:
    """Map dates onto a fixed 365-day calendar so leap years line up.

    Feb 29 maps to the same day as Feb 28; every later date in a leap year
    is shifted back by one so e.g. 1 Oct is always day 274.
    """
    doy = dates.dt.dayofyear
    after_feb28 = dates.dt.is_leap_year & (doy > 59)
    return doy - after_feb28.astype(int)


def get_storage_5y_range(years: int = 5, api_key: str | None = None) -> pd.DataFrame:
    """Seasonal storage norm from the last `years` complete calendar years.

    Pulls each full year from AGSI+ and aggregates storage % full by
    day-of-year, giving the min/max band and average used as a seasonal norm.

    Returns:
        DataFrame with columns: day_of_year, storage_min, storage_max, storage_avg.
    """
    current_year = date.today().year
    history = pd.concat(
        _fetch_agsi_storage(date(y, 1, 1), date(y, 12, 31), api_key)
        for y in range(current_year - years, current_year)
    )
    history["day_of_year"] = day_of_year(history["date"])

    norm = (
        history.groupby("day_of_year")["storage_pct_full"]
        .agg(storage_min="min", storage_max="max", storage_avg="mean")
        .reset_index()
    )
    return norm


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
