"""
TTF Gas Market Dashboard.

Streamlit front end for the data pipeline: headline metrics, TTF price and
realized volatility, and EU storage against its 5-year seasonal norm, all
filterable by date range. Theme (colors, Inter font) lives in
.streamlit/config.toml.

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
    compute_storage_norms,
    day_of_year,
)

LINE_COLOR = "#2a78d6"            # primary series
NORM_COLOR = "#898781"            # 5-year average (neutral, reads on light and dark)
BAND_FILL = "rgba(42, 120, 214, 0.15)"  # light tint of the primary hue
CHART_FONT = "Inter, sans-serif"
VOL_WINDOW = 30
NORM_YEARS = 5

st.set_page_config(page_title="TTF Gas Market Dashboard", page_icon="⛽", layout="wide")


@st.cache_data(ttl=3600)
def load_data() -> tuple[pd.DataFrame, datetime]:
    """Pull and merge full history from both sources, cached for an hour."""
    return build_dataset(), datetime.now(timezone.utc)


def price_change(prices: pd.Series, days: int = 7) -> tuple[float, float] | None:
    """Absolute and percent change vs the last price on or before (latest date - days)."""
    latest_date = prices.index.max()
    earlier = prices[prices.index <= latest_date - timedelta(days=days)]
    if earlier.empty:
        return None
    base = earlier.iloc[-1]
    return prices.iloc[-1] - base, (prices.iloc[-1] / base - 1) * 100


def style_chart(fig: go.Figure, height: int) -> go.Figure:
    """Shared chart styling: Inter, transparent background, quiet margins."""
    fig.update_layout(
        height=height,
        hovermode="x unified",
        margin=dict(l=0, r=0, t=10, b=0),
        font=dict(family=CHART_FONT),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def line_chart(df: pd.DataFrame, column: str, y_label: str, x_range, height: int = 420):
    """Single-series time-series chart with a unified hover crosshair.

    x_range pins the axis so stacked charts line up even when one series
    starts later (e.g. volatility needs a full window of returns first).
    """
    fig = px.line(df, x="date", y=column, labels={"date": "", column: y_label})
    fig.update_traces(line=dict(color=LINE_COLOR, width=2))
    fig.update_xaxes(range=x_range)
    return style_chart(fig, height)


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
        name=f"Prior {NORM_YEARS}-year range", hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=storage["date"], y=storage["storage_avg"], mode="lines",
        line=dict(color=NORM_COLOR, width=2, dash="dash"),
        name=f"Prior {NORM_YEARS}-year average", hovertemplate="%{y:.1f}%",
    ))
    fig.add_trace(go.Scatter(
        x=storage["date"], y=storage["storage_pct_full"], mode="lines",
        line=dict(color=LINE_COLOR, width=2),
        name="EU storage", hovertemplate="%{y:.1f}%",
    ))
    fig.update_layout(
        yaxis_title="% full",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    fig.update_xaxes(range=x_range)
    return style_chart(fig, height=460)


def section_header(title: str, subtitle: str | None = None) -> None:
    """Card heading with an optional muted one-line description."""
    st.markdown(f"#### {title}")
    if subtitle:
        st.caption(subtitle)


# --- Data ---
data, fetched_at = load_data()

prices = data.dropna(subset=["ttf_price_eur_mwh"]).set_index("date")["ttf_price_eur_mwh"]
storage = data.dropna(subset=["storage_pct_full"])[["date", "storage_pct_full"]]
# Attach each date's trailing norm; years before the first full norm keep NaN bands
storage = storage.assign(year=storage["date"].dt.year, day_of_year=day_of_year(storage["date"]))
storage = storage.merge(
    compute_storage_norms(storage, NORM_YEARS), on=["year", "day_of_year"], how="left"
)
volatility = compute_realized_volatility(data, window=VOL_WINDOW)

latest_storage = storage.iloc[-1]
storage_gap = latest_storage["storage_pct_full"] - latest_storage["storage_avg"]
change = price_change(prices)

# --- Sidebar date filter (applies to all charts) ---
# Default view starts where TTF prices begin so no chart opens empty; the
# selector still reaches back to the start of storage history.
min_date, max_date = data["date"].min().date(), data["date"].max().date()
default_start = prices.index.min().date()
with st.sidebar:
    st.markdown("#### Filters")
    selected = st.date_input(
        "Date range",
        value=(default_start, max_date),
        min_value=min_date,
        max_value=max_date,
    )
    st.caption("Applies to all charts. Headline metrics always show the latest data.")
# date_input returns a single date while the user is mid-selection
start, end = selected if len(selected) == 2 else (selected[0], max_date)
x_range = [pd.Timestamp(start), pd.Timestamp(end)]


def in_range(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["date"].between(*x_range)]


# --- Header ---
with st.container(gap="small"):
    st.title("TTF Gas Market Dashboard")
    st.markdown("Live TTF price, EU storage vs 5-year norms, and realized volatility")
    st.caption(f"Data last updated: {fetched_at:%Y-%m-%d %H:%M} UTC")

overview_tab, price_tab, storage_tab = st.tabs(["Overview", "Price & Volatility", "Storage"])

# --- Overview: headline metrics + compact price chart ---
with overview_tab:
    with st.container(gap="large"):
        price_col, change_col, storage_col, vol_col = st.columns(4, gap="medium")
        price_col.metric(
            "TTF price (€/MWh)",
            f"{prices.iloc[-1]:.2f}",
            help=f"TTF front-month settlement on {prices.index[-1]:%d %b %Y}",
            border=True,
            height="stretch",
        )
        change_col.metric(
            "7d change (€/MWh)",
            "n/a" if change is None else f"{change[0]:+.2f}",
            delta=None if change is None else f"{change[1]:+.1f}%",
            help="Latest settlement vs the last settlement at least 7 days earlier",
            border=True,
            height="stretch",
        )
        storage_col.metric(
            "EU storage fill",
            f"{latest_storage['storage_pct_full']:.1f}%",
            delta=f"{storage_gap:+.1f}pp vs {NORM_YEARS}-yr avg",
            help=f"Gas day {latest_storage['date']:%d %b %Y}",
            border=True,
            height="stretch",
        )
        vol_col.metric(
            f"{VOL_WINDOW}-day volatility",
            f"{volatility['realized_vol_pct'].iloc[-1]:.1f}%",
            help=f"Realized: annualized std. dev. of daily log returns over {VOL_WINDOW} trading days",
            border=True,
            height="stretch",
        )

        with st.container(border=True):
            section_header("TTF front-month price", "EUR/MWh, daily settlement")
            st.plotly_chart(
                line_chart(in_range(prices.reset_index()), "ttf_price_eur_mwh", "EUR/MWh",
                           x_range, height=280),
                width="stretch",
                key="overview_price",
            )

# --- Price & Volatility ---
with price_tab:
    with st.container(gap="large"):
        with st.container(border=True):
            section_header("TTF front-month price", "EUR/MWh, daily settlement")
            st.plotly_chart(
                line_chart(in_range(prices.reset_index()), "ttf_price_eur_mwh", "EUR/MWh", x_range),
                width="stretch",
                key="price",
            )
        with st.container(border=True):
            section_header(
                f"{VOL_WINDOW}-day realized volatility",
                "Annualized standard deviation of daily log returns (× √252)",
            )
            st.plotly_chart(
                line_chart(in_range(volatility), "realized_vol_pct", "Volatility (%)",
                           x_range, height=260),
                width="stretch",
                key="volatility",
            )

# --- Storage vs 5-year norm ---
with storage_tab:
    with st.container(border=True):
        section_header(
            f"EU gas storage vs prior {NORM_YEARS}-year range",
            f"Each year is compared with the {NORM_YEARS} calendar years before it",
        )
        direction = "above" if storage_gap >= 0 else "below"
        st.markdown(
            f"**{storage_gap:+.1f}pp {direction} {NORM_YEARS}-year average** — "
            f"{latest_storage['storage_pct_full']:.1f}% vs {latest_storage['storage_avg']:.1f}% "
            f"on {latest_storage['date']:%d %b %Y}"
        )
        st.plotly_chart(storage_chart(in_range(storage), x_range), width="stretch", key="storage")

# --- Footer ---
first_norm_year = int(storage.dropna(subset=["storage_avg"])["year"].min())
st.caption(
    f"Sources: Yahoo Finance (TTF=F, from {prices.index.min():%b %Y}), "
    f"GIE AGSI+ transparency platform (from {storage['date'].min():%b %Y}). "
    f"Each year's storage norm uses the {NORM_YEARS} preceding calendar years, "
    f"so the band starts in {first_norm_year}."
)
