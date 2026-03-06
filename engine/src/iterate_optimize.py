from __future__ import annotations
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from uuid import uuid4

import pandas as pd

from .aggregate import aggregate_timeframes
from .config import EngineConfig, load_config
from .feature_cores import list_supported_cores
from .features import build_feature_registry, build_feature_set
from .jsonio import load_json_retry, write_json_atomic
from .logging_setup import log_event
from .optimization import optimize_signal_core_for_symbol_timeframe
from .reporting import write_optimization_artifacts
from .storage import load_latest_partitioned_parquet
from .types import TimeframeOptimizationResult
from .universe import select_top15_universe, write_universe_snapshot
from .validation import write_validation_artifacts

PREFERRED_SYMBOL_ORDER: tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "LTCUSDT",
    "LINKUSDT",
    "BCHUSDT",
    "TRXUSDT",
    "ETCUSDT",
    "XLMUSDT",
    "EOSUSDT",
    "XMRUSDT",
    "ATOMUSDT",
)


@dataclass(frozen=True)
class IterationProfile:
    name: str
    trade_floor: int
    rsi_windows: tuple[int, ...]
    rsi_lower_bounds: tuple[int, ...]
    rsi_upper_bounds: tuple[int, ...]


ITERATION_PROFILES: tuple[IterationProfile, ...] = (
    IterationProfile(
        name="r1_baseline",
        trade_floor=100,
        rsi_windows=(14, 21),
        rsi_lower_bounds=(30, 35),
        rsi_upper_bounds=(65, 70),
    ),
    IterationProfile(
        name="r2_trade_floor_90",
        trade_floor=90,
        rsi_windows=(14, 21),
        rsi_lower_bounds=(30, 35),
        rsi_upper_bounds=(65, 70),
    ),
    IterationProfile(
        name="r3_trade_floor_80_expand_bounds",
        trade_floor=80,
        rsi_windows=(14, 21),
        rsi_lower_bounds=(25, 30, 35, 40),
        rsi_upper_bounds=(60, 65, 70, 75),
    ),
    IterationProfile(
        name="r4_trade_floor_70_expand_windows",
        trade_floor=70,
        rsi_windows=(10, 14, 21, 28),
        rsi_lower_bounds=(25, 30, 35, 40),
        rsi_upper_bounds=(60, 65, 70, 75),
    ),
)


def _clone_config_for_profile(cfg: EngineConfig, profile: IterationProfile) -> EngineConfig:
    return replace(
        cfg,
        trade_floor=profile.trade_floor,
        rsi_windows=profile.rsi_windows,
        rsi_lower_bounds=profile.rsi_lower_bounds,
        rsi_upper_bounds=profile.rsi_upper_bounds,
    )


def _list_local_raw_symbols(raw_root: Path) -> list[str]:
    if not raw_root.exists():
        return []
    available: set[str] = set()
    for symbol_dir in raw_root.glob("symbol=*"):
        name = symbol_dir.name
        if not name.startswith("symbol="):
            continue
        symbol = name.split("=", 1)[1].upper()
        tf_dir = symbol_dir / "timeframe=1m"
        if tf_dir.exists():
            available.add(symbol)
    return sorted(available)


def _resolve_symbols(cfg: EngineConfig) -> list[str]:
    if cfg.universe_symbols:
        return list(cfg.universe_symbols[: cfg.top_n])

    raw_root = cfg.data_root / "raw"
    local_symbols = _list_local_raw_symbols(raw_root)
    if local_symbols:
        local_set = set(local_symbols)
        picked: list[str] = [symbol for symbol in PREFERRED_SYMBOL_ORDER if symbol in local_set]
        for symbol in local_symbols:
            if symbol in picked:
                continue
            picked.append(symbol)
            if len(picked) >= cfg.top_n:
                break
        if len(picked) >= cfg.top_n:
            return picked[: cfg.top_n]

    universe = select_top15_universe(cfg)
    write_universe_snapshot(universe, cfg.artifact_root / "universe", datetime.now(timezone.utc).date())
    return [item.symbol for item in universe]


def _evaluate_quality(
    results: list[TimeframeOptimizationResult],
    gate_modes: tuple[str, ...],
    symbols: list[str],
    windows: tuple[str, ...],
    cores: tuple[str, ...],
    timeframes: tuple[str, ...],
) -> tuple[dict[str, dict[str, float | int]], bool]:
    expected_rows_per_gate = len(symbols) * len(cores) * max(1, len(timeframes))
    expected_window_cells_per_gate = len(symbols) * len(windows) * len(cores) * max(1, len(timeframes))
    quality: dict[str, dict[str, float | int]] = {}

    for gate_mode in gate_modes:
        gate_rows = [row for row in results if row["gate_mode"] == gate_mode]
        observed_rows = len(gate_rows)
        coverage = float(observed_rows / expected_rows_per_gate) if expected_rows_per_gate > 0 else 0.0

        insufficient_count = 0
        objective_pass_count = 0
        observed_window_cells = 0
        competitive_by_window: dict[str, int] = {window: 0 for window in windows}
        for row in gate_rows:
            observed_window_cells += len(row["windows"])
            for window in row["windows"]:
                window_name = str(window["window"])
                if bool(window.get("insufficient_statistical_significance")):
                    insufficient_count += 1
                if bool(window.get("best_long_passes_objective")):
                    objective_pass_count += 1
                if window.get("best_long") is not None:
                    competitive_by_window[window_name] = competitive_by_window.get(window_name, 0) + 1

        missing_window_cells = max(0, expected_window_cells_per_gate - observed_window_cells)
        insufficient_count += missing_window_cells
        total_window_cells = expected_window_cells_per_gate
        insufficient_rate = float(insufficient_count / total_window_cells) if total_window_cells > 0 else 1.0
        objective_pass_rate = float(objective_pass_count / total_window_cells) if total_window_cells > 0 else 0.0
        min_competitive_window = min(competitive_by_window.values()) if competitive_by_window else 0

        quality[gate_mode] = {
            "expected_rows": int(expected_rows_per_gate),
            "observed_rows": int(observed_rows),
            "expected_window_cells": int(expected_window_cells_per_gate),
            "observed_window_cells": int(observed_window_cells),
            "coverage": coverage,
            "insufficient_count": int(insufficient_count),
            "insufficient_rate": insufficient_rate,
            "objective_pass_rate": objective_pass_rate,
            "min_competitive_per_window": int(min_competitive_window),
        }

    min_competitive_target = max(4, int(round(float(len(cores)) * 0.75)))
    is_pass = all(
        float(quality[gate]["coverage"]) >= 0.99
        and float(quality[gate]["insufficient_rate"]) <= 0.90
        and float(quality[gate]["objective_pass_rate"]) >= 0.05
        and int(quality[gate]["min_competitive_per_window"]) >= min_competitive_target
        for gate in gate_modes
    )
    return quality, is_pass


def _score_quality(metrics: dict[str, dict[str, float | int]]) -> tuple[float, float, float]:
    if not metrics:
        return (0.0, 1.0, 0.0)
    coverage = min(float(item["coverage"]) for item in metrics.values())
    insuff = max(float(item["insufficient_rate"]) for item in metrics.values())
    pass_rate = min(float(item["objective_pass_rate"]) for item in metrics.values())
    return (coverage, -insuff, pass_rate)


def _write_iteration_report(artifact_root: Path, payload: dict[str, object]) -> Path:
    now = datetime.now(timezone.utc)
    out_dir = artifact_root / "optimization" / "single" / "iterations" / now.strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"iteration_{now.strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}.json"
    write_json_atomic(payload, path)
    return path


def _load_json(path: str | None) -> dict[str, object]:
    if not path:
        return {}
    candidate = Path(path)
    return load_json_retry(candidate)


def _extract_validation_metrics(
    *,
    artifacts: dict[str, str] | None,
    cfg: EngineConfig,
    symbols_count: int,
) -> dict[str, float | int | bool]:
    if not artifacts:
        return {
            "validation_candidates_total": 0,
            "validation_candidates_passed": 0,
            "validation_pass_rate": 0.0,
            "validation_median_final_score": 0.0,
            "all_window_avg_alpha_vs_spot": 0.0,
            "deploy_avg_alpha_vs_spot": 0.0,
            "deploy_total_symbols": 0,
            "deploy_total_rules": 0,
            "validation_converged": False,
            "target_deploy_symbols": max(1, int(round(float(symbols_count) * cfg.optimization_target_deploy_symbol_ratio))),
        }

    validation_payload = _load_json(artifacts.get("validation_report"))
    deploy_payload = _load_json(artifacts.get("deploy_pool"))
    summary_payload = _load_json(artifacts.get("summary"))
    rows = validation_payload.get("rows", []) if isinstance(validation_payload, dict) else []
    final_scores: list[float] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        scores = row.get("scores", {})
        if not isinstance(scores, dict):
            continue
        value = scores.get("final_score")
        try:
            final_scores.append(float(value))
        except Exception:
            continue

    candidates_total = int(validation_payload.get("candidates_total", 0)) if isinstance(validation_payload, dict) else 0
    candidates_passed = int(validation_payload.get("candidates_passed", 0)) if isinstance(validation_payload, dict) else 0
    pass_rate = float(validation_payload.get("pass_rate", 0.0)) if isinstance(validation_payload, dict) else 0.0
    median_score = float(median(final_scores)) if final_scores else 0.0
    all_window_avg_alpha = 0.0
    if isinstance(validation_payload, dict):
        summary_by_window = validation_payload.get("summary_by_window", [])
        if isinstance(summary_by_window, list):
            for item in summary_by_window:
                if not isinstance(item, dict):
                    continue
                if str(item.get("window")) != "all":
                    continue
                all_window_avg_alpha = float(item.get("avg_alpha_vs_spot", 0.0) or 0.0)
                break
    if all_window_avg_alpha == 0.0 and isinstance(summary_payload, dict):
        health = (
            summary_payload.get("executive_report", {})
            .get("window_health_by_gate", {})
            .get("gated", {})
            .get("all", {})
        )
        if isinstance(health, dict):
            all_window_avg_alpha = float(health.get("avg_strategy_return", 0.0) or 0.0) - float(
                health.get("avg_spot_return", 0.0) or 0.0
            )

    deploy_total_symbols = int(deploy_payload.get("total_symbols", 0)) if isinstance(deploy_payload, dict) else 0
    deploy_total_rules = int(deploy_payload.get("total_rules", 0)) if isinstance(deploy_payload, dict) else 0
    deploy_alpha_samples: list[float] = []
    if isinstance(deploy_payload, dict):
        for group in deploy_payload.get("symbols", []) if isinstance(deploy_payload.get("symbols"), list) else []:
            if not isinstance(group, dict):
                continue
            for rule in group.get("rules", []) if isinstance(group.get("rules"), list) else []:
                if not isinstance(rule, dict):
                    continue
                try:
                    deploy_alpha_samples.append(float(rule.get("alpha_vs_spot", 0.0) or 0.0))
                except Exception:
                    continue
    deploy_avg_alpha = float(sum(deploy_alpha_samples) / len(deploy_alpha_samples)) if deploy_alpha_samples else 0.0

    target_symbols = max(1, int(round(float(symbols_count) * cfg.optimization_target_deploy_symbol_ratio)))
    validation_converged = bool(
        pass_rate >= cfg.optimization_target_validation_pass_rate
        and all_window_avg_alpha >= cfg.optimization_target_all_window_alpha_floor
        and deploy_avg_alpha >= cfg.optimization_target_deploy_alpha_floor
        and deploy_total_symbols >= target_symbols
        and deploy_total_rules >= target_symbols
    )
    return {
        "validation_candidates_total": candidates_total,
        "validation_candidates_passed": candidates_passed,
        "validation_pass_rate": pass_rate,
        "validation_median_final_score": median_score,
        "all_window_avg_alpha_vs_spot": all_window_avg_alpha,
        "deploy_avg_alpha_vs_spot": deploy_avg_alpha,
        "deploy_total_symbols": deploy_total_symbols,
        "deploy_total_rules": deploy_total_rules,
        "validation_converged": validation_converged,
        "target_deploy_symbols": target_symbols,
    }


def _derive_round_decision(
    metrics: dict[str, dict[str, float | int]],
    validation_metrics: dict[str, float | int | bool],
    cfg: EngineConfig,
) -> dict[str, object]:
    if not metrics:
        return {
            "primary_bottleneck": "no_metrics",
            "recommended_action": "keep_profile",
            "rationale": "No quality metrics available.",
        }

    max_insufficient = max(float(item["insufficient_rate"]) for item in metrics.values())
    min_pass = min(float(item["objective_pass_rate"]) for item in metrics.values())
    min_competitive = min(int(item["min_competitive_per_window"]) for item in metrics.values())
    validation_pass_rate = float(validation_metrics.get("validation_pass_rate", 0.0))
    deploy_symbols = int(validation_metrics.get("deploy_total_symbols", 0))
    target_symbols = int(validation_metrics.get("target_deploy_symbols", 1))
    median_score = float(validation_metrics.get("validation_median_final_score", 0.0))
    deploy_avg_alpha = float(validation_metrics.get("deploy_avg_alpha_vs_spot", 0.0))
    all_window_alpha = float(validation_metrics.get("all_window_avg_alpha_vs_spot", 0.0))

    if max_insufficient > 0.90:
        return {
            "primary_bottleneck": "insufficient_rate",
            "recommended_action": "lower_trade_floor_or_expand_grid",
            "rationale": f"insufficient_rate={max_insufficient:.4f} remains above pragmatic threshold 0.90",
        }
    if validation_pass_rate < cfg.optimization_target_validation_pass_rate or median_score < 0.50:
        return {
            "primary_bottleneck": "validation_quality",
            "recommended_action": "strengthen_robustness_and_reduce_overfit",
            "rationale": (
                f"validation_pass_rate={validation_pass_rate:.4f}, "
                f"median_final_score={median_score:.4f} below convergence target"
            ),
        }
    if all_window_alpha < cfg.optimization_target_all_window_alpha_floor:
        return {
            "primary_bottleneck": "all_window_alpha",
            "recommended_action": "rebalance_entry_exit_for_long_horizon",
            "rationale": (
                f"all_window_avg_alpha={all_window_alpha:.4f} below "
                f"target={cfg.optimization_target_all_window_alpha_floor:.4f}"
            ),
        }
    if deploy_symbols < target_symbols:
        return {
            "primary_bottleneck": "deploy_coverage",
            "recommended_action": "increase_rule_diversity_per_symbol",
            "rationale": f"deploy_symbols={deploy_symbols} below target={target_symbols}",
        }
    if deploy_avg_alpha < cfg.optimization_target_deploy_alpha_floor:
        return {
            "primary_bottleneck": "deploy_alpha",
            "recommended_action": "tighten_alpha_selection_threshold",
            "rationale": (
                f"deploy_avg_alpha={deploy_avg_alpha:.4f} below "
                f"target={cfg.optimization_target_deploy_alpha_floor:.4f}"
            ),
        }
    if min_pass < 0.05:
        return {
            "primary_bottleneck": "objective_pass_rate",
            "recommended_action": "expand_rule_competition_and_relax_filter",
            "rationale": f"objective_pass_rate={min_pass:.4f} remains below target 0.05",
        }
    if min_competitive < 20:
        return {
            "primary_bottleneck": "competitive_density",
            "recommended_action": "increase_candidate_diversity",
            "rationale": f"min_competitive_per_window={min_competitive} remains sparse",
        }
    return {
        "primary_bottleneck": "none",
        "recommended_action": "keep_profile",
        "rationale": "Quality metrics are stable enough for current profile.",
    }


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _compute_objective_balance_score(
    *,
    validation_metrics: dict[str, float | int | bool],
    cfg: EngineConfig,
    symbols_count: int,
) -> float:
    pass_rate = float(validation_metrics.get("validation_pass_rate", 0.0) or 0.0)
    all_alpha = float(validation_metrics.get("all_window_avg_alpha_vs_spot", 0.0) or 0.0)
    deploy_alpha = float(validation_metrics.get("deploy_avg_alpha_vs_spot", 0.0) or 0.0)
    deploy_symbols = int(validation_metrics.get("deploy_total_symbols", 0) or 0)
    deploy_rules = int(validation_metrics.get("deploy_total_rules", 0) or 0)
    target_symbols = max(1, int(round(float(symbols_count) * cfg.optimization_target_deploy_symbol_ratio)))
    target_rules = max(1, target_symbols)

    pass_component = _clip01(pass_rate / max(cfg.optimization_target_validation_pass_rate, 1e-9))
    deploy_symbol_component = _clip01(float(deploy_symbols) / float(target_symbols))
    deploy_rule_component = _clip01(float(deploy_rules) / float(target_rules))
    all_alpha_component = _clip01(0.5 + 0.5 * ((all_alpha - cfg.optimization_target_all_window_alpha_floor) / 0.50))
    deploy_alpha_component = _clip01(0.5 + 0.5 * ((deploy_alpha - cfg.optimization_target_deploy_alpha_floor) / 0.25))

    return float(
        0.35 * pass_component
        + 0.20 * deploy_symbol_component
        + 0.15 * deploy_rule_component
        + 0.15 * all_alpha_component
        + 0.15 * deploy_alpha_component
    )


def _build_round_delta(
    *,
    current: dict[str, float | int | bool],
    previous: dict[str, float | int | bool] | None,
    current_objective_balance: float,
    previous_objective_balance: float | None,
) -> dict[str, float]:
    if previous is None:
        return {
            "validation_pass_rate": 0.0,
            "all_window_avg_alpha_vs_spot": 0.0,
            "deploy_avg_alpha_vs_spot": 0.0,
            "deploy_total_symbols": 0.0,
            "deploy_total_rules": 0.0,
            "objective_balance_score": 0.0,
        }
    return {
        "validation_pass_rate": float(current.get("validation_pass_rate", 0.0) or 0.0)
        - float(previous.get("validation_pass_rate", 0.0) or 0.0),
        "all_window_avg_alpha_vs_spot": float(current.get("all_window_avg_alpha_vs_spot", 0.0) or 0.0)
        - float(previous.get("all_window_avg_alpha_vs_spot", 0.0) or 0.0),
        "deploy_avg_alpha_vs_spot": float(current.get("deploy_avg_alpha_vs_spot", 0.0) or 0.0)
        - float(previous.get("deploy_avg_alpha_vs_spot", 0.0) or 0.0),
        "deploy_total_symbols": float(int(current.get("deploy_total_symbols", 0) or 0) - int(previous.get("deploy_total_symbols", 0) or 0)),
        "deploy_total_rules": float(int(current.get("deploy_total_rules", 0) or 0) - int(previous.get("deploy_total_rules", 0) or 0)),
        "objective_balance_score": float(current_objective_balance - float(previous_objective_balance or 0.0)),
    }


def _write_iteration_decision_log(
    artifact_root: Path,
    payload: dict[str, object],
) -> Path:
    now = datetime.now(timezone.utc)
    out_dir = artifact_root / "optimization" / "single" / "iterations" / now.strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"iteration_decision_log_{now.strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}.json"
    write_json_atomic(payload, path)
    return path


def _run_round(
    cfg: EngineConfig,
    profile: IterationProfile,
    symbols: list[str],
    round_index: int,
) -> tuple[str, list[TimeframeOptimizationResult], list[str], dict[str, str]]:
    run_cfg = _clone_config_for_profile(cfg, profile)
    run_id = f"iter_r{round_index}_{uuid4().hex[:12]}"
    strategy_ids = run_cfg.feature_cores if run_cfg.rule_engine_mode == "feature_native" else run_cfg.single_indicators
    if run_cfg.rule_engine_mode == "feature_native":
        unsupported = [item for item in strategy_ids if item not in set(list_supported_cores())]
        if unsupported:
            raise ValueError(f"Unsupported ENGINE_FEATURE_CORES values: {unsupported}")
    results: list[TimeframeOptimizationResult] = []
    feature_registry_entries: list[dict[str, object]] = []
    failures: list[str] = []
    raw_root = run_cfg.data_root / "raw"
    required_tfs = tuple(sorted(set(run_cfg.optimization_timeframes) | set(run_cfg.feature_timeframes) | {"1m"}))

    log_event(
        "ITERATION_ROUND_START",
        run_id=run_id,
        profile=profile.name,
        symbols=len(symbols),
        rule_engine_mode=run_cfg.rule_engine_mode,
        signal_cores=list(strategy_ids),
        gates=list(run_cfg.optimization_gate_modes),
        windows=list(run_cfg.optimization_windows),
        trade_floor=run_cfg.trade_floor,
        rsi_windows=list(run_cfg.rsi_windows),
        rsi_lower_bounds=list(run_cfg.rsi_lower_bounds),
        rsi_upper_bounds=list(run_cfg.rsi_upper_bounds),
    )

    for symbol in symbols:
        try:
            frame_1m = load_latest_partitioned_parquet(
                layer_root=raw_root,
                symbol=symbol,
                timeframe="1m",
                start_utc=pd.Timestamp(run_cfg.run_start_utc),
                end_utc=pd.Timestamp(run_cfg.run_end_utc),
            )
            if frame_1m.empty:
                failures.append(f"{symbol}: no_local_1m_data")
                log_event("ITERATION_SYMBOL_SKIPPED", run_id=run_id, symbol=symbol, reason="no_local_1m_data")
                continue

            aggregated = aggregate_timeframes(df_1m=frame_1m, timeframes=required_tfs)
            htf_map = {tf: aggregated.get(tf, pd.DataFrame()) for tf in run_cfg.feature_timeframes}
            feature_set = build_feature_set(df_1m=frame_1m, htf_map=htf_map)
            feature_registry_entries.extend(build_feature_registry(feature_set))

            for timeframe in run_cfg.optimization_timeframes:
                price_frame = frame_1m if timeframe == "1m" else aggregated.get(timeframe, pd.DataFrame())
                if price_frame.empty:
                    log_event(
                        "ITERATION_SYMBOL_TF_SKIPPED",
                        run_id=run_id,
                        symbol=symbol,
                        timeframe=timeframe,
                        reason="no_price_frame",
                    )
                    continue
                for core_id in strategy_ids:
                    for gate_mode in run_cfg.optimization_gate_modes:
                        result = optimize_signal_core_for_symbol_timeframe(
                            price_frame=price_frame,
                            feature_set_1m=feature_set,
                            cfg=run_cfg,
                            symbol=symbol,
                            timeframe=timeframe,
                            gate_mode=gate_mode,
                            core_id=core_id,
                        )
                        results.append(result)
                        valid_windows = sum(
                            1 for window in result["windows"] if not bool(window["insufficient_statistical_significance"])
                        )
                        log_event(
                            "ITERATION_SYMBOL_CORE_DONE",
                            run_id=run_id,
                            symbol=symbol,
                            timeframe=timeframe,
                            core_id=result["core_id"],
                            gate_mode=gate_mode,
                            windows=len(result["windows"]),
                            valid_windows=valid_windows,
                        )
        except Exception as error:
            failures.append(f"{symbol}: {error}")
            log_event("ITERATION_SYMBOL_FAILED", run_id=run_id, symbol=symbol, error=str(error))

    artifacts = write_optimization_artifacts(
        run_id=run_id,
        universe=symbols,
        results=results,
        artifact_root=run_cfg.artifact_root,
        raw_layer_root=raw_root,
        run_start_utc=run_cfg.run_start_utc,
        run_end_utc=run_cfg.run_end_utc,
        quality_targets={
            "validation_pass_rate_min": cfg.optimization_target_validation_pass_rate,
            "all_window_alpha_floor": cfg.optimization_target_all_window_alpha_floor,
            "deploy_alpha_floor": cfg.optimization_target_deploy_alpha_floor,
            "deploy_symbol_ratio_min": cfg.optimization_target_deploy_symbol_ratio,
        },
        feature_registry=feature_registry_entries,
    )
    log_event(
        "ITERATION_ROUND_END",
        run_id=run_id,
        profile=profile.name,
        results=len(results),
        failures=len(failures),
        summary=artifacts.get("summary"),
    )
    return run_id, results, failures, artifacts


def run_iterative_optimization(max_rounds: int = 4) -> int:
    cfg = load_config()
    active_cores = cfg.feature_cores if cfg.rule_engine_mode == "feature_native" else cfg.single_indicators

    symbols = _resolve_symbols(cfg)
    if len(symbols) < cfg.top_n:
        raise RuntimeError(f"Not enough symbols for iterative optimization. expected={cfg.top_n}, got={len(symbols)}")

    rounds_to_run = max(1, int(max_rounds if max_rounds > 0 else cfg.optimization_max_rounds))
    best_score: tuple[float, float, float, float, float, float, float, float] = (0.0, -1.0, 0.0, 0.0, -1.0, -1.0, 0.0, 0.0)
    best_results: list[TimeframeOptimizationResult] | None = None
    best_run_id = ""
    best_artifacts: dict[str, str] | None = None
    best_objective_balance_score = 0.0
    selected_results: list[TimeframeOptimizationResult] | None = None
    selected_artifacts: dict[str, str] | None = None
    round_reports: list[dict[str, object]] = []
    final_pass = False
    final_run_id = ""
    small_gain_streak = 0
    validation_stability_streak = 0
    prev_median_final_score: float | None = None
    prev_validation_metrics: dict[str, float | int | bool] | None = None
    prev_objective_balance: float | None = None

    for idx in range(rounds_to_run):
        profile = ITERATION_PROFILES[min(idx, len(ITERATION_PROFILES) - 1)]
        run_id, results, failures, artifacts = _run_round(cfg=cfg, profile=profile, symbols=symbols, round_index=idx + 1)

        validation_metrics: dict[str, float | int | bool] = {}
        if cfg.validation_enabled:
            validation_paths = write_validation_artifacts(
                run_id=run_id,
                results=results,
                cfg=cfg,
                artifact_root=cfg.artifact_root,
                raw_layer_root=cfg.data_root / "raw",
                run_start_utc=cfg.run_start_utc,
                run_end_utc=cfg.run_end_utc,
            )
            artifacts.update(validation_paths)
            log_event(
                "ITERATION_VALIDATION_ARTIFACT_WRITTEN",
                run_id=run_id,
                validation_report=validation_paths.get("validation_report"),
                deploy_pool=validation_paths.get("deploy_pool"),
            )
            validation_metrics = _extract_validation_metrics(artifacts=artifacts, cfg=cfg, symbols_count=len(symbols))
        objective_balance_score = _compute_objective_balance_score(
            validation_metrics=validation_metrics,
            cfg=cfg,
            symbols_count=len(symbols),
        )
        delta_vs_prev_round = _build_round_delta(
            current=validation_metrics,
            previous=prev_validation_metrics,
            current_objective_balance=objective_balance_score,
            previous_objective_balance=prev_objective_balance,
        )

        metrics, is_pass = _evaluate_quality(
            results=results,
            gate_modes=cfg.optimization_gate_modes,
            symbols=symbols,
            windows=cfg.optimization_windows,
            cores=active_cores,
            timeframes=cfg.optimization_timeframes,
        )
        quality_score = _score_quality(metrics)
        score = (
            quality_score[0],
            quality_score[1],
            quality_score[2],
            float(validation_metrics.get("validation_pass_rate", 0.0)),
            float(validation_metrics.get("all_window_avg_alpha_vs_spot", -1.0)),
            float(validation_metrics.get("deploy_avg_alpha_vs_spot", -1.0)),
            float(validation_metrics.get("validation_median_final_score", 0.0)),
            float(validation_metrics.get("deploy_total_rules", 0)),
        )
        best_validation_metrics = (
            _extract_validation_metrics(artifacts=best_artifacts, cfg=cfg, symbols_count=len(symbols))
            if best_artifacts is not None
            else {}
        )
        degraded_vs_best = bool(
            best_artifacts is not None
            and int(validation_metrics.get("validation_candidates_passed", 0))
            < int(best_validation_metrics.get("validation_candidates_passed", 0))
            and float(validation_metrics.get("deploy_avg_alpha_vs_spot", 0.0))
            < float(best_validation_metrics.get("deploy_avg_alpha_vs_spot", 0.0))
        )
        if (not degraded_vs_best) and score > best_score:
            best_score = score
            best_results = results
            best_run_id = run_id
            best_artifacts = artifacts
            best_objective_balance_score = objective_balance_score

        converged_by_validation = bool(validation_metrics.get("validation_converged", False))
        is_pass = bool(is_pass and converged_by_validation)
        validation_stability_streak = (validation_stability_streak + 1) if converged_by_validation else 0

        curr_median_final_score = float(validation_metrics.get("validation_median_final_score", 0.0))
        if prev_median_final_score is not None:
            denom = max(abs(prev_median_final_score), 1e-6)
            rel_gain = (curr_median_final_score - prev_median_final_score) / denom
            if rel_gain < 0.01:
                small_gain_streak += 1
            else:
                small_gain_streak = 0
        prev_median_final_score = curr_median_final_score

        round_reports.append(
            {
                "round_index": idx + 1,
                "profile": profile.name,
                "run_id": run_id,
                "quality_metrics": metrics,
                "validation_metrics": validation_metrics,
                "objective_balance_score": objective_balance_score,
                "delta_vs_prev_round": delta_vs_prev_round,
                "stability_streak": validation_stability_streak,
                "degraded_vs_best": degraded_vs_best,
                "decision": _derive_round_decision(metrics, validation_metrics, cfg),
                "is_pass": is_pass,
                "failures": failures,
                "artifacts": artifacts,
                "config": {
                    "trade_floor": profile.trade_floor,
                    "rsi_windows": list(profile.rsi_windows),
                    "rsi_lower_bounds": list(profile.rsi_lower_bounds),
                    "rsi_upper_bounds": list(profile.rsi_upper_bounds),
                },
            }
        )
        log_event(
            "ITERATION_QUALITY",
            run_id=run_id,
            profile=profile.name,
            quality_metrics=metrics,
            validation_metrics=validation_metrics,
            degraded_vs_best=degraded_vs_best,
            is_pass=is_pass,
        )
        prev_validation_metrics = dict(validation_metrics)
        prev_objective_balance = objective_balance_score

        final_run_id = run_id
        if is_pass:
            final_pass = True
            selected_results = results
            selected_artifacts = artifacts
            break
        if small_gain_streak >= 2:
            log_event(
                "ITERATION_STOP_SMALL_GAIN",
                run_id=run_id,
                streak=small_gain_streak,
                median_final_score=curr_median_final_score,
            )
            break

    if (not final_pass) and best_results is not None and best_run_id and best_run_id != final_run_id:
        final_run_id = best_run_id
        best_artifacts = best_artifacts
        selected_results = best_results
        selected_artifacts = best_artifacts
        log_event("ITERATION_BEST_ROUND_SELECTED", run_id=best_run_id, source_run_id=best_run_id)
    elif selected_results is None and best_results is not None:
        selected_results = best_results
        selected_artifacts = best_artifacts
        if not final_run_id:
            final_run_id = best_run_id

    decision_payload = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "final_run_id": final_run_id,
        "final_pass": final_pass,
        "final_stability_streak": validation_stability_streak,
        "stop_reason": "pass" if final_pass else ("small_gain" if small_gain_streak >= 2 else "max_rounds"),
        "round_decisions": [
            {
                "round_index": report["round_index"],
                "profile": report["profile"],
                "run_id": report["run_id"],
                "quality_metrics": report["quality_metrics"],
                "validation_metrics": report.get("validation_metrics"),
                "objective_balance_score": report.get("objective_balance_score"),
                "delta_vs_prev_round": report.get("delta_vs_prev_round"),
                "stability_streak": report.get("stability_streak"),
                "degraded_vs_best": report.get("degraded_vs_best"),
                "decision": report.get("decision"),
                "is_pass": report["is_pass"],
            }
            for report in round_reports
        ],
    }
    decision_log_path = _write_iteration_decision_log(cfg.artifact_root, decision_payload)
    if selected_artifacts is None:
        selected_artifacts = {}
    selected_artifacts["iteration_decision_log"] = str(decision_log_path)

    payload = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "max_rounds": rounds_to_run,
        "quality_gate": {
            "coverage_min": 0.99,
            "insufficient_rate_max": 0.90,
            "min_competitive_per_window": max(4, int(round(float(len(active_cores)) * 0.75))),
            "validation_pass_rate_min": cfg.optimization_target_validation_pass_rate,
            "all_window_alpha_floor": cfg.optimization_target_all_window_alpha_floor,
            "deploy_alpha_floor": cfg.optimization_target_deploy_alpha_floor,
            "deploy_symbol_ratio_min": cfg.optimization_target_deploy_symbol_ratio,
        },
        "symbols": symbols,
        "rule_engine_mode": cfg.rule_engine_mode,
        "signal_cores": list(active_cores),
        "windows": list(cfg.optimization_windows),
        "gate_modes": list(cfg.optimization_gate_modes),
        "final_pass": final_pass,
        "final_run_id": final_run_id,
        "stability_streak": validation_stability_streak,
        "final_objective_balance_score": float(round_reports[-1].get("objective_balance_score", 0.0)) if round_reports else 0.0,
        "stop_reason": "pass" if final_pass else ("small_gain" if small_gain_streak >= 2 else "max_rounds"),
        "best_round_run_id": best_run_id,
        "best_round_score": {
            "coverage": best_score[0],
            "negative_insufficient_rate": best_score[1],
            "objective_pass_rate": best_score[2],
            "validation_pass_rate": best_score[3],
            "all_window_avg_alpha_vs_spot": best_score[4],
            "deploy_avg_alpha_vs_spot": best_score[5],
            "validation_median_final_score": best_score[6],
            "deploy_total_rules": best_score[7],
            "objective_balance_score": best_objective_balance_score,
        },
        "final_artifacts": selected_artifacts,
        "round_reports": round_reports,
        "iteration_decision_log": str(decision_log_path),
    }
    report_path = _write_iteration_report(cfg.artifact_root, payload)
    log_event("ITERATION_COMPLETE", final_pass=final_pass, final_run_id=final_run_id, report=str(report_path))
    return 0
