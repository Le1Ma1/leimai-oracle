from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TypedDict


@dataclass(frozen=True)
class UniverseAsset:
    symbol: str
    base_asset: str
    quote_asset: str
    rank: int
    market_cap: float
    first_seen_date: date
    source_rank: int | None = None
    source_market_cap_usd: float | None = None
    eligibility_flags: tuple[str, ...] = ()


class RunReport(TypedDict):
    run_id: str
    started_at_utc: str
    finished_at_utc: str
    symbols_processed: int
    missing_filled_count: int
    failures: list[str]
    output_paths: list[str]
    optimization_artifacts: dict[str, str] | None


class TimeRange(TypedDict):
    start_utc: datetime
    end_utc: datetime


class StrategyMetrics(TypedDict):
    total_return: float
    friction_adjusted_return: float
    max_drawdown: float
    win_rate: float
    trades: int


class StrategyCandidate(TypedDict, total=False):
    signal_source: str
    strategy_mode: str
    core_id: str
    core_name_zh: str
    core_family: str
    indicator_id: str
    indicator_name_zh: str
    indicator_family: str
    rule_key: str
    rule_label_zh: str
    params: dict[str, int | float]
    score: float
    rule_complexity_score: float
    objective_margin_vs_spot: float
    stability_penalty: float
    credibility_penalty: float
    edge_quality: float
    friction_quality: float
    credibility_quality: float
    metrics: StrategyMetrics


class RejectedCandidateExample(TypedDict):
    reason: str
    signal_source: str
    strategy_mode: str
    core_id: str
    core_name_zh: str
    core_family: str
    indicator_id: str
    indicator_name_zh: str
    indicator_family: str
    rule_key: str
    rule_label_zh: str
    params: dict[str, int | float]
    alpha_vs_spot: float
    metrics: StrategyMetrics


class RuleCompetition(TypedDict):
    total_candidates: int
    kept_candidates: int
    rejected_breakdown: dict[str, int]
    top_rejected_examples: list[RejectedCandidateExample]


class SignalFrequency(TypedDict):
    total_entries: int
    weekday_entries: int
    weekend_entries: int
    session_entries_utc: dict[str, int]
    hourly_entries_utc: list[int]


class EventSampleRef(TypedDict):
    type: str
    start_utc: str
    end_utc: str
    entry_utc: str
    exit_utc: str
    pnl: float
    bars: int
    candles_path: str | None


class NoLookaheadAudit(TypedDict):
    position_shift_bars: int
    feature_lag_bars: int
    htf_confirmed_only: bool
    causality_perturbation_pass: bool


class FeatureContributionRow(TypedDict):
    name: str
    family: str
    utility_score: float
    correlation: float
    direction: str
    coverage: float


class FeaturePruningRow(TypedDict):
    name: str
    family: str
    utility_score: float
    reason: str
    correlated_with: str | None
    correlation_abs: float


class FeatureWeightProfile(TypedDict, total=False):
    trend_weight_share: float
    energy_weight_share: float
    essence_weight_share: float
    ttc_penalty_share: float
    trend_component_avg: float
    energy_component_avg: float
    essence_component_avg: float
    ttc_component_avg: float
    oscillation_weight_share: float
    risk_weight_share: float
    flow_weight_share: float
    timing_weight_share: float
    oscillation_component_avg: float
    risk_component_avg: float
    flow_component_avg: float
    timing_component_avg: float
    family_contribution: dict[str, float]
    top_features: list[FeatureContributionRow]
    prune_candidates: list[FeaturePruningRow]


class OptimizationWindowResult(TypedDict):
    window: str
    start_utc: str
    end_utc: str
    window_trade_floor: int
    benchmark_buy_hold_return: float
    best_long: StrategyCandidate | None
    best_inverse: StrategyCandidate | None
    top_long_candidates: list[StrategyCandidate]
    top_inverse_candidates: list[StrategyCandidate]
    best_long_alpha_vs_spot: float | None
    best_inverse_alpha_vs_spot: float | None
    best_long_passes_objective: bool
    best_inverse_passes_objective: bool
    insufficient_statistical_significance: bool
    evaluated_candidates: int
    rule_competition: RuleCompetition | None
    signal_frequency: SignalFrequency | None
    event_samples: list[EventSampleRef]
    no_lookahead_audit: NoLookaheadAudit | None
    feature_weight_profile: FeatureWeightProfile | None
    oracle_threshold: float | None
    confidence_threshold: float | None


class TimeframeOptimizationResult(TypedDict):
    symbol: str
    timeframe: str
    gate_mode: str
    strategy_mode: str
    core_id: str
    core_name_zh: str
    core_family: str
    indicator_id: str
    indicator_name_zh: str
    indicator_family: str
    windows: list[OptimizationWindowResult]


class SymbolOptimizationReport(TypedDict):
    symbol: str
    asof_utc: str
    timeframes: list[TimeframeOptimizationResult]


class OptimizationSummary(TypedDict):
    run_id: str
    asof_utc: str
    universe: list[str]
    windows: list[str]
    timeframes: list[str]
    gate_modes: list[str]
    results: list[TimeframeOptimizationResult]
