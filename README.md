# MoatMap open data

Two datasets from [MoatMap](https://moatmap.ai), a stock research site that scores 25,000+ listed companies in 38 markets on Quality, Value and Momentum:

1. **The decile tracker**: how the ranking has done out of sample. Each month the universe is split into ten deciles on each score, the deciles are frozen, and their forward returns are published as they happen, losing months included. No backtest, no restatement.
2. **The monthly Best Stocks lists**: the 25 highest-scoring companies in each country each month, plus a global list for each pillar, since July 2026.

Both are the same numbers the site publishes at [moatmap.ai/decile-tracker](https://moatmap.ai/decile-tracker) and [moatmap.ai/best-stocks](https://moatmap.ai/best-stocks). The methodology is at [moatmap.ai/methodology](https://moatmap.ai/methodology).

This is research data, not investment advice.

## Quick start

```python
import pandas as pd

base = "https://raw.githubusercontent.com/gavintan777/moatmap-data/main/data"

# Does the top decile beat the bottom one? One row per vintage and score.
summary = pd.read_csv(f"{base}/decile-tracker/summary-investable.csv")
print(summary[summary.rank_field == "stockrank"])

# This month's newcomers to the Best Stocks lists.
best = pd.read_csv(f"{base}/best-stocks/best-stocks.csv")
latest = best[best.edition_date == best.edition_date.max()]
print(latest[latest.new_entry == True][["edition", "rank", "ticker", "name", "stockrank"]])
```

The files are plain UTF-8 CSV, so they open in Excel, Google Sheets or R as they are. `datapackage.json` describes every column in the [Frictionless Data](https://specs.frictionlessdata.io/data-package/) format.

## Files

| File | What it holds |
|---|---|
| `data/decile-tracker/deciles-investable.csv` | Decile returns for the investable universe: market cap of at least $200M and at least $1M a day traded, judged when each vintage is formed. This is the headline series. |
| `data/decile-tracker/deciles-full.csv` | The same for every ranked company, thin and illiquid ones included. Stale prices inflate small-company returns, so read it with care. |
| `data/decile-tracker/summary-investable.csv`, `summary-full.csv` | One row per vintage and score: decile 1 against decile 10, and decile 1 against the MSCI ACWI ETF. Derived from the decile files. |
| `data/decile-tracker/ai-cohorts-*.csv` | Returns for groups formed on the site's AI review verdict (deep-review picks, neutral, concerns), both scopes. |
| `data/best-stocks/best-stocks.csv` | Every Best Stocks edition in one file. |
| `data/best-stocks/editions/YYYY-MM-01.csv` | One file per monthly edition. |

### Decile tracker columns

| Column | Meaning |
|---|---|
| `regime_id` | The scoring version the vintage was formed under. Only the current version is published; a change to the scoring starts a new series. |
| `vintage_date` | The day the deciles were formed (monthly, around the 10th). |
| `decile` | 1 to 10, where 1 holds the highest scores and 10 the lowest. |
| `rank_field` | The score the deciles were formed on: `stockrank`, `quality_rank`, `value_rank`, `momentum_rank`, or a two-factor blend (`qv`, `qm`, `vm`). |
| `scope` | `investable` or `full`. |
| `period_end`, `period_days` | The end of the return window (the next vintage's date) and its length in days. |
| `n_formed`, `n_stocks`, `coverage` | Companies in the decile when formed, companies with a price at `period_end`, and the share of the two. A company that shrinks or stops trading stays in its vintage. |
| `n_price_fallback` | Companies priced from the site's stored daily prices because the fresh adjusted price pull had none. |
| `avg_return_local`, `avg_return_usd`, `median_return_usd` | Equal-weighted total return (dividends reinvested, split-adjusted) in each stock's own currency and in US dollars, and the median in dollars. |
| `hit_rate` | The share of the decile with a positive dollar return. |
| `spy_return`, `qqq_return`, `acwi_return` | The S&P 500, Nasdaq-100 and MSCI ACWI ETFs' price returns over the same window, for reference. |
| `computed_at` | When the row was last computed (UTC). |

The AI cohort files carry `cohort_key` and `cohort_label` in place of `decile` and `rank_field`.

### Best Stocks columns

| Column | Meaning |
|---|---|
| `edition_date` | The month of the edition (the 1st). |
| `edition` | The country edition (`US`, `MY`, `JP`, ...) or `GLOBAL`. |
| `list` | `stockrank` for a country edition. The global edition has one list per pillar: `stockrank`, `quality_rank`, `value_rank`, `momentum_rank`. |
| `rank` | 1 to 25 within the list. |
| `ticker`, `name`, `listing_market`, `sector` | The company. Tickers use Yahoo Finance suffixes (`4324.KL`, `7203.T`). |
| `stockrank` | The overall score, 0 to 100, a percentile against every ranked company. |
| `quality_rank`, `value_rank`, `momentum_rank` | The three pillar scores, 0 to 100, each ranked against the company's sector peers. |
| `insider_buy`, `buyback` | Whether directors bought shares, or the company bought back its own, in the window the edition looked at. |
| `new_entry` | `true` if the company was not on the same list the month before, `false` if it was, empty for a list's first month here. |
| `why` | One line on what drove the score. Editions before September 2026 have none. |

Each country edition lists companies above a market-cap floor set for that country. The site states the floor on each country's page. Valuation figures the site shows beside each company (market cap, P/E, P/B, dividend yield) come from a third-party data vendor and are not included here.

## Updates

A GitHub Action (`.github/workflows/update.yml`) runs `scripts/update.py` on the 4th and 14th of each month, after each new Best Stocks edition and decile vintage, and commits whatever the site has published since. It reads only MoatMap's public endpoints, so anyone can run it. A past edition never changes, a vintage's deciles are never re-formed, and its returns are fixed once its window closes.

## Licence and citation

The data is released under [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/). Use it for anything, including commercially, as long as you credit **MoatMap (moatmap.ai)** with a link. See `CITATION.cff` for a citation.

No warranty: the scores rest on company filings and market data that can be wrong or late. Check anything you rely on at the source.
