from __future__ import annotations

from datetime import datetime
import io
from pathlib import Path
import zipfile

import pandas as pd
import requests

REQUEST_TIMEOUT_SECONDS = 60


def _iter_month_tokens(start_utc: datetime, end_utc: datetime) -> list[tuple[int, int]]:
    months: list[tuple[int, int]] = []
    cursor_year = start_utc.year
    cursor_month = start_utc.month
    while (cursor_year, cursor_month) <= (end_utc.year, end_utc.month):
        months.append((cursor_year, cursor_month))
        if cursor_month == 12:
            cursor_year += 1
            cursor_month = 1
        else:
            cursor_month += 1
    return months


def _monthly_archive_url(archive_base_url: str, symbol: str, timeframe: str, year: int, month: int) -> str:
    month_token = f"{month:02d}"
    filename = f"{symbol}-{timeframe}-{year}-{month_token}.zip"
    return f"{archive_base_url.rstrip('/')}/{symbol}/{timeframe}/{filename}"


def _normalize_open_time_to_ms(open_time: pd.Series) -> pd.Series:
    values = pd.to_numeric(open_time, errors="coerce").astype("int64")
    if values.empty:
        return values

    max_abs = int(values.abs().max())
    if max_abs >= 10**17:
        return values // 1_000_000
    if max_abs >= 10**14:
        return values // 1_000
    return values


def _read_ohlcv_csv_from_zip(content: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        csv_names = [name for name in zf.namelist() if name.endswith(".csv")]
        if not csv_names:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        with zf.open(csv_names[0]) as fp:
            df = pd.read_csv(
                fp,
                header=None,
                usecols=[0, 1, 2, 3, 4, 5],
                names=["open_time", "open", "high", "low", "close", "volume"],
                dtype={
                    "open_time": "int64",
                    "open": "float64",
                    "high": "float64",
                    "low": "float64",
                    "close": "float64",
                    "volume": "float64",
                },
            )
    if df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    normalized_open_time = _normalize_open_time_to_ms(df["open_time"])
    index = pd.to_datetime(normalized_open_time, unit="ms", utc=True)
    out = df[["open", "high", "low", "close", "volume"]].copy()
    out.index = index
    out.index.name = "ts"
    return out


def load_archive_1m(
    archive_base_url: str,
    symbol: str,
    start_utc: datetime,
    end_utc: datetime,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    months = _iter_month_tokens(start_utc=start_utc, end_utc=end_utc)
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)

    for year, month in months:
        url = _monthly_archive_url(
            archive_base_url=archive_base_url,
            symbol=symbol,
            timeframe="1m",
            year=year,
            month=month,
        )
        cache_file: Path | None = None
        if cache_dir:
            cache_file = cache_dir / f"{symbol}-1m-{year}-{month:02d}.zip"
        if cache_file and cache_file.exists():
            content = cache_file.read_bytes()
        else:
            response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code == 404:
                continue
            response.raise_for_status()
            content = response.content
            if cache_file:
                cache_file.write_bytes(content)

        frame = _read_ohlcv_csv_from_zip(content)
        if not frame.empty:
            frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    merged = pd.concat(frames).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    merged = merged.loc[(merged.index >= start_utc) & (merged.index <= end_utc)]
    return merged.astype("float64", copy=False)
