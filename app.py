"""
Global Rates Dashboard
======================
Pulls data from CCIL, FRED, Treasury, EIA and displays a live
fixed-income / macro dashboard.

Run:
    pip install -r requirements.txt
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, date
import time

# ── page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Global Rates Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── API keys (set in .streamlit/secrets.toml or env vars) ────────────────────
FRED_API_KEY   = st.secrets.get("FRED_API_KEY", "")      # https://fred.stlouisfed.org/docs/api/api_key.html
EIA_API_KEY    = st.secrets.get("EIA_API_KEY", "")       # https://www.eia.gov/opendata/register.php
FX_API_KEY     = st.secrets.get("FX_API_KEY", "")        # https://app.exchangerate-api.com  (free tier)

# ── helpers ───────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

def safe_get(url, timeout=10, params=None):
    """HTTP GET with error handling."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, params=params)
        r.raise_for_status()
        return r
    except Exception as e:
        st.warning(f"⚠️ Could not fetch {url}: {e}")
        return None


def fred_series(series_id: str) -> float | None:
    """Fetch latest observation from FRED."""
    if not FRED_API_KEY:
        return None
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 1,
    }
    r = safe_get(url, params=params)
    if r:
        obs = r.json().get("observations", [])
        if obs and obs[0]["value"] != ".":
            return float(obs[0]["value"])
    return None


# ── CCIL scraper ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)   # cache 1 hour
def fetch_ccil_tenor_yields() -> pd.DataFrame:
    """
    Scrape the CCIL Tenorwise Indicative Yields page.
    Returns a DataFrame with columns: Tenor, G-sec, SDL, T-Bill
    URL: https://www.ccilindia.com/tenorwise-indicative-yields
    """
    url = "https://www.ccilindia.com/tenorwise-indicative-yields"
    r = safe_get(url)
    if r is None:
        return pd.DataFrame()
    try:
        tables = pd.read_html(r.text)
        # CCIL renders one table with tenor-wise yields
        df = tables[0]
        df.columns = [str(c).strip() for c in df.columns]
        return df
    except Exception as e:
        st.warning(f"CCIL tenor parse error: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def fetch_ccil_sdl_spreads() -> pd.DataFrame:
    """
    Scrape the CCIL State Government Spread Analysis page.
    URL: https://www.ccilindia.com/state-government-spread-analysis
    Returns DataFrame with SDL yield, G-sec yield, spread.
    """
    url = "https://www.ccilindia.com/state-government-spread-analysis"
    r = safe_get(url)
    if r is None:
        return pd.DataFrame()
    try:
        tables = pd.read_html(r.text)
        df = tables[0]
        df.columns = [str(c).strip() for c in df.columns]
        return df
    except Exception as e:
        st.warning(f"CCIL SDL parse error: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def fetch_ccil_ois() -> pd.DataFrame:
    """
    Scrape CCIL OIS rates page.
    URL: https://www.ccilindia.com/ois-rates  (adjust if URL differs)
    """
    url = "https://www.ccilindia.com/ois-rates"
    r = safe_get(url)
    if r is None:
        return pd.DataFrame()
    try:
        tables = pd.read_html(r.text)
        df = tables[0]
        df.columns = [str(c).strip() for c in df.columns]
        return df
    except Exception as e:
        st.warning(f"CCIL OIS parse error: {e}")
        return pd.DataFrame()


# ── US Treasury yields ────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def fetch_us_treasury_yields() -> dict:
    """
    Fetch US Treasury par yields from Treasury Direct XML feed.
    Falls back to FRED if key is available.
    """
    today = date.today()
    year  = today.year
    url   = f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
    r = safe_get(url)
    if r is None:
        return {}
    try:
        soup  = BeautifulSoup(r.text, "xml")
        entries = soup.find_all("entry")
        if not entries:
            return {}
        # latest entry
        entry = entries[-1]
        def yld(tag):
            node = entry.find(tag)
            return float(node.text) if node and node.text else None
        return {
            "3M":  yld("d:BC_3MONTH"),
            "6M":  yld("d:BC_6MONTH"),
            "1Y":  yld("d:BC_1YEAR"),
            "2Y":  yld("d:BC_2YEAR"),
            "3Y":  yld("d:BC_3YEAR"),
            "5Y":  yld("d:BC_5YEAR"),
            "7Y":  yld("d:BC_7YEAR"),
            "10Y": yld("d:BC_10YEAR"),
            "20Y": yld("d:BC_20YEAR"),
            "30Y": yld("d:BC_30YEAR"),
        }
    except Exception as e:
        st.warning(f"US Treasury parse error: {e}")
        return {}


# ── Japan JGB yields via MoF ─────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def fetch_japan_yields() -> dict:
    """
    Fetch Japan JGB benchmark yields from MoF.
    URL: https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm
    Falls back to approximate scrape.
    """
    url = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm"
    r = safe_get(url)
    if r is None:
        return {}
    try:
        tables = pd.read_html(r.text)
        df = tables[0]
        # MoF table: rows are dates, columns are tenors
        # Get last row (most recent)
        last = df.iloc[-1]
        return {str(col): float(val) for col, val in last.items()
                if col != df.columns[0]}
    except Exception as e:
        st.warning(f"Japan JGB parse error: {e}")
        return {}


# ── FX: USD/INR ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=1800)
def fetch_usd_inr() -> float | None:
    """
    Fetch USD/INR rate.
    Uses ExchangeRate-API (free tier) if key set, else open endpoint.
    """
    if FX_API_KEY:
        url = f"https://v6.exchangerate-api.com/v6/{FX_API_KEY}/latest/USD"
        r = safe_get(url)
        if r:
            data = r.json()
            return data.get("conversion_rates", {}).get("INR")
    # open fallback (no key needed, lower limits)
    url = "https://open.er-api.com/v6/latest/USD"
    r = safe_get(url)
    if r:
        return r.json().get("rates", {}).get("INR")
    return None


# ── Brent crude via EIA ───────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def fetch_brent_crude() -> float | None:
    """
    Fetch Brent crude spot price from EIA API v2.
    Series: PET.RBRTE.D
    """
    if not EIA_API_KEY:
        # Try scraping investing.com as fallback
        return None
    url = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
    params = {
        "api_key": EIA_API_KEY,
        "frequency": "daily",
        "data[0]": "value",
        "facets[product][]": "EPCBRENT",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 1,
    }
    r = safe_get(url, params=params)
    if r:
        rows = r.json().get("response", {}).get("data", [])
        if rows:
            return float(rows[0]["value"])
    return None


# ── Central bank rates via FRED ───────────────────────────────────────────────

@st.cache_data(ttl=86400)   # refresh once a day
def fetch_central_bank_rates() -> dict:
    """
    Fetch policy rates from FRED for major central banks.
    Requires FRED_API_KEY.
    """
    series_map = {
        "🇮🇳 RBI Repo":       "INDIRR",        # India repo rate
        "🇺🇸 Fed Funds":      "FEDFUNDS",
        "🇯🇵 BoJ Policy":     "IRSTCB01JPM156N",
        "🇬🇧 BoE Base":       "BOERUKM",
        "🇪🇺 ECB Deposit":    "ECBDFR",
        "🇨🇳 PBoC LPR 1Y":   "PBOC1YLPR",
        "🇦🇺 RBA Cash":       "RBATCTR",
        "🇨🇭 SNB Policy":     "SNBPRA",
    }
    if not FRED_API_KEY:
        return {}
    return {label: fred_series(sid) for label, sid in series_map.items()}


# ── RBI repo rate fallback scrape ─────────────────────────────────────────────

@st.cache_data(ttl=86400)
def fetch_rbi_repo_rate() -> float | None:
    """Scrape current RBI repo rate from RBI website."""
    url = "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx"
    # RBI publishes policy rates on its home page stats panel
    url2 = "https://www.rbi.org.in/"
    r = safe_get(url2)
    if r is None:
        return None
    try:
        soup = BeautifulSoup(r.text, "html.parser")
        # Look for repo rate in the key rates box
        for tag in soup.find_all(string=lambda t: t and "Repo Rate" in t):
            parent = tag.find_parent()
            if parent:
                nxt = parent.find_next_sibling()
                if nxt:
                    val = nxt.get_text(strip=True).replace("%", "")
                    return float(val)
    except Exception:
        pass
    return None


# ── UI ────────────────────────────────────────────────────────────────────────

def delta_color(val, ref, higher_is_bad=True):
    diff = val - ref if (val is not None and ref is not None) else None
    if diff is None:
        return "normal"
    if higher_is_bad:
        return "inverse" if diff > 0 else "normal"
    return "normal" if diff > 0 else "inverse"


def fmt_yield(v):
    return f"{v:.2f}%" if v is not None else "N/A"


def fmt_rate(v):
    return f"{v:.2f}%" if v is not None else "N/A"


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN APP
# ─────────────────────────────────────────────────────────────────────────────

st.title("📊 Global Rates & Fixed Income Dashboard")
st.caption(f"Data as of {datetime.now().strftime('%d %b %Y, %H:%M IST')}  •  Refreshes every hour")

# Auto-refresh button
col_r, col_info = st.columns([1, 5])
with col_r:
    if st.button("🔄 Refresh now"):
        st.cache_data.clear()
        st.rerun()
with col_info:
    st.caption("Primary India data: CCIL  |  US: Treasury Direct  |  FX: ExchangeRate-API  |  Rates: FRED")

st.divider()

# ── Load all data ─────────────────────────────────────────────────────────────
with st.spinner("Fetching live data..."):
    ccil_yields   = fetch_ccil_tenor_yields()
    ccil_sdl      = fetch_ccil_sdl_spreads()
    ccil_ois      = fetch_ccil_ois()
    us_yields     = fetch_us_treasury_yields()
    jp_yields     = fetch_japan_yields()
    usd_inr       = fetch_usd_inr()
    brent         = fetch_brent_crude()
    cb_rates      = fetch_central_bank_rates()
    rbi_repo      = fetch_rbi_repo_rate()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — INDIA G-SEC YIELDS  (from CCIL)
# ═══════════════════════════════════════════════════════════════════════════
st.subheader("🇮🇳 India G-sec & T-bill Yields  (CCIL)")

if not ccil_yields.empty:
    st.dataframe(
        ccil_yields,
        use_container_width=True,
        hide_index=True,
    )
else:
    # Metric cards with placeholder message
    st.info("Live CCIL data requires network access to ccilindia.com. "
            "Run this app locally or on a server with outbound internet access.")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("10-yr G-sec", "—", help="Source: CCIL")
    c2.metric("5-yr G-sec",  "—", help="Source: CCIL")
    c3.metric("2-yr G-sec",  "—", help="Source: CCIL")
    c4.metric("91-Day T-bill","—", help="Source: CCIL")
    c5.metric("182-Day T-bill","—",help="Source: CCIL")

st.divider()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — OIS RATES  (from CCIL)
# ═══════════════════════════════════════════════════════════════════════════
st.subheader("🔁 India OIS Rates  (CCIL / FBIL MIBOR-based)")

if not ccil_ois.empty:
    st.dataframe(ccil_ois, use_container_width=True, hide_index=True)
else:
    st.info("OIS data will populate from CCIL once connected.")
    ois_cols = st.columns(6)
    for col, tenor in zip(ois_cols, ["1M", "3M", "6M", "1Y", "3Y", "5Y"]):
        col.metric(f"OIS {tenor}", "—")

st.divider()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 — SDL SPREADS  (from CCIL)
# ═══════════════════════════════════════════════════════════════════════════
st.subheader("📋 SDL Yields & Spreads vs G-sec  (CCIL)")

if not ccil_sdl.empty:
    # Try to highlight spread column
    spread_col = next((c for c in ccil_sdl.columns
                       if "spread" in c.lower()), None)
    if spread_col:
        st.dataframe(
            ccil_sdl.style.background_gradient(
                subset=[spread_col], cmap="RdYlGn_r"
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.dataframe(ccil_sdl, use_container_width=True, hide_index=True)
else:
    st.info("SDL spread data will populate from CCIL state-government-spread-analysis page.")
    # Show a sample static table as reference
    sample = pd.DataFrame({
        "State":        ["Maharashtra","Uttar Pradesh","Tamil Nadu","Gujarat","Rajasthan","Karnataka"],
        "Tenor":        ["10Y","10Y","7Y","10Y","15Y","5Y"],
        "SDL Yield (%)":["—","—","—","—","—","—"],
        "G-sec (%)":    ["—","—","—","—","—","—"],
        "Spread (bps)": ["—","—","—","—","—","—"],
    })
    st.dataframe(sample, use_container_width=True, hide_index=True)

st.divider()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4 — US TREASURY YIELDS
# ═══════════════════════════════════════════════════════════════════════════
st.subheader("🇺🇸 US Treasury Yields  (Treasury Direct)")

if us_yields:
    ust_df = pd.DataFrame(
        [(tenor, val) for tenor, val in us_yields.items() if val is not None],
        columns=["Tenor", "Yield (%)"]
    )
    # Show as metrics
    keys = ["3M", "6M", "2Y", "5Y", "10Y", "30Y"]
    cols = st.columns(len(keys))
    for col, k in zip(cols, keys):
        v = us_yields.get(k)
        col.metric(f"UST {k}", fmt_yield(v))

    # Full yield curve as bar chart
    st.bar_chart(
        ust_df.set_index("Tenor")["Yield (%)"],
        use_container_width=True,
        height=200,
    )
else:
    st.info("US Treasury data: fetching from home.treasury.gov")

st.divider()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5 — JAPAN JGB YIELDS
# ═══════════════════════════════════════════════════════════════════════════
st.subheader("🇯🇵 Japan JGB Yields  (MoF Japan)")

if jp_yields:
    cols = st.columns(min(len(jp_yields), 6))
    for col, (tenor, val) in zip(cols, list(jp_yields.items())[:6]):
        col.metric(f"JGB {tenor}", fmt_yield(val))
else:
    st.info("Japan JGB data: fetching from mof.go.jp")

st.divider()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6 — FX & COMMODITIES
# ═══════════════════════════════════════════════════════════════════════════
st.subheader("💱 FX & Commodities")

c1, c2, c3 = st.columns(3)
with c1:
    st.metric(
        "USD / INR",
        f"₹ {usd_inr:.2f}" if usd_inr else "—",
        help="Source: ExchangeRate-API",
    )
with c2:
    st.metric(
        "Brent Crude (USD/bbl)",
        f"$ {brent:.2f}" if brent else "—",
        help="Source: EIA API",
    )
with c3:
    st.metric("Gold (USD/oz)", "—", help="Add FRED series GOLDAMGBD228NLBM")

st.divider()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 7 — CENTRAL BANK POLICY RATES
# ═══════════════════════════════════════════════════════════════════════════
st.subheader("🏦 Central Bank Policy Rates  (FRED)")

# Merge RBI from scrape if FRED didn't return it
if cb_rates:
    cb_df = pd.DataFrame(
        [(bank, fmt_rate(rate)) for bank, rate in cb_rates.items()],
        columns=["Central Bank", "Policy Rate"],
    )
    st.dataframe(cb_df, use_container_width=True, hide_index=True)
else:
    st.info("Add your FRED API key in `.streamlit/secrets.toml` to get live central bank rates. "
            "Free key: https://fred.stlouisfed.org/docs/api/api_key.html")
    # Static reference table
    static_cb = pd.DataFrame({
        "Central Bank": [
            "🇮🇳 RBI Repo", "🇺🇸 Fed Funds", "🇯🇵 BoJ Policy",
            "🇬🇧 BoE Base","🇪🇺 ECB Deposit","🇨🇳 PBoC LPR 1Y",
            "🇦🇺 RBA Cash","🇨🇭 SNB Policy",
        ],
        "Policy Rate": ["—"] * 8,
        "Last Changed": ["—"] * 8,
    })
    st.dataframe(static_cb, use_container_width=True, hide_index=True)


# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "Data sources: CCIL (ccilindia.com) · US Treasury Direct · MoF Japan · "
    "ExchangeRate-API · EIA · FRED (St. Louis Fed)  |  "
    "Not for commercial redistribution. CCIL data © CCIL."
)
