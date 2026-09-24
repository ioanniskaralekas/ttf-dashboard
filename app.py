"""
TTF Gas Market Dashboard.

Streamlit front end for the data pipeline: headline metrics, TTF price and
realized volatility, and EU storage against its 5-year seasonal norm, all
filterable by date range. Theme (colors, Inter font) lives in
.streamlit/config.toml.

Usage:
    streamlit run app.py
"""

import re
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
    get_gas_news,
    get_lng_sendout,
)

LINE_COLOR = "#2a78d6"            # primary series
NORM_COLOR = "#898781"            # 5-year average (neutral, reads on light and dark)
BAND_FILL = "rgba(42, 120, 214, 0.15)"  # light tint of the primary hue
CHART_FONT = "Inter, sans-serif"
VOL_WINDOW = 30
NORM_YEARS = 5
DEFAULT_VIEW_DAYS = 14
# Drag pans, scroll wheel zooms: standard trading-chart interaction
CHART_CONFIG = {"scrollZoom": True, "displaylogo": False}

st.set_page_config(page_title="TTF Gas Market Dashboard", page_icon="⛽", layout="wide")


@st.cache_data(ttl=3600)
def load_data() -> tuple[pd.DataFrame, datetime]:
    """Pull and merge full history from both sources, cached for an hour."""
    return build_dataset(), datetime.now(timezone.utc)


@st.cache_data(ttl=86400)
def load_lng_sendout() -> pd.DataFrame:
    """Three years of EU LNG send-out from ENTSOG, cached for a day.

    The data is daily, and a cold fetch across all terminals takes ~11-14s
    (repeat requests are fast once ENTSOG has cached the query), so one pull
    per day keeps the page quick without losing history.
    """
    df = get_lng_sendout(days_back=365 * 3)
    return df.assign(terminals=[df.attrs["terminals"]] * len(df))  # attrs don't survive caching


@st.cache_data(ttl=1800)
def load_news() -> pd.DataFrame:
    """Latest gas-market headlines, refreshed every 30 minutes."""
    return get_gas_news(limit=15)


def time_ago(moment: datetime, now: datetime) -> str:
    """Relative timestamp such as '2 hours ago' or '1 day ago'."""
    seconds = max((now - moment).total_seconds(), 0)
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            count = int(seconds // size)
            return f"{count} {unit}{'s' if count != 1 else ''} ago"
    return "just now"


def escape_markdown(text: str) -> str:
    """Escape characters that Streamlit markdown would interpret in feed titles."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>$~])", r"\\\1", text)


def price_change(prices: pd.Series, days: int = 7) -> tuple[float, float] | None:
    """Absolute and percent change vs the last price on or before (latest date - days)."""
    latest_date = prices.index.max()
    earlier = prices[prices.index <= latest_date - timedelta(days=days)]
    if earlier.empty:
        return None
    base = earlier.iloc[-1]
    return prices.iloc[-1] - base, (prices.iloc[-1] / base - 1) * 100


def y_range_for(df: pd.DataFrame, columns: list[str], x_range, pad: float = 0.08):
    """y-axis limits fitted to the data inside the visible x window.

    Charts carry full history so users can pan, which would otherwise make
    Plotly scale the y-axis to all-time extremes (e.g. the 2022 spike) and
    flatten the default two-week view. Returns None (autorange) if the
    window holds no data.
    """
    window = df.loc[df["date"].between(*x_range), columns]
    lo, hi = window.min().min(), window.max().max()
    if pd.isna(lo) or pd.isna(hi):
        return None
    span = (hi - lo) or abs(hi) or 1.0
    floor = lo - span * pad
    # Prices, volatility and fill levels can't go negative; don't pad below zero
    if lo >= 0:
        floor = max(floor, 0)
    return [floor, hi + span * pad]


def style_chart(fig: go.Figure, height: int, x_range) -> go.Figure:
    """Shared styling and interaction: Inter, transparent background, drag-to-pan.

    uirevision is tied to the selected range so a new selection resets the
    view, while pans and zooms survive unrelated reruns.
    """
    fig.update_layout(
        height=height,
        dragmode="pan",
        uirevision=f"{x_range[0]:%Y%m%d}-{x_range[1]:%Y%m%d}",
        hovermode="x unified",
        margin=dict(l=0, r=0, t=10, b=0),
        font=dict(family=CHART_FONT),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def line_chart(df: pd.DataFrame, column: str, y_label: str, x_range, height: int = 420):
    """Single-series time-series chart over full history, opened at x_range.

    x_range sets the initial view (and keeps stacked charts aligned); the
    rest of the history stays loaded so dragging pans into it.
    """
    fig = px.line(df, x="date", y=column, labels={"date": "", column: y_label})
    fig.update_traces(line=dict(color=LINE_COLOR, width=2))
    fig.update_xaxes(range=x_range)
    fig.update_yaxes(range=y_range_for(df, [column], x_range))
    return style_chart(fig, height, x_range)


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
    fig.update_yaxes(range=y_range_for(
        storage, ["storage_pct_full", "storage_min", "storage_max", "storage_avg"], x_range
    ))
    return style_chart(fig, height=460, x_range=x_range)


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

min_date, max_date = data["date"].min().date(), data["date"].max().date()

# --- Header ---
with st.container(gap="small"):
    st.title("TTF Gas Market Dashboard")
    st.markdown("Live TTF price, EU storage vs 5-year norms, and realized volatility")
    st.caption(f"Data last updated: {fetched_at:%Y-%m-%d %H:%M} UTC")

# --- Date filter (shared by all charts) ---
# Opens on the last two weeks so no chart looks flat; full history back to
# 2011 stays loaded, reachable by widening the range or panning the charts.
with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
    selected = st.date_input(
        "Date range",
        value=(max_date - timedelta(days=DEFAULT_VIEW_DAYS), max_date),
        min_value=min_date,
        max_value=max_date,
        width=280,
    )
    st.caption("Applies to all charts · drag to pan, scroll to zoom, double-click to reset")
# date_input returns a single date while the user is mid-selection
start, end = selected if len(selected) == 2 else (selected[0], max_date)
x_range = [pd.Timestamp(start), pd.Timestamp(end)]

overview_tab, price_tab, storage_tab, flows_tab, news_tab = st.tabs(
    ["Overview", "Price & Volatility", "Storage", "Flows", "News"]
)

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
                line_chart(prices.reset_index(), "ttf_price_eur_mwh", "EUR/MWh",
                           x_range, height=280),
                width="stretch",
                config=CHART_CONFIG,
                key="overview_price",
            )

# --- Price & Volatility ---
with price_tab:
    with st.container(gap="large"):
        with st.container(border=True):
            section_header("TTF front-month price", "EUR/MWh, daily settlement")
            st.plotly_chart(
                line_chart(prices.reset_index(), "ttf_price_eur_mwh", "EUR/MWh", x_range),
                width="stretch",
                config=CHART_CONFIG,
                key="price",
            )
        with st.container(border=True):
            section_header(
                f"{VOL_WINDOW}-day realized volatility",
                "Annualized standard deviation of daily log returns (× √252)",
            )
            st.plotly_chart(
                line_chart(volatility, "realized_vol_pct", "Volatility (%)",
                           x_range, height=260),
                width="stretch",
                config=CHART_CONFIG,
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
        st.plotly_chart(
            storage_chart(storage, x_range), width="stretch", config=CHART_CONFIG, key="storage"
        )

# --- Flows: EU LNG send-out ---
with flows_tab:
    with st.container(border=True):
        section_header(
            "EU LNG send-out",
            "Regasified LNG entering EU transmission grids, GWh/d (ENTSOG physical flows)",
        )
        try:
            lng = load_lng_sendout()
        except Exception as exc:  # show exactly what went wrong instead of failing silently
            st.warning(f"LNG send-out data is unavailable: {exc}")
        else:
            latest_lng = lng.iloc[-1]
            week_ago = lng[lng["date"] <= latest_lng["date"] - timedelta(days=7)]
            with st.container(horizontal=True, gap="medium"):
                st.metric(
                    "Latest send-out (GWh/d)",
                    f"{latest_lng['lng_sendout_gwh']:,.0f}",
                    delta=None if week_ago.empty else
                    f"{latest_lng['lng_sendout_gwh'] / week_ago.iloc[-1]['lng_sendout_gwh'] - 1:+.1%} w/w",
                    delta_color="off",
                    help=f"Gas day {latest_lng['date']:%d %b %Y}",
                    border=True,
                    width=240,
                )
                st.metric(
                    "7-day average (GWh/d)",
                    f"{lng['lng_sendout_gwh'].tail(7).mean():,.0f}",
                    border=True,
                    width=240,
                )
            st.plotly_chart(
                line_chart(lng, "lng_sendout_gwh", "GWh/d", x_range),
                width="stretch",
                config=CHART_CONFIG,
                key="lng_sendout",
            )
            terminals = latest_lng["terminals"]
            st.caption(
                f"Sum of {len(terminals)} EU terminal entry points reporting to ENTSOG "
                f"(UK terminals excluded; history from {lng['date'].min():%b %Y}). "
                f"The latest gas days appear once at least 90% of terminals have reported."
            )
            with st.expander("Terminals included"):
                st.write(", ".join(terminals))

# --- News: recent gas-market headlines ---
with news_tab:
    try:
        news = load_news()
    except Exception:  # news is supplementary; never let it break the dashboard
        news = pd.DataFrame(columns=["title", "link", "published", "source"])
        news.attrs["failed_feeds"] = ["all feeds"]

    section_header("Gas market headlines", "Latest from public RSS feeds · refreshed every 30 minutes")
    if news.empty:
        st.info("Headlines are unavailable right now. Please check back shortly.")
    now = datetime.now(timezone.utc)
    with st.container(gap="small"):
        for item in news.itertuples():
            with st.container(border=True, gap="small"):
                link = item.link.replace(" ", "%20").replace(")", "%29")  # keep markdown link intact
                st.markdown(f"**[{escape_markdown(item.title)}]({link})**")
                st.caption(f"{item.source} · {time_ago(item.published, now)}")
    failed = news.attrs.get("failed_feeds", [])
    if failed:
        st.caption(f"Unavailable right now: {', '.join(failed)}")

# --- Footer ---
first_norm_year = int(storage.dropna(subset=["storage_avg"])["year"].min())
st.caption(
    f"Sources: Yahoo Finance (TTF=F, from {prices.index.min():%b %Y}), "
    f"GIE AGSI+ transparency platform (from {storage['date'].min():%b %Y}). "
    f"Each year's storage norm uses the {NORM_YEARS} preceding calendar years, "
    f"so the band starts in {first_norm_year}."
)
