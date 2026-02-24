from __future__ import annotations

import hashlib
import json
from time import perf_counter
from uuid import uuid4

if __package__:
    from .binance_client import fetch_binance_ohlcv
    from .config import EngineConfig, load_config
    from .logger import log_event
    from .optimizer import run_vectorbt_optimization
    from .schemas import ClickHousePayload, OptimizationResult
else:
    from binance_client import fetch_binance_ohlcv
    from config import EngineConfig, load_config
    from logger import log_event
    from optimizer import run_vectorbt_optimization
    from schemas import ClickHousePayload, OptimizationResult


def _to_clickhouse_symbol(symbol: str) -> str:
    return symbol.replace("/", "").upper()


def prepare_clickhouse_payload(result: OptimizationResult, config: EngineConfig) -> ClickHousePayload:
    symbol = _to_clickhouse_symbol(config.symbol)
    run_id = str(uuid4())
    snapshot_id = str(uuid4())
    params_json = json.dumps(result["best_params"], ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    proof_seed = "|".join(
        [
            symbol,
            config.timeframe,
            config.lookback_window,
            config.regime,
            result["indicator"],
            params_json,
            result["asof_utc"],
        ]
    )
    proof_id = hashlib.sha256(proof_seed.encode("utf-8")).hexdigest()[:24]
    headline_return = float(result["best_pnl"] * 100.0)

    return ClickHousePayload(
        backtest_runs=[
            {
                "run_id": run_id,
                "symbol": symbol,
                "timeframe": config.timeframe,
                "lookback_window": config.lookback_window,
                "regime": config.regime,
                "indicator_set_slug": result["indicator"],
                "params_json": params_json,
                "cagr": result["best_pnl"],
                "max_drawdown": 0.0,
                "turnover_penalty": 0.0,
                "score": result["best_pnl"],
                "fee_model_bps": 0,
                "slippage_bps": 0,
                "funding_bps": 0,
                "asof_ts": result["asof_utc"],
                "config_version": "phase_b_mock_v1",
            }
        ],
        best_params_snapshot=[
            {
                "snapshot_id": snapshot_id,
                "symbol": symbol,
                "timeframe": config.timeframe,
                "lookback_window": config.lookback_window,
                "regime": config.regime,
                "indicator_set_slug": result["indicator"],
                "best_run_id": run_id,
                "headline_return_is": headline_return,
                "headline_return_after_friction": headline_return,
                "max_drawdown": 0.0,
                "trade_count": 0,
                "proof_id": proof_id,
                "asof_ts": result["asof_utc"],
                "rank_bucket": "P0",
            }
        ],
    )


def write_to_clickhouse(payload: ClickHousePayload, config: EngineConfig) -> None:
    import clickhouse_connect

    client = clickhouse_connect.get_client(
        host=config.clickhouse_host,
        port=config.clickhouse_port,
        username=config.clickhouse_user,
        password=config.clickhouse_password,
        database=config.clickhouse_database,
        secure=config.clickhouse_secure,
    )

    backtest_rows = payload["backtest_runs"]
    snapshot_rows = payload["best_params_snapshot"]

    if backtest_rows:
        client.insert(
            "backtest_runs",
            [list(row.values()) for row in backtest_rows],
            column_names=list(backtest_rows[0].keys()),
        )
    if snapshot_rows:
        client.insert(
            "best_params_snapshot",
            [list(row.values()) for row in snapshot_rows],
            column_names=list(snapshot_rows[0].keys()),
        )


def main() -> int:
    started = perf_counter()
    config = load_config()
    log_event(
        "START",
        symbol=config.symbol,
        timeframe=config.timeframe,
        limit=config.limit,
        indicator=config.indicator,
        lookback_window=config.lookback_window,
        regime=config.regime,
    )

    try:
        df = fetch_binance_ohlcv(symbol=config.symbol, timeframe=config.timeframe, limit=config.limit)
        first_ts = df.index[0].isoformat()
        last_ts = df.index[-1].isoformat()
        last_close = float(df["close"].iat[-1])

        log_event(
            "FETCH_OK",
            rows=int(df.shape[0]),
            first_ts_utc=first_ts,
            last_ts_utc=last_ts,
            last_close=last_close,
        )
        log_event(
            "TRANSFORM_OK",
            index_tz=str(df.index.tz),
            null_count=int(df.isna().sum().sum()),
            dtypes=",".join(sorted({str(dtype) for dtype in df.dtypes})),
        )

        result = run_vectorbt_optimization(df=df, indicator=config.indicator)
        log_event(
            "OPTIMIZE_OK",
            grid_size=result["grid_size"],
            bars=result["bars"],
            best_params=result["best_params"],
            best_pnl=result["best_pnl"],
            asof_utc=result["asof_utc"],
        )

        payload = prepare_clickhouse_payload(result=result, config=config)
        run_row = payload["backtest_runs"][0]
        snapshot_row = payload["best_params_snapshot"][0]
        log_event(
            "PAYLOAD_READY",
            backtest_rows=len(payload["backtest_runs"]),
            snapshot_rows=len(payload["best_params_snapshot"]),
            run_id=run_row["run_id"],
            proof_id=snapshot_row["proof_id"],
        )

        if config.clickhouse_dry_run:
            log_event("CLICKHOUSE_SKIPPED", reason="dry_run_enabled")
        else:
            write_to_clickhouse(payload, config)
            log_event("CLICKHOUSE_WRITE_OK", rows_backtest=1, rows_snapshot=1)

        elapsed_ms = int((perf_counter() - started) * 1000)
        log_event("END", status="ok", duration_ms=elapsed_ms)
        return 0
    except Exception as error:
        elapsed_ms = int((perf_counter() - started) * 1000)
        log_event(
            "END",
            status="error",
            duration_ms=elapsed_ms,
            error_type=type(error).__name__,
            error=str(error),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
