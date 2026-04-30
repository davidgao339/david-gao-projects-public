"""
Buffett-Style Stock Screener — Owner Earnings Methodology
==========================================================
Criteria aligned with Buffett's publicly documented philosophy:

  - EPS growth consistency (no losses, growing over history)
  - Return on Equity (avg >20%, penalise years <15%)
  - Return on Invested Capital (avg ≥17%)
  - Profit margins (gross >40%, net >20% — moat indicators)
  - Debt & liquidity (D/E <0.5, LT debt <5x NI, CR >1.5, IC >8x)
  - Owner earnings yield: (NI + D&A − CapEx) / market cap
  - Capital allocation: earnings CAGR + buyback evidence

Valuation / MOS: 10-year owner-earnings DCF discounted at 9%,
  terminal value at 3% perpetual growth.
  MOS entry = 30% discount to high intrinsic value estimate.

Note: yfinance provides ~4 years of annual financials.
      All historical scoring uses the available 4-year window.
      The 10-year DCF is a forward projection, not a historical lookback.
      Clear .screener_cache/ after upgrading — new fields added.

Data sources: yfinance (free), iShares ETF holdings (free)

Usage:
    pip install yfinance requests pandas numpy tabulate
    python buffett_screener.py
    python buffett_screener.py --universe sp600
    python buffett_screener.py --universe russell2000
    python buffett_screener.py --tickers IOSP GRC FMCB ODC NPK
    python buffett_screener.py --universe sp600 --workers 8 --cache-dir .cache

Output: Ranked table + CSV saved to buffett_scores_<label>_<date>.csv
"""

import argparse
import dataclasses
import json
import os
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from io import StringIO
from typing import Optional

import numpy as np
import pandas as pd
import requests
import yfinance as yf

warnings.filterwarnings("ignore")

# ──────────────────────────────────────────────
# UNIVERSE SOURCES
# ──────────────────────────────────────────────
UNIVERSE_URLS = {
    "sp600": (
        "https://www.ishares.com/us/products/239774/ishares-core-sp-small-cap-etf"
        "/1467271812596.ajax?fileType=csv&fileName=IJR_holdings&dataType=fund"
    ),
    "russell2000": (
        "https://www.ishares.com/us/products/239707/ishares-russell-2000-etf"
        "/1467271812596.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund"
    ),
}

# ──────────────────────────────────────────────
# DEFAULT UNIVERSE
# ──────────────────────────────────────────────
DEFAULT_TICKERS = [
    "IOSP",   # Innospec - specialty chemicals
    "GRC",    # Gorman-Rupp - pumps, 76yr dividend streak
    "ODC",    # Oil-Dri Corp - cat litter / minerals niche
    "NPK",    # National Presto - appliances + defense
    "WABC",   # Westamerica Bancorporation - conservative bank
    "FMAO",   # Farmers & Merchants (Ohio) - community bank
    "CBSH",   # Commerce Bancshares - quality midwest bank
    "HWKN",   # Hawkins Inc - specialty chemicals distributor
    "MGRC",   # McGrath RentCorp - modular space / electronics rental
    "USLM",   # US Lime & Minerals - essential industrial mineral
    "SRCE",   # 1st Source Corp - Indiana community bank
    "CASS",   # Cass Information Systems - niche payment processing
    "HCSG",   # Healthcare Services Group
    "TNC",    # Tennant Company - industrial cleaning equipment
    "AWR",    # American States Water - regulated utility, 69yr div growth
]

# ──────────────────────────────────────────────
# SCORING WEIGHTS  (sum to 100)
# Removed: revenue_stability, dividend_reliability, net_cash_bonus (FCF yield merged into OE yield)
# Added:   roic, profit_margins, capital_allocation
# ──────────────────────────────────────────────
WEIGHTS = {
    "eps_consistency":       20,  # Consistent + growing EPS, no losses
    "return_on_equity":      15,  # Avg ROE >20%, consistent (no yr <15%)
    "roic":                  15,  # Avg ROIC ≥17% — true capital efficiency
    "profit_margins":        10,  # Gross >40%, Net >20% — moat signal
    "debt_liquidity":        15,  # D/E, LT debt/NI, current ratio, interest coverage
    "owner_earnings_yield":  15,  # (NI + D&A − CapEx) / mkt cap — valuation
    "capital_allocation":    10,  # Earnings CAGR + buyback evidence
}

assert sum(WEIGHTS.values()) == 100


# ──────────────────────────────────────────────
# UNIVERSE FETCHER
# ──────────────────────────────────────────────

def fetch_universe(universe: str) -> list[str]:
    """Download ticker list from iShares ETF holdings CSV."""
    url = UNIVERSE_URLS.get(universe)
    if not url:
        raise ValueError(f"Unknown universe '{universe}'. Choose: {list(UNIVERSE_URLS)}")

    print(f"  Downloading {universe} universe from iShares...", flush=True)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.ishares.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()

    lines = resp.text.splitlines()
    start_row = None
    for i, line in enumerate(lines):
        if line.startswith("Ticker,") or line.startswith('"Ticker",'):
            start_row = i
            break

    if start_row is None:
        raise ValueError(
            "Could not find 'Ticker' header in iShares CSV. "
            "The download format may have changed."
        )

    df = pd.read_csv(StringIO("\n".join(lines[start_row:])))
    if "Asset Class" in df.columns:
        df = df[df["Asset Class"] == "Equity"]

    tickers = df["Ticker"].dropna().astype(str).str.strip().tolist()
    tickers = [
        t for t in tickers
        if t and " " not in t and "." not in t and len(t) <= 5
    ]
    print(f"  Found {len(tickers)} equity tickers in {universe}", flush=True)
    return tickers


# ──────────────────────────────────────────────
# DISK CACHE (daily, per ticker)
# ──────────────────────────────────────────────

def _cache_path(ticker: str, cache_dir: str) -> str:
    day_dir = os.path.join(cache_dir, date.today().isoformat())
    os.makedirs(day_dir, exist_ok=True)
    return os.path.join(day_dir, f"{ticker}.json")


def _load_cache(ticker: str, cache_dir: str):
    path = _cache_path(ticker, cache_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        valid_fields = {f.name for f in dataclasses.fields(StockData)}
        return StockData(**{k: v for k, v in data.items() if k in valid_fields})
    except Exception:
        return None


def _save_cache(sd, cache_dir: str):
    path = _cache_path(sd.ticker, cache_dir)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dataclasses.asdict(sd), f)
    except Exception:
        pass


# ──────────────────────────────────────────────
# SCORING FUNCTIONS  (each returns 0.0–1.0)
# ──────────────────────────────────────────────

def score_eps_consistency(net_income_history: list,
                           eps_history: list) -> tuple[float, str]:
    """
    Positive, growing EPS over the available ~4-year window.
    Uses EPS if available, falls back to net income.
    Weight: 55% consistency (no losses), 45% growth CAGR.
    """
    data = eps_history if eps_history else net_income_history
    if not data:
        return 0.0, "No earnings data"

    positive = sum(1 for x in data if x and x > 0)
    total = len(data)
    loss_penalty = (total - positive) / total
    consistency_score = max(0.0, 1.0 - loss_penalty * 2)

    valid = [x for x in data if x and x > 0]
    growth_score = 0.3
    cagr_str = ""

    if len(valid) >= 2:
        oldest, newest = valid[-1], valid[0]  # yfinance: most recent first
        if oldest > 0 and newest > 0:
            n = len(valid) - 1
            cagr_pct = ((newest / oldest) ** (1 / n) - 1) * 100
            cagr_str = f", CAGR {cagr_pct:.1f}%"
            if cagr_pct >= 10:
                growth_score = 1.0
            elif cagr_pct >= 7:
                growth_score = 0.80
            elif cagr_pct >= 4:
                growth_score = 0.60
            elif cagr_pct >= 0:
                growth_score = 0.40
            else:
                growth_score = 0.10

    score = consistency_score * 0.55 + growth_score * 0.45
    return score, f"{positive}/{total} profitable yrs{cagr_str}"


def score_return_on_equity(roe_values: list) -> tuple[float, str]:
    """
    Avg ROE >20% over available ~4-year window, no single year below 15%.
    Consistency penalty reduces score proportionally to years below 15%.
    """
    valid = [r for r in roe_values if r is not None and not np.isnan(r)]
    if not valid:
        return 0.0, "No ROE data"

    avg_roe = np.mean(valid) * 100
    years_below_15 = sum(1 for r in valid if r * 100 < 15)
    consistency_penalty = years_below_15 / len(valid)

    if avg_roe >= 20:
        base = 1.0
    elif avg_roe >= 15:
        base = 0.75
    elif avg_roe >= 12:
        base = 0.50
    elif avg_roe >= 8:
        base = 0.30
    else:
        base = 0.10

    score = base * (1 - consistency_penalty * 0.35)
    detail = f"Avg ROE {avg_roe:.1f}%"
    if years_below_15:
        detail += f", {years_below_15}/{len(valid)} yrs <15%"
    return score, detail


def score_roic(roic_values: list) -> tuple[float, str]:
    """
    ROIC = NOPAT / (Equity + Debt). Buffett threshold: avg ≥17%.
    Measures whether the business earns well on all capital deployed.
    """
    valid = [r for r in roic_values if r is not None and not np.isnan(r)]
    if not valid:
        return 0.3, "No ROIC data"

    avg_roic = np.mean(valid) * 100
    if avg_roic >= 22:
        score = 1.0
    elif avg_roic >= 17:
        score = 0.85
    elif avg_roic >= 13:
        score = 0.65
    elif avg_roic >= 9:
        score = 0.40
    elif avg_roic >= 5:
        score = 0.20
    else:
        score = 0.05

    return score, f"Avg ROIC {avg_roic:.1f}%"


def score_profit_margins(gross_margin: Optional[float],
                          net_margin: Optional[float]) -> tuple[float, str]:
    """
    Gross >40% and Net >20% signal durable pricing power — Buffett's moat.
    Commodity businesses with thin margins fail this screen.
    """
    if gross_margin is None and net_margin is None:
        return 0.3, "No margin data"

    scores = []
    parts = []

    if gross_margin is not None:
        gm = gross_margin * 100
        if gm >= 60:
            scores.append(1.0)
        elif gm >= 40:
            scores.append(0.85)
        elif gm >= 25:
            scores.append(0.55)
        elif gm >= 15:
            scores.append(0.30)
        else:
            scores.append(0.10)
        parts.append(f"GM {gm:.0f}%")

    if net_margin is not None:
        nm = net_margin * 100
        if nm >= 20:
            scores.append(1.0)
        elif nm >= 15:
            scores.append(0.80)
        elif nm >= 10:
            scores.append(0.60)
        elif nm >= 5:
            scores.append(0.35)
        else:
            scores.append(0.10)
        parts.append(f"NM {nm:.0f}%")

    return float(np.mean(scores)), " | ".join(parts)


def score_debt_liquidity(debt_to_equity: Optional[float],
                          long_term_debt: Optional[float],
                          avg_net_income: Optional[float],
                          current_ratio: Optional[float],
                          interest_expense: Optional[float],
                          ebit: Optional[float],
                          total_cash: Optional[float],
                          total_debt: Optional[float]) -> tuple[float, str]:
    """
    Four sub-checks averaged:
      D/E <0.5 | LT debt <5x avg NI | Current ratio >1.5 | Interest coverage >8x
    Net cash position earns full marks outright.
    """
    if total_cash is not None and total_debt is not None and total_cash > total_debt:
        net = (total_cash - total_debt) / 1e6
        return 1.0, f"Net cash +${net:.0f}M"

    scores = []
    details = []

    if debt_to_equity is not None:
        de = debt_to_equity / 100 if debt_to_equity > 10 else debt_to_equity
        if de <= 0.25:
            scores.append(1.0)
        elif de <= 0.5:
            scores.append(0.80)
        elif de <= 1.0:
            scores.append(0.50)
        elif de <= 2.0:
            scores.append(0.20)
        else:
            scores.append(0.0)
        details.append(f"D/E {de:.2f}")

    if long_term_debt is not None and avg_net_income and avg_net_income > 0:
        lt_ratio = long_term_debt / avg_net_income
        if lt_ratio <= 2:
            scores.append(1.0)
        elif lt_ratio <= 5:
            scores.append(0.65)
        elif lt_ratio <= 8:
            scores.append(0.30)
        else:
            scores.append(0.0)
        details.append(f"LTD {lt_ratio:.1f}x NI")

    if current_ratio is not None:
        if current_ratio >= 2.0:
            scores.append(1.0)
        elif current_ratio >= 1.5:
            scores.append(0.75)
        elif current_ratio >= 1.0:
            scores.append(0.40)
        else:
            scores.append(0.0)
        details.append(f"CR {current_ratio:.1f}")

    if interest_expense and ebit and interest_expense > 0:
        ic = ebit / interest_expense
        if ic >= 10:
            scores.append(1.0)
        elif ic >= 8:
            scores.append(0.85)
        elif ic >= 5:
            scores.append(0.60)
        elif ic >= 3:
            scores.append(0.30)
        else:
            scores.append(0.0)
        details.append(f"IC {ic:.1f}x")

    if not scores:
        return 0.5, "Insufficient data"

    return float(np.mean(scores)), " | ".join(details)


def score_owner_earnings_yield(owner_earnings_history: list,
                                market_cap: Optional[float],
                                trailing_pe: Optional[float],
                                forward_pe: Optional[float]) -> tuple[float, str]:
    """
    Owner earnings yield = avg(NI + D&A − CapEx) / market cap.
    Falls back to 1/P/E when owner earnings data unavailable.
    Buffett prefers this over EBITDA or raw earnings yield.
    """
    if not market_cap or market_cap <= 0:
        return 0.3, "No market cap"

    valid_oe = [x for x in owner_earnings_history
                if x is not None and not np.isnan(x)] if owner_earnings_history else []

    if valid_oe:
        avg_oe = np.mean(valid_oe)
        yld = (avg_oe / market_cap) * 100
        if yld >= 9:
            score = 1.0
        elif yld >= 7:
            score = 0.85
        elif yld >= 5:
            score = 0.65
        elif yld >= 3:
            score = 0.40
        elif yld > 0:
            score = 0.15
        else:
            score = 0.0
        return score, f"OE yield {yld:.1f}%"

    pes = [p for p in [trailing_pe, forward_pe] if p and 0 < p < 100]
    if pes:
        pe = min(pes)
        yld = (1 / pe) * 100
        if pe <= 10:
            score = 1.0
        elif pe <= 13:
            score = 0.85
        elif pe <= 16:
            score = 0.65
        elif pe <= 20:
            score = 0.40
        elif pe <= 25:
            score = 0.20
        else:
            score = 0.05
        return score, f"Earnings yield {yld:.1f}% (P/E {pe:.1f}x, est)"

    return 0.3, "No valuation data"


def score_capital_allocation(net_income_history: list,
                              eps_history: list) -> tuple[float, str]:
    """
    Proxy for management quality:
      - Primary: net income CAGR
      - Bonus: EPS growing faster than NI signals share buybacks
    Replaces dividend criterion — Buffett values reinvestment over payouts.
    """
    valid_ni = [x for x in net_income_history if x and x > 0] if net_income_history else []
    valid_eps = [x for x in eps_history if x and x > 0] if eps_history else []

    if len(valid_ni) < 2:
        return 0.3, "Insufficient data"

    n_ni = len(valid_ni) - 1
    ni_cagr = (valid_ni[0] / valid_ni[-1]) ** (1 / n_ni) - 1  # newest / oldest

    parts = [f"NI CAGR {ni_cagr*100:.1f}%"]
    buyback_bonus = 0.0

    if len(valid_eps) >= 2:
        n_eps = len(valid_eps) - 1
        eps_cagr = (valid_eps[0] / valid_eps[-1]) ** (1 / n_eps) - 1
        parts.append(f"EPS CAGR {eps_cagr*100:.1f}%")
        if (eps_cagr - ni_cagr) > 0.02:
            buyback_bonus = 0.15
            parts.append("buybacks detected")

    if ni_cagr >= 0.12:
        base = 1.0
    elif ni_cagr >= 0.08:
        base = 0.80
    elif ni_cagr >= 0.05:
        base = 0.60
    elif ni_cagr >= 0.02:
        base = 0.40
    elif ni_cagr >= 0:
        base = 0.25
    else:
        base = 0.10

    return min(1.0, base + buyback_bonus), " | ".join(parts)


# ──────────────────────────────────────────────
# DATA STRUCTURES
# ──────────────────────────────────────────────

@dataclass
class StockData:
    ticker: str
    name: str = ""
    sector: str = ""
    industry: str = ""
    market_cap: Optional[float] = None
    trailing_pe: Optional[float] = None
    forward_pe: Optional[float] = None
    trailing_eps: Optional[float] = None
    shares_outstanding: Optional[float] = None
    debt_to_equity: Optional[float] = None
    total_cash: Optional[float] = None
    total_debt: Optional[float] = None
    long_term_debt: Optional[float] = None
    free_cash_flow: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    current_ratio: Optional[float] = None
    roe_values: list = field(default_factory=list)
    roic_values: list = field(default_factory=list)
    net_income_history: list = field(default_factory=list)
    eps_history: list = field(default_factory=list)
    ebit_history: list = field(default_factory=list)
    interest_expense_history: list = field(default_factory=list)
    da_history: list = field(default_factory=list)
    capex_history: list = field(default_factory=list)
    owner_earnings_history: list = field(default_factory=list)
    last_report_date: str = ""
    error: str = ""


# ──────────────────────────────────────────────
# DATA FETCHER
# ──────────────────────────────────────────────

def _extract_row(df: pd.DataFrame, candidates: list) -> list:
    """Return first matching row from a DataFrame as a list (most-recent first)."""
    for name in candidates:
        if name in df.index:
            return [df.loc[name, c] for c in df.columns if pd.notna(df.loc[name, c])]
    return []


def _ttm_row(df: pd.DataFrame, candidates: list, n: int = 4) -> Optional[float]:
    """Sum a row across the most recent n quarters to produce a TTM figure."""
    for name in candidates:
        if name in df.index:
            vals = [float(df.loc[name, c]) for c in df.columns[:n]
                    if pd.notna(df.loc[name, c])]
            if vals:
                return sum(vals)
    return None


def fetch_stock_data(ticker: str, delay: float = 0.5) -> StockData:
    """Fetch all required fundamental data for a ticker via yfinance."""
    sd = StockData(ticker=ticker)
    try:
        t = yf.Ticker(ticker)
        time.sleep(delay)

        info = t.info
        sd.name               = info.get("longName", ticker)
        sd.sector             = info.get("sector", "Unknown")
        sd.industry           = info.get("industry", "Unknown")
        sd.market_cap         = info.get("marketCap")
        sd.trailing_pe        = info.get("trailingPE")
        sd.forward_pe         = info.get("forwardPE")
        sd.trailing_eps       = info.get("trailingEps")
        sd.shares_outstanding = (info.get("sharesOutstanding")
                                  or info.get("impliedSharesOutstanding"))
        sd.debt_to_equity     = info.get("debtToEquity")
        sd.total_cash         = info.get("totalCash")
        sd.total_debt         = info.get("totalDebt")
        sd.free_cash_flow     = info.get("freeCashflow")
        sd.gross_margin       = info.get("grossMargins")
        sd.operating_margin   = info.get("operatingMargins")
        sd.net_margin         = info.get("profitMargins")
        sd.current_ratio      = info.get("currentRatio")

        # ── Income statement ──
        inc = None
        try:
            inc = t.income_stmt
        except AttributeError:
            try:
                inc = t.financials
            except Exception:
                pass

        if inc is not None and not inc.empty:
            try:
                sd.last_report_date = str(inc.columns[0].date())
            except Exception:
                pass
            sd.net_income_history = _extract_row(
                inc, ["Net Income", "Net Income Common Stockholders"])
            sd.ebit_history = _extract_row(
                inc, ["EBIT", "Operating Income"])
            raw_ie = _extract_row(inc, ["Interest Expense", "Net Interest Income"])
            sd.interest_expense_history = [abs(v) if v < 0 else v for v in raw_ie]

            # EPS from income statement (preferred over computed)
            eps_rows = _extract_row(inc, ["Diluted EPS", "Basic EPS"])
            if eps_rows:
                sd.eps_history = eps_rows

        # ── Cash flow statement ──
        try:
            cf = t.cashflow
            if cf is not None and not cf.empty:
                sd.da_history = _extract_row(
                    cf, ["Depreciation", "Depreciation And Amortization",
                         "Depreciation Amortization Depletion"])
                raw_cx = _extract_row(cf, ["Capital Expenditure", "Capital Expenditures"])
                sd.capex_history = [abs(v) if v < 0 else v for v in raw_cx]
        except Exception:
            pass

        # ── Owner earnings: NI + D&A − CapEx ──
        if sd.net_income_history and sd.da_history:
            if sd.capex_history:
                n = min(len(sd.net_income_history), len(sd.da_history), len(sd.capex_history))
                sd.owner_earnings_history = [
                    sd.net_income_history[i] + sd.da_history[i] - sd.capex_history[i]
                    for i in range(n)
                ]
            else:
                n = min(len(sd.net_income_history), len(sd.da_history))
                sd.owner_earnings_history = [
                    sd.net_income_history[i] + sd.da_history[i]
                    for i in range(n)
                ]

        # ── EPS fallback: compute from NI / shares ──
        if not sd.eps_history:
            if sd.net_income_history and sd.shares_outstanding:
                sd.eps_history = [ni / sd.shares_outstanding
                                   for ni in sd.net_income_history]
            elif sd.trailing_eps:
                sd.eps_history = [sd.trailing_eps]

        # ── Balance sheet: ROE, ROIC, long-term debt ──
        try:
            bs = t.balance_sheet
            if bs is not None and not bs.empty:
                eq_row = next(
                    (c for c in ["Stockholders Equity", "Total Stockholder Equity",
                                 "Common Stock Equity"] if c in bs.index), None)
                debt_row = next(
                    (c for c in ["Total Debt", "Long Term Debt",
                                 "Long Term Debt And Capital Lease Obligation"]
                     if c in bs.index), None)

                if debt_row:
                    ld = bs.loc[debt_row, bs.columns[0]]
                    if pd.notna(ld):
                        sd.long_term_debt = float(ld)

                if eq_row and sd.net_income_history:
                    roes = []
                    for i, col in enumerate(bs.columns):
                        if i < len(sd.net_income_history):
                            eq = bs.loc[eq_row, col]
                            ni = sd.net_income_history[i]
                            if pd.notna(eq) and eq > 0 and ni:
                                roes.append(ni / eq)
                    sd.roe_values = roes if roes else (
                        [info["returnOnEquity"]] if info.get("returnOnEquity") else [])

                if eq_row and sd.ebit_history:
                    # Estimate tax rate from income statement
                    tax_rate = 0.21
                    if inc is not None and not inc.empty:
                        tax_vals = _extract_row(inc, ["Tax Provision", "Income Tax Expense"])
                        pretax_vals = _extract_row(inc, ["Pretax Income", "Income Before Tax"])
                        if tax_vals and pretax_vals and pretax_vals[0] and pretax_vals[0] > 0:
                            tax_rate = max(0.10, min(0.40, tax_vals[0] / pretax_vals[0]))

                    roics = []
                    for i, col in enumerate(bs.columns):
                        if i < len(sd.ebit_history):
                            eq = bs.loc[eq_row, col] if pd.notna(bs.loc[eq_row, col]) else None
                            debt = (bs.loc[debt_row, col]
                                    if debt_row and pd.notna(bs.loc[debt_row, col]) else 0)
                            ebit = sd.ebit_history[i]
                            if eq and eq > 0 and ebit:
                                nopat = ebit * (1 - tax_rate)
                                ic = eq + (debt or 0)
                                if ic > 0:
                                    roics.append(nopat / ic)
                    sd.roic_values = roics

        except Exception:
            pass

        # Final fallback for ROE
        if not sd.roe_values and info.get("returnOnEquity"):
            sd.roe_values = [info["returnOnEquity"]]

        # ── Quarterly TTM: refresh current-state metrics ─────────────────
        # Annual data drives multi-year trend scoring (EPS consistency, ROE/ROIC history,
        # capital allocation CAGR).  Quarterly TTM drives current-state metrics:
        # interest coverage (EBIT/IE), owner earnings base for DCF, and report date.
        try:
            q_inc = t.quarterly_income_stmt
            q_cf  = t.quarterly_cashflow
            q_bs  = t.quarterly_balance_sheet

            ttm_ni = None  # shared between q_inc and q_cf blocks

            if q_inc is not None and not q_inc.empty and len(q_inc.columns) >= 4:
                # Most recent quarterly filing date (more timely than annual)
                try:
                    sd.last_report_date = str(q_inc.columns[0].date())
                except Exception:
                    pass

                ttm_ni   = _ttm_row(q_inc, ["Net Income",
                                             "Net Income Common Stockholders"])
                ttm_ebit = _ttm_row(q_inc, ["EBIT", "Operating Income"])
                ttm_ie   = _ttm_row(q_inc, ["Interest Expense",
                                             "Net Interest Income"])

                # Prepend TTM values so scoring functions use the most current figures
                if ttm_ebit is not None:
                    sd.ebit_history = [ttm_ebit] + (sd.ebit_history or [])
                if ttm_ie is not None:
                    sd.interest_expense_history = (
                        [abs(ttm_ie) if ttm_ie < 0 else ttm_ie]
                        + (sd.interest_expense_history or [])
                    )

            if q_cf is not None and not q_cf.empty and len(q_cf.columns) >= 4:
                ttm_da    = _ttm_row(q_cf, ["Depreciation",
                                             "Depreciation And Amortization",
                                             "Depreciation Amortization Depletion"])
                ttm_capex = _ttm_row(q_cf, ["Capital Expenditure",
                                             "Capital Expenditures"])

                if ttm_ni is not None and ttm_da is not None:
                    capex_abs = abs(ttm_capex) if ttm_capex and ttm_capex < 0 else (ttm_capex or 0)
                    ttm_oe = ttm_ni + ttm_da - capex_abs
                    sd.owner_earnings_history = [ttm_oe] + (sd.owner_earnings_history or [])

            if q_bs is not None and not q_bs.empty:
                ld_row = next(
                    (c for c in ["Long Term Debt",
                                 "Long Term Debt And Capital Lease Obligation"]
                     if c in q_bs.index), None)
                if ld_row:
                    ld_val = q_bs.loc[ld_row, q_bs.columns[0]]
                    if pd.notna(ld_val):
                        sd.long_term_debt = float(ld_val)

        except Exception:
            pass

    except Exception as e:
        sd.error = str(e)[:80]

    return sd


_RATE_LIMIT_PHRASES = ("too many requests", "rate limit", "429", "ratelimit")


def _is_rate_limited(error: str) -> bool:
    low = error.lower()
    return any(p in low for p in _RATE_LIMIT_PHRASES)


def fetch_with_cache(ticker: str, cache_dir: Optional[str],
                     delay: float, retries: int = 4) -> StockData:
    if cache_dir:
        cached = _load_cache(ticker, cache_dir)
        if cached is not None:
            return cached

    backoff = 20.0
    sd = StockData(ticker=ticker)
    for attempt in range(retries):
        sd = fetch_stock_data(ticker, delay=delay)
        if not sd.error:
            break
        if _is_rate_limited(sd.error) and attempt < retries - 1:
            time.sleep(backoff)
            backoff *= 2
            continue
        break  # non-rate-limit error or final attempt

    if cache_dir and not sd.error:
        _save_cache(sd, cache_dir)
    return sd


# ──────────────────────────────────────────────
# SCREENER ENGINE
# ──────────────────────────────────────────────

def compute_score(sd: StockData) -> dict:
    """Run all scoring functions and return a results dict."""
    if sd.market_cap:
        mkt_flag = (f"${sd.market_cap/1e9:.2f}B" if sd.market_cap >= 1_000_000_000
                    else f"${sd.market_cap/1e6:.0f}M")
    else:
        mkt_flag = "Unknown"

    ni_valid = [x for x in sd.net_income_history if x and x > 0]
    avg_ni = float(np.mean(ni_valid)) if ni_valid else None
    ebit = sd.ebit_history[0] if sd.ebit_history else None
    interest_exp = sd.interest_expense_history[0] if sd.interest_expense_history else None

    s1, d1 = score_eps_consistency(sd.net_income_history, sd.eps_history)
    s2, d2 = score_return_on_equity(sd.roe_values)
    s3, d3 = score_roic(sd.roic_values)
    s4, d4 = score_profit_margins(sd.gross_margin, sd.net_margin)
    s5, d5 = score_debt_liquidity(
        sd.debt_to_equity, sd.long_term_debt, avg_ni,
        sd.current_ratio, interest_exp, ebit,
        sd.total_cash, sd.total_debt,
    )
    s6, d6 = score_owner_earnings_yield(
        sd.owner_earnings_history, sd.market_cap,
        sd.trailing_pe, sd.forward_pe,
    )
    s7, d7 = score_capital_allocation(sd.net_income_history, sd.eps_history)

    w = WEIGHTS
    total = (
        s1 * w["eps_consistency"] +
        s2 * w["return_on_equity"] +
        s3 * w["roic"] +
        s4 * w["profit_margins"] +
        s5 * w["debt_liquidity"] +
        s6 * w["owner_earnings_yield"] +
        s7 * w["capital_allocation"]
    )

    return {
        "Ticker":                    sd.ticker,
        "Name":                      sd.name[:28],
        "Sector":                    sd.sector[:20],
        "Mkt Cap":                   mkt_flag,
        "Total Score":               round(total, 1),
        "EPS Consistency (20)":      f"{s1*20:.0f} — {d1}",
        "ROE (15)":                  f"{s2*15:.0f} — {d2}",
        "ROIC (15)":                 f"{s3*15:.0f} — {d3}",
        "Margins (10)":              f"{s4*10:.0f} — {d4}",
        "Debt & Liquidity (15)":     f"{s5*15:.0f} — {d5}",
        "Owner Earnings Yield (15)": f"{s6*15:.0f} — {d6}",
        "Capital Allocation (10)":   f"{s7*10:.0f} — {d7}",
        "Error":                     sd.error,
    }


# ──────────────────────────────────────────────
# MARGIN OF SAFETY — OWNER EARNINGS DCF
# ──────────────────────────────────────────────

def _owner_earnings_dcf(oe_per_share: float,
                         growth_rate: float,
                         discount_rate: float = 0.09,
                         terminal_growth: float = 0.03,
                         years: int = 10) -> float:
    """
    10-year DCF of owner earnings per share.
    Growth capped at 15% (conservative). Terminal value via Gordon Growth Model.
    Discount rate 9% ≈ long-run equity return expectation.
    """
    g = min(max(growth_rate, 0.0), 0.15)
    pv = sum(
        oe_per_share * (1 + g) ** yr / (1 + discount_rate) ** yr
        for yr in range(1, years + 1)
    )
    terminal_oe = oe_per_share * (1 + g) ** years * (1 + terminal_growth)
    if discount_rate > terminal_growth:
        pv += (terminal_oe / (discount_rate - terminal_growth)) / (1 + discount_rate) ** years
    return pv


def margin_of_safety(sd: StockData) -> dict:
    """
    Intrinsic value via owner earnings DCF (bull + bear scenarios).
    MOS entry = 30% discount to bull-case intrinsic value.
    """
    empty = {
        "Price": None, "OE/Share": None,
        "Intrinsic Low": None, "Intrinsic High": None,
        "MOS Entry": None, "MOS Status": "No data",
    }

    try:
        price = float(yf.Ticker(sd.ticker).history(period="1d")["Close"].iloc[-1])
    except Exception:
        return {**empty, "MOS Status": "Price unavailable"}
    empty["Price"] = round(price, 2)

    # Owner earnings per share
    valid_oe = [x for x in sd.owner_earnings_history
                if x is not None and not np.isnan(x)] if sd.owner_earnings_history else []

    if valid_oe and sd.shares_outstanding and sd.shares_outstanding > 0:
        oe_ps = np.mean(valid_oe) / sd.shares_outstanding
    elif sd.trailing_eps:
        oe_ps = sd.trailing_eps
    else:
        return {**empty, "MOS Status": "No earnings data"}

    if not oe_ps or oe_ps <= 0:
        return {**empty, "MOS Status": "Negative owner earnings"}
    empty["OE/Share"] = round(float(oe_ps), 2)

    # Historical growth rate — prefer OE series, fall back to NI
    growth_rate = 0.05
    for series in [sd.owner_earnings_history, sd.net_income_history]:
        vals = [x for x in series if x and x > 0] if series else []
        if len(vals) >= 2:
            n = len(vals) - 1
            growth_rate = (vals[0] / vals[-1]) ** (1 / n) - 1
            break

    bull_g = min(max(growth_rate, 0.0), 0.15)
    # Bear: 60% of bull when growth is meaningful; flat/slight decline when near zero
    bear_g = bull_g * 0.60 if bull_g > 0.01 else max(bull_g - 0.02, -0.02)

    intrinsic_high = _owner_earnings_dcf(oe_ps, bull_g)
    intrinsic_low  = _owner_earnings_dcf(oe_ps, bear_g)
    mos_entry      = intrinsic_high * 0.70  # 30% discount to bull IV

    if price <= mos_entry:
        status = "IN MOS ZONE"
    elif price <= intrinsic_low:
        status = "APPROACHING MOS"
    else:
        status = "ABOVE INTRINSIC VALUE"

    return {
        "Price":          round(price, 2),
        "OE/Share":       round(float(oe_ps), 2),
        "Intrinsic Low":  round(intrinsic_low, 2),
        "Intrinsic High": round(intrinsic_high, 2),
        "MOS Entry":      round(mos_entry, 2),
        "MOS Status":     status,
    }


def margin_of_safety_summary(sd: StockData) -> str:
    m = margin_of_safety(sd)
    if m["Price"] is None:
        return m["MOS Status"]
    if m["OE/Share"] is None:
        return f"Price: ${m['Price']} | {m['MOS Status']}"
    return (
        f"Price: ${m['Price']} | OE/Sh: ${m['OE/Share']} | "
        f"IV: ${m['Intrinsic Low']}-${m['Intrinsic High']} | "
        f"MOS entry: ${m['MOS Entry']} | {m['MOS Status']}"
    )


# ──────────────────────────────────────────────
# SINGLE-TICKER ANALYSIS
# ──────────────────────────────────────────────

def analyze_ticker(ticker: str, cache_dir: Optional[str] = None) -> None:
    """Fetch, score, and print a detailed Buffett-style analysis for one ticker."""
    ticker = ticker.upper().strip()
    print(f"\n{'='*65}")
    print(f"  BUFFETT-STYLE ANALYSIS: {ticker}")
    print(f"{'='*65}")
    print("  Fetching data...", flush=True)

    sd = fetch_with_cache(ticker, cache_dir, delay=0.5)

    if sd.error:
        print(f"\n  ERROR fetching {ticker}: {sd.error}\n")
        return

    r = compute_score(sd)

    print(f"\n  {r['Name']}")
    print(f"  Sector: {r['Sector']}  |  Market Cap: {r['Mkt Cap']}")
    print(f"\n  TOTAL SCORE: {r['Total Score']:.1f} / 100")
    print(f"{'─'*65}")

    criteria = [
        ("EPS Consistency",    "EPS Consistency (20)",      20),
        ("Return on Equity",   "ROE (15)",                  15),
        ("ROIC",               "ROIC (15)",                 15),
        ("Profit Margins",     "Margins (10)",              10),
        ("Debt & Liquidity",   "Debt & Liquidity (15)",     15),
        ("Owner Earnings Yld", "Owner Earnings Yield (15)", 15),
        ("Capital Allocation", "Capital Allocation (10)",   10),
    ]

    for label, key, weight in criteria:
        raw = r[key]          # e.g. "17 — Avg ROE 22.4%"
        pts, _, detail = raw.partition(" — ")
        bar_filled = int(float(pts) / weight * 20)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        print(f"  {label:<22} {pts:>3}/{weight:<3}  [{bar}]  {detail}")

    # ── MOS / DCF ──
    print(f"\n{'─'*65}")
    print("  MARGIN OF SAFETY  (Owner Earnings DCF @ 9% discount, 3% terminal)")
    print(f"{'─'*65}")
    m = margin_of_safety(sd)
    if m["Price"] is None:
        print(f"  {m['MOS Status']}")
    elif m["OE/Share"] is None:
        print(f"  Price: ${m['Price']}  |  {m['MOS Status']}")
    else:
        status_icon = {
            "IN MOS ZONE":           "✓ BUY ZONE",
            "APPROACHING MOS":       "~ APPROACHING",
            "ABOVE INTRINSIC VALUE": "✗ OVERVALUED",
        }.get(m["MOS Status"], m["MOS Status"])
        print(f"  Current price:     ${m['Price']}")
        print(f"  Owner earnings/sh: ${m['OE/Share']}")
        print(f"  Intrinsic value:   ${m['Intrinsic Low']} – ${m['Intrinsic High']}")
        print(f"  MOS entry (−30%):  ${m['MOS Entry']}")
        print(f"  Status:            {status_icon}")

    print(f"{'='*65}\n")


# ──────────────────────────────────────────────
# MAIN SCREENER
# ──────────────────────────────────────────────

def run_screener(tickers: list[str], show_mos: bool = True,
                 max_market_cap: float = 1_500_000_000,
                 min_score: float = 0,
                 workers: int = 5,
                 cache_dir: Optional[str] = None,
                 output: str = "buffett_scores.csv") -> pd.DataFrame:

    delay = max(0.2, 1.0 / workers)

    print(f"\n{'='*70}")
    print("  BUFFETT-STYLE SCREENER  (Owner Earnings Method)")
    print(f"  Universe: {len(tickers)} tickers | Max mkt cap: ${max_market_cap/1e9:.1f}B")
    print(f"  Workers: {workers} | Cache: {cache_dir or 'disabled'}")
    print(f"{'='*70}\n")

    results = []
    errors = skipped = completed = 0
    total = len(tickers)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_with_cache, t, cache_dir, delay): t
                   for t in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            completed += 1
            try:
                sd = future.result()
            except Exception as e:
                errors += 1
                print(f"  [{completed}/{total}] {ticker}: exception — {e}")
                continue

            if sd.error:
                errors += 1
                print(f"  [{completed}/{total}] {ticker}: ERROR — {sd.error}")
                continue

            if sd.market_cap and sd.market_cap > max_market_cap * 2:
                skipped += 1
                print(f"  [{completed}/{total}] {ticker}: skipped "
                      f"(${sd.market_cap/1e9:.1f}B cap)")
                continue

            score_dict = compute_score(sd)
            score_dict["_sd"] = sd
            results.append(score_dict)
            print(f"  [{completed}/{total}] {ticker}: {score_dict['Total Score']:.1f}")

    if not results:
        print("No results. Check ticker symbols and internet connection.")
        return pd.DataFrame()

    results = [r for r in results if r["Total Score"] >= min_score]
    results.sort(key=lambda x: x["Total Score"], reverse=True)

    # ── Ranked summary table ──
    print(f"\n{'='*70}")
    print(f"  RANKED RESULTS  (errors: {errors}, skipped: {skipped})")
    print(f"{'='*70}")
    print(f"\n{'Rank':<5} {'Ticker':<8} {'Score':>6}  {'Name':<28}  {'Mkt Cap':<18}  {'Sector'}")
    print("-" * 95)
    for rank, r in enumerate(results, 1):
        mkt = r["Mkt Cap"]
        flag = " [!]" if "above threshold" in mkt else ""
        print(f"  {rank:<4} {r['Ticker']:<8} {r['Total Score']:>5.1f}  "
              f"{r['Name']:<28}  {mkt:<18}  {r['Sector']}{flag}")

    # ── MOS for all results ──
    if show_mos:
        print(f"\n  Computing MOS (DCF) for {len(results)} stocks...", flush=True)
        for r in results:
            r["_mos"] = margin_of_safety(r["_sd"])

    # ── Detailed breakdown for top 5 ──
    print(f"\n{'='*70}")
    print("  DETAILED BREAKDOWN — TOP 5")
    print(f"{'='*70}")
    for r in results[:5]:
        print(f"\n  -- {r['Ticker']} | {r['Name']} | Score: {r['Total Score']:.1f}/100 --")
        for criterion in [
            "EPS Consistency (20)", "ROE (15)", "ROIC (15)", "Margins (10)",
            "Debt & Liquidity (15)", "Owner Earnings Yield (15)", "Capital Allocation (10)",
        ]:
            print(f"     {criterion}: {r[criterion]}")
        if show_mos:
            print(f"     MOS Analysis: {margin_of_safety_summary(r['_sd'])}")

    # ── Save to CSV ──
    score_cols = [
        "Ticker", "Name", "Sector", "Mkt Cap", "Total Score",
        "EPS Consistency (20)", "ROE (15)", "ROIC (15)", "Margins (10)",
        "Debt & Liquidity (15)", "Owner Earnings Yield (15)", "Capital Allocation (10)",
    ]
    mos_cols = ["Price", "OE/Share", "Intrinsic Low", "Intrinsic High",
                "MOS Entry", "MOS Status"]

    rows = []
    for r in results:
        row = {k: r[k] for k in score_cols}
        if show_mos:
            m = r.get("_mos", {})
            for col in mos_cols:
                row[col] = m.get(col)
        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv(output, index=False, encoding="utf-8-sig")
    print(f"\n  Results saved to: {output}  ({len(df)} stocks)")
    print(f"{'='*70}\n")
    return df


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Buffett-style screener — owner earnings methodology"
    )
    universe_group = parser.add_mutually_exclusive_group()
    universe_group.add_argument(
        "--ticker",
        help="Single ticker to analyse in detail (no CSV output)."
    )
    universe_group.add_argument(
        "--universe", choices=list(UNIVERSE_URLS),
        help="Auto-download ticker universe from iShares ETF holdings. "
             "Choices: sp600 (~600 stocks), russell2000 (~2000 stocks)."
    )
    universe_group.add_argument(
        "--tickers", nargs="+",
        help="Space-separated list of tickers to screen."
    )
    parser.add_argument(
        "--max-cap", type=float, default=1_500_000_000,
        help="Maximum market cap filter in dollars (default: 1.5B)"
    )
    parser.add_argument(
        "--min-score", type=float, default=0,
        help="Minimum score to include in output (default: 0 = show all)"
    )
    parser.add_argument(
        "--workers", type=int, default=5,
        help="Parallel fetch workers (default: 5). "
             "Higher = faster but more likely to be rate-limited."
    )
    parser.add_argument(
        "--cache-dir", default=".screener_cache",
        help="Directory for daily per-ticker cache (default: .screener_cache). "
             "Pass empty string to disable. Clear after upgrading screener."
    )
    parser.add_argument(
        "--no-mos", action="store_true",
        help="Skip margin of safety DCF calculations (faster)"
    )
    parser.add_argument(
        "--output",
        help="Output CSV filename. Defaults to buffett_scores_<universe>_<date>.csv"
    )
    args = parser.parse_args()

    if args.ticker:
        analyze_ticker(args.ticker, cache_dir=args.cache_dir or None)
        raise SystemExit(0)

    if args.universe:
        tickers = fetch_universe(args.universe)
    elif args.tickers:
        tickers = args.tickers
    else:
        tickers = DEFAULT_TICKERS

    if args.output:
        output_file = args.output
    else:
        label = args.universe or ("custom" if args.tickers else "default")
        output_file = f"buffett_scores_{label}_{date.today().isoformat()}.csv"

    run_screener(
        tickers=tickers,
        show_mos=not args.no_mos,
        max_market_cap=args.max_cap,
        min_score=args.min_score,
        workers=args.workers,
        cache_dir=args.cache_dir or None,
        output=output_file,
    )
