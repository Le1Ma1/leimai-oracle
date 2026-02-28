from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


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


@dataclass(frozen=True)
class BatchSlice:
    index: int
    total: int
    symbols: tuple[str, ...]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_symbols(symbols_csv: str | None) -> tuple[str, ...]:
    if not symbols_csv:
        return tuple(DEFAULT_SYMBOLS)
    values = tuple(item.strip().upper() for item in symbols_csv.split(",") if item.strip())
    return values if values else tuple(DEFAULT_SYMBOLS)


def _split_batches(symbols: tuple[str, ...], batch_total: int) -> list[tuple[str, ...]]:
    if batch_total <= 1:
        return [symbols]
    n = len(symbols)
    out: list[tuple[str, ...]] = []
    for i in range(batch_total):
        start = int(round(i * n / batch_total))
        end = int(round((i + 1) * n / batch_total))
        bucket = tuple(symbols[start:end])
        if bucket:
            out.append(bucket)
    if not out:
        out.append(symbols)
    return out


def _pick_batch(symbols: tuple[str, ...], batch_index: int, batch_total: int) -> BatchSlice:
    buckets = _split_batches(symbols, batch_total=batch_total)
    idx = max(1, min(batch_index, len(buckets)))
    return BatchSlice(index=idx, total=len(buckets), symbols=buckets[idx - 1])


def _default_run_id(target: str, batch: BatchSlice) -> str:
    stamp = _now_utc().strftime("%Y%m%dT%H%M%SZ")
    return f"{target}_b{batch.index}of{batch.total}_{stamp}"


def _infer_state_phase(status: str, tasks_done: int, tasks_total: int) -> str:
    normalized = status.lower()
    if normalized in {"failed", "error"}:
        return "error"
    if normalized in {"completed", "done"}:
        return "done"
    if tasks_total > 0 and tasks_done > 0:
        return "running"
    return "pending"


def _build_symbol_progress(symbols: tuple[str, ...], status: str, tasks_done: int, tasks_total: int) -> list[dict]:
    phase = _infer_state_phase(status=status, tasks_done=tasks_done, tasks_total=tasks_total)
    if phase == "done":
        return [{"symbol": sym, "done": 1, "total": 1, "pct": 100.0, "phase": "done"} for sym in symbols]
    if phase == "running":
        if not symbols:
            return []
        per_sym = max(0.0, min(1.0, float(tasks_done) / float(max(tasks_total, 1))))
        done_count = int(round(per_sym * len(symbols)))
        rows: list[dict] = []
        for idx, sym in enumerate(symbols):
            if idx < done_count:
                rows.append({"symbol": sym, "done": 1, "total": 1, "pct": 100.0, "phase": "done"})
            elif idx == done_count:
                rows.append({"symbol": sym, "done": 0, "total": 1, "pct": 35.0, "phase": "running"})
            else:
                rows.append({"symbol": sym, "done": 0, "total": 1, "pct": 0.0, "phase": "pending"})
        return rows
    return [{"symbol": sym, "done": 0, "total": 1, "pct": 0.0, "phase": "pending"} for sym in symbols]


def _normalize_status(status: str) -> str:
    value = status.strip().lower()
    if value in {"queued", "pending"}:
        return "queued"
    if value in {"running", "active"}:
        return "running"
    if value in {"completed", "done", "success"}:
        return "completed"
    if value in {"failed", "error"}:
        return "failed"
    raise ValueError(f"Unsupported status: {status}")


def _derive_eta(seconds_remaining: int | None) -> tuple[int | None, str | None]:
    if seconds_remaining is None:
        return None, None
    seconds_remaining = max(0, int(seconds_remaining))
    eta = _now_utc() + timedelta(seconds=seconds_remaining)
    return seconds_remaining, _iso_z(eta)


def _emit_commands(target: str, batch: BatchSlice, max_rounds: int, skip_ingest: bool) -> list[str]:
    symbols_csv = ",".join(batch.symbols)
    base_env = [
        f"ENGINE_UNIVERSE_SYMBOLS={symbols_csv}",
        "ENGINE_RULE_ENGINE_MODE=feature_native",
        "ENGINE_OPTIMIZATION_GATE_MODES=gated,ungated",
    ]
    ingest_line = " --skip-ingest" if skip_ingest else ""
    if target == "kaggle":
        return [
            " && ".join(base_env + [f"python scripts/alpha_supervisor.py --max-rounds {max_rounds}{ingest_line}"]),
            "python -m engine.src.main --mode validate",
        ]
    return [
        " && ".join(base_env + [f"python scripts/alpha_supervisor.py --max-rounds {max_rounds}{ingest_line}"]),
        "python -m engine.src.main --mode validate",
    ]


def cmd_prepare(args: argparse.Namespace) -> int:
    symbols = _parse_symbols(args.symbols)
    batch = _pick_batch(symbols=symbols, batch_index=args.batch_index, batch_total=max(1, args.batch_total))
    commands = _emit_commands(
        target=str(args.target),
        batch=batch,
        max_rounds=max(1, int(args.max_rounds)),
        skip_ingest=bool(args.skip_ingest),
    )
    payload = {
        "target": args.target,
        "batch": {"index": batch.index, "total": batch.total, "symbols": list(batch.symbols)},
        "commands": commands,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_manifest(args: argparse.Namespace) -> int:
    repo_root = _repo_root()
    symbols = _parse_symbols(args.symbols)
    batch = _pick_batch(symbols=symbols, batch_index=args.batch_index, batch_total=max(1, args.batch_total))
    status = _normalize_status(args.status)
    run_id = str(args.run_id or _default_run_id(target=str(args.target), batch=batch))
    notes = [item.strip() for item in (args.note or []) if item.strip()]

    tasks_total = max(0, int(args.tasks_total))
    tasks_done = max(0, min(int(args.tasks_done), tasks_total if tasks_total > 0 else int(args.tasks_done)))
    tasks_pct = float(tasks_done / tasks_total * 100.0) if tasks_total > 0 else 0.0
    eta_seconds, eta_utc = _derive_eta(args.eta_seconds)

    symbol_progress = _build_symbol_progress(
        symbols=batch.symbols,
        status=status,
        tasks_done=tasks_done,
        tasks_total=tasks_total,
    )

    manifest = {
        "schema": "lmo.cloud_run_manifest.v1",
        "updated_at_utc": _iso_z(_now_utc()),
        "source": str(args.target),
        "status": status,
        "run_id": run_id,
        "batch": {
            "index": batch.index,
            "total": batch.total,
            "symbols": list(batch.symbols),
        },
        "progress": {
            "tasks_total": tasks_total,
            "tasks_done": tasks_done,
            "tasks_pct": round(tasks_pct, 2),
        },
        "eta": {
            "seconds_remaining": eta_seconds,
            "eta_utc": eta_utc,
            "confidence": str(args.confidence),
        },
        "quality_snapshot": {
            "run_id": None,
            "validation_pass_rate": 0.0,
            "all_window_alpha_vs_spot": 0.0,
            "deploy_symbols": 0,
            "deploy_rules": 0,
            "deploy_avg_alpha_vs_spot": 0.0,
        },
        "symbol_progress": symbol_progress,
        "outputs": {
            "summary_json": str(args.summary_path) if args.summary_path else None,
            "validation_report": str(args.validation_path) if args.validation_path else None,
            "deploy_pool": str(args.deploy_path) if args.deploy_path else None,
        },
        "notes": notes,
    }

    output = Path(args.output).resolve() if args.output else (repo_root / "engine" / "artifacts" / "cloud" / "cloud_run_manifest.json")
    _write_json(output, manifest)

    if args.mirror_to_daily:
        today = _now_utc().date().isoformat()
        daily_path = repo_root / "engine" / "artifacts" / "optimization" / "single" / today / "cloud_run_manifest.json"
        _write_json(daily_path, manifest)

    print(f"[manifest_written] {output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cloud batch dispatcher and manifest writer.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_prepare = sub.add_parser("prepare", help="Print command payload for one cloud batch.")
    p_prepare.add_argument("--target", choices=("kaggle", "colab"), default="kaggle")
    p_prepare.add_argument("--batch-index", type=int, default=1)
    p_prepare.add_argument("--batch-total", type=int, default=3)
    p_prepare.add_argument("--symbols", default=None, help="CSV list of symbols. Defaults to 15-symbol basket.")
    p_prepare.add_argument("--max-rounds", type=int, default=1)
    p_prepare.add_argument("--skip-ingest", action="store_true")
    p_prepare.set_defaults(func=cmd_prepare)

    p_manifest = sub.add_parser("manifest", help="Write cloud_run_manifest.json for monitor ingestion.")
    p_manifest.add_argument("--target", choices=("kaggle", "colab"), default="kaggle")
    p_manifest.add_argument("--status", default="running", help="queued|running|completed|failed")
    p_manifest.add_argument("--run-id", default=None)
    p_manifest.add_argument("--batch-index", type=int, default=1)
    p_manifest.add_argument("--batch-total", type=int, default=3)
    p_manifest.add_argument("--symbols", default=None, help="CSV list of symbols. Defaults to 15-symbol basket.")
    p_manifest.add_argument("--tasks-total", type=int, default=0)
    p_manifest.add_argument("--tasks-done", type=int, default=0)
    p_manifest.add_argument("--eta-seconds", type=int, default=None)
    p_manifest.add_argument("--confidence", default="medium", help="low|medium|high")
    p_manifest.add_argument("--summary-path", default=None)
    p_manifest.add_argument("--validation-path", default=None)
    p_manifest.add_argument("--deploy-path", default=None)
    p_manifest.add_argument("--output", default=None)
    p_manifest.add_argument("--note", action="append", default=None, help="Repeatable note field.")
    p_manifest.add_argument("--mirror-to-daily", action="store_true")
    p_manifest.set_defaults(func=cmd_manifest)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
