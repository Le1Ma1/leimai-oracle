from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from .aggregate import aggregate_timeframes
from .config import EngineConfig
from .feature_cores import build_feature_core_signals
from .features import build_feature_set
from .optimization import build_fusion_components
from .single_indicators import build_indicator_signals
from .storage import load_latest_partitioned_parquet
from .types import TimeframeOptimizationResult

WINDOW_ORDER = {"all": 0, "360d": 1, "90d": 2, "30d": 3}
STRICTNESS_THRESHOLDS: dict[str, dict[str, float]] = {
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


def _serialize_json(payload: object, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
    entry_window: pd.Series,
    exit_window: pd.Series,
    cfg: EngineConfig,
) -> dict[str, object]:
    best_long = window.get("best_long")
    if not isinstance(best_long, dict):
        raise ValueError("best_long is required for validation rows")
    best_metrics = best_long.get("metrics", {})
    strategy_return = float(_safe_float(best_metrics.get("friction_adjusted_return")))
    benchmark_buy_hold = float(_safe_float(window.get("benchmark_buy_hold_return"), default=_compute_buy_hold_return(close_window)))
    alpha_vs_spot = float(strategy_return - benchmark_buy_hold)
    trades = int(best_metrics.get("trades", 0) or 0)
    win_rate = float(_safe_float(best_metrics.get("win_rate")))
    max_drawdown = float(_safe_float(best_metrics.get("max_drawdown")))

    close_eval, entry_eval, exit_eval = _sample_window_series(
        close=close_window,
        entry=entry_window,
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
        "passes_validation": bool(passes_validation),
        "failed_reasons": failed_reasons,
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
        picked = ranked[: max(1, int(max_rules_per_symbol))]
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
    thresholds = STRICTNESS_THRESHOLDS[strictness]

    symbol_frame_cache: dict[str, pd.DataFrame] = {}
    symbol_feature_cache: dict[str, pd.DataFrame] = {}
    signal_cache: dict[str, tuple[pd.Series, pd.Series]] = {}

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

    def _build_signals(
        *,
        symbol: str,
        gate_mode: str,
        signal_source: str,
        indicator_id: str,
        rule_key: str,
        params: dict[str, int | float],
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        params_token = json.dumps(params, sort_keys=True, ensure_ascii=True)
        cache_key = "|".join([symbol, gate_mode, signal_source, indicator_id, rule_key, params_token])
        if cache_key in signal_cache:
            entry_cached, exit_cached = signal_cache[cache_key]
            frame, _ = _load_symbol_inputs(symbol)
            return frame["close"].astype("float64"), entry_cached, exit_cached

        frame, feature_set = _load_symbol_inputs(symbol)
        close = frame["close"].astype("float64")
        high = frame["high"].astype("float64")
        low = frame["low"].astype("float64")
        if signal_source in {"feature_core", "feature_native"}:
            aligned_features = feature_set.reindex(close.index, method="ffill").fillna(0.0)
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
            aligned_features = feature_set.reindex(close.index, method="ffill").fillna(0.0)
            fusion_components = build_fusion_components(feature_df=aligned_features, timeframe="1m").reindex(close.index).fillna(0.0)
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

        signal_cache[cache_key] = (entry, exit_)
        return close, entry, exit_

    validation_rows: list[dict[str, object]] = []
    for result in results:
        symbol = str(result["symbol"])
        for window in result.get("windows", []):
            best_long = window.get("best_long")
            if not isinstance(best_long, dict):
                continue
            params = best_long.get("params", {})
            if not isinstance(params, dict):
                params = {}
            close_full, entry_full, exit_full = _build_signals(
                symbol=symbol,
                gate_mode=str(result["gate_mode"]),
                signal_source=str(best_long.get("signal_source", result.get("strategy_mode", "indicator"))),
                indicator_id=str(result["indicator_id"]),
                rule_key=str(best_long.get("rule_key", "")),
                params=params,
            )
            start_utc = pd.Timestamp(str(window.get("start_utc")), tz="UTC")
            end_utc = pd.Timestamp(str(window.get("end_utc")), tz="UTC")
            close_window = close_full.loc[(close_full.index >= start_utc) & (close_full.index <= end_utc)]
            if close_window.empty:
                continue
            entry_window = entry_full.reindex(close_window.index).fillna(False)
            exit_window = exit_full.reindex(close_window.index).fillna(False)
            validation_rows.append(
                _build_validation_row(
                    result=result,
                    window=window,
                    close_window=close_window,
                    entry_window=entry_window,
                    exit_window=exit_window,
                    cfg=cfg,
                )
            )

    validation_rows.sort(
        key=lambda item: (
            0 if bool(item.get("passes_validation")) else 1,
            -_safe_float(item.get("scores", {}).get("final_score")),
            str(item.get("symbol")),
        )
    )
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
        "rows": validation_rows,
    }
    deploy_payload = {
        "run_id": run_id,
        "generated_at_utc": now_utc.isoformat(),
        "strictness": strictness,
        "max_rules_per_symbol": int(cfg.max_deploy_rules_per_symbol),
        **_build_deploy_pool(validation_rows, max_rules_per_symbol=cfg.max_deploy_rules_per_symbol),
    }

    validation_path = base_dir / "validation_report.json"
    deploy_path = base_dir / "deploy_pool.json"
    _serialize_json(validation_payload, validation_path)
    _serialize_json(deploy_payload, deploy_path)
    return {
        "validation_report": str(validation_path),
        "deploy_pool": str(deploy_path),
    }


def _find_latest_summary_path(artifact_root: Path) -> Path | None:
    base_dir = artifact_root / "optimization" / "single"
    if not base_dir.exists():
        return None
    candidates = [path for path in base_dir.glob("*/summary.json") if path.is_file()]
    if not candidates:
        return None
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


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
    results = cast(list[TimeframeOptimizationResult], results_obj)

    return write_validation_artifacts(
        run_id=run_id,
        results=results,
        cfg=cfg,
        artifact_root=artifact_root,
        raw_layer_root=raw_layer_root,
        run_start_utc=run_start_utc,
        run_end_utc=run_end_utc,
    )
