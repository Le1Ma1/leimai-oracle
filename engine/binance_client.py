from __future__ import annotations

import ccxt
import numpy as np
import pandas as pd

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


def fetch_binance_ohlcv(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    if limit <= 0:
        raise ValueError("limit must be positive.")

    exchange = ccxt.binance(
        {
            "enableRateLimit": True,
            "options": {"defaultType": "spot", "adjustForTimeDifference": True},
        }
    )

    try:
        rows = exchange.fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
    finally:
        close_method = getattr(exchange, "close", None)
        if callable(close_method):
            close_method()

    if not rows:
        raise RuntimeError("Binance returned no OHLCV data.")

    raw = np.asarray(rows, dtype=np.float64)
    if raw.ndim != 2 or raw.shape[1] < 6:
        raise RuntimeError("Malformed OHLCV payload from Binance.")

    ts_ms = raw[:, 0].astype(np.int64)
    index = pd.to_datetime(ts_ms, unit="ms", utc=True)

    frame = pd.DataFrame(raw[:, 1:6], columns=OHLCV_COLUMNS, index=index)
    frame.index.name = "ts"
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    frame = frame.astype(np.float64, copy=False)

    if frame.empty:
        raise RuntimeError("OHLCV frame is empty after normalization.")

    return frame
