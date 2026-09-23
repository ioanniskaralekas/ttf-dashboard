# TTF Dashboard

Data pipeline for the Dutch TTF natural gas market, combining front-month
futures prices with EU-aggregate storage levels.

## Data sources

| Series | Source | Fields |
|---|---|---|
| TTF front-month futures | Yahoo Finance (`TTF=F`) via `yfinance` | settlement price (EUR/MWh), volume |
| EU gas storage | [GIE AGSI+](https://agsi.gie.eu/) API | % full, gas in storage (TWh) |

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
- EU storage against its 5-year seasonal norm: min–max band and average
  from the last five complete years, plus the gap to the average today

All charts share a sidebar date-range filter. Live data is cached for an
hour, the 5-year norm for a day.
