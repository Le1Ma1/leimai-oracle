# LeiMai Oracle Engine

Offline backend module for Binance OHLCV ingestion, simulated parameter optimization, and ClickHouse payload preparation.

## Setup

```bash
pip install -r engine/requirements.txt
```

## Run

```bash
python engine/main.py
```

## Environment variables

- `ENGINE_SYMBOL` (default: `BTC/USDT`)
- `ENGINE_TIMEFRAME` (default: `1h`)
- `ENGINE_LIMIT` (default: `1000`)
- `ENGINE_INDICATOR` (default: `mock-momentum`)
- `ENGINE_LOOKBACK_WINDOW` (default: `90d`)
- `ENGINE_REGIME` (default: `all`)
- `ENGINE_CLICKHOUSE_DRY_RUN` (default: `true`)
- `CLICKHOUSE_HOST` (default: `localhost`)
- `CLICKHOUSE_PORT` (default: `8123`)
- `CLICKHOUSE_USER` (default: `default`)
- `CLICKHOUSE_PASSWORD` (default: empty)
- `CLICKHOUSE_DATABASE` (default: `default`)
- `CLICKHOUSE_SECURE` (default: `false`)
