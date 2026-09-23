"""
TTF Gas Market Dashboard.

Streamlit front end for the data pipeline: headline metrics plus TTF price
and EU storage charts, filterable by date range.

Usage:
    streamlit run app.py
"""

from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from data_pipeline import build_dataset

LINE_COLOR = "#2a78d6"

st.set_page_config(page_title="TTF Gas Market Dashboard", layout="wide")


@st.cache_data(ttl=3600)
def load_data() -> pd.DataFrame:
    """Pull and merge both sources, cached for an hour across reruns."""
    return build_dataset()


def price_change_pct(prices: pd.Series, days: int = 7) -> float | None:
    """Percent change from the last price on or before (latest date - days)."""
    latest_date = prices.index.max()
    earlier = prices[prices.index <= latest_date - timedelta(days=days)]
    if earlier.empty:
        return None
    return (prices.iloc[-1] / earlier.iloc[-1] - 1) * 100


def line_chart(df: pd.DataFrame, column: str, y_label: str):
    """Single-series time-series chart with a unified hover crosshair."""
    fig = px.line(df, x="date", y=column, labels={"date": "", column: y_label})
    fig.update_traces(line=dict(color=LINE_COLOR, width=2))
    fig.update_layout(hovermode="x unified", margin=dict(l=0, r=0, t=10, b=0))
    return fig


st.title("TTF Gas Market Dashboard")

data = load_data()
prices = data.dropna(subset=["ttf_price_eur_mwh"]).set_index("date")["ttf_price_eur_mwh"]
storage = data.dropna(subset=["storage_pct_full"]).set_index("date")["storage_pct_full"]

# --- Headline metrics (always based on the latest available data) ---
change = price_change_pct(prices)
col1, col2, col3 = st.columns(3)
col1.metric(
    "TTF front-month (EUR/MWh)",
    f"{prices.iloc[-1]:.2f}",
    help=f"Settlement on {prices.index[-1]:%d %b %Y}",
)
col2.metric("7-day price change", "n/a" if change is None else f"{change:+.1f}%")
col3.metric(
    "EU storage fill",
    f"{storage.iloc[-1]:.1f}%",
    help=f"Gas day {storage.index[-1]:%d %b %Y}",
)

# --- Sidebar date filter (applies to both charts) ---
min_date, max_date = data["date"].min().date(), data["date"].max().date()
selected = st.sidebar.date_input(
    "Date range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)
# date_input returns a single date while the user is mid-selection
start, end = selected if len(selected) == 2 else (selected[0], max_date)
mask = data["date"].between(pd.Timestamp(start), pd.Timestamp(end))
filtered = data[mask]

# --- Charts ---
st.subheader("TTF front-month price")
st.plotly_chart(
    line_chart(filtered.dropna(subset=["ttf_price_eur_mwh"]), "ttf_price_eur_mwh", "EUR/MWh"),
    width="stretch",
)

st.subheader("EU gas storage")
st.plotly_chart(
    line_chart(filtered.dropna(subset=["storage_pct_full"]), "storage_pct_full", "% full"),
    width="stretch",
)

st.caption("Sources: Yahoo Finance (TTF=F), GIE AGSI+ transparency platform.")
