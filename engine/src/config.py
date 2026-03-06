from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv


@dataclass(frozen=True)
class EngineConfig:
    data_root: Path
    artifact_root: Path
    run_start_utc: datetime
    run_end_utc: datetime
    top_n: int
    quote_asset: str
    universe_symbols: tuple[str, ...]
    raw_timeframe: str
    aggregate_timeframes: tuple[str, ...]
    archive_base_url: str
    binance_api_base_url: str
    universe_source: str
    coingecko_api_base_url: str
    universe_strict_stable_filter: bool
    schedule_tier1_hours: int
    schedule_tier2_hours: int
    schedule_tier3_days: int
    optimization_enabled: bool
    optimization_timeframes: tuple[str, ...]
    feature_timeframes: tuple[str, ...]
    optimization_windows: tuple[str, ...]
    optimization_gate_modes: tuple[str, ...]
    leaderboard_modes: tuple[str, ...]
    optimization_long_only: bool
    objective_mode: str
    optimization_schedule_hours: int
    optimization_max_rounds: int
    optimization_target_validation_pass_rate: float
    optimization_target_all_window_alpha_floor: float
    optimization_target_deploy_alpha_floor: float
    optimization_target_deploy_symbol_ratio: float
    trade_floor: int
    window_trade_floor_overrides: tuple[tuple[str, int], ...]
    baseline_primary_timeframe: str
    baseline_confirm_timeframes: tuple[str, ...]
    baseline_low_dof_mode: bool
    baseline_feature_cap: int
    baseline_feature_allowlist: tuple[str, ...]
    rl_enabled: bool
    rl_unlock_requires_baseline: bool
    rsi_windows: tuple[int, ...]
    rsi_strategies: tuple[str, ...]
    rsi_lower_bounds: tuple[int, ...]
    rsi_upper_bounds: tuple[int, ...]
    friction_bps: int
    gate_oracle_quantile: float
    gate_confidence_quantile: float
    credibility_reject_threshold: float
    credible_candidate_max_penalty: float
    rule_engine_mode: str
    single_indicators: tuple[str, ...]
    feature_cores: tuple[str, ...]
    validation_enabled: bool
    validation_strictness: str
    validation_walk_forward_splits: int
    validation_cv_folds: int
    validation_purge_bars: int
    validation_stress_friction_bps: tuple[int, ...]
    validation_sample_step: int
    meta_label_enabled: bool
    meta_label_model: str
    meta_label_objective: str
    meta_label_penalty: str
    meta_label_c: float
    meta_label_max_iter: int
    meta_label_class_weight: str
    meta_label_tp_mult: float
    meta_label_sl_mult: float
    meta_label_vertical_horizon_bars: int
    meta_label_vol_window: int
    meta_label_min_events: int
    meta_label_threshold_min: float
    meta_label_threshold_max: float
    meta_label_threshold_step: float
    meta_label_precision_floor: float
    meta_label_threshold_objective: str
    meta_label_prob_threshold_fallback: float
    meta_label_feature_cap: int
    meta_label_feature_allowlist: tuple[str, ...]
    meta_label_cpcv_splits: int
    meta_label_cpcv_test_groups: int
    meta_label_cpcv_purge_bars: int
    meta_label_cpcv_embargo_bars: int
    meta_label_cpcv_max_combinations: int
    max_deploy_rules_per_symbol: int


def _parse_positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{name} must be positive.")
    return value


def _parse_non_negative_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = int(raw)
    if value < 0:
        raise ValueError(f"{name} must be non-negative.")
    return value


def _parse_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    return float(raw)


def _parse_ratio(name: str, default: float) -> float:
    value = _parse_float(name, default)
    if value < 0.0 or value > 1.0:
        raise ValueError(f"{name} must be between 0 and 1.")
    return value


def _parse_datetime_utc(name: str, default_value: datetime) -> datetime:
    raw = os.getenv(name)
    if raw is None:
        return default_value
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"{name} must include timezone.")
    return dt.astimezone(timezone.utc)


def _parse_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean string.")


def _parse_csv_str(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    values = tuple(token.strip() for token in raw.split(",") if token.strip())
    if not values:
        raise ValueError(f"{name} must not be empty.")
    return values


def _parse_csv_int(name: str, default: tuple[int, ...], positive_only: bool = True) -> tuple[int, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    out: list[int] = []
    for token in raw.split(","):
        value = int(token.strip())
        if positive_only and value <= 0:
            raise ValueError(f"{name} values must be positive.")
        out.append(value)
    if not out:
        raise ValueError(f"{name} must not be empty.")
    return tuple(out)


def _validate_subset(values: Iterable[str], allowed: set[str], name: str) -> None:
    for value in values:
        if value not in allowed:
            raise ValueError(f"{name} contains unsupported value: {value}")


def _validate_rsi_bounds(lower_bounds: tuple[int, ...], upper_bounds: tuple[int, ...]) -> None:
    for lower in lower_bounds:
        for upper in upper_bounds:
            if lower >= upper:
                raise ValueError("All RSI lower bounds must be strictly lower than upper bounds.")


def _validate_subset_exact(values: tuple[str, ...], allowed: set[str], name: str) -> None:
    for value in values:
        if value not in allowed:
            raise ValueError(f"{name} contains unsupported value: {value}")


def _parse_optional_csv_symbols(name: str) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return ()
    values = tuple(token.strip().upper() for token in raw.split(",") if token.strip())
    if not values:
        return ()
    for symbol in values:
        if len(symbol) < 6:
            raise ValueError(f"{name} contains invalid symbol: {symbol}")
    return values


def _parse_window_trade_floor_overrides(
    name: str,
    default: tuple[tuple[str, int], ...],
    allowed_windows: set[str],
) -> tuple[tuple[str, int], ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    parsed: dict[str, int] = {}
    for token in raw.split(","):
        chunk = token.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise ValueError(f"{name} must be comma-separated window:floor pairs.")
        window, floor_text = chunk.split(":", 1)
        window_key = window.strip().lower()
        if window_key not in allowed_windows:
            raise ValueError(f"{name} has unsupported window: {window_key}")
        floor = int(floor_text.strip())
        if floor <= 0:
            raise ValueError(f"{name} floors must be positive.")
        parsed[window_key] = floor
    if not parsed:
        raise ValueError(f"{name} must not be empty when provided.")
    ordered = sorted(parsed.items(), key=lambda item: item[0])
    return tuple((key, int(value)) for key, value in ordered)


def load_config() -> EngineConfig:
    load_dotenv()
    now_utc = datetime.now(timezone.utc)
    project_root = Path(__file__).resolve().parents[2]
    data_root = Path(os.getenv("ENGINE_DATA_ROOT", str(project_root / "engine" / "data")))
    artifact_root = Path(os.getenv("ENGINE_ARTIFACT_ROOT", str(project_root / "engine" / "artifacts")))

    allowed_timeframes = {"1m", "5m", "15m", "1h", "4h", "1d", "1w"}
    allowed_windows = {"all", "30d", "90d", "360d"}
    allowed_gate_modes = {"gated", "ungated"}
    allowed_leaderboard_modes = {"score", "return"}
    allowed_universe_source = {"binance_volume", "coingecko_market_cap"}
    allowed_objective_mode = {"none", "beat_spot_each_window"}
    allowed_rsi_strategies = {"mean_revert", "breakout", "centerline"}
    allowed_single_indicators = {
        "rsi",
        "macd",
        "bollinger",
        "ema_cross",
        "atr_regime",
        "stoch_rsi",
        "adx",
        "cci",
    }
    allowed_feature_cores = {
        "lmo_core_momentum_pulse",
        "lmo_core_mean_reclaim",
        "lmo_core_breakout_regime",
        "lmo_core_flow_absorption",
        "lmo_core_risk_compression",
        "lmo_core_timing_efficiency",
    }
    allowed_rule_engine_modes = {"indicator", "feature_native"}
    allowed_validation_strictness = {"institutional", "balanced", "fast", "recovery"}
    allowed_meta_label_model = {"logreg"}
    allowed_meta_label_objective = {"classification_binary"}
    allowed_meta_label_penalty = {"l1", "l2"}
    allowed_meta_label_class_weight = {"balanced", "none"}
    allowed_meta_label_threshold_objective = {"f1", "f05"}

    aggregate_timeframes = _parse_csv_str("ENGINE_AGGREGATE_TIMEFRAMES", ("1m", "5m", "15m", "1h", "4h", "1d", "1w"))
    optimization_timeframes = _parse_csv_str("ENGINE_OPTIMIZATION_TIMEFRAMES", ("15m",))
    feature_timeframes = _parse_csv_str("ENGINE_FEATURE_TIMEFRAMES", ("5m", "15m", "1h", "4h", "1d", "1w"))
    optimization_windows = _parse_csv_str("ENGINE_OPTIMIZATION_WINDOWS", ("all", "30d", "90d", "360d"))
    optimization_gate_modes = _parse_csv_str("ENGINE_OPTIMIZATION_GATE_MODES", ("gated", "ungated"))
    leaderboard_modes = _parse_csv_str("ENGINE_LEADERBOARD_MODES", ("score", "return"))
    rsi_windows = _parse_csv_int("ENGINE_RSI_WINDOWS", (7, 10, 14, 18, 21, 28, 35, 42, 56))
    rsi_strategies = _parse_csv_str("ENGINE_RSI_STRATEGIES", ("mean_revert", "breakout", "centerline"))
    rsi_lower_bounds = _parse_csv_int("ENGINE_RSI_LOWER_BOUNDS", (10, 15, 20, 25, 30, 35, 40, 45), positive_only=False)
    rsi_upper_bounds = _parse_csv_int("ENGINE_RSI_UPPER_BOUNDS", (55, 60, 65, 70, 75, 80, 85, 90), positive_only=False)
    single_indicators = _parse_csv_str(
        "ENGINE_SINGLE_INDICATORS",
        ("rsi", "macd", "bollinger", "ema_cross", "atr_regime", "stoch_rsi", "adx", "cci"),
    )
    feature_cores = _parse_csv_str(
        "ENGINE_FEATURE_CORES",
        (
            "lmo_core_momentum_pulse",
            "lmo_core_mean_reclaim",
            "lmo_core_breakout_regime",
            "lmo_core_flow_absorption",
            "lmo_core_risk_compression",
            "lmo_core_timing_efficiency",
        ),
    )
    universe_symbols = _parse_optional_csv_symbols("ENGINE_UNIVERSE_SYMBOLS")
    validation_stress_friction_bps = _parse_csv_int("ENGINE_VALIDATION_STRESS_FRICTION_BPS", (10, 20, 30))
    window_trade_floor_overrides = _parse_window_trade_floor_overrides(
        "ENGINE_WINDOW_TRADE_FLOORS",
        (("all", 40), ("360d", 20), ("90d", 10), ("30d", 6)),
        allowed_windows=allowed_windows,
    )

    _validate_subset(aggregate_timeframes, allowed_timeframes, "ENGINE_AGGREGATE_TIMEFRAMES")
    _validate_subset(optimization_timeframes, allowed_timeframes, "ENGINE_OPTIMIZATION_TIMEFRAMES")
    _validate_subset(feature_timeframes, allowed_timeframes, "ENGINE_FEATURE_TIMEFRAMES")
    _validate_subset(optimization_windows, allowed_windows, "ENGINE_OPTIMIZATION_WINDOWS")
    _validate_subset_exact(optimization_gate_modes, allowed_gate_modes, "ENGINE_OPTIMIZATION_GATE_MODES")
    _validate_subset_exact(leaderboard_modes, allowed_leaderboard_modes, "ENGINE_LEADERBOARD_MODES")
    _validate_subset_exact(rsi_strategies, allowed_rsi_strategies, "ENGINE_RSI_STRATEGIES")
    _validate_subset_exact(single_indicators, allowed_single_indicators, "ENGINE_SINGLE_INDICATORS")
    _validate_subset_exact(feature_cores, allowed_feature_cores, "ENGINE_FEATURE_CORES")
    _validate_rsi_bounds(rsi_lower_bounds, rsi_upper_bounds)

    baseline_primary_timeframe = os.getenv("ENGINE_BASELINE_PRIMARY_TIMEFRAME", "15m").strip().lower()
    if baseline_primary_timeframe not in allowed_timeframes:
        raise ValueError(
            f"ENGINE_BASELINE_PRIMARY_TIMEFRAME contains unsupported value: {baseline_primary_timeframe}"
        )

    baseline_confirm_timeframes = _parse_csv_str("ENGINE_BASELINE_CONFIRM_TIMEFRAMES", ("5m",))
    _validate_subset(baseline_confirm_timeframes, allowed_timeframes, "ENGINE_BASELINE_CONFIRM_TIMEFRAMES")

    baseline_feature_allowlist = _parse_csv_str(
        "ENGINE_BASELINE_FEATURE_ALLOWLIST",
        (
            "trend__logret__15m",
            "flow_liquidity__shock_density__1m",
            "risk_volatility__realized_vol_60__1m",
        ),
    )
    baseline_feature_cap = _parse_positive_int("ENGINE_BASELINE_FEATURE_CAP", 3)
    if baseline_feature_cap > 12:
        raise ValueError("ENGINE_BASELINE_FEATURE_CAP must be <= 12.")

    meta_label_model = os.getenv("ENGINE_META_LABEL_MODEL", "logreg").strip().lower()
    if meta_label_model not in allowed_meta_label_model:
        raise ValueError(f"ENGINE_META_LABEL_MODEL contains unsupported value: {meta_label_model}")
    meta_label_objective = os.getenv("ENGINE_META_LABEL_OBJECTIVE", "classification_binary").strip().lower()
    if meta_label_objective not in allowed_meta_label_objective:
        raise ValueError(f"ENGINE_META_LABEL_OBJECTIVE contains unsupported value: {meta_label_objective}")
    meta_label_penalty = os.getenv("ENGINE_META_LABEL_PENALTY", "l1").strip().lower()
    if meta_label_penalty not in allowed_meta_label_penalty:
        raise ValueError(f"ENGINE_META_LABEL_PENALTY contains unsupported value: {meta_label_penalty}")
    meta_label_threshold_objective = os.getenv("ENGINE_META_LABEL_THRESHOLD_OBJECTIVE", "f05").strip().lower()
    if meta_label_threshold_objective not in allowed_meta_label_threshold_objective:
        raise ValueError(
            f"ENGINE_META_LABEL_THRESHOLD_OBJECTIVE contains unsupported value: {meta_label_threshold_objective}"
        )
    meta_label_feature_allowlist = _parse_csv_str(
        "ENGINE_META_LABEL_FEATURE_ALLOWLIST",
        baseline_feature_allowlist,
    )
    meta_label_feature_cap = _parse_positive_int("ENGINE_META_LABEL_FEATURE_CAP", baseline_feature_cap)
    if meta_label_feature_cap > 16:
        raise ValueError("ENGINE_META_LABEL_FEATURE_CAP must be <= 16.")
    meta_label_enabled = _parse_bool("ENGINE_META_LABEL_ENABLED", True)
    meta_label_c = _parse_float("ENGINE_META_LABEL_C", 0.25)
    if meta_label_c <= 0.0:
        raise ValueError("ENGINE_META_LABEL_C must be positive.")
    meta_label_max_iter = _parse_positive_int("ENGINE_META_LABEL_MAX_ITER", 2500)
    meta_label_class_weight = os.getenv("ENGINE_META_LABEL_CLASS_WEIGHT", "balanced").strip().lower()
    if meta_label_class_weight not in allowed_meta_label_class_weight:
        raise ValueError(f"ENGINE_META_LABEL_CLASS_WEIGHT contains unsupported value: {meta_label_class_weight}")
    meta_label_tp_mult = _parse_float("ENGINE_META_LABEL_TP_MULT", 1.5)
    if meta_label_tp_mult <= 0.0:
        raise ValueError("ENGINE_META_LABEL_TP_MULT must be positive.")
    meta_label_sl_mult = _parse_float("ENGINE_META_LABEL_SL_MULT", 1.0)
    if meta_label_sl_mult <= 0.0:
        raise ValueError("ENGINE_META_LABEL_SL_MULT must be positive.")
    meta_label_vertical_horizon_bars = _parse_positive_int("ENGINE_META_LABEL_VERTICAL_HORIZON_BARS", 16)
    meta_label_vol_window = _parse_positive_int("ENGINE_META_LABEL_VOL_WINDOW", 20)
    meta_label_min_events = _parse_positive_int("ENGINE_META_LABEL_MIN_EVENTS", 80)
    meta_label_threshold_min = _parse_ratio("ENGINE_META_LABEL_THRESHOLD_MIN", 0.50)
    meta_label_threshold_max = _parse_ratio("ENGINE_META_LABEL_THRESHOLD_MAX", 0.95)
    if meta_label_threshold_max < meta_label_threshold_min:
        raise ValueError("ENGINE_META_LABEL_THRESHOLD_MAX must be >= ENGINE_META_LABEL_THRESHOLD_MIN.")
    meta_label_threshold_step = _parse_float("ENGINE_META_LABEL_THRESHOLD_STEP", 0.01)
    if meta_label_threshold_step <= 0.0:
        raise ValueError("ENGINE_META_LABEL_THRESHOLD_STEP must be positive.")
    meta_label_precision_floor = _parse_ratio("ENGINE_META_LABEL_PRECISION_FLOOR", 0.60)
    meta_label_prob_threshold_fallback = _parse_ratio("ENGINE_META_LABEL_PROB_THRESHOLD_FALLBACK", 0.55)
    meta_label_cpcv_splits = _parse_positive_int("ENGINE_META_LABEL_CPCV_SPLITS", 6)
    meta_label_cpcv_test_groups = _parse_positive_int("ENGINE_META_LABEL_CPCV_TEST_GROUPS", 2)
    meta_label_cpcv_purge_bars = _parse_non_negative_int(
        "ENGINE_META_LABEL_CPCV_PURGE_BARS",
        max(1, min(int(meta_label_vertical_horizon_bars), int(meta_label_vol_window))),
    )
    meta_label_cpcv_embargo_bars = _parse_non_negative_int(
        "ENGINE_META_LABEL_CPCV_EMBARGO_BARS",
        max(int(meta_label_vertical_horizon_bars), int(meta_label_cpcv_purge_bars)),
    )
    meta_label_cpcv_max_combinations = _parse_positive_int("ENGINE_META_LABEL_CPCV_MAX_COMBINATIONS", 24)

    universe_source = os.getenv("ENGINE_UNIVERSE_SOURCE", "coingecko_market_cap").strip().lower()
    if universe_source not in allowed_universe_source:
        raise ValueError(f"ENGINE_UNIVERSE_SOURCE contains unsupported value: {universe_source}")

    objective_mode = os.getenv("ENGINE_OBJECTIVE_MODE", "beat_spot_each_window").strip().lower()
    if objective_mode not in allowed_objective_mode:
        raise ValueError(f"ENGINE_OBJECTIVE_MODE contains unsupported value: {objective_mode}")

    validation_strictness = os.getenv("ENGINE_VALIDATION_STRICTNESS", "institutional").strip().lower()
    if validation_strictness not in allowed_validation_strictness:
        raise ValueError(f"ENGINE_VALIDATION_STRICTNESS contains unsupported value: {validation_strictness}")

    rule_engine_mode = os.getenv("ENGINE_RULE_ENGINE_MODE", "feature_native").strip().lower()
    if rule_engine_mode not in allowed_rule_engine_modes:
        raise ValueError(f"ENGINE_RULE_ENGINE_MODE contains unsupported value: {rule_engine_mode}")

    return EngineConfig(
        data_root=data_root,
        artifact_root=artifact_root,
        run_start_utc=_parse_datetime_utc("ENGINE_RUN_START_UTC", datetime(2020, 1, 1, tzinfo=timezone.utc)),
        run_end_utc=_parse_datetime_utc("ENGINE_RUN_END_UTC", now_utc),
        top_n=_parse_positive_int("ENGINE_TOP_N", 15),
        quote_asset=os.getenv("ENGINE_QUOTE_ASSET", "USDT").upper(),
        universe_symbols=universe_symbols,
        raw_timeframe=os.getenv("ENGINE_RAW_TIMEFRAME", "1m"),
        aggregate_timeframes=aggregate_timeframes,
        archive_base_url=os.getenv(
            "BINANCE_ARCHIVE_BASE_URL",
            "https://data.binance.vision/data/spot/monthly/klines",
        ),
        binance_api_base_url=os.getenv("BINANCE_API_BASE_URL", "https://api.binance.com/api/v3"),
        universe_source=universe_source,
        coingecko_api_base_url=os.getenv("COINGECKO_API_BASE_URL", "https://api.coingecko.com/api/v3"),
        universe_strict_stable_filter=_parse_bool("ENGINE_UNIVERSE_STRICT_STABLE_FILTER", True),
        schedule_tier1_hours=_parse_positive_int("ENGINE_TIER1_HOURS", 6),
        schedule_tier2_hours=_parse_positive_int("ENGINE_TIER2_HOURS", 24),
        schedule_tier3_days=_parse_positive_int("ENGINE_TIER3_DAYS", 7),
        optimization_enabled=_parse_bool("ENGINE_OPTIMIZATION_ENABLED", True),
        optimization_timeframes=optimization_timeframes,
        feature_timeframes=feature_timeframes,
        optimization_windows=optimization_windows,
        optimization_gate_modes=optimization_gate_modes,
        leaderboard_modes=leaderboard_modes,
        optimization_long_only=_parse_bool("ENGINE_OPTIMIZATION_LONG_ONLY", True),
        objective_mode=objective_mode,
        optimization_schedule_hours=_parse_positive_int("ENGINE_OPTIMIZATION_SCHEDULE_HOURS", 24),
        optimization_max_rounds=_parse_positive_int("ENGINE_OPTIMIZATION_MAX_ROUNDS", 8),
        optimization_target_validation_pass_rate=_parse_ratio("ENGINE_OPT_TARGET_VALIDATION_PASS_RATE", 0.55),
        optimization_target_all_window_alpha_floor=_parse_float("ENGINE_OPT_TARGET_ALL_WINDOW_ALPHA_FLOOR", -0.02),
        optimization_target_deploy_alpha_floor=_parse_float("ENGINE_OPT_TARGET_DEPLOY_ALPHA_FLOOR", 0.0),
        optimization_target_deploy_symbol_ratio=_parse_ratio("ENGINE_OPT_TARGET_DEPLOY_SYMBOL_RATIO", 0.30),
        trade_floor=_parse_positive_int("ENGINE_TRADE_FLOOR", 100),
        window_trade_floor_overrides=window_trade_floor_overrides,
        baseline_primary_timeframe=baseline_primary_timeframe,
        baseline_confirm_timeframes=baseline_confirm_timeframes,
        baseline_low_dof_mode=_parse_bool("ENGINE_BASELINE_LOW_DOF_MODE", True),
        baseline_feature_cap=baseline_feature_cap,
        baseline_feature_allowlist=baseline_feature_allowlist,
        rl_enabled=_parse_bool("ENGINE_RL_ENABLED", False),
        rl_unlock_requires_baseline=_parse_bool("ENGINE_RL_UNLOCK_REQUIRES_BASELINE", True),
        rsi_windows=rsi_windows,
        rsi_strategies=rsi_strategies,
        rsi_lower_bounds=rsi_lower_bounds,
        rsi_upper_bounds=rsi_upper_bounds,
        friction_bps=_parse_positive_int("ENGINE_FRICTION_BPS", 10),
        gate_oracle_quantile=_parse_ratio("ENGINE_GATE_ORACLE_QUANTILE", 0.55),
        gate_confidence_quantile=_parse_ratio("ENGINE_GATE_CONFIDENCE_QUANTILE", 0.40),
        credibility_reject_threshold=_parse_ratio("ENGINE_CREDIBILITY_REJECT_THRESHOLD", 0.65),
        credible_candidate_max_penalty=_parse_ratio("ENGINE_CREDIBLE_MAX_PENALTY", 0.80),
        rule_engine_mode=rule_engine_mode,
        single_indicators=single_indicators,
        feature_cores=feature_cores,
        validation_enabled=_parse_bool("ENGINE_VALIDATION_ENABLED", True),
        validation_strictness=validation_strictness,
        validation_walk_forward_splits=_parse_positive_int("ENGINE_VALIDATION_WALK_FORWARD_SPLITS", 4),
        validation_cv_folds=_parse_positive_int("ENGINE_VALIDATION_CV_FOLDS", 4),
        validation_purge_bars=_parse_positive_int("ENGINE_VALIDATION_PURGE_BARS", 120),
        validation_stress_friction_bps=validation_stress_friction_bps,
        validation_sample_step=_parse_positive_int("ENGINE_VALIDATION_SAMPLE_STEP", 5),
        meta_label_enabled=meta_label_enabled,
        meta_label_model=meta_label_model,
        meta_label_objective=meta_label_objective,
        meta_label_penalty=meta_label_penalty,
        meta_label_c=meta_label_c,
        meta_label_max_iter=meta_label_max_iter,
        meta_label_class_weight=meta_label_class_weight,
        meta_label_tp_mult=meta_label_tp_mult,
        meta_label_sl_mult=meta_label_sl_mult,
        meta_label_vertical_horizon_bars=meta_label_vertical_horizon_bars,
        meta_label_vol_window=meta_label_vol_window,
        meta_label_min_events=meta_label_min_events,
        meta_label_threshold_min=meta_label_threshold_min,
        meta_label_threshold_max=meta_label_threshold_max,
        meta_label_threshold_step=meta_label_threshold_step,
        meta_label_precision_floor=meta_label_precision_floor,
        meta_label_threshold_objective=meta_label_threshold_objective,
        meta_label_prob_threshold_fallback=meta_label_prob_threshold_fallback,
        meta_label_feature_cap=meta_label_feature_cap,
        meta_label_feature_allowlist=meta_label_feature_allowlist,
        meta_label_cpcv_splits=meta_label_cpcv_splits,
        meta_label_cpcv_test_groups=meta_label_cpcv_test_groups,
        meta_label_cpcv_purge_bars=meta_label_cpcv_purge_bars,
        meta_label_cpcv_embargo_bars=meta_label_cpcv_embargo_bars,
        meta_label_cpcv_max_combinations=meta_label_cpcv_max_combinations,
        max_deploy_rules_per_symbol=_parse_positive_int("ENGINE_MAX_DEPLOY_RULES_PER_SYMBOL", 2),
    )
