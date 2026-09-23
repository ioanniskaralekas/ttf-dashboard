# TTF Dashboard

Data pipeline for the Dutch TTF natural gas market, combining front-month
futures prices with EU-aggregate storage levels.

## Data sources

| Series | Source | Fields | History |
|---|---|---|---|
| TTF front-month futures | Yahoo Finance (`TTF=F`) via `yfinance` | settlement price (EUR/MWh), volume | Oct 2017 onward |
| EU gas storage | [GIE AGSI+](https://agsi.gie.eu/) API | % full, gas in storage (TWh) | Jan 2011 onward |

The pipeline pulls the full available history from both sources (AGSI+ pages
at 300 rows, so this is ~20 requests, with retry and backoff on rate limits).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then add your free AGSI+ API key
```

## Usage

```bash
python data_pipeline.py
```

Prints the latest prices and storage readings and writes the merged daily
dataset to `ttf_dataset.csv`. Storage is reported every calendar day while
futures trade on business days only, so weekend rows have empty price fields.

### Dashboard

```bash
streamlit run app.py
```

- Headline metrics: latest TTF price, 7-day change, EU storage fill and
  30-day realized volatility
- TTF price with rolling 30-day annualized realized volatility
  (std. dev. of daily log returns × √252)
- EU storage against a trailing 5-year seasonal norm: each year is compared
  with the min–max band and average of the five calendar years before it,
  plus today's gap to the average

All charts share a sidebar date-range filter. It defaults to the span of
the TTF price history (from Oct 2017) and can be extended back to 2011 for
storage-only history. Data is cached for an hour.
