from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class EngineConfig:
    symbol: str
    timeframe: str
    limit: int
    indicator: str
    lookback_window: str
    regime: str
    clickhouse_dry_run: bool
    clickhouse_host: str
    clickhouse_port: int
    clickhouse_user: str
    clickhouse_password: str
    clickhouse_database: str
    clickhouse_secure: bool


def _parse_positive_int(raw: str | None, default: int, key_name: str) -> int:
    if raw is None:
        return default
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{key_name} must be positive.")
    return value


def _parse_bool(raw: str | None, default: bool, key_name: str) -> bool:
    if raw is None:
        return default
    token = raw.strip().lower()
    if token in {"1", "true", "yes", "y", "on"}:
        return True
    if token in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"{key_name} must be a boolean value.")


def _normalize_symbol(symbol: str) -> str:
    token = symbol.strip().upper().replace("-", "/")
    if "/" not in token and token.endswith("USDT"):
        return f"{token[:-4]}/USDT"
    if "/" not in token:
        return f"{token}/USDT"
    return token


def load_config() -> EngineConfig:
    load_dotenv()
    return EngineConfig(
        symbol=_normalize_symbol(os.getenv("ENGINE_SYMBOL", "BTC/USDT")),
        timeframe=os.getenv("ENGINE_TIMEFRAME", "1h"),
        limit=_parse_positive_int(os.getenv("ENGINE_LIMIT"), 1000, "ENGINE_LIMIT"),
        indicator=os.getenv("ENGINE_INDICATOR", "mock-momentum"),
        lookback_window=os.getenv("ENGINE_LOOKBACK_WINDOW", "90d"),
        regime=os.getenv("ENGINE_REGIME", "all"),
        clickhouse_dry_run=_parse_bool(os.getenv("ENGINE_CLICKHOUSE_DRY_RUN"), True, "ENGINE_CLICKHOUSE_DRY_RUN"),
        clickhouse_host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        clickhouse_port=_parse_positive_int(os.getenv("CLICKHOUSE_PORT"), 8123, "CLICKHOUSE_PORT"),
        clickhouse_user=os.getenv("CLICKHOUSE_USER", "default"),
        clickhouse_password=os.getenv("CLICKHOUSE_PASSWORD", ""),
        clickhouse_database=os.getenv("CLICKHOUSE_DATABASE", "default"),
        clickhouse_secure=_parse_bool(os.getenv("CLICKHOUSE_SECURE"), False, "CLICKHOUSE_SECURE"),
    )
