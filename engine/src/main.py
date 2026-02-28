from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .iterate_optimize import run_iterative_optimization
from .logging_setup import log_event
from .run_once import main as run_once_main
from .scheduler import run_scheduled
from .validation import write_validation_from_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="LeiMai Oracle data engine entrypoint.")
    parser.add_argument("--mode", choices=["once", "scheduler", "iterate", "validate"], default="once")
    parser.add_argument(
        "--optimize",
        choices=["auto", "on", "off"],
        default="auto",
        help="Optimization mode for once execution.",
    )
    parser.add_argument("--symbol", default=None, help="Optional symbol filter, e.g. BTCUSDT.")
    parser.add_argument("--max-rounds", type=int, default=0, help="Max rounds for iterative optimization mode (0=use config).")
    parser.add_argument("--summary-path", default=None, help="Optional summary.json path for validate mode.")
    args = parser.parse_args()

    if args.mode == "scheduler":
        run_scheduled()
        return 0
    if args.mode == "iterate":
        cfg = load_config()
        rounds = max(1, int(args.max_rounds)) if int(args.max_rounds) > 0 else int(cfg.optimization_max_rounds)
        return run_iterative_optimization(max_rounds=rounds)
    if args.mode == "validate":
        cfg = load_config()
        try:
            paths = write_validation_from_summary(
                cfg=cfg,
                artifact_root=cfg.artifact_root,
                raw_layer_root=cfg.data_root / "raw",
                summary_path=Path(args.summary_path) if args.summary_path else None,
                run_start_utc=cfg.run_start_utc,
                run_end_utc=cfg.run_end_utc,
            )
            log_event(
                "VALIDATE_ONLY_DONE",
                summary_path=args.summary_path,
                validation_report=paths.get("validation_report"),
                deploy_pool=paths.get("deploy_pool"),
            )
            return 0
        except Exception as error:
            log_event("VALIDATE_ONLY_FAILED", summary_path=args.summary_path, error=str(error))
            return 1

    run_optimization: bool | None
    if args.optimize == "on":
        run_optimization = True
    elif args.optimize == "off":
        run_optimization = False
    else:
        run_optimization = None
    return run_once_main(run_optimization=run_optimization, symbol_filter=args.symbol)


if __name__ == "__main__":
    raise SystemExit(main())
