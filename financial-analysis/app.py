"""
Would Buffett Buy? — Single-ticker Streamlit app
Run: streamlit run app.py
"""

import numpy as np
import requests
import streamlit as st

from buffett_screener import fetch_with_cache, compute_score, margin_of_safety

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
                "A business that consistently earns high returns on equity without gorging on debt "
                "is compounding its owners' wealth year after year, whether the stock moves or not. "
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

    # ── Verdict box ───────────────────────────
    palette = {
        "green":  ("#0d2e1a", "#2ecc71"),
        "yellow": ("#2e2200", "#f1c40f"),
        "blue":   ("#0d1e2e", "#3498db"),
        "red":    ("#2e0d0d", "#e74c3c"),
    }
    bg, fg = palette[colour]
    st.markdown(
        f"""
        <div style="
            background:{bg};
            border-left:6px solid {fg};
            padding:22px 28px;
            border-radius:8px;
            margin-bottom:20px;
        ">
            <div style="color:{fg}; font-size:1.9rem; font-weight:800; letter-spacing:1px;">
                {verdict}
            </div>
            <div style="color:#aaa; font-size:0.95rem; margin-top:6px;">
                {r['Name']} &nbsp;·&nbsp; Score: {r['Total Score']:.0f} / 100
                &nbsp;·&nbsp; {r['Sector']} &nbsp;·&nbsp; {r['Mkt Cap']}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Report date warning ───────────────────
    if sd.last_report_date:
        from datetime import date, datetime
        report_dt = datetime.strptime(sd.last_report_date, "%Y-%m-%d").date()
        days_ago  = (date.today() - report_dt).days
        months_ago = days_ago // 30
        age_str = f"{months_ago} months ago" if months_ago > 1 else f"{days_ago} days ago"
        staleness = "🟡" if days_ago > 90 else "🟢"
        st.markdown(
            f'<div style="font-size:0.82rem;color:#999;margin:-10px 0 14px 0;">'
            f'{staleness} &nbsp;Most recent quarterly filing: <strong>{sd.last_report_date}</strong>'
            f' &nbsp;({age_str}) &nbsp;— data may not reflect events after this date.'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Valuation snapshot ────────────────────
    if m.get("Price") is not None and m.get("OE/Share") is not None:
        status = m["MOS Status"]
        if status == "IN MOS ZONE":
            st.success("✅ IN MOS ZONE — trading below intrinsic value with a margin of safety")
        elif status == "APPROACHING MOS":
            st.warning("⚠️ APPROACHING MOS — near the buy zone, not there yet")
        else:
            st.error("❌ ABOVE INTRINSIC VALUE — price exceeds our owner earnings DCF estimate")

        price     = m["Price"]
        mos_entry = m["MOS Entry"]
        iv_low    = m["Intrinsic Low"]
        iv_high   = m["Intrinsic High"]
        gap_pct   = (price - mos_entry) / mos_entry * 100

        vc1, vc2, vc3, vc4 = st.columns(4)
        vc1.metric("Current Price",      f"${price:.2f}")
        vc2.metric("Entry Point (−30%)", f"${mos_entry:.2f}",
                   delta=f"{gap_pct:+.1f}% vs entry", delta_color="inverse")
        vc3.metric("Intrinsic Value Low",  f"${iv_low:.2f}")
        vc4.metric("Intrinsic Value High", f"${iv_high:.2f}")
        st.caption("Owner Earnings DCF · 10-yr projection · 9% discount · 3% terminal growth · 30% MOS buffer")
    elif m.get("Price") is not None:
        st.info(f"Price: **${m['Price']}** — {m['MOS Status']}")

    st.divider()

    # ── Buffett explanation ───────────────────
    render_chat_bubbles(explanation_parts)
    st.divider()

    # ── Score breakdown ───────────────────────
    st.subheader("Score Breakdown")
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
