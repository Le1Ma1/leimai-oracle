from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, cast

import pandas as pd

from .storage import load_latest_partitioned_parquet
from .types import OptimizationSummary, OptimizationWindowResult, TimeframeOptimizationResult

WINDOW_ORDER = {"all": 0, "360d": 1, "90d": 2, "30d": 3}
GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "C*": 3}


def _serialize_json(payload: object, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _window_sort_key(window: str) -> tuple[int, str]:
    return (WINDOW_ORDER.get(window, 999), window)


def _safe_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        out = float(value)
    except Exception:
        return default
    if out != out:
        return default
    return out


def _classify_grade(window: OptimizationWindowResult) -> str:
    if bool(window.get("insufficient_statistical_significance")):
        return "C*"
    best_long = window.get("best_long")
    if not best_long:
        return "C"

    trades = int(best_long["metrics"]["trades"])
    window_trade_floor = int(window.get("window_trade_floor", 100) or 100)
    mdd = _safe_float(best_long["metrics"]["max_drawdown"], default=0.0)
    alpha = _safe_float(window.get("best_long_alpha_vs_spot"), default=-1e9)
    passes = bool(window.get("best_long_passes_objective"))

    if passes and alpha >= 0.05 and mdd >= -0.35 and trades >= window_trade_floor:
        return "A"
    if passes and alpha >= 0.0 and trades >= window_trade_floor:
        return "B"
    return "C"


def _format_params(params: dict[str, int | float] | None) -> str:
    if not params:
        return "-"
    parts: list[str] = []
    for key in sorted(params.keys()):
        value = params[key]
        if isinstance(value, float):
            parts.append(f"{key}={value:.4g}")
        else:
            parts.append(f"{key}={value}")
    return ", ".join(parts)


def _build_leaderboard(results: Iterable[TimeframeOptimizationResult], metric: str) -> list[dict[str, object]]:
    if metric not in {"score", "return", "alpha"}:
        raise ValueError(f"Unsupported leaderboard metric: {metric}")

    rows: list[dict[str, object]] = []
    for result in results:
        symbol = result["symbol"]
        timeframe = result["timeframe"]
        gate_mode = result["gate_mode"]
        for window in result["windows"]:
            best = window["best_long"]
            if best is None:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "gate_mode": gate_mode,
                    "strategy_mode": result.get("strategy_mode", "indicator"),
                    "core_id": result.get("core_id", result["indicator_id"]),
                    "core_name_zh": result.get("core_name_zh", result["indicator_name_zh"]),
                    "core_family": result.get("core_family", result["indicator_family"]),
                    "window": window["window"],
                    "window_trade_floor": int(window.get("window_trade_floor", 100) or 100),
                    "grade": _classify_grade(window),
                    "benchmark_buy_hold_return": window["benchmark_buy_hold_return"],
                    "alpha_vs_spot": window["best_long_alpha_vs_spot"],
                    "passes_objective": window["best_long_passes_objective"],
                    "indicator_id": result["indicator_id"],
                    "indicator_name_zh": result["indicator_name_zh"],
                    "indicator_family": result["indicator_family"],
                    "rule_key": best["rule_key"],
                    "rule_label_zh": best["rule_label_zh"],
                    "params": best["params"],
                    "params_text": _format_params(best["params"]),
                    "score": best["score"],
                    "friction_adjusted_return": best["metrics"]["friction_adjusted_return"],
                    "max_drawdown": best["metrics"]["max_drawdown"],
                    "win_rate": best["metrics"]["win_rate"],
                    "trades": best["metrics"]["trades"],
                }
            )

    if metric == "score":
        sort_key = "score"
    elif metric == "return":
        sort_key = "friction_adjusted_return"
    else:
        sort_key = "alpha_vs_spot"
    rows.sort(key=lambda item: _safe_float(item[sort_key]), reverse=True)
    return rows[:80]


def _build_gate_window_health(
    gate_results: list[TimeframeOptimizationResult],
    universe_size: int,
) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, dict[str, OptimizationWindowResult]] = defaultdict(dict)
    for result in gate_results:
        symbol = result["symbol"]
        for window in result["windows"]:
            window_name = str(window["window"])
            current = grouped[window_name].get(symbol)
            if current is None:
                grouped[window_name][symbol] = window
                continue

            current_alpha = _safe_float(current.get("best_long_alpha_vs_spot"), default=-1e9)
            candidate_alpha = _safe_float(window.get("best_long_alpha_vs_spot"), default=-1e9)
            if candidate_alpha > current_alpha:
                grouped[window_name][symbol] = window

    out: dict[str, dict[str, float | int]] = {}
    for window_name, rows_by_symbol in grouped.items():
        rows = list(rows_by_symbol.values())
        pass_count = sum(1 for row in rows if bool(row.get("best_long_passes_objective")))
        insufficient_count = sum(1 for row in rows if bool(row.get("insufficient_statistical_significance")))
        strategy_values = [
            _safe_float(row["best_long"]["metrics"]["friction_adjusted_return"])
            for row in rows
            if row.get("best_long") is not None
        ]
        spot_values = [_safe_float(row.get("benchmark_buy_hold_return")) for row in rows]
        out[window_name] = {
            "expected_total": int(universe_size),
            "observed_total": int(len(rows)),
            "pass_count": int(pass_count),
            "pass_rate": float(pass_count / universe_size) if universe_size > 0 else 0.0,
            "insufficient_count": int(insufficient_count),
            "avg_strategy_return": float(sum(strategy_values) / len(strategy_values)) if strategy_values else 0.0,
            "avg_spot_return": float(sum(spot_values) / len(spot_values)) if spot_values else 0.0,
        }
    return dict(sorted(out.items(), key=lambda kv: _window_sort_key(kv[0])))


def _build_executive_report(
    results_by_gate_mode: dict[str, list[TimeframeOptimizationResult]],
    universe_size: int,
) -> dict[str, object]:
    gate_window_health = {
        gate_mode: _build_gate_window_health(gate_results=gate_results, universe_size=universe_size)
        for gate_mode, gate_results in results_by_gate_mode.items()
    }
    default_gate = "gated" if "gated" in gate_window_health else (next(iter(gate_window_health.keys()), "gated"))
    headline = []
    for window_name, row in gate_window_health.get(default_gate, {}).items():
        headline.append(
            {
                "window": window_name,
                "pass_rate": row["pass_rate"],
                "insufficient_count": row["insufficient_count"],
                "avg_strategy_return": row["avg_strategy_return"],
                "avg_spot_return": row["avg_spot_return"],
            }
        )
    return {
        "default_gate_mode": default_gate,
        "window_health_by_gate": gate_window_health,
        "headline_by_window": headline,
    }


def _build_delta_views(
    *,
    results_by_gate_mode: dict[str, list[TimeframeOptimizationResult]],
    executive_report: dict[str, object],
) -> dict[str, object]:
    health_by_gate = executive_report.get("window_health_by_gate", {})
    gated_health = health_by_gate.get("gated", {}) if isinstance(health_by_gate, dict) else {}
    ungated_health = health_by_gate.get("ungated", {}) if isinstance(health_by_gate, dict) else {}
    window_union = sorted(
        set(gated_health.keys()) | set(ungated_health.keys()),
        key=_window_sort_key,
    )

    gate_delta_by_window: list[dict[str, object]] = []
    for window in window_union:
        g = gated_health.get(window, {})
        u = ungated_health.get(window, {})
        g_pass = _safe_float(g.get("pass_rate"))
        u_pass = _safe_float(u.get("pass_rate"))
        g_strat = _safe_float(g.get("avg_strategy_return"))
        u_strat = _safe_float(u.get("avg_strategy_return"))
        g_spot = _safe_float(g.get("avg_spot_return"))
        u_spot = _safe_float(u.get("avg_spot_return"))
        gate_delta_by_window.append(
            {
                "window": window,
                "gated_pass_rate": g_pass,
                "ungated_pass_rate": u_pass,
                "delta_pass_rate": g_pass - u_pass,
                "gated_avg_strategy_return": g_strat,
                "ungated_avg_strategy_return": u_strat,
                "delta_avg_strategy_return": g_strat - u_strat,
                "gated_avg_alpha_proxy": g_strat - g_spot,
                "ungated_avg_alpha_proxy": u_strat - u_spot,
                "delta_avg_alpha_proxy": (g_strat - g_spot) - (u_strat - u_spot),
            }
        )

    def _collect_gate_rows(gate_mode: str) -> dict[tuple[str, str, str], dict[str, object]]:
        out: dict[tuple[str, str, str], dict[str, object]] = {}
        for result in results_by_gate_mode.get(gate_mode, []):
            symbol = str(result["symbol"])
            indicator_id = str(result["indicator_id"])
            indicator_name_zh = str(result["indicator_name_zh"])
            indicator_family = str(result["indicator_family"])
            core_id = str(result.get("core_id", indicator_id))
            core_name_zh = str(result.get("core_name_zh", indicator_name_zh))
            core_family = str(result.get("core_family", indicator_family))
            strategy_mode = str(result.get("strategy_mode", "indicator"))
            for window in result["windows"]:
                best = window.get("best_long")
                window_name = str(window["window"])
                key = (window_name, symbol, core_id)
                if best is None:
                    continue
                out[key] = {
                    "strategy_mode": strategy_mode,
                    "core_id": core_id,
                    "core_name_zh": core_name_zh,
                    "core_family": core_family,
                    "indicator_name_zh": indicator_name_zh,
                    "indicator_family": indicator_family,
                    "rule_key": str(best["rule_key"]),
                    "rule_label_zh": str(best["rule_label_zh"]),
                    "score": _safe_float(best["score"]),
                    "strategy_return": _safe_float(best["metrics"]["friction_adjusted_return"]),
                    "spot_return": _safe_float(window.get("benchmark_buy_hold_return")),
                    "alpha_vs_spot": _safe_float(window.get("best_long_alpha_vs_spot")),
                    "trades": int(best["metrics"]["trades"]),
                    "win_rate": _safe_float(best["metrics"]["win_rate"]),
                    "passes_objective": bool(window.get("best_long_passes_objective")),
                    "insufficient": bool(window.get("insufficient_statistical_significance")),
                }
        return out

    gated_rows = _collect_gate_rows("gated")
    ungated_rows = _collect_gate_rows("ungated")
    key_union = sorted(set(gated_rows.keys()) | set(ungated_rows.keys()), key=lambda item: (_window_sort_key(item[0]), item[1], item[2]))

    symbol_indicator_gate_delta: list[dict[str, object]] = []
    for window, symbol, core_id in key_union:
        g = gated_rows.get((window, symbol, core_id))
        u = ungated_rows.get((window, symbol, core_id))
        indicator_name_zh = (g or u or {}).get("indicator_name_zh", core_id)
        indicator_family = (g or u or {}).get("indicator_family", "-")
        core_name_zh = (g or u or {}).get("core_name_zh", indicator_name_zh)
        core_family = (g or u or {}).get("core_family", indicator_family)
        strategy_mode = (g or u or {}).get("strategy_mode", "indicator")
        g_alpha = _safe_float((g or {}).get("alpha_vs_spot"), default=0.0)
        u_alpha = _safe_float((u or {}).get("alpha_vs_spot"), default=0.0)
        g_score = _safe_float((g or {}).get("score"), default=0.0)
        u_score = _safe_float((u or {}).get("score"), default=0.0)
        g_return = _safe_float((g or {}).get("strategy_return"), default=0.0)
        u_return = _safe_float((u or {}).get("strategy_return"), default=0.0)
        g_trades = int((g or {}).get("trades", 0) or 0)
        u_trades = int((u or {}).get("trades", 0) or 0)
        symbol_indicator_gate_delta.append(
            {
                "window": window,
                "symbol": symbol,
                "strategy_mode": strategy_mode,
                "core_id": core_id,
                "core_name_zh": core_name_zh,
                "core_family": core_family,
                "indicator_id": core_id,
                "indicator_name_zh": indicator_name_zh,
                "indicator_family": indicator_family,
                "has_gated": g is not None,
                "has_ungated": u is not None,
                "gated": g,
                "ungated": u,
                "delta_alpha_vs_spot": g_alpha - u_alpha,
                "delta_score": g_score - u_score,
                "delta_strategy_return": g_return - u_return,
                "delta_trades": g_trades - u_trades,
            }
        )

    indicator_buckets: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"gated_alpha": [], "ungated_alpha": [], "gated_score": [], "ungated_score": []})
    for row in symbol_indicator_gate_delta:
        indicator_id = str(row["indicator_id"])
        gated_payload = row.get("gated")
        ungated_payload = row.get("ungated")
        if isinstance(gated_payload, dict):
            indicator_buckets[indicator_id]["gated_alpha"].append(_safe_float(gated_payload.get("alpha_vs_spot")))
            indicator_buckets[indicator_id]["gated_score"].append(_safe_float(gated_payload.get("score")))
        if isinstance(ungated_payload, dict):
            indicator_buckets[indicator_id]["ungated_alpha"].append(_safe_float(ungated_payload.get("alpha_vs_spot")))
            indicator_buckets[indicator_id]["ungated_score"].append(_safe_float(ungated_payload.get("score")))

    indicator_delta: list[dict[str, object]] = []
    for indicator_id in sorted(indicator_buckets.keys()):
        bucket = indicator_buckets[indicator_id]
        g_alpha = bucket["gated_alpha"]
        u_alpha = bucket["ungated_alpha"]
        g_score = bucket["gated_score"]
        u_score = bucket["ungated_score"]
        avg_g_alpha = float(sum(g_alpha) / len(g_alpha)) if g_alpha else 0.0
        avg_u_alpha = float(sum(u_alpha) / len(u_alpha)) if u_alpha else 0.0
        avg_g_score = float(sum(g_score) / len(g_score)) if g_score else 0.0
        avg_u_score = float(sum(u_score) / len(u_score)) if u_score else 0.0
        indicator_delta.append(
            {
                "indicator_id": indicator_id,
                "avg_gated_alpha": avg_g_alpha,
                "avg_ungated_alpha": avg_u_alpha,
                "delta_alpha": avg_g_alpha - avg_u_alpha,
                "avg_gated_score": avg_g_score,
                "avg_ungated_score": avg_u_score,
                "delta_score": avg_g_score - avg_u_score,
                "samples_gated": len(g_alpha),
                "samples_ungated": len(u_alpha),
            }
        )
    indicator_delta.sort(key=lambda row: _safe_float(row.get("delta_alpha")), reverse=True)

    return {
        "gate_delta_by_window": gate_delta_by_window,
        "symbol_indicator_gate_delta": symbol_indicator_gate_delta,
        "indicator_delta": indicator_delta,
    }


def _build_rank_shift_gated_vs_ungated(
    symbol_indicator_gate_delta: list[dict[str, object]],
) -> list[dict[str, object]]:
    gated_ranks: dict[tuple[str, str, str], int] = {}
    ungated_ranks: dict[tuple[str, str, str], int] = {}
    grouped_by_window: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in symbol_indicator_gate_delta:
        grouped_by_window[str(row.get("window", ""))].append(row)

    for window, rows in grouped_by_window.items():
        gated_sorted = sorted(
            [row for row in rows if isinstance(row.get("gated"), dict)],
            key=lambda item: _safe_float(cast(dict[str, object], item["gated"]).get("alpha_vs_spot"), default=-1e9),
            reverse=True,
        )
        ungated_sorted = sorted(
            [row for row in rows if isinstance(row.get("ungated"), dict)],
            key=lambda item: _safe_float(cast(dict[str, object], item["ungated"]).get("alpha_vs_spot"), default=-1e9),
            reverse=True,
        )
        for idx, row in enumerate(gated_sorted):
            gated_ranks[(window, str(row["symbol"]), str(row["indicator_id"]))] = idx + 1
        for idx, row in enumerate(ungated_sorted):
            ungated_ranks[(window, str(row["symbol"]), str(row["indicator_id"]))] = idx + 1

    out: list[dict[str, object]] = []
    for row in symbol_indicator_gate_delta:
        window = str(row.get("window", ""))
        symbol = str(row.get("symbol", ""))
        indicator_id = str(row.get("indicator_id", ""))
        key = (window, symbol, indicator_id)
        rank_gated = gated_ranks.get(key)
        rank_ungated = ungated_ranks.get(key)
        if rank_gated is None and rank_ungated is None:
            continue
        out.append(
            {
                "window": window,
                "symbol": symbol,
                "strategy_mode": row.get("strategy_mode", "indicator"),
                "core_id": row.get("core_id", indicator_id),
                "core_name_zh": row.get("core_name_zh", row.get("indicator_name_zh", indicator_id)),
                "core_family": row.get("core_family", row.get("indicator_family", "-")),
                "indicator_id": indicator_id,
                "indicator_name_zh": row.get("indicator_name_zh", indicator_id),
                "indicator_family": row.get("indicator_family", "-"),
                "rank_gated": rank_gated,
                "rank_ungated": rank_ungated,
                "rank_shift": (
                    int(rank_ungated) - int(rank_gated)
                    if rank_gated is not None and rank_ungated is not None
                    else None
                ),
                "gated_alpha_vs_spot": _safe_float((row.get("gated") or {}).get("alpha_vs_spot") if isinstance(row.get("gated"), dict) else None),
                "ungated_alpha_vs_spot": _safe_float((row.get("ungated") or {}).get("alpha_vs_spot") if isinstance(row.get("ungated"), dict) else None),
                "delta_alpha_vs_spot": _safe_float(row.get("delta_alpha_vs_spot")),
            }
        )
    out.sort(
        key=lambda item: (
            _window_sort_key(str(item.get("window", ""))),
            -abs(int(item.get("rank_shift", 0) or 0)),
            -abs(_safe_float(item.get("delta_alpha_vs_spot"))),
        )
    )
    return out


def _build_window_alpha_heatmap_payload(
    symbol_indicator_gate_delta: list[dict[str, object]],
) -> dict[str, object]:
    windows = sorted({str(row.get("window", "")) for row in symbol_indicator_gate_delta}, key=_window_sort_key)
    symbols = sorted({str(row.get("symbol", "")) for row in symbol_indicator_gate_delta})
    cores = sorted({str(row.get("core_id", row.get("indicator_id", ""))) for row in symbol_indicator_gate_delta})
    cells: list[dict[str, object]] = []
    for row in symbol_indicator_gate_delta:
        gated_payload = row.get("gated") if isinstance(row.get("gated"), dict) else {}
        ungated_payload = row.get("ungated") if isinstance(row.get("ungated"), dict) else {}
        cells.append(
            {
                "window": row.get("window"),
                "symbol": row.get("symbol"),
                "strategy_mode": row.get("strategy_mode", "indicator"),
                "core_id": row.get("core_id", row.get("indicator_id")),
                "core_name_zh": row.get("core_name_zh", row.get("indicator_name_zh")),
                "core_family": row.get("core_family", row.get("indicator_family")),
                "indicator_id": row.get("indicator_id"),
                "indicator_name_zh": row.get("indicator_name_zh"),
                "gated_alpha_vs_spot": _safe_float((gated_payload or {}).get("alpha_vs_spot")),
                "ungated_alpha_vs_spot": _safe_float((ungated_payload or {}).get("alpha_vs_spot")),
                "delta_alpha_vs_spot": _safe_float(row.get("delta_alpha_vs_spot")),
                "gated_score": _safe_float((gated_payload or {}).get("score")),
                "ungated_score": _safe_float((ungated_payload or {}).get("score")),
                "delta_score": _safe_float(row.get("delta_score")),
                "gated_passes_objective": bool((gated_payload or {}).get("passes_objective")),
                "ungated_passes_objective": bool((ungated_payload or {}).get("passes_objective")),
            }
        )
    return {
        "windows": windows,
        "symbols": symbols,
        "cores": cores,
        "indicators": cores,
        "cells": cells,
    }


def _build_indicator_competition_overview(
    symbol_indicator_gate_delta: list[dict[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for row in symbol_indicator_gate_delta:
        indicator_id = str(row.get("core_id", row.get("indicator_id", "")))
        slot = grouped.setdefault(
            indicator_id,
            {
                "strategy_mode": row.get("strategy_mode", "indicator"),
                "core_id": indicator_id,
                "core_name_zh": row.get("core_name_zh", row.get("indicator_name_zh", indicator_id)),
                "core_family": row.get("core_family", row.get("indicator_family", "-")),
                "indicator_id": indicator_id,
                "indicator_name_zh": row.get("core_name_zh", row.get("indicator_name_zh", indicator_id)),
                "indicator_family": row.get("core_family", row.get("indicator_family", "-")),
                "samples": 0,
                "gated_alpha_sum": 0.0,
                "ungated_alpha_sum": 0.0,
                "gated_pass_count": 0,
                "ungated_pass_count": 0,
                "gated_count": 0,
                "ungated_count": 0,
            },
        )
        slot["samples"] = int(slot["samples"]) + 1
        gated_payload = row.get("gated") if isinstance(row.get("gated"), dict) else None
        ungated_payload = row.get("ungated") if isinstance(row.get("ungated"), dict) else None
        if gated_payload is not None:
            slot["gated_count"] = int(slot["gated_count"]) + 1
            slot["gated_alpha_sum"] = float(slot["gated_alpha_sum"]) + _safe_float(gated_payload.get("alpha_vs_spot"))
            slot["gated_pass_count"] = int(slot["gated_pass_count"]) + (1 if bool(gated_payload.get("passes_objective")) else 0)
        if ungated_payload is not None:
            slot["ungated_count"] = int(slot["ungated_count"]) + 1
            slot["ungated_alpha_sum"] = float(slot["ungated_alpha_sum"]) + _safe_float(ungated_payload.get("alpha_vs_spot"))
            slot["ungated_pass_count"] = int(slot["ungated_pass_count"]) + (1 if bool(ungated_payload.get("passes_objective")) else 0)

    out: list[dict[str, object]] = []
    for indicator_id in sorted(grouped.keys()):
        slot = grouped[indicator_id]
        gated_count = int(slot["gated_count"])
        ungated_count = int(slot["ungated_count"])
        gated_avg_alpha = float(slot["gated_alpha_sum"]) / gated_count if gated_count > 0 else 0.0
        ungated_avg_alpha = float(slot["ungated_alpha_sum"]) / ungated_count if ungated_count > 0 else 0.0
        out.append(
            {
                "indicator_id": indicator_id,
                "indicator_name_zh": slot["indicator_name_zh"],
                "indicator_family": slot["indicator_family"],
                "samples": int(slot["samples"]),
                "gated_avg_alpha_vs_spot": gated_avg_alpha,
                "ungated_avg_alpha_vs_spot": ungated_avg_alpha,
                "delta_alpha_vs_spot": gated_avg_alpha - ungated_avg_alpha,
                "gated_pass_rate": float(slot["gated_pass_count"]) / gated_count if gated_count > 0 else 0.0,
                "ungated_pass_rate": float(slot["ungated_pass_count"]) / ungated_count if ungated_count > 0 else 0.0,
            }
        )
    out.sort(key=lambda item: _safe_float(item.get("gated_avg_alpha_vs_spot")), reverse=True)
    return out


def _build_health_dashboard(
    *,
    executive_report: dict[str, object],
    gate_modes: list[str],
    windows: list[str],
    indicator_competition_overview: list[dict[str, object]],
    quality_targets: dict[str, float] | None = None,
) -> dict[str, object]:
    health_by_gate = executive_report.get("window_health_by_gate", {})
    gate_summaries: dict[str, dict[str, object]] = {}
    for gate_mode in gate_modes:
        gate_rows = health_by_gate.get(gate_mode, {}) if isinstance(health_by_gate, dict) else {}
        pass_values: list[float] = []
        alpha_values: list[float] = []
        for window_name in windows:
            row = gate_rows.get(window_name, {}) if isinstance(gate_rows, dict) else {}
            pass_values.append(_safe_float(row.get("pass_rate")))
            alpha_values.append(_safe_float(row.get("avg_strategy_return")) - _safe_float(row.get("avg_spot_return")))
        all_row = gate_rows.get("all", {}) if isinstance(gate_rows, dict) else {}
        if not isinstance(all_row, dict):
            all_row = {}
        gate_summaries[gate_mode] = {
            "avg_pass_rate": float(sum(pass_values) / len(pass_values)) if pass_values else 0.0,
            "avg_alpha_proxy": float(sum(alpha_values) / len(alpha_values)) if alpha_values else 0.0,
            "all_window_alpha_proxy": (
                _safe_float(all_row.get("avg_strategy_return"))
                - _safe_float(all_row.get("avg_spot_return"))
            ),
        }

    top_indicators = indicator_competition_overview[:5]
    return {
        "gate_summaries": gate_summaries,
        "top_indicators": top_indicators,
        "top_cores": top_indicators,
        "window_count": len(windows),
        "targets": quality_targets or {},
    }


def _build_indicator_comparison(
    results_by_gate_mode: dict[str, list[TimeframeOptimizationResult]],
) -> list[dict[str, object]]:
    table_rows: list[dict[str, object]] = []
    for gate_mode, gate_results in results_by_gate_mode.items():
        grouped: dict[str, dict[str, list[dict[str, object]]]] = defaultdict(lambda: defaultdict(list))
        for result in gate_results:
            symbol = result["symbol"]
            for window in result["windows"]:
                best = window.get("best_long")
                if best is None:
                    continue
                grouped[str(window["window"])][symbol].append(
                    {
                        "strategy_mode": result.get("strategy_mode", "indicator"),
                        "core_id": result.get("core_id", result["indicator_id"]),
                        "core_name_zh": result.get("core_name_zh", result["indicator_name_zh"]),
                        "core_family": result.get("core_family", result["indicator_family"]),
                        "indicator_id": result["indicator_id"],
                        "indicator_name_zh": result["indicator_name_zh"],
                        "indicator_family": result["indicator_family"],
                        "rule_label_zh": best["rule_label_zh"],
                        "rule_key": best["rule_key"],
                        "params": best["params"],
                        "params_text": _format_params(best["params"]),
                        "grade": _classify_grade(window),
                        "window_trade_floor": int(window.get("window_trade_floor", 100) or 100),
                        "alpha_vs_spot": _safe_float(window.get("best_long_alpha_vs_spot")),
                        "strategy_return": _safe_float(best["metrics"]["friction_adjusted_return"]),
                        "spot_return": _safe_float(window.get("benchmark_buy_hold_return")),
                        "win_rate": _safe_float(best["metrics"]["win_rate"]),
                        "trades": int(best["metrics"]["trades"]),
                    }
                )

        for window_name in sorted(grouped.keys(), key=_window_sort_key):
            symbol_rows: list[dict[str, object]] = []
            for symbol, cores in grouped[window_name].items():
                ranked = sorted(cores, key=lambda row: _safe_float(row["alpha_vs_spot"]), reverse=True)
                symbol_rows.append({"symbol": symbol, "cores": ranked, "indicators": ranked})
            symbol_rows.sort(key=lambda row: str(row["symbol"]))
            table_rows.append({"gate_mode": gate_mode, "window": window_name, "symbols": symbol_rows})
    return table_rows


def _build_rule_catalog(results: Iterable[TimeframeOptimizationResult]) -> list[dict[str, object]]:
    catalog: dict[str, dict[str, object]] = {}
    for result in results:
        indicator_id = result.get("core_id", result["indicator_id"])
        slot = catalog.setdefault(
            indicator_id,
            {
                "strategy_mode": result.get("strategy_mode", "indicator"),
                "core_id": result.get("core_id", result["indicator_id"]),
                "core_name_zh": result.get("core_name_zh", result["indicator_name_zh"]),
                "core_family": result.get("core_family", result["indicator_family"]),
                "indicator_id": indicator_id,
                "indicator_name_zh": result.get("core_name_zh", result["indicator_name_zh"]),
                "indicator_family": result.get("core_family", result["indicator_family"]),
                "rules": {},
            },
        )
        rules = slot["rules"]
        for window in result["windows"]:
            for candidate in list(window.get("top_long_candidates", [])) + list(window.get("top_inverse_candidates", [])):
                rule_key = str(candidate.get("rule_key", ""))
                if not rule_key:
                    continue
                rules[rule_key] = str(candidate.get("rule_label_zh", rule_key))
            rc = window.get("rule_competition")
            if not rc:
                continue
            for example in list(rc.get("top_rejected_examples", [])):
                rule_key = str(example.get("rule_key", ""))
                if not rule_key:
                    continue
                rules[rule_key] = str(example.get("rule_label_zh", rule_key))

    out: list[dict[str, object]] = []
    for indicator_id in sorted(catalog.keys()):
        item = catalog[indicator_id]
        rules_map = item["rules"]
        out.append(
            {
                "strategy_mode": item.get("strategy_mode", "indicator"),
                "core_id": item.get("core_id", indicator_id),
                "core_name_zh": item.get("core_name_zh", item["indicator_name_zh"]),
                "core_family": item.get("core_family", item["indicator_family"]),
                "indicator_id": indicator_id,
                "indicator_name_zh": item["indicator_name_zh"],
                "indicator_family": item["indicator_family"],
                "rules": [
                    {"rule_key": rule_key, "rule_label_zh": rules_map[rule_key]}
                    for rule_key in sorted(rules_map.keys())
                ],
            }
        )
    return out


def _merge_feature_registry_entries(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    if not entries:
        return []
    merged: dict[str, dict[str, object]] = {}
    for item in entries:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        current = merged.get(name)
        if current is None:
            merged[name] = dict(item)
            continue
        prev_ratio = _safe_float(current.get("non_null_ratio"), default=0.0)
        next_ratio = _safe_float(item.get("non_null_ratio"), default=0.0)
        if next_ratio > prev_ratio:
            merged[name] = dict(item)
    rows = list(merged.values())
    rows.sort(key=lambda row: (str(row.get("family", "")), str(row.get("name", ""))))
    return rows


def _build_feature_importance_overview(results: Iterable[TimeframeOptimizationResult]) -> list[dict[str, object]]:
    stats: dict[str, dict[str, object]] = {}
    for result in results:
        for window in result["windows"]:
            profile = window.get("feature_weight_profile")
            if not isinstance(profile, dict):
                continue
            for row in profile.get("top_features", []) if isinstance(profile.get("top_features", []), list) else []:
                name = str(row.get("name", "")).strip()
                if not name:
                    continue
                slot = stats.setdefault(
                    name,
                    {
                        "name": name,
                        "family": str(row.get("family", "misc")),
                        "samples": 0,
                        "utility_sum": 0.0,
                        "corr_abs_sum": 0.0,
                    },
                )
                slot["samples"] = int(slot["samples"]) + 1
                slot["utility_sum"] = float(slot["utility_sum"]) + _safe_float(row.get("utility_score"))
                slot["corr_abs_sum"] = float(slot["corr_abs_sum"]) + abs(_safe_float(row.get("correlation")))

    out: list[dict[str, object]] = []
    for name, row in stats.items():
        samples = max(1, int(row["samples"]))
        out.append(
            {
                "name": name,
                "family": row["family"],
                "samples": samples,
                "avg_utility": float(row["utility_sum"]) / samples,
                "avg_abs_correlation": float(row["corr_abs_sum"]) / samples,
            }
        )
    out.sort(key=lambda item: (_safe_float(item.get("avg_utility")), _safe_float(item.get("avg_abs_correlation"))), reverse=True)
    return out[:120]


def _build_feature_pruning_overview(results: Iterable[TimeframeOptimizationResult]) -> list[dict[str, object]]:
    stats: dict[str, dict[str, object]] = {}
    for result in results:
        for window in result["windows"]:
            profile = window.get("feature_weight_profile")
            if not isinstance(profile, dict):
                continue
            for row in profile.get("prune_candidates", []) if isinstance(profile.get("prune_candidates", []), list) else []:
                name = str(row.get("name", "")).strip()
                if not name:
                    continue
                slot = stats.setdefault(
                    name,
                    {
                        "name": name,
                        "family": str(row.get("family", "misc")),
                        "flag_count": 0,
                        "utility_sum": 0.0,
                        "reason_counts": defaultdict(int),
                    },
                )
                slot["flag_count"] = int(slot["flag_count"]) + 1
                slot["utility_sum"] = float(slot["utility_sum"]) + _safe_float(row.get("utility_score"))
                reason = str(row.get("reason", "unknown"))
                slot["reason_counts"][reason] += 1

    out: list[dict[str, object]] = []
    for _, row in stats.items():
        count = max(1, int(row["flag_count"]))
        reason_counts = cast(defaultdict[str, int], row["reason_counts"])
        dominant_reason = sorted(reason_counts.items(), key=lambda item: item[1], reverse=True)[0][0] if reason_counts else "unknown"
        out.append(
            {
                "name": row["name"],
                "family": row["family"],
                "flag_count": count,
                "avg_utility": float(row["utility_sum"]) / count,
                "dominant_reason": dominant_reason,
            }
        )
    out.sort(key=lambda item: (int(item.get("flag_count", 0)), -_safe_float(item.get("avg_utility"))), reverse=True)
    return out[:120]


def _normalize_rule_competition(window: OptimizationWindowResult) -> dict[str, object]:
    rc = window.get("rule_competition")
    if not rc:
        return {
            "total_candidates": int(window.get("evaluated_candidates", 0)),
            "kept_candidates": 0,
            "rejected_breakdown": {"low_trades": 0, "low_credibility": 0, "underperform_spot": 0, "high_drawdown": 0},
            "top_rejected_examples": [],
        }
    return {
        "total_candidates": int(rc.get("total_candidates", 0)),
        "kept_candidates": int(rc.get("kept_candidates", 0)),
        "rejected_breakdown": {
            "low_trades": int(rc.get("rejected_breakdown", {}).get("low_trades", 0)),
            "low_credibility": int(rc.get("rejected_breakdown", {}).get("low_credibility", 0)),
            "underperform_spot": int(rc.get("rejected_breakdown", {}).get("underperform_spot", 0)),
            "high_drawdown": int(rc.get("rejected_breakdown", {}).get("high_drawdown", 0)),
        },
        "top_rejected_examples": list(rc.get("top_rejected_examples", [])),
    }


def _write_event_candles_payload(
    *,
    event: dict[str, object],
    symbol: str,
    gate_mode: str,
    window: str,
    frame_1m: pd.DataFrame,
    base_dir: Path,
    date_token: str,
) -> str | None:
    if frame_1m.empty:
        return None
    try:
        start_utc = pd.Timestamp(str(event.get("start_utc")), tz="UTC")
        end_utc = pd.Timestamp(str(event.get("end_utc")), tz="UTC")
    except Exception:
        return None
    if end_utc < start_utc:
        return None

    pad = pd.Timedelta(minutes=120)
    sliced = frame_1m.loc[(frame_1m.index >= (start_utc - pad)) & (frame_1m.index <= (end_utc + pad))]
    if sliced.empty:
        return None
    sliced = sliced.tail(500)

    rel_path = (
        Path("events")
        / f"gate={gate_mode}"
        / f"window={window}"
        / f"symbol={symbol}"
        / f"{str(event.get('type', 'event'))}.json"
    )
    output_path = base_dir / rel_path
    payload = {
        "symbol": symbol,
        "gate_mode": gate_mode,
        "window": window,
        "event_type": event.get("type"),
        "entry_utc": event.get("entry_utc"),
        "exit_utc": event.get("exit_utc"),
        "start_utc": event.get("start_utc"),
        "end_utc": event.get("end_utc"),
        "pnl": _safe_float(event.get("pnl")),
        "bars": int(event.get("bars", 0) or 0),
        "candles": [
            {
                "ts": ts.isoformat(),
                "open": _safe_float(row["open"]),
                "high": _safe_float(row["high"]),
                "low": _safe_float(row["low"]),
                "close": _safe_float(row["close"]),
                "volume": _safe_float(row["volume"]),
            }
            for ts, row in sliced.iterrows()
        ],
    }
    _serialize_json(payload, output_path)
    return f"/engine/artifacts/optimization/single/{date_token}/{str(rel_path).replace('\\', '/')}"


def _build_explainability_payload(
    *,
    run_id: str,
    now_utc: datetime,
    date_token: str,
    base_dir: Path,
    gate_modes: list[str],
    windows: list[str],
    results_by_gate_mode: dict[str, list[TimeframeOptimizationResult]],
    raw_layer_root: Path | None,
    run_start_utc: datetime | None,
    run_end_utc: datetime | None,
) -> dict[str, object]:
    frame_cache: dict[str, pd.DataFrame] = {}

    def load_symbol_frame(symbol: str) -> pd.DataFrame:
        if raw_layer_root is None:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        if symbol not in frame_cache:
            frame_cache[symbol] = load_latest_partitioned_parquet(
                layer_root=raw_layer_root,
                symbol=symbol,
                timeframe="1m",
                start_utc=pd.Timestamp(run_start_utc) if run_start_utc is not None else None,
                end_utc=pd.Timestamp(run_end_utc) if run_end_utc is not None else None,
            )
        return frame_cache[symbol]

    window_reports: list[dict[str, object]] = []
    for gate_mode in gate_modes:
        gate_results = results_by_gate_mode.get(gate_mode, [])
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)

        for result in gate_results:
            symbol = result["symbol"]
            frame_1m = load_symbol_frame(symbol)
            for window in result["windows"]:
                best_long = window.get("best_long")
                performance = {
                    "strategy_return": _safe_float(best_long["metrics"]["friction_adjusted_return"]) if best_long else 0.0,
                    "spot_return": _safe_float(window.get("benchmark_buy_hold_return")),
                    "alpha_vs_spot": _safe_float(window.get("best_long_alpha_vs_spot")),
                    "max_drawdown": _safe_float(best_long["metrics"]["max_drawdown"]) if best_long else 0.0,
                    "trades": int(best_long["metrics"]["trades"]) if best_long else 0,
                    "win_rate": _safe_float(best_long["metrics"]["win_rate"]) if best_long else 0.0,
                    "window_trade_floor": int(window.get("window_trade_floor", 100) or 100),
                }

                event_samples = []
                for event in list(window.get("event_samples", [])):
                    event_copy = dict(event)
                    candles_path = _write_event_candles_payload(
                        event=event_copy,
                        symbol=symbol,
                        gate_mode=gate_mode,
                        window=str(window["window"]),
                        frame_1m=frame_1m,
                        base_dir=base_dir,
                        date_token=date_token,
                    )
                    event_copy["candles_path"] = candles_path
                    event_samples.append(event_copy)

                grouped[str(window["window"])].append(
                    {
                        "symbol": symbol,
                        "timeframe": result["timeframe"],
                        "strategy_mode": result.get("strategy_mode", "indicator"),
                        "core_id": result.get("core_id", result["indicator_id"]),
                        "core_name_zh": result.get("core_name_zh", result["indicator_name_zh"]),
                        "core_family": result.get("core_family", result["indicator_family"]),
                        "indicator_id": result["indicator_id"],
                        "indicator_name_zh": result["indicator_name_zh"],
                        "indicator_family": result["indicator_family"],
                        "grade": _classify_grade(window),
                        "status": "beat_spot" if bool(window.get("best_long_passes_objective")) else "underperform_spot",
                        "best_rule": (
                            {
                                "signal_source": best_long.get("signal_source", result.get("strategy_mode", "indicator")),
                                "strategy_mode": best_long.get("strategy_mode", result.get("strategy_mode", "indicator")),
                                "core_id": best_long.get("core_id", result.get("core_id", best_long["indicator_id"])),
                                "core_name_zh": best_long.get("core_name_zh", result.get("core_name_zh", best_long["indicator_name_zh"])),
                                "core_family": best_long.get("core_family", result.get("core_family", best_long["indicator_family"])),
                                "indicator_id": best_long["indicator_id"],
                                "indicator_name_zh": best_long["indicator_name_zh"],
                                "indicator_family": best_long["indicator_family"],
                                "rule_key": best_long["rule_key"],
                                "rule_label_zh": best_long["rule_label_zh"],
                                "params": best_long["params"],
                                "params_text": _format_params(best_long["params"]),
                                "score": _safe_float(best_long["score"]),
                            }
                            if best_long
                            else None
                        ),
                        "performance": performance,
                        "rule_competition": _normalize_rule_competition(window),
                        "feature_weight_profile": window.get("feature_weight_profile"),
                        "feature_diagnostics": {
                            "family_contribution": (window.get("feature_weight_profile") or {}).get("family_contribution", {}),
                            "top_features": (window.get("feature_weight_profile") or {}).get("top_features", []),
                            "prune_candidates": (window.get("feature_weight_profile") or {}).get("prune_candidates", []),
                        },
                        "oracle_threshold": window.get("oracle_threshold"),
                        "confidence_threshold": window.get("confidence_threshold"),
                        "signal_frequency": window.get("signal_frequency"),
                        "event_samples": event_samples,
                        "no_lookahead_audit": window.get("no_lookahead_audit"),
                        "insufficient_statistical_significance": bool(window.get("insufficient_statistical_significance")),
                    }
                )

        for window_name in sorted(grouped.keys(), key=_window_sort_key):
            rows = sorted(
                grouped[window_name],
                key=lambda row: (
                    GRADE_ORDER.get(str(row.get("grade", "C")), 9),
                    -_safe_float(row.get("performance", {}).get("alpha_vs_spot")),
                    str(row.get("symbol", "")),
                ),
            )
            window_reports.append({"gate_mode": gate_mode, "window": window_name, "symbols": rows})

    strategy_mode_value = "indicator"
    for gate_results in results_by_gate_mode.values():
        if gate_results:
            strategy_mode_value = str(gate_results[0].get("strategy_mode", "indicator"))
            break

    return {
        "run_id": run_id,
        "generated_at_utc": now_utc.isoformat(),
        "strategy_mode": strategy_mode_value,
        "gate_modes": gate_modes,
        "windows": sorted(windows, key=_window_sort_key),
        "window_reports": window_reports,
    }


def write_optimization_artifacts(
    run_id: str,
    universe: list[str],
    results: list[TimeframeOptimizationResult],
    artifact_root: Path,
    raw_layer_root: Path | None = None,
    run_start_utc: datetime | None = None,
    run_end_utc: datetime | None = None,
    quality_targets: dict[str, float] | None = None,
    feature_registry: list[dict[str, object]] | None = None,
) -> dict[str, str]:
    if any(result["timeframe"] != "1m" for result in results):
        raise ValueError("Optimization artifact contract is 1m-only. Non-1m result detected.")

    now_utc = datetime.now(timezone.utc)
    date_token = now_utc.strftime("%Y-%m-%d")
    base_dir = artifact_root / "optimization" / "single" / date_token

    windows = sorted({window["window"] for result in results for window in result["windows"]}, key=_window_sort_key)
    timeframes = sorted({result["timeframe"] for result in results})
    gate_modes = sorted({result["gate_mode"] for result in results})
    strategy_mode = str(results[0].get("strategy_mode", "indicator")) if results else "indicator"
    cores = sorted({str(result.get("core_id", result["indicator_id"])) for result in results})
    results_by_gate_mode = {
        gate_mode: [result for result in results if result["gate_mode"] == gate_mode]
        for gate_mode in gate_modes
    }
    default_results = results_by_gate_mode.get("gated", results)

    summary: OptimizationSummary = OptimizationSummary(
        run_id=run_id,
        asof_utc=now_utc.isoformat(),
        universe=universe,
        windows=windows,
        timeframes=timeframes,
        gate_modes=gate_modes,
        results=default_results,
    )
    executive_report = _build_executive_report(results_by_gate_mode=results_by_gate_mode, universe_size=len(universe))
    delta_views = _build_delta_views(
        results_by_gate_mode=results_by_gate_mode,
        executive_report=executive_report,
    )
    indicator_comparison = _build_indicator_comparison(results_by_gate_mode)
    symbol_indicator_gate_delta = (
        delta_views.get("symbol_indicator_gate_delta", [])
        if isinstance(delta_views.get("symbol_indicator_gate_delta", []), list)
        else []
    )
    rank_shift_gated_vs_ungated = _build_rank_shift_gated_vs_ungated(symbol_indicator_gate_delta)
    window_alpha_heatmap_payload = _build_window_alpha_heatmap_payload(symbol_indicator_gate_delta)
    indicator_competition_overview = _build_indicator_competition_overview(symbol_indicator_gate_delta)
    health_dashboard = _build_health_dashboard(
        executive_report=executive_report,
        gate_modes=gate_modes,
        windows=windows,
        indicator_competition_overview=indicator_competition_overview,
        quality_targets=quality_targets,
    )
    rule_catalog = _build_rule_catalog(results)
    merged_feature_registry = _merge_feature_registry_entries(feature_registry or [])
    feature_importance_leaderboard = _build_feature_importance_overview(results)
    feature_pruning_candidates = _build_feature_pruning_overview(results)
    summary_payload = {
        **summary,
        "results_by_gate_mode": results_by_gate_mode,
        "leaderboard_alpha": _build_leaderboard(results, metric="alpha"),
        "leaderboard_score": _build_leaderboard(results, metric="score"),
        "leaderboard_return": _build_leaderboard(results, metric="return"),
        "cross_section_leaderboard": _build_leaderboard(default_results, metric="alpha"),
        "executive_report": executive_report,
        "health_dashboard": health_dashboard,
        "delta_views": delta_views,
        "rank_shift_gated_vs_ungated": rank_shift_gated_vs_ungated,
        "window_alpha_heatmap_payload": window_alpha_heatmap_payload,
        "indicator_competition_overview": indicator_competition_overview,
        "strategy_mode": strategy_mode,
        "signal_cores": cores,
        "single_indicators": cores,
        "rule_catalog": rule_catalog,
        "prototype_catalog": rule_catalog,
        "indicator_comparison": indicator_comparison,
        "core_comparison": indicator_comparison,
        "feature_registry": merged_feature_registry,
        "feature_importance_leaderboard": feature_importance_leaderboard,
        "feature_pruning_candidates": feature_pruning_candidates,
        "feature_learning_summary": {
            "registry_size": len(merged_feature_registry),
            "importance_ranked_features": len(feature_importance_leaderboard),
            "prune_candidate_count": len(feature_pruning_candidates),
        },
        "style_ab_payload": [
            {
                "symbol": result["symbol"],
                "timeframe": result["timeframe"],
                "gate_mode": result["gate_mode"],
                "strategy_mode": result.get("strategy_mode", strategy_mode),
                "core_id": result.get("core_id", result["indicator_id"]),
                "core_name_zh": result.get("core_name_zh", result["indicator_name_zh"]),
                "indicator_id": result.get("core_id", result["indicator_id"]),
                "indicator_name_zh": result.get("core_name_zh", result["indicator_name_zh"]),
                "windows": [
                    {
                        "window": window["window"],
                        "best_long_score": window["best_long"]["score"] if window["best_long"] else None,
                        "best_inverse_score": window["best_inverse"]["score"] if window["best_inverse"] else None,
                    }
                    for window in result["windows"]
                ],
            }
            for result in default_results
        ],
    }

    summary_path = base_dir / "summary.json"
    _serialize_json(summary_payload, summary_path)

    for result in results:
        symbol = result["symbol"]
        timeframe = result["timeframe"]
        indicator = result.get("core_id", result["indicator_id"])
        gate_mode = result["gate_mode"]
        symbol_path = (
            base_dir
            / f"symbol={symbol}"
            / f"core={indicator}"
            / f"gate={gate_mode}"
            / f"timeframe={timeframe}.json"
        )
        _serialize_json(result, symbol_path)

    explainability_payload = _build_explainability_payload(
        run_id=run_id,
        now_utc=now_utc,
        date_token=date_token,
        base_dir=base_dir,
        gate_modes=gate_modes,
        windows=windows,
        results_by_gate_mode=results_by_gate_mode,
        raw_layer_root=raw_layer_root,
        run_start_utc=run_start_utc,
        run_end_utc=run_end_utc,
    )
    explainability_path = base_dir / "explainability.json"
    _serialize_json(explainability_payload, explainability_path)

    return {"summary": str(summary_path), "explainability": str(explainability_path), "root": str(base_dir)}
