from __future__ import annotations

from itertools import product
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from .rsi_strategies import build_long_signals, compute_rsi

if TYPE_CHECKING:
    from .config import EngineConfig


INDICATOR_META: dict[str, dict[str, str]] = {
    "rsi": {"name_zh": "相對強弱指標", "family": "OSC"},
    "macd": {"name_zh": "趨勢動能指標", "family": "TREND"},
    "bollinger": {"name_zh": "布林通道", "family": "OSC"},
    "ema_cross": {"name_zh": "指數均線交叉", "family": "TREND"},
    "atr_regime": {"name_zh": "波動趨勢濾網", "family": "RISK"},
    "stoch_rsi": {"name_zh": "隨機相對強弱", "family": "OSC"},
    "adx": {"name_zh": "趨勢強度指標", "family": "TREND"},
    "cci": {"name_zh": "商品通道指標", "family": "OSC"},
}

RULE_LABEL_ZH: dict[str, str] = {
    "mean_revert": "回歸均值",
    "breakout": "突破追蹤",
    "centerline": "中線轉向",
    "momentum_follow": "動能追蹤",
    "zero_line_follow": "零軸追蹤",
    "trend_cross": "快慢均線交叉",
    "trend_volatility": "趨勢波動濾網",
    "stoch_mean_revert": "隨機回歸均值",
    "stoch_breakout": "隨機突破追蹤",
    "adx_trend": "趨勢強度追蹤",
    "cci_mean_revert": "通道回歸均值",
    "cci_breakout": "通道突破追蹤",
    "bb_breakout": "通道上軌突破",
    "bb_mean_revert": "通道下軌回歸",
}


def list_supported_indicators() -> tuple[str, ...]:
    return tuple(INDICATOR_META.keys())


def get_indicator_name_zh(indicator_id: str) -> str:
    if indicator_id not in INDICATOR_META:
        raise ValueError(f"Unsupported indicator id: {indicator_id}")
    return INDICATOR_META[indicator_id]["name_zh"]


def get_indicator_family(indicator_id: str) -> str:
    if indicator_id not in INDICATOR_META:
        raise ValueError(f"Unsupported indicator id: {indicator_id}")
    return INDICATOR_META[indicator_id]["family"]


def get_rule_label_zh(rule_key: str) -> str:
    return RULE_LABEL_ZH.get(rule_key, rule_key)


def _cross_above(series: pd.Series, threshold: float) -> pd.Series:
    return (series.shift(1) <= threshold) & (series > threshold)


def _cross_below(series: pd.Series, threshold: float) -> pd.Series:
    return (series.shift(1) >= threshold) & (series < threshold)


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / float(window), adjust=False, min_periods=window).mean().fillna(0.0)


def _compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0.0), up_move, 0.0),
        index=close.index,
        dtype="float64",
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0.0), down_move, 0.0),
        index=close.index,
        dtype="float64",
    )

    atr = _compute_atr(high=high, low=low, close=close, window=window).replace(0.0, np.nan)
    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / float(window), adjust=False, min_periods=window).mean() / atr
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / float(window), adjust=False, min_periods=window).mean() / atr
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx = dx.ewm(alpha=1.0 / float(window), adjust=False, min_periods=window).mean()
    return plus_di.fillna(0.0), minus_di.fillna(0.0), adx.fillna(0.0)


def _signal_rsi(close: pd.Series, rule_key: str, params: dict[str, int | float]) -> tuple[pd.Series, pd.Series]:
    rsi_window = int(params["rsi_window"])
    lower = int(params["lower"])
    upper = int(params["upper"])
    rsi = compute_rsi(close=close, window=rsi_window)
    return build_long_signals(strategy=rule_key, rsi=rsi, lower=lower, upper=upper)


def _signal_macd(close: pd.Series, rule_key: str, params: dict[str, int | float]) -> tuple[pd.Series, pd.Series]:
    fast = int(params["fast_window"])
    slow = int(params["slow_window"])
    signal_window = int(params["signal_window"])

    ema_fast = _ema(close, span=fast)
    ema_slow = _ema(close, span=slow)
    macd = ema_fast - ema_slow
    signal = _ema(macd, span=signal_window)
    hist = macd - signal

    if rule_key == "momentum_follow":
        entry = _cross_above(hist, 0.0) & (macd > 0.0)
        exit_ = _cross_below(hist, 0.0) | (macd < 0.0)
    elif rule_key == "zero_line_follow":
        entry = _cross_above(macd, 0.0) & (signal > 0.0)
        exit_ = _cross_below(macd, 0.0)
    else:
        raise ValueError(f"Unsupported MACD rule: {rule_key}")
    return entry.fillna(False), exit_.fillna(False)


def _signal_ema_cross(close: pd.Series, params: dict[str, int | float]) -> tuple[pd.Series, pd.Series]:
    fast = int(params["fast_window"])
    slow = int(params["slow_window"])
    ema_fast = _ema(close, span=fast)
    ema_slow = _ema(close, span=slow)
    diff = ema_fast - ema_slow
    entry = _cross_above(diff, 0.0)
    exit_ = _cross_below(diff, 0.0)
    return entry.fillna(False), exit_.fillna(False)


def _signal_bollinger(close: pd.Series, rule_key: str, params: dict[str, int | float]) -> tuple[pd.Series, pd.Series]:
    window = int(params["window"])
    std_mult = float(params["std_mult"])
    mid = close.rolling(window=window, min_periods=window).mean()
    std = close.rolling(window=window, min_periods=window).std(ddof=0)
    upper = mid + std_mult * std
    lower = mid - std_mult * std

    if rule_key == "bb_breakout":
        entry = _cross_above(close - upper, 0.0)
        exit_ = _cross_below(close - mid, 0.0)
    elif rule_key == "bb_mean_revert":
        entry = _cross_below(close - lower, 0.0)
        exit_ = _cross_above(close - mid, 0.0)
    else:
        raise ValueError(f"Unsupported Bollinger rule: {rule_key}")
    return entry.fillna(False), exit_.fillna(False)


def _signal_stoch_rsi(close: pd.Series, rule_key: str, params: dict[str, int | float]) -> tuple[pd.Series, pd.Series]:
    rsi_window = int(params["rsi_window"])
    stoch_window = int(params["stoch_window"])
    lower = float(params["lower"])
    upper = float(params["upper"])

    rsi = compute_rsi(close=close, window=rsi_window)
    rolling_min = rsi.rolling(window=stoch_window, min_periods=stoch_window).min()
    rolling_max = rsi.rolling(window=stoch_window, min_periods=stoch_window).max()
    stoch = 100.0 * (rsi - rolling_min) / (rolling_max - rolling_min).replace(0.0, np.nan)
    stoch = stoch.fillna(50.0)

    if rule_key == "stoch_mean_revert":
        entry = _cross_below(stoch, lower)
        exit_ = _cross_above(stoch, upper)
    elif rule_key == "stoch_breakout":
        entry = _cross_above(stoch, upper)
        exit_ = _cross_below(stoch, lower)
    else:
        raise ValueError(f"Unsupported Stoch RSI rule: {rule_key}")
    return entry.fillna(False), exit_.fillna(False)


def _signal_adx(high: pd.Series, low: pd.Series, close: pd.Series, params: dict[str, int | float]) -> tuple[pd.Series, pd.Series]:
    window = int(params["window"])
    threshold = float(params["threshold"])
    plus_di, minus_di, adx = _compute_adx(high=high, low=low, close=close, window=window)
    entry = (plus_di > minus_di) & (adx > threshold) & _cross_above(plus_di - minus_di, 0.0)
    exit_ = (minus_di > plus_di) | (adx < threshold * 0.8)
    return entry.fillna(False), exit_.fillna(False)


def _signal_cci(high: pd.Series, low: pd.Series, close: pd.Series, rule_key: str, params: dict[str, int | float]) -> tuple[pd.Series, pd.Series]:
    window = int(params["window"])
    lower = float(params["lower"])
    upper = float(params["upper"])
    tp = (high + low + close) / 3.0
    sma = tp.rolling(window=window, min_periods=window).mean()
    mean_dev = (tp - sma).abs().rolling(window=window, min_periods=window).mean()
    cci = (tp - sma) / (0.015 * mean_dev.replace(0.0, np.nan))
    cci = cci.fillna(0.0)

    if rule_key == "cci_mean_revert":
        entry = _cross_below(cci, lower)
        exit_ = _cross_above(cci, upper)
    elif rule_key == "cci_breakout":
        entry = _cross_above(cci, upper)
        exit_ = _cross_below(cci, lower)
    else:
        raise ValueError(f"Unsupported CCI rule: {rule_key}")
    return entry.fillna(False), exit_.fillna(False)


def _signal_atr_regime(high: pd.Series, low: pd.Series, close: pd.Series, params: dict[str, int | float]) -> tuple[pd.Series, pd.Series]:
    atr_window = int(params["atr_window"])
    ema_window = int(params["ema_window"])
    atr_floor = float(params["atr_floor"])
    atr = _compute_atr(high=high, low=low, close=close, window=atr_window)
    atr_ratio = atr / close.replace(0.0, np.nan)
    ema_trend = _ema(close, span=ema_window)
    entry = _cross_above(close - ema_trend, 0.0) & (atr_ratio > atr_floor)
    exit_ = _cross_below(close - ema_trend, 0.0) | (atr_ratio < atr_floor * 0.8)
    return entry.fillna(False), exit_.fillna(False)


def build_indicator_signals(
    indicator_id: str,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    rule_key: str,
    params: dict[str, int | float],
) -> tuple[pd.Series, pd.Series]:
    if indicator_id == "rsi":
        return _signal_rsi(close=close, rule_key=rule_key, params=params)
    if indicator_id == "macd":
        return _signal_macd(close=close, rule_key=rule_key, params=params)
    if indicator_id == "ema_cross":
        return _signal_ema_cross(close=close, params=params)
    if indicator_id == "bollinger":
        return _signal_bollinger(close=close, rule_key=rule_key, params=params)
    if indicator_id == "stoch_rsi":
        return _signal_stoch_rsi(close=close, rule_key=rule_key, params=params)
    if indicator_id == "adx":
        return _signal_adx(high=high, low=low, close=close, params=params)
    if indicator_id == "cci":
        return _signal_cci(high=high, low=low, close=close, rule_key=rule_key, params=params)
    if indicator_id == "atr_regime":
        return _signal_atr_regime(high=high, low=low, close=close, params=params)
    raise ValueError(f"Unsupported indicator id: {indicator_id}")


def generate_indicator_candidates(
    indicator_id: str,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    cfg: EngineConfig,
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []

    if indicator_id == "rsi":
        rsi_cache: dict[int, pd.Series] = {
            int(window): compute_rsi(close=close, window=int(window)) for window in cfg.rsi_windows
        }
        for strategy in cfg.rsi_strategies:
            for rsi_window in cfg.rsi_windows:
                rsi = rsi_cache[int(rsi_window)]
                for lower in cfg.rsi_lower_bounds:
                    for upper in cfg.rsi_upper_bounds:
                        if int(lower) >= int(upper):
                            continue
                        params = {"rsi_window": int(rsi_window), "lower": int(lower), "upper": int(upper)}
                        entry, exit_ = build_long_signals(
                            strategy=str(strategy),
                            rsi=rsi,
                            lower=int(lower),
                            upper=int(upper),
                        )
                        candidates.append(
                            {
                                "rule_key": str(strategy),
                                "rule_label_zh": get_rule_label_zh(str(strategy)),
                                "params": params,
                                "entry": entry.fillna(False),
                                "exit": exit_.fillna(False),
                            }
                        )
        return candidates

    if indicator_id == "macd":
        for fast, slow, signal_window in product((8, 12, 16), (21, 26, 34), (7, 9)):
            if fast >= slow:
                continue
            params = {"fast_window": int(fast), "slow_window": int(slow), "signal_window": int(signal_window)}
            ema_fast = _ema(close, span=int(fast))
            ema_slow = _ema(close, span=int(slow))
            macd = ema_fast - ema_slow
            signal = _ema(macd, span=int(signal_window))
            hist = macd - signal
            for rule_key in ("momentum_follow", "zero_line_follow"):
                if rule_key == "momentum_follow":
                    entry = (_cross_above(hist, 0.0) & (macd > 0.0)).fillna(False)
                    exit_ = (_cross_below(hist, 0.0) | (macd < 0.0)).fillna(False)
                else:
                    entry = (_cross_above(macd, 0.0) & (signal > 0.0)).fillna(False)
                    exit_ = _cross_below(macd, 0.0).fillna(False)
                candidates.append(
                    {
                        "rule_key": rule_key,
                        "rule_label_zh": get_rule_label_zh(rule_key),
                        "params": dict(params),
                        "entry": entry,
                        "exit": exit_,
                    }
                )
        return candidates

    if indicator_id == "ema_cross":
        for fast, slow in product((8, 13, 21, 34), (55, 89, 144)):
            if fast >= slow:
                continue
            params = {"fast_window": int(fast), "slow_window": int(slow)}
            ema_fast = _ema(close, span=int(fast))
            ema_slow = _ema(close, span=int(slow))
            diff = ema_fast - ema_slow
            entry = _cross_above(diff, 0.0).fillna(False)
            exit_ = _cross_below(diff, 0.0).fillna(False)
            candidates.append(
                {
                    "rule_key": "trend_cross",
                    "rule_label_zh": get_rule_label_zh("trend_cross"),
                    "params": params,
                    "entry": entry,
                    "exit": exit_,
                }
            )
        return candidates

    if indicator_id == "bollinger":
        for window, std_mult in product((14, 20, 30), (1.8, 2.0, 2.2)):
            params = {"window": int(window), "std_mult": float(std_mult)}
            mid = close.rolling(window=int(window), min_periods=int(window)).mean()
            std = close.rolling(window=int(window), min_periods=int(window)).std(ddof=0)
            upper = mid + float(std_mult) * std
            lower = mid - float(std_mult) * std
            for rule_key in ("bb_breakout", "bb_mean_revert"):
                if rule_key == "bb_breakout":
                    entry = _cross_above(close - upper, 0.0).fillna(False)
                    exit_ = _cross_below(close - mid, 0.0).fillna(False)
                else:
                    entry = _cross_below(close - lower, 0.0).fillna(False)
                    exit_ = _cross_above(close - mid, 0.0).fillna(False)
                candidates.append(
                    {
                        "rule_key": rule_key,
                        "rule_label_zh": get_rule_label_zh(rule_key),
                        "params": dict(params),
                        "entry": entry,
                        "exit": exit_,
                    }
                )
        return candidates

    if indicator_id == "stoch_rsi":
        for rsi_window, stoch_window, lower, upper in product((14, 21), (14, 21), (20, 30), (70, 80)):
            if lower >= upper:
                continue
            params = {
                "rsi_window": int(rsi_window),
                "stoch_window": int(stoch_window),
                "lower": int(lower),
                "upper": int(upper),
            }
            rsi = compute_rsi(close=close, window=int(rsi_window))
            rolling_min = rsi.rolling(window=int(stoch_window), min_periods=int(stoch_window)).min()
            rolling_max = rsi.rolling(window=int(stoch_window), min_periods=int(stoch_window)).max()
            stoch = 100.0 * (rsi - rolling_min) / (rolling_max - rolling_min).replace(0.0, np.nan)
            stoch = stoch.fillna(50.0)
            for rule_key in ("stoch_mean_revert", "stoch_breakout"):
                if rule_key == "stoch_mean_revert":
                    entry = _cross_below(stoch, float(lower)).fillna(False)
                    exit_ = _cross_above(stoch, float(upper)).fillna(False)
                else:
                    entry = _cross_above(stoch, float(upper)).fillna(False)
                    exit_ = _cross_below(stoch, float(lower)).fillna(False)
                candidates.append(
                    {
                        "rule_key": rule_key,
                        "rule_label_zh": get_rule_label_zh(rule_key),
                        "params": dict(params),
                        "entry": entry,
                        "exit": exit_,
                    }
                )
        return candidates

    if indicator_id == "adx":
        for window in (14, 21, 28):
            plus_di, minus_di, adx = _compute_adx(high=high, low=low, close=close, window=int(window))
            for threshold in (18, 22, 28):
                params = {"window": int(window), "threshold": float(threshold)}
                entry = (
                    (plus_di > minus_di) & (adx > float(threshold)) & _cross_above(plus_di - minus_di, 0.0)
                ).fillna(False)
                exit_ = ((minus_di > plus_di) | (adx < float(threshold) * 0.8)).fillna(False)
                candidates.append(
                    {
                        "rule_key": "adx_trend",
                        "rule_label_zh": get_rule_label_zh("adx_trend"),
                        "params": params,
                        "entry": entry,
                        "exit": exit_,
                    }
                )
        return candidates

    if indicator_id == "cci":
        for window in (20, 30):
            tp = (high + low + close) / 3.0
            sma = tp.rolling(window=int(window), min_periods=int(window)).mean()
            mean_dev = (tp - sma).abs().rolling(window=int(window), min_periods=int(window)).mean()
            cci = ((tp - sma) / (0.015 * mean_dev.replace(0.0, np.nan))).fillna(0.0)
            for lower, upper in product((-200, -150, -100), (100, 150, 200)):
                if lower >= upper:
                    continue
                params = {"window": int(window), "lower": int(lower), "upper": int(upper)}
                for rule_key in ("cci_mean_revert", "cci_breakout"):
                    if rule_key == "cci_mean_revert":
                        entry = _cross_below(cci, float(lower)).fillna(False)
                        exit_ = _cross_above(cci, float(upper)).fillna(False)
                    else:
                        entry = _cross_above(cci, float(upper)).fillna(False)
                        exit_ = _cross_below(cci, float(lower)).fillna(False)
                    candidates.append(
                        {
                            "rule_key": rule_key,
                            "rule_label_zh": get_rule_label_zh(rule_key),
                            "params": dict(params),
                            "entry": entry,
                            "exit": exit_,
                        }
                    )
        return candidates

    if indicator_id == "atr_regime":
        for atr_window, ema_window, atr_floor in product((14, 21), (50, 100, 150), (0.003, 0.006, 0.010)):
            params = {
                "atr_window": int(atr_window),
                "ema_window": int(ema_window),
                "atr_floor": float(atr_floor),
            }
            atr = _compute_atr(high=high, low=low, close=close, window=int(atr_window))
            atr_ratio = atr / close.replace(0.0, np.nan)
            ema_trend = _ema(close, span=int(ema_window))
            entry = (_cross_above(close - ema_trend, 0.0) & (atr_ratio > float(atr_floor))).fillna(False)
            exit_ = (_cross_below(close - ema_trend, 0.0) | (atr_ratio < float(atr_floor) * 0.8)).fillna(False)
            candidates.append(
                {
                    "rule_key": "trend_volatility",
                    "rule_label_zh": get_rule_label_zh("trend_volatility"),
                    "params": params,
                    "entry": entry,
                    "exit": exit_,
                }
            )
        return candidates

    raise ValueError(f"Unsupported indicator id: {indicator_id}")
