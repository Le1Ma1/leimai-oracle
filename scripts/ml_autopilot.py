from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_PATH = ROOT / "engine" / "artifacts" / "control" / "ml_tune_state.json"
DEFAULT_DECISION_PATH = ROOT / "engine" / "artifacts" / "control" / "ml_autotune_decision.json"
DEFAULT_ENV_PATH = ROOT / "logs" / "ml_autotune.env"


def _run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    print(f"[run] {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Local ML autopilot based on previous iteration artifacts.")
    parser.add_argument("--symbols", default="BTCUSDT", help="Comma-separated symbols for alpha_supervisor.")
    parser.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--decision-path", default=str(DEFAULT_DECISION_PATH))
    parser.add_argument("--env-path", default=str(DEFAULT_ENV_PATH))
    parser.add_argument("--force-tune", action="store_true", help="Bypass stability gate if delta is positive.")
    args = parser.parse_args()

    state_path = Path(str(args.state_path))
    decision_path = Path(str(args.decision_path))
    env_path = Path(str(args.env_path))

    state_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.parent.mkdir(parents=True, exist_ok=True)

    _run(
        [
            "python",
            "scripts/ml_autotune.py",
            "--mode",
            "prepare",
            "--state-path",
            str(state_path),
            "--decision-path",
            str(decision_path.with_name("ml_autotune_prepare.json")),
            "--emit-env-path",
            str(env_path),
        ],
        env=os.environ.copy(),
    )
    tune_env = _load_env_file(env_path)

    run_env = os.environ.copy()
    run_env.update(tune_env)

    validation_mode = "recovery" if bool(args.force_tune) else "standard"
    cmd = [
        "python",
        "scripts/alpha_supervisor.py",
        "--symbols",
        str(args.symbols),
        "--cycles",
        run_env.get("ML_TARGET_CYCLES", "2"),
        "--max-rounds",
        run_env.get("ML_TARGET_MAX_ROUNDS", "2"),
        "--target-pass-rate",
        run_env.get("ML_TARGET_PASS_RATE", "0.20"),
        "--target-deploy-symbols",
        run_env.get("ML_TARGET_DEPLOY_SYMBOLS", "1"),
        "--target-deploy-rules",
        run_env.get("ML_TARGET_DEPLOY_RULES", "2"),
        "--target-all-alpha",
        run_env.get("ML_TARGET_ALL_ALPHA", "-2.0"),
        "--target-deploy-alpha",
        run_env.get("ML_TARGET_DEPLOY_ALPHA", "0.0"),
        "--stable-rounds",
        run_env.get("ML_TARGET_STABLE_ROUNDS", "1"),
        "--validation-mode",
        validation_mode,
    ]
    _run(cmd, env=run_env)

    update_cmd = [
        "python",
        "scripts/ml_autotune.py",
        "--mode",
        "update",
        "--state-path",
        str(state_path),
        "--decision-path",
        str(decision_path),
    ]
    if bool(args.force_tune):
        update_cmd.append("--force-tune")
    _run(update_cmd, env=os.environ.copy())

    print("[done] local ML autopilot completed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[fatal] {exc}", file=sys.stderr)
        raise SystemExit(1)
