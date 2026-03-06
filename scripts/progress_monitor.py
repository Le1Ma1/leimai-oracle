from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any


DEFAULT_VALIDATION_SECONDS = 20 * 60
MAX_LOG_FILES = 24
RECENT_RATE_WINDOW = 8
RECENT_EVENT_COUNT = 20
MAX_HISTORY_ROWS = 480
LOG_STALE_SECONDS = 180
DEFAULT_EXPORT_INTERVAL_SECONDS = 10.0
DEFAULT_EXPORT_TIMEOUT_SECONDS = 45.0
WRITE_RETRY_ATTEMPTS = 8
WRITE_RETRY_SLEEP_SECONDS = 0.05
WRITE_RETRY_BACKOFF = 1.8
READ_RETRY_ATTEMPTS = 6
READ_RETRY_SLEEP_SECONDS = 0.05
READ_RETRY_BACKOFF = 1.7
DEFAULT_SYMBOL_ORDER = (
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


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    if out != out:
        return default
    return out


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _read_json_retry(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    delay = READ_RETRY_SLEEP_SECONDS
    for attempt in range(1, READ_RETRY_ATTEMPTS + 1):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            if attempt >= READ_RETRY_ATTEMPTS:
                return {}
            time.sleep(delay)
            delay *= READ_RETRY_BACKOFF
    return {}


def _list_python_processes() -> list[dict[str, Any]]:
    if os.name == "nt":
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-CimInstance Win32_Process "
                "| Where-Object { $_.Name -match '^python(\\.exe)?$' } "
                "| Select-Object ProcessId,CommandLine "
                "| ConvertTo-Json -Compress"
            ),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return []
        raw = proc.stdout.strip()
        if not raw:
            return []
        try:
            payload = json.loads(raw)
        except Exception:
            return []
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    cmd = ["ps", "-eo", "pid,args"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return []
    rows: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        rows.append({"ProcessId": _safe_int(parts[0], 0), "CommandLine": parts[1]})
    return rows


def _detect_active_processes(processes: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in processes:
        pid = _safe_int(row.get("ProcessId"), 0)
        cmd = str(row.get("CommandLine") or "")
        cmd_l = cmd.lower()
        if pid <= 0:
            continue
        if "scripts/alpha_supervisor.py" in cmd_l or "scripts\\alpha_supervisor.py" in cmd_l:
            out["alpha_supervisor_pid"] = pid
        if "engine.src.main" in cmd_l and "--mode iterate" in cmd_l:
            out["iterate_pid"] = pid
        if "engine.src.main" in cmd_l and "--mode validate" in cmd_l:
            out["validate_pid"] = pid
    return out


def _parse_cli_int_arg(command_line: str, flag: str, default: int) -> int:
    pattern = rf"(?:^|\s){re.escape(flag)}\s+(\d+)"
    match = re.search(pattern, command_line, flags=re.IGNORECASE)
    if not match:
        return default
    return _safe_int(match.group(1), default)


def _parse_cli_float_arg(command_line: str, flag: str, default: float) -> float:
    pattern = rf"(?:^|\s){re.escape(flag)}\s+([+-]?[0-9]*\.?[0-9]+)"
    match = re.search(pattern, command_line, flags=re.IGNORECASE)
    if not match:
        return default
    return _safe_float(match.group(1), default)


def _parse_supervisor_targets(processes: list[dict[str, Any]]) -> dict[str, float | int]:
    defaults: dict[str, float | int] = {
        "target_pass_rate": 0.20,
        "target_deploy_symbols": 8,
        "target_deploy_rules": 16,
        "target_all_alpha": 0.0,
        "target_deploy_alpha": 0.0,
        "stable_rounds": 2,
        "cycles": 1,
        "max_rounds": 1,
    }
    for row in processes:
        cmd = str(row.get("CommandLine") or "")
        cmd_l = cmd.lower()
        if "scripts/alpha_supervisor.py" not in cmd_l and "scripts\\alpha_supervisor.py" not in cmd_l:
            continue
        return {
            "target_pass_rate": _parse_cli_float_arg(cmd, "--target-pass-rate", float(defaults["target_pass_rate"])),
            "target_deploy_symbols": _parse_cli_int_arg(cmd, "--target-deploy-symbols", int(defaults["target_deploy_symbols"])),
            "target_deploy_rules": _parse_cli_int_arg(cmd, "--target-deploy-rules", int(defaults["target_deploy_rules"])),
            "target_all_alpha": _parse_cli_float_arg(cmd, "--target-all-alpha", float(defaults["target_all_alpha"])),
            "target_deploy_alpha": _parse_cli_float_arg(cmd, "--target-deploy-alpha", float(defaults["target_deploy_alpha"])),
            "stable_rounds": _parse_cli_int_arg(cmd, "--stable-rounds", int(defaults["stable_rounds"])),
            "cycles": _parse_cli_int_arg(cmd, "--cycles", int(defaults["cycles"])),
            "max_rounds": _parse_cli_int_arg(cmd, "--max-rounds", int(defaults["max_rounds"])),
        }
    return defaults


def _list_out_logs(log_root: Path) -> list[Path]:
    if not log_root.exists():
        return []
    return sorted(log_root.glob("*.out.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:MAX_LOG_FILES]


def _parse_events(log_files: list[Path]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in log_files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for line in lines:
            line = line.strip()
            if not line.startswith("{") or '"event"' not in line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict) or "event" not in obj:
                continue
            ts = _parse_utc(obj.get("ts_utc"))
            if ts is None:
                continue
            obj["_ts"] = ts
            obj["_source"] = path.name
            events.append(obj)
    events.sort(key=lambda item: item["_ts"])
    return events


def _estimate_validation_tail_seconds(events: list[dict[str, Any]]) -> int:
    by_run: dict[str, dict[str, datetime]] = {}
    for event in events:
        run_id = str(event.get("run_id") or "")
        if not run_id:
            continue
        slot = by_run.setdefault(run_id, {})
        ts = event["_ts"]
        name = str(event.get("event"))
        if name == "ITERATION_ROUND_START":
            slot["start"] = ts
        elif name == "ITERATION_SYMBOL_CORE_DONE":
            prev = slot.get("last_core")
            if prev is None or ts > prev:
                slot["last_core"] = ts
        elif name == "ITERATION_ROUND_END":
            slot["round_end"] = ts

    samples: list[float] = []
    for slot in by_run.values():
        last_core = slot.get("last_core")
        round_end = slot.get("round_end")
        if last_core is None or round_end is None:
            continue
        diff = (round_end - last_core).total_seconds()
        if diff >= 0:
            samples.append(diff)
    if not samples:
        return DEFAULT_VALIDATION_SECONDS
    return int(max(60.0, median(samples)))


def _latest_quality_snapshot(artifact_root: Path) -> dict[str, Any]:
    single_root = artifact_root / "optimization" / "single"
    if not single_root.exists():
        return {}
    validations = sorted(single_root.rglob("validation_report.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    deploys = sorted(single_root.rglob("deploy_pool.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    v_payload = _read_json_retry(validations[0] if validations else None)
    d_payload = _read_json_retry(deploys[0] if deploys else None)

    pass_rate = _safe_float(v_payload.get("pass_rate"), 0.0) if isinstance(v_payload, dict) else 0.0
    all_alpha = 0.0
    for row in v_payload.get("summary_by_window", []) if isinstance(v_payload, dict) else []:
        if not isinstance(row, dict):
            continue
        if str(row.get("window")) == "all":
            all_alpha = _safe_float(row.get("avg_alpha_vs_spot"), 0.0)
            break

    deploy_alpha_samples: list[float] = []
    if isinstance(d_payload, dict):
        symbols = d_payload.get("symbols", [])
        if isinstance(symbols, list):
            for group in symbols:
                if not isinstance(group, dict):
                    continue
                rules = group.get("rules", [])
                if not isinstance(rules, list):
                    continue
                for rule in rules:
                    if not isinstance(rule, dict):
                        continue
                    deploy_alpha_samples.append(_safe_float(rule.get("alpha_vs_spot"), 0.0))
    deploy_avg_alpha = float(sum(deploy_alpha_samples) / len(deploy_alpha_samples)) if deploy_alpha_samples else 0.0

    return {
        "run_id": str(v_payload.get("run_id", d_payload.get("run_id", ""))) if isinstance(v_payload, dict) else "",
        "validation_pass_rate": pass_rate,
        "all_window_alpha_vs_spot": all_alpha,
        "deploy_symbols": _safe_int(d_payload.get("total_symbols"), 0) if isinstance(d_payload, dict) else 0,
        "deploy_rules": _safe_int(d_payload.get("total_rules"), 0) if isinstance(d_payload, dict) else 0,
        "deploy_avg_alpha_vs_spot": deploy_avg_alpha,
    }


def _load_json(path: Path | None) -> dict[str, Any]:
    return _read_json_retry(path)


def _extract_quality_snapshot(
    *,
    validation_payload: dict[str, Any],
    deploy_payload: dict[str, Any],
    summary_payload: dict[str, Any],
) -> dict[str, Any]:
    pass_rate = _safe_float(validation_payload.get("pass_rate"), 0.0)
    all_alpha = 0.0
    for row in validation_payload.get("summary_by_window", []) if isinstance(validation_payload.get("summary_by_window"), list) else []:
        if not isinstance(row, dict):
            continue
        if str(row.get("window")) == "all":
            all_alpha = _safe_float(row.get("avg_alpha_vs_spot"), 0.0)
            break

    if all_alpha == 0.0:
        health = (
            summary_payload.get("executive_report", {})
            .get("window_health_by_gate", {})
            .get("gated", {})
            .get("all", {})
        )
        if isinstance(health, dict):
            all_alpha = _safe_float(health.get("avg_strategy_return"), 0.0) - _safe_float(health.get("avg_spot_return"), 0.0)

    deploy_alpha_samples: list[float] = []
    for group in deploy_payload.get("symbols", []) if isinstance(deploy_payload.get("symbols"), list) else []:
        if not isinstance(group, dict):
            continue
        for rule in group.get("rules", []) if isinstance(group.get("rules"), list) else []:
            if not isinstance(rule, dict):
                continue
            deploy_alpha_samples.append(_safe_float(rule.get("alpha_vs_spot"), 0.0))
    deploy_avg_alpha = float(sum(deploy_alpha_samples) / len(deploy_alpha_samples)) if deploy_alpha_samples else 0.0

    run_id = str(
        summary_payload.get("run_id")
        or validation_payload.get("run_id")
        or deploy_payload.get("run_id")
        or ""
    )
    return {
        "run_id": run_id,
        "validation_pass_rate": pass_rate,
        "all_window_alpha_vs_spot": all_alpha,
        "deploy_symbols": _safe_int(deploy_payload.get("total_symbols"), 0),
        "deploy_rules": _safe_int(deploy_payload.get("total_rules"), 0),
        "deploy_avg_alpha_vs_spot": deploy_avg_alpha,
    }


def _quality_snapshot_from_summary(summary_path: Path | None) -> dict[str, Any]:
    if summary_path is None or not summary_path.exists():
        return {}
    summary_payload = _load_json(summary_path)
    base_dir = summary_path.parent
    validation_payload = _load_json(base_dir / "validation_report.json")
    deploy_payload = _load_json(base_dir / "deploy_pool.json")
    if not summary_payload and not validation_payload and not deploy_payload:
        return {}
    return _extract_quality_snapshot(
        validation_payload=validation_payload,
        deploy_payload=deploy_payload,
        summary_payload=summary_payload,
    )


def _latest_quality_snapshot_for_run(
    artifact_root: Path,
    preferred_run_id: str | None = None,
    allow_fallback_latest: bool = True,
) -> dict[str, Any]:
    single_root = artifact_root / "optimization" / "single"
    if not single_root.exists():
        return {}

    summary_files = sorted(single_root.rglob("summary.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if preferred_run_id:
        for summary_path in summary_files:
            payload = _load_json(summary_path)
            if str(payload.get("run_id", "")) != str(preferred_run_id):
                continue
            snapshot = _quality_snapshot_from_summary(summary_path)
            if snapshot:
                return snapshot

    if allow_fallback_latest and summary_files:
        snapshot = _quality_snapshot_from_summary(summary_files[0])
        if snapshot:
            return snapshot
    return _latest_quality_snapshot(artifact_root) if allow_fallback_latest else {}


def _build_status(repo_root: Path) -> dict[str, Any]:
    now = _now_utc()
    artifact_root = repo_root / "engine" / "artifacts"
    log_root = artifact_root / "logs"
    monitor_root = artifact_root / "monitor"
    monitor_root.mkdir(parents=True, exist_ok=True)

    processes = _list_python_processes()
    active_processes = _detect_active_processes(processes)
    targets_cfg = _parse_supervisor_targets(processes)
    iterate_active = "iterate_pid" in active_processes
    supervisor_active = "alpha_supervisor_pid" in active_processes

    log_files = _list_out_logs(log_root)
    events = _parse_events(log_files)
    validation_tail_seconds = _estimate_validation_tail_seconds(events)

    round_starts = [event for event in events if str(event.get("event")) == "ITERATION_ROUND_START" and event.get("run_id")]
    latest_start = round_starts[-1] if round_starts else None
    active_run_id = str(latest_start.get("run_id")) if latest_start is not None else None

    run_events: list[dict[str, Any]] = []
    if active_run_id:
        start_ts = latest_start["_ts"]
        run_events = [event for event in events if str(event.get("run_id")) == active_run_id and event["_ts"] >= start_ts]

    done_events = [event for event in run_events if str(event.get("event")) == "ITERATION_SYMBOL_CORE_DONE"]
    done_keys = {
        (
            str(event.get("symbol", "")),
            str(event.get("core_id", "")),
            str(event.get("gate_mode", "")),
        )
        for event in done_events
    }
    tasks_done = len(done_keys)

    symbols_total = _safe_int(latest_start.get("symbols"), 0) if latest_start else 0
    cores_total = len(latest_start.get("signal_cores", [])) if latest_start and isinstance(latest_start.get("signal_cores"), list) else 0
    gates_total = len(latest_start.get("gates", [])) if latest_start and isinstance(latest_start.get("gates"), list) else 0
    tasks_total = max(0, symbols_total * cores_total * gates_total)
    if tasks_total > 0:
        tasks_done = min(tasks_done, tasks_total)
    tasks_pct = float(tasks_done / tasks_total) * 100.0 if tasks_total > 0 else 0.0

    done_by_symbol: dict[str, int] = {}
    for event in done_events:
        symbol = str(event.get("symbol") or "").upper()
        if not symbol:
            continue
        done_by_symbol.setdefault(symbol, 0)
        done_by_symbol[symbol] += 1
    per_symbol_total = max(0, cores_total * gates_total)
    symbol_order: list[str] = list(DEFAULT_SYMBOL_ORDER[:symbols_total]) if symbols_total > 0 else []
    for symbol in done_by_symbol.keys():
        if symbol not in symbol_order:
            symbol_order.append(symbol)
    latest_done_symbol = str(done_events[-1].get("symbol") or "").upper() if done_events else ""
    symbol_progress: list[dict[str, Any]] = []
    for symbol in symbol_order:
        done_count = min(done_by_symbol.get(symbol, 0), per_symbol_total)
        pct = float(done_count / per_symbol_total * 100.0) if per_symbol_total > 0 else 0.0
        if done_count >= per_symbol_total and per_symbol_total > 0:
            phase = "done"
        elif done_count > 0 or (iterate_active and symbol == latest_done_symbol):
            phase = "running"
        else:
            phase = "pending"
        symbol_progress.append(
            {
                "symbol": symbol,
                "done": done_count,
                "total": per_symbol_total,
                "pct": round(pct, 2),
                "phase": phase,
            }
        )

    round_end = None
    for event in reversed(run_events):
        if str(event.get("event")) == "ITERATION_ROUND_END":
            round_end = event
            break
    iteration_complete = None
    for event in reversed(events):
        if str(event.get("event")) == "ITERATION_COMPLETE":
            iteration_complete = event
            break

    first_done_ts = done_events[0]["_ts"] if done_events else None
    last_done_ts = done_events[-1]["_ts"] if done_events else None

    global_rate = 0.0
    if first_done_ts is not None and tasks_done > 0:
        base_end = now if iterate_active and round_end is None else (last_done_ts or now)
        elapsed_min = max((base_end - first_done_ts).total_seconds() / 60.0, 1.0 / 60.0)
        global_rate = float(tasks_done / elapsed_min)

    recent_rate = global_rate
    if len(done_events) >= 2:
        recent_slice = done_events[-RECENT_RATE_WINDOW:]
        recent_start = recent_slice[0]["_ts"]
        recent_end = recent_slice[-1]["_ts"]
        recent_elapsed_min = max((recent_end - recent_start).total_seconds() / 60.0, 1.0 / 60.0)
        recent_rate = float((len(recent_slice) - 1) / recent_elapsed_min)

    stale_threshold_sec = LOG_STALE_SECONDS
    if iterate_active:
        if tasks_done <= 0:
            stale_threshold_sec = max(stale_threshold_sec, 900)
        else:
            stale_threshold_sec = max(stale_threshold_sec, 420)

    warnings: list[str] = []
    latest_event_ts = events[-1]["_ts"] if events else None
    last_event_age_sec: int | None = None
    if latest_event_ts is not None:
        age_sec = (now - latest_event_ts).total_seconds()
        last_event_age_sec = int(max(0.0, age_sec))
        if (iterate_active or supervisor_active) and age_sec > stale_threshold_sec:
            warnings.append(f"log_stale_{int(age_sec)}s")

    stale_active = bool(last_event_age_sec is not None and last_event_age_sec > stale_threshold_sec)
    round_completed = bool(round_end is not None)
    pipeline_state = "idle"
    stall_reason: str | None = None
    if iterate_active:
        if tasks_total > 0 and tasks_done < tasks_total:
            pipeline_state = "stalled" if stale_active else "running"
            if stale_active:
                stall_reason = "no_progress_events_while_running"
        elif tasks_total > 0 and tasks_done >= tasks_total and not round_completed:
            pipeline_state = "stalled" if stale_active else "validation"
            if stale_active:
                stall_reason = "no_round_end_after_tasks_done"
        else:
            pipeline_state = "stalled" if stale_active else "finalizing"
            if stale_active:
                stall_reason = "no_new_events_after_round_end"
    elif supervisor_active:
        pipeline_state = "stalled" if stale_active else "finalizing"
        if stale_active:
            stall_reason = "supervisor_no_new_events"
    elif iteration_complete is not None or round_completed:
        pipeline_state = "completed"

    seconds_remaining: int | None = None
    eta_utc: str | None = None
    if pipeline_state == "running" and tasks_total > 0:
        remaining_tasks = max(0, tasks_total - tasks_done)
        rate = recent_rate if recent_rate > 0 else global_rate
        if rate > 0:
            core_seconds = int((remaining_tasks / rate) * 60.0)
            seconds_remaining = max(0, core_seconds + validation_tail_seconds)
    elif pipeline_state == "validation":
        if last_done_ts is not None:
            elapsed = int((now - last_done_ts).total_seconds())
            seconds_remaining = max(60, validation_tail_seconds - elapsed)
        else:
            seconds_remaining = validation_tail_seconds
    elif pipeline_state == "finalizing":
        seconds_remaining = 60

    if seconds_remaining is not None:
        eta_utc = _to_iso_z(datetime.fromtimestamp(now.timestamp() + float(seconds_remaining), tz=timezone.utc))

    confidence = "low"
    if seconds_remaining is not None and tasks_done >= 6 and global_rate > 0 and recent_rate > 0:
        drift = abs(recent_rate - global_rate) / max(global_rate, 1e-9)
        if drift < 0.15:
            confidence = "high"
        elif drift < 0.35:
            confidence = "medium"

    round_end_summary_path: Path | None = None
    if isinstance(round_end, dict):
        summary_raw = round_end.get("summary")
        if isinstance(summary_raw, str) and summary_raw.strip():
            round_end_summary_path = Path(summary_raw)
            if not round_end_summary_path.is_absolute():
                round_end_summary_path = (repo_root / round_end_summary_path).resolve()
    quality_snapshot = _quality_snapshot_from_summary(round_end_summary_path)
    if not quality_snapshot and active_run_id:
        quality_snapshot = _latest_quality_snapshot_for_run(
            artifact_root,
            preferred_run_id=active_run_id,
            allow_fallback_latest=False,
        )
    if not quality_snapshot and not (iterate_active or supervisor_active):
        quality_snapshot = _latest_quality_snapshot_for_run(
            artifact_root,
            preferred_run_id=active_run_id,
            allow_fallback_latest=True,
        )
    quality_snapshot_run_id = str(quality_snapshot.get("run_id", "") or "")
    quality_snapshot_is_active_run = bool(active_run_id and quality_snapshot_run_id == str(active_run_id))
    active_run_consistent = bool(
        not active_run_id or not (iterate_active or supervisor_active) or quality_snapshot_is_active_run
    )
    if active_run_id and not active_run_consistent:
        warnings.append("quality_snapshot_from_previous_run")
    artifact_contract_ok = bool(quality_snapshot and quality_snapshot_run_id)
    if active_run_id and (iterate_active or supervisor_active) and not quality_snapshot:
        artifact_contract_ok = False
        warnings.append("quality_snapshot_missing_for_active_run")
    if active_run_id and not quality_snapshot_is_active_run and (iterate_active or supervisor_active):
        artifact_contract_ok = False
    if not artifact_contract_ok:
        warnings.append("artifact_contract_unhealthy")
    target_checks = [
        {
            "key": "validation_pass_rate",
            "label": f"Validation pass >= {float(targets_cfg['target_pass_rate']):.2f}",
            "actual": _safe_float(quality_snapshot.get("validation_pass_rate"), 0.0),
            "target": float(targets_cfg["target_pass_rate"]),
        },
        {
            "key": "deploy_symbols",
            "label": f"Deploy symbols >= {int(targets_cfg['target_deploy_symbols'])}",
            "actual": float(_safe_int(quality_snapshot.get("deploy_symbols"), 0)),
            "target": float(targets_cfg["target_deploy_symbols"]),
        },
        {
            "key": "deploy_rules",
            "label": f"Deploy rules >= {int(targets_cfg['target_deploy_rules'])}",
            "actual": float(_safe_int(quality_snapshot.get("deploy_rules"), 0)),
            "target": float(targets_cfg["target_deploy_rules"]),
        },
        {
            "key": "all_window_alpha_vs_spot",
            "label": f"all-window alpha >= {float(targets_cfg['target_all_alpha']):.2f}",
            "actual": _safe_float(quality_snapshot.get("all_window_alpha_vs_spot"), 0.0),
            "target": float(targets_cfg["target_all_alpha"]),
        },
        {
            "key": "deploy_avg_alpha_vs_spot",
            "label": f"deploy avg alpha >= {float(targets_cfg['target_deploy_alpha']):.2f}",
            "actual": _safe_float(quality_snapshot.get("deploy_avg_alpha_vs_spot"), 0.0),
            "target": float(targets_cfg["target_deploy_alpha"]),
        },
    ]
    for item in target_checks:
        item["passed"] = bool(float(item["actual"]) >= float(item["target"]))
    failed_checks = [item for item in target_checks if not bool(item["passed"])]
    if not artifact_contract_ok:
        promotion_block_reason = "artifact_contract_unhealthy"
    elif failed_checks:
        promotion_block_reason = f"target_not_met:{str(failed_checks[0]['key'])}"
    elif active_run_id and not active_run_consistent:
        promotion_block_reason = "active_run_inconsistent_snapshot"
    else:
        promotion_block_reason = None

    recent_source = run_events if run_events else events
    recent_events = recent_source[-RECENT_EVENT_COUNT:]
    recent_events_payload = [
        {
            "ts_utc": _to_iso_z(event["_ts"]),
            "event": str(event.get("event", "")),
            "symbol": str(event.get("symbol", "")) or None,
            "core_id": str(event.get("core_id", "")) or None,
            "gate_mode": str(event.get("gate_mode", "")) or None,
            "source": str(event.get("_source", "")),
        }
        for event in recent_events
    ]

    profile = str(latest_start.get("profile", "")) if latest_start else ""
    cycle_total = max(1, _safe_int(targets_cfg.get("cycles"), 1))
    cycle_current = 0
    if latest_start is not None:
        source_name = str(latest_start.get("_source", ""))
        seen_run_ids: set[str] = set()
        for event in events:
            if str(event.get("_source", "")) != source_name:
                continue
            if str(event.get("event")) != "ITERATION_ROUND_START":
                continue
            rid = str(event.get("run_id") or "")
            if rid:
                seen_run_ids.add(rid)
        cycle_current = len(seen_run_ids)
    cycle_total = max(cycle_total, cycle_current if cycle_current > 0 else 1)
    cycle_pct = float(cycle_current / cycle_total * 100.0) if cycle_total > 0 else 0.0

    status = {
        "updated_at_utc": _to_iso_z(now),
        "pipeline_state": pipeline_state,
        "stall_reason": stall_reason,
        "last_event_age_sec": last_event_age_sec,
        "stale_threshold_sec": stale_threshold_sec,
        "active_run_id": active_run_id,
        "active_processes": active_processes,
        "round": {
            "index": 1 if latest_start is not None else None,
            "profile": profile or None,
            "started_at_utc": _to_iso_z(latest_start["_ts"]) if latest_start is not None else None,
            "completed": round_completed,
            "completed_at_utc": _to_iso_z(round_end["_ts"]) if isinstance(round_end, dict) else None,
        },
        "cycle": {
            "current": cycle_current,
            "total": cycle_total,
            "pct": round(cycle_pct, 2),
            "max_rounds_per_cycle": _safe_int(targets_cfg.get("max_rounds"), 1),
        },
        "progress": {
            "symbols_total": symbols_total,
            "cores_total": cores_total,
            "gates_total": gates_total,
            "tasks_total": tasks_total,
            "tasks_done": tasks_done,
            "tasks_pct": round(tasks_pct, 2),
        },
        "symbol_progress": symbol_progress,
        "speed": {
            "tasks_per_minute_recent": round(recent_rate, 4),
            "tasks_per_minute_global": round(global_rate, 4),
        },
        "eta": {
            "seconds_remaining": seconds_remaining,
            "eta_utc": eta_utc,
            "confidence": confidence,
            "method": "hybrid",
            "validation_tail_seconds_assumed": int(validation_tail_seconds),
        },
        "quality_snapshot": quality_snapshot,
        "quality_snapshot_is_active_run": quality_snapshot_is_active_run,
        "artifact_contract_ok": artifact_contract_ok,
        "active_run_consistent": active_run_consistent,
        "promotion_block_reason": promotion_block_reason,
        "causal_contract": {
            "causal_mode": True,
            "winsorize_mode": "fold_safe",
            "fusion_mode": "online_lagged",
        },
        "targets": {
            "thresholds": targets_cfg,
            "checks": target_checks,
            "all_passed": all(bool(item["passed"]) for item in target_checks),
        },
        "last_events": recent_events_payload,
        "warnings": warnings,
        "log_files": [path.name for path in log_files[:5]],
    }
    return status


def _write_json(path: Path, payload: object) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    last_error: Exception | None = None
    for attempt in range(1, WRITE_RETRY_ATTEMPTS + 1):
        tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{attempt}")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)
            return True
        except (PermissionError, OSError) as error:
            last_error = error
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            if attempt < WRITE_RETRY_ATTEMPTS:
                backoff = WRITE_RETRY_SLEEP_SECONDS * (WRITE_RETRY_BACKOFF ** (attempt - 1))
                time.sleep(backoff)

    try:
        path.write_text(content, encoding="utf-8")
        return True
    except (PermissionError, OSError) as error:
        last_error = error

    print(
        f"[monitor][write_failed] path={path} attempts={WRITE_RETRY_ATTEMPTS} error={last_error}",
        flush=True,
    )
    return False


def _append_history(path: Path, status: dict[str, Any]) -> bool:
    row = {
        "updated_at_utc": status.get("updated_at_utc"),
        "pipeline_state": status.get("pipeline_state"),
        "stall_reason": status.get("stall_reason"),
        "active_run_id": status.get("active_run_id"),
        "cycle_current": status.get("cycle", {}).get("current"),
        "cycle_total": status.get("cycle", {}).get("total"),
        "tasks_done": status.get("progress", {}).get("tasks_done"),
        "tasks_total": status.get("progress", {}).get("tasks_total"),
        "tasks_pct": status.get("progress", {}).get("tasks_pct"),
        "eta_seconds_remaining": status.get("eta", {}).get("seconds_remaining"),
        "validation_pass_rate": status.get("quality_snapshot", {}).get("validation_pass_rate"),
        "deploy_symbols": status.get("quality_snapshot", {}).get("deploy_symbols"),
        "deploy_rules": status.get("quality_snapshot", {}).get("deploy_rules"),
        "targets_all_passed": status.get("targets", {}).get("all_passed"),
    }
    history: list[dict[str, Any]] = []
    if path.exists():
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(parsed, list):
                history = [item for item in parsed if isinstance(item, dict)]
        except Exception:
            history = []
    if not history or history[-1] != row:
        history.append(row)
    history = history[-MAX_HISTORY_ROWS:]
    return _write_json(path, history)


def _export_dashboard_state(repo_root: Path, timeout_sec: float) -> tuple[bool, str]:
    cmd = ["python", "scripts/export_dashboard_state.py"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root),
            check=False,
            capture_output=True,
            text=True,
            timeout=max(10.0, float(timeout_sec)),
        )
    except Exception as error:
        return False, str(error)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"exit_code_{proc.returncode}").strip()
        return False, detail[:280]
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate live monitor status JSON from engine logs.")
    parser.add_argument("--interval", type=float, default=2.0, help="Refresh interval seconds.")
    parser.add_argument(
        "--export-dashboard-state-interval",
        type=float,
        default=DEFAULT_EXPORT_INTERVAL_SECONDS,
        help="Export dashboard JSON interval seconds (0 disables export).",
    )
    parser.add_argument(
        "--export-dashboard-timeout-sec",
        type=float,
        default=DEFAULT_EXPORT_TIMEOUT_SECONDS,
        help="Timeout seconds for dashboard export command.",
    )
    parser.add_argument("--once", action="store_true", help="Write one snapshot and exit.")
    parser.add_argument("--repo-root", default=None, help="Optional repository root override.")
    args = parser.parse_args()

    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        repo_root = Path(__file__).resolve().parents[1]
    monitor_root = repo_root / "engine" / "artifacts" / "monitor"
    status_path = monitor_root / "live_status.json"
    history_path = monitor_root / "live_history.json"

    print(f"[monitor] repo_root={repo_root}")
    print(f"[monitor] writing={status_path}")

    last_write_ok_utc: str | None = None
    last_export_ok_utc: str | None = None
    last_export_error: str = ""
    consecutive_write_failures = 0
    consecutive_export_failures = 0
    last_export_monotonic = 0.0
    had_once_failure = False

    while True:
        try:
            status = _build_status(repo_root)
            status["monitor_health"] = {
                "last_write_ok_utc": last_write_ok_utc,
                "consecutive_write_failures": consecutive_write_failures,
                "last_export_ok_utc": last_export_ok_utc,
                "consecutive_export_failures": consecutive_export_failures,
                "last_export_error": last_export_error,
            }

            status_ok = _write_json(status_path, status)
            history_ok = _append_history(history_path, status)
            write_ok = bool(status_ok and history_ok)

            if write_ok:
                last_write_ok_utc = str(status.get("updated_at_utc") or last_write_ok_utc)
                consecutive_write_failures = 0
            else:
                consecutive_write_failures += 1
                had_once_failure = True
                print(
                    f"[monitor][write_retry] failures={consecutive_write_failures} "
                    f"updated_at={status.get('updated_at_utc')}",
                    flush=True,
                )

            export_interval = max(0.0, float(args.export_dashboard_state_interval))
            if export_interval > 0:
                now_monotonic = time.monotonic()
                if (now_monotonic - last_export_monotonic) >= export_interval:
                    ok, error_detail = _export_dashboard_state(
                        repo_root=repo_root,
                        timeout_sec=float(args.export_dashboard_timeout_sec),
                    )
                    last_export_monotonic = now_monotonic
                    if ok:
                        last_export_ok_utc = status.get("updated_at_utc")
                        last_export_error = ""
                        consecutive_export_failures = 0
                    else:
                        consecutive_export_failures += 1
                        last_export_error = error_detail
                        had_once_failure = True
                        print(
                            "[monitor][export_failed] "
                            f"failures={consecutive_export_failures} detail={error_detail}",
                            flush=True,
                        )
        except KeyboardInterrupt:
            break
        except Exception as error:
            consecutive_write_failures += 1
            had_once_failure = True
            print(
                f"[monitor][loop_error] failures={consecutive_write_failures} error={error}",
                flush=True,
            )

        if args.once:
            break
        time.sleep(max(0.2, float(args.interval)))
    if args.once and had_once_failure:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
