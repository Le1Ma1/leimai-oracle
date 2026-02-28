from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import pandas as pd
import requests

REQUEST_TIMEOUT_SECONDS = 30
MAX_LIMIT = 1000
ONE_MINUTE_MS = 60_000


def _parse_klines(rows: list[list[object]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    raw = pd.DataFrame(
        rows,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_asset_volume",
            "num_trades",
            "taker_buy_base",
            "taker_buy_quote",
            "ignore",
        ],
    )
    out = raw[["open_time", "open", "high", "low", "close", "volume"]].copy()
    out["open_time"] = pd.to_numeric(out["open_time"], errors="coerce").astype("int64")
    for column in ["open", "high", "low", "close", "volume"]:
        out[column] = pd.to_numeric(out[column], errors="coerce").astype("float64")
    out = out.dropna()
    out.index = pd.to_datetime(out["open_time"], unit="ms", utc=True)
    out.index.name = "ts"
    return out[["open", "high", "low", "close", "volume"]]


def fetch_ohlcv_range(
    binance_api_base_url: str,
    symbol: str,
    interval: str,
    start_utc: datetime,
    end_utc: datetime,
) -> pd.DataFrame:
    if start_utc.tzinfo is None or end_utc.tzinfo is None:
        raise ValueError("start_utc and end_utc must be timezone-aware UTC datetimes.")
    if start_utc > end_utc:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    url = f"{binance_api_base_url.rstrip('/')}/klines"
    start_ms = int(start_utc.timestamp() * 1000)
    end_ms = int(end_utc.timestamp() * 1000)

    frames: list[pd.DataFrame] = []
    cursor = start_ms
    while cursor <= end_ms:
        response = requests.get(
            url,
            params={
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": MAX_LIMIT,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list) or len(rows) == 0:
            break
        frame = _parse_klines(rows)
        if frame.empty:
            break
        frames.append(frame)
        last_open_time = int(frame.index[-1].timestamp() * 1000)
        next_cursor = last_open_time + ONE_MINUTE_MS
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(rows) < MAX_LIMIT:
            break

    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    merged = pd.concat(frames).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    return merged.loc[(merged.index >= start_utc) & (merged.index <= end_utc)]


def backfill_missing_ranges(
    binance_api_base_url: str,
    symbol: str,
    ranges: Iterable[tuple[datetime, datetime]],
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for start_utc, end_utc in ranges:
        frame = fetch_ohlcv_range(
            binance_api_base_url=binance_api_base_url,
            symbol=symbol,
            interval="1m",
            start_utc=start_utc,
            end_utc=end_utc,
        )
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    merged = pd.concat(frames).sort_index()
    return merged[~merged.index.duplicated(keep="last")]


def fetch_earliest_1m_candle_date(binance_api_base_url: str, symbol: str) -> datetime | None:
    url = f"{binance_api_base_url.rstrip('/')}/klines"
    response = requests.get(
        url,
        params={"symbol": symbol, "interval": "1m", "startTime": 0, "limit": 1},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list) or len(rows) == 0:
        return None
    first = rows[0]
    if not isinstance(first, list) or len(first) < 1:
        return None
    ts_ms = int(first[0])
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
