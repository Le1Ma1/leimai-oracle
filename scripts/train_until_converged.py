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
    meta_metrics = extract_meta_metrics(validation)
    pbo, dsr = extract_pbo_dsr(validation)
    deploy_ready = bool(failure.get("deploy_ready", False))
    deploy_symbols = safe_int(failure.get("deploy_symbols"), 0)
    deploy_rules = safe_int(failure.get("deploy_rules"), 0)

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
        "pbo": pbo,
        "dsr": dsr,
        **meta_metrics,
    }


def quality_score(metrics: dict[str, Any]) -> float:
    pass_norm = max(0.0, min(1.0, safe_float(metrics.get("validation_pass_rate"), 0.0) / 0.20))
    alpha_norm = max(0.0, min(1.0, (safe_float(metrics.get("all_window_alpha"), -1.0) + 1.0) / 2.0))
    deploy_norm = 1.0 if bool(metrics.get("deploy_ready")) else 0.0
    robustness = max(0.0, min(1.0, 1.0 - safe_float(metrics.get("pbo"), 1.0)))
    return float((0.35 * pass_norm) + (0.35 * alpha_norm) + (0.20 * deploy_norm) + (0.10 * robustness))


def choose_meta_overrides(last_metrics: dict[str, Any] | None, loop_index: int) -> dict[str, str]:
    # Baseline profile with finer threshold scan.
    overrides: dict[str, str] = {
        "ENGINE_META_LABEL_THRESHOLD_STEP": "0.005",
        "ENGINE_META_LABEL_PROB_THRESHOLD_FALLBACK": "0.55",
    }
    if last_metrics is None:
        overrides.update(
            {
                "ENGINE_META_LABEL_TP_MULT": "1.20",
                "ENGINE_META_LABEL_VERTICAL_HORIZON_BARS": "24",
                "ENGINE_META_LABEL_VOL_WINDOW": "24",
                "ENGINE_META_LABEL_THRESHOLD_MIN": "0.45",
                "ENGINE_META_LABEL_MIN_EVENTS": "60",
                "ENGINE_META_LABEL_CPCV_SPLITS": "5",
                "ENGINE_META_LABEL_CPCV_TEST_GROUPS": "1",
            }
        )
        return overrides

    veto_rate = max(
        safe_float(last_metrics.get("veto_all_rate"), 0.0),
        safe_float(last_metrics.get("failsafe_veto_all_rate"), 0.0),
    )
    trades_total = safe_int(last_metrics.get("trades_total_all_window"), 0)
    floor_comp = safe_float(last_metrics.get("precision_floor_compliance_rate"), 0.0)
    pass_rate = safe_float(last_metrics.get("validation_pass_rate"), 0.0)

    if veto_rate > 0.95 or trades_total <= 0:
        overrides.update(
            {
                "ENGINE_META_LABEL_TP_MULT": "1.20",
                "ENGINE_META_LABEL_VERTICAL_HORIZON_BARS": "24",
                "ENGINE_META_LABEL_VOL_WINDOW": "24",
                "ENGINE_META_LABEL_THRESHOLD_MIN": "0.45",
                "ENGINE_META_LABEL_MIN_EVENTS": "60",
                "ENGINE_META_LABEL_CPCV_SPLITS": "5",
                "ENGINE_META_LABEL_CPCV_TEST_GROUPS": "1",
            }
        )
    elif floor_comp < 0.40:
        overrides.update(
            {
                "ENGINE_META_LABEL_TP_MULT": "1.30",
                "ENGINE_META_LABEL_VERTICAL_HORIZON_BARS": "20",
                "ENGINE_META_LABEL_VOL_WINDOW": "22",
                "ENGINE_META_LABEL_THRESHOLD_MIN": "0.47",
                "ENGINE_META_LABEL_MIN_EVENTS": "70",
                "ENGINE_META_LABEL_CPCV_SPLITS": "5",
                "ENGINE_META_LABEL_CPCV_TEST_GROUPS": "1",
            }
        )
    elif pass_rate < 0.20:
        overrides.update(
            {
                "ENGINE_META_LABEL_TP_MULT": "1.25",
                "ENGINE_META_LABEL_VERTICAL_HORIZON_BARS": "22",
                "ENGINE_META_LABEL_VOL_WINDOW": "24",
                "ENGINE_META_LABEL_THRESHOLD_MIN": "0.46",
                "ENGINE_META_LABEL_MIN_EVENTS": "65",
            }
        )
    else:
        overrides.update(
            {
                "ENGINE_META_LABEL_TP_MULT": "1.35",
                "ENGINE_META_LABEL_VERTICAL_HORIZON_BARS": "20",
                "ENGINE_META_LABEL_VOL_WINDOW": "20",
                "ENGINE_META_LABEL_THRESHOLD_MIN": "0.50",
                "ENGINE_META_LABEL_MIN_EVENTS": "80",
                "ENGINE_META_LABEL_CPCV_SPLITS": "6",
                "ENGINE_META_LABEL_CPCV_TEST_GROUPS": "2",
            }
        )

    if loop_index % 4 == 0:
        overrides["ENGINE_META_LABEL_THRESHOLD_MIN"] = "0.44"
    return overrides


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

    state: dict[str, Any] = {
        "generated_at_utc": now_iso(),
        "status_key": "TRAINING_STATUS_RUNNING",
        "gate": gate,
        "hard_cap": max(1, int(args.hard_cap)),
        "stagnation_rounds": max(1, int(args.stagnation_rounds)),
        "loop_runs": 0,
        "stagnation_count": 0,
        "best_quality_score": -1.0,
        "current_streak": 0,
        "rounds": [],
    }
    if bool(args.resume):
        loaded = read_json(STATE_PATH)
        if loaded:
            state.update(loaded)
            state["gate"] = gate
            state["hard_cap"] = max(1, int(args.hard_cap))
            state["stagnation_rounds"] = max(1, int(args.stagnation_rounds))

    last_metrics: dict[str, Any] | None = None
    if isinstance(state.get("rounds"), list) and state["rounds"]:
        maybe = state["rounds"][-1]
        if isinstance(maybe, dict):
            last_metrics = maybe.get("metrics") if isinstance(maybe.get("metrics"), dict) else None

    hard_cap = max(1, safe_int(state.get("hard_cap"), 50))
    stagnation_rounds = max(1, safe_int(state.get("stagnation_rounds"), 6))
    best_quality = safe_float(state.get("best_quality_score"), -1.0)
    current_streak = safe_int(state.get("current_streak"), 0)
    stagnation_count = safe_int(state.get("stagnation_count"), 0)
    loop_runs = safe_int(state.get("loop_runs"), 0)

    try:
        if bool(args.dry_run):
            state["generated_at_utc"] = now_iso()
            write_json(STATE_PATH, state)
            export_dashboard()
            print(json.dumps({"event": "TRAIN_LOOP_DRY_RUN_DONE", "state_path": str(STATE_PATH)}, ensure_ascii=False))
            return 0

        while loop_runs < hard_cap:
            loop_index = loop_runs + 1
            overrides = choose_meta_overrides(last_metrics=last_metrics, loop_index=loop_index)
            env = os.environ.copy()
            env.update(overrides)

            started_at = now_iso()
            run_checked(alpha_supervisor_cmd(args), env=env)
            metrics = collect_latest_metrics()
            q_score = quality_score(metrics)
            this_gate_hit = gate_hit(metrics=metrics, gate=gate)
            current_streak = (current_streak + 1) if this_gate_hit else 0

            improved = q_score > (best_quality + 1e-8)
            if improved:
                best_quality = q_score
                stagnation_count = 0
            else:
                stagnation_count += 1

            round_entry = {
                "loop_index": loop_index,
                "started_at_utc": started_at,
                "ended_at_utc": now_iso(),
                "overrides": overrides,
                "metrics": metrics,
                "gate_hit": this_gate_hit,
                "quality_score": q_score,
                "improved": improved,
                "current_streak": current_streak,
                "stagnation_count": stagnation_count,
            }

            rounds = state.get("rounds")
            if not isinstance(rounds, list):
                rounds = []
            rounds.append(round_entry)

            loop_runs = loop_index
            state.update(
                {
                    "generated_at_utc": now_iso(),
                    "status_key": "TRAINING_STATUS_RUNNING",
                    "loop_runs": loop_runs,
                    "best_quality_score": best_quality,
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

            if current_streak >= safe_int(gate.get("required_streak"), 2):
                state["status_key"] = "TRAINING_STATUS_CONVERGED"
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
                state["status_key"] = "TRAINING_STATUS_STAGNATED"
                write_json(STATE_PATH, state)
                export_dashboard()
                print(
                    json.dumps(
                        {
                            "event": "TRAIN_LOOP_STAGNATED",
                            "loop_runs": loop_runs,
                            "stagnation_count": stagnation_count,
                            "run_id": metrics.get("run_id", ""),
                        },
                        ensure_ascii=False,
                    )
                )
                return 0

            time.sleep(max(0.0, float(args.cooldown_sec)))

        state["status_key"] = "TRAINING_STATUS_HALTED"
        state["generated_at_utc"] = now_iso()
        write_json(STATE_PATH, state)
        export_dashboard()
        print(
            json.dumps(
                {"event": "TRAIN_LOOP_HARD_CAP_REACHED", "loop_runs": loop_runs, "hard_cap": hard_cap},
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
