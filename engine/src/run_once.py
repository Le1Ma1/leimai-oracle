from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd

from .aggregate import aggregate_timeframes
from .config import EngineConfig, load_config
from .feature_cores import list_supported_cores
from .features import build_feature_registry, build_feature_set
from .ingest_1m import ingest_1m_hybrid
from .logging_setup import log_event
from .optimization import optimize_signal_core_for_symbol_timeframe
from .reporting import write_optimization_artifacts
from .storage import write_partitioned_parquet
from .types import RunReport, TimeframeOptimizationResult
from .universe import select_top15_universe, write_universe_snapshot
from .validation import write_validation_artifacts


def _filter_universe_by_symbol(universe: list, symbol_filter: str | None) -> list:
    if symbol_filter is None:
        return universe
    target = symbol_filter.upper()
    return [item for item in universe if item.symbol.upper() == target]


def run_pipeline_once(
    config: EngineConfig | None = None,
    timeframe_subset: tuple[str, ...] | None = None,
    run_optimization: bool | None = None,
    symbol_filter: str | None = None,
) -> RunReport:
    cfg = config or load_config()
    if cfg.optimization_timeframes != ("1m",):
        raise ValueError(
            "Optimization timeframe is hard-locked to 1m. "
            f"Current value: {cfg.optimization_timeframes}"
        )
    started_at = datetime.now(timezone.utc)
    run_id = uuid4().hex
    run_tag = started_at.strftime("%Y%m%dT%H%M%SZ") + "_" + run_id[:8]
    selected_tfs = timeframe_subset or cfg.aggregate_timeframes
    should_optimize = cfg.optimization_enabled if run_optimization is None else run_optimization
    strategy_ids = cfg.feature_cores if cfg.rule_engine_mode == "feature_native" else cfg.single_indicators
    if cfg.rule_engine_mode == "feature_native":
        unsupported = [item for item in strategy_ids if item not in set(list_supported_cores())]
        if unsupported:
            raise ValueError(f"Unsupported ENGINE_FEATURE_CORES values: {unsupported}")

    failures: list[str] = []
    output_paths: list[str] = []
    optimization_paths: dict[str, str] | None = None
    symbols_processed = 0
    missing_filled_count = 0
    optimization_results: list[TimeframeOptimizationResult] = []
    feature_registry_entries: list[dict[str, object]] = []

    log_event(
        "PIPELINE_START",
        run_id=run_id,
        start_utc=started_at.isoformat(),
        quote_asset=cfg.quote_asset,
        top_n=cfg.top_n,
        raw_timeframe=cfg.raw_timeframe,
        aggregate_timeframes=list(selected_tfs),
        optimization_enabled=should_optimize,
        symbol_filter=symbol_filter,
    )

    universe_full = select_top15_universe(cfg)
    universe_path = write_universe_snapshot(
        assets=universe_full,
        output_dir=cfg.artifact_root / "universe",
        asof_date=started_at.date(),
    )
    universe = _filter_universe_by_symbol(universe=universe_full, symbol_filter=symbol_filter)
    if not universe:
        raise RuntimeError(f"No symbols matched symbol_filter={symbol_filter}.")
    log_event(
        "UNIVERSE_SELECTED",
        run_id=run_id,
        assets=len(universe),
        assets_full=len(universe_full),
        artifact=str(universe_path),
        symbols=[item.symbol for item in universe],
    )

    raw_root = cfg.data_root / "raw"
    curated_root = cfg.data_root / "curated"
    cache_root = cfg.artifact_root / "archive_cache"
    tfs_required_for_optimization = tuple(
        sorted(set(cfg.optimization_timeframes) | set(cfg.feature_timeframes) | {"1m"})
    )
    tfs_to_compute = tuple(sorted(set(selected_tfs) | (set(tfs_required_for_optimization) if should_optimize else set())))

    for asset in universe:
        symbol = asset.symbol
        try:
            frame_1m, missing_ranges, archive_rows, backfill_rows = ingest_1m_hybrid(
                archive_base_url=cfg.archive_base_url,
                binance_api_base_url=cfg.binance_api_base_url,
                symbol=symbol,
                start_utc=cfg.run_start_utc,
                end_utc=cfg.run_end_utc,
                cache_dir=cache_root / symbol,
            )
            if frame_1m.empty:
                failures.append(f"{symbol}: no data fetched")
                continue

            symbols_processed += 1
            missing_filled_count += missing_ranges

            log_event(
                "ARCHIVE_LOADED",
                run_id=run_id,
                symbol=symbol,
                rows=archive_rows,
                start_ts_utc=frame_1m.index[0].isoformat(),
                end_ts_utc=frame_1m.index[-1].isoformat(),
            )
            log_event(
                "API_BACKFILL_DONE",
                run_id=run_id,
                symbol=symbol,
                missing_ranges=missing_ranges,
                backfill_rows=backfill_rows,
            )

            raw_paths = write_partitioned_parquet(
                df=frame_1m,
                layer_root=raw_root,
                symbol=symbol,
                timeframe="1m",
                run_tag=run_tag,
            )
            output_paths.extend(raw_paths)
            log_event("PARQUET_WRITTEN", run_id=run_id, symbol=symbol, layer="raw", timeframe="1m", files=len(raw_paths))

            aggregated = aggregate_timeframes(df_1m=frame_1m, timeframes=tfs_to_compute)
            log_event(
                "AGGREGATION_DONE",
                run_id=run_id,
                symbol=symbol,
                timeframes=list(tfs_to_compute),
                input_rows=int(frame_1m.shape[0]),
            )

            for tf in selected_tfs:
                tf_frame = aggregated.get(tf, pd.DataFrame())
                if tf_frame.empty:
                    continue
                curated_paths = write_partitioned_parquet(
                    df=tf_frame,
                    layer_root=curated_root,
                    symbol=symbol,
                    timeframe=tf,
                    run_tag=run_tag,
                )
                output_paths.extend(curated_paths)
                log_event(
                    "PARQUET_WRITTEN",
                    run_id=run_id,
                    symbol=symbol,
                    layer="curated",
                    timeframe=tf,
                    files=len(curated_paths),
                )

            if should_optimize:
                log_event(
                    "OPTIMIZATION_START",
                    run_id=run_id,
                    symbol=symbol,
                    timeframes=list(cfg.optimization_timeframes),
                    gate_modes=list(cfg.optimization_gate_modes),
                    rule_engine_mode=cfg.rule_engine_mode,
                    signal_cores=list(strategy_ids),
                    long_only=cfg.optimization_long_only,
                    objective_mode=cfg.objective_mode,
                    windows=list(cfg.optimization_windows),
                    trade_floor=cfg.trade_floor,
                )
                htf_map = {tf: aggregated.get(tf, pd.DataFrame()) for tf in cfg.feature_timeframes}
                feature_set = build_feature_set(df_1m=frame_1m, htf_map=htf_map)
                feature_registry_entries.extend(build_feature_registry(feature_set))
                log_event(
                    "FEATURESET_READY",
                    run_id=run_id,
                    symbol=symbol,
                    features=int(feature_set.shape[1]),
                    rows=int(feature_set.shape[0]),
                )

                timeframe = "1m"
                price_frame = frame_1m
                if price_frame.empty:
                    log_event(
                        "WINDOW_OPTIMIZED",
                        run_id=run_id,
                        symbol=symbol,
                        timeframe=timeframe,
                        status="skipped_no_data",
                    )
                    continue

                for core_id in strategy_ids:
                    for gate_mode in cfg.optimization_gate_modes:
                        result = optimize_signal_core_for_symbol_timeframe(
                            price_frame=price_frame,
                            feature_set_1m=feature_set,
                            cfg=cfg,
                            symbol=symbol,
                            timeframe=timeframe,
                            gate_mode=gate_mode,
                            core_id=core_id,
                        )
                        optimization_results.append(result)
                        valid_windows = sum(
                            1 for window in result["windows"] if not window["insufficient_statistical_significance"]
                        )
                        log_event(
                            "WINDOW_OPTIMIZED",
                            run_id=run_id,
                            symbol=symbol,
                            timeframe=timeframe,
                            gate_mode=gate_mode,
                            rule_engine_mode=cfg.rule_engine_mode,
                            core_id=result["core_id"],
                            core_name_zh=result["core_name_zh"],
                            windows=len(result["windows"]),
                            valid_windows=valid_windows,
                        )
        except Exception as error:
            failures.append(f"{symbol}: {error}")
            log_event("SYMBOL_FAILED", run_id=run_id, symbol=symbol, error=str(error))

    if should_optimize:
        log_event("OPTIMIZATION_DONE", run_id=run_id, results=len(optimization_results))
        if optimization_results:
            optimization_paths = write_optimization_artifacts(
                run_id=run_id,
                universe=[item.symbol for item in universe],
                results=optimization_results,
                artifact_root=cfg.artifact_root,
                raw_layer_root=raw_root,
                run_start_utc=cfg.run_start_utc,
                run_end_utc=cfg.run_end_utc,
                quality_targets={
                    "validation_pass_rate_min": cfg.optimization_target_validation_pass_rate,
                    "all_window_alpha_floor": cfg.optimization_target_all_window_alpha_floor,
                    "deploy_alpha_floor": cfg.optimization_target_deploy_alpha_floor,
                    "deploy_symbol_ratio_min": cfg.optimization_target_deploy_symbol_ratio,
                },
                feature_registry=feature_registry_entries,
            )
            log_event(
                "OPTIMIZATION_ARTIFACT_WRITTEN",
                run_id=run_id,
                summary=optimization_paths.get("summary"),
                root=optimization_paths.get("root"),
            )
            if cfg.validation_enabled:
                validation_paths = write_validation_artifacts(
                    run_id=run_id,
                    results=optimization_results,
                    cfg=cfg,
                    artifact_root=cfg.artifact_root,
                    raw_layer_root=raw_root,
                    run_start_utc=cfg.run_start_utc,
                    run_end_utc=cfg.run_end_utc,
                )
                optimization_paths.update(validation_paths)
                log_event(
                    "VALIDATION_ARTIFACT_WRITTEN",
                    run_id=run_id,
                    validation_report=validation_paths.get("validation_report"),
                    deploy_pool=validation_paths.get("deploy_pool"),
                )

    finished_at = datetime.now(timezone.utc)
    report: RunReport = {
        "run_id": run_id,
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "symbols_processed": symbols_processed,
        "missing_filled_count": missing_filled_count,
        "failures": failures,
        "output_paths": output_paths,
        "optimization_artifacts": optimization_paths,
    }
    log_event(
        "PIPELINE_END",
        run_id=run_id,
        status="ok" if not failures else "partial",
        symbols_processed=symbols_processed,
        failures=len(failures),
        output_files=len(output_paths),
        started_at_utc=report["started_at_utc"],
        finished_at_utc=report["finished_at_utc"],
    )
    return report


def main(run_optimization: bool | None = None, symbol_filter: str | None = None) -> int:
    try:
        run_pipeline_once(run_optimization=run_optimization, symbol_filter=symbol_filter)
        return 0
    except Exception as error:
        log_event("PIPELINE_FATAL", error=str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
