from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

READ_RETRY_ATTEMPTS = 6
READ_RETRY_SLEEP_SECONDS = 0.05
READ_RETRY_BACKOFF = 1.7
FULL_HISTORY_REQUIRED_START_UTC = "2020-01-01T00:00:00Z"


@dataclass(frozen=True)
class PhaseTarget:
    name: str
    validation_mode: str
    validation_strictness: str
    pass_rate: float
    deploy_symbols: int
    deploy_rules: int
    all_alpha: float
    deploy_alpha: float
    stable_rounds: int
    cycles: int
    max_rounds: int


def _run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"[run] {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")


def _latest_summary_path(artifact_root: Path) -> Path | None:
    root = artifact_root / "optimization" / "single"
    if not root.exists():
        return None
    candidates = sorted(root.rglob("summary.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _load_json(path: Path) -> dict[str, Any]:
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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if out != out:
            return default
        return out
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _parse_iso_utc(raw: Any) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _ensure_validate_sync(repo_root: Path, summary_path: Path, strictness: str) -> None:
    env = dict(os.environ)
    env["ENGINE_VALIDATION_STRICTNESS"] = str(strictness).strip().lower()
    _run(
        [
            "python",
            "-m",
            "engine.src.main",
            "--mode",
            "validate",
            "--summary-path",
            str(summary_path),
        ],
        cwd=repo_root,
        env=env,
    )


def _extract_all_window_alpha(summary: dict[str, Any]) -> float:
    report = summary.get("executive_report", {})
    rows = report.get("headline_by_window", []) if isinstance(report, dict) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("window")) != "all":
            continue
        try:
            return float(row.get("avg_strategy_return", 0.0) or 0.0) - float(row.get("avg_spot_return", 0.0) or 0.0)
        except Exception:
            return -999.0
    return -999.0


def _extract_all_window_start(summary: dict[str, Any]) -> datetime | None:
    results = summary.get("results", []) if isinstance(summary, dict) else []
    starts: list[datetime] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        windows = result.get("windows", [])
        if not isinstance(windows, list):
            continue
        for window in windows:
            if not isinstance(window, dict):
                continue
            if str(window.get("window")) != "all":
                continue
            dt = _parse_iso_utc(window.get("start_utc"))
            if dt is not None:
                starts.append(dt)
    if not starts:
        return None
    return min(starts)


def _assert_full_history_contract(summary: dict[str, Any], required_start_utc: str = FULL_HISTORY_REQUIRED_START_UTC) -> None:
    required = _parse_iso_utc(required_start_utc)
    observed = _extract_all_window_start(summary)
    if required is None:
        return
    if observed is None:
        raise RuntimeError("Full-history contract failed: cannot resolve all-window start timestamp from summary.")
    if observed > required:
        raise RuntimeError(
            f"Full-history contract failed: observed all-window start {observed.isoformat()} > required {required.isoformat()}."
        )


def _extract_deploy_avg_alpha(deploy: dict[str, Any]) -> float:
    values: list[float] = []
    for sym in deploy.get("symbols", []) if isinstance(deploy, dict) else []:
        if not isinstance(sym, dict):
            continue
        for rule in sym.get("rules", []):
            if not isinstance(rule, dict):
                continue
            alpha = rule.get("alpha_vs_spot")
            if isinstance(alpha, (int, float)):
                values.append(float(alpha))
    if not values:
        return -999.0
    return sum(values) / float(len(values))


def _collect_metrics(summary: dict[str, Any], validation: dict[str, Any], deploy: dict[str, Any]) -> dict[str, float | int | str]:
    return {
        "run_id": str(summary.get("run_id", "-")),
        "pass_rate": float(validation.get("pass_rate", 0.0) or 0.0),
        "deploy_symbols": int(deploy.get("total_symbols", 0) or 0),
        "deploy_rules": int(deploy.get("total_rules", 0) or 0),
        "all_window_alpha": _extract_all_window_alpha(summary),
        "deploy_avg_alpha": _extract_deploy_avg_alpha(deploy),
    }


def _passes_phase(metrics: dict[str, float | int | str], phase: PhaseTarget) -> bool:
    return bool(
        float(metrics["pass_rate"]) >= phase.pass_rate
        and int(metrics["deploy_symbols"]) >= phase.deploy_symbols
        and int(metrics["deploy_rules"]) >= phase.deploy_rules
        and float(metrics["all_window_alpha"]) >= phase.all_alpha
        and float(metrics["deploy_avg_alpha"]) >= phase.deploy_alpha
    )


def _print_metrics(prefix: str, metrics: dict[str, float | int | str]) -> None:
    print(
        f"[{prefix}] run_id={metrics['run_id']} pass_rate={float(metrics['pass_rate']):.4f} "
        f"deploy={int(metrics['deploy_symbols'])}sym/{int(metrics['deploy_rules'])}rules "
        f"all_alpha={float(metrics['all_window_alpha']):+.4f} deploy_alpha={float(metrics['deploy_avg_alpha']):+.4f}"
    )


def _wait_for_no_supervisor(repo_root: Path, poll_sec: int) -> None:
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "Get-CimInstance Win32_Process "
            "| Where-Object { $_.Name -match '^python(\\.exe)?$' -and "
            "($_.CommandLine -match 'scripts[\\\\/]alpha_supervisor.py' -or "
            "$_.CommandLine -match 'engine\\.src\\.main\\s+--mode\\s+iterate') } "
            "| Select-Object -First 1 ProcessId "
            "| ConvertTo-Json -Compress"
        ),
    ]
    while True:
        proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, check=False)
        out = (proc.stdout or "").strip()
        if not out or out == "null":
            return
        print("[wait] supervisor/iterate still running, waiting...")
        time.sleep(max(5, int(poll_sec)))


def _launch_phase(repo_root: Path, phase: PhaseTarget, monitor_interval: float) -> None:
    cmd = [
        "python",
        "scripts/alpha_supervisor.py",
        "--symbols",
        "BTCUSDT",
        "--skip-ingest",
        "--cycles",
        str(max(1, int(phase.cycles))),
        "--max-rounds",
        str(max(1, int(phase.max_rounds))),
        "--target-pass-rate",
        f"{phase.pass_rate:.2f}",
        "--target-deploy-symbols",
        str(max(1, int(phase.deploy_symbols))),
        "--target-deploy-rules",
        str(max(1, int(phase.deploy_rules))),
        "--target-all-alpha",
        f"{phase.all_alpha:.2f}",
        "--target-deploy-alpha",
        f"{phase.deploy_alpha:.2f}",
        "--stable-rounds",
        str(max(1, int(phase.stable_rounds))),
        "--validation-mode",
        str(phase.validation_mode),
        "--with-monitor",
        "--monitor-interval",
        f"{max(0.2, float(monitor_interval))}",
    ]
    _run(cmd, cwd=repo_root)


def _run_ml_progress_report(repo_root: Path) -> None:
    _run(["python", "scripts/ml_progress_report.py"], cwd=repo_root)


def _run_nonlinear_grid_backtest(repo_root: Path) -> None:
    _run(
        [
            "python",
            "scripts/nonlinear_grid_backtest.py",
            "--symbol",
            "BTCUSDT",
            "--max-bars",
            "300000",
        ],
        cwd=repo_root,
    )


def _run_rl_shadow_report(repo_root: Path) -> None:
    _run(["python", "scripts/rl_shadow_report.py"], cwd=repo_root)


def _read_progress_report(repo_root: Path) -> dict[str, Any]:
    return _load_json(repo_root / "logs" / "ml_progress_report.json")


def _derive_priority_from_report(progress_report: dict[str, Any]) -> tuple[str, list[str]]:
    mode = str(progress_report.get("priority_mode") or "").strip().lower()
    reasons = progress_report.get("priority_reasons")
    if not isinstance(reasons, list):
        reasons = []
    clean_reasons = [str(item).strip() for item in reasons if str(item).strip()]
    if mode in {"legacy_recovery", "dual_train", "idle"}:
        return mode, clean_reasons

    latest = progress_report.get("latest", {}) if isinstance(progress_report.get("latest"), dict) else {}
    targets = progress_report.get("targets", {}) if isinstance(progress_report.get("targets"), dict) else {}
    pass_rate = _safe_float(latest.get("validation_pass_rate"), 0.0)
    all_alpha = _safe_float(latest.get("all_window_alpha_vs_spot"), -10.0)
    deploy_symbols = _safe_int(latest.get("deploy_symbols"), 0)
    deploy_rules = _safe_int(latest.get("deploy_rules"), 0)
    target_pass = _safe_float(targets.get("validation_pass_rate"), 0.4)
    target_alpha = _safe_float(targets.get("all_window_alpha_vs_spot"), -3.0)
    target_symbols = _safe_int(targets.get("deploy_symbols"), 1)
    target_rules = _safe_int(targets.get("deploy_rules"), 2)
    if (
        pass_rate < target_pass
        or all_alpha < target_alpha
        or deploy_symbols < target_symbols
        or deploy_rules < target_rules
    ):
        return "legacy_recovery", ["derived_from_metrics"]
    return "dual_train", []


def _persist_priority_state(
    repo_root: Path,
    *,
    profile: str,
    priority_mode: str,
    reasons: list[str],
    progress_report: dict[str, Any],
) -> None:
    payload = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "profile": profile,
        "priority_mode": priority_mode,
        "priority_reasons": reasons,
        "latest": progress_report.get("latest", {}),
        "targets": progress_report.get("targets", {}),
        "role_decisions": progress_report.get("role_decisions", {}),
    }
    out_path = repo_root / "logs" / "ml_priority_state.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _should_allow_new_model(run_new_model: bool, priority_mode: str, reasons: list[str], legacy_only: bool) -> bool:
    if not run_new_model:
        return False
    if legacy_only:
        print("[guard] legacy-only mode enabled; skip new model branch.")
        return False
    if priority_mode == "legacy_recovery":
        reason_str = ", ".join(reasons[:4]) if reasons else "legacy_priority_guard"
        print(f"[guard] new model deferred; legacy recovery required ({reason_str})")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="BTC first-principles phase runner (bootstrap -> institutional ramp).")
    parser.add_argument(
        "--profile",
        type=str,
        choices=("deploy_recovery", "institutional_ramp", "nonlinear_grid_v1", "dual_track_train"),
        default="deploy_recovery",
        help="Execution profile.",
    )
    parser.add_argument("--wait-existing", action="store_true", help="Wait for any active supervisor/iterate before starting.")
    parser.add_argument("--monitor-interval", type=float, default=2.0, help="Monitor refresh interval in seconds.")
    parser.add_argument("--poll-sec", type=int, default=20, help="Polling interval when waiting for active runs.")
    parser.add_argument("--allow-shadow-new-model", action="store_true", help="Allow non-legacy shadow branch after guards pass.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    artifact_root = repo_root / "engine" / "artifacts"
    legacy_only = str(os.getenv("BTC_RUNNER_LEGACY_ONLY", "1")).strip().lower() not in {"0", "false", "no"}
    if args.allow_shadow_new_model:
        legacy_only = False

    if args.wait_existing:
        _wait_for_no_supervisor(repo_root=repo_root, poll_sec=max(5, int(args.poll_sec)))

    _run_ml_progress_report(repo_root=repo_root)
    progress_report = _read_progress_report(repo_root=repo_root)
    priority_mode, priority_reasons = _derive_priority_from_report(progress_report)
    _persist_priority_state(
        repo_root=repo_root,
        profile=str(args.profile),
        priority_mode=priority_mode,
        reasons=priority_reasons,
        progress_report=progress_report,
    )

    run_new_model = False
    if args.profile == "deploy_recovery":
        phases = [
            PhaseTarget(
                name="stage1_deploy_recovery",
                validation_mode="recovery",
                validation_strictness="recovery",
                pass_rate=0.01,
                deploy_symbols=1,
                deploy_rules=1,
                all_alpha=-8.0,
                deploy_alpha=-1.0,
                stable_rounds=1,
                cycles=2,
                max_rounds=2,
            ),
            PhaseTarget(
                name="stage2_deploy_lock",
                validation_mode="recovery",
                validation_strictness="recovery",
                pass_rate=0.05,
                deploy_symbols=1,
                deploy_rules=2,
                all_alpha=-8.0,
                deploy_alpha=-0.5,
                stable_rounds=1,
                cycles=2,
                max_rounds=2,
            ),
        ]
    elif args.profile == "nonlinear_grid_v1":
        phases = [
            PhaseTarget(
                name="stage_institutional_ramp",
                validation_mode="standard",
                validation_strictness="balanced",
                pass_rate=0.20,
                deploy_symbols=1,
                deploy_rules=2,
                all_alpha=-2.0,
                deploy_alpha=0.0,
                stable_rounds=1,
                cycles=2,
                max_rounds=2,
            ),
        ]
        run_new_model = True
    elif args.profile == "dual_track_train":
        phases = [
            PhaseTarget(
                name="stage1_deploy_recovery",
                validation_mode="recovery",
                validation_strictness="recovery",
                pass_rate=0.01,
                deploy_symbols=1,
                deploy_rules=1,
                all_alpha=-8.0,
                deploy_alpha=-1.0,
                stable_rounds=1,
                cycles=2,
                max_rounds=2,
            ),
            PhaseTarget(
                name="stage2_deploy_lock",
                validation_mode="recovery",
                validation_strictness="recovery",
                pass_rate=0.05,
                deploy_symbols=1,
                deploy_rules=2,
                all_alpha=-8.0,
                deploy_alpha=-0.5,
                stable_rounds=1,
                cycles=2,
                max_rounds=2,
            ),
            PhaseTarget(
                name="stage_institutional_ramp",
                validation_mode="standard",
                validation_strictness="balanced",
                pass_rate=0.20,
                deploy_symbols=1,
                deploy_rules=2,
                all_alpha=-2.0,
                deploy_alpha=0.0,
                stable_rounds=1,
                cycles=2,
                max_rounds=2,
            ),
        ]
        run_new_model = True
    else:
        phases = [
            PhaseTarget(
                name="stage_institutional_ramp",
                validation_mode="standard",
                validation_strictness="balanced",
                pass_rate=0.20,
                deploy_symbols=1,
                deploy_rules=2,
                all_alpha=-2.0,
                deploy_alpha=0.0,
                stable_rounds=1,
                cycles=2,
                max_rounds=2,
            ),
        ]

    run_new_model = _should_allow_new_model(run_new_model, priority_mode, priority_reasons, legacy_only=legacy_only)

    for phase in phases:
        summary_path = _latest_summary_path(artifact_root=artifact_root)
        if summary_path is None:
            raise RuntimeError("No summary.json found under engine/artifacts/optimization/single.")

        _ensure_validate_sync(
            repo_root=repo_root,
            summary_path=summary_path,
            strictness=phase.validation_strictness,
        )
        base = summary_path.parent
        summary = _load_json(base / "summary.json")
        _assert_full_history_contract(summary=summary)
        validation = _load_json(base / "validation_report.json")
        deploy = _load_json(base / "deploy_pool.json")
        metrics = _collect_metrics(summary=summary, validation=validation, deploy=deploy)
        _print_metrics(prefix=f"before {phase.name}", metrics=metrics)

        if _passes_phase(metrics=metrics, phase=phase):
            print(f"[skip] phase {phase.name} already satisfied")
            continue

        print(f"[phase] start {phase.name}")
        _launch_phase(repo_root=repo_root, phase=phase, monitor_interval=float(args.monitor_interval))

        summary_path = _latest_summary_path(artifact_root=artifact_root)
        if summary_path is None:
            raise RuntimeError(f"Phase {phase.name} finished but no summary.json found.")
        _ensure_validate_sync(
            repo_root=repo_root,
            summary_path=summary_path,
            strictness=phase.validation_strictness,
        )

        base = summary_path.parent
        summary = _load_json(base / "summary.json")
        _assert_full_history_contract(summary=summary)
        validation = _load_json(base / "validation_report.json")
        deploy = _load_json(base / "deploy_pool.json")
        metrics = _collect_metrics(summary=summary, validation=validation, deploy=deploy)
        _print_metrics(prefix=f"after {phase.name}", metrics=metrics)

    _run_ml_progress_report(repo_root=repo_root)
    progress_report = _read_progress_report(repo_root=repo_root)
    priority_mode, priority_reasons = _derive_priority_from_report(progress_report)
    _persist_priority_state(
        repo_root=repo_root,
        profile=str(args.profile),
        priority_mode=priority_mode,
        reasons=priority_reasons,
        progress_report=progress_report,
    )
    _run_rl_shadow_report(repo_root=repo_root)
    run_new_model = _should_allow_new_model(run_new_model, priority_mode, priority_reasons, legacy_only=legacy_only)

    if run_new_model:
        _run_nonlinear_grid_backtest(repo_root=repo_root)
    else:
        print("[new-model] skipped by priority guard (legacy-first).")

    print("[done] BTC phase runner completed all stages.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[fatal] {exc}", file=sys.stderr)
        raise SystemExit(1)
