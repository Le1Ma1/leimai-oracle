from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

READ_RETRY_ATTEMPTS = 6
READ_RETRY_SLEEP_SECONDS = 0.05
READ_RETRY_BACKOFF = 1.7


@dataclass(frozen=True)
class PhaseTarget:
    name: str
    pass_rate: float
    deploy_symbols: int
    deploy_rules: int
    all_alpha: float
    deploy_alpha: float
    stable_rounds: int
    cycles: int
    max_rounds: int


def _run(cmd: list[str], cwd: Path) -> None:
    print(f"[run] {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(cwd), check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")


def _latest_summary_path(artifact_root: Path) -> Path | None:
    root = artifact_root / "optimization" / "single"
    if not root.exists():
        return None
    candidates = sorted(root.rglob("summary.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _load_json(path: Path) -> dict:
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


def _ensure_validate_sync(repo_root: Path, summary_path: Path) -> None:
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
    )


def _extract_all_window_alpha(summary: dict) -> float:
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


def _extract_deploy_avg_alpha(deploy: dict) -> float:
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


def _collect_metrics(summary: dict, validation: dict, deploy: dict) -> dict[str, float | int | str]:
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
        "--with-monitor",
        "--monitor-interval",
        f"{max(0.2, float(monitor_interval))}",
    ]
    _run(cmd, cwd=repo_root)


def main() -> int:
    parser = argparse.ArgumentParser(description="BTC first-principles phase runner (bootstrap -> institutional ramp).")
    parser.add_argument("--wait-existing", action="store_true", help="Wait for any active supervisor/iterate before starting.")
    parser.add_argument("--monitor-interval", type=float, default=2.0, help="Monitor refresh interval in seconds.")
    parser.add_argument("--poll-sec", type=int, default=20, help="Polling interval when waiting for active runs.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    artifact_root = repo_root / "engine" / "artifacts"

    if args.wait_existing:
        _wait_for_no_supervisor(repo_root=repo_root, poll_sec=max(5, int(args.poll_sec)))

    phases = [
        PhaseTarget(
            name="stage1_balanced",
            pass_rate=0.40,
            deploy_symbols=1,
            deploy_rules=2,
            all_alpha=-3.0,
            deploy_alpha=0.0,
            stable_rounds=1,
            cycles=2,
            max_rounds=2,
        ),
        PhaseTarget(
            name="stage2_institutional",
            pass_rate=0.55,
            deploy_symbols=1,
            deploy_rules=3,
            all_alpha=0.0,
            deploy_alpha=0.0,
            stable_rounds=1,
            cycles=2,
            max_rounds=2,
        ),
    ]

    for phase in phases:
        summary_path = _latest_summary_path(artifact_root=artifact_root)
        if summary_path is None:
            raise RuntimeError("No summary.json found under engine/artifacts/optimization/single.")

        _ensure_validate_sync(repo_root=repo_root, summary_path=summary_path)
        base = summary_path.parent
        summary = _load_json(base / "summary.json")
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
        _ensure_validate_sync(repo_root=repo_root, summary_path=summary_path)

        base = summary_path.parent
        summary = _load_json(base / "summary.json")
        validation = _load_json(base / "validation_report.json")
        deploy = _load_json(base / "deploy_pool.json")
        metrics = _collect_metrics(summary=summary, validation=validation, deploy=deploy)
        _print_metrics(prefix=f"after {phase.name}", metrics=metrics)

    print("[done] BTC phase runner completed all stages.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[fatal] {exc}", file=sys.stderr)
        raise SystemExit(1)
