from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIVE_STATUS = ROOT / "engine" / "artifacts" / "monitor" / "live_status.json"
DEFAULT_ITERATION_ROOT = ROOT / "engine" / "artifacts" / "optimization" / "single" / "iterations"
DEFAULT_OUT_JSON = ROOT / "logs" / "ml_progress_report.json"
DEFAULT_OUT_MD = ROOT / "logs" / "ml_progress_report.md"


@dataclass(frozen=True)
class Targets:
    pass_rate: float
    deploy_symbols: int
    deploy_rules: int
    all_alpha: float


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if out != out:
            return float(default)
        return out
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_targets(live_status: dict[str, Any]) -> Targets:
    raw = live_status.get("targets", {}).get("thresholds", {}) if isinstance(live_status, dict) else {}
    return Targets(
        pass_rate=max(0.01, _to_float(raw.get("target_pass_rate"), 0.40)),
        deploy_symbols=max(1, _to_int(raw.get("target_deploy_symbols"), 1)),
        deploy_rules=max(1, _to_int(raw.get("target_deploy_rules"), 2)),
        all_alpha=_to_float(raw.get("target_all_alpha"), -3.0),
    )


def _resolve_artifact_path(raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    p = Path(raw)
    if p.is_absolute():
        return p
    return (ROOT / p).resolve()


def _extract_all_window_alpha(validation_payload: dict[str, Any], fallback: float = 0.0) -> float:
    rows = validation_payload.get("summary_by_window", [])
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("window")) != "all":
                continue
            return _to_float(row.get("avg_alpha_vs_spot"), fallback)
    return fallback


def _score(metrics: dict[str, Any], targets: Targets) -> float:
    pass_norm = clip01(_to_float(metrics.get("validation_pass_rate"), 0.0) / targets.pass_rate)
    sym_norm = clip01(_to_int(metrics.get("deploy_symbols"), 0) / float(targets.deploy_symbols))
    rule_norm = clip01(_to_int(metrics.get("deploy_rules"), 0) / float(targets.deploy_rules))
    alpha = _to_float(metrics.get("all_window_alpha_vs_spot"), -10.0)
    alpha_norm = clip01((alpha - targets.all_alpha + 2.0) / 4.0)
    return round((0.35 * pass_norm) + (0.25 * sym_norm) + (0.20 * rule_norm) + (0.20 * alpha_norm), 6)


def collect_iterations(iteration_root: Path, limit: int, targets: Targets) -> list[dict[str, Any]]:
    if not iteration_root.exists():
        return []
    files = sorted(
        (p for p in iteration_root.rglob("iteration_*.json") if "decision_log" not in p.name),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[: max(1, limit)]

    rows: list[dict[str, Any]] = []
    for path in files:
        iteration = read_json(path)
        if not iteration:
            continue
        artifacts = iteration.get("final_artifacts", {}) if isinstance(iteration.get("final_artifacts"), dict) else {}
        summary_path = _resolve_artifact_path(artifacts.get("summary"))
        validation_path = _resolve_artifact_path(artifacts.get("validation_report"))
        deploy_path = _resolve_artifact_path(artifacts.get("deploy_pool"))

        summary = read_json(summary_path) if summary_path else {}
        validation = read_json(validation_path) if validation_path else {}
        deploy = read_json(deploy_path) if deploy_path else {}
        best = iteration.get("best_round_score", {}) if isinstance(iteration.get("best_round_score"), dict) else {}

        all_alpha = _extract_all_window_alpha(validation, fallback=_to_float(best.get("all_window_avg_alpha_vs_spot"), -10.0))
        row = {
            "iteration_file": str(path),
            "ts_utc": str(iteration.get("ts_utc") or ""),
            "run_id": str(
                iteration.get("final_run_id")
                or iteration.get("best_round_run_id")
                or validation.get("run_id")
                or summary.get("run_id")
                or ""
            ),
            "validation_pass_rate": _to_float(validation.get("pass_rate"), _to_float(best.get("validation_pass_rate"), 0.0)),
            "all_window_alpha_vs_spot": all_alpha,
            "deploy_symbols": _to_int(deploy.get("total_symbols"), _to_int(best.get("deploy_total_symbols"), 0)),
            "deploy_rules": _to_int(deploy.get("total_rules"), _to_int(best.get("deploy_total_rules"), 0)),
        }
        row["quality_score"] = _score(row, targets)
        rows.append(row)

    rows.sort(key=lambda item: str(item.get("ts_utc") or ""))
    previous: dict[str, Any] | None = None
    for row in rows:
        if previous is None:
            row["delta"] = {
                "validation_pass_rate": 0.0,
                "all_window_alpha_vs_spot": 0.0,
                "deploy_symbols": 0,
                "deploy_rules": 0,
                "quality_score": 0.0,
            }
        else:
            row["delta"] = {
                "validation_pass_rate": round(
                    _to_float(row.get("validation_pass_rate")) - _to_float(previous.get("validation_pass_rate")),
                    6,
                ),
                "all_window_alpha_vs_spot": round(
                    _to_float(row.get("all_window_alpha_vs_spot")) - _to_float(previous.get("all_window_alpha_vs_spot")),
                    6,
                ),
                "deploy_symbols": _to_int(row.get("deploy_symbols")) - _to_int(previous.get("deploy_symbols")),
                "deploy_rules": _to_int(row.get("deploy_rules")) - _to_int(previous.get("deploy_rules")),
                "quality_score": round(
                    _to_float(row.get("quality_score")) - _to_float(previous.get("quality_score")),
                    6,
                ),
            }
        previous = row
    return rows


def _failed_target_checks(live_status: dict[str, Any]) -> list[str]:
    checks = live_status.get("targets", {}).get("checks", []) if isinstance(live_status, dict) else []
    out: list[str] = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        if bool(item.get("passed")):
            continue
        key = str(item.get("key") or "").strip()
        if key:
            out.append(key)
    return out


def derive_priority_mode(live_status: dict[str, Any], latest: dict[str, Any], targets: Targets) -> tuple[str, list[str]]:
    reasons: list[str] = []
    pipeline_state = str(live_status.get("pipeline_state") or "").strip().lower()
    stall_reason = str(live_status.get("stall_reason") or "").strip()
    promotion_block_reason = str(live_status.get("promotion_block_reason") or "").strip()

    pass_rate = _to_float(latest.get("validation_pass_rate"), 0.0)
    all_alpha = _to_float(latest.get("all_window_alpha_vs_spot"), -10.0)
    deploy_symbols = _to_int(latest.get("deploy_symbols"), 0)
    deploy_rules = _to_int(latest.get("deploy_rules"), 0)

    if pipeline_state == "stalled":
        reasons.append(f"pipeline_stalled:{stall_reason or 'unknown'}")
    if promotion_block_reason:
        reasons.append(f"promotion_block:{promotion_block_reason}")

    if pass_rate < targets.pass_rate:
        reasons.append("validation_pass_rate_below_target")
    if all_alpha < targets.all_alpha:
        reasons.append("all_window_alpha_below_target")
    if deploy_symbols < targets.deploy_symbols:
        reasons.append("deploy_symbols_below_target")
    if deploy_rules < targets.deploy_rules:
        reasons.append("deploy_rules_below_target")

    for key in _failed_target_checks(live_status):
        reasons.append(f"target_check_failed:{key}")

    if reasons:
        return "legacy_recovery", list(dict.fromkeys(reasons))
    if pipeline_state in {"running", "validation", "finalizing"}:
        return "dual_train", []
    return "idle", []


def build_feature_actions(latest: dict[str, Any]) -> dict[str, list[str]]:
    delta = latest.get("delta", {}) if isinstance(latest.get("delta"), dict) else {}
    alpha_delta = _to_float(delta.get("all_window_alpha_vs_spot"), 0.0)
    pass_delta = _to_float(delta.get("validation_pass_rate"), 0.0)

    boost: list[str] = []
    prune: list[str] = []
    watch: list[str] = []

    if alpha_delta <= 0.0:
        boost.extend(
            [
                "flow_liquidity__shock_density__1m",
                "risk_volatility__realized_vol_60__1m",
                "timing_execution__jump_density__1m",
            ]
        )
    else:
        watch.append("alpha improving; keep current feature family mix")

    if pass_delta < 0.0:
        prune.extend(
            [
                "high-collinearity weak utility factors (from feature_weight_profile.prune_candidates)",
                "overfit rule variants with low trade count",
            ]
        )
    else:
        watch.append("validation pass rate is stable or improving")

    return {
        "boost": boost[:5],
        "prune": prune[:5],
        "watch": watch[:5],
    }


def build_role_decisions(
    live_status: dict[str, Any],
    latest: dict[str, Any],
    targets: Targets,
    priority_mode: str,
    reasons: list[str],
) -> dict[str, str]:
    pass_rate = _to_float(latest.get("validation_pass_rate"), 0.0)
    all_alpha = _to_float(latest.get("all_window_alpha_vs_spot"), -10.0)
    deploy_rules = _to_int(latest.get("deploy_rules"), 0)

    macro = (
        "all-window alpha remains below target; keep macro direction but tighten entry quality."
        if all_alpha < targets.all_alpha
        else "macro direction is acceptable; preserve regime sensitivity and avoid over-tightening."
    )
    feature = (
        "boost flow/risk/timing families and prune high-collinearity low-utility features."
        if pass_rate < targets.pass_rate
        else "feature stack is stable; only incremental pruning is needed."
    )
    risk = (
        "legacy-first risk mode is active until pass-rate and alpha both recover."
        if priority_mode == "legacy_recovery"
        else "dual-track mode is allowed; keep drawdown controls strict."
    )
    execution = (
        "new model stays in shadow run while legacy gates are below target."
        if priority_mode == "legacy_recovery"
        else "run legacy and nonlinear tracks in parallel, promote only after stability."
    )
    if deploy_rules < targets.deploy_rules:
        execution = f"{execution} deploy rule coverage is below target."
    if reasons:
        risk = f"{risk} reasons={','.join(reasons[:3])}"

    return {
        "macro_strategist": macro,
        "feature_auditor": feature,
        "risk_controller": risk,
        "execution_operator": execution,
    }


def build_recommendations(
    live_status: dict[str, Any],
    latest: dict[str, Any],
    targets: Targets,
    priority_mode: str,
) -> list[str]:
    items: list[str] = []
    pipeline_state = str(live_status.get("pipeline_state") or "")
    stall_reason = str(live_status.get("stall_reason") or "")
    if pipeline_state == "stalled":
        items.append(f"Pipeline is stalled ({stall_reason or 'unknown'}); restart monitor/supervisor and continue legacy recovery.")

    pass_rate = _to_float(latest.get("validation_pass_rate"), 0.0)
    all_alpha = _to_float(latest.get("all_window_alpha_vs_spot"), -10.0)
    deploy_symbols = _to_int(latest.get("deploy_symbols"), 0)
    deploy_rules = _to_int(latest.get("deploy_rules"), 0)

    if pass_rate < targets.pass_rate:
        items.append("Validation pass rate is below target; keep trade-floor adaptation and legacy rounds active.")
    if all_alpha < targets.all_alpha:
        items.append("All-window alpha is below target; tighten gate thresholds and prioritize causal feature quality.")
    if deploy_symbols < targets.deploy_symbols or deploy_rules < targets.deploy_rules:
        items.append("Deploy coverage is below target; enforce at least 1 symbol / 2 rules before promotion.")

    items.append("Continue legacy BTC training: python scripts/btc_phase_runner.py --profile institutional_ramp --wait-existing")
    if priority_mode == "legacy_recovery":
        items.append("Defer new model expansion until legacy gates recover above target.")
    else:
        items.append("Run nonlinear backtest branch: python scripts/btc_phase_runner.py --profile nonlinear_grid_v1 --wait-existing")
    return items


def write_report_md(
    out_path: Path,
    *,
    generated_at: str,
    live_status: dict[str, Any],
    targets: Targets,
    rows: list[dict[str, Any]],
    recommendations: list[str],
    priority_mode: str,
    role_decisions: dict[str, str],
) -> None:
    latest = rows[-1] if rows else {}
    lines: list[str] = []
    lines.append("# ML Progress Report (Legacy BTC + Current State)")
    lines.append("")
    lines.append(f"- generated_at_utc: `{generated_at}`")
    lines.append(f"- pipeline_state: `{live_status.get('pipeline_state', 'unknown')}`")
    lines.append(f"- stall_reason: `{live_status.get('stall_reason', 'none')}`")
    lines.append(f"- promotion_block_reason: `{live_status.get('promotion_block_reason', 'none')}`")
    lines.append(f"- priority_mode: `{priority_mode}`")
    lines.append("")
    lines.append("## Latest Snapshot")
    lines.append("")
    lines.append(f"- run_id: `{latest.get('run_id', '-')}`")
    lines.append(f"- validation_pass_rate: `{_to_float(latest.get('validation_pass_rate'), 0.0):.4f}` (target `{targets.pass_rate:.2f}`)")
    lines.append(f"- all_window_alpha_vs_spot: `{_to_float(latest.get('all_window_alpha_vs_spot'), 0.0):+.4f}` (target `{targets.all_alpha:+.2f}`)")
    lines.append(f"- deploy: `{_to_int(latest.get('deploy_symbols'), 0)} symbols / {_to_int(latest.get('deploy_rules'), 0)} rules`")
    lines.append(f"- quality_score: `{_to_float(latest.get('quality_score'), 0.0):.4f}`")
    lines.append("")
    lines.append("## Role Decisions")
    lines.append("")
    for key, value in role_decisions.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Iteration Trend")
    lines.append("")
    if not rows:
        lines.append("- no iteration artifacts found")
    else:
        for row in rows[-6:]:
            delta = row.get("delta", {})
            lines.append(
                "- "
                f"`{row.get('ts_utc', '-')}` | `{row.get('run_id', '-')}` | "
                f"pass `{_to_float(row.get('validation_pass_rate'), 0.0):.4f}` "
                f"(d `{_to_float(delta.get('validation_pass_rate'), 0.0):+.4f}`), "
                f"alpha `{_to_float(row.get('all_window_alpha_vs_spot'), 0.0):+.4f}` "
                f"(d `{_to_float(delta.get('all_window_alpha_vs_spot'), 0.0):+.4f}`), "
                f"deploy `{_to_int(row.get('deploy_symbols'), 0)}/{_to_int(row.get('deploy_rules'), 0)}` "
                f"(d `{_to_int(delta.get('deploy_symbols'), 0)}/{_to_int(delta.get('deploy_rules'), 0)}`), "
                f"score `{_to_float(row.get('quality_score'), 0.0):.4f}` "
                f"(d `{_to_float(delta.get('quality_score'), 0.0):+.4f}`)"
            )
    lines.append("")
    lines.append("## Optimization Continuation Plan")
    lines.append("")
    for rec in recommendations:
        lines.append(f"- {rec}")
    lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate ML progress report for legacy BTC iterations.")
    parser.add_argument("--live-status", default=str(DEFAULT_LIVE_STATUS))
    parser.add_argument("--iteration-root", default=str(DEFAULT_ITERATION_ROOT))
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    live_status = read_json(Path(args.live_status))
    targets = parse_targets(live_status)
    rows = collect_iterations(Path(args.iteration_root), max(1, int(args.limit)), targets)
    latest = rows[-1] if rows else {}
    priority_mode, priority_reasons = derive_priority_mode(live_status, latest, targets)
    role_decisions = build_role_decisions(live_status, latest, targets, priority_mode, priority_reasons)
    feature_actions = build_feature_actions(latest)
    recommendations = build_recommendations(live_status, latest, targets, priority_mode)

    payload = {
        "generated_at_utc": now_iso(),
        "targets": {
            "validation_pass_rate": targets.pass_rate,
            "deploy_symbols": targets.deploy_symbols,
            "deploy_rules": targets.deploy_rules,
            "all_window_alpha_vs_spot": targets.all_alpha,
        },
        "priority_mode": priority_mode,
        "priority_reasons": priority_reasons,
        "live_status": {
            "pipeline_state": live_status.get("pipeline_state"),
            "stall_reason": live_status.get("stall_reason"),
            "promotion_block_reason": live_status.get("promotion_block_reason"),
            "active_run_id": live_status.get("active_run_id"),
        },
        "role_decisions": role_decisions,
        "feature_actions": feature_actions,
        "iterations": rows,
        "latest": latest,
        "recommendations": recommendations,
    }

    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report_md(
        Path(args.out_md),
        generated_at=payload["generated_at_utc"],
        live_status=live_status,
        targets=targets,
        rows=rows,
        recommendations=recommendations,
        priority_mode=priority_mode,
        role_decisions=role_decisions,
    )

    print(
        json.dumps(
            {
                "ok": True,
                "out_json": str(out_json),
                "out_md": str(args.out_md),
                "iterations": len(rows),
                "latest_run_id": latest.get("run_id"),
                "priority_mode": priority_mode,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
