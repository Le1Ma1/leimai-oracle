from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_PATH = ROOT / "engine" / "artifacts" / "control" / "ml_tune_state.json"
DEFAULT_DECISION_PATH = ROOT / "engine" / "artifacts" / "control" / "ml_autotune_decision.json"
DEFAULT_ITERATION_ROOT = ROOT / "engine" / "artifacts" / "optimization" / "single" / "iterations"

DEFAULT_TARGETS: dict[str, Any] = {
    "target_pass_rate": 0.20,
    "target_all_alpha": -2.0,
    "target_deploy_alpha": 0.0,
    "target_deploy_symbols": 1,
    "target_deploy_rules": 2,
    "stable_rounds": 1,
    "cycles": 2,
    "max_rounds": 2,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_event(event: str, **kwargs: Any) -> None:
    print(json.dumps({"ts_utc": utc_now_iso(), "event": event, **kwargs}, ensure_ascii=False))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_targets(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(DEFAULT_TARGETS)
    if isinstance(raw, dict):
        base.update(raw)
    return {
        "target_pass_rate": _clamp(_to_float(base.get("target_pass_rate"), 0.20), 0.01, 0.95),
        "target_all_alpha": _clamp(_to_float(base.get("target_all_alpha"), -2.0), -20.0, 2.0),
        "target_deploy_alpha": _clamp(_to_float(base.get("target_deploy_alpha"), 0.0), -2.0, 2.0),
        "target_deploy_symbols": max(1, _to_int(base.get("target_deploy_symbols"), 1)),
        "target_deploy_rules": max(1, _to_int(base.get("target_deploy_rules"), 2)),
        "stable_rounds": max(1, _to_int(base.get("stable_rounds"), 1)),
        "cycles": max(1, _to_int(base.get("cycles"), 2)),
        "max_rounds": max(1, _to_int(base.get("max_rounds"), 2)),
    }


def build_default_state() -> dict[str, Any]:
    targets = normalize_targets(None)
    return {
        "version": 1,
        "updated_at": utc_now_iso(),
        "current_targets": targets,
        "last_good_targets": targets,
        "last_metrics": {},
        "last_good_metrics": {},
        "degrade_streak": 0,
    }


def load_state(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if not payload:
        return build_default_state()
    state = build_default_state()
    state.update(payload)
    state["current_targets"] = normalize_targets(payload.get("current_targets") if isinstance(payload, dict) else None)
    state["last_good_targets"] = normalize_targets(payload.get("last_good_targets") if isinstance(payload, dict) else None)
    state["last_metrics"] = payload.get("last_metrics", {}) if isinstance(payload.get("last_metrics"), dict) else {}
    state["last_good_metrics"] = payload.get("last_good_metrics", {}) if isinstance(payload.get("last_good_metrics"), dict) else {}
    state["degrade_streak"] = max(0, _to_int(payload.get("degrade_streak"), 0))
    return state


def find_latest_iteration_report(root: Path) -> Path | None:
    if not root.exists():
        return None
    candidates = sorted(root.rglob("iteration_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def extract_iteration_metrics(report: dict[str, Any]) -> dict[str, Any]:
    round_reports = report.get("round_reports", []) if isinstance(report.get("round_reports"), list) else []
    last_round = round_reports[-1] if round_reports and isinstance(round_reports[-1], dict) else {}
    delta_pack = last_round.get("delta_vs_prev_round", {}) if isinstance(last_round.get("delta_vs_prev_round"), dict) else {}
    validation = last_round.get("validation_metrics", {}) if isinstance(last_round.get("validation_metrics"), dict) else {}
    best_score = report.get("best_round_score", {}) if isinstance(report.get("best_round_score"), dict) else {}

    return {
        "run_id": str(report.get("final_run_id") or report.get("best_round_run_id") or ""),
        "ts_utc": str(report.get("ts_utc") or utc_now_iso()),
        "objective_balance_score": _to_float(
            report.get("final_objective_balance_score"),
            _to_float(best_score.get("objective_balance_score"), 0.0),
        ),
        "delta_vs_prev_round": _to_float(
            delta_pack.get("objective_balance_score"),
            0.0,
        ),
        "stability_streak": max(0, _to_int(report.get("stability_streak"), 0)),
        "validation_pass_rate": _to_float(
            best_score.get("validation_pass_rate"),
            _to_float(validation.get("validation_pass_rate"), 0.0),
        ),
        "all_window_avg_alpha_vs_spot": _to_float(
            best_score.get("all_window_avg_alpha_vs_spot"),
            _to_float(validation.get("all_window_avg_alpha_vs_spot"), 0.0),
        ),
        "deploy_avg_alpha_vs_spot": _to_float(
            best_score.get("deploy_avg_alpha_vs_spot"),
            _to_float(validation.get("deploy_avg_alpha_vs_spot"), 0.0),
        ),
        "deploy_total_symbols": max(
            0,
            _to_int(validation.get("deploy_total_symbols"), 0),
        ),
        "deploy_total_rules": max(
            0,
            _to_int(validation.get("deploy_total_rules"), 0),
        ),
    }


def tighten_targets(current: dict[str, Any], max_delta_pct: float) -> dict[str, Any]:
    ratio = max(0.0, float(max_delta_pct)) / 100.0
    out = dict(current)
    out["target_pass_rate"] = _clamp(_to_float(current.get("target_pass_rate"), 0.20) * (1.0 + ratio), 0.01, 0.95)

    all_alpha = _to_float(current.get("target_all_alpha"), -2.0)
    if all_alpha < 0:
        out["target_all_alpha"] = min(0.0, all_alpha * (1.0 - ratio))
    elif all_alpha > 0:
        out["target_all_alpha"] = all_alpha * (1.0 + ratio)
    else:
        out["target_all_alpha"] = 0.0
    out["target_all_alpha"] = _clamp(out["target_all_alpha"], -20.0, 2.0)

    deploy_alpha = _to_float(current.get("target_deploy_alpha"), 0.0)
    if deploy_alpha < 0:
        out["target_deploy_alpha"] = min(0.0, deploy_alpha * (1.0 - ratio))
    elif deploy_alpha > 0:
        out["target_deploy_alpha"] = deploy_alpha * (1.0 + ratio)
    else:
        out["target_deploy_alpha"] = 0.0
    out["target_deploy_alpha"] = _clamp(out["target_deploy_alpha"], -2.0, 2.0)
    return normalize_targets(out)


def write_env_file(path: Path, targets: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"ML_TARGET_PASS_RATE={_to_float(targets.get('target_pass_rate'), 0.20):.6f}",
        f"ML_TARGET_ALL_ALPHA={_to_float(targets.get('target_all_alpha'), -2.0):.6f}",
        f"ML_TARGET_DEPLOY_ALPHA={_to_float(targets.get('target_deploy_alpha'), 0.0):.6f}",
        f"ML_TARGET_DEPLOY_SYMBOLS={max(1, _to_int(targets.get('target_deploy_symbols'), 1))}",
        f"ML_TARGET_DEPLOY_RULES={max(1, _to_int(targets.get('target_deploy_rules'), 2))}",
        f"ML_TARGET_STABLE_ROUNDS={max(1, _to_int(targets.get('stable_rounds'), 1))}",
        f"ML_TARGET_CYCLES={max(1, _to_int(targets.get('cycles'), 2))}",
        f"ML_TARGET_MAX_ROUNDS={max(1, _to_int(targets.get('max_rounds'), 2))}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bounded ML autotune with rollback safeguards.")
    parser.add_argument("--mode", choices=("prepare", "update"), default="update")
    parser.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--decision-path", default=str(DEFAULT_DECISION_PATH))
    parser.add_argument("--report-path", default="")
    parser.add_argument("--emit-env-path", default="")
    parser.add_argument("--force-tune", action="store_true")
    parser.add_argument("--max-delta-pct", type=float, default=float(os.getenv("ML_AUTOTUNE_MAX_DELTA_PCT", "5")))
    parser.add_argument("--min-stability-streak", type=int, default=int(os.getenv("ML_AUTOTUNE_MIN_STABILITY_STREAK", "2")))
    parser.add_argument(
        "--rollback-on-degrade-streak",
        type=int,
        default=int(os.getenv("ML_AUTOTUNE_ROLLBACK_ON_DEGRADE_STREAK", "2")),
    )
    return parser.parse_args()


def run_prepare_mode(args: argparse.Namespace) -> int:
    state_path = Path(str(args.state_path))
    decision_path = Path(str(args.decision_path))
    state = load_state(state_path)
    state["updated_at"] = utc_now_iso()
    write_json(state_path, state)

    targets = normalize_targets(state.get("current_targets"))
    if str(args.emit_env_path).strip():
        write_env_file(Path(str(args.emit_env_path)), targets)

    decision = {
        "ts_utc": utc_now_iso(),
        "mode": "prepare",
        "action": "emit_targets",
        "state_path": str(state_path),
        "targets": targets,
    }
    write_json(decision_path, decision)
    log_event("ML_AUTOTUNE_PREPARE_DONE", state_path=str(state_path), decision_path=str(decision_path))
    return 0


def run_update_mode(args: argparse.Namespace) -> int:
    state_path = Path(str(args.state_path))
    decision_path = Path(str(args.decision_path))
    report_path = Path(str(args.report_path)) if str(args.report_path).strip() else find_latest_iteration_report(DEFAULT_ITERATION_ROOT)

    state = load_state(state_path)
    targets_before = normalize_targets(state.get("current_targets"))
    degrade_streak = max(0, _to_int(state.get("degrade_streak"), 0))
    decision: dict[str, Any] = {
        "ts_utc": utc_now_iso(),
        "mode": "update",
        "state_path": str(state_path),
        "report_path": str(report_path) if report_path else "",
        "targets_before": targets_before,
        "action": "hold_targets",
    }

    if report_path is None or not report_path.exists():
        decision["action"] = "hold_targets"
        decision["reason"] = "missing_iteration_report"
        write_json(state_path, state)
        if str(args.emit_env_path).strip():
            write_env_file(Path(str(args.emit_env_path)), targets_before)
        write_json(decision_path, decision)
        log_event("ML_AUTOTUNE_UPDATE_SKIPPED", reason="missing_iteration_report")
        return 0

    report = load_json(report_path)
    metrics = extract_iteration_metrics(report)
    prev_metrics = state.get("last_metrics", {}) if isinstance(state.get("last_metrics"), dict) else {}
    prev_obj = _to_float(prev_metrics.get("objective_balance_score"), metrics["objective_balance_score"])
    current_obj = _to_float(metrics.get("objective_balance_score"), 0.0)
    degraded = bool(prev_metrics) and current_obj + 1e-12 < prev_obj
    if degraded:
        degrade_streak += 1
    else:
        degrade_streak = 0

    min_stability = max(1, int(args.min_stability_streak))
    improving_gate = bool(
        _to_float(metrics.get("delta_vs_prev_round"), 0.0) > 0.0
        and _to_int(metrics.get("stability_streak"), 0) >= min_stability
    )
    if bool(args.force_tune) and _to_float(metrics.get("delta_vs_prev_round"), 0.0) > 0.0:
        improving_gate = True

    targets_after = dict(targets_before)
    if improving_gate:
        targets_after = tighten_targets(targets_before, max_delta_pct=float(args.max_delta_pct))
        decision["action"] = "tighten_targets"
        decision["reason"] = "improving_gate_open"
        state["last_good_targets"] = targets_after
        state["last_good_metrics"] = metrics
        degrade_streak = 0
    elif degraded and degrade_streak >= max(1, int(args.rollback_on_degrade_streak)):
        rollback_targets = normalize_targets(state.get("last_good_targets"))
        targets_after = rollback_targets
        decision["action"] = "rollback_to_last_good"
        decision["reason"] = "degrade_streak_exceeded"
    else:
        decision["action"] = "hold_targets"
        decision["reason"] = "no_safe_improvement_signal"

    state["current_targets"] = normalize_targets(targets_after)
    state["degrade_streak"] = max(0, int(degrade_streak))
    state["last_metrics"] = metrics
    state["updated_at"] = utc_now_iso()
    write_json(state_path, state)

    if str(args.emit_env_path).strip():
        write_env_file(Path(str(args.emit_env_path)), state["current_targets"])

    decision.update(
        {
            "metrics": metrics,
            "previous_metrics": prev_metrics,
            "targets_after": state["current_targets"],
            "degrade_streak": state["degrade_streak"],
            "improving_gate": improving_gate,
            "min_stability_streak": min_stability,
            "max_delta_pct": float(args.max_delta_pct),
            "rollback_on_degrade_streak": max(1, int(args.rollback_on_degrade_streak)),
        }
    )
    write_json(decision_path, decision)
    log_event(
        "ML_AUTOTUNE_UPDATE_DONE",
        action=decision.get("action"),
        degrade_streak=state["degrade_streak"],
        report_path=str(report_path),
    )
    return 0


def main() -> int:
    args = parse_args()
    if str(os.getenv("ML_AUTOTUNE_ENABLED", "true")).strip().lower() in {"0", "false", "no", "off"}:
        log_event("ML_AUTOTUNE_DISABLED")
        return 0
    if args.mode == "prepare":
        return run_prepare_mode(args)
    return run_update_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())
