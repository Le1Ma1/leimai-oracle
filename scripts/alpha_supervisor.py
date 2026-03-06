from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SYMBOLS = (
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
READ_RETRY_ATTEMPTS = 6
READ_RETRY_SLEEP_SECONDS = 0.05
READ_RETRY_BACKOFF = 1.7


def _parse_symbols_csv(raw: str) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for token in str(raw).split(","):
        symbol = token.strip().upper()
        if not symbol:
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return tuple(out)


@dataclass(frozen=True)
class TuneState:
    gate_oracle_quantile: float = 0.45
    gate_confidence_quantile: float = 0.30
    credibility_reject_threshold: float = 0.75
    credible_max_penalty: float = 0.90
    trade_floor: int = 70
    validation_mode: str = "standard"
    validation_strictness: str = "balanced"
    validation_sample_step: int = 20
    validation_walk_forward_splits: int = 3
    validation_cv_folds: int = 3
    validation_purge_bars: int = 90
    validation_stress_friction_bps: str = "10,20"


@dataclass(frozen=True)
class CycleMetrics:
    run_id: str
    validation_pass_rate: float
    validation_median_final_score: float
    all_window_avg_alpha_vs_spot: float
    deploy_avg_alpha_vs_spot: float
    deploy_symbols: int
    deploy_rules: int
    gate_pass_delta_all: float
    gate_alpha_delta_all: float
    low_credibility_ratio_gated: float


def _run(cmd: list[str], env: dict[str, str]) -> None:
    print(f"[run] {' '.join(cmd)}")
    proc = subprocess.run(cmd, env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")


def _export_dashboard_state(repo_root: Path, env: dict[str, str]) -> None:
    cmd = ["python", "scripts/export_dashboard_state.py"]
    proc = subprocess.run(cmd, cwd=str(repo_root), env=env, check=False)
    if proc.returncode != 0:
        print(f"[warn] dashboard state export skipped (code={proc.returncode})", file=sys.stderr)
        return
    print("[info] dashboard state exported (evolution_validation.json + visual_state.json + training_roadmap.json + training_runtime.json)")


def _start_progress_monitor(repo_root: Path, interval: float, export_interval: float) -> tuple[subprocess.Popen[str], Any, Any]:
    logs_root = repo_root / "engine" / "artifacts" / "logs"
    logs_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = logs_root / f"progress_monitor_supervised_{stamp}.out.log"
    err_path = logs_root / f"progress_monitor_supervised_{stamp}.err.log"
    out_file = out_path.open("w", encoding="utf-8")
    err_file = err_path.open("w", encoding="utf-8")
    cmd = [
        "python",
        "scripts/progress_monitor.py",
        "--interval",
        str(max(0.2, float(interval))),
        "--export-dashboard-state-interval",
        str(max(0.0, float(export_interval))),
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=str(repo_root),
        stdout=out_file,
        stderr=err_file,
        text=True,
    )
    print(f"[monitor] started pid={proc.pid} interval={interval}s export_interval={export_interval}s")
    print(f"[monitor] out_log={out_path}")
    print(f"[monitor] err_log={err_path}")
    return proc, out_file, err_file


def _is_progress_monitor_running() -> bool:
    if os.name == "nt":
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-CimInstance Win32_Process "
                "| Where-Object { $_.Name -match '^python(\\.exe)?$' -and "
                "$_.CommandLine -match 'scripts[\\\\/]progress_monitor.py' } "
                "| Select-Object -First 1 ProcessId "
                "| ConvertTo-Json -Compress"
            ),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return proc.returncode == 0 and bool(proc.stdout.strip() and proc.stdout.strip() != "null")

    cmd = ["ps", "-eo", "args"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return False
    return any("scripts/progress_monitor.py" in row for row in proc.stdout.splitlines())


def _stop_progress_monitor(proc: subprocess.Popen[str] | None, out_file: Any, err_file: Any) -> None:
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        print(f"[monitor] stopped pid={proc.pid}")

    for stream in (out_file, err_file):
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass


def _latest_iteration_report(iteration_root: Path) -> Path | None:
    if not iteration_root.exists():
        return None
    reports = sorted(iteration_root.rglob("iteration_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return reports[0] if reports else None


def _find_latest_summary(artifact_root: Path) -> Path | None:
    single_root = artifact_root / "optimization" / "single"
    if not single_root.exists():
        return None
    summaries = sorted(single_root.rglob("summary.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return summaries[0] if summaries else None


def _read_json(path: Path | None) -> dict[str, Any]:
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


def _symbol_has_1m_data(raw_root: Path, symbol: str) -> bool:
    tf_root = raw_root / f"symbol={symbol}" / "timeframe=1m"
    return tf_root.exists() and any(tf_root.rglob("*.parquet"))


def _print_summary(summary_payload: dict[str, Any], deploy_payload: dict[str, Any]) -> None:
    run_id = str(summary_payload.get("run_id", "-"))
    strategy_mode = str(summary_payload.get("strategy_mode", "-"))
    delta_views = summary_payload.get("delta_views", {})
    gate_delta = delta_views.get("gate_delta_by_window", []) if isinstance(delta_views, dict) else []
    health = summary_payload.get("health_dashboard", {}) if isinstance(summary_payload, dict) else {}
    deploy_symbols = int(deploy_payload.get("total_symbols", 0)) if isinstance(deploy_payload, dict) else 0
    deploy_rules = int(deploy_payload.get("total_rules", 0)) if isinstance(deploy_payload, dict) else 0

    print("")
    print("=== ALPHA SUPERVISOR SUMMARY ===")
    print(f"run_id={run_id}")
    print(f"strategy_mode={strategy_mode}")
    print(f"deploy_coverage={deploy_symbols} symbols / {deploy_rules} rules")
    if isinstance(health, dict):
        print(f"health_default_gate={health.get('default_gate_mode', '-')}")
        print(f"health_target={health.get('quality_target_profile', '-')}")
    if isinstance(gate_delta, list):
        for row in gate_delta:
            if not isinstance(row, dict):
                continue
            window = str(row.get("window", "-"))
            pass_delta = float(row.get("delta_pass_rate", 0.0) or 0.0)
            alpha_delta = float(row.get("delta_avg_alpha_proxy", 0.0) or 0.0)
            print(
                f"window={window} pass_delta={pass_delta:+.4f} alpha_delta={alpha_delta:+.4f}"
            )
    print("================================")


def _float(value: object, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    if out != out:
        return default
    return out


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _extract_gate_delta(summary_payload: dict[str, Any], window: str = "all") -> tuple[float, float]:
    delta_views = summary_payload.get("delta_views", {})
    if not isinstance(delta_views, dict):
        return 0.0, 0.0
    rows = delta_views.get("gate_delta_by_window", [])
    if not isinstance(rows, list):
        return 0.0, 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("window")) != window:
            continue
        return _float(row.get("delta_pass_rate")), _float(row.get("delta_avg_alpha_proxy"))
    return 0.0, 0.0


def _extract_low_credibility_ratio(summary_payload: dict[str, Any], gate_mode: str = "gated") -> float:
    by_gate = summary_payload.get("results_by_gate_mode", {})
    if not isinstance(by_gate, dict):
        return 0.0
    rows = by_gate.get(gate_mode, [])
    if not isinstance(rows, list):
        return 0.0
    total_candidates = 0
    low_credibility = 0
    for result in rows:
        if not isinstance(result, dict):
            continue
        windows = result.get("windows", [])
        if not isinstance(windows, list):
            continue
        for window in windows:
            if not isinstance(window, dict):
                continue
            competition = window.get("rule_competition", {})
            if not isinstance(competition, dict):
                continue
            rejected = competition.get("rejected_breakdown", {})
            total_candidates += _int(competition.get("total_candidates"), 0)
            if isinstance(rejected, dict):
                low_credibility += _int(rejected.get("low_credibility", rejected.get("low_trades", 0)), 0)
    if total_candidates <= 0:
        return 0.0
    return float(low_credibility / float(total_candidates))


def _extract_validation_metrics(validation_payload: dict[str, Any]) -> tuple[float, float, float]:
    pass_rate = _float(validation_payload.get("pass_rate"), 0.0)
    rows = validation_payload.get("rows", [])
    median_score = 0.0
    if isinstance(rows, list) and rows:
        scores: list[float] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            score_obj = row.get("scores", {})
            if not isinstance(score_obj, dict):
                continue
            scores.append(_float(score_obj.get("final_score"), 0.0))
        if scores:
            ordered = sorted(scores)
            median_score = ordered[len(ordered) // 2]

    all_window_alpha = 0.0
    summary_by_window = validation_payload.get("summary_by_window", [])
    if isinstance(summary_by_window, list):
        for item in summary_by_window:
            if not isinstance(item, dict):
                continue
            if str(item.get("window")) == "all":
                all_window_alpha = _float(item.get("avg_alpha_vs_spot"), 0.0)
                break
    return pass_rate, median_score, all_window_alpha


def _extract_deploy_avg_alpha(deploy_payload: dict[str, Any]) -> float:
    if not isinstance(deploy_payload, dict):
        return 0.0
    symbols = deploy_payload.get("symbols", [])
    if not isinstance(symbols, list):
        return 0.0
    alpha_samples: list[float] = []
    for group in symbols:
        if not isinstance(group, dict):
            continue
        rules = group.get("rules", [])
        if not isinstance(rules, list):
            continue
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            alpha_samples.append(_float(rule.get("alpha_vs_spot"), 0.0))
    if not alpha_samples:
        return 0.0
    return float(sum(alpha_samples) / len(alpha_samples))


def _extract_cycle_metrics(
    summary_payload: dict[str, Any],
    validation_payload: dict[str, Any],
    deploy_payload: dict[str, Any],
) -> CycleMetrics:
    pass_delta_all, alpha_delta_all = _extract_gate_delta(summary_payload=summary_payload, window="all")
    low_cred_ratio = _extract_low_credibility_ratio(summary_payload=summary_payload, gate_mode="gated")
    validation_pass_rate, median_score, all_window_alpha = _extract_validation_metrics(validation_payload=validation_payload)
    deploy_avg_alpha = _extract_deploy_avg_alpha(deploy_payload)

    return CycleMetrics(
        run_id=str(summary_payload.get("run_id", "-")),
        validation_pass_rate=validation_pass_rate,
        validation_median_final_score=median_score,
        all_window_avg_alpha_vs_spot=all_window_alpha,
        deploy_avg_alpha_vs_spot=deploy_avg_alpha,
        deploy_symbols=_int(deploy_payload.get("total_symbols"), 0),
        deploy_rules=_int(deploy_payload.get("total_rules"), 0),
        gate_pass_delta_all=pass_delta_all,
        gate_alpha_delta_all=alpha_delta_all,
        low_credibility_ratio_gated=low_cred_ratio,
    )


def _clip(value: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, value)))


def _adapt_state(
    state: TuneState,
    metrics: CycleMetrics,
    cycle_index: int,
    total_cycles: int,
    validation_mode: str,
) -> TuneState:
    next_state = TuneState(**asdict(state))

    if metrics.gate_pass_delta_all < -0.05 and metrics.gate_alpha_delta_all <= 0.0:
        next_state = TuneState(
            **{
                **asdict(next_state),
                "gate_oracle_quantile": _clip(next_state.gate_oracle_quantile - 0.05, 0.30, 0.70),
                "gate_confidence_quantile": _clip(next_state.gate_confidence_quantile - 0.05, 0.20, 0.60),
            }
        )
    elif metrics.gate_pass_delta_all > 0.08 and metrics.gate_alpha_delta_all > 0.02:
        next_state = TuneState(
            **{
                **asdict(next_state),
                "gate_oracle_quantile": _clip(next_state.gate_oracle_quantile + 0.03, 0.30, 0.70),
                "gate_confidence_quantile": _clip(next_state.gate_confidence_quantile + 0.03, 0.20, 0.60),
            }
        )

    if metrics.low_credibility_ratio_gated > 0.70:
        min_trade_floor = 25 if validation_mode == "recovery" else 40
        next_state = TuneState(
            **{
                **asdict(next_state),
                "credibility_reject_threshold": _clip(next_state.credibility_reject_threshold + 0.05, 0.55, 0.90),
                "credible_max_penalty": _clip(next_state.credible_max_penalty + 0.03, 0.70, 0.95),
                "trade_floor": max(min_trade_floor, int(next_state.trade_floor - 10)),
            }
        )
    elif metrics.low_credibility_ratio_gated < 0.35 and metrics.validation_pass_rate >= 0.20:
        next_state = TuneState(
            **{
                **asdict(next_state),
                "credibility_reject_threshold": _clip(next_state.credibility_reject_threshold - 0.02, 0.55, 0.90),
                "credible_max_penalty": _clip(next_state.credible_max_penalty - 0.02, 0.70, 0.95),
            }
        )

    if validation_mode == "recovery":
        if metrics.validation_pass_rate < 0.10:
            next_state = TuneState(
                **{
                    **asdict(next_state),
                    "validation_mode": "recovery",
                    "validation_strictness": "recovery",
                    "validation_sample_step": 30,
                    "validation_walk_forward_splits": 2,
                    "validation_cv_folds": 2,
                    "validation_purge_bars": 45,
                    "validation_stress_friction_bps": "10",
                }
            )
        else:
            next_state = TuneState(
                **{
                    **asdict(next_state),
                    "validation_mode": "recovery",
                    "validation_strictness": "fast",
                    "validation_sample_step": 20,
                    "validation_walk_forward_splits": 2,
                    "validation_cv_folds": 2,
                    "validation_purge_bars": 60,
                    "validation_stress_friction_bps": "10",
                }
            )
    else:
        if metrics.validation_pass_rate < 0.10:
            next_state = TuneState(
                **{
                    **asdict(next_state),
                    "validation_mode": "standard",
                    "validation_strictness": "fast",
                    "validation_sample_step": 30,
                    "validation_walk_forward_splits": 2,
                    "validation_cv_folds": 2,
                    "validation_purge_bars": 60,
                    "validation_stress_friction_bps": "10",
                }
            )
        else:
            next_state = TuneState(
                **{
                    **asdict(next_state),
                    "validation_mode": "standard",
                    "validation_strictness": "balanced",
                    "validation_sample_step": 20,
                    "validation_walk_forward_splits": 3,
                    "validation_cv_folds": 3,
                    "validation_purge_bars": 90,
                    "validation_stress_friction_bps": "10,20",
                }
            )

        if cycle_index == total_cycles - 1:
            next_state = TuneState(
                **{
                    **asdict(next_state),
                    "validation_mode": "standard",
                    "validation_strictness": "institutional",
                    "validation_sample_step": 10,
                    "validation_walk_forward_splits": 4,
                    "validation_cv_folds": 4,
                    "validation_purge_bars": 120,
                    "validation_stress_friction_bps": "10,20,30",
                }
            )
    return next_state


def _build_cycle_env(base_env: dict[str, str], state: TuneState, rounds_per_cycle: int) -> dict[str, str]:
    env = dict(base_env)
    env.update(
        {
            "ENGINE_VALIDATION_STRICTNESS": state.validation_strictness,
            "ENGINE_VALIDATION_SAMPLE_STEP": str(int(state.validation_sample_step)),
            "ENGINE_VALIDATION_WALK_FORWARD_SPLITS": str(int(state.validation_walk_forward_splits)),
            "ENGINE_VALIDATION_CV_FOLDS": str(int(state.validation_cv_folds)),
            "ENGINE_VALIDATION_PURGE_BARS": str(int(state.validation_purge_bars)),
            "ENGINE_VALIDATION_STRESS_FRICTION_BPS": state.validation_stress_friction_bps,
            "ENGINE_GATE_ORACLE_QUANTILE": f"{state.gate_oracle_quantile:.2f}",
            "ENGINE_GATE_CONFIDENCE_QUANTILE": f"{state.gate_confidence_quantile:.2f}",
            "ENGINE_CREDIBILITY_REJECT_THRESHOLD": f"{state.credibility_reject_threshold:.2f}",
            "ENGINE_CREDIBLE_MAX_PENALTY": f"{state.credible_max_penalty:.2f}",
            "ENGINE_TRADE_FLOOR": str(int(state.trade_floor)),
            "ENGINE_OPTIMIZATION_MAX_ROUNDS": str(max(1, int(rounds_per_cycle))),
        }
    )
    return env


def _print_cycle(cycle: int, total_cycles: int, state: TuneState, metrics: CycleMetrics) -> None:
    print("")
    print(f"=== CYCLE {cycle}/{total_cycles} ===")
    print(
        f"state: gate(q_oracle={state.gate_oracle_quantile:.2f}, q_conf={state.gate_confidence_quantile:.2f}) "
        f"cred(th={state.credibility_reject_threshold:.2f}, max={state.credible_max_penalty:.2f}) "
        f"trade_floor={state.trade_floor} strictness={state.validation_strictness}"
    )
    print(
        f"metrics: run_id={metrics.run_id} pass_rate={metrics.validation_pass_rate:.4f} "
        f"median_score={metrics.validation_median_final_score:.4f} all_alpha={metrics.all_window_avg_alpha_vs_spot:+.4f} "
        f"deploy_alpha={metrics.deploy_avg_alpha_vs_spot:+.4f} deploy={metrics.deploy_symbols} symbols/{metrics.deploy_rules} rules"
    )
    print(
        f"gate_delta(all): pass={metrics.gate_pass_delta_all:+.4f} alpha={metrics.gate_alpha_delta_all:+.4f} "
        f"low_cred_ratio_gated={metrics.low_credibility_ratio_gated:.4f}"
    )
    print("====================")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run alpha-first aggressive optimization supervision loop.")
    parser.add_argument("--max-rounds", type=int, default=2, help="Iterative rounds for each cycle.")
    parser.add_argument("--cycles", type=int, default=3, help="Supervisor cycles with adaptive tuning.")
    parser.add_argument("--skip-ingest", action="store_true", help="Skip missing-symbol ingestion.")
    parser.add_argument("--target-deploy-symbols", type=int, default=8, help="Early-stop target for deploy symbol coverage.")
    parser.add_argument("--target-deploy-rules", type=int, default=16, help="Early-stop target for deploy rule count.")
    parser.add_argument("--target-pass-rate", type=float, default=0.20, help="Early-stop target validation pass rate.")
    parser.add_argument("--target-all-alpha", type=float, default=0.0, help="Early-stop target for all-window avg alpha vs spot.")
    parser.add_argument("--target-deploy-alpha", type=float, default=0.0, help="Early-stop target for deploy avg alpha vs spot.")
    parser.add_argument("--stable-rounds", type=int, default=2, help="Consecutive target-hit cycles required before early stop.")
    parser.add_argument(
        "--validation-mode",
        type=str,
        choices=("standard", "recovery"),
        default="standard",
        help="Validation adaptation profile.",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default=",".join(DEFAULT_SYMBOLS),
        help="Comma-separated symbols to train (e.g. BTCUSDT,ETHUSDT,BNBUSDT,XRPUSDT).",
    )
    parser.add_argument(
        "--with-monitor",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Start/stop progress monitor automatically during supervision.",
    )
    parser.add_argument("--monitor-interval", type=float, default=2.0, help="Progress monitor refresh interval seconds.")
    parser.add_argument(
        "--monitor-export-interval",
        type=float,
        default=10.0,
        help="Dashboard state export interval seconds while monitor is running (0 disables).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    artifact_root = repo_root / "engine" / "artifacts"
    raw_root = repo_root / "engine" / "data" / "raw"
    selected_symbols = _parse_symbols_csv(args.symbols)
    if not selected_symbols:
        raise ValueError("No symbols selected. Use --symbols with at least one symbol.")

    base_env = os.environ.copy()
    baseline_primary_tf = str(base_env.get("ENGINE_BASELINE_PRIMARY_TIMEFRAME", "15m")).strip().lower() or "15m"
    baseline_confirm_tfs = str(base_env.get("ENGINE_BASELINE_CONFIRM_TIMEFRAMES", "5m")).strip().lower() or "5m"
    baseline_feature_allowlist = str(
        base_env.get(
            "ENGINE_BASELINE_FEATURE_ALLOWLIST",
            "trend__logret__15m,flow_liquidity__shock_density__1m,risk_volatility__realized_vol_60__1m",
        )
    ).strip()
    baseline_cores = str(
        base_env.get(
            "ENGINE_FEATURE_CORES",
            "lmo_core_breakout_regime,lmo_core_flow_absorption,lmo_core_risk_compression",
        )
    ).strip()
    base_env.update(
        {
            "ENGINE_RULE_ENGINE_MODE": "feature_native",
            "ENGINE_UNIVERSE_SYMBOLS": ",".join(selected_symbols),
            "ENGINE_TOP_N": str(len(selected_symbols)),
            "ENGINE_OPTIMIZATION_TIMEFRAMES": baseline_primary_tf,
            "ENGINE_BASELINE_PRIMARY_TIMEFRAME": baseline_primary_tf,
            "ENGINE_BASELINE_CONFIRM_TIMEFRAMES": baseline_confirm_tfs,
            "ENGINE_BASELINE_LOW_DOF_MODE": str(base_env.get("ENGINE_BASELINE_LOW_DOF_MODE", "true")),
            "ENGINE_BASELINE_FEATURE_CAP": str(base_env.get("ENGINE_BASELINE_FEATURE_CAP", "3")),
            "ENGINE_BASELINE_FEATURE_ALLOWLIST": baseline_feature_allowlist,
            "ENGINE_OPTIMIZATION_WINDOWS": "all,360d,90d,30d",
            "ENGINE_OPTIMIZATION_GATE_MODES": "gated,ungated",
            "ENGINE_FEATURE_CORES": baseline_cores,
            "ENGINE_VALIDATION_ENABLED": "true",
            "ENGINE_OPT_TARGET_VALIDATION_PASS_RATE": "0.40",
            "ENGINE_OPT_TARGET_ALL_WINDOW_ALPHA_FLOOR": "0.00",
            "ENGINE_OPT_TARGET_DEPLOY_ALPHA_FLOOR": "0.00",
            "ENGINE_OPT_TARGET_DEPLOY_SYMBOL_RATIO": "0.20",
            "ENGINE_RL_ENABLED": str(base_env.get("ENGINE_RL_ENABLED", "false")),
            "ENGINE_RL_UNLOCK_REQUIRES_BASELINE": str(base_env.get("ENGINE_RL_UNLOCK_REQUIRES_BASELINE", "true")),
        }
    )

    monitor_proc: subprocess.Popen[str] | None = None
    monitor_out: Any = None
    monitor_err: Any = None
    if bool(args.with_monitor):
        if _is_progress_monitor_running():
            print("[monitor] existing progress_monitor detected, skip auto-start.")
        else:
            monitor_proc, monitor_out, monitor_err = _start_progress_monitor(
                repo_root=repo_root,
                interval=max(0.2, float(args.monitor_interval)),
                export_interval=max(0.0, float(args.monitor_export_interval)),
            )

    try:
        if not args.skip_ingest:
            missing = [symbol for symbol in selected_symbols if not _symbol_has_1m_data(raw_root=raw_root, symbol=symbol)]
            if missing:
                print(f"[info] Missing 1m data symbols: {missing}")
                for symbol in missing:
                    _run(
                        ["python", "-m", "engine.src.main", "--mode", "once", "--optimize", "off", "--symbol", symbol],
                        env=base_env,
                    )
            else:
                print("[info] All explicit symbols already have local 1m parquet data.")

        if args.validation_mode == "recovery":
            state = TuneState(
                validation_mode="recovery",
                validation_strictness="recovery",
                validation_sample_step=30,
                validation_walk_forward_splits=2,
                validation_cv_folds=2,
                validation_purge_bars=45,
                validation_stress_friction_bps="10",
            )
        else:
            state = TuneState(
                validation_mode="standard",
                validation_strictness="balanced",
                validation_sample_step=20,
                validation_walk_forward_splits=3,
                validation_cv_folds=3,
                validation_purge_bars=90,
                validation_stress_friction_bps="10,20",
            )
        stable_hits = 0
        latest_summary_payload: dict[str, Any] = {}
        latest_deploy_payload: dict[str, Any] = {}
        for cycle_index in range(max(1, int(args.cycles))):
            env = _build_cycle_env(base_env=base_env, state=state, rounds_per_cycle=max(1, int(args.max_rounds)))
            _run(
                ["python", "-m", "engine.src.main", "--mode", "iterate", "--max-rounds", str(max(1, int(args.max_rounds)))],
                env=env,
            )

            latest_report = _latest_iteration_report(artifact_root / "optimization" / "single" / "iterations")
            report_payload = _read_json(latest_report)
            final_artifacts = report_payload.get("final_artifacts", {}) if isinstance(report_payload, dict) else {}
            summary_path = final_artifacts.get("summary") if isinstance(final_artifacts, dict) else None
            validation_path = final_artifacts.get("validation_report") if isinstance(final_artifacts, dict) else None
            deploy_path = final_artifacts.get("deploy_pool") if isinstance(final_artifacts, dict) else None

            summary_payload = (
                _read_json(Path(summary_path))
                if isinstance(summary_path, str)
                else _read_json(_find_latest_summary(artifact_root))
            )
            validation_payload = _read_json(Path(validation_path)) if isinstance(validation_path, str) else {}
            deploy_payload = _read_json(Path(deploy_path)) if isinstance(deploy_path, str) else {}
            latest_summary_payload = summary_payload
            latest_deploy_payload = deploy_payload

            metrics = _extract_cycle_metrics(
                summary_payload=summary_payload,
                validation_payload=validation_payload,
                deploy_payload=deploy_payload,
            )
            _print_cycle(
                cycle=cycle_index + 1,
                total_cycles=max(1, int(args.cycles)),
                state=state,
                metrics=metrics,
            )
            target_hit = bool(
                metrics.validation_pass_rate >= float(args.target_pass_rate)
                and metrics.deploy_symbols >= int(args.target_deploy_symbols)
                and metrics.deploy_rules >= int(args.target_deploy_rules)
                and metrics.all_window_avg_alpha_vs_spot >= float(args.target_all_alpha)
                and metrics.deploy_avg_alpha_vs_spot >= float(args.target_deploy_alpha)
            )
            stable_hits = (stable_hits + 1) if target_hit else 0
            required_stable_hits = max(1, int(args.stable_rounds))
            print(
                f"[target] hit={str(target_hit).lower()} "
                f"streak={stable_hits}/{required_stable_hits}"
            )
            if stable_hits >= required_stable_hits:
                print("[info] Early stop: target quality reached with stability.")
                break
            state = _adapt_state(
                state=state,
                metrics=metrics,
                cycle_index=cycle_index,
                total_cycles=max(1, int(args.cycles)),
                validation_mode=str(args.validation_mode),
            )

        _print_summary(summary_payload=latest_summary_payload, deploy_payload=latest_deploy_payload)
        _export_dashboard_state(repo_root=repo_root, env=base_env)
        return 0
    finally:
        _stop_progress_monitor(proc=monitor_proc, out_file=monitor_out, err_file=monitor_err)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"[fatal] {error}", file=sys.stderr)
        raise SystemExit(1)
