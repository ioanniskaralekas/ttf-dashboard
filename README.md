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
