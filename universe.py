"""
universe.py — Ticker universe loaders for S&P 500 (NYSE) and Nifty 500 (NSE).

Each loader fetches the full constituent list from a public source,
then returns the first `cap` tickers (default 50) for rate-limit safety.
Hardcoded fallbacks are included in case the network fetch fails.
"""

import io

import pandas as pd
import requests
import streamlit as st

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

# ---------------------------------------------------------------------------
# Fallback lists (top 50 by market cap, manually curated)
# ---------------------------------------------------------------------------

_SP500_FALLBACK = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "BRK-B", "LLY", "UBER",
    "AVGO", "JPM", "TSLA", "V", "UNH", "WMT", "MA", "XOM", "PG", "JNJ",
    "COST", "HD", "ORCL", "ABBV", "MRK", "BAC", "KO", "CRM", "CVX", "NFLX",
    "AMD", "PEP", "TMO", "ACN", "LIN", "MCD", "ADBE", "ABT", "WFC", "CSCO",
    "DHR", "TXN", "PM", "GE", "QCOM", "INTU", "CMCSA", "AMGN", "IBM", "AMAT",
]

_NIFTY500_FALLBACK = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "BHARTIARTL.NS", "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "LT.NS",
    "BAJFINANCE.NS", "KOTAKBANK.NS", "AXISBANK.NS", "MARUTI.NS", "HCLTECH.NS",
    "TITAN.NS", "SUNPHARMA.NS", "ASIANPAINT.NS", "TRENT.NS", "WIPRO.NS",
    "NTPC.NS", "ONGC.NS", "ULTRACEMCO.NS", "POWERGRID.NS", "ADANIPORTS.NS",
    "TATASTEEL.NS", "JSWSTEEL.NS", "BAJAJFINSV.NS", "M&M.NS", "INDUSINDBK.NS",
    "TECHM.NS", "HDFCLIFE.NS", "COALINDIA.NS", "NESTLEIND.NS", "GRASIM.NS",
    "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS", "APOLLOHOSP.NS", "SBILIFE.NS",
    "BPCL.NS", "BRITANNIA.NS", "EICHERMOT.NS", "TATACONSUM.NS", "HEROMOTOCO.NS",
    "HINDALCO.NS", "BAJAJ-AUTO.NS", "DABUR.NS", "HAVELLS.NS", "PIDILITIND.NS",
]


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)  # cache 24 h — constituents rarely change
def load_sp500(cap: int = 50) -> list[str]:
    """
    Fetch S&P 500 constituents from Wikipedia.
    Returns the first *cap* tickers.
    """
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        resp = requests.get(url, headers={"User-Agent": _UA}, timeout=15)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text), header=0)
        df = tables[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        return tickers[:cap]
    except Exception as e:
        st.warning(f"⚠️ Could not fetch S&P 500 list from Wikipedia: {e}. Using fallback.")
        return _SP500_FALLBACK[:cap]


@st.cache_data(ttl=86400, show_spinner=False)
def load_nifty500(cap: int = 50) -> list[str]:
    """
    Fetch Nifty 500 constituents from NSE India.
    Uses multiple strategies with fallbacks:
      1. NSE API (session-based with cookies)
      2. Legacy NSE archive CSV
      3. Wikipedia Nifty 50 page
      4. Hardcoded fallback list
    Returns the first *cap* tickers with '.NS' suffix.
    """
    # --- Strategy 1: NSE API with session cookies ---
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        })
        # Hit homepage first to get cookies
        session.get("https://www.nseindia.com", timeout=10)

        # Now call the index API
        api_url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20500"
        resp = session.get(api_url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        symbols = [item["symbol"] for item in data.get("data", []) if item.get("symbol")]
        if symbols:
            tickers = [f"{s}.NS" for s in symbols]
            return tickers[:cap]
    except Exception:
        pass  # Fall through to next strategy

    # --- Strategy 2: Legacy archive CSV ---
    legacy_urls = [
        "https://archives1.nseindia.com/content/indices/ind_nifty500list.csv",
        "https://www1.nseindia.com/content/indices/ind_nifty500list.csv",
    ]
    for url in legacy_urls:
        try:
            resp = requests.get(url, headers={"User-Agent": _UA}, timeout=10)
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text))
            col = [c for c in df.columns if "symbol" in c.lower()]
            if col:
                symbols = df[col[0]].str.strip().tolist()
                tickers = [f"{s}.NS" for s in symbols]
                return tickers[:cap]
        except Exception:
            continue

    # --- Strategy 3: Wikipedia Nifty 50 page ---
    try:
        wiki_url = "https://en.wikipedia.org/wiki/NIFTY_50"
        resp = requests.get(wiki_url, headers={"User-Agent": _UA}, timeout=15)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text), header=0)
        for tbl in tables:
            sym_col = [c for c in tbl.columns if "symbol" in c.lower()]
            if sym_col and len(tbl) >= 40:
                symbols = tbl[sym_col[0]].str.strip().tolist()
                tickers = [f"{s}.NS" for s in symbols if isinstance(s, str) and s.isalpha()]
                if tickers:
                    return tickers[:cap]
    except Exception:
        pass

    # --- Strategy 4: Hardcoded fallback ---
    st.info("ℹ️ Using built-in Nifty 50 ticker list (NSE endpoints unavailable).")
    return _NIFTY500_FALLBACK[:cap]


def get_tickers(market: str, cap: int = 50) -> list[str]:
    """
    Unified entry point.
    market: 'US' for S&P 500 (NYSE) | 'IN' for Nifty 500 (NSE)
    """
    if market == "US":
        return load_sp500(cap)
    else:
        return load_nifty500(cap)
