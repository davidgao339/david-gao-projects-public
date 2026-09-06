"""
Would Buffett Buy? — Single-ticker Streamlit app
Run: streamlit run app.py
"""

import numpy as np
import pandas as pd
import requests
import streamlit as st

from buffett_screener import (fetch_with_cache, compute_score, margin_of_safety,
                              compute_tenet10)

# ─────────────────────────────────────────────
# VERDICT
# ─────────────────────────────────────────────

def get_verdict(score: float, mos_status: str) -> tuple[str, str]:
    """Return (verdict label, colour key)."""
    if score >= 65 and mos_status == "IN MOS ZONE":
        return "BUFFETT WOULD BUY", "green"
    elif score >= 65:
        return "YES — BUT WAIT FOR A LOWER PRICE", "yellow"
    elif score >= 50:
        return "WORTH WATCHING", "blue"
    else:
        return "BUFFETT WOULD PASS", "red"


# ─────────────────────────────────────────────
# BUFFETT-STYLE EXPLANATION  (rule-based, no LLM)
# ─────────────────────────────────────────────

def build_explanation(sd, r: dict, m: dict, verdict: str) -> list[tuple[str, str]]:
    """Return list of (text, sentiment) tuples. sentiment: 'positive'|'negative'|'neutral'."""
    name  = sd.name or sd.ticker
    score = r["Total Score"]
    parts: list[tuple[str, str]] = []

    # ── Opening ──────────────────────────────
    if "BUY" in verdict:
        parts.append((
            f"**{name}** is the kind of business Charlie and I have spent decades searching for. "
            "It earns exceptional returns on the capital it employs, carries a balance sheet we can sleep with, "
            "and — crucially — the market is currently offering it at a price that gives us a real margin of safety. "
            "A wonderful company at a fair price will always beat a fair company at a wonderful price.",
            "positive"
        ))
    elif "LOWER" in verdict:
        parts.append((
            f"**{name}** has the business characteristics we admire. "
            "The economics are sound and management has demonstrated it knows how to allocate capital. "
            "Our hesitation is entirely about price. "
            "The market is asking us to pay a full — perhaps optimistic — valuation, "
            "and we have never found it necessary to stretch on price when patience costs us nothing. "
            "We would revisit this one when Mr. Market turns pessimistic.",
            "neutral"
        ))
    elif "WATCHING" in verdict:
        parts.append((
            f"**{name}** shows some of the qualities we admire, but not yet with the consistency "
            "or returns we require before committing significant capital. "
            "We keep a list of businesses we understand and like but aren't yet ready to own. "
            "This one belongs on that list.",
            "neutral"
        ))
    else:
        parts.append((
            f"We would pass on **{name}**. "
            "Investing is about saying no to nearly everything and reserving your best swing for the fat pitch. "
            "At Berkshire, we have passed on hundreds of businesses that looked interesting at first glance "
            "and have never regretted it. Discipline is the foundation.",
            "negative"
        ))

    # ── Moat / Margins ───────────────────────
    gm = (sd.gross_margin or 0) * 100
    nm = (sd.net_margin  or 0) * 100

    if gm >= 60:
        parts.append((
            f"The gross margin of {gm:.0f}% is exceptional. "
            "Businesses with margins like this can raise prices faster than their costs rise — "
            "that is the essence of a durable competitive moat. "
            "Commodity businesses, by contrast, are price-takers. This one is a price-setter.",
            "positive"
        ))
    elif gm >= 40:
        parts.append((
            f"A gross margin of {gm:.0f}% signals genuine pricing power. "
            "The company is not competing on price alone, which is exactly where we want to be. "
            "Customers who choose you for reasons other than price are customers you keep.",
            "positive"
        ))
    elif gm > 0:
        parts.append((
            f"The gross margin of {gm:.0f}% is thinner than we prefer. "
            "Businesses with narrow margins leave little room for error — a cost shock, "
            "a recession, or a determined competitor can erode profitability quickly. "
            "We require a wider cushion.",
            "negative"
        ))

    if nm >= 20:
        parts.append((
            f"Net margins of {nm:.0f}% confirm that the pricing power flows all the way to the bottom line. "
            "That is not a given — many businesses with decent gross margins lose it to bloated overhead or heavy reinvestment. "
            "Here, the earnings are real and the business earns what it appears to earn.",
            "positive"
        ))
    elif nm >= 10 and gm >= 40:
        parts.append((
            f"The net margin of {nm:.0f}% is respectable. "
            "There is room to improve if the business can scale without proportionally growing its cost base.",
            "neutral"
        ))

    # ── ROE ──────────────────────────────────
    valid_roe = [r_ for r_ in (sd.roe_values or []) if r_ and not np.isnan(r_)]
    if valid_roe:
        avg_roe = np.mean(valid_roe) * 100
        if avg_roe >= 20:
            parts.append((
                f"Return on equity averages {avg_roe:.1f}% — comfortably above our informal 20% threshold. "
                "A business that consistently earns high returns on equity is compounding its owners' "
                "wealth year after year, whether the stock moves or not. "
                "That is the engine Berkshire has ridden for sixty years.",
                "positive"
            ))
        elif avg_roe >= 12:
            parts.append((
                f"Return on equity at {avg_roe:.1f}% is acceptable but not exceptional. "
                "We'd want to understand whether management can push this higher, "
                "or whether the industry structure caps returns at this level permanently.",
                "neutral"
            ))
        else:
            parts.append((
                f"A return on equity of {avg_roe:.1f}% tells us the business requires large amounts of capital "
                "to produce modest returns. That is the opposite of what we look for. "
                "Great businesses generate cash; they do not consume it.",
                "negative"
            ))

    # ── ROE/ROIC divergence warning ──────────
    valid_roic_chk = [r_ for r_ in (sd.roic_values or []) if r_ and not np.isnan(r_)]
    if valid_roe and valid_roic_chk:
        chk_roe  = np.mean(valid_roe)  * 100
        chk_roic = np.mean(valid_roic_chk) * 100
        if chk_roe > 30 and chk_roic < 13:
            parts.append((
                f"One caution worth noting: the return on equity ({chk_roe:.0f}%) is far above "
                f"the return on invested capital ({chk_roic:.1f}%). When those two figures diverge "
                "significantly, it typically means debt — not business quality — is amplifying "
                "the reported equity returns. We have always preferred businesses that earn well "
                "on capital before leverage enters the picture. High ROE alone is not a moat.",
                "negative"
            ))

    # ── ROIC ─────────────────────────────────
    valid_roic = [r_ for r_ in (sd.roic_values or []) if r_ and not np.isnan(r_)]
    if valid_roic:
        avg_roic = np.mean(valid_roic) * 100
        if avg_roic >= 17:
            parts.append((
                f"Return on invested capital of {avg_roic:.1f}% — including all the debt on the balance sheet — "
                "confirms this is a business that genuinely earns well on every dollar deployed. "
                "ROIC is the metric we trust most when evaluating capital efficiency.",
                "positive"
            ))
        elif avg_roic < 10:
            parts.append((
                f"With ROIC at {avg_roic:.1f}%, the business struggles to earn meaningfully above its cost of capital. "
                "Growth in a business like this destroys value rather than creates it.",
                "negative"
            ))

    # ── Balance sheet ─────────────────────────
    debt_detail = r.get("Debt & Liquidity (15)", "")
    if "Net cash" in debt_detail:
        net_str = debt_detail.split("+$")[1].split("M")[0] if "+$" in debt_detail else ""
        cash_note = f" — ${net_str}M more cash than debt" if net_str else ""
        parts.append((
            f"The balance sheet is fortress-like{cash_note}. "
            "A company that owes nobody anything can act boldly when others cannot. "
            "Financial strength is not glamorous, but it has saved many businesses that leverage destroyed.",
            "positive"
        ))
    elif "D/E" in debt_detail:
        try:
            de = float(debt_detail.split("D/E")[1].split()[0].strip())
            if de <= 0.5:
                parts.append((
                    f"Debt-to-equity of {de:.2f} reflects conservative financial management. "
                    "We have never understood why managements willingly put businesses they love "
                    "at the mercy of bankers they barely know. This team hasn't made that mistake.",
                    "positive"
                ))
            elif de <= 1.5:
                parts.append((
                    f"The debt load — D/E of {de:.2f} — is manageable but worth watching. "
                    "Leverage amplifies returns in good times and pain in bad ones. "
                    "We'd want comfort that this debt is purposeful, not structural.",
                    "neutral"
                ))
            else:
                parts.append((
                    f"A debt-to-equity ratio of {de:.2f} is higher than we're comfortable with. "
                    "When trouble arrives — and it always does eventually — "
                    "leverage turns a survivable problem into an existential one.",
                    "negative"
                ))
        except ValueError:
            pass

    # ── Valuation / MOS ──────────────────────
    price    = m.get("Price")
    iv_low   = m.get("Intrinsic Low")
    iv_high  = m.get("Intrinsic High")
    mos_entry = m.get("MOS Entry")

    if price and iv_high:
        if m.get("MOS Status") == "IN MOS ZONE":
            parts.append((
                f"At ${price:.2f}, the stock trades below our intrinsic value estimate of "
                f"${iv_low:.2f}–${iv_high:.2f}, and well below our required entry price of ${mos_entry:.2f}. "
                "The margin of safety is not just a mathematical formula — it is the acknowledgement "
                "that we can be wrong, and that being wrong with a 30% cushion is very different "
                "from being wrong without one.",
                "positive"
            ))
        elif m.get("MOS Status") == "APPROACHING MOS":
            parts.append((
                f"At ${price:.2f}, the stock is approaching our buy threshold of ${mos_entry:.2f} "
                f"but has not crossed it. Our intrinsic value estimate sits at ${iv_low:.2f}–${iv_high:.2f}. "
                "We'd rather be approximately right than precisely wrong — "
                "and right now, the approximation says wait a little longer.",
                "neutral"
            ))
        else:
            parts.append((
                f"At ${price:.2f}, the market is asking us to pay above our intrinsic value range "
                f"of ${iv_low:.2f}–${iv_high:.2f}. Our required entry price is ${mos_entry:.2f}. "
                "Price is what you pay; value is what you get. "
                "Today, those two figures are too far apart for our comfort.",
                "negative"
            ))

    # ── Closing note ──────────────────────────
    parts.append((
        f"__NOTE__ This analysis scores {name} at {score:.0f}/100 across earnings consistency, "
        "capital returns, balance sheet strength, profit margins, and valuation. "
        "No formula substitutes for understanding the business itself — "
        "but the numbers tell us where to look.",
        "neutral"
    ))

    return parts


# ─────────────────────────────────────────────
# SCORE BREAKDOWN CONTEXT
# ─────────────────────────────────────────────

def build_score_context(sd, r: dict) -> dict:
    """Return plain-English threshold explanations for each scoring criterion."""
    ctx = {}

    # ── EPS Consistency ──
    data = sd.eps_history if sd.eps_history else sd.net_income_history
    if data:
        total     = len(data)
        profitable = sum(1 for x in data if x and x > 0)
        valid      = [x for x in data if x and x > 0]
        cons_note  = f"{profitable}/{total} years profitable"
        if len(valid) >= 2:
            n    = len(valid) - 1
            cagr = ((valid[0] / valid[-1]) ** (1 / n) - 1) * 100
            if cagr >= 10:
                g = f"CAGR {cagr:.1f}% — excellent (≥10% = full growth credit)"
            elif cagr >= 7:
                g = f"CAGR {cagr:.1f}% — good (≥10% for full marks)"
            elif cagr >= 4:
                g = f"CAGR {cagr:.1f}% — fair (≥10% for full marks)"
            elif cagr >= 0:
                g = f"CAGR {cagr:.1f}% — below target (≥10% for full marks)"
            else:
                g = f"CAGR {cagr:.1f}% — earnings declining, near-zero growth credit"
        else:
            g = "Insufficient history to compute CAGR"
        ctx["EPS Consistency"] = f"{cons_note}  ·  {g}"
    else:
        ctx["EPS Consistency"] = "No earnings data available"

    # ── Return on Equity ──
    valid_roe = [x for x in (sd.roe_values or []) if x is not None and not np.isnan(x)]
    if valid_roe:
        avg_roe     = np.mean(valid_roe) * 100
        below_15    = sum(1 for x in valid_roe if x * 100 < 15)
        roe_line    = f"Avg ROE {avg_roe:.1f}% ({'above' if avg_roe >= 20 else 'below'} 20% threshold)"
        if below_15:
            roe_line += f"  ·  {below_15}/{len(valid_roe)} years below 15% — consistency penalty"
        if sd.debt_to_equity is not None:
            de = sd.debt_to_equity / 100 if sd.debt_to_equity > 10 else sd.debt_to_equity
            if de > 2:
                factor = max(0.4, 1 - (de - 2) * 0.12)
                roe_line += (f"  ·  D/E {de:.1f}x exceeds 2× leverage limit — "
                             f"score reduced by {(1-factor)*100:.0f}% (debt inflates ROE)")
        ctx["Return on Equity"] = roe_line
    else:
        ctx["Return on Equity"] = "No ROE data available"

    # ── ROIC ──
    valid_roic = [x for x in (sd.roic_values or []) if x is not None and not np.isnan(x)]
    if valid_roic:
        avg = np.mean(valid_roic) * 100
        if avg >= 22:
            tier = "excellent (≥22% = full marks)"
        elif avg >= 17:
            tier = "good (≥17% threshold met)"
        elif avg >= 13:
            tier = "fair — below 17% target"
        elif avg >= 9:
            tier = "weak — target ≥17%"
        else:
            tier = "very low — target ≥17%"
        ctx["ROIC"] = (f"Avg ROIC {avg:.1f}% — {tier}  ·  "
                       "measures returns on all capital including debt (thresholds: ≥22% full, ≥17% good, ≥13% fair, ≥9% weak)")
    else:
        ctx["ROIC"] = "ROIC data unavailable — no partial credit awarded"

    # ── Revenue Consistency ──
    rev_note = r.get("Revenue Consistency", "")
    ctx["Revenue Consistency"] = rev_note if rev_note else "No revenue data"

    # ── Profit Margins (sector-calibrated) ──
    margin_detail = r.get("Margins (10)", "")
    # The detail string already includes sector label from _sector_calibration
    gm = (sd.gross_margin or 0) * 100
    nm = (sd.net_margin  or 0) * 100
    ctx["Profit Margins"] = (
        f"Gross {gm:.0f}%  ·  Net {nm:.0f}%  ·  "
        f"benchmarks are sector-calibrated — see score detail above"
    )

    # ── Debt & Liquidity ──
    parts = []
    if sd.debt_to_equity is not None:
        de = sd.debt_to_equity / 100 if sd.debt_to_equity > 10 else sd.debt_to_equity
        parts.append(f"D/E {de:.1f}× ({'≤0.5 target' if de <= 0.5 else '≤1× ok' if de <= 1 else '≤2× elevated' if de <= 2 else 'above 2× — fails'})")
    if sd.long_term_debt is not None:
        ni_pos = [x for x in (sd.net_income_history or []) if x and x > 0]
        if ni_pos:
            lt = sd.long_term_debt / np.mean(ni_pos)
            parts.append(f"LT debt {lt:.1f}× NI ({'≤2× excellent' if lt <= 2 else '≤5× acceptable' if lt <= 5 else '≤8× elevated' if lt <= 8 else 'above 8× — fails'})")
    if sd.current_ratio is not None:
        cr = sd.current_ratio
        parts.append(f"Current ratio {cr:.1f} ({'≥2.0 strong' if cr >= 2 else '≥1.5 target' if cr >= 1.5 else '≥1.0 marginal' if cr >= 1 else 'below 1.0 — short-term risk'})")
    ebit = sd.ebit_history[0] if sd.ebit_history else None
    ie   = sd.interest_expense_history[0] if sd.interest_expense_history else None
    if ebit and ie and ie > 0:
        ic = ebit / ie
        parts.append(f"Interest coverage {ic:.1f}× ({'≥10× excellent' if ic >= 10 else '≥8× target' if ic >= 8 else '≥5× marginal' if ic >= 5 else 'below 5× — risk'})")
    ctx["Debt & Liquidity"] = ("  ·  ".join(parts) + "  ·  score = average of all sub-checks"
                                if parts else "Insufficient data")

    # ── Owner Earnings Yield ──
    valid_oe = [x for x in (sd.owner_earnings_history or []) if x is not None and not np.isnan(x)]
    if valid_oe and sd.market_cap:
        yld = np.mean(valid_oe) / sd.market_cap * 100
        tier = ("≥9% = full marks" if yld >= 9
                else "≥7% good" if yld >= 7
                else "≥5% fair" if yld >= 5
                else "≥3% weak" if yld >= 3
                else "below 3% — very low")
        ctx["Owner Earnings Yld"] = (f"OE yield {yld:.1f}% — {tier}  ·  "
                                     "owner earnings = Net Income + D&A − CapEx ÷ market cap  ·  thresholds: ≥9% full, ≥7% good, ≥5% fair")
    elif sd.trailing_pe:
        yld = (1 / sd.trailing_pe) * 100
        ctx["Owner Earnings Yld"] = (f"Earnings yield {yld:.1f}% (P/E {sd.trailing_pe:.1f}×, estimated — owner earnings unavailable)  ·  target yield ≥7%")
    else:
        ctx["Owner Earnings Yld"] = "No valuation data available"

    # ── Capital Allocation ──
    valid_ni  = [x for x in (sd.net_income_history or []) if x and x > 0]
    valid_eps = [x for x in (sd.eps_history or [])        if x and x > 0]
    ca_parts  = []
    ni_cagr = eps_cagr = None
    if len(valid_ni) >= 2:
        ni_cagr = ((valid_ni[0] / valid_ni[-1]) ** (1 / (len(valid_ni) - 1)) - 1) * 100
        ca_parts.append(f"NI CAGR {ni_cagr:.1f}%")
    if len(valid_eps) >= 2:
        eps_cagr = ((valid_eps[0] / valid_eps[-1]) ** (1 / (len(valid_eps) - 1)) - 1) * 100
        tier = ("≥12% = full marks" if eps_cagr >= 12
                else "≥8% good" if eps_cagr >= 8
                else "≥5% fair" if eps_cagr >= 5
                else "≥2% below target" if eps_cagr >= 2
                else "≥0% weak" if eps_cagr >= 0
                else "negative — declining per-share value")
        ca_parts.append(f"EPS CAGR {eps_cagr:.1f}% — {tier} (primary metric)")
        if ni_cagr is not None and (ni_cagr - eps_cagr) > 5:
            ca_parts.append(f"NI outpaced EPS by {ni_cagr - eps_cagr:.1f}pp → dilution detected, penalty applied")
        elif ni_cagr is not None and (eps_cagr - ni_cagr) > 2:
            ca_parts.append("EPS outpacing NI → buyback bonus applied")
    ctx["Capital Allocation"] = ("  ·  ".join(ca_parts)
                                  if ca_parts else "Insufficient data")
    return ctx


# ─────────────────────────────────────────────
# 12-TENET SCORECARD RENDERER
# ─────────────────────────────────────────────

_TENET_TITLES = {
    1:  "Simple and understandable",
    2:  "Consistent operating history",
    3:  "Favorable long-term prospects",
    4:  "Rational capital allocation",
    5:  "Candid with shareholders",
    6:  "Resists institutional imperative",
    7:  "ROE >15% sustained",
    8:  "Owner earnings / FCF positive",
    9:  "High margins maintained",
    10: "$1 market value per $1 retained",
    11: "Intrinsic value determinable",
    12: "Margin of safety ≥20%",
}

_TENET_GROUPS = {
    "BUSINESS": [1, 2, 3],
    "MANAGEMENT": [4, 5, 6],
    "FINANCIAL": [7, 8, 9, 10],
    "VALUE": [11, 12],
}

_BADGE = {
    "Pass":     ("✅", "#2ecc71", "rgba(46,204,113,0.15)"),
    "Partial":  ("⚠️",  "#f1c40f", "rgba(241,196,15,0.15)"),
    "Fail":     ("❌", "#e74c3c", "rgba(231,76,60,0.15)"),
    "Review":   ("🔍", "#888888", "rgba(100,100,100,0.10)"),
    "Deferred": ("⏳", "#3498db", "rgba(52,152,219,0.12)"),
    "Insufficient data": ("❓", "#888888", "rgba(100,100,100,0.10)"),
}


def render_tenet_scorecard(tenet_scores: dict) -> None:
    """Render the 12-tenet Buffett scorecard as an HTML widget."""
    # Tally automated grades
    counts = {"Pass": 0, "Partial": 0, "Fail": 0}
    for grade, _ in tenet_scores.values():
        if grade in counts:
            counts[grade] += 1

    automated = counts["Pass"] + counts["Partial"] + counts["Fail"]
    verdict_score = counts["Pass"] + counts["Partial"] * 0.5
    if automated:
        scaled = round(verdict_score / automated * 12)
        if scaled >= 10:
            verdict_label, verdict_color = "Strong Buy", "#2ecc71"
        elif scaled >= 7:
            verdict_label, verdict_color = "Investigate Further", "#f1c40f"
        elif scaled >= 5:
            verdict_label, verdict_color = "Cautious", "#e67e22"
        elif scaled >= 3:
            verdict_label, verdict_color = "Speculative", "#e74c3c"
        else:
            verdict_label, verdict_color = "Avoid", "#c0392b"
    else:
        verdict_label, verdict_color = "Insufficient data", "#888"

    rows = [
        '<div style="font-family:sans-serif;margin:0 0 24px 0;">',
        f'<div style="margin-bottom:14px;font-size:0.88rem;color:#aaa;">'
        f'Auto-graded: <b style="color:#2ecc71">{counts["Pass"]} Pass</b> · '
        f'<b style="color:#f1c40f">{counts["Partial"]} Partial</b> · '
        f'<b style="color:#e74c3c">{counts["Fail"]} Fail</b> · '
        f'<span style="color:#888">4 require manual review</span> &nbsp;|&nbsp; '
        f'Scaled verdict: <b style="color:{verdict_color}">{verdict_label}</b></div>',
    ]

    for group, tenet_ids in _TENET_GROUPS.items():
        rows.append(
            f'<div style="font-size:0.75rem;font-weight:700;letter-spacing:1.5px;'
            f'color:#555;margin:16px 0 6px 0;">{group}</div>'
        )
        for tid in tenet_ids:
            grade, evidence = tenet_scores[tid]
            icon, color, bg = _BADGE.get(grade, _BADGE["Review"])
            rows.append(
                f'<div style="display:flex;gap:10px;align-items:flex-start;'
                f'background:{bg};border-left:3px solid {color};'
                f'border-radius:0 6px 6px 0;padding:8px 12px;margin-bottom:5px;">'
                f'<div style="min-width:22px;font-size:1rem;line-height:1.4">{icon}</div>'
                f'<div style="flex:1;">'
                f'<span style="font-size:0.78rem;color:#888;">T{tid}</span> '
                f'<span style="font-size:0.88rem;font-weight:600;color:#ddd;">'
                f'{_TENET_TITLES[tid]}</span>'
                f'<div style="font-size:0.80rem;color:#aaa;margin-top:3px;">{evidence}</div>'
                f'</div>'
                f'<div style="min-width:60px;text-align:right;font-size:0.78rem;'
                f'color:{color};font-weight:700;">{grade}</div>'
                f'</div>'
            )

    rows.append('</div>')
    st.markdown("".join(rows), unsafe_allow_html=True)


# ─────────────────────────────────────────────
# CHAT BUBBLE RENDERER
# ─────────────────────────────────────────────

def render_chat_bubbles(parts: list[tuple[str, str]]) -> None:
    """Render explanation paragraphs as chat bubbles coloured by sentiment."""
    import re

    def _bold(t: str) -> str:
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)

    STYLES = {
        "positive": (
            'background:rgba(46,204,113,0.13);border:1px solid rgba(46,204,113,0.35);'
            'border-radius:18px 18px 18px 4px;padding:13px 17px;max-width:88%;'
            'color:#c8f0d8;font-size:0.93rem;line-height:1.65;word-break:break-word;margin-bottom:2px;'
        ),
        "negative": (
            'background:rgba(231,76,60,0.13);border:1px solid rgba(231,76,60,0.35);'
            'border-radius:18px 18px 18px 4px;padding:13px 17px;max-width:88%;'
            'color:#f0ccc8;font-size:0.93rem;line-height:1.65;word-break:break-word;margin-bottom:2px;'
        ),
        "neutral": (
            'background:rgba(100,120,140,0.13);border:1px solid rgba(100,120,140,0.3);'
            'border-radius:18px 18px 18px 4px;padding:13px 17px;max-width:88%;'
            'color:#d0d8e0;font-size:0.93rem;line-height:1.65;word-break:break-word;margin-bottom:2px;'
        ),
        "note": (
            'color:#666;font-size:0.78rem;font-style:italic;line-height:1.5;'
            'padding:8px 4px 0 4px;border-top:1px solid #2a2a2a;margin-top:6px;'
        ),
    }
    HEADER = 'font-size:0.78rem;color:#888;margin-bottom:6px;padding-left:2px;'

    rows = ['<div style="display:flex;flex-direction:column;gap:8px;margin:8px 0 24px 0;">']
    rows.append(f'<div style="{HEADER}">🎩 &nbsp;<strong>Warren Buffett</strong></div>')

    for text, sentiment in parts:
        is_note = text.startswith("__NOTE__")
        clean = _bold(text.replace("__NOTE__ ", ""))
        style = STYLES["note"] if is_note else STYLES.get(sentiment, STYLES["neutral"])
        rows.append(f'<div style="{style}">{clean}</div>')

    rows.append('</div>')
    st.markdown("".join(rows), unsafe_allow_html=True)


# ─────────────────────────────────────────────
# TICKER DATA  (6-hour in-process cache shared across all users)
# ─────────────────────────────────────────────

def _cached_fetch(ticker: str):
    return fetch_with_cache(ticker, cache_dir=None, delay=0.5)


# ─────────────────────────────────────────────
# TOP MOVERS  (Yahoo Finance screener, 5-min cache)
# ─────────────────────────────────────────────

@st.cache_data(ttl=300)
def fetch_top_movers(count: int = 20) -> list[dict]:
    try:
        url = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
        params = {
            "scrIds": "most_actives",
            "count": count,
            "fields": "symbol,shortName,regularMarketChangePercent,regularMarketPrice,regularMarketVolume",
        }
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, params=params, headers=headers, timeout=8)
        quotes = resp.json()["finance"]["result"][0]["quotes"]
        return [
            {
                "ticker": q["symbol"],
                "name":   q.get("shortName", q["symbol"])[:24],
                "pct":    q.get("regularMarketChangePercent", 0.0),
                "price":  q.get("regularMarketPrice", 0.0),
                "volume": q.get("regularMarketVolume", 0),
            }
            for q in quotes
        ]
    except Exception:
        return []


# ─────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="Would Buffett Buy?",
    page_icon="🎩",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stAppFooter { display: none !important; }
    footer { display: none !important; }
    footer[data-testid="stAppFooter"] { display: none !important; }
    .stApp > footer { display: none !important; }
    section.main > div:has(~ footer) { padding-bottom: 0 !important; }
    .block-container { padding-bottom: 1rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Session state defaults
if "ticker_input" not in st.session_state:
    st.session_state["ticker_input"] = ""
if "auto_run" not in st.session_state:
    st.session_state["auto_run"] = False

# ── Sidebar: Top 20 Movers ────────────────────
with st.sidebar:
    st.markdown("## 🔥 Trending on Yahoo Finance")
    st.caption("Sorted by volume. Click any ticker to analyse it.")
    movers = fetch_top_movers(20)

    if movers:
        for item in movers:
            arrow = "▲" if item["pct"] >= 0 else "▼"
            col_a, col_b = st.columns([3, 2])
            vol = item["volume"]
            vol_str = f"{vol/1e6:.1f}M" if vol >= 1_000_000 else f"{vol/1e3:.0f}K"
            col_a.markdown(f"**{item['ticker']}**  \n{item['name']}")
            col_b.markdown(
                f"{'🟢' if item['pct'] >= 0 else '🔴'} {arrow} {abs(item['pct']):.1f}%  \n"
                f"${item['price']:.2f} · {vol_str}"
            )
            if st.button("Analyse", key=f"mover_{item['ticker']}",
                         use_container_width=True):
                st.session_state["ticker_input"] = item["ticker"]
                st.session_state["auto_run"] = True
                st.rerun()
            st.markdown("---")
    else:
        st.caption("Could not load movers — check your connection.")

# ── Main ──────────────────────────────────────
st.title("🎩 Would Buffett Buy?")
st.caption("Analysing stocks through the lens of Warren Buffett's investment philosophy.")

with st.form(key="ticker_form"):
    ticker_input = st.text_input(
        "Ticker symbol",
        key="ticker_input",
        placeholder="e.g. KO, AAPL, IOSP",
    ).strip().upper()
    analyse_clicked = st.form_submit_button("Analyse", type="primary")

auto_run = st.session_state.get("auto_run", False)
if auto_run:
    st.session_state["auto_run"] = False

if (analyse_clicked or auto_run) and ticker_input:

    with st.spinner(f"Fetching fundamentals for {ticker_input}… (may retry if rate-limited)"):
        sd = _cached_fetch(ticker_input.upper())

    if sd.error:
        if any(p in sd.error.lower() for p in ("too many requests", "rate limit", "429")):
            st.warning(
                f"Yahoo Finance is rate-limiting requests right now. "
                f"Wait 60–120 seconds and click **Analyse** again — cached results will be used next time."
            )
        else:
            st.error(f"Could not fetch data for **{ticker_input}**: {sd.error}")
        st.stop()

    r       = compute_score(sd)
    m       = margin_of_safety(sd)
    verdict, colour  = get_verdict(r["Total Score"], m.get("MOS Status", ""))
    explanation_parts = build_explanation(sd, r, m, verdict)

    # ── Overall header card ───────────────────
    from datetime import date as _date, datetime as _datetime

    palette = {
        "green":  ("#0d2e1a", "#2ecc71"),
        "yellow": ("#2e2200", "#f1c40f"),
        "blue":   ("#0d1e2e", "#3498db"),
        "red":    ("#2e0d0d", "#e74c3c"),
    }
    bg, fg = palette[colour]
    mos_status = m.get("MOS Status", "")

    _mos_pill = {
        "IN MOS ZONE":               ("#2ecc71", "#0a2010", "IN MOS ZONE"),
        "APPROACHING MOS":           ("#f1c40f", "#2e2200", "APPROACHING MOS"),
        "ABOVE INTRINSIC VALUE":     ("#e74c3c", "#2e0a0a", "ABOVE INTRINSIC VALUE"),
        "DEBT EXCEEDS ENTERPRISE VALUE": ("#e74c3c", "#2e0a0a", "DEBT > EV"),
        "NEGATIVE OWNER EARNINGS":   ("#e74c3c", "#2e0a0a", "NEGATIVE OE"),
    }
    pill_fg, pill_bg, pill_label = _mos_pill.get(
        mos_status, ("#888", "#1a1a1a", mos_status or "NO DATA"))

    score = r["Total Score"]
    score_bar_html = (
        f'<div style="display:flex;align-items:center;gap:10px;margin-top:10px;">'
        f'<div style="flex:1;height:5px;background:rgba(255,255,255,0.08);border-radius:3px;">'
        f'<div style="width:{score:.0f}%;height:100%;background:{fg};border-radius:3px;"></div>'
        f'</div>'
        f'<span style="color:{fg};font-size:0.82rem;font-weight:700;white-space:nowrap">'
        f'{score:.0f} / 100</span></div>'
    )

    tags_html = ""
    if sd.last_report_date:
        try:
            report_dt = _datetime.strptime(sd.last_report_date, "%Y-%m-%d").date()
            days_ago  = (_date.today() - report_dt).days
            age_str   = f"{days_ago // 30}mo" if days_ago >= 60 else f"{days_ago}d"
            tag_col   = "#c8a84b" if days_ago > 90 else "#5a8a5a"
            tags_html += (
                f'<span style="font-size:0.70rem;color:{tag_col};border:1px solid {tag_col};'
                f'border-radius:4px;padding:1px 7px;margin-left:6px;white-space:nowrap">'
                f'Filing {sd.last_report_date} ({age_str} ago)</span>'
            )
        except Exception:
            pass
    if sd.financial_currency and sd.financial_currency != sd.currency:
        tags_html += (
            f'<span style="font-size:0.70rem;color:#c8a84b;border:1px solid #c8a84b;'
            f'border-radius:4px;padding:1px 7px;margin-left:6px;white-space:nowrap">'
            f'Financials in {sd.financial_currency}</span>'
        )

    st.markdown(
        f'<div style="background:{bg};border-left:6px solid {fg};padding:20px 24px;'
        f'border-radius:8px;margin-bottom:18px;">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;">'
        f'<div style="flex:1;min-width:0;">'
        f'<div style="color:{fg};font-size:1.7rem;font-weight:800;letter-spacing:0.5px;'
        f'line-height:1.2">{verdict}</div>'
        f'<div style="color:#bbb;font-size:0.86rem;margin-top:5px;display:flex;'
        f'flex-wrap:wrap;align-items:center;gap:2px;">'
        f'<strong style="color:#ddd">{r["Name"]}</strong>'
        f'<span style="color:#555">&nbsp;·&nbsp;</span>{r["Sector"]}'
        f'<span style="color:#555">&nbsp;·&nbsp;</span>{r["Mkt Cap"]}'
        f'{tags_html}</div>'
        f'{score_bar_html}'
        f'</div>'
        f'<div style="flex-shrink:0;padding-top:4px;">'
        f'<div style="background:{pill_bg};color:{pill_fg};font-size:0.75rem;font-weight:700;'
        f'border:1px solid {pill_fg};border-radius:20px;padding:4px 12px;'
        f'letter-spacing:0.5px;white-space:nowrap;text-align:center">{pill_label}</div>'
        f'</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # ── Valuation metrics ─────────────────────
    price     = m.get("Price")
    mos_entry = m.get("MOS Entry") or 0.0
    iv_low    = m.get("Intrinsic Low")
    iv_high   = m.get("Intrinsic High")
    ev_ebitda = r.get("EV/EBITDA")
    fcf_conv  = r.get("FCF Conversion")
    fwd_pe    = sd.forward_pe

    if price is not None:
        if mos_status == "DEBT EXCEEDS ENTERPRISE VALUE":
            mc1, mc2 = st.columns([1, 3])
            mc1.metric("Current Price", f"${price:.2f}")
            mc2.warning(
                "Net debt exceeds the owner earnings DCF enterprise value — "
                "no positive equity value exists under this model."
            )
        elif m.get("OE/Share") is not None and iv_high:
            # Primary valuation row
            gap_pct = (price - mos_entry) / mos_entry * 100 if mos_entry else None
            low_gap_pct = (iv_low - price) / price * 100 if iv_low and price else None
            high_gap_pct = (iv_high - price) / price * 100 if iv_high and price else None
            
            vc1, vc2, vc3, vc4 = st.columns(4)
            vc1.metric("Current Price",       f"${price:.2f}")
            vc2.metric("MOS Entry (−30%)",    f"${mos_entry:.2f}",
                       delta=f"{gap_pct:+.1f}% vs now" if gap_pct is not None else None,
                       delta_color="inverse")
            vc3.metric("Intrinsic Low (Bear)",  f"${iv_low:.2f}",
                       delta=f"{low_gap_pct:+.1f}%" if low_gap_pct is not None else None)
            vc4.metric("Intrinsic High (Bull)", f"${iv_high:.2f}",
                       delta=f"{high_gap_pct:+.1f}%" if high_gap_pct is not None else None)

            # Secondary multiples row
            secondary = []
            if ev_ebitda is not None:
                secondary.append(("EV / EBITDA",     f"{ev_ebitda:.1f}×", None, None))
            if fcf_conv is not None:
                secondary.append(("FCF Conversion",  f"{fcf_conv:.0f}%",
                                   "≥80% ✓" if fcf_conv >= 80 else "<80%",
                                   "normal" if fcf_conv >= 80 else "off"))
            if fwd_pe is not None:
                secondary.append(("Forward P/E",     f"{fwd_pe:.1f}×", None, None))
            if secondary:
                sec_cols = st.columns(len(secondary))
                for col, (lbl, val, delta, dc) in zip(sec_cols, secondary):
                    if delta:
                        col.metric(lbl, val, delta=delta, delta_color=dc)
                    else:
                        col.metric(lbl, val)

            st.caption(
                "DCF: 10-yr owner earnings · 9% discount rate · 3% terminal growth · 30% MOS buffer"
            )
        else:
            st.info(f"Price: **${price:.2f}** — {mos_status or 'Valuation unavailable'}")

    st.divider()

    # ── 12-Tenet Buffett Scorecard ────────────
    st.subheader("12-Tenet Buffett Scorecard")
    st.caption(
        "8 tenets are rule-based (auto-graded). "
        "T1, T3, T5, T6 require qualitative judgment — marked Review. "
        "T10 fetches price history (~1–2s)."
    )

    tenet_scores = r.get("tenet_scores", {})

    with st.spinner("Fetching price history for T10 ($1 retained → $1 value)…"):
        t10 = compute_tenet10(sd)
    tenet_scores[10] = (t10["grade"], t10["evidence"])

    ev_ebitda = r.get("EV/EBITDA")
    fwd_pe    = sd.forward_pe
    t11_parts = []
    if ev_ebitda:
        t11_parts.append(f"EV/EBITDA {ev_ebitda}×")
    if fwd_pe:
        t11_parts.append(f"fwd P/E {fwd_pe:.1f}×")
    if m.get("Intrinsic Low"):
        t11_parts.append(f"IV ${m['Intrinsic Low']}–${m['Intrinsic High']}")
    t11_ev    = " · ".join(t11_parts) if t11_parts else "Insufficient valuation data"
    t11_grade = "Pass" if m.get("OE/Share") and ev_ebitda else "Partial" if t11_parts else "Fail"
    tenet_scores[11] = (t11_grade, t11_ev)

    mos_status = m.get("MOS Status", "No data")
    t12_grade  = ("Pass"    if mos_status == "IN MOS ZONE"
                  else "Partial" if mos_status == "APPROACHING MOS"
                  else "Fail")
    t12_ev = mos_status
    if m.get("Price") and m.get("MOS Entry"):
        gap     = (m["Price"] - m["MOS Entry"]) / m["MOS Entry"] * 100
        t12_ev += f" · price {gap:+.1f}% vs MOS entry ${m['MOS Entry']}"
    tenet_scores[12] = (t12_grade, t12_ev)

    render_tenet_scorecard(tenet_scores)
    st.divider()

    # ── Buffett explanation ───────────────────
    st.subheader("Warren Buffett's Take")
    render_chat_bubbles(explanation_parts)
    st.divider()

    # ── Score breakdown ───────────────────────
    st.subheader("Score Breakdown")
    score_ctx = build_score_context(sd, r)
    criteria = [
        ("EPS Consistency",    "EPS Consistency (20)",       20),
        ("Return on Equity",   "ROE (15)",                   15),
        ("ROIC",               "ROIC (15)",                  15),
        ("Profit Margins",     "Margins (10)",               10),
        ("Debt & Liquidity",   "Debt & Liquidity (15)",      15),
        ("Owner Earnings Yld", "Owner Earnings Yield (15)",  15),
        ("Capital Allocation", "Capital Allocation (10)",    10),
    ]
    for label, key, weight in criteria:
        raw = r[key]
        pts_str, _, detail = raw.partition(" — ")
        pts = float(pts_str)
        c1, c2 = st.columns([3, 7])
        c1.markdown(f"**{label}**  \n`{pts:.0f} / {weight}`")
        c2.progress(pts / weight, text=detail)
        if label in score_ctx:
            c2.caption(score_ctx[label])

    rev_ctx = score_ctx.get("Revenue Consistency")
    if rev_ctx and rev_ctx != "No revenue data":
        st.caption(f"Revenue consistency (display only, not in 100-pt score): {rev_ctx}")

    # ── Historical Owner Earnings Breakdown ───
    if sd.owner_earnings_history:
        st.divider()
        st.subheader("Historical Owner Earnings")
        st.caption("How the true cash flow was calculated each year (Formula: Operating Cash Flow - Smoothed CapEx - SBC).")
        
        n_cols = len(sd.owner_earnings_history)
        labels = ["TTM / Most Recent"] + [f"{i} Yr(s) Ago" for i in range(1, n_cols)]
        
        def safe_get(lst, idx):
            if lst and idx < len(lst) and lst[idx] is not None:
                return lst[idx]
            return 0
            
        hist_data = []
        for i in range(n_cols):
            hist_data.append({
                "Period": labels[i],
                "Operating Cash Flow": safe_get(sd.operating_cash_flow_history, i),
                "- Smoothed CapEx": -abs(safe_get(sd.smoothed_capex_history, i)),
                "- Stock-Based Comp": -abs(safe_get(sd.sbc_history, i)),
                "Owner Earnings": safe_get(sd.owner_earnings_history, i)
            })
            
        st.dataframe(
            pd.DataFrame(hist_data).style.format({
                "Operating Cash Flow": "${:,.0f}",
                "- Smoothed CapEx": "${:,.0f}",
                "- Stock-Based Comp": "${:,.0f}",
                "Owner Earnings": "${:,.0f}"
            }),
            hide_index=True,
            use_container_width=True
        )

    # ── DCF Calculation Breakdown ────────────────
    if "Bull Breakdown" in m and m["Bull Breakdown"]:
        st.divider()
        st.subheader("DCF Calculation Breakdown")
        st.caption("Step-by-step mathematical breakdown of the 3-Stage Fading Growth DCF model.")
        
        tab1, tab2 = st.tabs(["Bull Case", "Bear Case"])
        
        with tab1:
            st.markdown(f"**Base Owner Earnings:** ${m.get('Base OE', 0):,.2f}")
            df_bull = pd.DataFrame(m["Bull Breakdown"])
            st.dataframe(
                df_bull.style.format({
                    "Future OE": "${:,.2f}",
                    "Present Value": "${:,.2f}"
                }), 
                hide_index=True,
                use_container_width=True
            )
            
        with tab2:
            st.markdown(f"**Base Owner Earnings:** ${m.get('Base OE', 0):,.2f}")
            df_bear = pd.DataFrame(m["Bear Breakdown"])
            st.dataframe(
                df_bear.style.format({
                    "Future OE": "${:,.2f}",
                    "Present Value": "${:,.2f}"
                }), 
                hide_index=True,
                use_container_width=True
            )
            
        st.markdown(f"**Net Debt:** ${m.get('Net Debt', 0):,.2f} &nbsp;&nbsp;|&nbsp;&nbsp; **Shares Outstanding:** {m.get('Shares', 0):,.0f}")
