from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from .aggregate import RESAMPLE_RULES, aggregate_timeframes
from .config import EngineConfig
from .feature_cores import build_feature_core_signals
from .features import apply_winsor_bounds, build_feature_set, fit_winsor_bounds
from .jsonio import write_json_atomic
from .meta_labeling import MetaLabelConfig, run_meta_label_veto
from .optimization import build_fusion_components
from .single_indicators import build_indicator_signals
from .storage import load_latest_partitioned_parquet
from .types import TimeframeOptimizationResult

WINDOW_ORDER = {"all": 0, "360d": 1, "90d": 2, "30d": 3}
WINDOW_SELECTION_WEIGHT = {"all": 1.0, "360d": 0.85, "90d": 0.65, "30d": 0.50}
STRICTNESS_THRESHOLDS: dict[str, dict[str, float]] = {
    "recovery": {
        "wf_pass_rate_min": 0.35,
        "cv_pass_rate_min": 0.30,
        "pbo_max": 0.60,
        "dsr_min": -1.80,
        "friction_robustness_min": 0.15,
        "final_score_min": 0.30,
    },
    "institutional": {
        "wf_pass_rate_min": 0.50,
        "cv_pass_rate_min": 0.45,
        "pbo_max": 0.75,
        "dsr_min": -2.00,
        "friction_robustness_min": 0.00,
        "final_score_min": 0.45,
    },
    "balanced": {
        "wf_pass_rate_min": 0.50,
        "cv_pass_rate_min": 0.45,
        "pbo_max": 0.35,
        "dsr_min": -0.25,
        "friction_robustness_min": 0.35,
        "final_score_min": 0.45,
    },
    "fast": {
        "wf_pass_rate_min": 0.40,
        "cv_pass_rate_min": 0.35,
        "pbo_max": 0.50,
        "dsr_min": -0.50,
        "friction_robustness_min": 0.25,
        "final_score_min": 0.35,
    },
}


def _parse_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean string.")


def _serialize_json(payload: object, output_path: Path) -> None:
    write_json_atomic(payload, output_path)


def _safe_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        out = float(value)
    except Exception:
        return default
    if not math.isfinite(out):
        return default
    return out


def _coerce_bool_series(value: object, index: pd.DatetimeIndex) -> pd.Series:
    if isinstance(value, pd.Series):
        return value.reindex(index).fillna(False).astype(bool)
    return pd.Series(np.asarray(value, dtype=bool), index=index, dtype=bool)


def _window_sort_key(window_name: str) -> tuple[int, str]:
    return (WINDOW_ORDER.get(window_name, 999), window_name)


def _to_meta_label_config(cfg: EngineConfig) -> MetaLabelConfig:
    model = str(cfg.meta_label_model).strip().lower()
    objective = str(cfg.meta_label_objective).strip().lower()
    if model != "logreg":
        raise ValueError(f"Unsupported meta label model: {cfg.meta_label_model}")
    if objective != "classification_binary":
        raise ValueError("Regression objective is forbidden for phase-1 meta-label pipeline.")
    return MetaLabelConfig(
        enabled=bool(cfg.meta_label_enabled),
        model=model,
        objective=objective,
        penalty=str(cfg.meta_label_penalty).strip().lower(),
        c=float(cfg.meta_label_c),
        max_iter=int(cfg.meta_label_max_iter),
        class_weight=str(cfg.meta_label_class_weight).strip().lower(),
        tp_mult=float(cfg.meta_label_tp_mult),
        sl_mult=float(cfg.meta_label_sl_mult),
        vertical_horizon_bars=int(cfg.meta_label_vertical_horizon_bars),
        vol_window=int(cfg.meta_label_vol_window),
        min_events=int(cfg.meta_label_min_events),
        threshold_min=float(cfg.meta_label_threshold_min),
        threshold_max=float(cfg.meta_label_threshold_max),
        threshold_step=float(cfg.meta_label_threshold_step),
        precision_floor=float(cfg.meta_label_precision_floor),
        threshold_objective=str(cfg.meta_label_threshold_objective).strip().lower(),
        prob_threshold_fallback=float(cfg.meta_label_prob_threshold_fallback),
        feature_cap=int(cfg.meta_label_feature_cap),
        feature_allowlist=tuple(str(item) for item in cfg.meta_label_feature_allowlist),
        cpcv_splits=int(cfg.meta_label_cpcv_splits),
        cpcv_test_groups=int(cfg.meta_label_cpcv_test_groups),
        cpcv_purge_bars=int(cfg.meta_label_cpcv_purge_bars),
        cpcv_embargo_bars=int(cfg.meta_label_cpcv_embargo_bars),
        cpcv_max_combinations=int(cfg.meta_label_cpcv_max_combinations),
    )


def _compute_buy_hold_return(close: pd.Series) -> float:
    if close.shape[0] < 2:
        return 0.0
    start = _safe_float(close.iloc[0])
    end = _safe_float(close.iloc[-1])
    if abs(start) < 1e-12:
        return 0.0
    return float(end / start - 1.0)


def _compute_position_and_returns(
    close: pd.Series,
    entry: pd.Series,
    exit_: pd.Series,
    friction_bps: int,
) -> tuple[pd.Series, pd.Series]:
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
    raw_returns = shifted_position * raw_change

    turnover = np.abs(np.diff(np.concatenate(([0.0], position_arr))))
    costs = turnover * (float(friction_bps) / 10_000.0)
    net_returns = raw_returns - costs
    return pd.Series(position_arr, index=index, dtype="float64"), pd.Series(net_returns, index=index, dtype="float64")


def _compute_metrics(close: pd.Series, entry: pd.Series, exit_: pd.Series, friction_bps: int) -> dict[str, float | int]:
    position, net_returns = _compute_position_and_returns(close=close, entry=entry, exit_=exit_, friction_bps=friction_bps)
    net_arr = net_returns.to_numpy(dtype="float64", copy=False)
    pos_arr = position.to_numpy(dtype="float64", copy=False)
    if net_arr.size == 0:
        return {
            "friction_adjusted_return": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "trades": 0,
            "sharpe": 0.0,
            "trade_sharpe": 0.0,
        }

    equity = np.cumprod(1.0 + net_arr)
    running_max = np.maximum.accumulate(equity)
    drawdown = np.where(running_max > 0.0, (equity / running_max) - 1.0, 0.0)

    transitions = np.diff(np.concatenate(([0.0], pos_arr, [0.0])))
    entry_idx = np.where(transitions > 0.0)[0]
    exit_idx = np.where(transitions < 0.0)[0] - 1
    trades = int(min(entry_idx.shape[0], exit_idx.shape[0]))
    if trades > 0:
        entry_idx = entry_idx[:trades]
        exit_idx = exit_idx[:trades]
        start_equity = np.where(entry_idx > 0, equity[entry_idx - 1], 1.0)
        end_equity = equity[exit_idx]
        trade_ret = np.where(np.abs(start_equity) > 1e-12, (end_equity / start_equity) - 1.0, 0.0)
        win_rate = float(np.mean(trade_ret > 0.0))
        trade_std = float(np.std(trade_ret))
        if trade_std <= 1e-12:
            trade_sharpe = 0.0
        else:
            trade_sharpe = float(np.mean(trade_ret) / trade_std) * math.sqrt(float(trades))
    else:
        win_rate = 0.0
        trade_sharpe = 0.0

    std = float(np.std(net_arr))
    if std <= 1e-12:
        sharpe = 0.0
    else:
        sharpe = float(np.mean(net_arr) / std) * math.sqrt(365.0 * 24.0 * 60.0)

    return {
        "friction_adjusted_return": float(equity[-1] - 1.0),
        "max_drawdown": float(np.min(drawdown)) if drawdown.size > 0 else 0.0,
        "win_rate": win_rate,
        "trades": trades,
        "sharpe": sharpe,
        "trade_sharpe": trade_sharpe,
    }


def _segment_bounds(length: int, segments: int) -> list[tuple[int, int]]:
    if length <= 0 or segments <= 0:
        return []
    bounds = np.linspace(0, length, num=segments + 1, dtype=int)
    out: list[tuple[int, int]] = []
    for i in range(segments):
        start = int(bounds[i])
        end = int(bounds[i + 1])
        if end - start >= 20:
            out.append((start, end))
    return out


def _evaluate_segments(
    close: pd.Series,
    entry: pd.Series,
    exit_: pd.Series,
    segments: list[tuple[int, int]],
    friction_bps: int,
) -> tuple[float, float, int, list[float]]:
    pass_count = 0
    valid = 0
    alphas: list[float] = []
    for start, end in segments:
        close_slice = close.iloc[start:end]
        if close_slice.shape[0] < 20:
            continue
        entry_slice = entry.reindex(close_slice.index).fillna(False)
        exit_slice = exit_.reindex(close_slice.index).fillna(False)
        metrics = _compute_metrics(close=close_slice, entry=entry_slice, exit_=exit_slice, friction_bps=friction_bps)
        benchmark = _compute_buy_hold_return(close_slice)
        alpha = float(_safe_float(metrics["friction_adjusted_return"]) - benchmark)
        valid += 1
        alphas.append(alpha)
        if alpha >= 0.0:
            pass_count += 1
    if valid == 0:
        return 0.0, 0.0, 0, []
    return float(pass_count / valid), float(np.median(alphas)), valid, alphas


def _walk_forward_stats(
    close: pd.Series,
    entry: pd.Series,
    exit_: pd.Series,
    splits: int,
    friction_bps: int,
) -> tuple[float, float, int, list[float]]:
    return _evaluate_segments(
        close=close,
        entry=entry,
        exit_=exit_,
        segments=_segment_bounds(len(close), max(2, splits)),
        friction_bps=friction_bps,
    )


def _purged_cv_stats(
    close: pd.Series,
    entry: pd.Series,
    exit_: pd.Series,
    folds: int,
    purge_bars: int,
    friction_bps: int,
) -> tuple[float, float, int, list[float]]:
    base_segments = _segment_bounds(len(close), max(2, folds))
    purged_segments: list[tuple[int, int]] = []
    for start, end in base_segments:
        purged_start = start + purge_bars
        purged_end = end - purge_bars
        if purged_end - purged_start >= 20:
            purged_segments.append((purged_start, purged_end))
    return _evaluate_segments(
        close=close,
        entry=entry,
        exit_=exit_,
        segments=purged_segments,
        friction_bps=friction_bps,
    )


def _compute_pbo(alpha_samples: list[float]) -> float:
    if not alpha_samples:
        return 1.0
    failures = sum(1 for alpha in alpha_samples if alpha <= 0.0)
    return float(failures / len(alpha_samples))


def _sample_window_series(
    close: pd.Series,
    entry: pd.Series,
    exit_: pd.Series,
    step: int,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    if step <= 1 or close.shape[0] <= 2:
        return close, entry, exit_
    idx = np.arange(0, close.shape[0], step, dtype=int)
    if idx[-1] != close.shape[0] - 1:
        idx = np.append(idx, close.shape[0] - 1)
    close_s = close.iloc[idx]
    entry_s = entry.reindex(close_s.index).fillna(False)
    exit_s = exit_.reindex(close_s.index).fillna(False)
    return close_s, entry_s, exit_s


def _compute_friction_robustness(
    close: pd.Series,
    entry: pd.Series,
    exit_: pd.Series,
    stress_friction_bps: tuple[int, ...],
) -> tuple[float, dict[str, float]]:
    if not stress_friction_bps:
        return 0.0, {}
    ordered_bps = tuple(sorted(set(int(value) for value in stress_friction_bps)))
    ret_by_bps: dict[str, float] = {}
    for bps in ordered_bps:
        metrics = _compute_metrics(close=close, entry=entry, exit_=exit_, friction_bps=bps)
        ret_by_bps[str(bps)] = float(_safe_float(metrics["friction_adjusted_return"]))

    first = ret_by_bps[str(ordered_bps[0])]
    last = ret_by_bps[str(ordered_bps[-1])]
    if abs(first) < 1e-9:
        robustness = 1.0 if last >= first else max(0.0, 1.0 - abs(last - first) / 0.10)
    else:
        degradation = max(0.0, first - last)
        robustness = max(0.0, min(1.0, 1.0 - (degradation / abs(first))))
    return float(robustness), ret_by_bps


def _compute_complexity_penalty(
    *,
    params: dict[str, int | float],
    rule_key: str,
    gate_mode: str,
) -> float:
    param_count = len(params)
    param_penalty = min(1.0, float(param_count) / 8.0)
    rule_penalty = min(1.0, max(0.0, float(len(rule_key) - 8) / 24.0))
    gate_penalty = 0.50 if gate_mode == "gated" else 0.35
    return float(min(1.0, 0.70 * param_penalty + 0.20 * rule_penalty + 0.10 * gate_penalty))


def _compute_scores(
    *,
    wf_pass_rate: float,
    wf_alpha_median: float,
    cv_pass_rate: float,
    cv_alpha_median: float,
    alpha_vs_spot: float,
    max_drawdown: float,
    pbo: float,
    dsr: float,
    friction_robustness: float,
    trades: int,
    window_trade_floor: int,
    complexity_penalty: float,
) -> dict[str, float]:
    alpha_signal = float(np.clip(((wf_alpha_median + cv_alpha_median) / 2.0) / 0.10, -1.0, 1.0))
    alpha_signal_norm = float(np.clip((alpha_signal + 1.0) / 2.0, 0.0, 1.0))
    alpha_quality = float(np.clip((alpha_vs_spot + 0.05) / 0.20, 0.0, 1.0))
    stability_quality = float(np.clip(1.0 - (abs(min(max_drawdown, 0.0)) / 0.35), 0.0, 1.0))
    transferability = float(
        np.clip(
            0.40 * wf_pass_rate + 0.35 * cv_pass_rate + 0.25 * alpha_signal_norm,
            0.0,
            1.0,
        )
    )
    trade_ratio = float(min(1.0, float(trades) / max(float(window_trade_floor), 1.0)))
    pbo_score = float(np.clip(1.0 - pbo, 0.0, 1.0))
    dsr_score = float(np.clip((dsr + 1.0) / 2.0, 0.0, 1.0))
    credibility = float(np.clip(0.40 * trade_ratio + 0.25 * pbo_score + 0.20 * dsr_score + 0.15 * stability_quality, 0.0, 1.0))
    friction = float(np.clip(friction_robustness, 0.0, 1.0))
    complexity = float(np.clip(complexity_penalty, 0.0, 1.0))
    final_score = float(np.clip(0.40 * transferability + 0.30 * credibility + 0.20 * friction - 0.10 * complexity, 0.0, 1.0))
    return {
        "transferability": transferability,
        "statistical_credibility": credibility,
        "alpha_quality": alpha_quality,
        "stability_quality": stability_quality,
        "execution_cost_quality": friction,
        "friction_robustness": friction,
        "complexity_penalty": complexity,
        "final_score": final_score,
    }


def _passes_thresholds(
    *,
    strictness: str,
    wf_pass_rate: float,
    cv_pass_rate: float,
    pbo: float,
    dsr: float,
    friction_robustness: float,
    final_score: float,
) -> tuple[bool, list[str]]:
    thresholds = STRICTNESS_THRESHOLDS[strictness]
    reasons: list[str] = []
    if wf_pass_rate < thresholds["wf_pass_rate_min"]:
        reasons.append("walk_forward")
    if cv_pass_rate < thresholds["cv_pass_rate_min"]:
        reasons.append("purged_cv")
    if pbo > thresholds["pbo_max"]:
        reasons.append("pbo")
    if dsr < thresholds["dsr_min"]:
        reasons.append("dsr")
    if friction_robustness < thresholds["friction_robustness_min"]:
        reasons.append("friction")
    if final_score < thresholds["final_score_min"]:
        reasons.append("final_score")
    return (len(reasons) == 0), reasons


def _build_validation_row(
    *,
    result: TimeframeOptimizationResult,
    window: dict[str, object],
    close_window: pd.Series,
    high_window: pd.Series,
    low_window: pd.Series,
    feature_window: pd.DataFrame,
    entry_window: pd.Series,
    exit_window: pd.Series,
    cfg: EngineConfig,
    meta_cfg: MetaLabelConfig,
) -> dict[str, object]:
    best_long = window.get("best_long")
    if not isinstance(best_long, dict):
        raise ValueError("best_long is required for validation rows")

    entry_effective = _coerce_bool_series(entry_window, close_window.index)
    threshold_payload: dict[str, object] = {
        "precision_floor": float(meta_cfg.precision_floor),
        "objective": meta_cfg.threshold_objective,
        "selected": None,
        "valid_threshold_count": 0,
        "failsafe_veto_all": False,
    }
    classification_payload: dict[str, object] = {}
    cpcv_payload: dict[str, object] = {}
    meta_reason = "disabled_by_config"
    meta_events_total = 0
    labels_positive = 0
    labels_negative = 0
    label_provenance: dict[str, int] = {}
    feature_columns: list[str] = []
    coefficients: dict[str, float] = {}
    if meta_cfg.enabled:
        meta_result = run_meta_label_veto(
            close=close_window,
            high=high_window,
            low=low_window,
            entry=entry_window,
            feature_df=feature_window,
            friction_bps=cfg.friction_bps,
            cfg=meta_cfg,
        )
        entry_effective = _coerce_bool_series(meta_result.get("entry_meta"), close_window.index)
        threshold_obj = meta_result.get("threshold")
        if isinstance(threshold_obj, dict):
            threshold_payload = threshold_obj
        classification_obj = meta_result.get("classification")
        if isinstance(classification_obj, dict):
            classification_payload = classification_obj
        cpcv_obj = meta_result.get("cpcv")
        if isinstance(cpcv_obj, dict):
            cpcv_payload = cpcv_obj
        meta_reason = str(meta_result.get("reason", "unknown"))
        meta_events_total = int(meta_result.get("events_total", 0) or 0)
        labels_positive = int(meta_result.get("labels_positive", 0) or 0)
        labels_negative = int(meta_result.get("labels_negative", 0) or 0)
        provenance_obj = meta_result.get("label_provenance")
        if isinstance(provenance_obj, dict):
            label_provenance = {str(key): int(value) for key, value in provenance_obj.items()}
        cols_obj = meta_result.get("feature_columns")
        if isinstance(cols_obj, list):
            feature_columns = [str(item) for item in cols_obj]
        coef_obj = meta_result.get("coefficients")
        if isinstance(coef_obj, dict):
            coefficients = {str(key): float(_safe_float(value)) for key, value in coef_obj.items()}

    window_metrics = _compute_metrics(
        close=close_window,
        entry=entry_effective,
        exit_=exit_window,
        friction_bps=cfg.friction_bps,
    )
    strategy_return = float(_safe_float(window_metrics.get("friction_adjusted_return")))
    benchmark_buy_hold = float(_safe_float(window.get("benchmark_buy_hold_return"), default=_compute_buy_hold_return(close_window)))
    alpha_vs_spot = float(strategy_return - benchmark_buy_hold)
    trades = int(window_metrics.get("trades", 0) or 0)
    win_rate = float(_safe_float(window_metrics.get("win_rate")))
    max_drawdown = float(_safe_float(window_metrics.get("max_drawdown")))
    entry_raw_count = int(entry_window.sum())
    entry_meta_count = int(entry_effective.sum())

    close_eval, entry_eval, exit_eval = _sample_window_series(
        close=close_window,
        entry=entry_effective,
        exit_=exit_window,
        step=max(1, int(cfg.validation_sample_step)),
    )
    eval_metrics = _compute_metrics(close=close_eval, entry=entry_eval, exit_=exit_eval, friction_bps=cfg.friction_bps)

    wf_pass_rate, wf_alpha_median, wf_segments, wf_alphas = _walk_forward_stats(
        close=close_eval,
        entry=entry_eval,
        exit_=exit_eval,
        splits=cfg.validation_walk_forward_splits,
        friction_bps=cfg.friction_bps,
    )
    cv_pass_rate, cv_alpha_median, cv_segments, cv_alphas = _purged_cv_stats(
        close=close_eval,
        entry=entry_eval,
        exit_=exit_eval,
        folds=cfg.validation_cv_folds,
        purge_bars=cfg.validation_purge_bars,
        friction_bps=cfg.friction_bps,
    )

    pbo = _compute_pbo(wf_alphas + cv_alphas)
    trials = max(1, int(window.get("evaluated_candidates", 1) or 1))
    trade_sharpe = float(_safe_float(eval_metrics.get("trade_sharpe", 0.0)))
    dsr_penalty = math.sqrt((2.0 * math.log(max(2, trials))) / max(1.0, float(trades)))
    dsr = float(trade_sharpe - dsr_penalty)
    friction_robustness, stress_returns = _compute_friction_robustness(
        close=close_eval,
        entry=entry_eval,
        exit_=exit_eval,
        stress_friction_bps=cfg.validation_stress_friction_bps,
    )

    params = best_long.get("params", {})
    if not isinstance(params, dict):
        params = {}
    complexity_penalty = _compute_complexity_penalty(
        params=params,
        rule_key=str(best_long.get("rule_key", "")),
        gate_mode=str(result.get("gate_mode", "gated")),
    )
    window_trade_floor = int(window.get("window_trade_floor", cfg.trade_floor) or cfg.trade_floor)
    scores = _compute_scores(
        wf_pass_rate=wf_pass_rate,
        wf_alpha_median=wf_alpha_median,
        cv_pass_rate=cv_pass_rate,
        cv_alpha_median=cv_alpha_median,
        alpha_vs_spot=alpha_vs_spot,
        max_drawdown=max_drawdown,
        pbo=pbo,
        dsr=dsr,
        friction_robustness=friction_robustness,
        trades=trades,
        window_trade_floor=window_trade_floor,
        complexity_penalty=complexity_penalty,
    )
    passes_validation, failed_reasons = _passes_thresholds(
        strictness=cfg.validation_strictness,
        wf_pass_rate=wf_pass_rate,
        cv_pass_rate=cv_pass_rate,
        pbo=pbo,
        dsr=dsr,
        friction_robustness=friction_robustness,
        final_score=scores["final_score"],
    )
    if bool(meta_cfg.enabled) and bool(threshold_payload.get("failsafe_veto_all", False)):
        passes_validation = False
        failed_reasons = [*failed_reasons, "meta_precision_floor"]

    return {
        "symbol": result["symbol"],
        "timeframe": result["timeframe"],
        "gate_mode": result["gate_mode"],
        "strategy_mode": result.get("strategy_mode", best_long.get("strategy_mode", "indicator")),
        "core_id": result.get("core_id", best_long.get("core_id", result["indicator_id"])),
        "core_name_zh": result.get("core_name_zh", best_long.get("core_name_zh", result["indicator_name_zh"])),
        "core_family": result.get("core_family", best_long.get("core_family", result["indicator_family"])),
        "indicator_id": result["indicator_id"],
        "indicator_name_zh": result["indicator_name_zh"],
        "indicator_family": result["indicator_family"],
        "window": str(window["window"]),
        "window_trade_floor": window_trade_floor,
        "rule_key": str(best_long.get("rule_key", "")),
        "rule_label_zh": str(best_long.get("rule_label_zh", "")),
        "params": params,
        "evaluated_candidates": trials,
        "trades": trades,
        "win_rate": win_rate,
        "max_drawdown": max_drawdown,
        "strategy_return": strategy_return,
        "spot_return": float(benchmark_buy_hold),
        "alpha_vs_spot": alpha_vs_spot,
        "walk_forward": {
            "segments": wf_segments,
            "pass_rate": wf_pass_rate,
            "median_alpha_vs_spot": wf_alpha_median,
        },
        "purged_cv": {
            "segments": cv_segments,
            "pass_rate": cv_pass_rate,
            "median_alpha_vs_spot": cv_alpha_median,
            "purge_bars": cfg.validation_purge_bars,
        },
        "pbo": float(pbo),
        "dsr": float(dsr),
        "friction_stress": {
            "bps_returns": stress_returns,
            "robustness": float(friction_robustness),
        },
        "scores": scores,
        "entry_signals_raw": entry_raw_count,
        "entry_signals_meta": entry_meta_count,
        "meta_label": {
            "enabled": bool(meta_cfg.enabled),
            "events_total": meta_events_total,
            "labels_positive": labels_positive,
            "labels_negative": labels_negative,
            "label_provenance": label_provenance,
            "threshold": threshold_payload,
            "classification": classification_payload,
            "cpcv": cpcv_payload,
            "feature_columns": feature_columns,
            "coefficients": coefficients,
            "reason": meta_reason,
        },
        "passes_validation": bool(passes_validation),
        "failed_reasons": sorted(set(failed_reasons)),
        "source_window": {
            "start_utc": str(window.get("start_utc", "")),
            "end_utc": str(window.get("end_utc", "")),
        },
    }


def _summarize_rows(rows: list[dict[str, object]], key_name: str) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        key = str(row.get(key_name, ""))
        grouped.setdefault(key, []).append(row)

    out: list[dict[str, object]] = []
    for key in sorted(grouped.keys(), key=lambda item: _window_sort_key(item) if key_name == "window" else (item, item)):
        data = grouped[key]
        total = len(data)
        passed = sum(1 for item in data if bool(item.get("passes_validation")))
        avg_score = float(sum(_safe_float(item.get("scores", {}).get("final_score")) for item in data) / total) if total > 0 else 0.0
        avg_alpha = float(sum(_safe_float(item.get("alpha_vs_spot")) for item in data) / total) if total > 0 else 0.0
        out.append(
            {
                key_name: key,
                "total": total,
                "passed": passed,
                "pass_rate": float(passed / total) if total > 0 else 0.0,
                "avg_final_score": avg_score,
                "avg_alpha_vs_spot": avg_alpha,
            }
        )
    return out


def _summarize_meta_label(rows: list[dict[str, object]]) -> dict[str, object]:
    meta_rows: list[dict[str, object]] = []
    for row in rows:
        payload = row.get("meta_label")
        if not isinstance(payload, dict):
            continue
        if not bool(payload.get("enabled")):
            continue
        meta_rows.append(payload)

    if not meta_rows:
        return {
            "enabled": False,
            "rows_total": len(rows),
            "rows_with_meta": 0,
            "events_total": 0,
            "failsafe_veto_all_count": 0,
            "failsafe_veto_all_rate": 0.0,
            "precision_floor": 0.0,
            "classification_median": {
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
                "f05": 0.0,
                "pr_auc": 0.0,
            },
            "cpcv_median": {
                "precision_floor_compliance_rate": 0.0,
                "veto_all_rate": 0.0,
            },
        }

    precision_vals: list[float] = []
    recall_vals: list[float] = []
    f1_vals: list[float] = []
    f05_vals: list[float] = []
    pr_auc_vals: list[float] = []
    cpcv_compliance_vals: list[float] = []
    cpcv_veto_vals: list[float] = []
    failsafe_count = 0
    events_total = 0
    precision_floor = 0.0

    for payload in meta_rows:
        threshold = payload.get("threshold")
        if isinstance(threshold, dict):
            if bool(threshold.get("failsafe_veto_all", False)):
                failsafe_count += 1
            precision_floor = max(precision_floor, float(_safe_float(threshold.get("precision_floor"), 0.0)))
        events_total += int(payload.get("events_total", 0) or 0)
        classification = payload.get("classification")
        if isinstance(classification, dict):
            precision_vals.append(float(_safe_float(classification.get("precision"), 0.0)))
            recall_vals.append(float(_safe_float(classification.get("recall"), 0.0)))
            f1_vals.append(float(_safe_float(classification.get("f1"), 0.0)))
            f05_vals.append(float(_safe_float(classification.get("f05"), 0.0)))
            pr_auc_vals.append(float(_safe_float(classification.get("pr_auc"), 0.0)))
        cpcv = payload.get("cpcv")
        if isinstance(cpcv, dict):
            cpcv_compliance_vals.append(float(_safe_float(cpcv.get("precision_floor_compliance_rate"), 0.0)))
            cpcv_veto_vals.append(float(_safe_float(cpcv.get("veto_all_rate"), 0.0)))

    return {
        "enabled": True,
        "rows_total": len(rows),
        "rows_with_meta": len(meta_rows),
        "events_total": int(events_total),
        "failsafe_veto_all_count": int(failsafe_count),
        "failsafe_veto_all_rate": float(failsafe_count / max(1, len(meta_rows))),
        "precision_floor": float(precision_floor),
        "classification_median": {
            "precision": float(np.median(precision_vals)) if precision_vals else 0.0,
            "recall": float(np.median(recall_vals)) if recall_vals else 0.0,
            "f1": float(np.median(f1_vals)) if f1_vals else 0.0,
            "f05": float(np.median(f05_vals)) if f05_vals else 0.0,
            "pr_auc": float(np.median(pr_auc_vals)) if pr_auc_vals else 0.0,
        },
        "cpcv_median": {
            "precision_floor_compliance_rate": float(np.median(cpcv_compliance_vals)) if cpcv_compliance_vals else 0.0,
            "veto_all_rate": float(np.median(cpcv_veto_vals)) if cpcv_veto_vals else 0.0,
        },
    }


def _build_deploy_pool(rows: list[dict[str, object]], max_rules_per_symbol: int) -> dict[str, object]:
    passed_rows = [
        row
        for row in rows
        if bool(row.get("passes_validation")) and _safe_float(row.get("alpha_vs_spot"), default=-1.0) >= 0.0
    ]
    by_symbol: dict[str, list[dict[str, object]]] = {}
    for row in passed_rows:
        by_symbol.setdefault(str(row["symbol"]), []).append(row)

    symbols_payload: list[dict[str, object]] = []
    total_rules = 0
    for symbol in sorted(by_symbol.keys()):
        dedup: dict[tuple[str, str, str], dict[str, object]] = {}
        for row in by_symbol[symbol]:
            key = (
                str(row.get("core_id", row["indicator_id"])),
                str(row["rule_key"]),
                str(row["gate_mode"]),
            )
            current = dedup.get(key)
            if current is None or _safe_float(row["scores"]["final_score"]) > _safe_float(current["scores"]["final_score"]):
                dedup[key] = row
        ranked = sorted(
            dedup.values(),
            key=lambda item: (
                0 if str(item.get("gate_mode")) == "gated" else 1,
                _window_sort_key(str(item.get("window"))),
                -_safe_float(item.get("scores", {}).get("final_score")),
                -_safe_float(item.get("friction_stress", {}).get("robustness")),
            ),
        )
        pick_limit = max(1, int(max_rules_per_symbol))
        picked: list[dict[str, object]] = []
        seen_core_window: set[tuple[str, str]] = set()
        for item in ranked:
            core_id = str(item.get("core_id", item.get("indicator_id", "")))
            window_name = str(item.get("window", ""))
            key = (core_id, window_name)
            if key in seen_core_window:
                continue
            picked.append(item)
            seen_core_window.add(key)
            if len(picked) >= pick_limit:
                break
        if len(picked) < pick_limit:
            for item in ranked:
                if item in picked:
                    continue
                picked.append(item)
                if len(picked) >= pick_limit:
                    break
        total_rules += len(picked)
        symbols_payload.append(
            {
                "symbol": symbol,
                "rules": [
                    {
                        "rank": idx + 1,
                        "gate_mode": item["gate_mode"],
                        "window": item["window"],
                        "strategy_mode": item.get("strategy_mode", "indicator"),
                        "core_id": item.get("core_id", item["indicator_id"]),
                        "core_name_zh": item.get("core_name_zh", item["indicator_name_zh"]),
                        "core_family": item.get("core_family", item["indicator_family"]),
                        "indicator_id": item["indicator_id"],
                        "indicator_name_zh": item["indicator_name_zh"],
                        "rule_key": item["rule_key"],
                        "rule_label_zh": item["rule_label_zh"],
                        "params": item["params"],
                        "trades": item["trades"],
                        "alpha_vs_spot": item["alpha_vs_spot"],
                        "final_score": item["scores"]["final_score"],
                        "friction_robustness": item["friction_stress"]["robustness"],
                        "selection_rationale": {
                            "alpha_quality": _safe_float(item.get("scores", {}).get("alpha_quality"), 0.0),
                            "transferability": _safe_float(item.get("scores", {}).get("transferability"), 0.0),
                            "friction_robustness": _safe_float(item.get("friction_stress", {}).get("robustness"), 0.0),
                            "window_weight": float(WINDOW_SELECTION_WEIGHT.get(str(item.get("window", "")).lower(), 0.40)),
                        },
                    }
                    for idx, item in enumerate(picked)
                ],
            }
        )

    return {
        "symbols": symbols_payload,
        "total_symbols": len(symbols_payload),
        "total_rules": total_rules,
    }


def _build_failure_breakdown(
    *,
    run_id: str,
    strictness: str,
    now_utc: datetime,
    rows: list[dict[str, object]],
    deploy_payload: dict[str, object],
) -> dict[str, object]:
    reason_counts: dict[str, int] = {}
    trades_by_window: dict[str, dict[str, float | int]] = {}
    for row in rows:
        failed_reasons = row.get("failed_reasons", [])
        if isinstance(failed_reasons, list):
            for reason in failed_reasons:
                key = str(reason).strip().lower()
                if not key:
                    continue
                reason_counts[key] = int(reason_counts.get(key, 0)) + 1

        window = str(row.get("window", "unknown"))
        trades = int(row.get("trades", 0) or 0)
        slot = trades_by_window.setdefault(window, {"count": 0, "trades_total": 0})
        slot["count"] = int(slot.get("count", 0)) + 1
        slot["trades_total"] = int(slot.get("trades_total", 0)) + trades

    for window, payload in trades_by_window.items():
        count = int(payload.get("count", 0))
        trades_total = int(payload.get("trades_total", 0))
        payload["trades_avg"] = float(trades_total / count) if count > 0 else 0.0
        trades_by_window[window] = payload

    def _row_view(item: dict[str, object]) -> dict[str, object]:
        scores = item.get("scores", {})
        if not isinstance(scores, dict):
            scores = {}
        return {
            "symbol": item.get("symbol"),
            "window": item.get("window"),
            "gate_mode": item.get("gate_mode"),
            "core_id": item.get("core_id", item.get("indicator_id")),
            "rule_key": item.get("rule_key"),
            "trades": int(item.get("trades", 0) or 0),
            "alpha_vs_spot": float(_safe_float(item.get("alpha_vs_spot"), 0.0)),
            "final_score": float(_safe_float(scores.get("final_score"), 0.0)),
            "passes_validation": bool(item.get("passes_validation")),
            "failed_reasons": item.get("failed_reasons", []),
        }

    ranked_score = sorted(
        rows,
        key=lambda item: _safe_float((item.get("scores", {}) or {}).get("final_score"), 0.0),
        reverse=True,
    )
    ranked_alpha = sorted(
        rows,
        key=lambda item: _safe_float(item.get("alpha_vs_spot"), 0.0),
        reverse=True,
    )
    top_by_score = [_row_view(item) for item in ranked_score[:8]]
    top_by_alpha = [_row_view(item) for item in ranked_alpha[:8]]

    pass_count = sum(1 for item in rows if bool(item.get("passes_validation")))
    deploy_symbols = int(deploy_payload.get("total_symbols", 0) or 0)
    deploy_rules = int(deploy_payload.get("total_rules", 0) or 0)
    deploy_ready = bool(pass_count > 0 and deploy_symbols > 0 and deploy_rules > 0)
    rerun_needed = not deploy_ready

    return {
        "run_id": run_id,
        "generated_at_utc": now_utc.isoformat(),
        "strictness": strictness,
        "candidates_total": len(rows),
        "candidates_passed": pass_count,
        "failed_reason_counts": reason_counts,
        "trades_distribution_by_window": trades_by_window,
        "top_rules_by_final_score": top_by_score,
        "top_rules_by_alpha_vs_spot": top_by_alpha,
        "deploy_symbols": deploy_symbols,
        "deploy_rules": deploy_rules,
        "deploy_ready": deploy_ready,
        "rerun_needed": rerun_needed,
        "recommendation": "deploy_ready" if deploy_ready else "rerun_needed",
    }


def _write_validation_payloads(
    *,
    run_id: str,
    strictness: str,
    now_utc: datetime,
    validation_rows: list[dict[str, object]],
    cfg: EngineConfig,
    base_dir: Path,
) -> dict[str, str]:
    thresholds = STRICTNESS_THRESHOLDS[strictness]
    passed_count = sum(1 for row in validation_rows if bool(row.get("passes_validation")))
    total_count = len(validation_rows)

    validation_payload = {
        "run_id": run_id,
        "generated_at_utc": now_utc.isoformat(),
        "strictness": strictness,
        "thresholds": thresholds,
        "candidates_total": total_count,
        "candidates_passed": passed_count,
        "pass_rate": float(passed_count / total_count) if total_count > 0 else 0.0,
        "summary_by_gate_mode": _summarize_rows(validation_rows, "gate_mode"),
        "summary_by_window": _summarize_rows(validation_rows, "window"),
        "meta_label_summary": _summarize_meta_label(validation_rows),
        "rows": validation_rows,
    }
    deploy_payload = {
        "run_id": run_id,
        "generated_at_utc": now_utc.isoformat(),
        "strictness": strictness,
        "max_rules_per_symbol": int(cfg.max_deploy_rules_per_symbol),
        **_build_deploy_pool(validation_rows, max_rules_per_symbol=cfg.max_deploy_rules_per_symbol),
    }
    failure_payload = _build_failure_breakdown(
        run_id=run_id,
        strictness=strictness,
        now_utc=now_utc,
        rows=validation_rows,
        deploy_payload=deploy_payload,
    )

    validation_path = base_dir / "validation_report.json"
    deploy_path = base_dir / "deploy_pool.json"
    failure_path = base_dir / "failure_breakdown.json"
    _serialize_json(validation_payload, validation_path)
    _serialize_json(deploy_payload, deploy_path)
    _serialize_json(failure_payload, failure_path)
    return {
        "validation_report": str(validation_path),
        "deploy_pool": str(deploy_path),
        "failure_breakdown": str(failure_path),
    }


def _build_light_validation_rows(
    *,
    results: list[TimeframeOptimizationResult],
    cfg: EngineConfig,
) -> list[dict[str, object]]:
    strictness = cfg.validation_strictness if cfg.validation_strictness in STRICTNESS_THRESHOLDS else "institutional"
    rows: list[dict[str, object]] = []
    for result in results:
        gate_mode = str(result.get("gate_mode", "gated"))
        indicator_id = str(result.get("indicator_id", ""))
        indicator_name_zh = str(result.get("indicator_name_zh", indicator_id))
        indicator_family = str(result.get("indicator_family", ""))
        strategy_mode = str(result.get("strategy_mode", "indicator"))
        core_id = str(result.get("core_id", indicator_id))
        core_name_zh = str(result.get("core_name_zh", indicator_name_zh))
        core_family = str(result.get("core_family", indicator_family))
        symbol = str(result.get("symbol", ""))
        timeframe = str(result.get("timeframe", "1m"))

        windows = result.get("windows", [])
        if not isinstance(windows, list):
            continue
        for window in windows:
            if not isinstance(window, dict):
                continue
            best_long = window.get("best_long")
            if not isinstance(best_long, dict):
                continue
            metrics = best_long.get("metrics", {})
            if not isinstance(metrics, dict):
                metrics = {}
            params = best_long.get("params", {})
            if not isinstance(params, dict):
                params = {}
            rule_key = str(best_long.get("rule_key", ""))
            rule_label_zh = str(best_long.get("rule_label_zh", ""))
            trades = int(metrics.get("trades", 0) or 0)
            win_rate = float(_safe_float(metrics.get("win_rate")))
            max_drawdown = float(_safe_float(metrics.get("max_drawdown")))
            strategy_return = float(_safe_float(metrics.get("friction_adjusted_return")))
            spot_return = float(_safe_float(window.get("benchmark_buy_hold_return")))
            alpha_vs_spot = float(
                _safe_float(
                    window.get("best_long_alpha_vs_spot"),
                    default=(strategy_return - spot_return),
                )
            )
            wf_pass_rate = 1.0 if alpha_vs_spot >= 0.0 else 0.0
            cv_pass_rate = wf_pass_rate
            wf_alpha_median = alpha_vs_spot
            cv_alpha_median = alpha_vs_spot
            pbo = 0.0 if alpha_vs_spot >= 0.0 else 1.0
            dsr = float(_safe_float(metrics.get("trade_sharpe", metrics.get("sharpe", 0.0))))
            friction_robustness = 1.0
            window_trade_floor = int(window.get("window_trade_floor", cfg.trade_floor) or cfg.trade_floor)
            complexity_penalty = _compute_complexity_penalty(
                params=params,
                rule_key=rule_key,
                gate_mode=gate_mode,
            )
            scores = _compute_scores(
                wf_pass_rate=wf_pass_rate,
                wf_alpha_median=wf_alpha_median,
                cv_pass_rate=cv_pass_rate,
                cv_alpha_median=cv_alpha_median,
                alpha_vs_spot=alpha_vs_spot,
                max_drawdown=max_drawdown,
                pbo=pbo,
                dsr=dsr,
                friction_robustness=friction_robustness,
                trades=trades,
                window_trade_floor=window_trade_floor,
                complexity_penalty=complexity_penalty,
            )
            passes_validation, failed_reasons = _passes_thresholds(
                strictness=strictness,
                wf_pass_rate=wf_pass_rate,
                cv_pass_rate=cv_pass_rate,
                pbo=pbo,
                dsr=dsr,
                friction_robustness=friction_robustness,
                final_score=scores["final_score"],
            )
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "gate_mode": gate_mode,
                    "strategy_mode": strategy_mode,
                    "core_id": core_id,
                    "core_name_zh": core_name_zh,
                    "core_family": core_family,
                    "indicator_id": indicator_id,
                    "indicator_name_zh": indicator_name_zh,
                    "indicator_family": indicator_family,
                    "window": str(window.get("window", "")),
                    "window_trade_floor": window_trade_floor,
                    "rule_key": rule_key,
                    "rule_label_zh": rule_label_zh,
                    "params": params,
                    "evaluated_candidates": int(window.get("evaluated_candidates", 0) or 0),
                    "trades": trades,
                    "win_rate": win_rate,
                    "max_drawdown": max_drawdown,
                    "strategy_return": strategy_return,
                    "spot_return": spot_return,
                    "alpha_vs_spot": alpha_vs_spot,
                    "walk_forward": {
                        "segments": 1,
                        "pass_rate": wf_pass_rate,
                        "median_alpha_vs_spot": wf_alpha_median,
                    },
                    "purged_cv": {
                        "segments": 1,
                        "pass_rate": cv_pass_rate,
                        "median_alpha_vs_spot": cv_alpha_median,
                        "purge_bars": cfg.validation_purge_bars,
                    },
                    "pbo": float(pbo),
                    "dsr": float(dsr),
                    "friction_stress": {
                        "bps_returns": {str(int(cfg.friction_bps)): strategy_return},
                        "robustness": float(friction_robustness),
                    },
                    "scores": scores,
                    "entry_signals_raw": trades,
                    "entry_signals_meta": trades,
                    "meta_label": {
                        "enabled": False,
                        "events_total": 0,
                        "labels_positive": 0,
                        "labels_negative": 0,
                        "label_provenance": {},
                        "threshold": {},
                        "classification": {},
                        "cpcv": {},
                        "feature_columns": [],
                        "coefficients": {},
                        "reason": "light_mode_skipped",
                    },
                    "passes_validation": bool(passes_validation),
                    "failed_reasons": failed_reasons,
                    "source_window": {
                        "start_utc": str(window.get("start_utc", "")),
                        "end_utc": str(window.get("end_utc", "")),
                    },
                    "validation_mode": "light",
                }
            )
    rows.sort(
        key=lambda item: (
            0 if bool(item.get("passes_validation")) else 1,
            -_safe_float(item.get("scores", {}).get("final_score")),
            str(item.get("symbol")),
        )
    )
    return rows


def write_validation_artifacts(
    *,
    run_id: str,
    results: list[TimeframeOptimizationResult],
    cfg: EngineConfig,
    artifact_root: Path,
    raw_layer_root: Path,
    run_start_utc: datetime | None = None,
    run_end_utc: datetime | None = None,
) -> dict[str, str]:
    now_utc = datetime.now(timezone.utc)
    date_token = now_utc.strftime("%Y-%m-%d")
    base_dir = artifact_root / "optimization" / "single" / date_token
    strictness = cfg.validation_strictness if cfg.validation_strictness in STRICTNESS_THRESHOLDS else "institutional"
    meta_cfg = _to_meta_label_config(cfg)

    symbol_frame_cache: dict[str, pd.DataFrame] = {}
    symbol_timeframe_cache: dict[tuple[str, str], pd.DataFrame] = {}
    symbol_feature_cache: dict[str, pd.DataFrame] = {}
    signal_cache: dict[str, tuple[pd.Series, pd.Series, pd.DataFrame]] = {}

    def _load_symbol_inputs(symbol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        if symbol not in symbol_frame_cache:
            frame_1m = load_latest_partitioned_parquet(
                layer_root=raw_layer_root,
                symbol=symbol,
                timeframe="1m",
                start_utc=pd.Timestamp(run_start_utc) if run_start_utc is not None else None,
                end_utc=pd.Timestamp(run_end_utc) if run_end_utc is not None else None,
            )
            symbol_frame_cache[symbol] = frame_1m

        if symbol not in symbol_feature_cache:
            frame_1m = symbol_frame_cache[symbol]
            required_tfs = tuple(sorted(set(cfg.feature_timeframes) | {"1m"}))
            aggregated = aggregate_timeframes(df_1m=frame_1m, timeframes=required_tfs)
            htf_map = {tf: aggregated.get(tf, pd.DataFrame()) for tf in cfg.feature_timeframes}
            symbol_feature_cache[symbol] = build_feature_set(df_1m=frame_1m, htf_map=htf_map)

        return symbol_frame_cache[symbol], symbol_feature_cache[symbol]

    def _load_symbol_frame(symbol: str, timeframe: str) -> pd.DataFrame:
        if timeframe == "1m":
            frame_1m, _ = _load_symbol_inputs(symbol)
            return frame_1m
        cache_key = (symbol, timeframe)
        if cache_key in symbol_timeframe_cache:
            return symbol_timeframe_cache[cache_key]
        frame_1m, _ = _load_symbol_inputs(symbol)
        aggregated = aggregate_timeframes(df_1m=frame_1m, timeframes=(timeframe,))
        symbol_timeframe_cache[cache_key] = aggregated.get(timeframe, pd.DataFrame())
        return symbol_timeframe_cache[cache_key]

    def _align_features_for_timeframe(
        feature_set_1m: pd.DataFrame,
        timeframe: str,
        target_index: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        if feature_set_1m.empty:
            return pd.DataFrame(index=target_index.copy())
        if timeframe == "1m":
            return feature_set_1m.reindex(target_index, method="ffill").fillna(0.0)
        rule = RESAMPLE_RULES.get(timeframe)
        if rule is None:
            return feature_set_1m.reindex(target_index, method="ffill").fillna(0.0)
        feature_tf = feature_set_1m.resample(rule, label="left", closed="left").last()
        return feature_tf.reindex(target_index, method="ffill").fillna(0.0)

    def _build_signals(
        *,
        symbol: str,
        timeframe: str,
        gate_mode: str,
        signal_source: str,
        indicator_id: str,
        rule_key: str,
        params: dict[str, int | float],
        window_start_utc: pd.Timestamp | None = None,
    ) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series, pd.DataFrame]:
        params_token = json.dumps(params, sort_keys=True, ensure_ascii=True)
        start_token = window_start_utc.isoformat() if isinstance(window_start_utc, pd.Timestamp) else "none"
        cache_key = "|".join([symbol, timeframe, gate_mode, signal_source, indicator_id, rule_key, params_token, start_token])
        if cache_key in signal_cache:
            entry_cached, exit_cached, feature_cached = signal_cache[cache_key]
            frame = _load_symbol_frame(symbol, timeframe)
            return (
                frame["close"].astype("float64"),
                frame["high"].astype("float64"),
                frame["low"].astype("float64"),
                entry_cached,
                exit_cached,
                feature_cached,
            )

        frame = _load_symbol_frame(symbol, timeframe)
        _, feature_set = _load_symbol_inputs(symbol)
        close = frame["close"].astype("float64")
        high = frame["high"].astype("float64")
        low = frame["low"].astype("float64")
        aligned_features = _align_features_for_timeframe(
            feature_set_1m=feature_set,
            timeframe=timeframe,
            target_index=close.index,
        )
        if isinstance(window_start_utc, pd.Timestamp):
            train_feature_frame = aligned_features.loc[aligned_features.index < window_start_utc]
            winsor_bounds = fit_winsor_bounds(train_feature_frame) if not train_feature_frame.empty else {}
            if winsor_bounds:
                aligned_features = apply_winsor_bounds(aligned_features, bounds=winsor_bounds)
        if signal_source in {"feature_core", "feature_native"}:
            entry, exit_ = build_feature_core_signals(
                core_id=indicator_id,
                feature_df=aligned_features,
                close=close,
                rule_key=rule_key,
                params=params,
            )
        else:
            entry, exit_ = build_indicator_signals(
                indicator_id=indicator_id,
                close=close,
                high=high,
                low=low,
                rule_key=rule_key,
                params=params,
            )
        entry = _coerce_bool_series(entry, close.index)
        exit_ = _coerce_bool_series(exit_, close.index)
        if gate_mode == "gated":
            fusion_components = build_fusion_components(feature_df=aligned_features, timeframe=timeframe).reindex(close.index).fillna(0.0)
            oracle = fusion_components.get("oracle_score", fusion_components["fusion_score"]).reindex(close.index).fillna(0.0)
            confidence = fusion_components.get(
                "confidence",
                pd.Series(1.0, index=close.index, dtype="float64"),
            ).reindex(close.index).fillna(1.0)
            entry_threshold = float(oracle.quantile(cfg.gate_oracle_quantile)) if not oracle.empty else 0.0
            confidence_threshold = (
                float(np.clip(confidence.quantile(cfg.gate_confidence_quantile), 0.05, 0.95))
                if not confidence.empty
                else 0.25
            )
            entry = (entry & (oracle >= entry_threshold) & (confidence >= confidence_threshold)).fillna(False)

        signal_cache[cache_key] = (entry, exit_, aligned_features)
        return close, high, low, entry, exit_, aligned_features

    validation_rows: list[dict[str, object]] = []
    for result in results:
        symbol = str(result["symbol"])
        timeframe = str(result.get("timeframe", "1m"))
        for window in result.get("windows", []):
            best_long = window.get("best_long")
            if not isinstance(best_long, dict):
                continue
            start_utc = pd.Timestamp(str(window.get("start_utc")), tz="UTC")
            end_utc = pd.Timestamp(str(window.get("end_utc")), tz="UTC")
            params = best_long.get("params", {})
            if not isinstance(params, dict):
                params = {}
            close_full, high_full, low_full, entry_full, exit_full, feature_full = _build_signals(
                symbol=symbol,
                timeframe=timeframe,
                gate_mode=str(result["gate_mode"]),
                signal_source=str(best_long.get("signal_source", result.get("strategy_mode", "indicator"))),
                indicator_id=str(result["indicator_id"]),
                rule_key=str(best_long.get("rule_key", "")),
                params=params,
                window_start_utc=start_utc,
            )
            close_window = close_full.loc[(close_full.index >= start_utc) & (close_full.index <= end_utc)]
            if close_window.empty:
                continue
            high_window = high_full.reindex(close_window.index).ffill().bfill().fillna(close_window)
            low_window = low_full.reindex(close_window.index).ffill().bfill().fillna(close_window)
            feature_window = feature_full.reindex(close_window.index, method="ffill").fillna(0.0)
            entry_window = entry_full.reindex(close_window.index).fillna(False)
            exit_window = exit_full.reindex(close_window.index).fillna(False)
            validation_rows.append(
                _build_validation_row(
                    result=result,
                    window=window,
                    close_window=close_window,
                    high_window=high_window,
                    low_window=low_window,
                    feature_window=feature_window,
                    entry_window=entry_window,
                    exit_window=exit_window,
                    cfg=cfg,
                    meta_cfg=meta_cfg,
                )
            )

    validation_rows.sort(
        key=lambda item: (
            0 if bool(item.get("passes_validation")) else 1,
            -_safe_float(item.get("scores", {}).get("final_score")),
            str(item.get("symbol")),
        )
    )
    return _write_validation_payloads(
        run_id=run_id,
        strictness=strictness,
        now_utc=now_utc,
        validation_rows=validation_rows,
        cfg=cfg,
        base_dir=base_dir,
    )


def _find_latest_summary_path(artifact_root: Path) -> Path | None:
    base_dir = artifact_root / "optimization" / "single"
    if not base_dir.exists():
        return None
    candidates = [path for path in base_dir.glob("*/summary.json") if path.is_file()]
    if not candidates:
        return None
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


def _parse_validation_gate_modes_env() -> set[str] | None:
    raw = os.getenv("ENGINE_VALIDATION_GATE_MODES")
    if raw is None:
        return None
    values = {item.strip().lower() for item in raw.split(",") if item.strip()}
    if not values:
        return None
    allowed = {"gated", "ungated"}
    invalid = values - allowed
    if invalid:
        raise ValueError(f"ENGINE_VALIDATION_GATE_MODES contains unsupported values: {sorted(invalid)}")
    return values


def _parse_validation_max_results_env() -> int | None:
    raw = os.getenv("ENGINE_VALIDATION_MAX_RESULTS")
    if raw is None:
        return None
    value = int(raw)
    if value <= 0:
        raise ValueError("ENGINE_VALIDATION_MAX_RESULTS must be positive when set.")
    return value


def _apply_validation_result_filters(results: list[TimeframeOptimizationResult]) -> list[TimeframeOptimizationResult]:
    gate_modes = _parse_validation_gate_modes_env()
    max_results = _parse_validation_max_results_env()

    filtered = results
    if gate_modes is not None:
        filtered = [item for item in filtered if str(item.get("gate_mode", "")).lower() in gate_modes]

    if max_results is not None and len(filtered) > max_results:
        filtered = filtered[:max_results]

    return filtered


def write_validation_from_summary(
    *,
    cfg: EngineConfig,
    artifact_root: Path,
    raw_layer_root: Path,
    summary_path: Path | None = None,
    run_start_utc: datetime | None = None,
    run_end_utc: datetime | None = None,
) -> dict[str, str]:
    target_summary = summary_path or _find_latest_summary_path(artifact_root)
    if target_summary is None:
        raise FileNotFoundError("No summary.json found under optimization/single.")
    if not target_summary.exists():
        raise FileNotFoundError(f"summary.json not found: {target_summary}")

    payload = json.loads(target_summary.read_text(encoding="utf-8"))
    run_id = str(payload.get("run_id", "")).strip()
    results_by_gate = payload.get("results_by_gate_mode")
    merged_results: list[object] = []
    if isinstance(results_by_gate, dict):
        for gate_payload in results_by_gate.values():
            if isinstance(gate_payload, list):
                merged_results.extend(gate_payload)
    if merged_results:
        results_obj: object = merged_results
    else:
        results_obj = payload.get("results")
    if not run_id:
        raise ValueError(f"Invalid summary payload: missing run_id ({target_summary})")
    if not isinstance(results_obj, list):
        raise ValueError(f"Invalid summary payload: results must be list ({target_summary})")
    results = _apply_validation_result_filters(cast(list[TimeframeOptimizationResult], results_obj))
    if not results:
        raise ValueError("Validation filters removed all candidate results; adjust ENGINE_VALIDATION_* filters.")

    if _parse_bool_env("ENGINE_VALIDATION_LIGHT_MODE", False):
        now_utc = datetime.now(timezone.utc)
        strictness = cfg.validation_strictness if cfg.validation_strictness in STRICTNESS_THRESHOLDS else "institutional"
        date_token = now_utc.strftime("%Y-%m-%d")
        base_dir = artifact_root / "optimization" / "single" / date_token
        rows = _build_light_validation_rows(results=results, cfg=cfg)
        return _write_validation_payloads(
            run_id=run_id,
            strictness=strictness,
            now_utc=now_utc,
            validation_rows=rows,
            cfg=cfg,
            base_dir=base_dir,
        )

    return write_validation_artifacts(
        run_id=run_id,
        results=results,
        cfg=cfg,
        artifact_root=artifact_root,
        raw_layer_root=raw_layer_root,
        run_start_utc=run_start_utc,
        run_end_utc=run_end_utc,
    )
