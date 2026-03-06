export type LocaleCode = "zh-TW" | "en-US";

export type RejectionReason =
  | "REASON_ALL_WINDOW_ALPHA"
  | "REASON_CV_FAIL"
  | "REASON_DSR_BELOW_MIN"
  | "REASON_FINAL_SCORE_LOW"
  | "REASON_FRICTION_WEAK"
  | "REASON_HIGH_PBO"
  | "REASON_LOW_PRECISION"
  | "REASON_WF_FAIL"
  | "REASON_UNKNOWN";

export type StatusKey = "STATUS_VETO_ALL" | "STATUS_STALLED" | "STATUS_RECOVERY" | "STATUS_STABLE";

export type RegimeKey = "REGIME_VETO_HOLD" | "REGIME_CONSOLIDATION" | "REGIME_EXPANSION";

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
