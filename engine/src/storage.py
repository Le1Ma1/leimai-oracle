from __future__ import annotations

from pathlib import Path

import pandas as pd


def write_partitioned_parquet(
    df: pd.DataFrame,
    layer_root: Path,
    symbol: str,
    timeframe: str,
    run_tag: str,
) -> list[str]:
    if df.empty:
        return []

    frame = df.copy()
    frame = frame.reset_index().rename(columns={"index": "ts"})
    frame["date"] = frame["ts"].dt.strftime("%Y-%m-%d")

    written_paths: list[str] = []
    for date_token, chunk in frame.groupby("date", sort=True):
        output_dir = layer_root / f"symbol={symbol}" / f"timeframe={timeframe}" / f"date={date_token}"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{run_tag}.parquet"
        chunk.drop(columns=["date"]).to_parquet(output_path, index=False, engine="pyarrow")
        written_paths.append(str(output_path))
    return written_paths


def load_latest_partitioned_parquet(
    layer_root: Path,
    symbol: str,
    timeframe: str,
    start_utc: pd.Timestamp | None = None,
    end_utc: pd.Timestamp | None = None,
) -> pd.DataFrame:
    base_dir = layer_root / f"symbol={symbol}" / f"timeframe={timeframe}"
    if not base_dir.exists():
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    selected_files: list[Path] = []
    for date_dir in sorted(base_dir.glob("date=*")):
        parquet_files = sorted(date_dir.glob("*.parquet"))
        if not parquet_files:
            continue
        selected_files.append(parquet_files[-1])

    if not selected_files:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    frame = pd.read_parquet([str(path) for path in selected_files], engine="pyarrow")
    if frame.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    if "ts" in frame.columns:
        frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
        frame = frame.set_index("ts")
    elif frame.index.name != "ts":
        frame.index = pd.to_datetime(frame.index, utc=True)
        frame.index.name = "ts"

    frame = frame.sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    for column in ("open", "high", "low", "close", "volume"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    frame = frame.dropna(subset=["open", "high", "low", "close", "volume"])

    if start_utc is not None:
        frame = frame.loc[frame.index >= pd.Timestamp(start_utc)]
    if end_utc is not None:
        frame = frame.loc[frame.index <= pd.Timestamp(end_utc)]

    return frame[["open", "high", "low", "close", "volume"]]
