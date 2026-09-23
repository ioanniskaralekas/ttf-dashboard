"""
TTF gas market data pipeline.

Pulls two daily series and merges them into a single dataset:
  * Dutch TTF front-month natural gas futures (Yahoo Finance, ticker TTF=F)
  * EU-aggregate gas storage levels (GIE AGSI+ transparency platform)

Usage:
    python data_pipeline.py

Requires an AGSI+ API key in a local .env file (see .env.example).
"""

import os
from datetime import date, timedelta

import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

TTF_TICKER = "TTF=F"
AGSI_URL = "https://agsi.gie.eu/api"
OUTPUT_CSV = "ttf_dataset.csv"

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


def get_eu_storage(days_back: int = 180, api_key: str | None = None) -> pd.DataFrame:
    """Fetch daily EU-aggregate gas storage levels from AGSI+.

    Args:
        days_back: Number of calendar days of history to request.
        api_key: AGSI+ API key. Defaults to the AGSI_API_KEY environment variable.

    Returns:
        DataFrame with columns: date, storage_pct_full, storage_twh.
    """
    api_key = api_key or os.getenv("AGSI_API_KEY")
    if not api_key:
        raise ValueError("AGSI_API_KEY not set — add it to .env (see .env.example)")

    end = date.today()
    start = end - timedelta(days=days_back)
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
        raise RuntimeError("No storage data returned from AGSI+")

    df = pd.DataFrame(records)[["gasDayStart", "full", "gasInStorage"]]
    df.columns = ["date", "storage_pct_full", "storage_twh"]
    df["date"] = pd.to_datetime(df["date"])
    # AGSI returns numbers as strings; blanks become NaN
    for col in ("storage_pct_full", "storage_twh"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


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
