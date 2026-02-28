from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .binance_api import backfill_missing_ranges
from .binance_archive import load_archive_1m

ONE_MINUTE_NS = 60 * 1_000_000_000


def _build_missing_ranges(index: pd.DatetimeIndex, start_utc: datetime, end_utc: datetime) -> list[tuple[datetime, datetime]]:
    if index.empty:
        return [(start_utc, end_utc)]

    ranges: list[tuple[datetime, datetime]] = []
    first = index[0].to_pydatetime().astimezone(timezone.utc)
    last = index[-1].to_pydatetime().astimezone(timezone.utc)

    if first > start_utc:
        ranges.append((start_utc, first - timedelta(minutes=1)))

    ts = index.asi8
    diffs = np.diff(ts)
    gap_positions = np.where(diffs > ONE_MINUTE_NS)[0]
    for pos in gap_positions:
        gap_start = pd.Timestamp(ts[pos] + ONE_MINUTE_NS, tz="UTC").to_pydatetime()
        gap_end = pd.Timestamp(ts[pos + 1] - ONE_MINUTE_NS, tz="UTC").to_pydatetime()
        ranges.append((gap_start, gap_end))

    if last < end_utc:
        ranges.append((last + timedelta(minutes=1), end_utc))

    return [(start, end) for start, end in ranges if start <= end]


def ingest_1m_hybrid(
    archive_base_url: str,
    binance_api_base_url: str,
    symbol: str,
    start_utc: datetime,
    end_utc: datetime,
    cache_dir: Path | None = None,
) -> tuple[pd.DataFrame, int, int, int]:
    archive_frame = load_archive_1m(
        archive_base_url=archive_base_url,
        symbol=symbol,
        start_utc=start_utc,
        end_utc=end_utc,
        cache_dir=cache_dir,
    )
    archive_frame = archive_frame.sort_index()
    archive_frame = archive_frame[~archive_frame.index.duplicated(keep="last")]
    archive_rows = int(archive_frame.shape[0])

    missing_ranges = _build_missing_ranges(archive_frame.index, start_utc, end_utc)
    missing_count = len(missing_ranges)
    backfill_rows = 0

    if missing_ranges:
        backfill = backfill_missing_ranges(
            binance_api_base_url=binance_api_base_url,
            symbol=symbol,
            ranges=missing_ranges,
        )
        if not backfill.empty:
            backfill_rows = int(backfill.shape[0])
            merged = pd.concat([archive_frame, backfill]).sort_index()
            archive_frame = merged[~merged.index.duplicated(keep="last")]

    archive_frame = archive_frame.loc[(archive_frame.index >= start_utc) & (archive_frame.index <= end_utc)]
    archive_frame = archive_frame.astype("float64", copy=False)
    return archive_frame, missing_count, archive_rows, backfill_rows
