from __future__ import annotations

import pandas as pd

RESAMPLE_RULES = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
    "1w": "1W-MON",
}

OHLCV_AGG = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}


def aggregate_timeframes(df_1m: pd.DataFrame, timeframes: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    if df_1m.empty:
        return {tf: pd.DataFrame(columns=["open", "high", "low", "close", "volume"]) for tf in timeframes}

    out: dict[str, pd.DataFrame] = {}
    for timeframe in timeframes:
        if timeframe not in RESAMPLE_RULES:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        if timeframe == "1m":
            frame = df_1m.copy()
        else:
            frame = df_1m.resample(RESAMPLE_RULES[timeframe], label="left", closed="left").agg(OHLCV_AGG)
            frame = frame.dropna(subset=["open", "high", "low", "close"])
        out[timeframe] = frame.astype("float64", copy=False)
    return out
