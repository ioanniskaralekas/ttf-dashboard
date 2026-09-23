"""
TTF Gas Market Dashboard.

Streamlit front end for the data pipeline: headline metrics, TTF price and
realized volatility, and EU storage against its 5-year seasonal norm, all
filterable by date range.

Usage:
    streamlit run app.py
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data_pipeline import (
    build_dataset,
    compute_realized_volatility,
    day_of_year,
    get_storage_5y_range,
)

LINE_COLOR = "#2a78d6"            # primary series
NORM_COLOR = "#898781"            # 5-year average (neutral, reads on light and dark)
BAND_FILL = "rgba(42, 120, 214, 0.15)"  # light tint of the primary hue
VOL_WINDOW = 30

st.set_page_config(page_title="TTF Gas Market Dashboard", page_icon="⛽", layout="wide")


@st.cache_data(ttl=3600)
def load_data() -> tuple[pd.DataFrame, datetime]:
    """Pull and merge both sources, cached for an hour across reruns."""
    return build_dataset(), datetime.now(timezone.utc)


@st.cache_data(ttl=24 * 3600)
def load_storage_norm() -> pd.DataFrame:
    """5-year seasonal storage norm; historical, so cached for a day."""
    return get_storage_5y_range()


def price_change_pct(prices: pd.Series, days: int = 7) -> float | None:
    """Percent change from the last price on or before (latest date - days)."""
    latest_date = prices.index.max()
    earlier = prices[prices.index <= latest_date - timedelta(days=days)]
    if earlier.empty:
        return None
    return (prices.iloc[-1] / earlier.iloc[-1] - 1) * 100


def line_chart(df: pd.DataFrame, column: str, y_label: str, x_range, height: int = 450):
    """Single-series time-series chart with a unified hover crosshair.

    x_range pins the axis so stacked charts line up even when one series
    starts later (e.g. volatility needs a full window of returns first).
    """
    fig = px.line(df, x="date", y=column, labels={"date": "", column: y_label})
    fig.update_traces(line=dict(color=LINE_COLOR, width=2))
    fig.update_layout(hovermode="x unified", height=height, margin=dict(l=0, r=0, t=10, b=0))
    fig.update_xaxes(range=x_range)
    return fig


def storage_chart(storage: pd.DataFrame, x_range) -> go.Figure:
    """Current storage line over the 5-year min-max band and average."""
    fig = go.Figure()
    # Band: invisible upper edge, then lower edge filled up to it with tonexty
    fig.add_trace(go.Scatter(
        x=storage["date"], y=storage["storage_max"], mode="lines",
        line=dict(width=0), hoverinfo="skip", showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=storage["date"], y=storage["storage_min"], mode="lines",
        line=dict(width=0), fill="tonexty", fillcolor=BAND_FILL,
        name="5-year range", hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=storage["date"], y=storage["storage_avg"], mode="lines",
        line=dict(color=NORM_COLOR, width=2, dash="dash"),
        name="5-year average", hovertemplate="%{y:.1f}%",
    ))
    fig.add_trace(go.Scatter(
        x=storage["date"], y=storage["storage_pct_full"], mode="lines",
        line=dict(color=LINE_COLOR, width=2),
        name=f"{storage['date'].dt.year.max()}", hovertemplate="%{y:.1f}%",
    ))
    fig.update_layout(
        hovermode="x unified",
        height=450,
        margin=dict(l=0, r=0, t=10, b=0),
        yaxis_title="% full",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    fig.update_xaxes(range=x_range)
    return fig


# --- Data ---
data, fetched_at = load_data()
norm = load_storage_norm()

prices = data.dropna(subset=["ttf_price_eur_mwh"]).set_index("date")["ttf_price_eur_mwh"]
storage = data.dropna(subset=["storage_pct_full"])[["date", "storage_pct_full"]]
storage = storage.assign(day_of_year=day_of_year(storage["date"])).merge(norm, on="day_of_year")
volatility = compute_realized_volatility(data, window=VOL_WINDOW)

# --- Header ---
st.title("TTF Gas Market Dashboard")
st.markdown("Live TTF price, EU storage vs 5-year norms, and realized volatility")
st.caption(f"Data last updated: {fetched_at:%Y-%m-%d %H:%M} UTC")

# --- Headline metrics (always based on the latest available data) ---
change = price_change_pct(prices)
latest_storage = storage.iloc[-1]
col1, col2, col3, col4 = st.columns(4)
col1.metric(
    "TTF front-month (EUR/MWh)",
    f"{prices.iloc[-1]:.2f}",
    help=f"Settlement on {prices.index[-1]:%d %b %Y}",
)
col2.metric("7-day price change", "n/a" if change is None else f"{change:+.1f}%")
col3.metric(
    "EU storage fill",
    f"{latest_storage['storage_pct_full']:.1f}%",
    help=f"Gas day {latest_storage['date']:%d %b %Y}",
)
col4.metric(
    f"{VOL_WINDOW}-day realized volatility",
    f"{volatility['realized_vol_pct'].iloc[-1]:.1f}%",
    help=f"Annualized std. dev. of daily log returns over {VOL_WINDOW} trading days",
)

# --- Sidebar date filter (applies to all charts) ---
min_date, max_date = data["date"].min().date(), data["date"].max().date()
selected = st.sidebar.date_input(
    "Date range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)
# date_input returns a single date while the user is mid-selection
start, end = selected if len(selected) == 2 else (selected[0], max_date)
x_range = [pd.Timestamp(start), pd.Timestamp(end)]


def in_range(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["date"].between(*x_range)]


# --- Price and volatility ---
st.subheader("TTF front-month price")
st.plotly_chart(
    line_chart(in_range(prices.reset_index()), "ttf_price_eur_mwh", "EUR/MWh", x_range),
    width="stretch",
)

st.markdown(f"**{VOL_WINDOW}-day realized volatility** (annualized)")
st.plotly_chart(
    line_chart(in_range(volatility), "realized_vol_pct", "Volatility (%)", x_range, height=220),
    width="stretch",
)

# --- Storage vs 5-year norm ---
st.subheader("EU gas storage vs 5-year range")
gap = latest_storage["storage_pct_full"] - latest_storage["storage_avg"]
direction = "above" if gap >= 0 else "below"
st.markdown(
    f"**{gap:+.1f}pp {direction} 5-year average** — "
    f"{latest_storage['storage_pct_full']:.1f}% vs {latest_storage['storage_avg']:.1f}% "
    f"on {latest_storage['date']:%d %b %Y}"
)
st.plotly_chart(storage_chart(in_range(storage), x_range), width="stretch")

norm_years = f"{max_date.year - 5}–{max_date.year - 1}"
st.caption(
    f"Sources: Yahoo Finance (TTF=F), GIE AGSI+ transparency platform. "
    f"5-year range covers {norm_years}."
)
