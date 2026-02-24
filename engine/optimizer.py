from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

if __package__:
    from .schemas import OptimizationResult
else:
    from schemas import OptimizationResult

WINDOW_GRID: tuple[int, ...] = (5, 8, 13, 21, 34)
THRESHOLD_GRID: tuple[float, ...] = (0.0, 0.0005, 0.001, 0.002, 0.003)


def _rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    kernel = np.full(window, 1.0 / window, dtype=np.float64)
    return np.convolve(values, kernel, mode="valid")


def _iter_param_grid() -> Iterable[tuple[int, float]]:
    for window in WINDOW_GRID:
        for threshold in THRESHOLD_GRID:
            yield window, threshold


def run_vectorbt_optimization(df: pd.DataFrame, indicator: str) -> OptimizationResult:
    close = df["close"].to_numpy(dtype=np.float64, copy=False)
    if close.size < 50:
        raise ValueError("Insufficient bars for optimization.")

    returns = np.diff(close) / close[:-1]
    if returns.size == 0:
        raise ValueError("Insufficient returns for optimization.")

    best_pnl = float("-inf")
    best_params: dict[str, float] = {}
    grid_size = 0

    for window, threshold in _iter_param_grid():
        if returns.size < window:
            continue
        momentum = _rolling_mean(returns, window)
        aligned_returns = returns[window - 1 :]
        signal = momentum > threshold
        pnl = float(np.sum(aligned_returns * signal))
        grid_size += 1
        if pnl > best_pnl:
            best_pnl = pnl
            best_params = {"window": float(window), "threshold": float(threshold)}

    if not best_params:
        raise RuntimeError("Parameter grid produced no candidate result.")

    return OptimizationResult(
        indicator=indicator,
        best_params=best_params,
        best_pnl=best_pnl,
        grid_size=grid_size,
        bars=int(close.size),
        last_close=float(close[-1]),
        asof_utc=df.index[-1].isoformat(),
    )
