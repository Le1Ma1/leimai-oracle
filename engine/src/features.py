from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

EPS = 1e-12


def _timeframe_to_timedelta(timeframe: str) -> pd.Timedelta:
    mapping = {
        "1m": pd.Timedelta(minutes=1),
        "5m": pd.Timedelta(minutes=5),
        "15m": pd.Timedelta(minutes=15),
        "1h": pd.Timedelta(hours=1),
        "4h": pd.Timedelta(hours=4),
        "1d": pd.Timedelta(days=1),
        "1w": pd.Timedelta(days=7),
    }
    if timeframe not in mapping:
        raise ValueError(f"Unsupported timeframe for features: {timeframe}")
    return mapping[timeframe]


def _safe_log_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    num = pd.to_numeric(numerator, errors="coerce").astype("float64")
    den = pd.to_numeric(denominator, errors="coerce").astype("float64")
    return np.log((num + EPS) / (den + EPS))


def _winsorize(series: pd.Series, lower_q: float = 0.005, upper_q: float = 0.995) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").astype("float64")
    if s.empty:
        return s
    lo = float(s.quantile(lower_q))
    hi = float(s.quantile(upper_q))
    if not np.isfinite(lo) or not np.isfinite(hi):
        return s
    if lo > hi:
        lo, hi = hi, lo
    return s.clip(lower=lo, upper=hi)


def _robust_zscore(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").astype("float64")
    med = s.rolling(window=window, min_periods=min_periods).median()
    mad = (s - med).abs().rolling(window=window, min_periods=min_periods).median()
    scale = (1.4826 * mad).replace(0.0, np.nan)
    z = (s - med) / scale
    return z.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _infer_feature_family(name: str) -> str:
    if "__" in name:
        return name.split("__", 1)[0]
    if name.startswith("htf_logret_") or name in {"ret_1m"}:
        return "trend"
    if name.startswith("htf_breakout_"):
        return "oscillation"
    if name.startswith("htf_range_ratio_") or name.startswith("htf_wick_ratio_"):
        return "risk_volatility"
    if name.startswith("vol_") or "volume" in name:
        return "flow_liquidity"
    if name.startswith("ttc_"):
        return "timing_execution"
    return "misc"


def build_feature_registry(feature_df: pd.DataFrame) -> list[dict[str, object]]:
    generated_at_utc = datetime.now(timezone.utc).isoformat()
    if feature_df.empty:
        return []

    rows: list[dict[str, object]] = []
    for column in sorted(feature_df.columns):
        series = pd.to_numeric(feature_df[column], errors="coerce")
        finite = series.replace([np.inf, -np.inf], np.nan).dropna()
        rows.append(
            {
                "name": column,
                "family": _infer_feature_family(column),
                "dtype": str(feature_df[column].dtype),
                "generated_at_utc": generated_at_utc,
                "non_null_ratio": float(finite.shape[0] / max(len(series), 1)),
                "std": float(finite.std()) if not finite.empty else 0.0,
                "mean_abs": float(finite.abs().mean()) if not finite.empty else 0.0,
                "enabled": True,
            }
        )
    return rows


def _prepare_htf_feature_frame(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["close_ts"])

    safe_close = frame["close"].replace(0.0, np.nan)
    safe_open = frame["open"].replace(0.0, np.nan)
    htf_logret = _safe_log_ratio(safe_close, safe_open)
    bar_range = (frame["high"] - frame["low"]).replace(0.0, np.nan)
    upper_wick = frame["high"] - np.maximum(frame["open"], frame["close"])
    lower_wick = np.minimum(frame["open"], frame["close"]) - frame["low"]
    rolling_high = frame["high"].rolling(20, min_periods=5).max().shift(1)
    rolling_low = frame["low"].rolling(20, min_periods=5).min().shift(1)

    out = pd.DataFrame(index=frame.index.copy())
    out["close_ts"] = out.index + _timeframe_to_timedelta(timeframe)

    # Legacy columns for backward compatibility.
    out[f"htf_logret_{timeframe}"] = htf_logret
    out[f"htf_range_ratio_{timeframe}"] = (frame["high"] - frame["low"]) / safe_close
    out[f"htf_wick_ratio_{timeframe}"] = (upper_wick + lower_wick) / bar_range
    out[f"htf_breakout_high_dist_{timeframe}"] = (safe_close - rolling_high) / rolling_high.replace(0.0, np.nan)
    out[f"htf_breakout_low_dist_{timeframe}"] = (safe_close - rolling_low) / rolling_low.replace(0.0, np.nan)

    # Family columns used by the feature-first pipeline.
    out[f"trend__logret__{timeframe}"] = htf_logret
    out[f"risk_volatility__range_ratio__{timeframe}"] = (frame["high"] - frame["low"]) / safe_close
    out[f"risk_volatility__wick_ratio__{timeframe}"] = (upper_wick + lower_wick) / bar_range
    out[f"risk_volatility__realized_vol_20__{timeframe}"] = htf_logret.rolling(20, min_periods=5).std()
    out[f"oscillation__breakout_high_dist__{timeframe}"] = (safe_close - rolling_high) / rolling_high.replace(0.0, np.nan)
    out[f"oscillation__breakout_low_dist__{timeframe}"] = (safe_close - rolling_low) / rolling_low.replace(0.0, np.nan)
    return out.reset_index(drop=True)


def _time_to_close_efficiency(index_1m: pd.DatetimeIndex, timeframe: str) -> pd.DataFrame:
    tf_delta = _timeframe_to_timedelta(timeframe)
    total_minutes = int(tf_delta // pd.Timedelta(minutes=1))
    if total_minutes <= 0:
        raise ValueError(f"Invalid timeframe span in minutes: {timeframe}")

    epoch_minutes = index_1m.view("int64") // 60_000_000_000
    offset = epoch_minutes % total_minutes
    remaining = (total_minutes - offset).astype("float64")

    out = pd.DataFrame(index=index_1m.copy())
    # Legacy columns.
    out[f"ttc_min_{timeframe}"] = remaining
    out[f"ttc_log_{timeframe}"] = np.log1p(remaining)

    # Family columns.
    out[f"timing_execution__ttc_min__{timeframe}"] = remaining
    out[f"timing_execution__ttc_log__{timeframe}"] = np.log1p(remaining)
    out[f"timing_execution__ttc_phase__{timeframe}"] = remaining / max(float(total_minutes), 1.0)
    return out


def _build_base_1m_features(df_1m: pd.DataFrame) -> pd.DataFrame:
    base = pd.DataFrame(index=df_1m.index.copy())
    base.index.name = "ts"

    safe_close = df_1m["close"].replace(0.0, np.nan)
    safe_volume = df_1m["volume"].replace(0.0, np.nan)
    safe_high = pd.to_numeric(df_1m["high"], errors="coerce").astype("float64")
    safe_low = pd.to_numeric(df_1m["low"], errors="coerce").astype("float64")

    ret_1m = _safe_log_ratio(safe_close, safe_close.shift(1))
    vol_logret_1m = _safe_log_ratio(safe_volume, safe_volume.shift(1))
    range_ratio_1m = (safe_high - safe_low) / safe_close

    # Legacy columns.
    base["ret_1m"] = ret_1m
    base["vol_logret_1m"] = vol_logret_1m

    # Family: trend / oscillation / risk.
    base["trend__ret_log__1m"] = ret_1m
    base["oscillation__revert_tension_60__1m"] = _robust_zscore(ret_1m, window=60, min_periods=20)
    base["risk_volatility__range_ratio__1m"] = range_ratio_1m
    base["risk_volatility__realized_vol_60__1m"] = ret_1m.rolling(60, min_periods=20).std()

    # Family: flow / liquidity (adaptive-log heavy).
    rolling_volume_median = safe_volume.rolling(240, min_periods=30).median()
    flow_rel_volume_log = _safe_log_ratio(safe_volume, rolling_volume_median)
    volume_log = np.log1p(pd.to_numeric(df_1m["volume"], errors="coerce").clip(lower=0.0))
    flow_volume_z = _robust_zscore(volume_log, window=240, min_periods=30)
    liq_impact_proxy_log = np.log((ret_1m.abs() + EPS) / (safe_volume.fillna(0.0) + EPS))
    liq_range_over_volume_log = np.log((range_ratio_1m.abs() + EPS) / (safe_volume.fillna(0.0) + EPS))
    vol_ema_fast = safe_volume.ewm(span=30, adjust=False, min_periods=30).mean()
    vol_ema_slow = safe_volume.ewm(span=240, adjust=False, min_periods=60).mean()
    flow_regime_expand_contract = _safe_log_ratio(vol_ema_fast, vol_ema_slow)
    shock_source = flow_rel_volume_log.abs().fillna(0.0)
    shock_threshold = shock_source.rolling(480, min_periods=60).quantile(0.95)
    flow_shock_density = (shock_source > shock_threshold).astype("float64").rolling(240, min_periods=30).mean()

    base["flow_liquidity__rel_volume_log__1m"] = flow_rel_volume_log
    base["flow_liquidity__volume_z__1m"] = flow_volume_z
    base["flow_liquidity__impact_proxy_log__1m"] = liq_impact_proxy_log
    base["flow_liquidity__range_over_volume_log__1m"] = liq_range_over_volume_log
    base["flow_liquidity__regime_expand_contract__1m"] = flow_regime_expand_contract
    base["flow_liquidity__shock_density__1m"] = flow_shock_density

    # Family: timing/execution proxy at 1m level.
    jump_threshold = ret_1m.abs().rolling(480, min_periods=60).quantile(0.97)
    jump_density = (ret_1m.abs() > jump_threshold).astype("float64").rolling(240, min_periods=30).mean()
    base["timing_execution__jump_density__1m"] = jump_density
    return base


def build_feature_set(df_1m: pd.DataFrame, htf_map: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if df_1m.empty:
        return pd.DataFrame()

    base = _build_base_1m_features(df_1m=df_1m)
    base_reset = base.reset_index()

    for timeframe, frame in htf_map.items():
        if timeframe == "1m":
            continue
        prepared = _prepare_htf_feature_frame(frame=frame, timeframe=timeframe)
        if prepared.empty:
            continue

        merged = pd.merge_asof(
            left=base_reset[["ts"]],
            right=prepared,
            left_on="ts",
            right_on="close_ts",
            direction="backward",
        )
        value_columns = [column for column in merged.columns if column not in {"ts", "close_ts"}]
        for column in value_columns:
            base_reset[column] = merged[column].to_numpy(dtype="float64", copy=False)

        ttc = _time_to_close_efficiency(index_1m=base.index, timeframe=timeframe)
        for column in ttc.columns:
            base_reset[column] = ttc[column].to_numpy(dtype="float64", copy=False)

    feature_set = base_reset.set_index("ts")
    feature_set = feature_set.replace([np.inf, -np.inf], np.nan)
    feature_set = feature_set.ffill().bfill().fillna(0.0)

    numeric_cols = [column for column in feature_set.columns if pd.api.types.is_numeric_dtype(feature_set[column])]
    for column in numeric_cols:
        feature_set[column] = _winsorize(feature_set[column])

    return feature_set.astype("float64", copy=False)
