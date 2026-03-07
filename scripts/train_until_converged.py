from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OPT_ROOT = ROOT / "engine" / "artifacts" / "optimization" / "single"
CONTROL_ROOT = ROOT / "engine" / "artifacts" / "control"
STATE_PATH = CONTROL_ROOT / "training_loop_state.json"

STAGE_FLOW_RECOVERY = "STAGE_FLOW_RECOVERY"
STAGE_ALPHA_RECOVERY = "STAGE_ALPHA_RECOVERY"
BATCH_FLOW_UNLOCK = "BATCH_FLOW_UNLOCK"
BATCH_QUALITY_RECOVERY = "BATCH_QUALITY_RECOVERY"

STATUS_FLOW_LOCK = "TRAINING_STATUS_STAGNATED_FLOW_LOCK"
OBJECTIVE_FLOW_UNLOCK = "OBJECTIVE_FLOW_UNLOCK"
OBJECTIVE_ALPHA_RECOVERY = "OBJECTIVE_ALPHA_RECOVERY"

CANDIDATE_TIER_EXPLORATORY = "CANDIDATE_TIER_EXPLORATORY"
CANDIDATE_TIER_STRICT = "CANDIDATE_TIER_STRICT"

MILESTONE_M1_TRADES = "M1_TRADES"
MILESTONE_M2_VETO_93 = "M2_VETO_93"
MILESTONE_M3_VETO_85_FAILSAFE_40 = "M3_VETO_85_FAILSAFE_40"
MILESTONE_M3_PASSED = "M3_PASSED"

FLOW_REASON_NEED_TRADES = "FLOW_REASON_NEED_TRADES"
FLOW_REASON_NEED_VETO_93 = "FLOW_REASON_NEED_VETO_93"
FLOW_REASON_NEED_VETO_85_FAILSAFE_40 = "FLOW_REASON_NEED_VETO_85_FAILSAFE_40"
FLOW_REASON_PASSED = "FLOW_REASON_PASSED"

ROUTE_TRADE_DENSITY_LOW = "ROUTE_TRADE_DENSITY_LOW"
ROUTE_PRECISION_UNMET = "ROUTE_PRECISION_UNMET"
ROUTE_ALPHA_NEGATIVE = "ROUTE_ALPHA_NEGATIVE"
ROUTE_STABILITY_SCAN = "ROUTE_STABILITY_SCAN"
ROUTE_PROFILE_EFFECTIVENESS_OVERRIDE = "ROUTE_PROFILE_EFFECTIVENESS_OVERRIDE"
ROUTE_BATCH_EXPLORATION = "ROUTE_BATCH_EXPLORATION"

FLOW_UNLOCK_CAP_DEFAULT = 30
QUALITY_RECOVERY_CAP_DEFAULT = 20

FLOW_UNLOCK_THRESHOLD_MIN_VALUES = [round(0.30 + (0.02 * idx), 2) for idx in range(12)]
FLOW_UNLOCK_FALLBACK_VALUES = [0.50, 0.52, 0.55]
FLOW_UNLOCK_HORIZON_VALUES = [24, 32, 40]
FLOW_UNLOCK_TP_VALUES = [1.00, 1.10, 1.20]
FLOW_UNLOCK_SL_VALUES = [1.00, 1.05, 1.10]
FLOW_UNLOCK_MIN_EVENT_VALUES = [20, 30, 40]
FLOW_UNLOCK_CPCV_SPLITS = [4, 5]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out:
        return default
    return out


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_checked(cmd: list[str], env: dict[str, str] | None = None) -> None:
    print(f"[run] {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"command_failed:{proc.returncode}:{' '.join(cmd)}")


def latest_validation_path() -> Path:
    candidates = sorted(OPT_ROOT.rglob("validation_report.json"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise RuntimeError("validation_report.json not found")
    return candidates[-1]


def extract_all_window_alpha(validation: dict[str, Any]) -> float:
    rows = validation.get("summary_by_window", [])
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("window")) == "all":
                return safe_float(row.get("avg_alpha_vs_spot"), 0.0)
    return 0.0


def extract_trade_stats(validation: dict[str, Any]) -> tuple[int, float]:
    rows = validation.get("rows", [])
    if not isinstance(rows, list):
        return 0, 0.0
    selected = [row for row in rows if isinstance(row, dict) and str(row.get("window")) == "all"]
    if not selected:
        return 0, 0.0
    trades = [safe_int(row.get("trades"), 0) for row in selected]
    total = int(sum(trades))
    avg = float(total / len(trades)) if trades else 0.0
    return total, avg


def extract_signal_density(validation: dict[str, Any]) -> tuple[int, int]:
    rows = validation.get("rows", [])
    if not isinstance(rows, list):
        return 0, 0
    selected = [row for row in rows if isinstance(row, dict) and str(row.get("window")) == "all"]
    if not selected:
        return 0, 0
    raw_total = int(sum(safe_int(row.get("entry_signals_raw"), 0) for row in selected))
    meta_total = int(sum(safe_int(row.get("entry_signals_meta"), 0) for row in selected))
    return raw_total, meta_total


def extract_meta_metrics(validation: dict[str, Any]) -> dict[str, float]:
    meta_summary = validation.get("meta_label_summary", {})
    meta_summary = meta_summary if isinstance(meta_summary, dict) else {}
    class_median = meta_summary.get("classification_median", {})
    class_median = class_median if isinstance(class_median, dict) else {}
    cpcv_median = meta_summary.get("cpcv_median", {})
    cpcv_median = cpcv_median if isinstance(cpcv_median, dict) else {}
    return {
        "precision": safe_float(class_median.get("precision"), 0.0),
        "f1": safe_float(class_median.get("f1"), 0.0),
        "pr_auc": safe_float(class_median.get("pr_auc"), 0.0),
        "failsafe_veto_all_rate": safe_float(meta_summary.get("failsafe_veto_all_rate"), 0.0),
        "precision_floor_compliance_rate": safe_float(cpcv_median.get("precision_floor_compliance_rate"), 0.0),
        "veto_all_rate": safe_float(cpcv_median.get("veto_all_rate"), 0.0),
    }


def compute_veto_rate(validation: dict[str, Any], fallback: float = 1.0) -> float:
    rows = validation.get("rows", [])
    if not isinstance(rows, list):
        return max(0.0, min(1.0, fallback))
    raw_total = 0
    kept_total = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_total += safe_int(row.get("entry_signals_raw"), 0)
        kept_total += safe_int(row.get("entry_signals_meta"), 0)
    if raw_total <= 0:
        return max(0.0, min(1.0, fallback))
    return max(0.0, min(1.0, 1.0 - (kept_total / raw_total)))


def extract_pbo_dsr(validation: dict[str, Any]) -> tuple[float, float]:
    rows = validation.get("rows", [])
    if not isinstance(rows, list) or not rows:
        return 1.0, -10.0
    pbo_values: list[float] = []
    dsr_values: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pbo_values.append(safe_float(row.get("pbo"), 1.0))
        dsr_values.append(safe_float(row.get("dsr"), -10.0))
    if not pbo_values:
        return 1.0, -10.0
    pbo_values.sort()
    dsr_values.sort()
    mid = len(pbo_values) // 2
    return float(pbo_values[mid]), float(dsr_values[mid])


def collect_latest_metrics() -> dict[str, Any]:
    validation_path = latest_validation_path()
    validation = read_json(validation_path)
    failure = read_json(validation_path.parent / "failure_breakdown.json")
    run_id = str(validation.get("run_id") or "")
    pass_rate = safe_float(validation.get("pass_rate"), 0.0)
    all_alpha = extract_all_window_alpha(validation)
    trades_total, trades_avg = extract_trade_stats(validation)
    entry_signals_raw_all, entry_signals_meta_all = extract_signal_density(validation)
    meta_metrics = extract_meta_metrics(validation)
    pbo, dsr = extract_pbo_dsr(validation)
    deploy_ready = bool(failure.get("deploy_ready", False))
    deploy_symbols = safe_int(failure.get("deploy_symbols"), 0)
    deploy_rules = safe_int(failure.get("deploy_rules"), 0)
    veto_rate = compute_veto_rate(validation, fallback=safe_float(meta_metrics.get("failsafe_veto_all_rate"), 1.0))

    return {
        "run_id": run_id,
        "validation_path": str(validation_path),
        "failure_path": str(validation_path.parent / "failure_breakdown.json"),
        "validation_pass_rate": pass_rate,
        "all_window_alpha": all_alpha,
        "deploy_ready": deploy_ready,
        "deploy_symbols": deploy_symbols,
        "deploy_rules": deploy_rules,
        "trades_total_all_window": trades_total,
        "trades_avg_all_window": trades_avg,
        "entry_signals_raw_all_window": entry_signals_raw_all,
        "entry_signals_meta_all_window": entry_signals_meta_all,
        "pbo": pbo,
        "dsr": dsr,
        "veto_rate": veto_rate,
        **meta_metrics,
    }


def quality_score(metrics: dict[str, Any]) -> float:
    pass_norm = max(0.0, min(1.0, safe_float(metrics.get("validation_pass_rate"), 0.0) / 0.20))
    alpha_norm = max(0.0, min(1.0, (safe_float(metrics.get("all_window_alpha"), -1.0) + 1.0) / 2.0))
    deploy_norm = 1.0 if bool(metrics.get("deploy_ready")) else 0.0
    robustness = max(0.0, min(1.0, 1.0 - safe_float(metrics.get("pbo"), 1.0)))
    return float((0.35 * pass_norm) + (0.35 * alpha_norm) + (0.20 * deploy_norm) + (0.10 * robustness))


def flow_score(metrics: dict[str, Any]) -> float:
    trades_total = safe_int(metrics.get("trades_total_all_window"), 0)
    veto_rate = safe_float(metrics.get("veto_rate"), 1.0)
    failsafe_rate = safe_float(metrics.get("failsafe_veto_all_rate"), 1.0)
    raw_signals = safe_int(metrics.get("entry_signals_raw_all_window"), 0)
    kept_signals = safe_int(metrics.get("entry_signals_meta_all_window"), 0)

    trades_norm = max(0.0, min(1.0, trades_total / 20.0))
    veto_norm = max(0.0, min(1.0, 1.0 - veto_rate))
    failsafe_norm = max(0.0, min(1.0, 1.0 - failsafe_rate))
    kept_ratio = (kept_signals / max(1, raw_signals)) if raw_signals > 0 else 0.0
    kept_norm = max(0.0, min(1.0, kept_ratio * 8.0))
    return float((0.35 * trades_norm) + (0.30 * veto_norm) + (0.20 * failsafe_norm) + (0.15 * kept_norm))


def flow_milestone_state(metrics: dict[str, Any], *, flow_gate: dict[str, Any] | None = None) -> tuple[int, str, str, bool]:
    flow_gate = flow_gate if isinstance(flow_gate, dict) else {}
    trades_total = safe_int(metrics.get("trades_total_all_window"), 0)
    veto_rate = safe_float(metrics.get("veto_rate"), 1.0)
    failsafe_rate = safe_float(metrics.get("failsafe_veto_all_rate"), 1.0)
    min_trades = max(1, safe_int(flow_gate.get("min_trades_total_all_window"), 12))
    max_veto = safe_float(flow_gate.get("max_veto_rate"), 0.93)
    max_failsafe = safe_float(flow_gate.get("max_failsafe_veto_all_rate"), 0.40)

    if trades_total < min_trades:
        return 0, MILESTONE_M1_TRADES, FLOW_REASON_NEED_TRADES, False
    if veto_rate > max_veto:
        return 1, MILESTONE_M2_VETO_93, FLOW_REASON_NEED_VETO_93, False
    if failsafe_rate > max_failsafe:
        return 2, MILESTONE_M3_VETO_85_FAILSAFE_40, FLOW_REASON_NEED_VETO_85_FAILSAFE_40, False
    return 3, MILESTONE_M3_PASSED, FLOW_REASON_PASSED, True


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _choice(values: list[Any], *, loop_index: int, multiplier: int, offset: int = 0) -> Any:
    if not values:
        raise ValueError("values must not be empty")
    idx = max(0, (int(loop_index) * int(multiplier) + int(offset))) % len(values)
    return values[idx]


def _fmt_float(value: float, digits: int = 2) -> str:
    return f"{float(value):.{int(digits)}f}"


def _override_float(overrides: dict[str, str], key: str, default: float) -> float:
    return safe_float(overrides.get(key), default)


def _override_int(overrides: dict[str, str], key: str, default: int) -> int:
    return safe_int(overrides.get(key), default)


def apply_flow_unlock_batch(*, loop_index: int, base_overrides: dict[str, str]) -> dict[str, str]:
    overrides = dict(base_overrides)
    overrides["ENGINE_META_LABEL_THRESHOLD_MIN"] = _fmt_float(
        float(_choice(FLOW_UNLOCK_THRESHOLD_MIN_VALUES, loop_index=loop_index, multiplier=7))
    )
    overrides["ENGINE_META_LABEL_PROB_THRESHOLD_FALLBACK"] = _fmt_float(
        float(_choice(FLOW_UNLOCK_FALLBACK_VALUES, loop_index=loop_index, multiplier=5))
    )
    overrides["ENGINE_META_LABEL_VERTICAL_HORIZON_BARS"] = str(
        int(_choice(FLOW_UNLOCK_HORIZON_VALUES, loop_index=loop_index, multiplier=3))
    )
    overrides["ENGINE_META_LABEL_TP_MULT"] = _fmt_float(
        float(_choice(FLOW_UNLOCK_TP_VALUES, loop_index=loop_index, multiplier=11))
    )
    overrides["ENGINE_META_LABEL_SL_MULT"] = _fmt_float(
        float(_choice(FLOW_UNLOCK_SL_VALUES, loop_index=loop_index, multiplier=13))
    )
    overrides["ENGINE_META_LABEL_MIN_EVENTS"] = str(
        int(_choice(FLOW_UNLOCK_MIN_EVENT_VALUES, loop_index=loop_index, multiplier=17))
    )
    overrides["ENGINE_META_LABEL_CPCV_SPLITS"] = str(
        int(_choice(FLOW_UNLOCK_CPCV_SPLITS, loop_index=loop_index, multiplier=19))
    )
    overrides["ENGINE_META_LABEL_CPCV_TEST_GROUPS"] = "1"
    return overrides


def _around_float(anchor: float, lo: float, hi: float, step: float) -> list[float]:
    vals = [anchor - step, anchor, anchor + step]
    out: list[float] = []
    for v in vals:
        clipped = _clip(v, lo, hi)
        if all(abs(clipped - prev) > 1e-9 for prev in out):
            out.append(clipped)
    return out


def _around_int(anchor: int, lo: int, hi: int, step: int) -> list[int]:
    vals = [anchor - step, anchor, anchor + step]
    out: list[int] = []
    for v in vals:
        clipped = int(max(lo, min(hi, v)))
        if clipped not in out:
            out.append(clipped)
    return out


def apply_quality_recovery_batch(
    *,
    loop_index: int,
    base_overrides: dict[str, str],
    anchor_overrides: dict[str, str] | None,
) -> dict[str, str]:
    anchor = anchor_overrides if isinstance(anchor_overrides, dict) else base_overrides

    anchor_threshold = _override_float(anchor, "ENGINE_META_LABEL_THRESHOLD_MIN", 0.46)
    anchor_horizon = _override_int(anchor, "ENGINE_META_LABEL_VERTICAL_HORIZON_BARS", 32)
    anchor_tp = _override_float(anchor, "ENGINE_META_LABEL_TP_MULT", 1.10)
    anchor_sl = _override_float(anchor, "ENGINE_META_LABEL_SL_MULT", 1.05)
    anchor_min_events = _override_int(anchor, "ENGINE_META_LABEL_MIN_EVENTS", 40)
    anchor_fallback = _override_float(anchor, "ENGINE_META_LABEL_PROB_THRESHOLD_FALLBACK", 0.55)

    threshold_values = _around_float(anchor_threshold, 0.30, 0.60, 0.03)
    horizon_values = _around_int(anchor_horizon, 16, 56, 8)
    tp_values = _around_float(anchor_tp, 0.95, 1.30, 0.08)
    sl_values = _around_float(anchor_sl, 0.90, 1.20, 0.08)
    min_event_values = _around_int(anchor_min_events, 20, 80, 10)
    fallback_values = _around_float(anchor_fallback, 0.50, 0.62, 0.03)

    overrides = dict(base_overrides)
    overrides["ENGINE_META_LABEL_THRESHOLD_MIN"] = _fmt_float(
        float(_choice(threshold_values, loop_index=loop_index, multiplier=7))
    )
    overrides["ENGINE_META_LABEL_PROB_THRESHOLD_FALLBACK"] = _fmt_float(
        float(_choice(fallback_values, loop_index=loop_index, multiplier=11))
    )
    overrides["ENGINE_META_LABEL_VERTICAL_HORIZON_BARS"] = str(
        int(_choice(horizon_values, loop_index=loop_index, multiplier=5))
    )
    overrides["ENGINE_META_LABEL_TP_MULT"] = _fmt_float(
        float(_choice(tp_values, loop_index=loop_index, multiplier=13))
    )
    overrides["ENGINE_META_LABEL_SL_MULT"] = _fmt_float(
        float(_choice(sl_values, loop_index=loop_index, multiplier=17))
    )
    overrides["ENGINE_META_LABEL_MIN_EVENTS"] = str(
        int(_choice(min_event_values, loop_index=loop_index, multiplier=19))
    )
    overrides["ENGINE_META_LABEL_CPCV_SPLITS"] = "6"
    overrides["ENGINE_META_LABEL_CPCV_TEST_GROUPS"] = "2"
    return overrides


def extract_override_snapshot(overrides: dict[str, str]) -> dict[str, float]:
    return {
        "threshold_min": safe_float(overrides.get("ENGINE_META_LABEL_THRESHOLD_MIN"), 0.0),
        "prob_threshold_fallback": safe_float(overrides.get("ENGINE_META_LABEL_PROB_THRESHOLD_FALLBACK"), 0.0),
        "vertical_horizon_bars": float(safe_int(overrides.get("ENGINE_META_LABEL_VERTICAL_HORIZON_BARS"), 0)),
        "tp_mult": safe_float(overrides.get("ENGINE_META_LABEL_TP_MULT"), 0.0),
        "sl_mult": safe_float(overrides.get("ENGINE_META_LABEL_SL_MULT"), 0.0),
        "min_events": float(safe_int(overrides.get("ENGINE_META_LABEL_MIN_EVENTS"), 0)),
        "cpcv_splits": float(safe_int(overrides.get("ENGINE_META_LABEL_CPCV_SPLITS"), 0)),
    }


def profile_effectiveness(
    rounds: list[dict[str, Any]] | None,
    *,
    window: int = 8,
) -> dict[str, float]:
    if not isinstance(rounds, list) or len(rounds) < 2:
        return {}

    recent = rounds[-max(2, int(window)) :]
    bucket_sum: dict[str, float] = {}
    bucket_cnt: dict[str, int] = {}

    prev_metrics: dict[str, Any] | None = None
    for row in recent:
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            continue
        profile_name = str(row.get("profile_name") or "").strip().lower()
        if not profile_name:
            prev_metrics = metrics
            continue
        if prev_metrics is None:
            prev_metrics = metrics
            continue

        prev_veto = safe_float(prev_metrics.get("veto_rate"), 1.0)
        cur_veto = safe_float(metrics.get("veto_rate"), 1.0)
        prev_trades = safe_int(prev_metrics.get("trades_total_all_window"), 0)
        cur_trades = safe_int(metrics.get("trades_total_all_window"), 0)
        prev_alpha = safe_float(prev_metrics.get("all_window_alpha"), 0.0)
        cur_alpha = safe_float(metrics.get("all_window_alpha"), 0.0)

        delta_veto = _clip(prev_veto - cur_veto, -1.0, 1.0)
        delta_trades = _clip((cur_trades - prev_trades) / max(1.0, float(max(prev_trades, 1))), -1.0, 1.0)
        delta_alpha = _clip((cur_alpha - prev_alpha) / 2.0, -1.0, 1.0)
        score = float((0.50 * delta_veto) + (0.30 * delta_trades) + (0.20 * delta_alpha))

        bucket_sum[profile_name] = bucket_sum.get(profile_name, 0.0) + score
        bucket_cnt[profile_name] = bucket_cnt.get(profile_name, 0) + 1
        prev_metrics = metrics

    out: dict[str, float] = {}
    for key, total in bucket_sum.items():
        out[key] = total / max(1, bucket_cnt.get(key, 1))
    return out


PROFILE_PRESETS: dict[str, dict[str, str]] = {
    "r1_baseline": {
        "ENGINE_META_LABEL_TP_MULT": "1.20",
        "ENGINE_META_LABEL_SL_MULT": "1.00",
        "ENGINE_META_LABEL_VERTICAL_HORIZON_BARS": "24",
        "ENGINE_META_LABEL_VOL_WINDOW": "24",
        "ENGINE_META_LABEL_THRESHOLD_MIN": "0.45",
        "ENGINE_META_LABEL_MIN_EVENTS": "60",
        "ENGINE_META_LABEL_CPCV_SPLITS": "5",
        "ENGINE_META_LABEL_CPCV_TEST_GROUPS": "1",
    },
    "r2_event_expansion": {
        "ENGINE_META_LABEL_TP_MULT": "1.05",
        "ENGINE_META_LABEL_SL_MULT": "1.05",
        "ENGINE_META_LABEL_VERTICAL_HORIZON_BARS": "32",
        "ENGINE_META_LABEL_VOL_WINDOW": "18",
        "ENGINE_META_LABEL_THRESHOLD_MIN": "0.36",
        "ENGINE_META_LABEL_MIN_EVENTS": "30",
        "ENGINE_META_LABEL_CPCV_SPLITS": "4",
        "ENGINE_META_LABEL_CPCV_TEST_GROUPS": "1",
    },
    "r3_precision_recovery": {
        "ENGINE_META_LABEL_TP_MULT": "1.28",
        "ENGINE_META_LABEL_SL_MULT": "0.92",
        "ENGINE_META_LABEL_VERTICAL_HORIZON_BARS": "20",
        "ENGINE_META_LABEL_VOL_WINDOW": "20",
        "ENGINE_META_LABEL_THRESHOLD_MIN": "0.50",
        "ENGINE_META_LABEL_MIN_EVENTS": "55",
        "ENGINE_META_LABEL_CPCV_SPLITS": "6",
        "ENGINE_META_LABEL_CPCV_TEST_GROUPS": "2",
    },
    "r4_alpha_rescue": {
        "ENGINE_META_LABEL_TP_MULT": "1.12",
        "ENGINE_META_LABEL_SL_MULT": "1.10",
        "ENGINE_META_LABEL_VERTICAL_HORIZON_BARS": "28",
        "ENGINE_META_LABEL_VOL_WINDOW": "22",
        "ENGINE_META_LABEL_THRESHOLD_MIN": "0.40",
        "ENGINE_META_LABEL_MIN_EVENTS": "40",
        "ENGINE_META_LABEL_CPCV_SPLITS": "5",
        "ENGINE_META_LABEL_CPCV_TEST_GROUPS": "1",
    },
}


def _flow_gate_hit(metrics: dict[str, Any], flow_gate: dict[str, Any]) -> bool:
    min_trades = max(1, safe_int(flow_gate.get("min_trades_total_all_window"), 1))
    max_veto = safe_float(flow_gate.get("max_veto_rate"), 0.93)
    max_failsafe = safe_float(flow_gate.get("max_failsafe_veto_all_rate"), 0.40)
    trades_total = safe_int(metrics.get("trades_total_all_window"), 0)
    veto_rate = safe_float(metrics.get("veto_rate"), 1.0)
    failsafe_rate = safe_float(metrics.get("failsafe_veto_all_rate"), 1.0)
    return bool(
        trades_total >= min_trades
        and veto_rate <= max_veto
        and failsafe_rate <= max_failsafe
    )


def choose_meta_overrides(
    *,
    last_metrics: dict[str, Any] | None,
    loop_index: int,
    stagnation_count: int,
    stage_key: str,
    recent_rounds: list[dict[str, Any]] | None = None,
) -> tuple[str, str, dict[str, str]]:
    overrides: dict[str, str] = {
        "ENGINE_META_LABEL_THRESHOLD_STEP": "0.005",
        "ENGINE_META_LABEL_PROB_THRESHOLD_FALLBACK": "0.55",
    }

    def _with_profile(profile_name: str, reason_key: str) -> tuple[str, str, dict[str, str]]:
        merged = dict(overrides)
        merged.update(PROFILE_PRESETS.get(profile_name, PROFILE_PRESETS["r1_baseline"]))
        if loop_index % 4 == 0 and profile_name in {"r1_baseline", "r4_alpha_rescue"}:
            merged["ENGINE_META_LABEL_THRESHOLD_MIN"] = "0.44"
        return profile_name, reason_key, merged

    def _profile_score(profile_name: str, eff_map: dict[str, float]) -> float:
        return safe_float(eff_map.get(profile_name), 0.0)

    if last_metrics is None:
        return _with_profile("r2_event_expansion", ROUTE_TRADE_DENSITY_LOW)

    veto_rate = max(
        safe_float(last_metrics.get("veto_rate"), 0.0),
        safe_float(last_metrics.get("failsafe_veto_all_rate"), 0.0),
    )
    trades_total = safe_int(last_metrics.get("trades_total_all_window"), 0)
    floor_comp = safe_float(last_metrics.get("precision_floor_compliance_rate"), 0.0)
    pass_rate = safe_float(last_metrics.get("validation_pass_rate"), 0.0)
    alpha_all = safe_float(last_metrics.get("all_window_alpha"), 0.0)
    eff_map = profile_effectiveness(recent_rounds, window=8)
    preferred_profile = "r1_baseline"
    route_reason = ROUTE_STABILITY_SCAN

    if stage_key == STAGE_FLOW_RECOVERY:
        if stagnation_count >= 2:
            cycle = ["r2_event_expansion", "r4_alpha_rescue", "r3_precision_recovery"]
            preferred_profile = cycle[(loop_index + stagnation_count) % len(cycle)]
            route_reason = ROUTE_STABILITY_SCAN
        elif trades_total <= 0 or veto_rate > 0.95:
            preferred_profile = "r2_event_expansion"
            route_reason = ROUTE_TRADE_DENSITY_LOW
        elif floor_comp < 0.60:
            preferred_profile = "r3_precision_recovery"
            route_reason = ROUTE_PRECISION_UNMET
        else:
            preferred_profile = "r4_alpha_rescue"
            route_reason = ROUTE_ALPHA_NEGATIVE
    else:
        if stagnation_count >= 2:
            cycle = ["r4_alpha_rescue", "r1_baseline", "r3_precision_recovery"]
            preferred_profile = cycle[(loop_index + stagnation_count) % len(cycle)]
            route_reason = ROUTE_STABILITY_SCAN
        elif floor_comp < 0.60:
            preferred_profile = "r3_precision_recovery"
            route_reason = ROUTE_PRECISION_UNMET
        elif pass_rate < 0.20 or alpha_all <= 0.0:
            preferred_profile = "r4_alpha_rescue"
            route_reason = ROUTE_ALPHA_NEGATIVE
        else:
            preferred_profile = "r1_baseline"
            route_reason = ROUTE_STABILITY_SCAN

    candidates = list(PROFILE_PRESETS.keys())
    best_profile = max(candidates, key=lambda name: _profile_score(name, eff_map))
    if _profile_score(preferred_profile, eff_map) <= 0.0 and _profile_score(best_profile, eff_map) > 0.03:
        preferred_profile = best_profile
        route_reason = ROUTE_PROFILE_EFFECTIVENESS_OVERRIDE

    return _with_profile(preferred_profile, route_reason)


def alpha_supervisor_cmd(args: argparse.Namespace) -> list[str]:
    cmd = [
        "python",
        "scripts/alpha_supervisor.py",
        "--symbols",
        str(args.symbols),
        "--cycles",
        "1",
        "--max-rounds",
        str(max(1, int(args.max_rounds_per_loop))),
        "--target-pass-rate",
        f"{float(args.min_validation_pass_rate):.2f}",
        "--target-deploy-symbols",
        "1",
        "--target-deploy-rules",
        "1",
        "--target-all-alpha",
        f"{float(args.min_all_window_alpha):.2f}",
        "--target-deploy-alpha",
        "0.00",
        "--stable-rounds",
        "1",
        "--validation-mode",
        str(args.validation_mode),
        "--monitor-interval",
        f"{max(0.2, float(args.monitor_interval)):.2f}",
        "--monitor-export-interval",
        f"{max(0.0, float(args.monitor_export_interval)):.2f}",
    ]
    if bool(args.skip_ingest):
        cmd.append("--skip-ingest")
    if bool(args.with_monitor):
        cmd.append("--with-monitor")
    else:
        cmd.append("--no-with-monitor")
    return cmd


def export_dashboard() -> None:
    run_checked(["python", "scripts/export_dashboard_state.py"], env=os.environ.copy())


def gate_hit(metrics: dict[str, Any], gate: dict[str, Any]) -> bool:
    pass_ok = safe_float(metrics.get("validation_pass_rate"), 0.0) >= safe_float(gate.get("min_validation_pass_rate"), 0.20)
    alpha_ok = safe_float(metrics.get("all_window_alpha"), -999.0) > safe_float(gate.get("min_all_window_alpha"), 0.0)
    deploy_required = bool(gate.get("require_deploy_ready", True))
    deploy_ok = (not deploy_required) or bool(metrics.get("deploy_ready"))
    return bool(pass_ok and alpha_ok and deploy_ok)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run legacy BTC training until convergence gate is satisfied.")
    parser.add_argument("--symbols", default="BTCUSDT")
    parser.add_argument("--validation-mode", choices=("standard", "recovery"), default="standard")
    parser.add_argument("--max-rounds-per-loop", type=int, default=2)
    parser.add_argument("--min-validation-pass-rate", type=float, default=0.20)
    parser.add_argument("--min-all-window-alpha", type=float, default=0.0)
    parser.add_argument("--require-deploy-ready", dest="require_deploy_ready", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--required-streak", type=int, default=2)
    parser.add_argument("--stagnation-rounds", type=int, default=6)
    parser.add_argument("--hard-cap", type=int, default=50)
    parser.add_argument("--flow-gate-max-veto-rate", type=float, default=0.93)
    parser.add_argument("--flow-gate-max-failsafe-rate", type=float, default=0.40)
    parser.add_argument("--flow-gate-min-trades", type=int, default=12)
    parser.add_argument("--flow-gate-required-streak", type=int, default=2)
    parser.add_argument("--flow-unlock-cap", type=int, default=FLOW_UNLOCK_CAP_DEFAULT)
    parser.add_argument("--quality-recovery-cap", type=int, default=QUALITY_RECOVERY_CAP_DEFAULT)
    parser.add_argument("--resume", dest="resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--skip-ingest", dest="skip_ingest", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--with-monitor", dest="with_monitor", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--monitor-interval", type=float, default=2.0)
    parser.add_argument("--monitor-export-interval", type=float, default=10.0)
    parser.add_argument("--cooldown-sec", type=float, default=2.0)
    parser.add_argument("--dry-run", action="store_true", default=False)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    gate = {
        "min_validation_pass_rate": float(args.min_validation_pass_rate),
        "min_all_window_alpha": float(args.min_all_window_alpha),
        "require_deploy_ready": bool(args.require_deploy_ready),
        "required_streak": max(1, int(args.required_streak)),
    }
    flow_gate = {
        "max_veto_rate": max(0.0, min(1.0, float(args.flow_gate_max_veto_rate))),
        "max_failsafe_veto_all_rate": max(0.0, min(1.0, float(args.flow_gate_max_failsafe_rate))),
        "min_trades_total_all_window": max(1, int(args.flow_gate_min_trades)),
        "required_streak": max(1, int(args.flow_gate_required_streak)),
    }
    flow_unlock_cap_cli = max(1, int(args.flow_unlock_cap))
    quality_recovery_cap_cli = max(1, int(args.quality_recovery_cap))
    default_hard_cap = max(1, int(args.hard_cap))

    state: dict[str, Any] = {
        "generated_at_utc": now_iso(),
        "status_key": "TRAINING_STATUS_RUNNING",
        "gate": gate,
        "flow_gate": flow_gate,
        "current_batch_key": BATCH_FLOW_UNLOCK,
        "batch_status_key": "STATUS_STALLED",
        "batch_outcome_reason_key": "BATCH_REASON_IN_PROGRESS",
        "batch_round_index": 0,
        "batch_round_cap": flow_unlock_cap_cli,
        "flow_unlock_cap": flow_unlock_cap_cli,
        "quality_recovery_cap": quality_recovery_cap_cli,
        "flow_unlock_rounds_run": 0,
        "quality_recovery_rounds_run": 0,
        "stage_key": STAGE_FLOW_RECOVERY,
        "active_objective_key": OBJECTIVE_FLOW_UNLOCK,
        "candidate_tier": CANDIDATE_TIER_EXPLORATORY,
        "flow_stage_progress": 0,
        "flow_stage_reason_key": FLOW_REASON_NEED_TRADES,
        "recovery_milestone_key": MILESTONE_M1_TRADES,
        "flow_gate_streak": 0,
        "flow_gate_achieved": False,
        "next_profile_name": "r2_event_expansion",
        "next_profile_route_reason_key": ROUTE_TRADE_DENSITY_LOW,
        "hard_cap": default_hard_cap,
        "stagnation_rounds": max(1, int(args.stagnation_rounds)),
        "loop_runs": 0,
        "stagnation_count": 0,
        "best_quality_score": -1.0,
        "best_flow_score": -1.0,
        "best_flow_overrides": {},
        "last_flow_score": 0.0,
        "last_objective_score": 0.0,
        "last_no_threshold_meets_floor": False,
        "current_streak": 0,
        "rounds": [],
    }
    if bool(args.resume):
        loaded = read_json(STATE_PATH)
        if loaded:
            state.update(loaded)
            state["gate"] = gate
            state["flow_gate"] = flow_gate
            state["hard_cap"] = default_hard_cap
            state["stagnation_rounds"] = max(1, int(args.stagnation_rounds))
            state["flow_unlock_cap"] = flow_unlock_cap_cli
            state["quality_recovery_cap"] = quality_recovery_cap_cli
            current_batch = str(state.get("current_batch_key") or BATCH_FLOW_UNLOCK)
            state["batch_round_cap"] = quality_recovery_cap_cli if current_batch == BATCH_QUALITY_RECOVERY else flow_unlock_cap_cli
            batch_round_index_loaded = max(0, safe_int(state.get("batch_round_index"), 0))
            batch_round_cap_loaded = max(1, safe_int(state.get("batch_round_cap"), 1))
            if (
                str(state.get("batch_outcome_reason_key") or "") == "BATCH_REASON_STAGE_CAP_REACHED"
                and batch_round_index_loaded < batch_round_cap_loaded
            ):
                state["batch_outcome_reason_key"] = "BATCH_REASON_IN_PROGRESS"
                state["batch_status_key"] = "STATUS_STALLED"

    last_metrics: dict[str, Any] | None = None
    if isinstance(state.get("rounds"), list) and state["rounds"]:
        maybe = state["rounds"][-1]
        if isinstance(maybe, dict):
            last_metrics = maybe.get("metrics") if isinstance(maybe.get("metrics"), dict) else None

    flow_unlock_cap = max(1, safe_int(state.get("flow_unlock_cap"), flow_unlock_cap_cli))
    quality_recovery_cap = max(1, safe_int(state.get("quality_recovery_cap"), quality_recovery_cap_cli))
    hard_cap = max(
        max(1, safe_int(state.get("hard_cap"), default_hard_cap)),
        flow_unlock_cap + quality_recovery_cap,
    )
    stagnation_rounds = max(1, safe_int(state.get("stagnation_rounds"), 6))
    best_quality = safe_float(state.get("best_quality_score"), -1.0)
    best_flow = safe_float(state.get("best_flow_score"), -1.0)
    best_flow_overrides = state.get("best_flow_overrides")
    if not isinstance(best_flow_overrides, dict):
        best_flow_overrides = {}
    current_streak = safe_int(state.get("current_streak"), 0)
    stagnation_count = safe_int(state.get("stagnation_count"), 0)
    loop_runs = safe_int(state.get("loop_runs"), 0)
    flow_unlock_rounds_run = safe_int(state.get("flow_unlock_rounds_run"), 0)
    quality_recovery_rounds_run = safe_int(state.get("quality_recovery_rounds_run"), 0)
    if flow_unlock_rounds_run <= 0 or quality_recovery_rounds_run <= 0:
        rounds_loaded = state.get("rounds")
        if isinstance(rounds_loaded, list):
            inferred_flow = 0
            inferred_alpha = 0
            for row in rounds_loaded:
                if not isinstance(row, dict):
                    continue
                row_stage = str(row.get("stage_key") or "")
                if row_stage == STAGE_ALPHA_RECOVERY:
                    inferred_alpha += 1
                else:
                    inferred_flow += 1
            if flow_unlock_rounds_run <= 0:
                flow_unlock_rounds_run = inferred_flow
            if quality_recovery_rounds_run <= 0:
                quality_recovery_rounds_run = inferred_alpha
    stage_key = str(state.get("stage_key") or STAGE_FLOW_RECOVERY)
    flow_gate_streak = safe_int(state.get("flow_gate_streak"), 0)
    flow_gate_achieved = bool(state.get("flow_gate_achieved", False)) or stage_key == STAGE_ALPHA_RECOVERY

    try:
        if bool(args.dry_run):
            state["generated_at_utc"] = now_iso()
            write_json(STATE_PATH, state)
            export_dashboard()
            print(json.dumps({"event": "TRAIN_LOOP_DRY_RUN_DONE", "state_path": str(STATE_PATH)}, ensure_ascii=False))
            return 0

        while loop_runs < hard_cap:
            loop_index = loop_runs + 1
            stage_key = STAGE_ALPHA_RECOVERY if flow_gate_achieved else STAGE_FLOW_RECOVERY
            active_objective_key = OBJECTIVE_ALPHA_RECOVERY if stage_key == STAGE_ALPHA_RECOVERY else OBJECTIVE_FLOW_UNLOCK
            candidate_tier = CANDIDATE_TIER_STRICT if stage_key == STAGE_ALPHA_RECOVERY else CANDIDATE_TIER_EXPLORATORY
            batch_key = BATCH_QUALITY_RECOVERY if stage_key == STAGE_ALPHA_RECOVERY else BATCH_FLOW_UNLOCK
            batch_round_cap = quality_recovery_cap if batch_key == BATCH_QUALITY_RECOVERY else flow_unlock_cap
            batch_round_index = quality_recovery_rounds_run if batch_key == BATCH_QUALITY_RECOVERY else flow_unlock_rounds_run
            if batch_round_index >= batch_round_cap:
                state.update(
                    {
                        "generated_at_utc": now_iso(),
                        "status_key": "TRAINING_STATUS_STAGNATED"
                        if stage_key == STAGE_ALPHA_RECOVERY
                        else STATUS_FLOW_LOCK,
                        "current_batch_key": batch_key,
                        "batch_status_key": "STATUS_STALLED",
                        "batch_outcome_reason_key": "BATCH_REASON_STAGE_CAP_REACHED",
                        "batch_round_index": batch_round_index,
                        "batch_round_cap": batch_round_cap,
                        "flow_unlock_rounds_run": flow_unlock_rounds_run,
                        "quality_recovery_rounds_run": quality_recovery_rounds_run,
                    }
                )
                write_json(STATE_PATH, state)
                export_dashboard()
                print(
                    json.dumps(
                        {
                            "event": "TRAIN_LOOP_BATCH_CAP_REACHED",
                            "batch_key": batch_key,
                            "batch_round_index": batch_round_index,
                            "batch_round_cap": batch_round_cap,
                            "loop_runs": loop_runs,
                        },
                        ensure_ascii=False,
                    )
                )
                return 0

            rounds_snapshot = state.get("rounds")
            rounds_snapshot = rounds_snapshot if isinstance(rounds_snapshot, list) else []
            profile_name, profile_route_reason_key, base_overrides = choose_meta_overrides(
                last_metrics=last_metrics,
                loop_index=loop_index,
                stagnation_count=stagnation_count,
                stage_key=stage_key,
                recent_rounds=rounds_snapshot,
            )
            if stage_key == STAGE_FLOW_RECOVERY:
                overrides = apply_flow_unlock_batch(loop_index=loop_index, base_overrides=base_overrides)
            else:
                overrides = apply_quality_recovery_batch(
                    loop_index=loop_index,
                    base_overrides=base_overrides,
                    anchor_overrides=best_flow_overrides if best_flow_overrides else base_overrides,
                )
            profile_route_reason_key = ROUTE_BATCH_EXPLORATION
            env = os.environ.copy()
            env.update(overrides)

            started_at = now_iso()
            run_checked(alpha_supervisor_cmd(args), env=env)
            metrics = collect_latest_metrics()
            no_threshold_meets_floor = bool(
                safe_float(metrics.get("precision_floor_compliance_rate"), 0.0) <= 0.0
                and safe_float(metrics.get("veto_all_rate"), 0.0) >= 0.999
            )
            q_score = quality_score(metrics)
            f_score = flow_score(metrics)
            this_gate_hit = gate_hit(metrics=metrics, gate=gate)
            current_streak = (current_streak + 1) if this_gate_hit else 0
            flow_stage_progress, recovery_milestone_key, flow_stage_reason_key, this_flow_milestone_hit = flow_milestone_state(
                metrics,
                flow_gate=flow_gate,
            )
            this_flow_gate_hit = _flow_gate_hit(metrics=metrics, flow_gate=flow_gate)
            flow_gate_streak = (flow_gate_streak + 1) if this_flow_gate_hit else 0
            if flow_gate_streak >= safe_int(flow_gate.get("required_streak"), 1):
                flow_gate_achieved = True
            next_stage_key = STAGE_ALPHA_RECOVERY if flow_gate_achieved else STAGE_FLOW_RECOVERY
            objective_score = q_score if active_objective_key == OBJECTIVE_ALPHA_RECOVERY else f_score
            batch_round_index += 1
            if batch_key == BATCH_QUALITY_RECOVERY:
                quality_recovery_rounds_run = batch_round_index
            else:
                flow_unlock_rounds_run = batch_round_index

            improved = objective_score > ((best_quality if active_objective_key == OBJECTIVE_ALPHA_RECOVERY else best_flow) + 1e-8)
            if improved:
                if active_objective_key == OBJECTIVE_ALPHA_RECOVERY:
                    best_quality = q_score
                else:
                    best_flow = f_score
                    best_flow_overrides = dict(overrides)
                stagnation_count = 0
            else:
                stagnation_count += 1

            if q_score > best_quality:
                best_quality = q_score
            if f_score > best_flow:
                best_flow = f_score
                if stage_key == STAGE_FLOW_RECOVERY:
                    best_flow_overrides = dict(overrides)

            if no_threshold_meets_floor:
                batch_status_key = "STATUS_VETO_ALL"
                batch_outcome_reason_key = "BATCH_REASON_NO_THRESHOLD_MEETS_PRECISION_FLOOR"
            elif stage_key == STAGE_FLOW_RECOVERY and this_flow_gate_hit:
                batch_status_key = "STATUS_STABLE"
                batch_outcome_reason_key = "BATCH_REASON_FLOW_GATE_HIT"
            elif stage_key == STAGE_ALPHA_RECOVERY and this_gate_hit:
                batch_status_key = "STATUS_STABLE"
                batch_outcome_reason_key = "BATCH_REASON_QUALITY_GATE_HIT"
            else:
                batch_status_key = "STATUS_STALLED"
                batch_outcome_reason_key = "BATCH_REASON_IN_PROGRESS"

            round_entry = {
                "loop_index": loop_index,
                "started_at_utc": started_at,
                "ended_at_utc": now_iso(),
                "profile_name": profile_name,
                "profile_route_reason_key": profile_route_reason_key,
                "batch_key": batch_key,
                "batch_round_index": batch_round_index,
                "batch_round_cap": batch_round_cap,
                "batch_status_key": batch_status_key,
                "batch_outcome_reason_key": batch_outcome_reason_key,
                "no_threshold_meets_precision_floor": no_threshold_meets_floor,
                "stage_key": stage_key,
                "active_objective_key": active_objective_key,
                "candidate_tier": candidate_tier,
                "overrides": overrides,
                "override_snapshot": extract_override_snapshot(overrides),
                "metrics": metrics,
                "gate_hit": this_gate_hit,
                "flow_stage_progress": flow_stage_progress,
                "flow_stage_reason_key": flow_stage_reason_key,
                "recovery_milestone_key": recovery_milestone_key,
                "flow_milestone_hit": this_flow_milestone_hit,
                "flow_gate_hit": this_flow_gate_hit,
                "flow_gate_streak": flow_gate_streak,
                "flow_gate_achieved": flow_gate_achieved,
                "quality_score": q_score,
                "flow_score": f_score,
                "objective_score": objective_score,
                "improved": improved,
                "current_streak": current_streak,
                "stagnation_count": stagnation_count,
            }

            rounds = state.get("rounds")
            if not isinstance(rounds, list):
                rounds = []
            rounds.append(round_entry)

            loop_runs = loop_index
            next_active_objective_key = OBJECTIVE_ALPHA_RECOVERY if next_stage_key == STAGE_ALPHA_RECOVERY else OBJECTIVE_FLOW_UNLOCK
            next_candidate_tier = CANDIDATE_TIER_STRICT if next_stage_key == STAGE_ALPHA_RECOVERY else CANDIDATE_TIER_EXPLORATORY
            next_batch_key = BATCH_QUALITY_RECOVERY if next_stage_key == STAGE_ALPHA_RECOVERY else BATCH_FLOW_UNLOCK
            next_batch_round_cap = quality_recovery_cap if next_batch_key == BATCH_QUALITY_RECOVERY else flow_unlock_cap
            next_batch_round_index = quality_recovery_rounds_run if next_batch_key == BATCH_QUALITY_RECOVERY else flow_unlock_rounds_run
            next_profile_name, next_profile_route_reason_key, _ = choose_meta_overrides(
                last_metrics=metrics,
                loop_index=loop_index + 1,
                stagnation_count=stagnation_count,
                stage_key=next_stage_key,
                recent_rounds=rounds,
            )
            state.update(
                {
                    "generated_at_utc": now_iso(),
                    "status_key": "TRAINING_STATUS_RUNNING",
                    "current_batch_key": next_batch_key,
                    "batch_status_key": batch_status_key,
                    "batch_outcome_reason_key": batch_outcome_reason_key,
                    "batch_round_index": next_batch_round_index,
                    "batch_round_cap": next_batch_round_cap,
                    "flow_unlock_cap": flow_unlock_cap,
                    "quality_recovery_cap": quality_recovery_cap,
                    "flow_unlock_rounds_run": flow_unlock_rounds_run,
                    "quality_recovery_rounds_run": quality_recovery_rounds_run,
                    "stage_key": next_stage_key,
                    "active_objective_key": next_active_objective_key,
                    "candidate_tier": next_candidate_tier,
                    "flow_stage_progress": flow_stage_progress,
                    "flow_stage_reason_key": flow_stage_reason_key,
                    "recovery_milestone_key": recovery_milestone_key,
                    "flow_gate_streak": flow_gate_streak,
                    "flow_gate_achieved": flow_gate_achieved,
                    "next_profile_name": next_profile_name,
                    "next_profile_route_reason_key": next_profile_route_reason_key,
                    "last_profile_name": profile_name,
                    "last_profile_route_reason_key": profile_route_reason_key,
                    "loop_runs": loop_runs,
                    "best_quality_score": best_quality,
                    "best_flow_score": best_flow,
                    "best_flow_overrides": best_flow_overrides,
                    "last_flow_score": f_score,
                    "last_objective_score": objective_score,
                    "last_no_threshold_meets_floor": no_threshold_meets_floor,
                    "current_streak": current_streak,
                    "stagnation_count": stagnation_count,
                    "last_run_id": metrics.get("run_id", ""),
                    "last_metrics": metrics,
                    "rounds": rounds,
                }
            )

            write_json(STATE_PATH, state)
            export_dashboard()
            last_metrics = metrics

            if no_threshold_meets_floor:
                state["status_key"] = STATUS_FLOW_LOCK if stage_key == STAGE_FLOW_RECOVERY else "TRAINING_STATUS_STAGNATED"
                state["batch_status_key"] = "STATUS_VETO_ALL"
                state["batch_outcome_reason_key"] = "BATCH_REASON_NO_THRESHOLD_MEETS_PRECISION_FLOOR"
                state["generated_at_utc"] = now_iso()
                write_json(STATE_PATH, state)
                export_dashboard()
                print(
                    json.dumps(
                        {
                            "event": "TRAIN_LOOP_BATCH_VETO_ALL",
                            "loop_runs": loop_runs,
                            "batch_key": batch_key,
                            "run_id": metrics.get("run_id", ""),
                        },
                        ensure_ascii=False,
                    )
                )
                return 0

            if current_streak >= safe_int(gate.get("required_streak"), 2):
                state["status_key"] = "TRAINING_STATUS_CONVERGED"
                state["batch_status_key"] = "STATUS_STABLE"
                state["batch_outcome_reason_key"] = "BATCH_REASON_QUALITY_GATE_HIT"
                write_json(STATE_PATH, state)
                export_dashboard()
                print(
                    json.dumps(
                        {
                            "event": "TRAIN_LOOP_CONVERGED",
                            "loop_runs": loop_runs,
                            "current_streak": current_streak,
                            "run_id": metrics.get("run_id", ""),
                        },
                        ensure_ascii=False,
                    )
                )
                return 0

            if stagnation_count >= stagnation_rounds:
                state["status_key"] = STATUS_FLOW_LOCK if not flow_gate_achieved else "TRAINING_STATUS_STAGNATED"
                state["batch_status_key"] = "STATUS_STALLED"
                state["batch_outcome_reason_key"] = "BATCH_REASON_STAGNATION_LIMIT"
                write_json(STATE_PATH, state)
                export_dashboard()
                print(
                    json.dumps(
                        {
                            "event": "TRAIN_LOOP_FLOW_LOCK" if state["status_key"] == STATUS_FLOW_LOCK else "TRAIN_LOOP_STAGNATED",
                            "loop_runs": loop_runs,
                            "stagnation_count": stagnation_count,
                            "run_id": metrics.get("run_id", ""),
                        },
                        ensure_ascii=False,
                    )
                )
                return 0

            time.sleep(max(0.0, float(args.cooldown_sec)))

        state["status_key"] = STATUS_FLOW_LOCK if not flow_gate_achieved else "TRAINING_STATUS_HALTED"
        state["batch_status_key"] = "STATUS_STALLED"
        state["batch_outcome_reason_key"] = "BATCH_REASON_HARD_CAP_REACHED"
        state["generated_at_utc"] = now_iso()
        write_json(STATE_PATH, state)
        export_dashboard()
        print(
            json.dumps(
                {
                    "event": "TRAIN_LOOP_FLOW_LOCK"
                    if state["status_key"] == STATUS_FLOW_LOCK
                    else "TRAIN_LOOP_HARD_CAP_REACHED",
                    "loop_runs": loop_runs,
                    "hard_cap": hard_cap,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        state["status_key"] = "TRAINING_STATUS_HALTED"
        state["generated_at_utc"] = now_iso()
        state["last_error"] = str(exc)
        write_json(STATE_PATH, state)
        try:
            export_dashboard()
        except Exception:
            pass
        print(json.dumps({"event": "TRAIN_LOOP_FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
