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
  last_event_at_utc: string | null;
  last_sync_at_utc: string;
  notify_event_key: RuntimeNotifyKey | string;
  notify_seq: number;
}
