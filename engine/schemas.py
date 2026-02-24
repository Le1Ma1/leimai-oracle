from __future__ import annotations

from typing import TypedDict


class OptimizationResult(TypedDict):
    indicator: str
    best_params: dict[str, float]
    best_pnl: float
    grid_size: int
    bars: int
    last_close: float
    asof_utc: str


class ClickHousePayload(TypedDict):
    backtest_runs: list[dict[str, object]]
    best_params_snapshot: list[dict[str, object]]
