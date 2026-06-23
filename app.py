import streamlit as st
import pandas as pd
import requests
from datetime import datetime

st.set_page_config(
    page_title="Treasury & Markets Dashboard",
    page_icon="📊",
    layout="wide"
)

# -----------------------------
# API KEYS
# -----------------------------
FRED_API_KEY = st.secrets.get("FRED_API_KEY", "")
EIA_API_KEY = st.secrets.get("EIA_API_KEY", "")

# -----------------------------
# HELPERS
# -----------------------------
@st.cache_data(ttl=3600)
def get_fred_latest(series_id):
    try:
        url = "https://api.stlouisfed.org/fred/series/observations"

        params = {
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1
        }

        r = requests.get(url, params=params, timeout=20)
        data = r.json()

        value = data["observations"][0]["value"]

        if value == ".":
            return None

        return float(value)

    except:
        return None


@st.cache_data(ttl=1800)
def get_usd_inr():

    try:
        url = "https://open.er-api.com/v6/latest/USD"

        r = requests.get(url, timeout=20)

        return r.json()["rates"]["INR"]

    except:
        return None


@st.cache_data(ttl=3600)
def get_brent():

    try:
        url = "https://api.eia.gov/v2/petroleum/pri/spt/data/"

        params = {
            "api_key": EIA_API_KEY,
            "frequency": "daily",
            "data[0]": "value",
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": 1
        }

        r = requests.get(url, params=params, timeout=20)

        rows = r.json()["response"]["data"]

        return float(rows[0]["value"])

    except:
        return None


# -----------------------------
# MARKET DATA
# -----------------------------
us2y = get_fred_latest("DGS2")
us5y = get_fred_latest("DGS5")
us10y = get_fred_latest("DGS10")
us30y = get_fred_latest("DGS30")

fed = get_fred_latest("FEDFUNDS")

gold = get_fred_latest("GOLDAMGBD228NLBM")

dxy = get_fred_latest("DTWEXBGS")

usd_inr = get_usd_inr()

brent = get_brent()

# -----------------------------
# INDIA SECTION
# Placeholder until FBIL feed
# -----------------------------
india10y = None
india5y = None
tbill91 = None

rbi_repo = 5.25

# -----------------------------
# HEADER
# -----------------------------
st.title("📊 Treasury & Markets Dashboard")

st.caption(
    f"Last Updated : {datetime.now().strftime('%d-%b-%Y %H:%M')}"
)

# -----------------------------
# INDIA
# -----------------------------
st.subheader("🇮🇳 India")

c1,c2,c3,c4 = st.columns(4)

c1.metric(
    "India 10Y",
    india10y if india10y else "Pending"
)

c2.metric(
    "India 5Y",
    india5y if india5y else "Pending"
)

c3.metric(
    "91D T-Bill",
    tbill91 if tbill91 else "Pending"
)

c4.metric(
    "RBI Repo",
    f"{rbi_repo:.2f}%"
)

st.divider()

# -----------------------------
# US
# -----------------------------
st.subheader("🇺🇸 US Treasury")

u1,u2,u3,u4,u5 = st.columns(5)

u1.metric("US 2Y", f"{us2y:.2f}%" if us2y else "NA")
u2.metric("US 5Y", f"{us5y:.2f}%" if us5y else "NA")
u3.metric("US 10Y", f"{us10y:.2f}%" if us10y else "NA")
u4.metric("US 30Y", f"{us30y:.2f}%" if us30y else "NA")
u5.metric("Fed Funds", f"{fed:.2f}%" if fed else "NA")

st.divider()

# -----------------------------
# FX / COMMODITIES
# -----------------------------
st.subheader("💱 Markets")

m1,m2,m3,m4 = st.columns(4)

m1.metric(
    "USD/INR",
    f"{usd_inr:.2f}" if usd_inr else "NA"
)

m2.metric(
    "Brent",
    f"${brent:.2f}" if brent else "NA"
)

m3.metric(
    "Gold",
    f"${gold:.2f}" if gold else "NA"
)

m4.metric(
    "DXY",
    f"{dxy:.2f}" if dxy else "NA"
)

st.divider()

# -----------------------------
# TREASURY ANALYTICS
# -----------------------------
st.subheader("📈 Treasury Analytics")

spread1 = None
spread2 = None
spread3 = None

if us10y and fed:
    spread3 = round(us10y - fed, 2)

a1,a2,a3 = st.columns(3)

a1.metric(
    "India-US 10Y Spread",
    "Pending"
)

a2.metric(
    "India 10Y - Repo",
    "Pending"
)

a3.metric(
    "US 10Y - Fed",
    f"{spread3:.2f}%" if spread3 is not None else "NA"
)

st.divider()

# -----------------------------
# CENTRAL BANK TABLE
# -----------------------------
st.subheader("🏦 Central Bank Monitor")

cb = pd.DataFrame({
    "Central Bank":[
        "RBI",
        "Federal Reserve"
    ],
    "Rate":[
        rbi_repo,
        fed
    ]
})

st.dataframe(
    cb,
    width="stretch"
)

# -----------------------------
# DOWNLOAD
# -----------------------------
csv = cb.to_csv(index=False).encode()

st.download_button(
    "⬇ Download Central Bank Data",
    csv,
    "central_bank_rates.csv",
    "text/csv"
)
