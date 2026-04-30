# Buffett-Style Stock Screener

A stock analyser built around Warren Buffett's publicly documented investment methodology — owner earnings, ROIC, profit margins, and DCF intrinsic value.

Data is fetched live from Yahoo Finance (no API key required).

---

## What does it do?

You type in a stock ticker (e.g. `AAPL`, `KO`, `TSLA`) and the app:

1. Pulls live financial data from Yahoo Finance
2. Scores the stock out of 100 across seven Buffett-style criteria
3. Calculates an intrinsic value estimate using a 10-year owner earnings DCF
4. Shows a margin of safety analysis — is it trading below fair value?
5. Generates a "Would Buffett Buy?" verdict with a plain-English explanation of why

The sidebar shows today's most-active tickers from Yahoo Finance — click any of them to analyse instantly.

---

## Setup

**Requirements:** Python 3.10+

### 1. Install dependencies

```bash
pip install yfinance requests pandas numpy streamlit
```

### 2. Navigate to the project folder

```bash
cd financial-analysis
```

---

## Running the Web App

```bash
streamlit run app.py
```

Your browser will open at `http://localhost:8501`.

**To use it:**
1. Type a ticker symbol into the search box (e.g. `KO`, `AAPL`, `IOSP`)
2. Press **Enter** or click **Analyse**
3. Wait 5–15 seconds for live data to load from Yahoo Finance
4. Results appear below — verdict, intrinsic value estimate, and score breakdown

> You can also click any ticker in the **Trending** sidebar to analyse it immediately.

---

## Running from the Command Line

Analyse a single ticker and print results to the terminal:

```bash
python buffett_screener.py --ticker KO
```

Screen a custom list of tickers and save to CSV:

```bash
python buffett_screener.py --tickers AAPL MSFT KO
```

Screen the S&P 600 small-cap universe:

```bash
python buffett_screener.py --universe sp600
```

Skip margin of safety calculations (faster):

```bash
python buffett_screener.py --tickers AAPL KO --no-mos
```

---

## Scoring Criteria

Each stock is scored out of 100 across seven criteria:

| Criterion | Weight | What it measures |
|---|---|---|
| EPS Consistency | 20 | Consecutive profitable years + earnings CAGR |
| Return on Equity | 15 | Avg ROE >20%, penalises years below 15% |
| ROIC | 15 | NOPAT / (Equity + Debt), threshold ≥17% |
| Profit Margins | 10 | Gross >40%, Net >20% — moat signal |
| Debt & Liquidity | 15 | D/E, LT debt/NI, current ratio, interest coverage |
| Owner Earnings Yield | 15 | (NI + D&A − CapEx) / market cap |
| Capital Allocation | 10 | NI CAGR + buyback detection |

**Verdict thresholds:**
- **≥65 + in MOS zone** → Buffett Would Buy
- **≥65, above MOS** → Yes — but wait for a lower price
- **≥50** → Worth Watching
- **<50** → Buffett Would Pass

### Margin of Safety

Intrinsic value is calculated via a 10-year owner earnings DCF:
- **Discount rate:** 9%
- **Terminal growth:** 3%
- **MOS entry price:** 30% discount to the bull-case intrinsic value

---

## Notes

- Data is sourced live from Yahoo Finance via `yfinance` (free, no API key required)
- ~4 years of annual financials are available; all historical scoring uses this window
- The 10-year DCF is a forward projection of owner earnings, not a historical lookback
- This is a quantitative screening tool, not investment advice — always do your own research
