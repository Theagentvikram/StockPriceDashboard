"""
screener.py — Parallel data fetch, AND filters, composite-score ranking.

Flow:
  1. Batch-download 1 month of daily OHLCV via yf.download()
  2. Fetch P/E + price via yf.Ticker().info (throttled, batched)
  3. Compute RSI(14) and volume-ratio(20) per ticker
  4. Apply AND filters
  5. Rank by composite score → return top N

GARP screen (run_garp_screen):
  Uses yfinance annual income_stmt (4 years) and quarterly_income_stmt (5 quarters)
  to compute multi-year growth CAGRs and quarterly profit trends.
  Filters:
    Market Cap > 1000 Cr  |  Sales > 1000 Cr
    PEG 0–2               |  Sales growth 1Y/3Y > 15%
    EPS YoY > 1.15        |  EPS growth 3Y > 15%
    Latest quarterly profit > profit 3 quarters ago
  Note: yfinance provides 4 years of annual data, so 3Y CAGR is the longest
  reliable multi-year window (5Y filter uses 3Y CAGR as the best available proxy).
"""

import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st
import yfinance as yf

from indicators import compute_rsi, compute_volume_ratio

warnings.filterwarnings("ignore", category=FutureWarning)


# ---------------------------------------------------------------------------
# 1. Historical data — single batch download
# ---------------------------------------------------------------------------

def _download_history(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """
    Download ~2 months of daily OHLCV for all tickers in one call.
    Returns a dict mapping ticker → DataFrame with columns [Open,High,Low,Close,Volume].
    """
    if not tickers:
        return {}

    try:
        raw = yf.download(
            tickers=tickers,
            period="2mo",
            interval="1d",
            group_by="ticker",
            threads=True,
            progress=False,
        )
    except Exception:
        return {}

    result: dict[str, pd.DataFrame] = {}

    if len(tickers) == 1:
        # yf.download returns a flat DataFrame for a single ticker
        t = tickers[0]
        if not raw.empty:
            # Flatten multi-level columns if present
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.droplevel(1)
            result[t] = raw
        return result

    # Multi-ticker: columns are MultiIndex (ticker, field)
    for t in tickers:
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                df = raw[t].dropna(how="all") if t in raw.columns.get_level_values(0) else pd.DataFrame()
            else:
                df = pd.DataFrame()
            if not df.empty:
                # Flatten any remaining multi-level
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                result[t] = df
        except Exception:
            continue

    return result


# ---------------------------------------------------------------------------
# 2. Ticker info — P/E, price, name (throttled)
# ---------------------------------------------------------------------------

def _fetch_single_info(ticker: str) -> dict | None:
    """Fetch info for a single ticker. Returns dict or None on failure."""
    try:
        info = yf.Ticker(ticker).info
        pe = info.get("trailingPE") or info.get("forwardPE")
        price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
        )
        name = info.get("shortName") or info.get("longName") or ticker
        return {
            "ticker": ticker,
            "name": name,
            "price": round(float(price), 2) if price else None,
            "pe": round(float(pe), 2) if pe else None,
        }
    except Exception:
        return None


def _fetch_info_batch(tickers: list[str], batch_size: int = 10, delay: float = 1.0,
                      progress_cb=None) -> list[dict]:
    """
    Fetch .info for tickers in batches with throttling.
    Uses ThreadPoolExecutor within each batch for speed,
    then sleeps between batches to respect rate limits.
    """
    results = []
    total = len(tickers)

    for i in range(0, total, batch_size):
        batch = tickers[i : i + batch_size]
        with ThreadPoolExecutor(max_workers=min(5, len(batch))) as executor:
            futures = {executor.submit(_fetch_single_info, t): t for t in batch}
            for future in as_completed(futures):
                res = future.result()
                if res:
                    results.append(res)

        if progress_cb:
            progress_cb(min(i + batch_size, total), total)

        # Throttle between batches (skip sleep after last batch)
        if i + batch_size < total:
            time.sleep(delay)

    return results


# ---------------------------------------------------------------------------
# 3. Full screening pipeline
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def run_screen(
    tickers: list[str],
    pe_threshold: float = 20.0,
    vol_threshold: float = 2.0,
    rsi_threshold: float = 50.0,
    top_n: int = 25,
) -> tuple[pd.DataFrame, dict]:
    """
    Run the full screening pipeline.

    Returns
    -------
    (ranked_df, stats)
        ranked_df : top-N filtered & ranked DataFrame
        stats : dict with scanned, passed, shown counts
    """
    stats = {"scanned": len(tickers), "passed": 0, "shown": 0, "rate_limited": False}

    if not tickers:
        return pd.DataFrame(), stats

    # --- Step 1: Download historical data ---
    history = _download_history(tickers)
    
    # Check for rate limiting or complete failure if we requested many
    if (not history or len(history) < len(tickers) * 0.2) and len(tickers) > 50:
        stats["rate_limited"] = True
        tickers = tickers[:50]
        stats["scanned"] = len(tickers)
        history = _download_history(tickers)

    available = [t for t in tickers if t in history]

    if not available:
        return pd.DataFrame(), stats

    # --- Step 2: Fetch info (P/E, price, name) ---
    info_list = _fetch_info_batch(available)
    
    # If info fetch failed mostly, we might be rate limited there
    if len(info_list) < len(available) * 0.2 and len(tickers) > 50:
        stats["rate_limited"] = True
        tickers = tickers[:50]
        stats["scanned"] = len(tickers)
        available = [t for t in tickers if t in history]
        info_list = _fetch_info_batch(available)

    info_map = {item["ticker"]: item for item in info_list}

    # --- Step 3: Compute indicators & assemble rows ---
    rows = []
    for t in available:
        info = info_map.get(t)
        if not info or info["price"] is None:
            continue

        hist = history[t]

        # Flatten MultiIndex columns if needed (yfinance sometimes returns (col, ticker))
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.droplevel(1)

        # Get close and volume series
        close_col = None
        vol_col = None
        for c in hist.columns:
            cl = str(c).lower()
            if cl == "close":
                close_col = c
            elif cl == "volume":
                vol_col = c

        if close_col is None or vol_col is None:
            continue

        close = hist[close_col].dropna()
        volume = hist[vol_col].dropna()

        rsi = compute_rsi(close, window=14)
        vol_ratio = compute_volume_ratio(volume, window=20)

        if rsi is None or vol_ratio is None:
            continue

        rows.append({
            "Ticker": t,
            "Company": info["name"],
            "Price": info["price"],
            "P/E": info["pe"],
            "Vol Ratio": vol_ratio,
            "RSI(14)": rsi,
        })

    if not rows:
        return pd.DataFrame(), stats

    df = pd.DataFrame(rows)

    # --- Step 4: AND filter ---
    mask = (
        df["P/E"].notna()
        & (df["P/E"] > 0)
        & (df["P/E"] < pe_threshold)
        & (df["Vol Ratio"] > vol_threshold)
        & (df["RSI(14)"] > rsi_threshold)
    )
    filtered = df[mask].copy()
    stats["passed"] = len(filtered)

    if filtered.empty:
        return pd.DataFrame(), stats

    # --- Step 5: Composite score & rank ---
    #   score = 0.5 × vol_score + 0.3 × rsi_score + 0.2 × pe_score
    #   vol_score  = min(vol_ratio / 5, 1.0)          → 0–1
    #   rsi_score  = (RSI - 50) / 50                   → 0–1
    #   pe_score   = min(1 / PE, 0.2) / 0.2            → 0–1 (lower PE = higher)
    filtered["Vol Score"] = filtered["Vol Ratio"].clip(upper=5.0) / 5.0
    filtered["RSI Score"] = (filtered["RSI(14)"] - 50.0) / 50.0
    filtered["PE Score"] = (1.0 / filtered["P/E"]).clip(upper=0.2) / 0.2

    filtered["Score"] = (
        0.50 * filtered["Vol Score"]
        + 0.30 * filtered["RSI Score"]
        + 0.20 * filtered["PE Score"]
    )

    # Rank
    ranked = (
        filtered
        .sort_values("Score", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )
    ranked.index = ranked.index + 1  # 1-based rank
    ranked.index.name = "Rank"

    # Clean up internal score columns
    ranked = ranked.drop(columns=["Vol Score", "RSI Score", "PE Score"])
    ranked["Score"] = ranked["Score"].round(3)

    stats["shown"] = len(ranked)

    return ranked, stats


# ---------------------------------------------------------------------------
# GARP screen — multi-year fundamental filters using annual statements
# ---------------------------------------------------------------------------

_CRORE = 1e7  # 1 Crore = 10,000,000


def _cagr(end_val: float, start_val: float, years: int) -> float | None:
    """Compound annual growth rate. Returns None if inputs are invalid."""
    try:
        if start_val <= 0 or end_val <= 0 or years <= 0:
            return None
        return (end_val / start_val) ** (1.0 / years) - 1.0
    except Exception:
        return None


def _fetch_garp_data(ticker: str) -> dict | None:
    """
    Fetch all data needed for GARP filters for one ticker.
    Returns a flat dict of computed values, or None on hard failure.
    """
    try:
        t = yf.Ticker(ticker)
        info = t.info

        market_cap = info.get("marketCap")
        total_revenue = info.get("totalRevenue")
        peg = info.get("pegRatio")
        rev_growth_1y = info.get("revenueGrowth")  # decimal, e.g. 0.15
        price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
        )
        name = info.get("shortName") or info.get("longName") or ticker
        pe = info.get("trailingPE") or info.get("forwardPE")
        # earningsGrowth from .info is 1Y EPS growth (decimal); use as PEG fallback
        earnings_growth_1y = info.get("earningsGrowth")

        # --- Annual income statement (up to 5 years, newest-first columns) ---
        ai = t.income_stmt
        rev_series = ai.loc["Total Revenue"].dropna() if "Total Revenue" in ai.index else pd.Series(dtype=float)
        eps_series = ai.loc["Basic EPS"].dropna() if "Basic EPS" in ai.index else pd.Series(dtype=float)
        # Fall back to Diluted EPS if Basic is missing
        if eps_series.empty and "Diluted EPS" in ai.index:
            eps_series = ai.loc["Diluted EPS"].dropna()

        # Sort newest → oldest
        rev_series = rev_series.sort_index(ascending=False)
        eps_series = eps_series.sort_index(ascending=False)

        # 3Y CAGR for revenue: need year[0] and year[3]
        rev_cagr_3y = None
        if len(rev_series) >= 4:
            rev_cagr_3y = _cagr(rev_series.iloc[0], rev_series.iloc[3], 3)
        elif len(rev_series) >= 2:
            # Use whatever span we have
            n = len(rev_series) - 1
            rev_cagr_3y = _cagr(rev_series.iloc[0], rev_series.iloc[n], n)

        # YoY EPS ratio: year[0] / year[1]
        eps_yoy_ratio = None
        if len(eps_series) >= 2 and eps_series.iloc[1] > 0:
            eps_yoy_ratio = eps_series.iloc[0] / eps_series.iloc[1]

        # 3Y EPS CAGR
        eps_cagr_3y = None
        if len(eps_series) >= 4:
            eps_cagr_3y = _cagr(eps_series.iloc[0], eps_series.iloc[3], 3)
        elif len(eps_series) >= 2:
            n = len(eps_series) - 1
            eps_cagr_3y = _cagr(eps_series.iloc[0], eps_series.iloc[n], n)

        # --- Compute PEG if yfinance didn't provide it ---
        # PEG = P/E ÷ (EPS growth rate as %). Use 3Y CAGR first, then 1Y earnings growth.
        if peg is None and pe and pe > 0:
            growth_rate_pct = None
            if eps_cagr_3y is not None and eps_cagr_3y > 0:
                growth_rate_pct = eps_cagr_3y * 100
            elif earnings_growth_1y is not None and earnings_growth_1y > 0:
                growth_rate_pct = earnings_growth_1y * 100
            if growth_rate_pct and growth_rate_pct > 0:
                peg = pe / growth_rate_pct

        # --- Quarterly net income: latest vs 3 quarters ago ---
        qi = t.quarterly_income_stmt
        qni_series = qi.loc["Net Income"].dropna() if "Net Income" in qi.index else pd.Series(dtype=float)
        qni_series = qni_series.sort_index(ascending=False)

        qni_latest = qni_series.iloc[0] if len(qni_series) >= 1 else None
        qni_3q_ago = qni_series.iloc[3] if len(qni_series) >= 4 else None

        return {
            "ticker": ticker,
            "name": name,
            "price": round(float(price), 2) if price else None,
            "pe": round(float(pe), 2) if pe else None,
            "market_cap_cr": round(market_cap / _CRORE, 0) if market_cap else None,
            "sales_cr": round(total_revenue / _CRORE, 0) if total_revenue else None,
            "peg": round(float(peg), 2) if peg else None,
            "rev_growth_1y": round(float(rev_growth_1y), 4) if rev_growth_1y is not None else None,
            "rev_cagr_3y": round(float(rev_cagr_3y), 4) if rev_cagr_3y is not None else None,
            "eps_yoy_ratio": round(float(eps_yoy_ratio), 3) if eps_yoy_ratio is not None else None,
            "eps_cagr_3y": round(float(eps_cagr_3y), 4) if eps_cagr_3y is not None else None,
            "qni_latest": float(qni_latest) if qni_latest is not None else None,
            "qni_3q_ago": float(qni_3q_ago) if qni_3q_ago is not None else None,
        }
    except Exception:
        return None


def _fetch_garp_batch(
    tickers: list[str],
    batch_size: int = 5,
    delay: float = 1.0,
    progress_cb=None,
) -> list[dict]:
    """Fetch GARP data for all tickers with threading + rate-limit throttling."""
    results = []
    total = len(tickers)
    for i in range(0, total, batch_size):
        batch = tickers[i: i + batch_size]
        with ThreadPoolExecutor(max_workers=min(3, len(batch))) as executor:
            futures = {executor.submit(_fetch_garp_data, t): t for t in batch}
            for future in as_completed(futures):
                res = future.result()
                if res:
                    results.append(res)
        if progress_cb:
            progress_cb(min(i + batch_size, total), total)
        if i + batch_size < total:
            time.sleep(delay)
    return results


@st.cache_data(ttl=300, show_spinner=False)
def run_garp_screen(
    tickers: list[str],
    min_market_cap_cr: float = 1000.0,
    min_sales_cr: float = 1000.0,
    peg_min: float = 0.0,
    peg_max: float = 2.0,
    min_sales_growth_1y: float = 0.15,
    min_sales_growth_3y: float = 0.15,
    min_eps_yoy_ratio: float = 1.15,
    min_eps_cagr_3y: float = 0.15,
    top_n: int = 50,
) -> tuple[pd.DataFrame, dict]:
    """
    GARP (Growth At a Reasonable Price) screener using yfinance fundamentals.

    Filters (all must pass — AND logic):
      1. Market Cap > min_market_cap_cr Crores
      2. Sales (TTM) > min_sales_cr Crores
      3. PEG Ratio in (peg_min, peg_max]
      4. Sales growth 1Y > min_sales_growth_1y
      5. Sales growth 3Y CAGR > min_sales_growth_3y  (proxy for 5Y — best available)
      6. EPS (latest) / EPS (1Y ago) > min_eps_yoy_ratio
      7. EPS 3Y CAGR > min_eps_cagr_3y               (proxy for 5Y — best available)
      8. Latest quarter net profit > net profit 3 quarters ago

    Returns (ranked_df, stats).
    """
    stats = {
        "scanned": len(tickers),
        "passed": 0,
        "shown": 0,
        "failed_data": 0,
    }

    if not tickers:
        return pd.DataFrame(), stats

    raw_list = _fetch_garp_batch(tickers)
    stats["failed_data"] = len(tickers) - len(raw_list)

    rows = []
    for d in raw_list:
        # Each filter condition — None means data missing → fail that stock
        mc = d.get("market_cap_cr")
        sales = d.get("sales_cr")
        peg = d.get("peg")
        rg1 = d.get("rev_growth_1y")
        rg3 = d.get("rev_cagr_3y")
        eps_ratio = d.get("eps_yoy_ratio")
        eps3 = d.get("eps_cagr_3y")
        qni_now = d.get("qni_latest")
        qni_3q = d.get("qni_3q_ago")

        # Skip if any required field is missing
        if any(v is None for v in [mc, sales, peg, rg1, rg3, eps_ratio, eps3, qni_now, qni_3q]):
            continue

        passes = (
            mc >= min_market_cap_cr
            and sales >= min_sales_cr
            and peg_min < peg <= peg_max
            and rg1 > min_sales_growth_1y
            and rg3 > min_sales_growth_3y
            and eps_ratio > min_eps_yoy_ratio
            and eps3 > min_eps_cagr_3y
            and qni_now > qni_3q
        )

        if passes:
            rows.append({
                "Ticker": d["ticker"],
                "Company": d["name"],
                "Price": d["price"],
                "Mkt Cap (Cr)": int(mc),
                "Sales (Cr)": int(sales),
                "PEG": d["peg"],
                "P/E": d["pe"],
                "Sales Gr 1Y": f"{rg1 * 100:.1f}%",
                "Sales Gr 3Y": f"{rg3 * 100:.1f}%",
                "EPS YoY": f"{eps_ratio:.2f}x",
                "EPS Gr 3Y": f"{eps3 * 100:.1f}%",
                "Qtr Profit Trend": "↑" if qni_now > qni_3q else "↓",
            })

    stats["passed"] = len(rows)

    if not rows:
        df = pd.DataFrame()
        return df, stats

    df = pd.DataFrame(rows)
    df = df.sort_values("PEG").reset_index(drop=True)
    df.index = df.index + 1
    df.index.name = "Rank"

    stats["shown"] = len(df.head(top_n))
    return df.head(top_n), stats
