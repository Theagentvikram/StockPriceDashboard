"""
screener.py — Parallel data fetch, AND filters, composite-score ranking.

Flow:
  1. Batch-download 1 month of daily OHLCV via yf.download()
  2. Fetch P/E + price via yf.Ticker().info (throttled, batched)
  3. Compute RSI(14) and volume-ratio(20) per ticker
  4. Apply AND filters
  5. Rank by composite score → return top N
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
    stats = {"scanned": len(tickers), "passed": 0, "shown": 0}

    if not tickers:
        return pd.DataFrame(), stats

    # --- Step 1: Download historical data ---
    history = _download_history(tickers)
    available = [t for t in tickers if t in history]

    if not available:
        return pd.DataFrame(), stats

    # --- Step 2: Fetch info (P/E, price, name) ---
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
