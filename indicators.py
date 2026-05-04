"""
indicators.py — Technical indicator calculations.

- Wilder's RSI (14-period)  using `ta.momentum.RSIIndicator`
- 20-day volume ratio       (latest volume / 20-day SMA of volume)
"""

import pandas as pd
from ta.momentum import RSIIndicator


def compute_rsi(close: pd.Series, window: int = 14) -> float | None:
    """
    Compute the latest Wilder's RSI value.

    Parameters
    ----------
    close : pd.Series
        Series of closing prices (at least `window + 1` data points).
    window : int
        RSI look-back period. Default 14.

    Returns
    -------
    float or None if insufficient data.
    """
    if close is None or len(close) < window + 1:
        return None
    try:
        # ta library uses Wilder's smoothing by default
        rsi = RSIIndicator(close=close, window=window).rsi()
        val = rsi.iloc[-1]
        return round(float(val), 2) if pd.notna(val) else None
    except Exception:
        return None


def compute_volume_ratio(volume: pd.Series, window: int = 20) -> float | None:
    """
    Compute latest volume / 20-day SMA of volume.

    Parameters
    ----------
    volume : pd.Series
        Series of daily volumes (at least `window` data points).
    window : int
        Look-back period for volume average. Default 20.

    Returns
    -------
    float or None if insufficient data or zero average.
    """
    if volume is None or len(volume) < window:
        return None
    try:
        avg = volume.iloc[-window:].mean()
        if avg == 0 or pd.isna(avg):
            return None
        latest = volume.iloc[-1]
        if pd.isna(latest):
            return None
        return round(float(latest / avg), 2)
    except Exception:
        return None
