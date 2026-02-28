from __future__ import annotations

import numpy as np
import pandas as pd


def compute_rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / float(window), adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1.0 / float(window), adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.astype("float64")


def _cross_above(series: pd.Series, threshold: float) -> pd.Series:
    return (series.shift(1) <= threshold) & (series > threshold)


def _cross_below(series: pd.Series, threshold: float) -> pd.Series:
    return (series.shift(1) >= threshold) & (series < threshold)


def build_long_signals(strategy: str, rsi: pd.Series, lower: int, upper: int) -> tuple[pd.Series, pd.Series]:
    if strategy == "mean_revert":
        entry = _cross_below(rsi, float(lower))
        exit_ = _cross_above(rsi, float(upper))
    elif strategy == "breakout":
        entry = _cross_above(rsi, float(upper))
        exit_ = _cross_below(rsi, float(lower))
    elif strategy == "centerline":
        entry = _cross_above(rsi, 50.0) & (rsi < float(upper))
        exit_ = _cross_below(rsi, 50.0) & (rsi > float(lower))
    else:
        raise ValueError(f"Unsupported RSI strategy: {strategy}")
    return entry.fillna(False), exit_.fillna(False)


def build_inverse_signals(long_entry: pd.Series, long_exit: pd.Series) -> tuple[pd.Series, pd.Series]:
    return long_exit.copy(), long_entry.copy()
