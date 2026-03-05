from __future__ import annotations

from itertools import product
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from .config import EngineConfig


CORE_META: dict[str, dict[str, str]] = {
    "lmo_core_momentum_pulse": {"name_zh": "動量脈衝核心", "family": "TREND_FLOW"},
    "lmo_core_mean_reclaim": {"name_zh": "均值回收核心", "family": "OSC_RECLAIM"},
    "lmo_core_breakout_regime": {"name_zh": "突破體制核心", "family": "BREAKOUT_REGIME"},
    "lmo_core_flow_absorption": {"name_zh": "流動吸收核心", "family": "FLOW_IMPACT"},
    "lmo_core_risk_compression": {"name_zh": "風險壓縮核心", "family": "RISK_COMPRESSION"},
    "lmo_core_timing_efficiency": {"name_zh": "時機效率核心", "family": "TIMING_EXECUTION"},
}

RULE_LABEL_ZH: dict[str, str] = {
    "pulse_follow": "脈衝跟隨",
    "drift_hold": "漂移持有",
    "deep_reclaim": "深度回收",
    "snap_back": "快速回彈",
    "regime_break": "體制突破",
    "vol_reaccel": "波動再加速",
    "shock_absorb": "衝擊吸收",
    "flow_reprice": "流動重定價",
    "compression_release": "壓縮釋放",
    "range_reopen": "區間重開",
    "phase_edge": "相位邊際",
    "jump_sync": "跳變同步",
}

def list_supported_cores() -> tuple[str, ...]:
    return tuple(CORE_META.keys())


def get_core_name_zh(core_id: str) -> str:
    if core_id not in CORE_META:
        raise ValueError(f"Unsupported core id: {core_id}")
    return CORE_META[core_id]["name_zh"]


def get_core_family(core_id: str) -> str:
    if core_id not in CORE_META:
        raise ValueError(f"Unsupported core id: {core_id}")
    return CORE_META[core_id]["family"]


def get_core_rule_label_zh(rule_key: str) -> str:
    return RULE_LABEL_ZH.get(rule_key, rule_key)


def _cross_above(series: pd.Series, threshold: float) -> pd.Series:
    return (series.shift(1) <= threshold) & (series > threshold)


def _cross_below(series: pd.Series, threshold: float) -> pd.Series:
    return (series.shift(1) >= threshold) & (series < threshold)


def _feature_col(feature_df: pd.DataFrame, candidates: tuple[str, ...], default: float = 0.0) -> pd.Series:
    for name in candidates:
        if name in feature_df.columns:
            return pd.to_numeric(feature_df[name], errors="coerce").astype("float64").fillna(default)
    return pd.Series(default, index=feature_df.index, dtype="float64")


def _momentum_pulse_signals(
    feature_df: pd.DataFrame,
    close: pd.Series,
    rule_key: str,
    params: dict[str, int | float],
) -> tuple[pd.Series, pd.Series]:
    trend_ret = _feature_col(feature_df, ("trend__ret_log__1m", "ret_1m"))
    trend_4h = _feature_col(feature_df, ("trend__logret__4h", "htf_logret_4h"))
    flow_rel = _feature_col(feature_df, ("flow_liquidity__rel_volume_log__1m", "vol_logret_1m"))
    flow_regime = _feature_col(feature_df, ("flow_liquidity__regime_expand_contract__1m",))
    risk_vol = _feature_col(feature_df, ("risk_volatility__realized_vol_60__1m",))
    breakout_hi = _feature_col(feature_df, ("oscillation__breakout_high_dist__1h", "htf_breakout_high_dist_1h"))
    if rule_key == "pulse_follow":
        entry = (
            _cross_above(trend_ret, float(params["ret_entry"]))
            & (flow_rel > float(params["flow_min"]))
            & (risk_vol < float(params["risk_cap"]))
        )
        exit_ = (
            _cross_below(trend_ret, float(params["ret_exit"]))
            | (flow_rel < float(params["flow_exit"]))
            | (risk_vol > float(params["risk_stop"]))
        )
    elif rule_key == "drift_hold":
        entry = (
            (trend_4h > float(params["trend4h_min"]))
            & _cross_above(breakout_hi, float(params["breakout_entry"]))
            & (flow_regime > float(params["flow_regime_min"]))
        )
        exit_ = (
            _cross_below(breakout_hi, float(params["breakout_exit"]))
            | (trend_4h < float(params["trend4h_exit"]))
            | (flow_regime < float(params["flow_regime_exit"]))
        )
    else:
        raise ValueError(f"Unsupported momentum pulse rule: {rule_key}")
    return entry.fillna(False), exit_.fillna(False)


def _mean_reclaim_signals(
    feature_df: pd.DataFrame,
    close: pd.Series,
    rule_key: str,
    params: dict[str, int | float],
) -> tuple[pd.Series, pd.Series]:
    del close
    tension = _feature_col(feature_df, ("oscillation__revert_tension_60__1m",))
    low_dist = _feature_col(feature_df, ("oscillation__breakout_low_dist__1h", "htf_breakout_low_dist_1h"))
    high_dist = _feature_col(feature_df, ("oscillation__breakout_high_dist__1h", "htf_breakout_high_dist_1h"))
    wick_1h = _feature_col(feature_df, ("risk_volatility__wick_ratio__1h", "htf_wick_ratio_1h"))
    if rule_key == "deep_reclaim":
        entry = (
            (tension < float(params["tension_low"]))
            & (low_dist < float(params["low_dist_min"]))
            & (wick_1h < float(params["wick_cap"]))
        )
        exit_ = (
            (tension > float(params["tension_exit"]))
            | (high_dist > float(params["high_dist_exit"]))
            | (wick_1h > float(params["wick_stop"]))
        )
    elif rule_key == "snap_back":
        entry = (
            _cross_above(tension, float(params["tension_recover"]))
            & (low_dist < float(params["low_dist_gate"]))
            & (wick_1h < float(params["wick_cap"]))
        )
        exit_ = (
            _cross_below(tension, float(params["tension_fail"]))
            | (high_dist > float(params["high_dist_exit"]))
        )
    else:
        raise ValueError(f"Unsupported mean reclaim rule: {rule_key}")
    return entry.fillna(False), exit_.fillna(False)


def _breakout_regime_signals(
    feature_df: pd.DataFrame,
    close: pd.Series,
    rule_key: str,
    params: dict[str, int | float],
) -> tuple[pd.Series, pd.Series]:
    del close
    breakout_4h = _feature_col(feature_df, ("oscillation__breakout_high_dist__4h", "htf_breakout_high_dist_4h"))
    breakout_15m = _feature_col(feature_df, ("oscillation__breakout_high_dist__15m", "htf_breakout_high_dist_15m"))
    flow_regime = _feature_col(feature_df, ("flow_liquidity__regime_expand_contract__1m",))
    shock_density = _feature_col(feature_df, ("flow_liquidity__shock_density__1m",))
    risk_range = _feature_col(feature_df, ("risk_volatility__range_ratio__1m", "htf_range_ratio_1m"))
    if rule_key == "regime_break":
        entry = (
            _cross_above(breakout_4h, float(params["breakout_entry"]))
            & (flow_regime > float(params["flow_regime_min"]))
            & (shock_density < float(params["shock_cap"]))
        )
        exit_ = (
            _cross_below(breakout_4h, float(params["breakout_exit"]))
            | (shock_density > float(params["shock_stop"]))
            | (risk_range > float(params["risk_stop"]))
        )
    elif rule_key == "vol_reaccel":
        entry = (
            _cross_above(breakout_15m, float(params["breakout15_entry"]))
            & (flow_regime > float(params["flow_regime_min"]))
            & (risk_range < float(params["risk_cap"]))
        )
        exit_ = (
            _cross_below(breakout_15m, float(params["breakout15_exit"]))
            | (flow_regime < float(params["flow_regime_exit"]))
            | (risk_range > float(params["risk_stop"]))
        )
    else:
        raise ValueError(f"Unsupported breakout regime rule: {rule_key}")
    return entry.fillna(False), exit_.fillna(False)


def _flow_absorption_signals(
    feature_df: pd.DataFrame,
    close: pd.Series,
    rule_key: str,
    params: dict[str, int | float],
) -> tuple[pd.Series, pd.Series]:
    del close
    shock_density = _feature_col(feature_df, ("flow_liquidity__shock_density__1m",))
    impact_proxy = _feature_col(feature_df, ("flow_liquidity__impact_proxy_log__1m",))
    trend_ret = _feature_col(feature_df, ("trend__ret_log__1m", "ret_1m"))
    rel_volume = _feature_col(feature_df, ("flow_liquidity__rel_volume_log__1m",))
    if rule_key == "shock_absorb":
        entry = (
            (shock_density > float(params["shock_min"]))
            & (impact_proxy < float(params["impact_cap"]))
            & (trend_ret > float(params["ret_min"]))
        )
        exit_ = (
            (shock_density < float(params["shock_exit"]))
            | (impact_proxy > float(params["impact_stop"]))
            | (trend_ret < float(params["ret_exit"]))
        )
    elif rule_key == "flow_reprice":
        entry = (
            _cross_above(rel_volume, float(params["rel_volume_entry"]))
            & (impact_proxy < float(params["impact_cap"]))
            & (trend_ret > float(params["ret_min"]))
        )
        exit_ = (
            _cross_below(rel_volume, float(params["rel_volume_exit"]))
            | (impact_proxy > float(params["impact_stop"]))
        )
    else:
        raise ValueError(f"Unsupported flow absorption rule: {rule_key}")
    return entry.fillna(False), exit_.fillna(False)


def _risk_compression_signals(
    feature_df: pd.DataFrame,
    close: pd.Series,
    rule_key: str,
    params: dict[str, int | float],
) -> tuple[pd.Series, pd.Series]:
    del close
    range_1m = _feature_col(feature_df, ("risk_volatility__range_ratio__1m", "htf_range_ratio_1m"))
    vol_60 = _feature_col(feature_df, ("risk_volatility__realized_vol_60__1m",))
    breakout_15m = _feature_col(feature_df, ("oscillation__breakout_high_dist__15m", "htf_breakout_high_dist_15m"))
    breakout_low_15m = _feature_col(feature_df, ("oscillation__breakout_low_dist__15m", "htf_breakout_low_dist_15m"))
    if rule_key == "compression_release":
        entry = (
            (range_1m < float(params["range_cap"]))
            & (vol_60 < float(params["vol_cap"]))
            & (breakout_15m > float(params["breakout_entry"]))
        )
        exit_ = (
            (range_1m > float(params["range_stop"]))
            | (vol_60 > float(params["vol_stop"]))
            | (breakout_low_15m < float(params["breakout_low_exit"]))
        )
    elif rule_key == "range_reopen":
        entry = (
            _cross_above(breakout_15m, float(params["breakout_cross"]))
            & (range_1m < float(params["range_cap"]))
        )
        exit_ = (
            _cross_below(breakout_15m, float(params["breakout_fail"]))
            | (range_1m > float(params["range_stop"]))
        )
    else:
        raise ValueError(f"Unsupported risk compression rule: {rule_key}")
    return entry.fillna(False), exit_.fillna(False)


def _timing_efficiency_signals(
    feature_df: pd.DataFrame,
    close: pd.Series,
    rule_key: str,
    params: dict[str, int | float],
) -> tuple[pd.Series, pd.Series]:
    del close
    ttc_phase_5m = _feature_col(feature_df, ("timing_execution__ttc_phase__5m",))
    jump_density = _feature_col(feature_df, ("timing_execution__jump_density__1m",))
    trend_ret = _feature_col(feature_df, ("trend__ret_log__1m", "ret_1m"))
    rel_volume = _feature_col(feature_df, ("flow_liquidity__rel_volume_log__1m",))
    if rule_key == "phase_edge":
        entry = (
            (ttc_phase_5m < float(params["phase_entry"]))
            & (trend_ret > float(params["ret_min"]))
            & (rel_volume > float(params["flow_min"]))
        )
        exit_ = (
            (ttc_phase_5m > float(params["phase_exit"]))
            | (trend_ret < float(params["ret_exit"]))
            | (rel_volume < float(params["flow_exit"]))
        )
    elif rule_key == "jump_sync":
        entry = (
            _cross_above(jump_density, float(params["jump_entry"]))
            & (trend_ret > float(params["ret_min"]))
            & (ttc_phase_5m < float(params["phase_cap"]))
        )
        exit_ = (
            _cross_below(jump_density, float(params["jump_exit"]))
            | (trend_ret < float(params["ret_exit"]))
        )
    else:
        raise ValueError(f"Unsupported timing efficiency rule: {rule_key}")
    return entry.fillna(False), exit_.fillna(False)


def build_feature_core_signals(
    core_id: str,
    feature_df: pd.DataFrame,
    close: pd.Series,
    rule_key: str,
    params: dict[str, int | float],
) -> tuple[pd.Series, pd.Series]:
    if core_id == "lmo_core_momentum_pulse":
        return _momentum_pulse_signals(feature_df=feature_df, close=close, rule_key=rule_key, params=params)
    if core_id == "lmo_core_mean_reclaim":
        return _mean_reclaim_signals(feature_df=feature_df, close=close, rule_key=rule_key, params=params)
    if core_id == "lmo_core_breakout_regime":
        return _breakout_regime_signals(feature_df=feature_df, close=close, rule_key=rule_key, params=params)
    if core_id == "lmo_core_flow_absorption":
        return _flow_absorption_signals(feature_df=feature_df, close=close, rule_key=rule_key, params=params)
    if core_id == "lmo_core_risk_compression":
        return _risk_compression_signals(feature_df=feature_df, close=close, rule_key=rule_key, params=params)
    if core_id == "lmo_core_timing_efficiency":
        return _timing_efficiency_signals(feature_df=feature_df, close=close, rule_key=rule_key, params=params)
    raise ValueError(f"Unsupported core id: {core_id}")


def generate_feature_core_candidates(
    core_id: str,
    feature_df: pd.DataFrame,
    close: pd.Series,
    cfg: EngineConfig,
) -> list[dict[str, object]]:
    del cfg
    candidates: list[dict[str, object]] = []

    def add(rule_key: str, params: dict[str, int | float]) -> None:
        entry, exit_ = build_feature_core_signals(
            core_id=core_id,
            feature_df=feature_df,
            close=close,
            rule_key=rule_key,
            params=params,
        )
        candidates.append(
            {
                "core_id": core_id,
                "core_name_zh": get_core_name_zh(core_id),
                "core_family": get_core_family(core_id),
                "signal_source": "feature_core",
                "rule_key": rule_key,
                "rule_label_zh": get_core_rule_label_zh(rule_key),
                "params": params,
                "entry": entry.fillna(False),
                "exit": exit_.fillna(False),
            }
        )

    if core_id == "lmo_core_momentum_pulse":
        for ret_entry, flow_min, risk_cap, ret_exit, flow_exit, risk_stop in product(
            (0.0002, 0.0005),
            (0.0, 0.2),
            (0.004, 0.006),
            (0.0, -0.0002),
            (-0.2, -0.4),
            (0.007, 0.009),
        ):
            add(
                "pulse_follow",
                {
                    "ret_entry": float(ret_entry),
                    "flow_min": float(flow_min),
                    "risk_cap": float(risk_cap),
                    "ret_exit": float(ret_exit),
                    "flow_exit": float(flow_exit),
                    "risk_stop": float(risk_stop),
                },
            )
        for trend4h_min, breakout_entry, flow_regime_min in product((0.0, 0.002), (0.0, 0.002), (0.0, 0.05)):
            add(
                "drift_hold",
                {
                    "trend4h_min": float(trend4h_min),
                    "trend4h_exit": float(trend4h_min - 0.001),
                    "breakout_entry": float(breakout_entry),
                    "breakout_exit": float(-0.001),
                    "flow_regime_min": float(flow_regime_min),
                    "flow_regime_exit": float(-0.03),
                },
            )
        return candidates

    if core_id == "lmo_core_mean_reclaim":
        for tension_low, low_dist_min, wick_cap in product((-1.6, -1.2), (-0.01, -0.005), (0.55, 0.75)):
            add(
                "deep_reclaim",
                {
                    "tension_low": float(tension_low),
                    "tension_exit": float(0.2),
                    "low_dist_min": float(low_dist_min),
                    "high_dist_exit": float(0.015),
                    "wick_cap": float(wick_cap),
                    "wick_stop": float(1.2),
                },
            )
        for tension_recover, low_dist_gate in product((-0.6, -0.3), (-0.015, -0.008)):
            add(
                "snap_back",
                {
                    "tension_recover": float(tension_recover),
                    "tension_fail": float(-0.8),
                    "low_dist_gate": float(low_dist_gate),
                    "high_dist_exit": float(0.02),
                    "wick_cap": float(0.9),
                },
            )
        return candidates

    if core_id == "lmo_core_breakout_regime":
        for breakout_entry, flow_regime_min, shock_cap in product((0.0, 0.003), (0.0, 0.04), (0.3, 0.5)):
            add(
                "regime_break",
                {
                    "breakout_entry": float(breakout_entry),
                    "breakout_exit": float(-0.002),
                    "flow_regime_min": float(flow_regime_min),
                    "shock_cap": float(shock_cap),
                    "shock_stop": float(0.75),
                    "risk_stop": float(0.012),
                },
            )
        for breakout15_entry, flow_regime_min in product((0.0, 0.004), (0.0, 0.05)):
            add(
                "vol_reaccel",
                {
                    "breakout15_entry": float(breakout15_entry),
                    "breakout15_exit": float(-0.002),
                    "flow_regime_min": float(flow_regime_min),
                    "flow_regime_exit": float(-0.02),
                    "risk_cap": float(0.009),
                    "risk_stop": float(0.013),
                },
            )
        return candidates

    if core_id == "lmo_core_flow_absorption":
        for shock_min, impact_cap, ret_min in product((0.25, 0.35), (-11.5, -10.5), (0.0, 0.0002)):
            add(
                "shock_absorb",
                {
                    "shock_min": float(shock_min),
                    "shock_exit": float(0.15),
                    "impact_cap": float(impact_cap),
                    "impact_stop": float(-8.8),
                    "ret_min": float(ret_min),
                    "ret_exit": float(-0.0004),
                },
            )
        for rel_volume_entry, impact_cap in product((0.1, 0.3), (-11.5, -10.5)):
            add(
                "flow_reprice",
                {
                    "rel_volume_entry": float(rel_volume_entry),
                    "rel_volume_exit": float(-0.1),
                    "impact_cap": float(impact_cap),
                    "impact_stop": float(-8.5),
                    "ret_min": float(0.0),
                },
            )
        return candidates

    if core_id == "lmo_core_risk_compression":
        for range_cap, vol_cap, breakout_entry in product((0.0015, 0.0025), (0.0015, 0.0025), (0.0, 0.002)):
            add(
                "compression_release",
                {
                    "range_cap": float(range_cap),
                    "vol_cap": float(vol_cap),
                    "breakout_entry": float(breakout_entry),
                    "range_stop": float(0.006),
                    "vol_stop": float(0.006),
                    "breakout_low_exit": float(-0.01),
                },
            )
        for breakout_cross, range_cap in product((0.0, 0.003), (0.002, 0.0035)):
            add(
                "range_reopen",
                {
                    "breakout_cross": float(breakout_cross),
                    "breakout_fail": float(-0.002),
                    "range_cap": float(range_cap),
                    "range_stop": float(0.006),
                },
            )
        return candidates

    if core_id == "lmo_core_timing_efficiency":
        for phase_entry, ret_min, flow_min in product((0.10, 0.25), (0.0, 0.0002), (-0.05, 0.1)):
            add(
                "phase_edge",
                {
                    "phase_entry": float(phase_entry),
                    "phase_exit": float(0.85),
                    "ret_min": float(ret_min),
                    "ret_exit": float(-0.0003),
                    "flow_min": float(flow_min),
                    "flow_exit": float(-0.2),
                },
            )
        for jump_entry, phase_cap in product((0.05, 0.12), (0.4, 0.7)):
            add(
                "jump_sync",
                {
                    "jump_entry": float(jump_entry),
                    "jump_exit": float(0.03),
                    "ret_min": float(0.0),
                    "ret_exit": float(-0.0003),
                    "phase_cap": float(phase_cap),
                },
            )
        return candidates

    raise ValueError(f"Unsupported core id: {core_id}")

