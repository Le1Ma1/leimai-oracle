from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OPT_ROOT = ROOT / "engine" / "artifacts" / "optimization" / "single"
MONITOR_ROOT = ROOT / "engine" / "artifacts" / "monitor"
PUBLIC_STATE_ROOT = ROOT / "monitor" / "public" / "state"


REASON_MAP = {
    "all_window_alpha": "REASON_ALL_WINDOW_ALPHA",
    "dsr": "REASON_DSR_BELOW_MIN",
    "final_score": "REASON_FINAL_SCORE_LOW",
    "friction": "REASON_FRICTION_WEAK",
    "meta_precision_floor": "REASON_LOW_PRECISION",
    "pbo": "REASON_HIGH_PBO",
    "purged_cv": "REASON_CV_FAIL",
    "walk_forward": "REASON_WF_FAIL",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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


def latest_validation_path(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        return p if p.is_absolute() else (ROOT / p).resolve()

    candidates = list(OPT_ROOT.rglob("validation_report.json"))
    if not candidates:
        raise FileNotFoundError("validation_report.json not found")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def all_window_alpha(validation: dict[str, Any]) -> float:
    rows = validation.get("summary_by_window", [])
    if not isinstance(rows, list):
        return 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("window")) == "all":
            return safe_float(row.get("avg_alpha_vs_spot"), 0.0)
    return 0.0


def compute_max_drawdown(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    values = [abs(safe_float(row.get("max_drawdown"), 0.0)) for row in rows if isinstance(row, dict)]
    if not values:
        return 0.0
    return float(max(values))


def compute_veto_rate(rows: list[dict[str, Any]], fallback: float) -> float:
    raw_total = 0
    kept_total = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_total += safe_int(row.get("entry_signals_raw"), 0)
        kept_total += safe_int(row.get("entry_signals_meta"), 0)
    if raw_total <= 0:
        return float(max(0.0, min(1.0, fallback)))
    return float(max(0.0, min(1.0, 1.0 - (kept_total / raw_total))))


def median_or_default(values: list[float], default: float = 0.0) -> float:
    clean = [float(v) for v in values]
    if not clean:
        return default
    return float(median(clean))


def map_rejection_breakdown(raw: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    counts = raw.get("failed_reason_counts", {})
    if not isinstance(counts, dict):
        return out
    for key, value in counts.items():
        count = safe_int(value, 0)
        if count <= 0:
            continue
        reason_key = REASON_MAP.get(str(key), "REASON_UNKNOWN")
        out.append({"reason_key": reason_key, "count": count})
    out.sort(key=lambda item: item["count"], reverse=True)
    return out


def classify_status(pass_rate: float, failsafe_rate: float) -> str:
    if failsafe_rate >= 0.999:
        return "STATUS_VETO_ALL"
    if pass_rate <= 0.0:
        return "STATUS_STALLED"
    if pass_rate < 0.2:
        return "STATUS_RECOVERY"
    return "STATUS_STABLE"


def classify_regime(status_key: str, alpha_all: float, failsafe_rate: float) -> str:
    if status_key == "STATUS_VETO_ALL" or failsafe_rate >= 0.5:
        return "REGIME_VETO_HOLD"
    if alpha_all > 0.0:
        return "REGIME_EXPANSION"
    return "REGIME_CONSOLIDATION"


def build_payload(validation: dict[str, Any], failure_breakdown: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = validation.get("rows", [])
    rows = rows if isinstance(rows, list) else []
    run_id = str(validation.get("run_id") or "")
    generated_at = str(validation.get("generated_at_utc") or "")
    pass_rate = safe_float(validation.get("pass_rate"), 0.0)
    alpha_all = all_window_alpha(validation)
    max_dd = compute_max_drawdown(rows)

    meta_summary = validation.get("meta_label_summary", {})
    meta_summary = meta_summary if isinstance(meta_summary, dict) else {}

    class_median = meta_summary.get("classification_median", {})
    class_median = class_median if isinstance(class_median, dict) else {}
    cpcv_median = meta_summary.get("cpcv_median", {})
    cpcv_median = cpcv_median if isinstance(cpcv_median, dict) else {}

    precision_floor = safe_float(meta_summary.get("precision_floor"), 0.0)
    failsafe_rate = safe_float(meta_summary.get("failsafe_veto_all_rate"), 0.0)
    compliance_rate = safe_float(cpcv_median.get("precision_floor_compliance_rate"), 0.0)
    veto_rate = compute_veto_rate(rows, fallback=failsafe_rate)

    pbo_values = [safe_float(row.get("pbo"), 0.0) for row in rows if isinstance(row, dict)]
    dsr_values = [safe_float(row.get("dsr"), 0.0) for row in rows if isinstance(row, dict)]
    threshold_values: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        meta = row.get("meta_label")
        if not isinstance(meta, dict):
            continue
        threshold = meta.get("threshold")
        if not isinstance(threshold, dict):
            continue
        selected = threshold.get("selected")
        if selected is None:
            continue
        threshold_values.append(safe_float(selected, 0.0))

    status_key = classify_status(pass_rate=pass_rate, failsafe_rate=failsafe_rate)
    regime_key = classify_regime(status_key=status_key, alpha_all=alpha_all, failsafe_rate=failsafe_rate)
    rejection_breakdown = map_rejection_breakdown(failure_breakdown)

    latest_synced = utc_now_iso()
    evolution_validation = {
        "artifact_version": "phase1_meta_label_v2",
        "generated_at_utc": latest_synced,
        "source_generated_at_utc": generated_at,
        "run_id": run_id,
        "status_key": status_key,
        "regime_key": regime_key,
        "metrics": {
            "all_window_alpha": alpha_all,
            "max_drawdown": max_dd,
            "pbo": median_or_default(pbo_values, 1.0),
            "dsr": median_or_default(dsr_values, -10.0),
            "precision": safe_float(class_median.get("precision"), 0.0),
            "f1": safe_float(class_median.get("f1"), 0.0),
            "pr_auc": safe_float(class_median.get("pr_auc"), 0.0),
            "precision_floor": precision_floor,
            "precision_floor_compliance_rate": compliance_rate,
            "failsafe_veto_all_rate": failsafe_rate,
            "veto_rate": veto_rate,
            "threshold_selected": median_or_default(threshold_values, 0.0),
        },
        "rejection_breakdown": rejection_breakdown,
    }

    visual_state = {
        "artifact_version": "phase1_meta_label_v2",
        "last_synced_at": latest_synced,
        "run_id": run_id,
        "status_key": status_key,
        "regime_key": regime_key,
        "heartbeat_ok": True,
        "live_alpha_vs_spot": alpha_all,
        "max_drawdown": max_dd,
        "meta_diagnostics": {
            "precision_floor": precision_floor,
            "precision_floor_compliance_rate": compliance_rate,
            "failsafe_veto_all_rate": failsafe_rate,
            "veto_rate": veto_rate,
            "threshold_selected": median_or_default(threshold_values, 0.0),
        },
        "rejection_breakdown": rejection_breakdown,
    }
    return evolution_validation, visual_state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export monitor dashboard state from latest validation artifacts.")
    parser.add_argument("--validation-path", default="", help="Optional explicit validation_report.json path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    validation_path = latest_validation_path(args.validation_path or None)
    base_dir = validation_path.parent

    validation = read_json(validation_path)
    failure_breakdown = read_json(base_dir / "failure_breakdown.json")
    if not validation:
        raise RuntimeError(f"empty validation payload: {validation_path}")

    evolution_validation, visual_state = build_payload(validation, failure_breakdown)

    monitor_evolution_path = MONITOR_ROOT / "evolution_validation.json"
    monitor_visual_path = MONITOR_ROOT / "visual_state.json"
    public_evolution_path = PUBLIC_STATE_ROOT / "evolution_validation.json"
    public_visual_path = PUBLIC_STATE_ROOT / "visual_state.json"

    write_json(monitor_evolution_path, evolution_validation)
    write_json(monitor_visual_path, visual_state)
    write_json(public_evolution_path, evolution_validation)
    write_json(public_visual_path, visual_state)

    print(
        json.dumps(
            {
                "event": "DASHBOARD_STATE_EXPORTED",
                "validation_path": str(validation_path),
                "monitor_evolution": str(monitor_evolution_path),
                "monitor_visual": str(monitor_visual_path),
                "public_evolution": str(public_evolution_path),
                "public_visual": str(public_visual_path),
                "run_id": evolution_validation.get("run_id"),
                "all_window_alpha": evolution_validation.get("metrics", {}).get("all_window_alpha"),
                "status_key": visual_state.get("status_key"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
