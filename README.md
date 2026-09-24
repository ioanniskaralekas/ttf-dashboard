# TTF Gas Market Dashboard

**Live app: [ttf-dashboard.streamlit.app](https://ttf-dashboard.streamlit.app)**

An interactive dashboard for the European natural gas market, built around
the Dutch **TTF** hub, Europe's main gas price benchmark. It brings price,
volatility, storage, LNG supply and news together in one view, using free
public data that refreshes automatically.

> Built as a portfolio project for commodity trading job applications.

## What's in the dashboard

### Overview
The market at a glance. Four headline metrics:
- **TTF price**: latest front-month settlement (€/MWh)
- **7-day change**: price move over the past week, in €/MWh and %
- **EU storage fill**: how full EU gas storage is, and how that compares with the 5-year average
- **30-day volatility**: how much prices have been swinging recently

Plus a compact TTF price chart.

### Price & Volatility
TTF front-month price history since 2017, with **rolling 30-day realized
volatility** below it: the annualized standard deviation of daily log
returns (× √252). It shows when the market has been calm and when it has
been stressed, such as the 2022 energy crisis.

### Storage
EU gas storage levels (% full) against a **5-year seasonal norm**: a shaded
min–max band and a dashed average from the five previous years. A callout
shows how far above or below normal storage is today. Storage is a key
driver of winter supply risk and of the price.

### Flows
**EU LNG send-out**: the daily volume of regasified LNG entering European
gas grids (GWh/d), summed across 30 EU terminals. Since Russian pipeline
supply fell away, LNG has become Europe's main source of marginal supply.

### News
Live gas and energy market headlines from public RSS feeds, refreshed every
30 minutes. Each card shows the headline, its source and how long ago it was
published, and links to the original article.

All charts share one date filter (the last 14 days by default) and work like
trading charts: drag to pan, scroll to zoom, double-click to reset.

## Data sources

| Data | Source | History |
|---|---|---|
| TTF front-month futures | [Yahoo Finance](https://finance.yahoo.com/quote/TTF%3DF/) (`TTF=F`) via `yfinance` | Oct 2017 → |
| EU gas storage | [GIE AGSI+](https://agsi.gie.eu/) transparency platform API | Jan 2011 → |
| EU LNG send-out | [ENTSOG Transparency Platform](https://transparency.entsog.eu/) API | 3 years |
| Headlines | RSS feeds: Reuters (via Google News), Natural Gas Intelligence, LNG Prime, OilPrice.com, Rigzone | Last few days |

<details>
<summary>Methodology notes</summary>

- **Seasonal norm:** each year is compared with the five calendar years
  before it, so historical dates are never judged against their own future.
- **LNG send-out:** ENTSOG has no working EU-level LNG total, so the
  dashboard sums daily physical flow at every EU LNG terminal entry point.
  UK terminals are excluded, and so is Spain's virtual tank point, to avoid
  double counting. The latest days appear once 90% of terminals have reported.
- **News:** only the headline, link, date and source are stored. Feeds that
  mix oil and gas are filtered to gas headlines, and a feed that is down is
  skipped rather than breaking the page.
- **Caching:** prices and storage refresh hourly, news every 30 minutes,
  LNG flows daily.

</details>

## Run it locally

Requires Python 3.10+ and a free AGSI+ API key
([register here](https://agsi.gie.eu/account)).

```bash
git clone https://github.com/ioanniskaralekas/ttf-dashboard.git
cd ttf-dashboard
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then set AGSI_API_KEY=<your key> in .env
streamlit run app.py
```

The dashboard opens at http://localhost:8501.

To fetch the raw price and storage data without the dashboard, run
`python data_pipeline.py`. It writes the merged daily dataset to `ttf_dataset.csv`.

## Project structure

| File | Purpose |
|---|---|
| `data_pipeline.py` | Data fetching and calculations: prices, storage, seasonal norms, volatility, LNG flows, news |
| `app.py` | Streamlit dashboard: layout, charts, metrics |
| `.streamlit/config.toml` | Theme: colours, fonts, light and dark mode |
| `requirements.txt` | Pinned Python dependencies |
