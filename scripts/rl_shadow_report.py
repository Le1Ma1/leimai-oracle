from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_ROOT = ROOT / "engine" / "artifacts" / "optimization" / "single"
DEFAULT_OUT_JSON = ROOT / "logs" / "rl_shadow_report.json"
DEFAULT_OUT_MD = ROOT / "logs" / "rl_shadow_report.md"
FULL_HISTORY_REQUIRED_START_UTC = "2020-01-01T00:00:00Z"


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


def parse_iso_utc(raw: Any) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def find_latest_summary(summary_root: Path) -> Path | None:
    if not summary_root.exists():
        return None
    candidates = sorted(summary_root.rglob("summary.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def reward_proxy(friction_return: float, max_drawdown: float, trades: int) -> float:
    # Conservative utility: reward alpha, penalize drawdown and turnover.
    return float(friction_return - (0.45 * abs(max_drawdown)) - (0.0008 * max(0, int(trades))))


def _extract_candidate_fields(candidate: dict[str, Any]) -> dict[str, Any]:
    metrics = candidate.get("metrics", {}) if isinstance(candidate.get("metrics"), dict) else {}
    return {
        "rule_key": str(candidate.get("rule_key") or ""),
        "core_id": str(candidate.get("core_id") or ""),
        "gate_mode": str(candidate.get("gate_mode") or ""),
        "score": _to_float(candidate.get("score"), 0.0),
        "credibility_penalty": _to_float(candidate.get("credibility_penalty"), 1.0),
        "stability_penalty": _to_float(candidate.get("stability_penalty"), 1.0),
        "friction_adjusted_return": _to_float(metrics.get("friction_adjusted_return"), 0.0),
        "max_drawdown": _to_float(metrics.get("max_drawdown"), 0.0),
        "trades": _to_int(metrics.get("trades"), 0),
    }


def extract_legacy_and_shadow_samples(summary: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    results = summary.get("results", []) if isinstance(summary.get("results"), list) else []
    legacy_rows: list[dict[str, Any]] = []
    shadow_rows: list[dict[str, Any]] = []
    all_starts: list[str] = []

    for result in results:
        if not isinstance(result, dict):
            continue
        gate_mode = str(result.get("gate_mode") or "")
        core_id = str(result.get("core_id") or "")
        windows = result.get("windows", [])
        if not isinstance(windows, list):
            continue
        for window in windows:
            if not isinstance(window, dict):
                continue
            if str(window.get("window")) != "all":
                continue
            all_starts.append(str(window.get("start_utc") or ""))
            best_long = window.get("best_long") if isinstance(window.get("best_long"), dict) else None
            if best_long:
                row = _extract_candidate_fields({**best_long, "gate_mode": gate_mode, "core_id": core_id})
                row["source"] = "legacy_best_long"
                legacy_rows.append(row)

            top = window.get("top_long_candidates", [])
            if isinstance(top, list):
                for cand in top[:8]:
                    if not isinstance(cand, dict):
                        continue
                    row = _extract_candidate_fields({**cand, "gate_mode": gate_mode, "core_id": core_id})
                    row["source"] = "shadow_candidate"
                    shadow_rows.append(row)

    return legacy_rows, shadow_rows, all_starts


def aggregate_legacy(legacy_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not legacy_rows:
        return {
            "count": 0,
            "friction_adjusted_return_avg": 0.0,
            "max_drawdown_worst": 0.0,
            "trades_avg": 0.0,
            "reward_proxy": 0.0,
        }
    frictions = [_to_float(row.get("friction_adjusted_return"), 0.0) for row in legacy_rows]
    drawdowns = [_to_float(row.get("max_drawdown"), 0.0) for row in legacy_rows]
    trades = [_to_int(row.get("trades"), 0) for row in legacy_rows]
    fric_avg = sum(frictions) / len(frictions)
    dd_worst = min(drawdowns) if drawdowns else 0.0
    tr_avg = sum(trades) / float(len(trades)) if trades else 0.0
    return {
        "count": len(legacy_rows),
        "friction_adjusted_return_avg": fric_avg,
        "max_drawdown_worst": dd_worst,
        "trades_avg": tr_avg,
        "reward_proxy": reward_proxy(fric_avg, dd_worst, int(round(tr_avg))),
    }


def aggregate_shadow(shadow_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not shadow_rows:
        return {
            "count": 0,
            "policy": "softmax(score-penalty)",
            "friction_adjusted_return_est": 0.0,
            "max_drawdown_est": 0.0,
            "trades_est": 0.0,
            "reward_proxy": 0.0,
            "top_actions": [],
        }

    logits: list[float] = []
    for row in shadow_rows:
        score = _to_float(row.get("score"), 0.0)
        cred = _to_float(row.get("credibility_penalty"), 1.0)
        stab = _to_float(row.get("stability_penalty"), 1.0)
        logits.append(score - (0.35 * cred) - (0.25 * stab))

    max_logit = max(logits)
    weights = [math.exp(x - max_logit) for x in logits]
    total = sum(weights) if weights else 1.0
    probs = [w / total for w in weights]

    friction_est = sum(p * _to_float(row.get("friction_adjusted_return"), 0.0) for p, row in zip(probs, shadow_rows))
    dd_est = sum(p * _to_float(row.get("max_drawdown"), 0.0) for p, row in zip(probs, shadow_rows))
    trades_est = sum(p * _to_int(row.get("trades"), 0) for p, row in zip(probs, shadow_rows))

    ranked = sorted(
        [
            {
                "rule_key": str(row.get("rule_key") or ""),
                "core_id": str(row.get("core_id") or ""),
                "probability": float(p),
                "score": _to_float(row.get("score"), 0.0),
                "friction_adjusted_return": _to_float(row.get("friction_adjusted_return"), 0.0),
                "max_drawdown": _to_float(row.get("max_drawdown"), 0.0),
                "trades": _to_int(row.get("trades"), 0),
            }
            for p, row in zip(probs, shadow_rows)
        ],
        key=lambda item: item["probability"],
        reverse=True,
    )

    return {
        "count": len(shadow_rows),
        "policy": "softmax(score-penalty)",
        "friction_adjusted_return_est": friction_est,
        "max_drawdown_est": dd_est,
        "trades_est": trades_est,
        "reward_proxy": reward_proxy(friction_est, dd_est, int(round(trades_est))),
        "top_actions": ranked[:12],
    }


def build_history_contract(all_starts: list[str]) -> dict[str, Any]:
    required = parse_iso_utc(FULL_HISTORY_REQUIRED_START_UTC)
    starts = [parse_iso_utc(v) for v in all_starts]
    starts = [v for v in starts if v is not None]
    observed = min(starts) if starts else None
    return {
        "required_start_utc": FULL_HISTORY_REQUIRED_START_UTC,
        "observed_start_utc": None if observed is None else observed.isoformat().replace("+00:00", "Z"),
        "full_history_ok": bool(required and observed and observed <= required),
    }


def build_recommendation(legacy: dict[str, Any], shadow: dict[str, Any], history_contract: dict[str, Any]) -> dict[str, Any]:
    legacy_reward = _to_float(legacy.get("reward_proxy"), 0.0)
    shadow_reward = _to_float(shadow.get("reward_proxy"), 0.0)
    legacy_dd = abs(_to_float(legacy.get("max_drawdown_worst"), 0.0))
    shadow_dd = abs(_to_float(shadow.get("max_drawdown_est"), 0.0))

    out = {
        "recommend": "hold_shadow",
        "reason": "legacy remains primary; shadow is research only",
        "promotion_candidate": False,
    }

    if not bool(history_contract.get("full_history_ok")):
        out["reason"] = "full-history contract not satisfied"
        return out

    if shadow_reward > legacy_reward * 1.03 and shadow_dd <= legacy_dd * 1.05:
        out["recommend"] = "candidate_for_promotion"
        out["reason"] = "shadow reward exceeds legacy with comparable drawdown"
        out["promotion_candidate"] = True
    return out


def write_md(out_path: Path, payload: dict[str, Any]) -> None:
    legacy = payload.get("legacy_baseline", {}) if isinstance(payload.get("legacy_baseline"), dict) else {}
    shadow = payload.get("rl_shadow", {}) if isinstance(payload.get("rl_shadow"), dict) else {}
    rec = payload.get("decision", {}) if isinstance(payload.get("decision"), dict) else {}
    contract = payload.get("history_contract", {}) if isinstance(payload.get("history_contract"), dict) else {}

    lines = [
        "# RL Shadow Report (Offline Research)",
        "",
        f"- generated_at_utc: `{payload.get('generated_at_utc')}`",
        f"- summary_path: `{payload.get('summary_path')}`",
        f"- required_start_utc: `{contract.get('required_start_utc')}`",
        f"- observed_start_utc: `{contract.get('observed_start_utc')}`",
        f"- full_history_ok: `{contract.get('full_history_ok')}`",
        "",
        "## Legacy Baseline",
        f"- friction_adjusted_return_avg: `{_to_float(legacy.get('friction_adjusted_return_avg'), 0.0):+.6f}`",
        f"- max_drawdown_worst: `{_to_float(legacy.get('max_drawdown_worst'), 0.0):+.6f}`",
        f"- trades_avg: `{_to_float(legacy.get('trades_avg'), 0.0):.2f}`",
        f"- reward_proxy: `{_to_float(legacy.get('reward_proxy'), 0.0):+.6f}`",
        "",
        "## RL Shadow Estimate",
        f"- policy: `{shadow.get('policy', 'n/a')}`",
        f"- friction_adjusted_return_est: `{_to_float(shadow.get('friction_adjusted_return_est'), 0.0):+.6f}`",
        f"- max_drawdown_est: `{_to_float(shadow.get('max_drawdown_est'), 0.0):+.6f}`",
        f"- trades_est: `{_to_float(shadow.get('trades_est'), 0.0):.2f}`",
        f"- reward_proxy: `{_to_float(shadow.get('reward_proxy'), 0.0):+.6f}`",
        "",
        "## Decision",
        f"- recommend: `{rec.get('recommend', 'hold_shadow')}`",
        f"- reason: `{rec.get('reason', '-')}`",
        "",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate RL shadow report from latest optimization artifacts.")
    parser.add_argument("--summary-path", default="", help="Optional explicit summary.json path.")
    parser.add_argument("--summary-root", default=str(DEFAULT_SUMMARY_ROOT))
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary_path = Path(args.summary_path).resolve() if str(args.summary_path).strip() else find_latest_summary(Path(args.summary_root))
    if summary_path is None or not summary_path.exists():
        payload = {
            "ok": False,
            "error": "summary_not_found",
            "generated_at_utc": now_iso(),
        }
        Path(args.out_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    summary = read_json(summary_path)
    legacy_rows, shadow_rows, all_starts = extract_legacy_and_shadow_samples(summary)
    legacy = aggregate_legacy(legacy_rows)
    shadow = aggregate_shadow(shadow_rows)
    contract = build_history_contract(all_starts)
    decision = build_recommendation(legacy, shadow, contract)

    payload = {
        "ok": True,
        "generated_at_utc": now_iso(),
        "summary_path": str(summary_path),
        "history_contract": contract,
        "legacy_baseline": legacy,
        "rl_shadow": shadow,
        "decision": decision,
    }

    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_md(Path(args.out_md), payload)

    print(
        json.dumps(
            {
                "ok": True,
                "out_json": str(out_json),
                "out_md": str(args.out_md),
                "decision": decision.get("recommend"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
