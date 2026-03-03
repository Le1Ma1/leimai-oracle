from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from .aggregate import RESAMPLE_RULES
from .config import EngineConfig
from .feature_cores import (
    build_feature_core_signals,
    generate_feature_core_candidates,
    get_core_family,
    get_core_name_zh,
    list_supported_cores,
)
from .features import apply_winsor_bounds, fit_winsor_bounds
from .rsi_strategies import build_inverse_signals
from .single_indicators import (
    build_indicator_signals,
    generate_indicator_candidates,
    get_indicator_family,
    get_indicator_name_zh,
    list_supported_indicators,
)
from .types import (
    EventSampleRef,
    FeatureContributionRow,
    FeaturePruningRow,
    FeatureWeightProfile,
    NoLookaheadAudit,
    OptimizationWindowResult,
    RuleCompetition,
    SignalFrequency,
    StrategyCandidate,
    StrategyMetrics,
    TimeframeOptimizationResult,
)


def _compute_buy_hold_return(close: pd.Series) -> float:
    if close.shape[0] < 2:
        return 0.0
    start = float(close.iloc[0])
    end = float(close.iloc[-1])
    if not np.isfinite(start) or not np.isfinite(end) or abs(start) < 1e-12:
        return 0.0
    return float(end / start - 1.0)


def _passes_objective(friction_adjusted_return: float, benchmark_buy_hold_return: float, objective_mode: str) -> bool:
    if objective_mode == "none":
        return True
    if objective_mode == "beat_spot_each_window":
        return friction_adjusted_return >= benchmark_buy_hold_return
    raise ValueError(f"Unsupported objective mode: {objective_mode}")


def _resolve_window(index: pd.DatetimeIndex, mode: str) -> tuple[datetime, datetime]:
    if index.empty:
        now = datetime.now(timezone.utc)
        return now, now
    end = index.max().to_pydatetime().astimezone(timezone.utc)
    if mode == "all":
        start = index.min().to_pydatetime().astimezone(timezone.utc)
    elif mode == "30d":
        start = end - timedelta(days=30)
    elif mode == "90d":
        start = end - timedelta(days=90)
    elif mode == "360d":
        start = end - timedelta(days=360)
    else:
        raise ValueError(f"Unsupported optimization window: {mode}")
    return start, end


def _resolve_window_trade_floor(
    base_trade_floor: int,
    window_start: datetime,
    window_end: datetime,
    window_mode: str,
    overrides: dict[str, int] | None = None,
) -> int:
    if overrides:
        override_value = overrides.get(str(window_mode).lower())
        if isinstance(override_value, int) and override_value > 0:
            return int(override_value)
    days = max(1, int((window_end - window_start).total_seconds() // 86_400))
    scaled = int(round(float(base_trade_floor) * (float(days) / 365.25)))
    lower_bound = 15
    upper_bound = int(max(base_trade_floor, 1) * 3)
    return int(min(max(scaled, lower_bound), upper_bound))


def _normalize_minmax(values: pd.Series) -> pd.Series:
    lo = float(values.min())
    hi = float(values.max())
    if not np.isfinite(lo) or not np.isfinite(hi):
        return pd.Series(np.full(values.shape[0], 0.5), index=values.index, dtype="float64")
    if abs(hi - lo) < 1e-12:
        return pd.Series(np.full(values.shape[0], 0.5), index=values.index, dtype="float64")
    return ((values - lo) / (hi - lo)).astype("float64")


def _estimate_rule_complexity(rule_key: str, params: dict[str, int | float]) -> float:
    param_count = len(params)
    param_penalty = min(1.0, float(param_count) / 8.0)
    rule_penalty = min(1.0, max(0.0, float(len(rule_key) - 8) / 24.0))
    return float(min(1.0, 0.75 * param_penalty + 0.25 * rule_penalty))


def _estimate_credibility_penalty(
    trades: int,
    window_trade_floor: int,
    win_rate: float,
    max_drawdown: float,
    params_count: int,
) -> float:
    target = max(1.0, float(window_trade_floor))
    trade_ratio = float(max(0, int(trades)) / target)
    trade_quality = float(np.clip(trade_ratio, 0.0, 1.0))
    win_quality = float(np.clip((float(win_rate) - 0.35) / 0.35, 0.0, 1.0))
    dd_quality = float(np.clip(1.0 - (abs(min(float(max_drawdown), 0.0)) / 0.45), 0.0, 1.0))
    complexity_penalty = float(np.clip(float(params_count) / 10.0, 0.0, 1.0))
    credibility = float(np.clip(0.80 * trade_quality + 0.10 * win_quality + 0.10 * dd_quality, 0.0, 1.0))
    return float(np.clip(1.0 - credibility + 0.15 * complexity_penalty, 0.0, 1.0))


def _build_position(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    entry_cum = entry.astype("int64").cumsum()
    exit_cum = exit_.astype("int64").cumsum()
    return (entry_cum > exit_cum).astype("float64")


def _compute_position_and_returns(
    close: pd.Series,
    entry: pd.Series,
    exit_: pd.Series,
    friction_bps: int,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    index = close.index
    close_arr = close.to_numpy(dtype="float64", copy=False)
    entry_arr = entry.reindex(index).fillna(False).to_numpy(dtype=bool, copy=False)
    exit_arr = exit_.reindex(index).fillna(False).to_numpy(dtype=bool, copy=False)

    entry_cum = np.cumsum(entry_arr.astype(np.int64, copy=False))
    exit_cum = np.cumsum(exit_arr.astype(np.int64, copy=False))
    position_arr = (entry_cum > exit_cum).astype("float64", copy=False)

    shifted_position = np.empty_like(position_arr)
    shifted_position[0] = 0.0
    shifted_position[1:] = position_arr[:-1]

    raw_change = np.zeros_like(close_arr)
    prev_close = close_arr[:-1]
    valid = np.abs(prev_close) > 1e-12
    raw_change[1:] = np.where(valid, (close_arr[1:] / prev_close) - 1.0, 0.0)
    raw_returns_arr = shifted_position * raw_change

    turnover = np.abs(np.diff(np.concatenate(([0.0], position_arr))))
    costs = turnover * (float(friction_bps) / 10_000.0)
    net_returns_arr = raw_returns_arr - costs

    position = pd.Series(position_arr, index=index, dtype="float64")
    raw_returns = pd.Series(raw_returns_arr, index=index, dtype="float64")
    net_returns = pd.Series(net_returns_arr, index=index, dtype="float64")
    return position, raw_returns, net_returns


def _compute_strategy_metrics(close: pd.Series, entry: pd.Series, exit_: pd.Series, friction_bps: int) -> StrategyMetrics:
    position, raw_returns, net_returns = _compute_position_and_returns(
        close=close,
        entry=entry,
        exit_=exit_,
        friction_bps=friction_bps,
    )

    raw_arr = raw_returns.to_numpy(dtype="float64", copy=False)
    net_arr = net_returns.to_numpy(dtype="float64", copy=False)
    pos_arr = position.to_numpy(dtype="float64", copy=False)
    if raw_arr.size == 0 or net_arr.size == 0:
        return StrategyMetrics(
            total_return=0.0,
            friction_adjusted_return=0.0,
            max_drawdown=0.0,
            win_rate=0.0,
            trades=0,
        )

    equity_raw = np.cumprod(1.0 + raw_arr)
    equity_net = np.cumprod(1.0 + net_arr)
    running_max = np.maximum.accumulate(equity_net)
    drawdown = np.where(running_max > 0.0, (equity_net / running_max) - 1.0, 0.0)

    transitions = np.diff(np.concatenate(([0.0], pos_arr, [0.0])))
    entry_idx = np.where(transitions > 0.0)[0]
    exit_idx = np.where(transitions < 0.0)[0] - 1
    trades = int(min(entry_idx.shape[0], exit_idx.shape[0]))
    if trades > 0:
        entry_idx = entry_idx[:trades]
        exit_idx = exit_idx[:trades]
        start_equity = np.where(entry_idx > 0, equity_net[entry_idx - 1], 1.0)
        end_equity = equity_net[exit_idx]
        trade_ret = np.where(np.abs(start_equity) > 1e-12, (end_equity / start_equity) - 1.0, 0.0)
        win_rate = float(np.mean(trade_ret > 0.0))
    else:
        win_rate = 0.0

    return StrategyMetrics(
        total_return=float(equity_raw[-1] - 1.0),
        friction_adjusted_return=float(equity_net[-1] - 1.0),
        max_drawdown=float(np.min(drawdown)) if drawdown.size > 0 else 0.0,
        win_rate=win_rate,
        trades=trades,
    )


def _extract_signal_frequency(entry: pd.Series) -> SignalFrequency:
    entry_times = entry.index[entry.fillna(False).to_numpy(dtype=bool)]
    if len(entry_times) == 0:
        return SignalFrequency(
            total_entries=0,
            weekday_entries=0,
            weekend_entries=0,
            session_entries_utc={"asia_00_08": 0, "europe_08_16": 0, "us_16_24": 0},
            hourly_entries_utc=[0] * 24,
        )

    weekday_mask = entry_times.dayofweek < 5
    weekend_count = int((~weekday_mask).sum())
    weekday_count = int(weekday_mask.sum())

    hours = entry_times.hour.to_numpy(dtype=int)
    asia_count = int((hours < 8).sum())
    europe_count = int(((hours >= 8) & (hours < 16)).sum())
    us_count = int((hours >= 16).sum())

    hour_bins = np.bincount(hours, minlength=24).astype(int).tolist()
    return SignalFrequency(
        total_entries=int(len(entry_times)),
        weekday_entries=weekday_count,
        weekend_entries=weekend_count,
        session_entries_utc={"asia_00_08": asia_count, "europe_08_16": europe_count, "us_16_24": us_count},
        hourly_entries_utc=hour_bins,
    )

def _derive_trade_events(close: pd.Series, entry: pd.Series, exit_: pd.Series, friction_bps: int) -> list[dict[str, Any]]:
    position, _, net_returns = _compute_position_and_returns(
        close=close,
        entry=entry,
        exit_=exit_,
        friction_bps=friction_bps,
    )
    pos_arr = position.to_numpy(dtype="float64", copy=False)
    net_arr = net_returns.to_numpy(dtype="float64", copy=False)
    transitions = np.diff(np.concatenate(([0.0], pos_arr, [0.0])))
    entry_idx = np.where(transitions > 0.0)[0]
    exit_idx = np.where(transitions < 0.0)[0] - 1
    trades = int(min(entry_idx.shape[0], exit_idx.shape[0]))
    if trades <= 0:
        return []

    events: list[dict[str, Any]] = []
    idx = close.index
    for trade_i in range(trades):
        start_i = int(entry_idx[trade_i])
        end_i = int(exit_idx[trade_i])
        if end_i < start_i:
            continue
        start_ts = idx[start_i]
        end_ts = idx[end_i]
        pnl = float(np.sum(net_arr[start_i : end_i + 1]))
        events.append(
            {
                "start_utc": start_ts.isoformat(),
                "end_utc": end_ts.isoformat(),
                "entry_utc": start_ts.isoformat(),
                "exit_utc": end_ts.isoformat(),
                "pnl": pnl,
                "bars": int(end_i - start_i + 1),
            }
        )
    return events


def _select_event_samples(events: list[dict[str, Any]]) -> list[EventSampleRef]:
    if not events:
        return []

    ordered = sorted(events, key=lambda item: float(item["pnl"]))
    median_pnl = float(np.median([float(item["pnl"]) for item in ordered]))
    median_item = min(ordered, key=lambda item: abs(float(item["pnl"]) - median_pnl))

    selected: list[tuple[str, dict[str, Any]]] = [
        ("worst_trade", ordered[0]),
        ("median_trade", median_item),
        ("best_trade", ordered[-1]),
    ]
    dedup: dict[tuple[str, str, str], EventSampleRef] = {}
    for sample_type, item in selected:
        key = (item["start_utc"], item["end_utc"], sample_type)
        dedup[key] = EventSampleRef(
            type=sample_type,
            start_utc=item["start_utc"],
            end_utc=item["end_utc"],
            entry_utc=item["entry_utc"],
            exit_utc=item["exit_utc"],
            pnl=float(item["pnl"]),
            bars=int(item["bars"]),
            candles_path=None,
        )
    return list(dedup.values())


def _coerce_bool_series(value: object, index: pd.DatetimeIndex) -> pd.Series:
    if isinstance(value, pd.Series):
        return value.reindex(index).fillna(False).astype(bool)
    return pd.Series(np.asarray(value, dtype=bool), index=index, dtype=bool)


def _supported_strategy_ids(strategy_mode: str) -> set[str]:
    if strategy_mode == "feature_native":
        return set(list_supported_cores())
    return set(list_supported_indicators())


def _resolve_strategy_meta(strategy_mode: str, strategy_id: str) -> tuple[str, str]:
    if strategy_mode == "feature_native":
        return get_core_name_zh(strategy_id), get_core_family(strategy_id)
    return get_indicator_name_zh(strategy_id), get_indicator_family(strategy_id)


def _generate_strategy_candidates(
    *,
    strategy_mode: str,
    strategy_id: str,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    feature_window: pd.DataFrame,
    cfg: EngineConfig,
) -> list[dict[str, object]]:
    if strategy_mode == "feature_native":
        return generate_feature_core_candidates(
            core_id=strategy_id,
            feature_df=feature_window,
            close=close,
            cfg=cfg,
        )
    return generate_indicator_candidates(
        indicator_id=strategy_id,
        close=close,
        high=high,
        low=low,
        cfg=cfg,
    )


def _build_strategy_signals(
    *,
    strategy_mode: str,
    strategy_id: str,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    feature_window: pd.DataFrame,
    rule_key: str,
    params: dict[str, int | float],
) -> tuple[pd.Series, pd.Series]:
    if strategy_mode == "feature_native":
        return build_feature_core_signals(
            core_id=strategy_id,
            feature_df=feature_window,
            close=close,
            rule_key=rule_key,
            params=params,
        )
    return build_indicator_signals(
        indicator_id=strategy_id,
        close=close,
        high=high,
        low=low,
        rule_key=rule_key,
        params=params,
    )


def _run_causality_perturbation_check(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    feature_window: pd.DataFrame,
    fusion_window: pd.Series,
    gate_mode: str,
    indicator_id: str,
    rule_key: str,
    params: dict[str, int | float],
    strategy_mode: str = "indicator",
) -> bool:
    bars = close.shape[0]
    if bars < 140:
        return True

    cutoff_idx = int(bars * 0.70)
    if cutoff_idx < 80 or cutoff_idx >= bars - 2:
        return True

    base_entry, base_exit = _build_strategy_signals(
        strategy_mode=strategy_mode,
        strategy_id=indicator_id,
        close=close,
        high=high,
        low=low,
        feature_window=feature_window,
        rule_key=rule_key,
        params=params,
    )
    base_entry = _coerce_bool_series(base_entry, close.index)
    base_exit = _coerce_bool_series(base_exit, close.index)
    if gate_mode == "gated":
        base_entry = (base_entry & (fusion_window > 0.0)).fillna(False)

    perturbed_close = close.copy()
    perturbed_high = high.copy()
    perturbed_low = low.copy()
    perturbed_feature_window = feature_window.copy()
    perturbed_close.iloc[cutoff_idx + 1 :] = perturbed_close.iloc[cutoff_idx + 1 :] * 1.03
    perturbed_high.iloc[cutoff_idx + 1 :] = perturbed_high.iloc[cutoff_idx + 1 :] * 1.03
    perturbed_low.iloc[cutoff_idx + 1 :] = perturbed_low.iloc[cutoff_idx + 1 :] * 1.03
    if not perturbed_feature_window.empty:
        tail = perturbed_feature_window.iloc[cutoff_idx + 1 :]
        if not tail.empty:
            perturbed_feature_window.iloc[cutoff_idx + 1 :] = tail * 1.03

    perturb_entry, perturb_exit = _build_strategy_signals(
        strategy_mode=strategy_mode,
        strategy_id=indicator_id,
        close=perturbed_close,
        high=perturbed_high,
        low=perturbed_low,
        feature_window=perturbed_feature_window,
        rule_key=rule_key,
        params=params,
    )
    perturb_entry = _coerce_bool_series(perturb_entry, close.index)
    perturb_exit = _coerce_bool_series(perturb_exit, close.index)
    if gate_mode == "gated":
        perturb_entry = (perturb_entry & (fusion_window > 0.0)).fillna(False)

    compare_index = close.index[: cutoff_idx + 1]
    return bool(
        base_entry.loc[compare_index].equals(perturb_entry.loc[compare_index])
        and base_exit.loc[compare_index].equals(perturb_exit.loc[compare_index])
    )

def _score_candidates(rows: list[dict[str, Any]]) -> list[StrategyCandidate]:
    if not rows:
        return []
    df = pd.DataFrame(rows)
    for column, default_value in (
        ("objective_margin_vs_spot", 0.0),
        ("rule_complexity_score", 0.0),
        ("stability_penalty", 0.0),
        ("credibility_penalty", 0.0),
    ):
        if column not in df.columns:
            df[column] = default_value
    df["objective_margin_vs_spot"] = pd.to_numeric(df["objective_margin_vs_spot"], errors="coerce").fillna(0.0)
    df["rule_complexity_score"] = pd.to_numeric(df["rule_complexity_score"], errors="coerce").fillna(0.0)
    df["stability_penalty"] = pd.to_numeric(df["stability_penalty"], errors="coerce").fillna(0.0)
    df["credibility_penalty"] = pd.to_numeric(df["credibility_penalty"], errors="coerce").fillna(0.0).clip(0.0, 1.0)

    ret_norm = _normalize_minmax(df["friction_adjusted_return"])
    alpha_norm = _normalize_minmax(df["objective_margin_vs_spot"])
    mdd_norm = _normalize_minmax(df["max_drawdown"].abs())
    win_norm = _normalize_minmax(df["win_rate"])
    gross_cost = (pd.to_numeric(df["total_return"], errors="coerce").fillna(0.0) - pd.to_numeric(df["friction_adjusted_return"], errors="coerce").fillna(0.0)).clip(lower=0.0)
    cost_norm = _normalize_minmax(gross_cost)
    complexity_norm = _normalize_minmax(df["rule_complexity_score"])
    stability_penalty = df["stability_penalty"].clip(lower=0.0, upper=1.0)
    df["edge_quality"] = (0.70 * alpha_norm + 0.30 * ret_norm).clip(0.0, 1.0)
    df["stability_quality"] = (0.65 * (1.0 - mdd_norm) + 0.35 * win_norm).clip(0.0, 1.0)
    df["friction_quality"] = (1.0 - cost_norm).clip(0.0, 1.0)
    df["credibility_quality"] = (1.0 - df["credibility_penalty"]).clip(0.0, 1.0)
    df["score"] = (
        0.35 * df["edge_quality"]
        + 0.25 * df["stability_quality"]
        + 0.20 * df["friction_quality"]
        + 0.20 * df["credibility_quality"]
        - 0.05 * complexity_norm
        - 0.05 * stability_penalty
    ).clip(lower=-1.0, upper=1.0)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)

    out: list[StrategyCandidate] = []
    for _, row in df.iterrows():
        params = row["params"] if isinstance(row["params"], dict) else {}
        normalized_params: dict[str, int | float] = {}
        for key, value in params.items():
            if isinstance(value, (float, np.floating)):
                normalized_params[str(key)] = float(value)
            else:
                normalized_params[str(key)] = int(value)
        out.append(
            StrategyCandidate(
                signal_source=str(row.get("signal_source", "indicator")),
                strategy_mode=str(row.get("strategy_mode", str(row.get("signal_source", "indicator")))),
                core_id=str(row.get("core_id", row["indicator_id"])),
                core_name_zh=str(row.get("core_name_zh", row["indicator_name_zh"])),
                core_family=str(row.get("core_family", row["indicator_family"])),
                indicator_id=str(row["indicator_id"]),
                indicator_name_zh=str(row["indicator_name_zh"]),
                indicator_family=str(row["indicator_family"]),
                rule_key=str(row["rule_key"]),
                rule_label_zh=str(row["rule_label_zh"]),
                params=normalized_params,
                score=float(row["score"]),
                rule_complexity_score=float(row.get("rule_complexity_score", 0.0)),
                objective_margin_vs_spot=float(row.get("objective_margin_vs_spot", 0.0)),
                stability_penalty=float(row.get("stability_penalty", 0.0)),
                credibility_penalty=float(row.get("credibility_penalty", 0.0)),
                edge_quality=float(row.get("edge_quality", 0.0)),
                friction_quality=float(row.get("friction_quality", 0.0)),
                credibility_quality=float(row.get("credibility_quality", 0.0)),
                metrics=StrategyMetrics(
                    total_return=float(row["total_return"]),
                    friction_adjusted_return=float(row["friction_adjusted_return"]),
                    max_drawdown=float(row["max_drawdown"]),
                    win_rate=float(row["win_rate"]),
                    trades=int(row["trades"]),
                ),
            )
        )
    return out


def _prioritize_objective_candidates(
    candidates: list[StrategyCandidate],
    benchmark_buy_hold_return: float,
    objective_mode: str,
) -> list[StrategyCandidate]:
    if not candidates or objective_mode == "none":
        return candidates

    passing: list[StrategyCandidate] = []
    failing: list[StrategyCandidate] = []
    for candidate in candidates:
        passes = _passes_objective(
            friction_adjusted_return=float(candidate["metrics"]["friction_adjusted_return"]),
            benchmark_buy_hold_return=benchmark_buy_hold_return,
            objective_mode=objective_mode,
        )
        if passes:
            passing.append(candidate)
        else:
            failing.append(candidate)
    return passing + failing


def _normalize_series_01(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").astype("float64")
    if s.empty:
        return s
    lo = float(s.min())
    hi = float(s.max())
    if not np.isfinite(lo) or not np.isfinite(hi) or abs(hi - lo) < 1e-12:
        return pd.Series(np.full(s.shape[0], 0.5), index=s.index, dtype="float64")
    return ((s - lo) / (hi - lo)).astype("float64")


def _family_columns(feature_df: pd.DataFrame, family_prefix: str, legacy_prefixes: tuple[str, ...]) -> list[str]:
    family = [column for column in feature_df.columns if column.startswith(f"{family_prefix}__")]
    legacy: list[str] = []
    for column in feature_df.columns:
        if any(column.startswith(prefix) for prefix in legacy_prefixes):
            legacy.append(column)
    return list(dict.fromkeys(family + legacy))


def _aggregate_family_component(feature_df: pd.DataFrame, columns: list[str]) -> pd.Series:
    if not columns:
        return pd.Series(0.0, index=feature_df.index, dtype="float64")
    frame = feature_df[columns].astype("float64", copy=False)
    exp_mean = frame.expanding(min_periods=60).mean().shift(1)
    exp_std = frame.expanding(min_periods=60).std(ddof=0).shift(1).replace(0.0, np.nan)
    z = (frame - exp_mean) / exp_std
    z = z.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return pd.Series(np.tanh(z).mean(axis=1), index=feature_df.index, dtype="float64")


def _causal_corr_ema(
    signal: pd.Series,
    ret_1m: pd.Series,
    alpha: float = 0.02,
    min_periods: int = 120,
) -> pd.Series:
    x = pd.to_numeric(signal, errors="coerce").astype("float64").shift(1).fillna(0.0)
    y = pd.to_numeric(ret_1m, errors="coerce").astype("float64").fillna(0.0)
    mx = x.ewm(alpha=alpha, adjust=False, min_periods=min_periods).mean()
    my = y.ewm(alpha=alpha, adjust=False, min_periods=min_periods).mean()
    cov = ((x - mx) * (y - my)).ewm(alpha=alpha, adjust=False, min_periods=min_periods).mean()
    vx = ((x - mx).pow(2)).ewm(alpha=alpha, adjust=False, min_periods=min_periods).mean()
    vy = ((y - my).pow(2)).ewm(alpha=alpha, adjust=False, min_periods=min_periods).mean()
    corr = cov / np.sqrt(vx * vy + 1e-12)
    return corr.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def build_fusion_components(feature_df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if feature_df.empty:
        return pd.DataFrame(
            columns=[
                "trend_component",
                "oscillation_component",
                "risk_component",
                "flow_component",
                "timing_component",
                "energy_component",
                "essence_component",
                "ttc_component",
                "fusion_score",
                "oracle_score",
                "confidence",
            ]
        )

    trend_cols = _family_columns(feature_df, "trend", ("htf_logret_", "ret_1m"))
    oscillation_cols = _family_columns(
        feature_df,
        "oscillation",
        ("htf_breakout_high_dist_", "htf_breakout_low_dist_"),
    )
    risk_cols = _family_columns(feature_df, "risk_volatility", ("htf_range_ratio_", "htf_wick_ratio_"))
    flow_cols = _family_columns(feature_df, "flow_liquidity", ("vol_logret_1m",))
    preferred_timing_prefix = f"timing_execution__ttc_log__{timeframe}"
    timing_cols = _family_columns(feature_df, "timing_execution", ("ttc_log_",))
    if preferred_timing_prefix in timing_cols:
        timing_cols = [preferred_timing_prefix] + [column for column in timing_cols if column != preferred_timing_prefix]

    trend_raw = _aggregate_family_component(feature_df, trend_cols)
    oscillation_raw = _aggregate_family_component(feature_df, oscillation_cols)
    risk_raw = _aggregate_family_component(feature_df, risk_cols)
    flow_raw = _aggregate_family_component(feature_df, flow_cols)
    timing_raw = _aggregate_family_component(feature_df, timing_cols)

    ret_1m = pd.to_numeric(
        feature_df.get("trend__ret_log__1m", feature_df.get("ret_1m", pd.Series(0.0, index=feature_df.index))),
        errors="coerce",
    ).astype("float64")
    base_weights = {"trend": 0.30, "oscillation": 0.20, "risk": 0.20, "flow": 0.20, "timing": 0.10}
    corr_alpha = 0.02
    weight_beta = 3.0
    weight_floor = 0.05
    corr_clip = 0.85

    relevance_df = pd.DataFrame(
        {
            "trend": _causal_corr_ema(trend_raw, ret_1m, alpha=corr_alpha).abs().clip(upper=corr_clip),
            "oscillation": _causal_corr_ema(oscillation_raw, ret_1m, alpha=corr_alpha).abs().clip(upper=corr_clip),
            "risk": _causal_corr_ema(risk_raw, ret_1m, alpha=corr_alpha).abs().clip(upper=corr_clip),
            "flow": _causal_corr_ema(flow_raw, ret_1m, alpha=corr_alpha).abs().clip(upper=corr_clip),
            "timing": _causal_corr_ema(timing_raw, ret_1m, alpha=corr_alpha).abs().clip(upper=corr_clip),
        },
        index=feature_df.index,
    ).fillna(0.0)
    weighted_scores = pd.DataFrame(
        {
            key: (0.65 + 1.35 * relevance_df[key]) * float(base_weights[key])
            for key in base_weights
        },
        index=feature_df.index,
    ).fillna(0.0)
    logits = (weighted_scores * weight_beta).clip(lower=-8.0, upper=8.0)
    exp_logits = np.exp(logits)
    family_weights_df = exp_logits.div(exp_logits.sum(axis=1).replace(0.0, np.nan), axis=0).fillna(value=base_weights)
    family_weights_df = family_weights_df.clip(lower=weight_floor)
    family_weights_df = family_weights_df.div(family_weights_df.sum(axis=1).replace(0.0, np.nan), axis=0).fillna(value=base_weights)

    trend_component = family_weights_df["trend"] * trend_raw
    oscillation_component = family_weights_df["oscillation"] * oscillation_raw
    risk_component = -family_weights_df["risk"] * risk_raw.abs()
    flow_component = family_weights_df["flow"] * flow_raw
    timing_component = -family_weights_df["timing"] * timing_raw.abs()
    fusion = trend_component + oscillation_component + risk_component + flow_component + timing_component

    signal_strength = _normalize_series_01(fusion.abs())
    flow_support = ((flow_raw + 1.0) / 2.0).clip(lower=0.0, upper=1.0)
    risk_pressure = _normalize_series_01(risk_raw.abs())
    confidence = (0.50 * signal_strength + 0.30 * flow_support + 0.20 * (1.0 - risk_pressure)).clip(lower=0.0, upper=1.0)

    return pd.DataFrame(
        {
            "trend_component": trend_component.astype("float64", copy=False),
            "oscillation_component": oscillation_component.astype("float64", copy=False),
            "risk_component": risk_component.astype("float64", copy=False),
            "flow_component": flow_component.astype("float64", copy=False),
            "timing_component": timing_component.astype("float64", copy=False),
            # Legacy aliases for compatibility with existing UI naming.
            "energy_component": oscillation_component.astype("float64", copy=False),
            "essence_component": flow_component.astype("float64", copy=False),
            "ttc_component": timing_component.astype("float64", copy=False),
            "fusion_score": fusion.astype("float64", copy=False),
            "oracle_score": fusion.astype("float64", copy=False),
            "confidence": confidence.astype("float64", copy=False),
            "family_weight_trend": family_weights_df["trend"].astype("float64", copy=False),
            "family_weight_oscillation": family_weights_df["oscillation"].astype("float64", copy=False),
            "family_weight_risk": family_weights_df["risk"].astype("float64", copy=False),
            "family_weight_flow": family_weights_df["flow"].astype("float64", copy=False),
            "family_weight_timing": family_weights_df["timing"].astype("float64", copy=False),
        },
        index=feature_df.index,
    )


def _infer_feature_family(feature_name: str) -> str:
    if "__" in feature_name:
        return feature_name.split("__", 1)[0]
    if feature_name.startswith("htf_logret_") or feature_name == "ret_1m":
        return "trend"
    if feature_name.startswith("htf_breakout_"):
        return "oscillation"
    if feature_name.startswith("htf_range_ratio_") or feature_name.startswith("htf_wick_ratio_"):
        return "risk_volatility"
    if "volume" in feature_name or feature_name.startswith("vol_"):
        return "flow_liquidity"
    if feature_name.startswith("ttc_"):
        return "timing_execution"
    return "misc"


def _compute_feature_diagnostics(
    feature_window: pd.DataFrame,
    close_window: pd.Series,
    entry_mask: pd.Series,
) -> tuple[list[FeatureContributionRow], list[FeaturePruningRow], dict[str, float]]:
    if feature_window.empty or close_window.empty:
        return [], [], {}

    horizon = min(30, max(5, int(len(close_window) * 0.002)))
    future_ret = np.log((close_window.shift(-horizon) + 1e-12) / (close_window + 1e-12)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    mask = entry_mask.reindex(close_window.index).fillna(False).astype(bool)
    if int(mask.sum()) < 80:
        mask = pd.Series(True, index=close_window.index)
    sampled_features = feature_window.reindex(close_window.index).loc[mask]
    sampled_target = future_ret.loc[sampled_features.index]

    rows: list[FeatureContributionRow] = []
    for column in sampled_features.columns:
        x = pd.to_numeric(sampled_features[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
        joined = pd.concat([x.rename("x"), sampled_target.rename("y")], axis=1).dropna()
        if joined.shape[0] < 80:
            continue
        std = float(joined["x"].std())
        if not np.isfinite(std) or std <= 1e-12:
            continue
        corr = float(joined["x"].corr(joined["y"]))
        if not np.isfinite(corr):
            corr = 0.0
        coverage = float((joined["x"].abs() > 1e-12).mean())
        utility = float(abs(corr) * (0.5 + 0.5 * coverage))
        rows.append(
            FeatureContributionRow(
                name=str(column),
                family=_infer_feature_family(str(column)),
                utility_score=utility,
                correlation=corr,
                direction="positive" if corr >= 0.0 else "negative",
                coverage=coverage,
            )
        )
    rows.sort(key=lambda item: float(item["utility_score"]), reverse=True)

    family_sums: dict[str, float] = {}
    for row in rows:
        family = str(row["family"])
        family_sums[family] = family_sums.get(family, 0.0) + float(row["utility_score"])
    total_utility = sum(family_sums.values())
    family_share = {
        key: (float(value / total_utility) if total_utility > 1e-12 else 0.0)
        for key, value in family_sums.items()
    }

    prune_rows: list[FeaturePruningRow] = []
    if rows:
        utilities = pd.Series([float(row["utility_score"]) for row in rows], dtype="float64")
        cutoff = float(utilities.quantile(0.20))
        top_names = [str(item["name"]) for item in rows[:10]]
        top_frame = sampled_features[top_names] if top_names else pd.DataFrame(index=sampled_features.index)

        for row in rows:
            score = float(row["utility_score"])
            if score > cutoff:
                continue
            feature_name = str(row["name"])
            correlated_with = None
            corr_abs = 0.0
            if not top_frame.empty and feature_name in sampled_features.columns:
                x = pd.to_numeric(sampled_features[feature_name], errors="coerce")
                best_name = None
                best_corr = 0.0
                for top_name in top_names:
                    if top_name == feature_name:
                        continue
                    y = pd.to_numeric(sampled_features[top_name], errors="coerce")
                    corr = float(pd.concat([x, y], axis=1).corr().iloc[0, 1])
                    if not np.isfinite(corr):
                        continue
                    if abs(corr) > best_corr:
                        best_corr = abs(corr)
                        best_name = top_name
                correlated_with = best_name
                corr_abs = float(best_corr)
            reason = "low_utility"
            if corr_abs >= 0.90 and correlated_with:
                reason = "low_utility_high_collinearity"
            prune_rows.append(
                FeaturePruningRow(
                    name=feature_name,
                    family=str(row["family"]),
                    utility_score=score,
                    reason=reason,
                    correlated_with=correlated_with,
                    correlation_abs=corr_abs,
                )
            )
    prune_rows = sorted(
        prune_rows,
        key=lambda item: (0 if item["reason"] == "low_utility_high_collinearity" else 1, float(item["utility_score"])),
    )[:20]
    return rows[:30], prune_rows, family_share


def _compute_feature_weight_profile(
    fusion_components: pd.DataFrame,
    entry: pd.Series,
    feature_contributions: list[FeatureContributionRow] | None = None,
    prune_candidates: list[FeaturePruningRow] | None = None,
    family_contribution: dict[str, float] | None = None,
) -> FeatureWeightProfile | None:
    if fusion_components.empty:
        return None

    entry_mask = entry.fillna(False).to_numpy(dtype=bool)
    scoped = fusion_components.loc[entry_mask]
    if scoped.empty:
        scoped = fusion_components

    abs_means = {
        "trend": float(scoped["trend_component"].abs().mean()),
        "oscillation": float(scoped["oscillation_component"].abs().mean()) if "oscillation_component" in scoped else 0.0,
        "risk": float(scoped["risk_component"].abs().mean()) if "risk_component" in scoped else 0.0,
        "flow": float(scoped["flow_component"].abs().mean()) if "flow_component" in scoped else 0.0,
        "timing": float(scoped["timing_component"].abs().mean()) if "timing_component" in scoped else 0.0,
    }
    denominator = sum(abs_means.values())
    if denominator <= 1e-12:
        shares = {"trend": 0.20, "oscillation": 0.20, "risk": 0.20, "flow": 0.20, "timing": 0.20}
    else:
        shares = {key: float(value / denominator) for key, value in abs_means.items()}

    family_payload = family_contribution or {}
    return FeatureWeightProfile(
        trend_weight_share=shares["trend"],
        energy_weight_share=shares["oscillation"],  # Legacy alias.
        essence_weight_share=shares["flow"],  # Legacy alias.
        ttc_penalty_share=shares["timing"],  # Legacy alias.
        trend_component_avg=float(scoped["trend_component"].mean()),
        energy_component_avg=float(scoped["oscillation_component"].mean()) if "oscillation_component" in scoped else 0.0,
        essence_component_avg=float(scoped["flow_component"].mean()) if "flow_component" in scoped else 0.0,
        ttc_component_avg=float(scoped["timing_component"].mean()) if "timing_component" in scoped else 0.0,
        oscillation_weight_share=shares["oscillation"],
        risk_weight_share=shares["risk"],
        flow_weight_share=shares["flow"],
        timing_weight_share=shares["timing"],
        oscillation_component_avg=float(scoped["oscillation_component"].mean()) if "oscillation_component" in scoped else 0.0,
        risk_component_avg=float(scoped["risk_component"].mean()) if "risk_component" in scoped else 0.0,
        flow_component_avg=float(scoped["flow_component"].mean()) if "flow_component" in scoped else 0.0,
        timing_component_avg=float(scoped["timing_component"].mean()) if "timing_component" in scoped else 0.0,
        family_contribution=family_payload,
        top_features=list(feature_contributions or []),
        prune_candidates=list(prune_candidates or []),
    )


def _align_features_for_timeframe(feature_set_1m: pd.DataFrame, timeframe: str, target_index: pd.DatetimeIndex) -> pd.DataFrame:
    if feature_set_1m.empty:
        return pd.DataFrame(index=target_index.copy())
    if timeframe == "1m":
        return feature_set_1m.reindex(target_index, method="ffill").fillna(0.0)
    rule = RESAMPLE_RULES.get(timeframe)
    if rule is None:
        raise ValueError(f"Unsupported timeframe for feature alignment: {timeframe}")
    feature_tf = feature_set_1m.resample(rule, label="left", closed="left").last()
    return feature_tf.reindex(target_index, method="ffill").fillna(0.0)

def optimize_single_indicator_for_symbol_timeframe(
    price_frame: pd.DataFrame,
    feature_set_1m: pd.DataFrame,
    cfg: EngineConfig,
    symbol: str,
    timeframe: str,
    gate_mode: str,
    indicator_id: str,
) -> TimeframeOptimizationResult:
    strategy_mode = str(getattr(cfg, "rule_engine_mode", "indicator") or "indicator")
    strategy_id = indicator_id
    if price_frame.empty:
        strategy_name_zh, strategy_family = _resolve_strategy_meta(strategy_mode, strategy_id)
        return TimeframeOptimizationResult(
            symbol=symbol,
            timeframe=timeframe,
            gate_mode=gate_mode,
            strategy_mode=strategy_mode,
            core_id=strategy_id,
            core_name_zh=strategy_name_zh,
            core_family=strategy_family,
            indicator_id=strategy_id,
            indicator_name_zh=strategy_name_zh,
            indicator_family=strategy_family,
            windows=[],
        )

    if gate_mode not in {"gated", "ungated"}:
        raise ValueError(f"Unsupported gate mode: {gate_mode}")
    if strategy_id not in _supported_strategy_ids(strategy_mode):
        raise ValueError(f"Unsupported strategy id: {strategy_id} in mode={strategy_mode}")

    close = price_frame["close"].astype("float64")
    high = price_frame["high"].astype("float64")
    low = price_frame["low"].astype("float64")
    aligned_features = _align_features_for_timeframe(feature_set_1m=feature_set_1m, timeframe=timeframe, target_index=close.index)

    indicator_name_zh, indicator_family = _resolve_strategy_meta(strategy_mode, strategy_id)
    drawdown_floor = -0.35
    window_results: list[OptimizationWindowResult] = []
    window_trade_floor_overrides = {str(key).lower(): int(value) for key, value in cfg.window_trade_floor_overrides}

    for window_mode in cfg.optimization_windows:
        window_start, window_end = _resolve_window(index=close.index, mode=window_mode)
        window_trade_floor = _resolve_window_trade_floor(
            base_trade_floor=cfg.trade_floor,
            window_start=window_start,
            window_end=window_end,
            window_mode=window_mode,
            overrides=window_trade_floor_overrides,
        )
        window_mask = (close.index >= window_start) & (close.index <= window_end)
        close_window = close.loc[window_mask]
        high_window = high.loc[window_mask]
        low_window = low.loc[window_mask]
        train_feature_frame = aligned_features.loc[aligned_features.index < window_start]
        winsor_bounds = fit_winsor_bounds(train_feature_frame) if not train_feature_frame.empty else {}
        aligned_features_causal = (
            apply_winsor_bounds(aligned_features, bounds=winsor_bounds)
            if winsor_bounds
            else aligned_features
        )
        fusion_components_all = build_fusion_components(feature_df=aligned_features_causal, timeframe=timeframe)
        oracle_score_all = fusion_components_all.get("oracle_score", fusion_components_all["fusion_score"]).reindex(close.index).fillna(0.0)
        confidence_all = fusion_components_all.get(
            "confidence",
            pd.Series(1.0, index=fusion_components_all.index, dtype="float64"),
        ).reindex(close.index).fillna(1.0)
        oracle_window = oracle_score_all.reindex(close_window.index).fillna(0.0)
        confidence_window = confidence_all.reindex(close_window.index).fillna(1.0)
        fusion_components_window = fusion_components_all.reindex(close_window.index).fillna(0.0)
        benchmark_buy_hold_return = _compute_buy_hold_return(close_window)
        oracle_entry_threshold = (
            float(oracle_window.quantile(cfg.gate_oracle_quantile)) if not oracle_window.empty else 0.0
        )
        confidence_threshold = (
            float(np.clip(confidence_window.quantile(cfg.gate_confidence_quantile), 0.05, 0.95))
            if not confidence_window.empty
            else 0.25
        )

        if close_window.shape[0] < 140:
            window_results.append(
                OptimizationWindowResult(
                    window=window_mode,
                    start_utc=window_start.isoformat(),
                    end_utc=window_end.isoformat(),
                    window_trade_floor=window_trade_floor,
                    benchmark_buy_hold_return=benchmark_buy_hold_return,
                    best_long=None,
                    best_inverse=None,
                    top_long_candidates=[],
                    top_inverse_candidates=[],
                    best_long_alpha_vs_spot=None,
                    best_inverse_alpha_vs_spot=None,
                    best_long_passes_objective=False,
                    best_inverse_passes_objective=False,
                    insufficient_statistical_significance=True,
                    evaluated_candidates=0,
                    rule_competition=None,
                    signal_frequency=None,
                    event_samples=[],
                    no_lookahead_audit=None,
                    feature_weight_profile=None,
                    oracle_threshold=oracle_entry_threshold,
                    confidence_threshold=confidence_threshold,
                )
            )
            continue

        feature_window = aligned_features_causal.reindex(close_window.index).fillna(0.0)
        candidate_defs = _generate_strategy_candidates(
            strategy_mode=strategy_mode,
            strategy_id=strategy_id,
            close=close_window,
            high=high_window,
            low=low_window,
            feature_window=feature_window,
            cfg=cfg,
        )

        long_rows: list[dict[str, Any]] = []
        inverse_rows: list[dict[str, Any]] = []
        evaluated_candidates = 0
        low_credibility_rejected = 0
        underperform_spot_rejected = 0
        high_drawdown_rejected = 0
        rejected_examples: list[dict[str, Any]] = []

        for candidate in candidate_defs:
            rule_key = str(candidate["rule_key"])
            rule_label_zh = str(candidate["rule_label_zh"])
            params = dict(candidate["params"])
            rule_complexity_score = _estimate_rule_complexity(rule_key=rule_key, params=params)
            long_entry = _coerce_bool_series(candidate["entry"], close_window.index)
            long_exit = _coerce_bool_series(candidate["exit"], close_window.index)

            if gate_mode == "gated":
                long_entry = (
                    long_entry
                    & (oracle_window >= oracle_entry_threshold)
                    & (confidence_window >= confidence_threshold)
                ).fillna(False)

            long_metrics = _compute_strategy_metrics(
                close=close_window,
                entry=long_entry,
                exit_=long_exit,
                friction_bps=cfg.friction_bps,
            )
            evaluated_candidates += 1
            long_alpha_vs_spot = float(long_metrics["friction_adjusted_return"] - benchmark_buy_hold_return)
            long_passes_objective = _passes_objective(
                friction_adjusted_return=long_metrics["friction_adjusted_return"],
                benchmark_buy_hold_return=benchmark_buy_hold_return,
                objective_mode=cfg.objective_mode,
            )
            has_high_drawdown = float(long_metrics["max_drawdown"]) < drawdown_floor
            long_credibility_penalty = _estimate_credibility_penalty(
                trades=int(long_metrics["trades"]),
                window_trade_floor=window_trade_floor,
                win_rate=float(long_metrics["win_rate"]),
                max_drawdown=float(long_metrics["max_drawdown"]),
                params_count=len(params),
            )
            if int(long_metrics["trades"]) <= 0:
                low_credibility_rejected += 1
                rejected_examples.append(
                    {
                        "reason": "low_credibility",
                        "signal_source": strategy_mode,
                        "strategy_mode": strategy_mode,
                        "core_id": strategy_id,
                        "core_name_zh": indicator_name_zh,
                        "core_family": indicator_family,
                        "indicator_id": strategy_id,
                        "indicator_name_zh": indicator_name_zh,
                        "indicator_family": indicator_family,
                        "rule_key": rule_key,
                        "rule_label_zh": rule_label_zh,
                        "params": params,
                        "alpha_vs_spot": long_alpha_vs_spot,
                        "metrics": dict(long_metrics),
                    }
                )
                continue
            long_stability_penalty = float(
                np.clip(
                    0.70 * (abs(min(float(long_metrics["max_drawdown"]), 0.0)) / 0.35)
                    + 0.30 * long_credibility_penalty,
                    0.0,
                    1.0,
                )
            )

            if long_credibility_penalty >= cfg.credibility_reject_threshold:
                low_credibility_rejected += 1
                rejected_examples.append(
                    {
                        "reason": "low_credibility",
                        "signal_source": strategy_mode,
                        "strategy_mode": strategy_mode,
                        "core_id": strategy_id,
                        "core_name_zh": indicator_name_zh,
                        "core_family": indicator_family,
                        "indicator_id": strategy_id,
                        "indicator_name_zh": indicator_name_zh,
                        "indicator_family": indicator_family,
                        "rule_key": rule_key,
                        "rule_label_zh": rule_label_zh,
                        "params": params,
                        "alpha_vs_spot": long_alpha_vs_spot,
                        "metrics": dict(long_metrics),
                    }
                )
            if not long_passes_objective:
                underperform_spot_rejected += 1
                rejected_examples.append(
                    {
                        "reason": "underperform_spot",
                        "signal_source": strategy_mode,
                        "strategy_mode": strategy_mode,
                        "core_id": strategy_id,
                        "core_name_zh": indicator_name_zh,
                        "core_family": indicator_family,
                        "indicator_id": strategy_id,
                        "indicator_name_zh": indicator_name_zh,
                        "indicator_family": indicator_family,
                        "rule_key": rule_key,
                        "rule_label_zh": rule_label_zh,
                        "params": params,
                        "alpha_vs_spot": long_alpha_vs_spot,
                        "metrics": dict(long_metrics),
                    }
                )
            if has_high_drawdown:
                high_drawdown_rejected += 1
                rejected_examples.append(
                    {
                        "reason": "high_drawdown",
                        "signal_source": strategy_mode,
                        "strategy_mode": strategy_mode,
                        "core_id": strategy_id,
                        "core_name_zh": indicator_name_zh,
                        "core_family": indicator_family,
                        "indicator_id": strategy_id,
                        "indicator_name_zh": indicator_name_zh,
                        "indicator_family": indicator_family,
                        "rule_key": rule_key,
                        "rule_label_zh": rule_label_zh,
                        "params": params,
                        "alpha_vs_spot": long_alpha_vs_spot,
                        "metrics": dict(long_metrics),
                    }
                )

            long_rows.append(
                {
                    "signal_source": strategy_mode,
                    "strategy_mode": strategy_mode,
                    "core_id": strategy_id,
                    "core_name_zh": indicator_name_zh,
                    "core_family": indicator_family,
                    "indicator_id": strategy_id,
                    "indicator_name_zh": indicator_name_zh,
                    "indicator_family": indicator_family,
                    "rule_key": rule_key,
                    "rule_label_zh": rule_label_zh,
                    "params": params,
                    "rule_complexity_score": rule_complexity_score,
                    "objective_margin_vs_spot": long_alpha_vs_spot,
                    "stability_penalty": long_stability_penalty,
                    "credibility_penalty": long_credibility_penalty,
                    **dict(long_metrics),
                }
            )

            if not cfg.optimization_long_only:
                inverse_entry, inverse_exit = build_inverse_signals(long_entry=long_entry, long_exit=long_exit)
                if gate_mode == "gated":
                    inverse_entry = (
                        inverse_entry
                        & (oracle_window <= -abs(oracle_entry_threshold))
                        & (confidence_window >= confidence_threshold)
                    ).fillna(False)
                inverse_metrics = _compute_strategy_metrics(
                    close=close_window,
                    entry=inverse_entry,
                    exit_=inverse_exit,
                    friction_bps=cfg.friction_bps,
                )
                inverse_alpha_vs_spot = float(inverse_metrics["friction_adjusted_return"] - benchmark_buy_hold_return)
                inverse_credibility_penalty = _estimate_credibility_penalty(
                    trades=int(inverse_metrics["trades"]),
                    window_trade_floor=window_trade_floor,
                    win_rate=float(inverse_metrics["win_rate"]),
                    max_drawdown=float(inverse_metrics["max_drawdown"]),
                    params_count=len(params),
                )
                if int(inverse_metrics["trades"]) <= 0:
                    continue
                inverse_stability_penalty = float(
                    np.clip(
                        0.70 * (abs(min(float(inverse_metrics["max_drawdown"]), 0.0)) / 0.35)
                        + 0.30 * inverse_credibility_penalty,
                        0.0,
                        1.0,
                    )
                )
                inverse_rows.append(
                    {
                        "signal_source": strategy_mode,
                        "strategy_mode": strategy_mode,
                        "core_id": strategy_id,
                        "core_name_zh": indicator_name_zh,
                        "core_family": indicator_family,
                        "indicator_id": strategy_id,
                        "indicator_name_zh": indicator_name_zh,
                        "indicator_family": indicator_family,
                        "rule_key": rule_key,
                        "rule_label_zh": rule_label_zh,
                        "params": params,
                        "rule_complexity_score": rule_complexity_score,
                        "objective_margin_vs_spot": inverse_alpha_vs_spot,
                        "stability_penalty": inverse_stability_penalty,
                        "credibility_penalty": inverse_credibility_penalty,
                        **dict(inverse_metrics),
                    }
                )

        long_scored = _prioritize_objective_candidates(
            candidates=_score_candidates(long_rows),
            benchmark_buy_hold_return=benchmark_buy_hold_return,
            objective_mode=cfg.objective_mode,
        )
        inverse_scored = (
            _prioritize_objective_candidates(
                candidates=_score_candidates(inverse_rows),
                benchmark_buy_hold_return=benchmark_buy_hold_return,
                objective_mode=cfg.objective_mode,
            )
            if not cfg.optimization_long_only
            else []
        )
        credible_long = [
            candidate
            for candidate in long_scored
            if (
                int(candidate["metrics"]["trades"]) > 0
                and float(candidate.get("credibility_penalty", 1.0)) <= cfg.credible_candidate_max_penalty
            )
        ]
        credible_inverse = [
            candidate
            for candidate in inverse_scored
            if (
                int(candidate["metrics"]["trades"]) > 0
                and float(candidate.get("credibility_penalty", 1.0)) <= cfg.credible_candidate_max_penalty
            )
        ]
        insufficient = len(credible_long) == 0 if cfg.optimization_long_only else (len(credible_long) == 0 and len(credible_inverse) == 0)

        rejected_examples.sort(key=lambda item: float(item["alpha_vs_spot"]))
        top_rejected_examples = [
            {
                "reason": str(item["reason"]),
                "signal_source": str(item.get("signal_source", strategy_mode)),
                "strategy_mode": str(item.get("strategy_mode", strategy_mode)),
                "core_id": str(item.get("core_id", strategy_id)),
                "core_name_zh": str(item.get("core_name_zh", indicator_name_zh)),
                "core_family": str(item.get("core_family", indicator_family)),
                "indicator_id": str(item["indicator_id"]),
                "indicator_name_zh": str(item["indicator_name_zh"]),
                "indicator_family": str(item["indicator_family"]),
                "rule_key": str(item["rule_key"]),
                "rule_label_zh": str(item["rule_label_zh"]),
                "params": dict(item["params"]),
                "alpha_vs_spot": float(item["alpha_vs_spot"]),
                "metrics": StrategyMetrics(**item["metrics"]),
            }
            for item in rejected_examples[:3]
        ]
        kept_candidates = max(0, int(evaluated_candidates - low_credibility_rejected - underperform_spot_rejected - high_drawdown_rejected))
        rule_competition: RuleCompetition = RuleCompetition(
            total_candidates=int(evaluated_candidates),
            kept_candidates=kept_candidates,
            rejected_breakdown={
                "low_trades": int(low_credibility_rejected),  # legacy key: now maps to low credibility.
                "low_credibility": int(low_credibility_rejected),
                "underperform_spot": int(underperform_spot_rejected),
                "high_drawdown": int(high_drawdown_rejected),
            },
            top_rejected_examples=top_rejected_examples,
        )

        best_long = long_scored[0] if long_scored else None
        best_inverse = inverse_scored[0] if inverse_scored else None
        best_long_alpha_vs_spot = (
            float(best_long["metrics"]["friction_adjusted_return"] - benchmark_buy_hold_return)
            if best_long is not None
            else None
        )
        best_inverse_alpha_vs_spot = (
            float(best_inverse["metrics"]["friction_adjusted_return"] - benchmark_buy_hold_return)
            if best_inverse is not None
            else None
        )
        best_long_passes_objective = (
            _passes_objective(
                friction_adjusted_return=best_long["metrics"]["friction_adjusted_return"],
                benchmark_buy_hold_return=benchmark_buy_hold_return,
                objective_mode=cfg.objective_mode,
            )
            if best_long is not None
            else False
        )
        best_inverse_passes_objective = (
            _passes_objective(
                friction_adjusted_return=best_inverse["metrics"]["friction_adjusted_return"],
                benchmark_buy_hold_return=benchmark_buy_hold_return,
                objective_mode=cfg.objective_mode,
            )
            if best_inverse is not None
            else False
        )

        signal_frequency: SignalFrequency | None = None
        event_samples: list[EventSampleRef] = []
        no_lookahead_audit: NoLookaheadAudit | None = None
        feature_weight_profile: FeatureWeightProfile | None = None
        top_features: list[FeatureContributionRow] = []
        prune_candidates: list[FeaturePruningRow] = []
        family_contribution: dict[str, float] = {}
        if best_long is not None:
            best_entry, best_exit = _build_strategy_signals(
                strategy_mode=strategy_mode,
                strategy_id=strategy_id,
                close=close_window,
                high=high_window,
                low=low_window,
                feature_window=feature_window,
                rule_key=str(best_long["rule_key"]),
                params=dict(best_long["params"]),
            )
            best_entry = _coerce_bool_series(best_entry, close_window.index)
            best_exit = _coerce_bool_series(best_exit, close_window.index)
            if gate_mode == "gated":
                best_entry = (
                    best_entry
                    & (oracle_window >= oracle_entry_threshold)
                    & (confidence_window >= confidence_threshold)
                ).fillna(False)

            top_features, prune_candidates, family_contribution = _compute_feature_diagnostics(
                feature_window=feature_window,
                close_window=close_window,
                entry_mask=best_entry,
            )

            signal_frequency = _extract_signal_frequency(best_entry)
            trade_events = _derive_trade_events(
                close=close_window,
                entry=best_entry,
                exit_=best_exit,
                friction_bps=cfg.friction_bps,
            )
            event_samples = _select_event_samples(trade_events)
            feature_weight_profile = _compute_feature_weight_profile(
                fusion_components=fusion_components_window,
                entry=best_entry,
                feature_contributions=top_features,
                prune_candidates=prune_candidates,
                family_contribution=family_contribution,
            )
            no_lookahead_audit = NoLookaheadAudit(
                position_shift_bars=1,
                feature_lag_bars=0,
                htf_confirmed_only=True,
                causality_perturbation_pass=_run_causality_perturbation_check(
                    close=close_window,
                    high=high_window,
                    low=low_window,
                    feature_window=feature_window,
                    fusion_window=oracle_window,
                    gate_mode=gate_mode,
                    indicator_id=strategy_id,
                    rule_key=str(best_long["rule_key"]),
                    params=dict(best_long["params"]),
                    strategy_mode=strategy_mode,
                ),
            )

        window_results.append(
            OptimizationWindowResult(
                window=window_mode,
                start_utc=window_start.isoformat(),
                end_utc=window_end.isoformat(),
                window_trade_floor=window_trade_floor,
                benchmark_buy_hold_return=benchmark_buy_hold_return,
                best_long=best_long,
                best_inverse=best_inverse,
                top_long_candidates=long_scored[:5],
                top_inverse_candidates=inverse_scored[:5],
                best_long_alpha_vs_spot=best_long_alpha_vs_spot,
                best_inverse_alpha_vs_spot=best_inverse_alpha_vs_spot,
                best_long_passes_objective=best_long_passes_objective,
                best_inverse_passes_objective=best_inverse_passes_objective,
                insufficient_statistical_significance=insufficient,
                evaluated_candidates=evaluated_candidates,
                rule_competition=rule_competition,
                signal_frequency=signal_frequency,
                event_samples=event_samples,
                no_lookahead_audit=no_lookahead_audit,
                feature_weight_profile=feature_weight_profile,
                oracle_threshold=oracle_entry_threshold,
                confidence_threshold=confidence_threshold,
            )
        )

    return TimeframeOptimizationResult(
        symbol=symbol,
        timeframe=timeframe,
        gate_mode=gate_mode,
        strategy_mode=strategy_mode,
        core_id=strategy_id,
        core_name_zh=indicator_name_zh,
        core_family=indicator_family,
        indicator_id=strategy_id,
        indicator_name_zh=indicator_name_zh,
        indicator_family=indicator_family,
        windows=window_results,
    )


def optimize_rsi_for_symbol_timeframe(
    price_frame: pd.DataFrame,
    feature_set_1m: pd.DataFrame,
    cfg: EngineConfig,
    symbol: str,
    timeframe: str,
    gate_mode: str,
) -> TimeframeOptimizationResult:
    return optimize_single_indicator_for_symbol_timeframe(
        price_frame=price_frame,
        feature_set_1m=feature_set_1m,
        cfg=cfg,
        symbol=symbol,
        timeframe=timeframe,
        gate_mode=gate_mode,
        indicator_id="rsi",
    )


def optimize_signal_core_for_symbol_timeframe(
    price_frame: pd.DataFrame,
    feature_set_1m: pd.DataFrame,
    cfg: EngineConfig,
    symbol: str,
    timeframe: str,
    gate_mode: str,
    core_id: str,
) -> TimeframeOptimizationResult:
    return optimize_single_indicator_for_symbol_timeframe(
        price_frame=price_frame,
        feature_set_1m=feature_set_1m,
        cfg=cfg,
        symbol=symbol,
        timeframe=timeframe,
        gate_mode=gate_mode,
        indicator_id=core_id,
    )
