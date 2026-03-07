export type LocaleCode = "zh-TW" | "en-US";

export type RejectionReason =
  | "REASON_ALL_WINDOW_ALPHA"
  | "REASON_CV_FAIL"
  | "REASON_DSR_BELOW_MIN"
  | "REASON_FINAL_SCORE_LOW"
  | "REASON_FRICTION_WEAK"
  | "REASON_HIGH_PBO"
  | "REASON_LOW_PRECISION"
  | "REASON_TRADE_DENSITY_LOW"
  | "REASON_WF_FAIL"
  | "REASON_UNKNOWN";

export type StatusKey = "STATUS_VETO_ALL" | "STATUS_STALLED" | "STATUS_RECOVERY" | "STATUS_STABLE";

export type RegimeKey = "REGIME_VETO_HOLD" | "REGIME_CONSOLIDATION" | "REGIME_EXPANSION";

export type TrainingStatusKey =
  | "TRAINING_STATUS_RUNNING"
  | "TRAINING_STATUS_CONVERGED"
  | "TRAINING_STATUS_STALLED"
  | "TRAINING_STATUS_STAGNATED"
  | "TRAINING_STATUS_STAGNATED_FLOW_LOCK"
  | "TRAINING_STATUS_HALTED";

export type RuntimeStatusKey = "RUNTIME_RUNNING" | "RUNTIME_STALLED" | "RUNTIME_COMPLETED" | "RUNTIME_IDLE";

export type RuntimePhaseKey = "PHASE_ITERATING" | "PHASE_VALIDATING" | "PHASE_FINALIZING" | "PHASE_WAITING";

export type RuntimeStallReasonKey =
  | "STALL_NO_NEW_EVENTS"
  | "STALL_TARGET_NOT_MET"
  | "STALL_PROCESS_INACTIVE"
  | "STALL_UNKNOWN";

export type RuntimeCompletionReasonKey =
  | "COMPLETION_GATE_HIT"
  | "COMPLETION_STAGNATED"
  | "COMPLETION_HALTED"
  | "COMPLETION_UNKNOWN";

export type RuntimeNotifyKey = "NOTIFY_RUN_STARTED" | "NOTIFY_STALLED" | "NOTIFY_COMPLETED" | "NOTIFY_RESUMED";

export type RecoveryStageKey = "STAGE_FLOW_RECOVERY" | "STAGE_ALPHA_RECOVERY" | string;
export type CandidateTierKey = "CANDIDATE_TIER_EXPLORATORY" | "CANDIDATE_TIER_STRICT" | string;
export type RecoveryMilestoneKey =
  | "M1_TRADES"
  | "M2_VETO_93"
  | "M3_VETO_85_FAILSAFE_40"
  | "M3_PASSED"
  | string;
export type FlowStageReasonKey =
  | "FLOW_REASON_NEED_TRADES"
  | "FLOW_REASON_NEED_VETO_93"
  | "FLOW_REASON_NEED_VETO_85_FAILSAFE_40"
  | "FLOW_REASON_PASSED"
  | string;
export type RouteReasonKey =
  | "ROUTE_TRADE_DENSITY_LOW"
  | "ROUTE_PRECISION_UNMET"
  | "ROUTE_ALPHA_NEGATIVE"
  | "ROUTE_STABILITY_SCAN"
  | "ROUTE_PROFILE_EFFECTIVENESS_OVERRIDE"
  | "ROUTE_BATCH_EXPLORATION"
  | string;

export type BatchKey = "BATCH_FLOW_UNLOCK" | "BATCH_QUALITY_RECOVERY" | string;
export type BatchReasonKey =
  | "BATCH_REASON_IN_PROGRESS"
  | "BATCH_REASON_STAGE_CAP_REACHED"
  | "BATCH_REASON_FLOW_GATE_HIT"
  | "BATCH_REASON_QUALITY_GATE_HIT"
  | "BATCH_REASON_STAGNATION_LIMIT"
  | "BATCH_REASON_HARD_CAP_REACHED"
  | "BATCH_REASON_NO_THRESHOLD_MEETS_PRECISION_FLOOR"
  | "BATCH_REASON_EVENT_GENERATOR_DRY"
  | string;

export type FlowGatePhaseKey = "FLOW_GATE_A1_PENDING" | "FLOW_GATE_A2_PENDING" | "FLOW_GATE_A2_PASSED" | string;

export type ProfileKey =
  | "PROFILE_BASELINE"
  | "PROFILE_EVENT_EXPANSION"
  | "PROFILE_PRECISION_RECOVERY"
  | "PROFILE_ALPHA_RESCUE"
  | "PROFILE_STABILITY_SCAN"
  | "PROFILE_UNKNOWN"
  | string;

export type DiagnosisObjectiveKey =
  | "OBJECTIVE_FLOW_UNLOCK"
  | "OBJECTIVE_ALPHA_RECOVERY"
  | "OBJECTIVE_RECOVER_TRADE_FLOW"
  | "OBJECTIVE_RESTORE_PRECISION_COMPLIANCE"
  | "OBJECTIVE_REDUCE_ALL_WINDOW_LOSS"
  | "OBJECTIVE_STABILIZE_GENERALIZATION"
  | string;

export interface EvolutionValidation {
  artifact_version: string;
  generated_at_utc: string;
  source_generated_at_utc: string;
  run_id: string;
  status_key: StatusKey | string;
  regime_key: RegimeKey | string;
  metrics: {
    all_window_alpha: number;
    max_drawdown: number;
    pbo: number;
    dsr: number;
    precision: number;
    f1: number;
    pr_auc: number;
    precision_floor: number;
    precision_floor_compliance_rate: number;
    failsafe_veto_all_rate: number;
    veto_rate: number;
    threshold_selected: number;
    entry_signals_raw_all_window: number;
    barrier_events_all_window: number;
    entry_signals_meta_all_window: number;
    trades_total_all_window: number;
    funnel_kept_over_raw: number;
    funnel_trades_over_kept: number;
    funnel_trades_over_raw: number;
  };
  rejection_breakdown: Array<{
    reason_key: RejectionReason | string;
    count: number;
  }>;
}

export interface VisualState {
  artifact_version: string;
  last_synced_at: string;
  run_id: string;
  status_key: StatusKey | string;
  regime_key: RegimeKey | string;
  heartbeat_ok: boolean;
  live_alpha_vs_spot: number;
  max_drawdown: number;
  meta_diagnostics: {
    precision_floor: number;
    precision_floor_compliance_rate: number;
    failsafe_veto_all_rate: number;
    veto_rate: number;
    threshold_selected: number;
  };
  flow_funnel?: {
    raw_signals: number;
    barrier_labeled: number;
    meta_kept: number;
    trades: number;
    kept_over_raw: number;
    trades_over_kept: number;
    trades_over_raw: number;
  };
  rejection_breakdown: Array<{
    reason_key: RejectionReason | string;
    count: number;
  }>;
}

export interface TrainingRound {
  round_index: number;
  ts_utc: string;
  run_id: string;
  status_key: StatusKey | string;
  regime_key: RegimeKey | string;
  validation_pass_rate: number;
  all_window_alpha: number;
  deploy_ready: boolean;
  deploy_symbols: number;
  deploy_rules: number;
  trades_total_all_window: number;
  trades_avg_all_window: number;
  entry_signals_raw_all_window: number;
  barrier_events_all_window: number;
  entry_signals_meta_all_window: number;
  funnel_kept_over_raw: number;
  funnel_trades_over_kept: number;
  funnel_trades_over_raw: number;
  pbo: number;
  dsr: number;
  precision: number;
  f1: number;
  pr_auc: number;
  precision_floor: number;
  precision_floor_compliance_rate: number;
  failsafe_veto_all_rate: number;
  veto_rate: number;
  threshold_selected: number;
  primary_bottleneck: string;
  recommended_action: string;
  decision_rationale: string;
  round_profile: string;
  config_snapshot: Record<string, unknown>;
  objective_balance_score: number;
  rejection_top_reason_key: RejectionReason | string;
  rejection_breakdown: Array<{
    reason_key: RejectionReason | string;
    count: number;
  }>;
  iteration_file: string;
  gate_hit: boolean;
  quality_score: number;
}

export interface TrainingRoadmap {
  artifact_version: string;
  generated_at_utc: string;
  status_key: TrainingStatusKey | string;
  gate: {
    min_validation_pass_rate: number;
    min_all_window_alpha: number;
    require_deploy_ready: boolean;
    required_streak: number;
  };
  summary: {
    rounds_total: number;
    current_streak: number;
    required_streak: number;
    best_quality_score: number;
    stagnation_count: number;
    stagnation_rounds: number;
    hard_cap: number;
    loop_runs: number;
    flow_gate_streak: number;
    flow_gate_required_streak: number;
    flow_gate_achieved: boolean;
    flow_gate_phase_key: FlowGatePhaseKey | string;
    flow_gate_a1_hit: boolean;
    flow_gate_a2_hit: boolean;
    zero_trade_streak: number;
    last_flow_score: number;
    last_objective_score: number;
  };
  flow_gate?: {
    max_veto_rate: number;
    max_failsafe_veto_all_rate: number;
    min_trades_total_all_window: number;
    required_streak: number;
  };
  recovery_stage_key?: RecoveryStageKey | string;
  active_objective_key?: DiagnosisObjectiveKey | string;
  candidate_tier?: CandidateTierKey | string;
  current_batch_key?: BatchKey | string;
  batch_status_key?: StatusKey | string;
  batch_outcome_reason_key?: BatchReasonKey | string;
  batch_round_index?: number;
  batch_round_cap?: number;
  flow_unlock_cap?: number;
  quality_recovery_cap?: number;
  flow_unlock_rounds_run?: number;
  quality_recovery_rounds_run?: number;
  flow_stage_progress?: number;
  flow_stage_reason_key?: FlowStageReasonKey | string;
  recovery_milestone_key?: RecoveryMilestoneKey | string;
  next_profile_key?: ProfileKey | string;
  next_profile_name?: string;
  next_profile_route_reason_key?: RouteReasonKey | string;
  early_gate_hit?: boolean;
  latest_funnel?: {
    raw_signals: number;
    barrier_labeled: number;
    meta_kept: number;
    trades: number;
    kept_over_raw: number;
    trades_over_kept: number;
    trades_over_raw: number;
  };
  diagnosis?: {
    objective_key: DiagnosisObjectiveKey;
    recommended_profile_key: ProfileKey;
    recommended_overrides?: Record<string, string>;
    confidence: number;
    top_bottlenecks: Array<{
      reason_key: RejectionReason | string;
      severity: number;
      observed: number;
      target: number;
    }>;
  };
  profile_comparison?: {
    winner_profile_key: ProfileKey;
    sampled_rounds: number;
    rows: Array<{
      profile_key: ProfileKey;
      rounds: number;
      avg_pass_rate: number;
      avg_all_window_alpha: number;
      avg_veto_pressure: number;
      avg_quality_score: number;
      gate_hit_rate: number;
    }>;
  };
  profile_effectiveness?: Array<{
    profile_key: ProfileKey | string;
    recent_rounds: number;
    delta_veto: number;
    delta_trades: number;
    delta_alpha: number;
    score: number;
  }>;
  batch_param_heatmap?: Array<{
    loop_index: number;
    batch_key: BatchKey | string;
    threshold_min: number;
    vertical_horizon_bars: number;
    tp_mult: number;
    sl_mult: number;
    min_events: number;
    veto_rate: number;
    failsafe_veto_all_rate: number;
    trades_total_all_window: number;
    all_window_alpha: number;
  }>;
  latest_loop_profile?: {
    profile_name: string;
    profile_key: ProfileKey | string;
    profile_route_reason_key: RouteReasonKey | string;
    candidate_tier: CandidateTierKey | string;
    overrides: Record<string, string>;
  };
  latest_round: TrainingRound | Record<string, never>;
  best_round: TrainingRound | Record<string, never>;
  rounds: TrainingRound[];
}

export interface TrainingRuntime {
  artifact_version: string;
  generated_at_utc: string;
  runtime_status_key: RuntimeStatusKey | string;
  phase_key: RuntimePhaseKey | string;
  run_id: string;
  started_at_utc: string;
  elapsed_sec: number;
  remaining_sec: number | null;
  eta_utc: string | null;
  eta_confidence: string;
  cycle_current: number;
  cycle_total: number;
  cycle_pct: number;
  tasks_done: number;
  tasks_total: number;
  tasks_pct: number;
  progress_completed: boolean;
  gate_blocked: boolean;
  gate_block_reason_key: RuntimeStallReasonKey | string;
  stalled_reason_key: RuntimeStallReasonKey | string;
  completion_reason_key: RuntimeCompletionReasonKey | string;
  diagnosis_objective_key: DiagnosisObjectiveKey | string;
  diagnosis_recommended_profile_key: ProfileKey | string;
  diagnosis_top_reason_key: RejectionReason | string;
  diagnosis_confidence: number;
  recovery_stage_key: RecoveryStageKey | string;
  active_objective_key: DiagnosisObjectiveKey | string;
  candidate_tier: CandidateTierKey | string;
  current_batch_key: BatchKey | string;
  batch_status_key: StatusKey | string;
  batch_outcome_reason_key: BatchReasonKey | string;
  batch_round_index: number;
  batch_round_cap: number;
  flow_unlock_rounds_run: number;
  quality_recovery_rounds_run: number;
  flow_stage_progress: number;
  flow_stage_reason_key: FlowStageReasonKey | string;
  recovery_milestone_key: RecoveryMilestoneKey | string;
  next_profile_key: ProfileKey | string;
  next_profile_route_reason_key: RouteReasonKey | string;
  early_gate_hit: boolean;
  flow_gate_phase_key: FlowGatePhaseKey | string;
  flow_gate_a1_hit: boolean;
  flow_gate_a2_hit: boolean;
  zero_trade_streak: number;
  flow_funnel: {
    raw_signals: number;
    barrier_labeled: number;
    meta_kept: number;
    trades: number;
    kept_over_raw: number;
    trades_over_kept: number;
    trades_over_raw: number;
  };
  flow_gate_thresholds: {
    max_veto_rate: number;
    max_failsafe_veto_all_rate: number;
    min_trades_total_all_window: number;
    required_streak: number;
  };
  last_event_at_utc: string | null;
  last_sync_at_utc: string;
  notify_event_key: RuntimeNotifyKey | string;
  notify_seq: number;
}
