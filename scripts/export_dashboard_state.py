from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


ROOT = Path(__file__).resolve().parents[1]
OPT_ROOT = ROOT / "engine" / "artifacts" / "optimization" / "single"
ITERATION_ROOT = OPT_ROOT / "iterations"
CONTROL_ROOT = ROOT / "engine" / "artifacts" / "control"
MONITOR_ROOT = ROOT / "engine" / "artifacts" / "monitor"
LIVE_STATUS_PATH = MONITOR_ROOT / "live_status.json"
PUBLIC_STATE_ROOT = ROOT / "monitor" / "public" / "state"


REASON_MAP = {
    "all_window_alpha": "REASON_ALL_WINDOW_ALPHA",
    "dsr": "REASON_DSR_BELOW_MIN",
    "final_score": "REASON_FINAL_SCORE_LOW",
    "friction": "REASON_FRICTION_WEAK",
    "meta_precision_floor": "REASON_LOW_PRECISION",
    "pbo": "REASON_HIGH_PBO",
    "trade_density_low": "REASON_TRADE_DENSITY_LOW",
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


def _env_text(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def _load_env_files() -> None:
    if load_dotenv is None:
        return
    for file_path in (ROOT / ".env", ROOT / "engine" / ".env", ROOT / "support" / ".env"):
        try:
            load_dotenv(dotenv_path=file_path, override=False)
        except Exception:
            continue


def _http_request(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None = None,
    timeout_sec: float = 15.0,
) -> tuple[int, bytes]:
    req = urlrequest.Request(url=url, data=body, headers=headers, method=method.upper())
    try:
        with urlrequest.urlopen(req, timeout=max(2.0, float(timeout_sec))) as resp:
            return int(resp.getcode() or 200), resp.read()
    except urlerror.HTTPError as exc:
        try:
            payload = exc.read()
        except Exception:
            payload = b""
        return int(exc.code or 0), payload
    except Exception:
        return 0, b""


def _supabase_state_sync(files: dict[str, dict[str, Any]]) -> dict[str, Any]:
    supabase_url = _env_text("SUPABASE_URL", "").rstrip("/")
    service_key = _env_text("SUPABASE_SERVICE_ROLE_KEY", "")
    bucket = _env_text("SUPABASE_STATE_BUCKET", "monitor-state") or "monitor-state"
    prefix = _env_text("SUPABASE_STATE_PREFIX", "state").strip("/")
    sync_flag = _env_text("SUPABASE_STATE_SYNC", "").lower()
    sync_enabled = sync_flag not in {"0", "false", "no", "off"}

    if not sync_enabled:
        return {
            "enabled": False,
            "synced": False,
            "reason": "sync_disabled",
            "bucket": bucket,
            "prefix": prefix,
            "uploaded": 0,
            "failed": 0,
        }
    if not supabase_url or not service_key:
        return {
            "enabled": False,
            "synced": False,
            "reason": "missing_supabase_credentials",
            "bucket": bucket,
            "prefix": prefix,
            "uploaded": 0,
            "failed": 0,
        }

    base_headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
    }
    create_bucket_body = json.dumps(
        {
            "id": bucket,
            "name": bucket,
            "public": False,
            "file_size_limit": None,
            "allowed_mime_types": ["application/json"],
        }
    ).encode("utf-8")
    bucket_status, _ = _http_request(
        method="POST",
        url=f"{supabase_url}/storage/v1/bucket",
        headers={**base_headers, "Content-Type": "application/json"},
        body=create_bucket_body,
    )
    bucket_ready = bucket_status in {200, 201, 409}
    if not bucket_ready:
        list_status, list_payload = _http_request(
            method="GET",
            url=f"{supabase_url}/storage/v1/bucket",
            headers=base_headers,
        )
        if list_status == 200 and list_payload:
            try:
                rows = json.loads(list_payload.decode("utf-8", errors="replace"))
            except Exception:
                rows = []
            if isinstance(rows, list):
                bucket_ready = any(isinstance(item, dict) and str(item.get("id") or "") == bucket for item in rows)

    if not bucket_ready:
        return {
            "enabled": True,
            "synced": False,
            "reason": f"bucket_create_failed:{bucket_status}",
            "bucket": bucket,
            "prefix": prefix,
            "uploaded": 0,
            "failed": len(files),
        }

    uploaded: list[str] = []
    failed: list[str] = []
    encoded_bucket = urlparse.quote(bucket, safe="")
    for name, payload in files.items():
        object_path = f"{prefix}/{name}" if prefix else name
        encoded_path = urlparse.quote(object_path, safe="/")
        endpoint = f"{supabase_url}/storage/v1/object/{encoded_bucket}/{encoded_path}"
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        headers = {
            **base_headers,
            "Content-Type": "application/json",
            "x-upsert": "true",
        }
        status, _ = _http_request(method="POST", url=endpoint, headers=headers, body=body)
        if status < 200 or status >= 300:
            status, _ = _http_request(method="PUT", url=endpoint, headers=headers, body=body)
        if 200 <= status < 300:
            uploaded.append(name)
        else:
            failed.append(f"{name}:{status}")

    return {
        "enabled": True,
        "synced": len(failed) == 0,
        "reason": "" if len(failed) == 0 else "partial_failure",
        "bucket": bucket,
        "prefix": prefix,
        "uploaded": len(uploaded),
        "failed": len(failed),
        "uploaded_files": uploaded,
        "failed_files": failed,
    }


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


def parse_iso_utc(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


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


def resolve_artifact_path(raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    p = Path(raw)
    if p.is_absolute():
        return p
    return (ROOT / p).resolve()


def _extract_meta_metrics(validation: dict[str, Any]) -> dict[str, float]:
    rows = validation.get("rows", [])
    rows = rows if isinstance(rows, list) else []
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

    return {
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
    }


def _extract_validation_trades(validation: dict[str, Any], window_name: str = "all") -> tuple[int, float]:
    rows = validation.get("rows", [])
    rows = rows if isinstance(rows, list) else []
    selected = [row for row in rows if isinstance(row, dict) and str(row.get("window")) == window_name]
    if not selected:
        return 0, 0.0
    trades = [safe_int(row.get("trades"), 0) for row in selected]
    total = int(sum(trades))
    avg = float(total / len(trades)) if trades else 0.0
    return total, avg


def _round_quality_score(row: dict[str, Any]) -> float:
    objective = safe_float(row.get("objective_balance_score"), 0.0)
    if objective > 0.0:
        return objective
    pass_norm = max(0.0, min(1.0, safe_float(row.get("validation_pass_rate"), 0.0) / 0.20))
    alpha_norm = max(0.0, min(1.0, (safe_float(row.get("all_window_alpha"), -5.0) + 1.0) / 2.0))
    deploy_norm = 1.0 if bool(row.get("deploy_ready")) else 0.0
    robustness_norm = max(0.0, min(1.0, 1.0 - safe_float(row.get("pbo"), 1.0)))
    return float((0.35 * pass_norm) + (0.35 * alpha_norm) + (0.20 * deploy_norm) + (0.10 * robustness_norm))


def _latest_round_context(report: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    round_reports = report.get("round_reports", [])
    if not isinstance(round_reports, list) or not round_reports:
        return {}, {}
    latest_round = round_reports[-1] if isinstance(round_reports[-1], dict) else {}
    decision = latest_round.get("decision", {}) if isinstance(latest_round.get("decision"), dict) else {}
    return latest_round, decision


def _collect_iteration_rounds(*, max_rounds: int, gate: dict[str, Any]) -> list[dict[str, Any]]:
    if not ITERATION_ROOT.exists():
        return []
    files = sorted(
        (path for path in ITERATION_ROOT.rglob("iteration_*.json") if "decision_log" not in path.name),
        key=lambda p: p.stat().st_mtime,
    )
    if max_rounds > 0:
        files = files[-max_rounds:]

    out: list[dict[str, Any]] = []
    for idx, path in enumerate(files, start=1):
        iteration = read_json(path)
        if not iteration:
            continue
        final_artifacts = iteration.get("final_artifacts", {})
        final_artifacts = final_artifacts if isinstance(final_artifacts, dict) else {}
        validation_path = resolve_artifact_path(final_artifacts.get("validation_report"))
        failure_path = resolve_artifact_path(final_artifacts.get("failure_breakdown"))
        deploy_path = resolve_artifact_path(final_artifacts.get("deploy_pool"))
        validation = read_json(validation_path) if validation_path else {}
        failure = read_json(failure_path) if failure_path else {}
        deploy = read_json(deploy_path) if deploy_path else {}
        latest_round, decision = _latest_round_context(iteration)

        metrics = _extract_meta_metrics(validation)
        all_alpha = all_window_alpha(validation)
        validation_pass_rate = safe_float(
            validation.get("pass_rate"),
            safe_float((iteration.get("best_round_score") or {}).get("validation_pass_rate"), 0.0),
        )
        deploy_symbols = safe_int(deploy.get("total_symbols"), safe_int(failure.get("deploy_symbols"), 0))
        deploy_rules = safe_int(deploy.get("total_rules"), safe_int(failure.get("deploy_rules"), 0))
        deploy_ready = bool(failure.get("deploy_ready", False))
        status_key = classify_status(pass_rate=validation_pass_rate, failsafe_rate=metrics["failsafe_veto_all_rate"])
        regime_key = classify_regime(
            status_key=status_key,
            alpha_all=all_alpha,
            failsafe_rate=metrics["failsafe_veto_all_rate"],
        )
        rejection_breakdown = map_rejection_breakdown(failure)
        top_reason_key = rejection_breakdown[0]["reason_key"] if rejection_breakdown else "REASON_UNKNOWN"
        trades_total_all, trades_avg_all = _extract_validation_trades(validation, window_name="all")
        round_obj = {
            "round_index": idx,
            "ts_utc": str(iteration.get("ts_utc") or ""),
            "run_id": str(
                iteration.get("final_run_id")
                or iteration.get("best_round_run_id")
                or validation.get("run_id")
                or ""
            ),
            "status_key": status_key,
            "regime_key": regime_key,
            "validation_pass_rate": validation_pass_rate,
            "all_window_alpha": all_alpha,
            "deploy_ready": deploy_ready,
            "deploy_symbols": deploy_symbols,
            "deploy_rules": deploy_rules,
            "trades_total_all_window": trades_total_all,
            "trades_avg_all_window": trades_avg_all,
            "pbo": metrics["pbo"],
            "dsr": metrics["dsr"],
            "precision": metrics["precision"],
            "f1": metrics["f1"],
            "pr_auc": metrics["pr_auc"],
            "precision_floor": metrics["precision_floor"],
            "precision_floor_compliance_rate": metrics["precision_floor_compliance_rate"],
            "failsafe_veto_all_rate": metrics["failsafe_veto_all_rate"],
            "veto_rate": metrics["veto_rate"],
            "threshold_selected": metrics["threshold_selected"],
            "primary_bottleneck": str(decision.get("primary_bottleneck") or ""),
            "recommended_action": str(decision.get("recommended_action") or ""),
            "decision_rationale": str(decision.get("rationale") or ""),
            "round_profile": str(latest_round.get("profile") or ""),
            "config_snapshot": latest_round.get("config", {}) if isinstance(latest_round.get("config"), dict) else {},
            "objective_balance_score": safe_float(
                latest_round.get("objective_balance_score"),
                safe_float((iteration.get("best_round_score") or {}).get("objective_balance_score"), 0.0),
            ),
            "rejection_top_reason_key": str(top_reason_key),
            "rejection_breakdown": rejection_breakdown,
            "iteration_file": str(path),
        }
        gate_hit = bool(
            round_obj["validation_pass_rate"] >= safe_float(gate.get("min_validation_pass_rate"), 0.20)
            and round_obj["all_window_alpha"] > safe_float(gate.get("min_all_window_alpha"), 0.0)
            and (
                not bool(gate.get("require_deploy_ready", True))
                or bool(round_obj["deploy_ready"])
            )
        )
        round_obj["gate_hit"] = gate_hit
        round_obj["quality_score"] = _round_quality_score(round_obj)
        out.append(round_obj)
    return out


def _load_training_loop_state() -> dict[str, Any]:
    return read_json(CONTROL_ROOT / "training_loop_state.json")


def build_training_roadmap(*, latest_synced: str) -> dict[str, Any]:
    gate = {
        "min_validation_pass_rate": 0.20,
        "min_all_window_alpha": 0.0,
        "require_deploy_ready": True,
        "required_streak": 2,
    }
    loop_state = _load_training_loop_state()
    if isinstance(loop_state.get("gate"), dict):
        gate = {
            "min_validation_pass_rate": safe_float(loop_state["gate"].get("min_validation_pass_rate"), gate["min_validation_pass_rate"]),
            "min_all_window_alpha": safe_float(loop_state["gate"].get("min_all_window_alpha"), gate["min_all_window_alpha"]),
            "require_deploy_ready": bool(loop_state["gate"].get("require_deploy_ready", gate["require_deploy_ready"])),
            "required_streak": max(1, safe_int(loop_state["gate"].get("required_streak"), gate["required_streak"])),
        }

    rounds = _collect_iteration_rounds(max_rounds=240, gate=gate)
    current_streak = 0
    for row in reversed(rounds):
        if not bool(row.get("gate_hit")):
            break
        current_streak += 1
    best_round = max(rounds, key=lambda row: safe_float(row.get("quality_score"), 0.0), default={})
    latest_round = rounds[-1] if rounds else {}

    status_key = "TRAINING_STATUS_RUNNING"
    if current_streak >= safe_int(gate.get("required_streak"), 2) and rounds:
        status_key = "TRAINING_STATUS_CONVERGED"
    if rounds and safe_float(latest_round.get("validation_pass_rate"), 0.0) <= 0.0:
        status_key = "TRAINING_STATUS_STALLED"
    loop_status = str(loop_state.get("status_key") or "").strip()
    if loop_status:
        status_key = loop_status

    stagnation_rounds = safe_int(loop_state.get("stagnation_rounds"), 6)
    stagnation_count = safe_int(loop_state.get("stagnation_count"), 0)
    hard_cap = safe_int(loop_state.get("hard_cap"), 50)
    loop_runs = safe_int(loop_state.get("loop_runs"), 0)

    return {
        "artifact_version": "phase1_training_roadmap_v1",
        "generated_at_utc": latest_synced,
        "status_key": status_key,
        "gate": gate,
        "summary": {
            "rounds_total": len(rounds),
            "current_streak": current_streak,
            "required_streak": safe_int(gate.get("required_streak"), 2),
            "best_quality_score": safe_float(best_round.get("quality_score"), 0.0),
            "stagnation_count": stagnation_count,
            "stagnation_rounds": stagnation_rounds,
            "hard_cap": hard_cap,
            "loop_runs": loop_runs,
        },
        "latest_round": latest_round,
        "best_round": best_round,
        "rounds": rounds,
    }


def _runtime_phase_key(pipeline_state: str) -> str:
    value = str(pipeline_state or "").strip().lower()
    if value in {"running", "iterate", "iterating"}:
        return "PHASE_ITERATING"
    if value in {"validation", "validating"}:
        return "PHASE_VALIDATING"
    if value in {"finalizing", "finalize"}:
        return "PHASE_FINALIZING"
    return "PHASE_WAITING"


def _runtime_stall_reason_key(*, stall_reason: str, promotion_block_reason: str, has_active_process: bool) -> str:
    reason = str(stall_reason or "").strip().lower()
    block = str(promotion_block_reason or "").strip().lower()
    if "no_new_events" in reason:
        return "STALL_NO_NEW_EVENTS"
    if "target_not_met" in block:
        return "STALL_TARGET_NOT_MET"
    if not has_active_process:
        return "STALL_PROCESS_INACTIVE"
    return "STALL_UNKNOWN"


def _runtime_completion_reason_key(loop_status: str) -> str:
    status = str(loop_status or "").strip().upper()
    if status == "TRAINING_STATUS_CONVERGED":
        return "COMPLETION_GATE_HIT"
    if status == "TRAINING_STATUS_STAGNATED":
        return "COMPLETION_STAGNATED"
    if status == "TRAINING_STATUS_HALTED":
        return "COMPLETION_HALTED"
    return "COMPLETION_UNKNOWN"


def _extract_last_event_ts(live_status: dict[str, Any]) -> str:
    events = live_status.get("last_events", [])
    if isinstance(events, list) and events:
        last = events[-1]
        if isinstance(last, dict):
            value = str(last.get("ts_utc") or "").strip()
            if value:
                return value
    return ""


def _extract_started_at(live_status: dict[str, Any], loop_state: dict[str, Any]) -> str:
    round_payload = live_status.get("round", {})
    if isinstance(round_payload, dict):
        started = str(round_payload.get("started_at_utc") or "").strip()
        if started:
            return started

    rounds = loop_state.get("rounds", [])
    if isinstance(rounds, list) and rounds:
        last_round = rounds[-1]
        if isinstance(last_round, dict):
            started = str(last_round.get("started_at_utc") or "").strip()
            if started:
                return started
    return ""


def _runtime_status_key(*, pipeline_state: str, loop_status: str, has_active_process: bool) -> str:
    state = str(pipeline_state or "").strip().lower()
    loop = str(loop_status or "").strip().upper()
    if state in {"running", "iterate", "iterating", "validation", "validating", "finalizing"}:
        return "RUNTIME_RUNNING"
    if loop == "TRAINING_STATUS_CONVERGED" and not has_active_process:
        return "RUNTIME_COMPLETED"
    if loop in {"TRAINING_STATUS_STAGNATED", "TRAINING_STATUS_HALTED"} and not has_active_process:
        return "RUNTIME_STALLED"
    if state == "stalled":
        return "RUNTIME_STALLED"
    if has_active_process:
        return "RUNTIME_RUNNING"
    return "RUNTIME_IDLE"


def _notify_event_key(*, prev: dict[str, Any], runtime_status_key: str, run_id: str) -> tuple[str, int]:
    previous_status = str(prev.get("runtime_status_key") or "")
    previous_run_id = str(prev.get("run_id") or "")
    previous_seq = safe_int(prev.get("notify_seq"), 0)

    event_key = ""
    if run_id and run_id != previous_run_id:
        event_key = "NOTIFY_RUN_STARTED"
    elif previous_status != "RUNTIME_STALLED" and runtime_status_key == "RUNTIME_STALLED":
        event_key = "NOTIFY_STALLED"
    elif previous_status != "RUNTIME_COMPLETED" and runtime_status_key == "RUNTIME_COMPLETED":
        event_key = "NOTIFY_COMPLETED"
    elif previous_status == "RUNTIME_STALLED" and runtime_status_key == "RUNTIME_RUNNING":
        event_key = "NOTIFY_RESUMED"

    next_seq = previous_seq + 1 if event_key else previous_seq
    return event_key, next_seq


def build_training_runtime(*, latest_synced: str, training_roadmap: dict[str, Any], visual_state: dict[str, Any]) -> dict[str, Any]:
    loop_state = _load_training_loop_state()
    live_status = read_json(LIVE_STATUS_PATH)
    prev_runtime = read_json(MONITOR_ROOT / "training_runtime.json")

    pipeline_state = str(live_status.get("pipeline_state") or "").strip().lower()
    loop_status = str(loop_state.get("status_key") or training_roadmap.get("status_key") or "").strip()
    active_processes = live_status.get("active_processes", {})
    has_active_process = isinstance(active_processes, dict) and any(
        safe_int(pid, 0) > 0 for pid in active_processes.values()
    )

    runtime_status_key = _runtime_status_key(
        pipeline_state=pipeline_state,
        loop_status=loop_status,
        has_active_process=has_active_process,
    )
    phase_key = _runtime_phase_key(pipeline_state)

    run_id = str(
        live_status.get("active_run_id")
        or visual_state.get("run_id")
        or ((training_roadmap.get("latest_round") or {}).get("run_id") if isinstance(training_roadmap.get("latest_round"), dict) else "")
        or ""
    ).strip()
    started_at_utc = _extract_started_at(live_status, loop_state)
    started_dt = parse_iso_utc(started_at_utc)
    now_dt = parse_iso_utc(latest_synced) or datetime.now(timezone.utc)
    elapsed_sec = int(max(0.0, (now_dt - started_dt).total_seconds())) if started_dt else 0

    eta_payload = live_status.get("eta", {})
    eta_payload = eta_payload if isinstance(eta_payload, dict) else {}
    remaining_raw = eta_payload.get("seconds_remaining")
    remaining_sec = safe_int(remaining_raw, -1) if remaining_raw is not None else -1
    if remaining_sec < 0:
        remaining_sec = -1
    eta_utc = str(eta_payload.get("eta_utc") or "").strip()
    eta_confidence = str(eta_payload.get("confidence") or "low").strip().lower() or "low"

    progress = live_status.get("progress", {})
    progress = progress if isinstance(progress, dict) else {}
    cycle = live_status.get("cycle", {})
    cycle = cycle if isinstance(cycle, dict) else {}

    tasks_done = safe_int(progress.get("tasks_done"), 0)
    tasks_total = safe_int(progress.get("tasks_total"), 0)
    tasks_pct = safe_float(progress.get("tasks_pct"), 0.0)
    cycle_current = safe_int(cycle.get("current"), 0)
    cycle_total = safe_int(cycle.get("total"), 0)
    cycle_pct = safe_float(cycle.get("pct"), 0.0)

    stall_reason = str(live_status.get("stall_reason") or "").strip()
    promotion_block_reason = str(live_status.get("promotion_block_reason") or "").strip()
    stalled_reason_key = (
        _runtime_stall_reason_key(
            stall_reason=stall_reason,
            promotion_block_reason=promotion_block_reason,
            has_active_process=has_active_process,
        )
        if runtime_status_key == "RUNTIME_STALLED"
        else ""
    )

    completion_reason_key = (
        _runtime_completion_reason_key(loop_status)
        if runtime_status_key == "RUNTIME_COMPLETED"
        else ""
    )

    last_event_at_utc = _extract_last_event_ts(live_status)
    notify_event_key, notify_seq = _notify_event_key(
        prev=prev_runtime,
        runtime_status_key=runtime_status_key,
        run_id=run_id,
    )

    return {
        "artifact_version": "phase1_training_runtime_v1",
        "generated_at_utc": latest_synced,
        "runtime_status_key": runtime_status_key,
        "phase_key": phase_key,
        "run_id": run_id,
        "started_at_utc": started_at_utc,
        "elapsed_sec": elapsed_sec,
        "remaining_sec": None if remaining_sec < 0 else remaining_sec,
        "eta_utc": eta_utc or None,
        "eta_confidence": eta_confidence,
        "cycle_current": cycle_current,
        "cycle_total": cycle_total,
        "cycle_pct": cycle_pct,
        "tasks_done": tasks_done,
        "tasks_total": tasks_total,
        "tasks_pct": tasks_pct,
        "stalled_reason_key": stalled_reason_key,
        "completion_reason_key": completion_reason_key,
        "last_event_at_utc": last_event_at_utc or None,
        "last_sync_at_utc": str(visual_state.get("last_synced_at") or latest_synced),
        "notify_event_key": notify_event_key,
        "notify_seq": notify_seq,
    }


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
    _load_env_files()
    args = parse_args()
    validation_path = latest_validation_path(args.validation_path or None)
    base_dir = validation_path.parent

    validation = read_json(validation_path)
    failure_breakdown = read_json(base_dir / "failure_breakdown.json")
    if not validation:
        raise RuntimeError(f"empty validation payload: {validation_path}")

    evolution_validation, visual_state = build_payload(validation, failure_breakdown)
    latest_synced = str(evolution_validation.get("generated_at_utc") or utc_now_iso())
    training_roadmap = build_training_roadmap(latest_synced=latest_synced)
    training_runtime = build_training_runtime(
        latest_synced=latest_synced,
        training_roadmap=training_roadmap,
        visual_state=visual_state,
    )

    monitor_evolution_path = MONITOR_ROOT / "evolution_validation.json"
    monitor_visual_path = MONITOR_ROOT / "visual_state.json"
    monitor_training_path = MONITOR_ROOT / "training_roadmap.json"
    monitor_runtime_path = MONITOR_ROOT / "training_runtime.json"
    public_evolution_path = PUBLIC_STATE_ROOT / "evolution_validation.json"
    public_visual_path = PUBLIC_STATE_ROOT / "visual_state.json"
    public_training_path = PUBLIC_STATE_ROOT / "training_roadmap.json"
    public_runtime_path = PUBLIC_STATE_ROOT / "training_runtime.json"
    write_public_snapshots = _env_text("DASHBOARD_PUBLIC_SNAPSHOT_WRITE", "1").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }

    write_json(monitor_evolution_path, evolution_validation)
    write_json(monitor_visual_path, visual_state)
    write_json(monitor_training_path, training_roadmap)
    write_json(monitor_runtime_path, training_runtime)
    if write_public_snapshots:
        write_json(public_evolution_path, evolution_validation)
        write_json(public_visual_path, visual_state)
        write_json(public_training_path, training_roadmap)
        write_json(public_runtime_path, training_runtime)
    supabase_sync = _supabase_state_sync(
        {
            "evolution_validation.json": evolution_validation,
            "visual_state.json": visual_state,
            "training_roadmap.json": training_roadmap,
            "training_runtime.json": training_runtime,
        }
    )

    print(
        json.dumps(
            {
                "event": "DASHBOARD_STATE_EXPORTED",
                "validation_path": str(validation_path),
                "monitor_evolution": str(monitor_evolution_path),
                "monitor_visual": str(monitor_visual_path),
                "monitor_training": str(monitor_training_path),
                "monitor_runtime": str(monitor_runtime_path),
                "public_evolution": str(public_evolution_path),
                "public_visual": str(public_visual_path),
                "public_training": str(public_training_path),
                "public_runtime": str(public_runtime_path),
                "public_snapshot_written": write_public_snapshots,
                "run_id": evolution_validation.get("run_id"),
                "all_window_alpha": evolution_validation.get("metrics", {}).get("all_window_alpha"),
                "status_key": visual_state.get("status_key"),
                "training_status_key": training_roadmap.get("status_key"),
                "runtime_status_key": training_runtime.get("runtime_status_key"),
                "supabase_state_sync": supabase_sync,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
