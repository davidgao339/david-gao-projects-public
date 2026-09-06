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

# Hardcoded fallback — verified against NASDAQ 100 index (update periodically)
_NASDAQ100_FALLBACK = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA", "AVGO", "COST",
    "NFLX", "AMD", "ADBE", "QCOM", "INTU", "CSCO", "PEP", "TMUS", "TXN", "AMAT",
    "HON", "AMGN", "SBUX", "BKNG", "ISRG", "VRTX", "ADP", "GILD", "MDLZ", "ADI",
    "REGN", "PANW", "LRCX", "MELI", "MU", "KLAC", "CDNS", "SNPS", "CRWD", "FTNT",
    "MRVL", "ABNB", "CSX", "KDP", "PCAR", "MAR", "ODFL", "WDAY", "DXCM", "CSGP",
    "DLTR", "BIIB", "FAST", "ROP", "ROST", "EA", "ORLY", "CTSH", "IDXX", "MNST",
    "GEHC", "AEP", "EXC", "FANG", "PAYX", "CEG", "TTD", "ZS", "TEAM", "CPRT",
    "KHC", "NXPI", "MCHP", "ON", "DDOG", "EBAY", "VRSK", "ALGN", "ANSS", "XEL",
    "CHTR", "CTAS", "WBD", "DASH", "RIVN", "ENPH", "GFS", "PDD", "ILMN", "SIRI",
    "OKTA", "ZM", "ASML", "NTES", "JD", "APP", "PLTR", "ARM", "MSTR", "PTON",
]

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


def fetch_nasdaq100() -> list[str]:
    """Fetch NASDAQ 100 constituents from Wikipedia. Falls back to hardcoded list."""
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/Nasdaq-100", match="Company")
        df = tables[0]
        col = next((c for c in df.columns if "ticker" in str(c).lower()
                    or "symbol" in str(c).lower()), None)
        if col is None:
            raise ValueError("Ticker column not found in Wikipedia table")
        tickers = df[col].dropna().astype(str).str.strip().tolist()
        tickers = [t for t in tickers if t and len(t) <= 5 and " " not in t and "." not in t]
        if len(tickers) < 90:
            raise ValueError(f"Only {len(tickers)} tickers found — table format may have changed")
        print(f"  Found {len(tickers)} NASDAQ 100 tickers from Wikipedia", flush=True)
        return tickers
    except Exception as e:
        print(f"  Wikipedia fetch failed ({e}) — using hardcoded fallback list", flush=True)
        return _NASDAQ100_FALLBACK


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


def score_revenue_consistency(revenue_history: list) -> tuple[float, str]:
    """
    Revenue growing consistently with no YoY declines.
    Weight: 55% consistency (no declines), 45% CAGR.
    Used in T2 of the 12-tenet scorecard; not part of the main 100-point score.
    """
    valid = [x for x in revenue_history if x and x > 0]
    if len(valid) < 2:
        return 0.3, "Insufficient revenue data"

    declines = sum(1 for i in range(len(valid) - 1) if valid[i] < valid[i + 1])
    total_pairs = len(valid) - 1
    consistency = max(0.0, 1.0 - declines / total_pairs * 1.5)

    n = len(valid) - 1
    cagr_pct = ((valid[0] / valid[-1]) ** (1 / n) - 1) * 100
    if cagr_pct >= 10:
        growth = 1.0
    elif cagr_pct >= 7:
        growth = 0.80
    elif cagr_pct >= 4:
        growth = 0.60
    elif cagr_pct >= 0:
        growth = 0.35
    else:
        growth = 0.10

    score = consistency * 0.55 + growth * 0.45
    decline_str = f"{declines}/{total_pairs} YoY decline{'s' if declines != 1 else ''}"
    return score, f"Rev CAGR {cagr_pct:.1f}% · {decline_str}"


def score_return_on_equity(roe_values: list,
                           debt_to_equity: Optional[float] = None) -> tuple[float, str]:
    """
    Avg ROE >20% over available ~4-year window, no single year below 15%.
    Consistency penalty reduces score proportionally to years below 15%.
    Leverage penalty applied when D/E > 2 — high ROE from debt is not a moat.
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

    if debt_to_equity is not None:
        de = debt_to_equity / 100 if debt_to_equity > 10 else debt_to_equity
        if de > 2:
            leverage_factor = max(0.4, 1 - (de - 2) * 0.12)
            score *= leverage_factor
            detail += f", leverage-adj (D/E {de:.1f}x)"

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


def _sector_calibration(sector: str, industry: str) -> tuple[list, list, str]:
    """
    Return (gm_tiers, nm_tiers, label) for the sector.
    Tiers: [(decimal_threshold, score_fraction), ...] in descending threshold order.
    IT resellers are structurally capped — Buffett's framework can't grade them on margins alone.
    """
    s = (sector or "").lower()
    i = (industry or "").lower()
    if "software" in i:
        return (
            [(0.75, 1.0), (0.60, 0.80), (0.45, 0.55), (0.30, 0.30), (0, 0.10)],
            [(0.25, 1.0), (0.18, 0.75), (0.10, 0.50), (0.05, 0.25), (0, 0.05)],
            "SaaS/Software",
        )
    if any(k in i for k in ("distribution", "wholesale", "electronics & computer")):
        # Structurally capped — full marks at much lower thresholds
        return (
            [(0.20, 0.80), (0.12, 0.60), (0.08, 0.40), (0.04, 0.20), (0, 0.05)],
            [(0.05, 0.80), (0.03, 0.55), (0.01, 0.30), (0, 0.10)],
            "IT Reseller (structural margin cap)",
        )
    if "retail" in i or "apparel" in i or "store" in i:
        return (
            [(0.45, 1.0), (0.35, 0.85), (0.25, 0.60), (0.15, 0.35), (0, 0.10)],
            [(0.10, 1.0), (0.08, 0.80), (0.05, 0.55), (0.02, 0.25), (0, 0.05)],
            "Specialty Retail",
        )
    if "financial" in s or "bank" in i or "insurance" in i:
        # Gross margin not meaningful for financials — score on net only
        return (
            [],
            [(0.20, 1.0), (0.15, 0.80), (0.10, 0.55), (0.05, 0.30), (0, 0.10)],
            "Financial Services",
        )
    return (
        [(0.60, 1.0), (0.40, 0.85), (0.25, 0.55), (0.15, 0.30), (0, 0.10)],
        [(0.20, 1.0), (0.15, 0.80), (0.10, 0.60), (0.05, 0.35), (0, 0.10)],
        "General",
    )


def _tier_score(value: float, tiers: list) -> float:
    for threshold, score in tiers:
        if value >= threshold:
            return score
    return 0.0


def score_profit_margins(gross_margin: Optional[float],
                          net_margin: Optional[float],
                          sector: str = "",
                          industry: str = "") -> tuple[float, str]:
    """
    Gross and net margin scoring with sector-calibrated benchmarks.
    SaaS software, specialty retail, IT resellers, and financials each get appropriate thresholds.
    """
    if gross_margin is None and net_margin is None:
        return 0.3, "No margin data"

    gm_tiers, nm_tiers, sector_label = _sector_calibration(sector, industry)

    scores = []
    parts = [f"[{sector_label}]"]

    if gross_margin is not None and gm_tiers:
        scores.append(_tier_score(gross_margin, gm_tiers))
        parts.append(f"GM {gross_margin*100:.0f}%")

    if net_margin is not None and nm_tiers:
        scores.append(_tier_score(net_margin, nm_tiers))
        parts.append(f"NM {net_margin*100:.0f}%")

    if not scores:
        return 0.3, f"[{sector_label}] No usable margin data"

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
      - Primary: EPS CAGR (shareholder-relevant; falls back to NI CAGR if unavailable)
      - Bonus: +0.15 if EPS grows faster than NI (buyback signal)
      - Penalty: -0.15 if NI grows much faster than EPS (dilution signal)
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
    dilution_penalty = 0.0
    eps_cagr = None

    if len(valid_eps) >= 2:
        n_eps = len(valid_eps) - 1
        eps_cagr = (valid_eps[0] / valid_eps[-1]) ** (1 / n_eps) - 1
        parts.append(f"EPS CAGR {eps_cagr*100:.1f}%")
        if (eps_cagr - ni_cagr) > 0.02:
            buyback_bonus = 0.15
            parts.append("buybacks detected")
        elif (ni_cagr - eps_cagr) > 0.05:
            dilution_penalty = 0.15
            parts.append("dilution detected")

    # EPS CAGR is the shareholder-relevant number; fall back to NI only if unavailable
    primary_cagr = eps_cagr if eps_cagr is not None else ni_cagr

    if primary_cagr >= 0.12:
        base = 1.0
    elif primary_cagr >= 0.08:
        base = 0.80
    elif primary_cagr >= 0.05:
        base = 0.60
    elif primary_cagr >= 0.02:
        base = 0.40
    elif primary_cagr >= 0:
        base = 0.25
    else:
        base = 0.10

    return min(1.0, max(0.0, base + buyback_bonus - dilution_penalty)), " | ".join(parts)


# ──────────────────────────────────────────────
# DATA STRUCTURES
# ──────────────────────────────────────────────

@dataclass
class StockData:
    ticker: str
    name: str = ""
    sector: str = ""
    industry: str = ""
    currency: str = "USD"           # trading currency (price / market cap)
    financial_currency: str = ""    # reporting currency of financial statements
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
    sbc_history: list = field(default_factory=list)
    change_in_wc_history: list = field(default_factory=list)
    cash_history: list = field(default_factory=list)
    owner_earnings_history: list = field(default_factory=list)
    smoothed_capex_history: list = field(default_factory=list)
    revenue_history: list = field(default_factory=list)
    operating_cash_flow_history: list = field(default_factory=list)
    retained_earnings_history: list = field(default_factory=list)
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


def _get_fx_rate(from_currency: str, to_currency: str) -> float:
    """Fetch spot FX rate via yfinance (e.g. CNY → USD). Returns 1.0 on failure."""
    if not from_currency or from_currency == to_currency:
        return 1.0
    try:
        symbol = f"{from_currency}{to_currency}=X"
        rate = yf.Ticker(symbol).info.get("regularMarketPrice")
        if rate and float(rate) > 0:
            return float(rate)
    except Exception:
        pass
    return 1.0


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
        sd.currency           = info.get("currency", "USD") or "USD"
        sd.financial_currency = info.get("financialCurrency", "") or ""
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
            sd.revenue_history = _extract_row(inc, ["Total Revenue"])
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
                sd.operating_cash_flow_history = _extract_row(
                    cf, ["Operating Cash Flow",
                         "Total Cash From Operating Activities"])
                sd.sbc_history = _extract_row(cf, ["Stock Based Compensation", "Share Based Compensation"])
                sd.change_in_wc_history = _extract_row(cf, ["Change In Working Capital", "Changes In Working Capital"])
        except Exception:
            pass

        # ── Owner earnings: NI + D&A + Change_in_WC − CapEx - SBC ──
        # CapEx Smoothing
        sd.smoothed_capex_history = []
        if sd.capex_history and sd.revenue_history:
            n_ratio = min(len(sd.capex_history), len(sd.revenue_history))
            if n_ratio > 0:
                capex_ratios = [sd.capex_history[i] / sd.revenue_history[i] for i in range(n_ratio) if sd.revenue_history[i] > 0]
                avg_capex_ratio = sum(capex_ratios) / len(capex_ratios) if capex_ratios else 0
                sd.smoothed_capex_history = [rev * avg_capex_ratio for rev in sd.revenue_history]
        elif sd.capex_history:
            sd.smoothed_capex_history = sd.capex_history

        if sd.operating_cash_flow_history:
            n = len(sd.operating_cash_flow_history)
            oe_hist = []
            for i in range(n):
                ocf = sd.operating_cash_flow_history[i]
                cx = sd.smoothed_capex_history[i] if i < len(sd.smoothed_capex_history) else 0
                sbc = sd.sbc_history[i] if i < len(sd.sbc_history) else 0
                
                oe = ocf - cx - sbc
                oe_hist.append(oe)
            sd.owner_earnings_history = oe_hist

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

                re_row = next(
                    (c for c in ["Retained Earnings"] if c in bs.index), None)
                if re_row:
                    sd.retained_earnings_history = [
                        float(bs.loc[re_row, col])
                        for col in bs.columns
                        if pd.notna(bs.loc[re_row, col])
                    ]

                cash_row = next((c for c in ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments", "Total Cash"] if c in bs.index), None)
                if cash_row:
                    sd.cash_history = [
                        float(bs.loc[cash_row, col])
                        for col in bs.columns
                        if pd.notna(bs.loc[cash_row, col])
                    ]

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
                                
                                cash = sd.cash_history[i] if i < len(sd.cash_history) else 0
                                rev = sd.revenue_history[i] if i < len(sd.revenue_history) else 0
                                operating_cash = 0.02 * rev
                                excess_cash = max(0, cash - operating_cash)
                                
                                ic = eq + (debt or 0) - excess_cash
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
                ttm_rev = _ttm_row(q_inc, ["Total Revenue"])
                if ttm_rev is not None:
                    sd.revenue_history = [ttm_rev] + (sd.revenue_history or [])
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
                ttm_sbc   = _ttm_row(q_cf, ["Stock Based Compensation", "Share Based Compensation"])
                ttm_wc    = _ttm_row(q_cf, ["Change In Working Capital", "Changes In Working Capital"])

                ttm_ocf = _ttm_row(q_cf, ["Operating Cash Flow",
                                           "Total Cash From Operating Activities"])
                
                if ttm_ocf is not None:
                    capex_abs = abs(ttm_capex) if ttm_capex and ttm_capex < 0 else (ttm_capex or 0)
                    sbc = ttm_sbc if ttm_sbc else 0
                    ttm_oe = ttm_ocf - capex_abs - sbc
                    
                    sd.owner_earnings_history = [ttm_oe] + (sd.owner_earnings_history or [])
                    sd.net_income_history = [ttm_ni] + (sd.net_income_history or []) if ttm_ni else sd.net_income_history
                    sd.da_history = [ttm_da] + (sd.da_history or []) if ttm_da else sd.da_history
                    sd.capex_history = [capex_abs] + (sd.capex_history or [])
                    sd.smoothed_capex_history = [capex_abs] + (sd.smoothed_capex_history or [])
                    sd.sbc_history = [sbc] + (sd.sbc_history or [])
                    sd.change_in_wc_history = [ttm_wc] + (sd.change_in_wc_history or []) if ttm_wc else sd.change_in_wc_history
                    sd.operating_cash_flow_history = [ttm_ocf] + (sd.operating_cash_flow_history or [])

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

        # ── FX conversion ────────────────────────────────────────────────────
        # Financial statements may be in a different currency than the trading price
        # (e.g. Chinese ADRs: income stmt in CNY, market cap / price in USD).
        # OE yield and DCF mix these — convert owner_earnings to the trading currency.
        # Ratios (ROE, ROIC, margins, LTD/NI, IC) are currency-neutral: no conversion needed.
        if sd.financial_currency and sd.financial_currency != sd.currency:
            fx = _get_fx_rate(sd.financial_currency, sd.currency)
            if fx != 1.0:
                sd.owner_earnings_history = [
                    x * fx if x is not None else None
                    for x in sd.owner_earnings_history
                ]

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
    """Run all scoring functions and return a results dict including 12-tenet map."""
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
    s2, d2 = score_return_on_equity(sd.roe_values, sd.debt_to_equity)
    s3, d3 = score_roic(sd.roic_values)
    s4, d4 = score_profit_margins(sd.gross_margin, sd.net_margin, sd.sector, sd.industry)
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
    s_rev, d_rev = score_revenue_consistency(sd.revenue_history)

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

    # ── EV / EBITDA ───────────────────────────────────────────────────────────
    ev_ebitda: Optional[float] = None
    da = sd.da_history[0] if sd.da_history else None
    if ebit is not None and da is not None and sd.market_cap:
        ebitda = ebit + da
        ev = sd.market_cap + (sd.total_debt or 0) - (sd.total_cash or 0)
        if ebitda > 0:
            ev_ebitda = round(ev / ebitda, 1)

    # ── FCF conversion: (OCF − CapEx) / Net Income ───────────────────────────
    fcf_conversion: Optional[float] = None
    if sd.operating_cash_flow_history and sd.net_income_history:
        ocf = sd.operating_cash_flow_history[0]
        ni  = sd.net_income_history[0]
        capex = sd.capex_history[0] if sd.capex_history else 0
        if ni and ni > 0 and ocf is not None:
            true_fcf = ocf - abs(capex)
            fcf_conversion = round(true_fcf / ni * 100, 1)

    # ── 12-tenet scorecard map (T10/T11/T12 filled by caller after MOS/T10 fetch) ──
    def _grade(s: float) -> str:
        return "Pass" if s >= 0.75 else "Partial" if s >= 0.40 else "Fail"

    oe_positive = any(x and x > 0 for x in (sd.owner_earnings_history or []))
    t8_detail = d6
    if fcf_conversion is not None:
        conv_flag = "✓" if fcf_conversion >= 80 else "⚠"
        t8_detail += f" · FCF conv {fcf_conversion:.0f}% {conv_flag}"
    t8_grade = _grade(s6) if oe_positive else "Fail"
    if t8_grade == "Pass" and fcf_conversion is not None and fcf_conversion < 80:
        t8_grade = "Partial"

    tenet_scores = {
        1:  ("Review",  "Qualitative — can you describe the business in 2 sentences without jargon?"),
        2:  (_grade((s1 + s_rev) / 2),
             f"EPS: {d1} · Revenue: {d_rev}"),
        3:  ("Review",  "Qualitative — assess industry tailwind AND company moat separately."),
        4:  (_grade(s7), d7),
        5:  ("Review",  "Qualitative — does MD&A name specific problems with numbers, or is it vague?"),
        6:  ("Review",  "Qualitative — concrete hard decision against short-term optics required."),
        7:  (_grade(s2), d2),
        8:  (t8_grade,  t8_detail),
        9:  (_grade(s4), d4),
        10: ("Deferred", "Computed separately — requires price history download."),
        11: ("Deferred", f"EV/EBITDA {ev_ebitda}× · forward P/E {sd.forward_pe} · see DCF below."),
        12: ("Deferred", "See margin of safety section above."),
    }

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
        "Revenue Consistency":       d_rev,
        "EV/EBITDA":                 ev_ebitda,
        "FCF Conversion":            fcf_conversion,
        "tenet_scores":              tenet_scores,
        "Error":                     sd.error,
    }


# ──────────────────────────────────────────────
# MARGIN OF SAFETY — OWNER EARNINGS DCF
# ──────────────────────────────────────────────

def _owner_earnings_dcf(oe_total: float,
                         growth_rate: float,
                         discount_rate: float = 0.09,
                         terminal_growth: float = 0.03,
                         years: int = 10,
                         verbose: bool = False,
                         label: str = "") -> tuple[float, list[dict]]:
    """
    10-year DCF of total owner earnings → Enterprise Value.
    Caller must subtract net debt and divide by shares to reach per-share equity value.
    Growth capped at 40% (hyper-growth). 3-Stage fading logic. Terminal value via Gordon Growth Model.
    Discount rate 9% ≈ long-run equity return expectation.
    """
    g = min(max(growth_rate, 0.0), 0.40)
    pv = 0
    current_oe = oe_total
    breakdown = []
    
    if verbose:
        print(f"\n  --- {label} DCF Breakdown ---")
        print(f"  Base OE: ${oe_total:,.2f}  |  Initial Growth Rate: {g*100:.1f}%")
        print(f"  {'Year':<6} | {'Growth Rate':<12} | {'Future OE':<16} | {'Present Value':<16}")
        print(f"  {'-'*62}")

    for yr in range(1, years + 1):
        if yr <= 3:
            current_g = g
        elif yr <= 6 and g > 0.15:
            # Stage 2: Gravity Phase (Years 4-6)
            fade_step = (0.15 - 0.10) / 2
            current_g = 0.15 - fade_step * (yr - 4)
        else:
            # Stage 3 or standard fade
            if g > 0.15:
                fade_step = (0.10 - terminal_growth) / 3
                current_g = 0.10 - fade_step * (yr - 7)
            else:
                fade_step = (g - terminal_growth) / (years - 3)
                current_g = g - fade_step * (yr - 3)
        current_oe *= (1 + current_g)
        yr_pv = current_oe / (1 + discount_rate) ** yr
        pv += yr_pv
        
        breakdown.append({
            "Year": str(yr),
            "Growth Rate": f"{current_g*100:.1f}%",
            "Future OE": current_oe,
            "Present Value": yr_pv
        })
        
        if verbose:
            print(f"  {yr:<6} | {current_g*100:>11.1f}% | ${current_oe:>14,.2f} | ${yr_pv:>14,.2f}")

    terminal_oe = current_oe * (1 + terminal_growth)
    terminal_pv = 0
    if discount_rate > terminal_growth:
        terminal_pv = (terminal_oe / (discount_rate - terminal_growth)) / (1 + discount_rate) ** years
        pv += terminal_pv

    breakdown.append({
        "Year": "Term.",
        "Growth Rate": f"{terminal_growth*100:.1f}%",
        "Future OE": terminal_oe,
        "Present Value": terminal_pv
    })

    if verbose:
        print(f"  {'-'*62}")
        print(f"  {'Term.':<6} | {terminal_growth*100:>11.1f}% | ${terminal_oe:>14,.2f} | ${terminal_pv:>14,.2f}")
        print(f"  Total Enterprise Value (PV): ${pv:,.2f}")

    return pv, breakdown


def margin_of_safety(sd: StockData, verbose: bool = False) -> dict:
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

    shares = sd.shares_outstanding if sd.shares_outstanding and sd.shares_outstanding > 0 else None

    # Total owner earnings (absolute $, not per-share) — used for enterprise-level DCF
    valid_oe = [x for x in sd.owner_earnings_history
                if x is not None and not np.isnan(x)] if sd.owner_earnings_history else []

    if valid_oe:
        oe_total = float(np.mean(valid_oe))
    elif sd.trailing_eps and shares:
        oe_total = sd.trailing_eps * shares
    else:
        return {**empty, "MOS Status": "No earnings data"}

    if oe_total <= 0:
        return {**empty, "MOS Status": "Negative owner earnings"}

    # Expose OE/share for display only
    oe_ps_display = oe_total / shares if shares else None
    if oe_ps_display:
        empty["OE/Share"] = round(oe_ps_display, 2)

    # Historical growth rate — prefer OE series, fall back to NI
    growth_rate = 0.05
    for series in [sd.owner_earnings_history, sd.net_income_history]:
        vals = [x for x in series if x and x > 0] if series else []
        if len(vals) >= 2:
            n = len(vals) - 1
            growth_rate = (vals[0] / vals[-1]) ** (1 / n) - 1
            break

    bull_g = min(max(growth_rate, 0.0), 0.40)
    # Bear: 60% of bull when growth is meaningful; flat/slight decline when near zero
    if bull_g > 0.20:
        bear_g = 0.12
    else:
        bear_g = bull_g * 0.60 if bull_g > 0.01 else max(bull_g - 0.02, -0.02)

    # DCF at enterprise level, then subtract net debt to get equity value.
    # This prevents over-leveraged companies from appearing cheap purely on cash-flow yield.
    net_debt = 0.0
    if sd.total_debt and sd.total_debt > 0:
        cash = sd.total_cash if sd.total_cash and sd.total_cash > 0 else 0.0
        net_debt = sd.total_debt - cash  # can be negative (net cash) — that's fine

    ev_high, breakdown_high = _owner_earnings_dcf(oe_total, bull_g, verbose=verbose, label="Bull Case")
    ev_low, breakdown_low  = _owner_earnings_dcf(oe_total, bear_g, verbose=verbose, label="Bear Case")

    equity_high = max(ev_high - net_debt, 0.0)
    equity_low  = max(ev_low  - net_debt, 0.0)
    
    if verbose:
        print(f"\n  --- Enterprise to Equity Bridge ---")
        print(f"  Net Debt (Total Debt - Excess Cash): ${net_debt:,.2f}")
        print(f"  Total Shares Outstanding:            {shares:,.0f}")
        print(f"  Bull Case Equity Value:              ${equity_high:,.2f}  (Per Share: ${equity_high/shares:,.2f})")
        print(f"  Bear Case Equity Value:              ${equity_low:,.2f}  (Per Share: ${equity_low/shares:,.2f})")
        print(f"  {'-'*62}\n")

    if not shares:
        return {**empty, "MOS Status": "Shares data unavailable"}

    intrinsic_high = equity_high / shares
    intrinsic_low  = equity_low  / shares
    mos_entry      = intrinsic_high * 0.70  # 30% discount to bull IV

    if intrinsic_high <= 0:
        return {
            "Price":          round(price, 2),
            "OE/Share":       round(oe_ps_display, 2) if oe_ps_display else None,
            "Intrinsic Low":  0.0,
            "Intrinsic High": 0.0,
            "MOS Entry":      0.0,
            "MOS Status":     "DEBT EXCEEDS ENTERPRISE VALUE",
            "Bull Breakdown": breakdown_high,
            "Bear Breakdown": breakdown_low,
            "Base OE": oe_total,
            "Net Debt": net_debt,
            "Shares": shares
        }

    if price <= mos_entry:
        status = "IN MOS ZONE"
    elif price <= intrinsic_low:
        status = "APPROACHING MOS"
    else:
        status = "ABOVE INTRINSIC VALUE"

    return {
        "Price":          round(price, 2),
        "OE/Share":       round(oe_ps_display, 2) if oe_ps_display else None,
        "Intrinsic Low":  round(intrinsic_low, 2),
        "Intrinsic High": round(intrinsic_high, 2),
        "MOS Entry":      round(mos_entry, 2),
        "MOS Status":     status,
        "Bull Breakdown": breakdown_high,
        "Bear Breakdown": breakdown_low,
        "Base OE": oe_total,
        "Net Debt": net_debt,
        "Shares": shares
    }


def margin_of_safety_summary(sd: StockData) -> str:
    m = margin_of_safety(sd)
    if m["Price"] is None:
        return m["MOS Status"]
    if m["OE/Share"] is None:
        return f"Price: ${m['Price']} | {m['MOS Status']}"
    iv_l_pct = f"{((m['Intrinsic Low'] - m['Price']) / m['Price'] * 100):+.1f}%" if m.get('Intrinsic Low') and m.get('Price') else "N/A"
    iv_h_pct = f"{((m['Intrinsic High'] - m['Price']) / m['Price'] * 100):+.1f}%" if m.get('Intrinsic High') and m.get('Price') else "N/A"
    return (
        f"Price: ${m['Price']} | OE/Sh: ${m['OE/Share']} | "
        f"IV: ${m['Intrinsic Low']} ({iv_l_pct}) - ${m['Intrinsic High']} ({iv_h_pct}) | "
        f"MOS entry: ${m['MOS Entry']} | {m['MOS Status']}"
    )


def compute_tenet10(sd: StockData) -> dict:
    """
    Tenet 10: $1 of retained earnings → $1+ of market value created.
    Compares cumulative retained earnings per share against stock CAGR vs S&P 500
    over the available balance sheet window (typically 3–4 years).
    Requires yfinance price history — adds ~1s latency per call.
    """
    result: dict = {
        "grade": "Insufficient data",
        "period": None,
        "re_delta_ps": None,
        "stock_cagr": None,
        "sp500_cagr": None,
        "evidence": "Need ≥2 years of retained earnings on the balance sheet.",
    }

    re_vals = [x for x in (sd.retained_earnings_history or []) if x is not None]
    if len(re_vals) < 2 or not sd.shares_outstanding or sd.shares_outstanding <= 0:
        return result

    n = len(re_vals) - 1          # years in window (most-recent-first)
    re_delta = re_vals[0] - re_vals[n]
    re_delta_ps = re_delta / sd.shares_outstanding
    result["re_delta_ps"] = round(re_delta_ps, 2)
    result["period"] = n

    try:
        period_str = f"{n + 1}y"
        hist = yf.download(sd.ticker, period=period_str,
                           auto_adjust=True, progress=False)
        if hist.empty or len(hist) < 20:
            result["evidence"] = (
                f"RE/sh Δ${re_delta_ps:+.2f} over {n}yr — price history unavailable.")
            return result

        price_start = float(hist["Close"].iloc[0])
        price_end   = float(hist["Close"].iloc[-1])
        stock_cagr  = (price_end / price_start) ** (1 / n) - 1
        result["stock_cagr"] = round(stock_cagr * 100, 1)

        sp_hist = yf.download("^GSPC", period=period_str,
                              auto_adjust=True, progress=False)
        sp500_cagr: Optional[float] = None
        if not sp_hist.empty and len(sp_hist) >= 20:
            sp_cagr = (float(sp_hist["Close"].iloc[-1]) /
                       float(sp_hist["Close"].iloc[0])) ** (1 / n) - 1
            sp500_cagr = round(sp_cagr * 100, 1)
            result["sp500_cagr"] = sp500_cagr

        beats_sp = sp500_cagr is None or stock_cagr * 100 >= sp500_cagr
        if re_delta_ps > 0 and beats_sp:
            result["grade"] = "Pass"
        elif re_delta_ps > 0 or stock_cagr > 0:
            result["grade"] = "Partial"
        else:
            result["grade"] = "Fail"

        sp_str = f" vs S&P {sp500_cagr:.1f}%" if sp500_cagr is not None else ""
        result["evidence"] = (
            f"RE/sh Δ${re_delta_ps:+.2f} over {n}yr · "
            f"stock CAGR {stock_cagr * 100:.1f}%{sp_str}"
        )

    except Exception as e:
        result["evidence"] = (
            f"RE/sh Δ${re_delta_ps:+.2f} over {n}yr — price fetch failed: {e}")

    return result


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
    m = margin_of_safety(sd, verbose=True)
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
                 max_market_cap: Optional[float] = None,
                 min_score: float = 0,
                 workers: int = 5,
                 cache_dir: Optional[str] = None,
                 output: str = "buffett_scores.csv") -> pd.DataFrame:

    delay = max(0.2, 1.0 / workers)

    cap_str = f"${max_market_cap/1e9:.1f}B" if max_market_cap else "none"
    print(f"\n{'='*70}")
    print("  BUFFETT-STYLE SCREENER  (Owner Earnings Method)")
    print(f"  Universe: {len(tickers)} tickers | Max mkt cap: {cap_str}")
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

            if max_market_cap and sd.market_cap and sd.market_cap > max_market_cap * 2:
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

    if show_mos and {"Price", "MOS Entry"}.issubset(df.columns):
        summary = (
            df[["Ticker", "Total Score", "Price", "MOS Entry"]]
            .rename(columns={"Total Score": "Score", "MOS Entry": "Entry Point"})
            .dropna(subset=["Price"])
            .sort_values("Score", ascending=False)
        )
        summary_output = output.replace(".csv", "_summary.csv")
        summary.to_csv(summary_output, index=False, encoding="utf-8-sig")
        print(f"  Summary saved to:  {summary_output}  (ticker · score · price · entry point)")

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
        "--universe", choices=[*UNIVERSE_URLS, "nasdaq100"],
        help="Universe to screen. nasdaq100: NASDAQ 100 (~100 large-caps, Wikipedia). "
             "sp600: ~600 small-caps (iShares). russell2000: ~2000 small-caps (iShares)."
    )
    universe_group.add_argument(
        "--tickers", nargs="+",
        help="Space-separated list of tickers to screen."
    )
    parser.add_argument(
        "--max-cap", type=float, default=None,
        help="Maximum market cap filter in dollars (default: no filter). "
             "Example: 1500000000 to restrict to small-caps ≤$1.5B."
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

    if args.universe == "nasdaq100":
        tickers = fetch_nasdaq100()
    elif args.universe:
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
