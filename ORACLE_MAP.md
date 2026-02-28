# ORACLE_MAP

Source of Truth for LeiMai Oracle architecture and execution status.

- Last Updated (UTC): `2026-02-28T11:09:12Z`
- Operating Protocol: read this file before coding; sync this file after execution.
- Governance Principles: MECE modules, Read/Write Isolation, Bai Ben (Minimalism).

## [LOGIC_CORE]

### [x] G0_PROTOCOL_BASELINE
- Technical Dependency: `ORACLE_MAP.md`, `.cursorrules`
- Business Value: Persistent governance baseline for autonomous implementation.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] R0_REPOSITORY_RESET_BASELINE
- Technical Dependency: repository reset + whitelist retention mechanism.
- Business Value: legacy overlap removed; rebuild starts from clean topology.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] R1_BRAND_ASSET_SIGNATURE_MECHANISM
- Technical Dependency: `logo.png`, `signature.jpg`, `scripts/prepare-brand.mjs`, `public/*icon*`.
- Business Value: stable brand identity and signed visual assets.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B0_ENGINE_MODULE_ISOLATION
- Technical Dependency: `engine/src/*`, `engine/requirements.txt`.
- Business Value: standalone backend runtime, physically isolated from web runtime.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B1_UNIVERSE_COINGECKO_MARKET_CAP_TOP15
- Technical Dependency: `engine/src/universe.py`, `engine/src/config.py`, `engine/src/exclusions.py`.
- Business Value: Universe aligned to market-cap ranking (CoinGecko free API) mapped to Binance USDT spot symbols.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B1_1_STRICT_STABLE_FILTER
- Technical Dependency: `engine/src/exclusions.py`, `engine/src/universe.py`.
- Business Value: strict exclusion for stable/wrapped patterns to avoid contaminating growth universe.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B2_HYBRID_INGEST_ARCHIVE_PLUS_API
- Technical Dependency: `engine/src/binance_archive.py`, `engine/src/binance_api.py`, `engine/src/ingest_1m.py`.
- Business Value: archive-first ingestion with API backfill for missing ranges.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B2_1_TIMESTAMP_UNIT_HARDENING
- Technical Dependency: `engine/src/binance_archive.py::_normalize_open_time_to_ms`.
- Business Value: normalizes mixed timestamp precision from archive edge cases.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B2_2_TOP15_COMPLETENESS_20200101_TO_NOW
- Technical Dependency: `engine/src/main.py` once-mode runs, `engine/data/raw/symbol=*/timeframe=1m/date=*`.
- Business Value: current Top15 complete from `2020-01-01` to `2026-02-24` (UTC) with zero missing partition days.
- Evidence: backfill runs `b75b513f153f4e93bf06d0d9b50381c6` (ETCUSDT), `2dc436d7042b40e292c8872d7b3df362` (ATOMUSDT).
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B3_MULTI_TF_AGGREGATION_PARQUET
- Technical Dependency: `engine/src/aggregate.py`, `engine/src/storage.py`.
- Business Value: generates `1m/5m/15m/1h/4h/1d/1w` parquet layers for analysis and feature pipeline.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B4_AUTOMATION_SCHEDULER_TIERS
- Technical Dependency: `engine/src/scheduler.py`.
- Business Value: tiered refresh cadence for data + dedicated optimization schedule.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B8_RSI_MULTIMODAL_HARDFIT_ENGINE
- Technical Dependency: `engine/src/rsi_strategies.py`, `engine/src/optimization.py`.
- Business Value: RSI hard-fit grid search with statistical trade floor.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B8_1_OPTIMIZATION_TIMEFRAME_LOCK_1M
- Technical Dependency: `engine/src/config.py`, `engine/src/run_once.py`, `engine/src/reporting.py`, `engine/.env.example`.
- Business Value: optimization contract hard-locked to `1m`; non-1m optimization input rejected.
- Read/Write Isolation Review: Pass. Constraint applied only in backend config/runtime/artifact layers.
- Bai Ben (Minimalism) Review: Pass. Eliminates fitting-timeframe ambiguity.

### [x] B8_2_DUAL_GATE_AND_LEADERBOARD_MODES
- Technical Dependency: `engine/src/config.py`, `engine/src/types.py`, `engine/src/optimization.py`, `engine/src/run_once.py`, `engine/src/reporting.py`, `engine/.env.example`.
- Business Value: outputs both `gated/ungated` optimization views and both `score/return` leaderboard views in one artifact contract.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B8_3_MISSCOPED_FULL_RUN_ABORTED
- Technical Dependency: runtime process control on `python -m engine.src.main --mode once --optimize on`.
- Business Value: stopped incorrect full-run branch to prevent wasted compute and wrong-universe artifacts.
- Evidence: stopped process `PID=9552` (run_id `8846443e15f141988454b50a911f4deb`).
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B8_4_LONG_ONLY_BEAT_SPOT_OBJECTIVE
- Technical Dependency: `engine/src/config.py`, `engine/src/types.py`, `engine/src/optimization.py`, `engine/src/reporting.py`, `engine/src/run_once.py`, `engine/.env.example`.
- Business Value: optimization supports long-only mode and per-window objective `strategy_return >= spot_buy_hold_return`.
- Evidence: smoke run `fc595eaa26094e0a9b3182872d1d754b` includes benchmark, alpha_vs_spot, passes_objective fields.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B8_5_STAT_SIGNIFICANCE_DECOUPLED_FROM_OBJECTIVE
- Technical Dependency: `engine/src/optimization.py`.
- Business Value: `insufficient_statistical_significance` now depends only on statistical floor (`trades > trade_floor`) and no longer mislabels objective failure as missing significance.
- Evidence: iterative run `iter_r1_7c22035dfb08` reports `insufficient_count=0` for both `gated` and `ungated`.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B8_6_OBJECTIVE_FIRST_BEST_SELECTION
- Technical Dependency: `engine/src/optimization.py::_prioritize_objective_candidates`.
- Business Value: when objective-passing candidates exist, `best_long` and `best_inverse` are selected from that subset first.
- Evidence: iterative run `iter_r1_7c22035dfb08` reached `ungated` pass rate `0.9833`.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B8_7_ITERATIVE_QUALITY_GATE_PASS
- Technical Dependency: `engine/src/iterate_optimize.py`, `engine/src/main.py`, `engine/artifacts/optimization/single/iterations/*`.
- Business Value: automated iterative loop converges and exits on quality gate pass.
- Evidence: `ITERATION_COMPLETE` with `final_pass=true`, `final_run_id=iter_r1_ad659c3b8a2a`, report `engine/artifacts/optimization/rsi/iterations/2026-02-24/iteration_20260224T133011Z_0db41582.json`.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B8_8_SINGLE_INDICATOR_COMPETITION_ENGINE
- Technical Dependency: `engine/src/single_indicators.py`, `engine/src/optimization.py`, `engine/src/run_once.py`.
- Business Value: promotion from RSI-only hard-fit to multi-indicator single-factor competition (`rsi/macd/bollinger/ema_cross/atr_regime/stoch_rsi/adx/cci`) under 1m lock.
- Evidence: smoke artifact run `smoke_fast_20260224T151355Z`.
- Read/Write Isolation Review: Pass. Pure backend compute/artifact path only.
- Bai Ben (Minimalism) Review: Pass. Reused existing scoring/gating contract; no frontend coupling.

### [x] B9_FEATURE_FUSION_TTC
- Technical Dependency: `engine/src/features.py`.
- Business Value: HTF confirmed-bar features fused into 1m feature set with TTC efficiency.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B10_OPTIMIZATION_ARTIFACT_CONTRACT
- Technical Dependency: `engine/src/reporting.py`, `engine/artifacts/optimization/single/*`.
- Business Value: stable JSON payload for review and downstream integration.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B10_1_REVIEW_DASHBOARD_STATIC_UI
- Technical Dependency: `review/index.html`, `review/README.md`.
- Business Value: immediate human review surface without framework coupling.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B10_3_REVIEW_UI_1M_ONLY
- Technical Dependency: `review/index.html`, `review/review-guide.md`.
- Business Value: UI enforces 1m-only fitting interpretation.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B10_4_REVIEW_UI_DUAL_MODE_CONTROLS
- Technical Dependency: `review/index.html`, `review/README.md`, `review/review-guide.md`.
- Business Value: operators inspect `gated/ungated` and `score/return` without schema translation.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B10_5_REVIEW_SPOT_BENCHMARK_COLUMNS
- Technical Dependency: `review/index.html`, `review/README.md`, `review/review-guide.md`.
- Business Value: review panel surfaces `spot`, `alpha_vs_spot`, `passes_objective`, and `UNDERPERFORM_SPOT` flags.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B10_6_EXPLAINABILITY_ARTIFACT_LAYER
- Technical Dependency: `engine/src/types.py`, `engine/src/optimization.py`, `engine/src/reporting.py`.
- Business Value: outputs `explainability.json` with per-window grade, rule competition, feature contribution, signal frequency, event samples, and no-lookahead audit.
- Evidence: `engine/artifacts/optimization/rsi/2026-02-24/explainability.json`.
- Read/Write Isolation Review: Pass. Explainability is generated inside isolated engine artifact write path.
- Bai Ben (Minimalism) Review: Pass. Added one clear artifact contract without coupling to frontend runtime.

### [x] B10_7_EVENT_KLINE_SAMPLING_PAYLOAD
- Technical Dependency: `engine/src/reporting.py`, `engine/src/storage.py`, `engine/artifacts/optimization/rsi/*/events/*`.
- Business Value: each symbol-window now includes best/median/worst sampled trade K-line payloads for human audit.
- Evidence: `engine/artifacts/optimization/rsi/2026-02-24/events/gate=gated/window=all/symbol=BTCUSDT/*.json`.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B10_8_WHITE_LANGUAGE_WINDOW_FIRST_REVIEW_UI
- Technical Dependency: `review/index.html`, `review/README.md`, `review/review-guide.md`.
- Business Value: UI switched to decision-first, window-first matrix with A/B/C/C* grade and plain-language interpretation for non-technical review.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B10_9_MULTI_INDICATOR_WHITE_LANGUAGE_UI
- Technical Dependency: `review/index.html`, `review/README.md`.
- Business Value: review panel now supports indicator filter, symbol-indicator matrix, rule competition decomposition, and plain-language weight labels.
- Read/Write Isolation Review: Pass. Static review assets only read artifact JSON.
- Bai Ben (Minimalism) Review: Pass. Single static page, no framework runtime coupling.

### [x] B10_10_SINGLE_ARTIFACT_PATH_AND_RULE_CATALOG
- Technical Dependency: `engine/src/reporting.py`, `engine/artifacts/optimization/single/*`.
- Business Value: unified single-indicator artifact contract with `rule_catalog` + `indicator_comparison` for operator decision workflows.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B13_VALIDATION_LAYER_WALKFORWARD_PURGEDCV_PBO_DSR
- Technical Dependency: `engine/src/validation.py`, `engine/src/config.py`, `engine/src/run_once.py`, `engine/.env.example`.
- Business Value: converts candidate rules into validated rules with walk-forward, purged CV, PBO, DSR, and friction stress checkpoints.
- Evidence: `engine/artifacts/optimization/single/2026-02-25/validation_report.json` generated by run `smoke_validation_btc_short`.
- Read/Write Isolation Review: Pass. Validation reads engine artifacts/raw parquet and writes new engine artifacts only.
- Bai Ben (Minimalism) Review: Pass. Added one isolated backend module and two artifacts.

### [x] B14_DEPLOY_POOL_SELECTION
- Technical Dependency: `engine/src/validation.py`, `engine/src/run_once.py`, `engine/src/iterate_optimize.py`.
- Business Value: enforces execution-layer minimalism by selecting at most two validated rules per symbol into `deploy_pool.json`.
- Evidence: `engine/artifacts/optimization/single/2026-02-25/deploy_pool.json`.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B14_1_DEPLOY_ALPHA_FLOOR
- Technical Dependency: `engine/src/validation.py::_build_deploy_pool`.
- Business Value: deploy pool now enforces `alpha_vs_spot >= 0`, preventing validated-but-underperforming rules from entering execution candidates.
- Evidence: `engine/artifacts/optimization/single/2026-02-25/deploy_pool.json` min alpha is non-negative.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B15_ITERATION_DECISION_LOG
- Technical Dependency: `engine/src/iterate_optimize.py`.
- Business Value: each iterative round now records bottleneck diagnosis and recommended next action for deterministic tuning traceability.
- Evidence: `engine/artifacts/optimization/single/iterations/2026-02-25/iteration_decision_log_20260225T065243Z_1fad102b.json`.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B16_DYNAMIC_WINDOW_TRADE_FLOOR_AND_TTC_FUSION
- Technical Dependency: `engine/src/optimization.py`, `engine/src/types.py`, `engine/src/reporting.py`.
- Business Value: replaces fixed per-window trade threshold with window-scaled floor and upgrades TTC from single-fallback to multi-timeframe fusion.
- Evidence: optimization outputs now include `window_trade_floor` in window payloads.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B17_VALIDATE_ONLY_REBUILD_MODE
- Technical Dependency: `engine/src/main.py`, `engine/src/validation.py`, `engine/README.md`.
- Business Value: supports validation/deploy regeneration from existing `summary.json` without rerunning full optimization; guarantees same-run artifact consistency.
- Evidence: `python -m engine.src.main --mode validate --summary-path engine/artifacts/optimization/single/2026-02-25/summary.json`.
- Read/Write Isolation Review: Pass. Validation-only reads optimization artifacts/raw parquet and writes validation artifacts only.
- Bai Ben (Minimalism) Review: Pass. One focused mode, no frontend coupling.

### [x] B18_ITERATION_TARGET_GATES_CONFIGURABLE
- Technical Dependency: `engine/src/config.py`, `engine/.env.example`, `engine/src/main.py`, `engine/src/iterate_optimize.py`.
- Business Value: iteration stop conditions are now configurable by environment (`validation pass rate`, `all-window alpha floor`, `deploy alpha floor`, `deploy symbol ratio`, `max rounds`) for autonomous tuning.
- Evidence: new env keys `ENGINE_OPTIMIZATION_MAX_ROUNDS`, `ENGINE_OPT_TARGET_*`.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B18_1_VALIDATION_SCORE_ALPHA_ALIGNMENT
- Technical Dependency: `engine/src/validation.py`.
- Business Value: score decomposition now exposes `alpha_quality`, `stability_quality`, `execution_cost_quality` and increases alpha alignment inside transferability scoring.
- Evidence: validation rows now include expanded `scores` fields.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B18_2_SINGLE_INDICATOR_RULE_SPACE_EXPANSION
- Technical Dependency: `engine/src/single_indicators.py`, `engine/src/optimization.py`, `engine/src/types.py`.
- Business Value: broader indicator candidate grids and explicit candidate metadata (`rule_complexity_score`, `objective_margin_vs_spot`, `stability_penalty`) improve competition quality and explainability.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B10_14_REPORTING_HEALTH_RANK_HEATMAP_CONTRACT
- Technical Dependency: `engine/src/reporting.py`, `engine/src/run_once.py`, `engine/src/iterate_optimize.py`.
- Business Value: summary contract now includes `health_dashboard`, `rank_shift_gated_vs_ungated`, `window_alpha_heatmap_payload`, `indicator_competition_overview`.
- Evidence: `engine/artifacts/optimization/single/2026-02-26/summary.json`.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B10_15_REVIEW_HEALTH_AND_RANK_SHIFT_LAYER
- Technical Dependency: `review/index.html`, `review/README.md`.
- Business Value: review UI now adds KPI health dashboard and gated-vs-ungated rank-shift board for faster decision-making.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B18_3_AUTONOMOUS_FULL_ITERATION_LAUNCHED
- Technical Dependency: `engine/src/main.py`, `engine/src/iterate_optimize.py`, `engine/artifacts/logs/*`.
- Business Value: full Top15 single-indicator autonomous iteration is now launched in background with persistent logs for long-running execution.
- Evidence: restarted run_id `iter_r1_5d4024cafdb3`, log `engine/artifacts/logs/iterate_featurefirst_20260226_123913.out.log`.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B10_11_REVIEW_UI_CONSISTENCY_AND_PLAIN_GUIDE
- Technical Dependency: `review/index.html`, `review/README.md`.
- Business Value: dashboard now enforces run-id consistency checks, auto-ignores cross-run validation/deploy files, and provides plain-language 4-step guidance for rapid human review.
- Evidence: `review/index.html` integrity hint + quick guide + translated rejection reasons + indicator zh labels.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B10_12_REVIEW_PYRAMID_GATE_DELTA_LAYER
- Technical Dependency: `review/index.html`, `engine/src/reporting.py`.
- Business Value: introduces a top-level gated-vs-ungated difference layer so users can see pass-rate and alpha deltas before entering detailed matrices.
- Evidence: `summary.json` now includes `delta_views.gate_delta_by_window`; review renders `金字塔差異總覽`.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B10_13_REVIEW_HYPERMATRIX_SLICE_VIEW
- Technical Dependency: `review/index.html`, `engine/src/reporting.py`, `review/README.md`.
- Business Value: adds `symbol x indicator` hypermatrix with direct/delta mode and metric switch (`alpha/return/score/pass`) for multidimensional comparison without unreadable single mega-table.
- Evidence: review `#hmTable` + controls (`hmWindowFilter/hmMetricFilter/hmModeFilter`), clickable cells drilled down to detail panel.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B10_16_REVIEW_UNIFIED_MATRIX_ATLAS
- Technical Dependency: `review/index.html`, `engine/src/reporting.py`.
- Business Value: consolidates multidimensional comparison into one atlas (`window x symbol x indicator x gate-delta`) with sortable axis (`symbol/metric/rank-shift/pass-rate`) to reduce scan latency for operator decisions.
- Evidence: review panel `Unified Matrix Atlas（單圖整合）` with `hmSortFilter`, `hmTimeframeBadge`, G/U pass flags, rank-shift tags, and dual mini-bars in each cell.
- Read/Write Isolation Review: Pass. Static frontend reads existing artifact JSON only.
- Bai Ben (Minimalism) Review: Pass. Reuses one panel and existing payload without new runtime module.

### [x] B10_17_REVIEW_FEATURE_CONVERGENCE_INTELLIGENCE_LAYER
- Technical Dependency: `review/index.html`, `review/README.md`, `engine/src/reporting.py`.
- Business Value: adds feature convergence cockpit (family contribution ranking, top-importance features, prune candidates, plain-language weakness/improvement/advantage insights) and explicit high-dimensional two-bar feature family mapping for faster operator interpretation.
- Evidence: review panel `特徵收斂總覽（家族 / 排名 / 剪枝）`, tables `featureFamilyTable/featureTopTable/featurePruneTable`, and guide block `featureConvergenceGuide`.
- Read/Write Isolation Review: Pass. Static review layer only reads existing artifact contracts.
- Bai Ben (Minimalism) Review: Pass. Implemented in one panel with existing JSON sources; no new service/module introduced.

### [x] B19_FEATURE_LAYER_V2_FLOW_LIQUIDITY
- Technical Dependency: `engine/src/features.py`, `engine/src/run_once.py`, `engine/src/iterate_optimize.py`.
- Business Value: feature layer upgraded from indicator-centric to family-centric (`trend/oscillation/risk_volatility/flow_liquidity/timing_execution`) with adaptive log-based flow/liquidity signals and registry contract.
- Evidence: smoke run `209d04f8582b432caf750eccca6725b1` logged `features=109`; summary contains `feature_registry`.
- Read/Write Isolation Review: Pass. Pure backend data/feature path; frontend only reads artifacts.
- Bai Ben (Minimalism) Review: Pass. Reused existing feature pipeline entrypoint and added one registry surface.

### [x] B20_SOFT_CREDIBILITY_AND_ORACLE_GATE
- Technical Dependency: `engine/src/optimization.py`, `engine/src/validation.py`, `engine/src/reporting.py`, `engine/src/types.py`, `engine/.env.example`.
- Business Value: removed hard trade-floor rejection, replaced with continuous credibility penalty; gated mode now uses adaptive `oracle_score + confidence` thresholds (dynamic family weights); artifacts now expose feature importance and pruning candidates for iterative elimination.
- Evidence: summary/explainability include `oracle_threshold`, `confidence_threshold`, `low_credibility`, `feature_importance_leaderboard`, `feature_pruning_candidates`.
- Read/Write Isolation Review: Pass. Changes confined to backend scoring/validation/reporting.
- Bai Ben (Minimalism) Review: Pass. No new runtime service; contract extended in-place.

### [x] B21_FEATURE_NATIVE_RULE_ENGINE_MIGRATION
- Technical Dependency: `engine/src/feature_cores.py`, `engine/src/config.py`, `engine/src/optimization.py`, `engine/src/run_once.py`, `engine/src/iterate_optimize.py`, `engine/src/validation.py`, `engine/src/reporting.py`, `engine/src/types.py`, `engine/.env.example`.
- Business Value: execution and artifact contracts now support `feature_native` as first-class mode, with six branded signal cores replacing indicator-only orchestration while keeping compatibility aliases.
- Evidence: smoke run `4745ff586edc4560bdff53db2a450a88` produced `strategy_mode=feature_native` and `signal_cores` in `engine/artifacts/optimization/single/2026-02-26/summary.json`.
- Read/Write Isolation Review: Pass. Changes isolated to `engine` computation and artifact layer.
- Bai Ben (Minimalism) Review: Pass. Reused existing optimization/validation pipelines via shared strategy abstraction.

### [x] B10_18_REVIEW_FEATURE_NATIVE_DUAL_GATE_MATRIX
- Technical Dependency: `review/index.html`.
- Business Value: dashboard now provides one unified matrix with `single gate / dual gate` modes and same-cell `gated vs ungated` delta view for direct visual comparison.
- Evidence: `review/index.html` includes `matrixMode` selector, delta cards, and dual-cell render (`Δ alpha`, `G/U` values).
- Read/Write Isolation Review: Pass. Static review layer only reads artifact JSON.
- Bai Ben (Minimalism) Review: Pass. One file update, no framework/runtime coupling.

### [x] B18_4_ITERATION_PROCESS_CONTROL_AND_SMOKE_VERIFICATION
- Technical Dependency: runtime process control + `python -m engine.src.main --mode once --optimize on --symbol BTCUSDT`.
- Business Value: stale long-running iterate branch was stopped and replaced by deterministic feature-native smoke verification to keep artifact contract trustworthy.
- Evidence: new run_id `4745ff586edc4560bdff53db2a450a88`, `review_status=200`, `summary_status=200`.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B1_2_EXPLICIT_UNIVERSE_OVERRIDE
- Technical Dependency: `engine/src/config.py`, `engine/src/universe.py`, `engine/src/iterate_optimize.py`, `engine/.env.example`.
- Business Value: supports fixed symbol basket via `ENGINE_UNIVERSE_SYMBOLS`, decoupling iteration targets from dynamic market-cap ranking drift.
- Evidence: explicit override now accepts historical symbols and falls back to symbol suffix parsing when exchange TRADING status is unavailable.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B20_1_AGGRESSIVE_GATE_AND_CREDIBILITY_TUNABLES
- Technical Dependency: `engine/src/config.py`, `engine/src/optimization.py`, `engine/src/validation.py`, `engine/.env.example`.
- Business Value: gating quantiles and credibility cutoffs are now configurable (`oracle/confidence quantile`, `reject threshold`, `credible max penalty`) for alpha-first aggressive iteration.
- Evidence: new env keys `ENGINE_GATE_ORACLE_QUANTILE`, `ENGINE_GATE_CONFIDENCE_QUANTILE`, `ENGINE_CREDIBILITY_REJECT_THRESHOLD`, `ENGINE_CREDIBLE_MAX_PENALTY`.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B18_5_ALPHA_SUPERVISOR_AUTOMATION
- Technical Dependency: `scripts/alpha_supervisor.py`, `engine/README.md`.
- Business Value: one-command orchestration for aggressive run (`missing data ingest -> iterate -> alpha/deploy summary`) with fixed 15-symbol basket.
- Evidence: `python scripts/alpha_supervisor.py --max-rounds 2`.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] B18_6_ADAPTIVE_AUTOPILOT_SUPERVISOR
- Technical Dependency: `scripts/alpha_supervisor.py`.
- Business Value: supervisor now supports multi-cycle adaptive tuning (`gate quantiles`, `credibility cutoffs`, `validation strictness`) with early-stop quality targets.
- Evidence: `python scripts/alpha_supervisor.py --max-rounds 1 --cycles 2 --skip-ingest`.
- Read/Write Isolation Review: Pass. Script only orchestrates `engine` CLI and writes logs/artifacts under `engine/artifacts`.
- Bai Ben (Minimalism) Review: Pass. Reused existing pipeline, added adaptation in one script without new service/runtime.

### [x] B18_7_FEATURE_NATIVE_TRADE_FLOOR_OVERRIDE_FIX
- Technical Dependency: `engine/src/iterate_optimize.py::_clone_config_for_profile`.
- Business Value: in `feature_native` mode, profile baseline no longer hard-overrides env-driven `trade_floor`, enabling supervisor adaptive trade-floor control to actually take effect.
- Evidence: profile clone now uses `cfg.trade_floor` when `rule_engine_mode=feature_native`.
- Read/Write Isolation Review: Pass. Change is isolated to engine iteration config cloning.
- Bai Ben (Minimalism) Review: Pass. One-line behavior fix, no new module.

### [x] B10_19_LIVE_PROGRESS_STATUS_WRITER
- Technical Dependency: `scripts/progress_monitor.py`, `engine/artifacts/monitor/live_status.json`, `engine/artifacts/monitor/live_history.json`.
- Business Value: converts raw event logs into plain-language, machine-readable progress/ETA snapshots for operators.
- Evidence: `python scripts/progress_monitor.py --interval 2` continuously updates `live_status.json`.
- Read/Write Isolation Review: Pass. Monitor is read-only against engine logs/artifacts and writes only monitor snapshots under artifacts.
- Bai Ben (Minimalism) Review: Pass. Single lightweight script, no backend service added.

### [x] B10_20_MONITOR_STANDALONE_UI_SURFACE
- Technical Dependency: `monitor/index.html`, `monitor/README.md`.
- Business Value: dedicated local page for real-time training progress, ETA, warnings, and quality snapshot without parsing logs.
- Evidence: `http://localhost:8787/monitor/` reads `/engine/artifacts/monitor/live_status.json`.
- Read/Write Isolation Review: Pass. Static UI reads monitor JSON only; no coupling to Next.js runtime.
- Bai Ben (Minimalism) Review: Pass. One standalone static page.

### [x] B10_21_MONITOR_SYMBOL_HEATMAP_AND_TARGET_LIGHTS
- Technical Dependency: `scripts/progress_monitor.py`, `monitor/index.html`.
- Business Value: monitor now exposes per-symbol completion heatmap and cycle target pass/fail lights, so operators can instantly see execution coverage and convergence status.
- Evidence: `live_status.json` includes `symbol_progress` and `targets.checks`; monitor UI renders both sections.
- Read/Write Isolation Review: Pass. Uses existing log/artifact inputs and writes only monitor snapshots.
- Bai Ben (Minimalism) Review: Pass. Extends existing monitor contract without new backend service.

### [x] B10_22_MONITOR_ZH_LOCALTIME_LOCALIZATION
- Technical Dependency: `monitor/index.html`, `monitor/README.md`.
- Business Value: monitor is localized to Traditional Chinese plain-language labels with local-time rendering, reducing operator interpretation cost and timezone confusion.
- Evidence: monitor header/KPI/table/actions are zh-Hant; `updated_at_utc`/`eta_utc`/event timestamps are rendered in browser local time.
- Read/Write Isolation Review: Pass. UI-only display-layer change; no backend schema/compute mutation.
- Bai Ben (Minimalism) Review: Pass. Reuses existing JSON contract and static monitor page.

### [x] B10_23_MONITOR_WINDOWS_FILELOCK_RESILIENCE
- Technical Dependency: `scripts/progress_monitor.py`.
- Business Value: monitor writer no longer exits on transient Windows file-lock contention; progress snapshots remain continuous during long training runs.
- Evidence: `_write_json` now retries atomic replace with backoff and degrades to direct write; loop catches write exceptions and continues.
- Read/Write Isolation Review: Pass. Change is isolated to monitor artifact write path.
- Bai Ben (Minimalism) Review: Pass. No new service, only hardened write behavior.

### [x] B10_24_SUPERVISOR_EMBEDDED_MONITOR_LIFECYCLE
- Technical Dependency: `scripts/alpha_supervisor.py`, `scripts/progress_monitor.py`.
- Business Value: one-command training now auto-starts/stops monitor writer, so operators can refresh monitor page without manual sidecar process management.
- Evidence: new CLI args `--with-monitor/--no-with-monitor` and `--monitor-interval`; supervisor manages monitor subprocess lifecycle and logs.
- Read/Write Isolation Review: Pass. Supervisor orchestrates scripts only; no coupling to frontend runtime.
- Bai Ben (Minimalism) Review: Pass. Reuses existing scripts with minimal CLI additions.

### [x] B10_25_CLOUD_BATCH_DISPATCH_AND_MANIFEST
- Technical Dependency: `scripts/cloud_dispatch.py`, `engine/artifacts/cloud/cloud_run_manifest.json`.
- Business Value: standardized cloud batch slicing (`kaggle/colab`) and monitor-readable manifest contract for remote run visibility.
- Evidence: `cloud_dispatch.py prepare` emits deterministic batch command payload; `cloud_dispatch.py manifest` writes schema `lmo.cloud_run_manifest.v1`.
- Read/Write Isolation Review: Pass. Cloud orchestration is script-level and does not couple to web/support runtime.
- Bai Ben (Minimalism) Review: Pass. One lightweight dispatcher script + one JSON contract.

### [x] B10_26_KAGGLE_DATASET_SYNC_PIPELINE
- Technical Dependency: `scripts/cloud_data_sync.py`.
- Business Value: push/pull synchronization between local repo and Kaggle datasets for data/artifact offload workflow.
- Evidence: subcommands `push` and `pull` with dataset id contract (`owner/slug`) and auto extract-root detection.
- Read/Write Isolation Review: Pass. Sync path is explicit and constrained to selected roots.
- Bai Ben (Minimalism) Review: Pass. Reuses Kaggle CLI without adding backend services.

### [x] B10_27_MONITOR_SOURCE_TOGGLE_LOCAL_CLOUD
- Technical Dependency: `monitor/index.html`, `monitor/CLOUD.md`.
- Business Value: operators can switch between live local monitor stream and cloud manifest stream without manual page rewiring.
- Evidence: toolbar source selector (`本地 Monitor` / `雲端 Manifest`) and schema normalization for `lmo.cloud_run_manifest.v1`.
- Read/Write Isolation Review: Pass. UI-only source binding; no mutation of engine training logic.
- Bai Ben (Minimalism) Review: Pass. Implemented in existing monitor page with path presets.

### [x] B10_28_VALIDATION_LIGHT_MODE_AND_FILTERS
- Technical Dependency: `engine/src/validation.py`, `engine/.env.example`, `engine/README.md`.
- Business Value: validation tail can be completed deterministically on constrained compute by using summary-driven light mode and optional gate/result filters.
- Evidence: new env contracts `ENGINE_VALIDATION_LIGHT_MODE`, `ENGINE_VALIDATION_GATE_MODES`, `ENGINE_VALIDATION_MAX_RESULTS`; validate run produced `2026-02-28/validation_report.json` and `deploy_pool.json`.
- Read/Write Isolation Review: Pass. Validation remains backend-only and does not couple to frontend/support modules.
- Bai Ben (Minimalism) Review: Pass. Added optional runtime switches without changing default full-validation path.

### [ ] B11_CLICKHOUSE_WRITEBACK
- Technical Dependency: future schema + idempotent writer.
- Business Value: persistent query layer for SaaS APIs.
- Read/Write Isolation Review: Pending.
- Bai Ben (Minimalism) Review: Pending.

### [ ] B12_SAAS_PUSH_DELTA_CHANNEL
- Technical Dependency: queue/webhook/websocket dispatcher.
- Business Value: real-time subscriber delivery.
- Read/Write Isolation Review: Pending.
- Bai Ben (Minimalism) Review: Pending.

### [x] S0_SUPPORT_SITE_MODULE_ISOLATION
- Technical Dependency: `support/server.mjs`, `support/worker.mjs`, `support/lib/*`, `support/web/*`.
- Business Value: standalone support + conversion property launched without coupling to engine training runtime.
- Read/Write Isolation Review: Pass. Support module has independent runtime state and API surface.
- Bai Ben (Minimalism) Review: Pass. Single-node service + worker, no extra framework dependency.

### [x] S1_TRON_DUAL_SOURCE_VERIFICATION
- Technical Dependency: `support/lib/chain-sources.mjs`, `support/worker.mjs`.
- Business Value: redundant ingestion path (Tronscan + TronGrid) for resilient TRC20 receipt verification and leaderboard continuity.
- Read/Write Isolation Review: Pass. Chain receipts persist only in `support/runtime/chain-state.json`.
- Bai Ben (Minimalism) Review: Pass. Two-source merge in one worker loop; no message queue introduced.

### [x] S2_SUPPORT_TRILINGUAL_SEO_GEO_STACK
- Technical Dependency: `support/server.mjs`, `support/lib/content.mjs`, `support/lib/seo.mjs`.
- Business Value: multilingual indexability + AI discoverability via hreflang, canonical, JSON-LD, sitemap, robots, llms.txt, and machine-readable knowledge endpoint.
- Read/Write Isolation Review: Pass. SEO/GEO output is read-only and isolated from training artifacts.
- Bai Ben (Minimalism) Review: Pass. SEO primitives are generated server-side with one compact module.

### [x] S3_DECLARATION_PREMOD_AND_AD_SLOTS
- Technical Dependency: `support/lib/moderation.mjs`, `support/server.mjs`, `support/lib/leaderboard.mjs`.
- Business Value: supports declaration monetization path (personal/ad) with pre-moderation and compliance control before public display.
- Read/Write Isolation Review: Pass. Moderation write path is isolated to `support/runtime/app-state.json`.
- Bai Ben (Minimalism) Review: Pass. One moderation queue and admin token gate, no extra approval service.

### [x] S4_APEX_THRONE_UIUX_FINALIZATION
- Technical Dependency: `support/server.mjs`, `support/web/styles.css`, `support/web/app.js`.
- Business Value: conversion-first Apex visual system with clearer hierarchy, throne event signaling, and faster decision scan on desktop/mobile.
- Read/Write Isolation Review: Pass. UI layer only reads support APIs and does not write into engine artifacts.
- Bai Ben (Minimalism) Review: Pass. Kept to one static CSS + one static JS without framework coupling.

### [x] S5_SUPPORT_SEO_GEO_COPY_AND_KNOWLEDGE_REFINEMENT
- Technical Dependency: `support/lib/content.mjs`, `support/lib/seo.mjs`, `support/server.mjs`.
- Business Value: fixed multilingual content integrity and strengthened machine-readable semantics (`keywords`, localized compliance, intent/ranking metadata).
- Read/Write Isolation Review: Pass. SEO/GEO output remains stateless and read-only.
- Bai Ben (Minimalism) Review: Pass. Reused existing generation path and refined payload contract only.

### [x] S6_LOCAL_OPERATOR_ONE_CLICK_RUNTIME
- Technical Dependency: `scripts/support_run_local.ps1`, `scripts/support_stop_local.ps1`, `package.json`, `support/README.md`, `support/runtime/.gitignore`.
- Business Value: one-command local start/stop for server + worker, reducing operator friction and preview cycle time.
- Read/Write Isolation Review: Pass. Scripts only manage support runtime processes and files.
- Bai Ben (Minimalism) Review: Pass. Two lightweight scripts with no new runtime service.

### [x] S7_THREE_TEMPLATE_STATIC_PREVIEW_SUITE
- Technical Dependency: `support/preview/index.html`, `support/preview/a.html`, `support/preview/b.html`, `support/preview/c.html`, `support/preview/preview.css`, `support/server.mjs`.
- Business Value: decision-ready side-by-side visual direction set (Apex Vault / Crystal Prestige / Neon Ritual) before committing production UI refactor.
- Read/Write Isolation Review: Pass. Preview is read-only static surface and does not alter support runtime data.
- Bai Ben (Minimalism) Review: Pass. One static preview directory + lightweight route mapping.

### [x] S8_VERCEL_SERVERLESS_BRIDGE_AND_GLOBAL_REWRITE
- Technical Dependency: `api/index.mjs`, `vercel.json`, `support/server.mjs`.
- Business Value: migrates support runtime from local long-lived server shape to Vercel-invokable handler path, unblocking production deployment.
- Read/Write Isolation Review: Pass. Request handling remains isolated in support module and is bridged by one serverless entrypoint.
- Bai Ben (Minimalism) Review: Pass. Single bridge function + simple global rewrite contract.

### [x] S9_INTERNAL_CRON_CHAIN_POLL_ENDPOINT
- Technical Dependency: `api/internal/poll-chain.mjs`, `support/server.mjs`, `vercel.json`.
- Business Value: replaces always-on worker dependency with authenticated poll endpoint + Vercel cron schedule for chain state refresh.
- Read/Write Isolation Review: Pass. Internal poll endpoint is write-scoped and protected by secret auth.
- Bai Ben (Minimalism) Review: Pass. Reuses existing chain poll logic without introducing new service layers.

## [BUSINESS_STATUS]

### [x] 雲端加速路線完成第一階段落地（Kaggle 主跑 / Colab 備援）
- Technical Dependency: `cloud/kaggle/*`, `cloud/colab/*`, `scripts/cloud_dispatch.py`.
- Business Value: 筆電 CPU 慢速問題可切換到免費雲端批次訓練，保持 1m-only 矩陣契約不變。

### [x] 監控面板支援本地與雲端雙來源
- Technical Dependency: `monitor/index.html`, `monitor/CLOUD.md`, `engine/artifacts/cloud/cloud_run_manifest.json`.
- Business Value: 可在同一個 Monitor 介面切換查看本地迭代與雲端批次進度。

### [x] 2026-02-28 矩陣訓練收斂並補齊驗證產物
- Technical Dependency: `engine/artifacts/optimization/single/2026-02-28/summary.json`, `engine/artifacts/optimization/single/2026-02-28/validation_report.json`, `engine/artifacts/optimization/single/2026-02-28/deploy_pool.json`.
- Business Value: 主段 `180` 任務完成後，已補齊 validation/deploy 交付面板所需核心檔案；當前快照為 `validation_pass_rate=0.7273`, `deploy_symbols=15`, `deploy_rules=29`, `deploy_avg_alpha_vs_spot=0.3804`。

### [x] 雲端批次派工演練完成（3 批切分）
- Technical Dependency: `scripts/cloud_dispatch.py`, `engine/artifacts/cloud/cloud_run_manifest.json`.
- Business Value: Kaggle 主跑可直接按 `batch 1/3, 2/3, 3/3` 進行，降低單機長跑與中斷風險。

### [x] 前 15 交易標的與歷史 1m 數據完成
- Technical Dependency: `engine/src/universe.py`, `engine/src/ingest_1m.py`, `engine/data/raw/symbol=*/timeframe=1m/*`.
- Business Value: 2020-01-01 至今可直接進行硬擬合，不需再重抓基礎盤。

### [x] 統計顯著性判定已修復
- Technical Dependency: `engine/src/optimization.py`.
- Business Value: 系統不再把「打不贏現貨」誤判為「樣本不足」，回測解讀更精準。

### [x] 目標優先最佳參選擇已上線
- Technical Dependency: `engine/src/optimization.py::_prioritize_objective_candidates`.
- Business Value: 當存在可打贏現貨組合時，最佳參會優先呈現該組合，避免誤導性的次優輸出。

### [x] Phase B 迭代品質門檻達標
- Technical Dependency: `engine/src/iterate_optimize.py`, `engine/src/main.py`.
- Business Value: 一輪即達標並自動收斂；`gated=0.9167`、`ungated=0.9833`、`insufficient=0`。

### [x] 本地審閱面板可直接查看最新結果
- Technical Dependency: `review/index.html`, `engine/artifacts/optimization/single/2026-02-24/summary.json`.
- Business Value: 可即時審閱最終輸出，支援交付前人工品檢。

### [x] 特徵權重與信號來源可視化已上線
- Technical Dependency: `engine/src/optimization.py`, `engine/src/reporting.py`, `review/index.html`.
- Business Value: 可直接查看趨勢/能量/本質/時間懲罰對信號的占比，避免黑盒感。

### [x] 特徵層升級為五大家族並引入流動性自適應特徵
- Technical Dependency: `engine/src/features.py`, `engine/src/run_once.py`, `engine/src/iterate_optimize.py`.
- Business Value: 從低維指標導向升級為 `趨勢/震盪/風險/流動性/時序` 全特徵導向，且新增可追溯的 `feature_registry` 供後續淘汰迭代。
- Evidence: `engine/artifacts/optimization/single/2026-02-26/summary.json` -> `feature_registry`（109 欄）。

### [x] 硬門檻交易次數已改為連續可信度懲罰
- Technical Dependency: `engine/src/optimization.py`, `engine/src/validation.py`.
- Business Value: 不再使用 `trades > 100` 一刀切，改為 soft penalty 評分，降低邊界樣本的先見偏誤。
- Evidence: `rule_competition.rejected_breakdown` 新增 `low_credibility` 且 gated/ungated 仍可正常產出最佳候選。

### [x] 特徵訓練淘汰層（重要度與剪枝候選）已落地
- Technical Dependency: `engine/src/optimization.py`, `engine/src/reporting.py`, `engine/src/types.py`.
- Business Value: 每窗口可輸出 top feature 與 prune candidates，支援「先整合後淘汰」的自動化迭代閉環。
- Evidence: `summary.json` -> `feature_importance_leaderboard` / `feature_pruning_candidates`; `explainability.json` -> `feature_diagnostics`.

### [x] 回測可驗證性提升（事件抽樣 + 無未來資訊審計）
- Technical Dependency: `engine/src/optimization.py`, `engine/src/reporting.py`, `engine/artifacts/optimization/single/2026-02-24/events/*`.
- Business Value: 可人工追蹤模型入場/出場並檢查是否存在未來資訊污染。

### [x] 單指標全量競賽已上線（8 指標）
- Technical Dependency: `engine/src/single_indicators.py`, `engine/src/optimization.py`, `engine/src/run_once.py`, `engine/.env.example`.
- Business Value: 不再侷限 RSI，可直接比較各指標在同窗口下的最佳規則與超額回報。

### [x] 審閱面板改為白話多指標版
- Technical Dependency: `review/index.html`, `review/README.md`, `engine/src/reporting.py`.
- Business Value: 可直接查看「符號 x 指標」矩陣、規則辭典、特徵權重白話標籤，非技術審閱可落地。

### [x] Phase C 驗證淘汰層已上線
- Technical Dependency: `engine/src/validation.py`, `engine/src/run_once.py`, `engine/src/iterate_optimize.py`.
- Business Value: 候選規則不再直接視為可上線策略，先經過可遷移/統計可信/摩擦魯棒性驗證。

### [x] Deploy Pool 最小執行層已上線
- Technical Dependency: `engine/src/validation.py`, `engine/.env.example`.
- Business Value: 每檔最多保留 2 條規則，將策略複雜度壓回可控範圍，符合白賁極簡原則。

### [x] Deploy Pool 已加上 alpha 下限保護
- Technical Dependency: `engine/src/validation.py::_build_deploy_pool`, `engine/artifacts/optimization/single/2026-02-25/deploy_pool.json`.
- Business Value: 上線候選不再出現超額為負的規則，決策更直觀且更貼近「打贏現貨」目標。

### [x] 迭代決策可追溯日誌已上線
- Technical Dependency: `engine/src/iterate_optimize.py`, `engine/artifacts/optimization/single/iterations/*`.
- Business Value: 每輪瓶頸與調參方向可追蹤，避免黑箱式反覆試錯。

### [x] Validation 可獨立重建且已修正雙模式漏算
- Technical Dependency: `engine/src/validation.py`, `engine/src/main.py`, `engine/artifacts/optimization/single/2026-02-25/*`.
- Business Value: `validate` 模式改為優先讀取 `results_by_gate_mode`，避免只驗證 `gated` 的漏算風險；目前 `summary / validation / deploy` run_id 已完全一致。

### [x] 審閱面板升級為一致性防呆 + 白話導覽
- Technical Dependency: `review/index.html`, `review/README.md`.
- Business Value: 可直接看到資料是否同一輪、用四步驟白話理解結果，降低決策誤判與術語障礙。

### [x] 金字塔差異視圖與超矩陣切片已上線
- Technical Dependency: `review/index.html`, `engine/src/reporting.py`, `engine/artifacts/optimization/single/2026-02-25/summary.json`.
- Business Value: 先看宏觀差異（gated vs ungated）再下鑽矩陣，符合人類決策路徑；多維比較可讀性顯著提升。

### [x] 多維矩陣已整合成單一 Atlas 視圖
- Technical Dependency: `review/index.html`, `engine/src/reporting.py`, `engine/artifacts/optimization/single/*/summary.json`.
- Business Value: 以單圖就能比較窗口、幣種、指標、gated/ungated 差異與名次變化，顯著降低審閱成本並提升決策速度。

### [x] 特徵收斂總覽與白話剪枝審閱已上線
- Technical Dependency: `review/index.html`, `review/README.md`, `engine/artifacts/optimization/single/*/summary.json`, `engine/artifacts/optimization/single/*/explainability.json`.
- Business Value: 可直接在前端查看特徵家族貢獻排名、Top 重要度、剪枝候選與白話缺點/改善/優勢摘要，並明確展示「兩根 K 高維特徵」歸屬家族，降低術語門檻與審閱成本。

### [x] 迭代門檻參數化與健康儀表已落地
- Technical Dependency: `engine/src/config.py`, `engine/src/iterate_optimize.py`, `engine/src/reporting.py`, `review/index.html`.
- Business Value: 可直接以門檻驅動迭代停止條件，並在前端用紅綠式指標快速判斷是否達標。
- Evidence: `iter_r1_cbaa4494575e`, `engine/artifacts/optimization/single/iterations/2026-02-26/iteration_20260226T015905Z_6798768a.json`.

### [x] 新合約欄位已完成 smoke 驗證
- Technical Dependency: `engine/artifacts/optimization/single/2026-02-26/*`.
- Business Value: 新增的 `health_dashboard / rank_shift / heatmap payload / indicator overview` 已可被審閱面板讀取，資料契約可用。
- Evidence: `run_id=0ecf1f527d20437186eb5b115e1ea5b9`.

### [x] Feature-Native 六核引擎已完成契約驗證
- Technical Dependency: `engine/src/feature_cores.py`, `engine/src/optimization.py`, `engine/src/reporting.py`, `engine/artifacts/optimization/single/2026-02-26/summary.json`.
- Business Value: 從「指標清單」升級為「訊號核清單」，前端與報告可直接讀 `strategy_mode=feature_native` 與 `signal_cores`，便於後續純特徵化迭代。
- Evidence: `run_id=4745ff586edc4560bdff53db2a450a88`, `strategy_mode=feature_native`.

### [x] 審閱面板升級為雙模式矩陣（單 gate / 雙 gate）
- Technical Dependency: `review/index.html`.
- Business Value: 一張矩陣內即可比較 `gated` 與 `ungated` 的同格差值（Δ alpha），降低審閱切換成本與誤讀。
- Evidence: `matrixMode` 選單 + `deltaCards` + 雙模式 cell（`G/U` + `Δ`）。

### [x] 顯式 15 幣清單與歷史符號容忍機制已落地
- Technical Dependency: `engine/src/config.py`, `engine/src/universe.py`, `engine/src/iterate_optimize.py`, `engine/.env.example`.
- Business Value: 可固定跑 `BTC,ETH,BNB,XRP,ADA,DOGE,LTC,LINK,BCH,TRX,ETC,XLM,EOS,XMR,ATOM`，不再受即時市值與交易狀態變動干擾。
- Evidence: `ENGINE_UNIVERSE_SYMBOLS` 支援顯式覆蓋；`EOSUSDT/XMRUSDT` 已補齊本地 1m parquet。

### [x] Alpha-first Aggressive 監督腳本已上線
- Technical Dependency: `scripts/alpha_supervisor.py`, `engine/README.md`.
- Business Value: 自動補缺資料、套用 aggressive 參數、執行迭代並輸出 alpha 摘要，降低人工操作成本與漏步風險。
- Evidence: `python scripts/alpha_supervisor.py --max-rounds 2`.

### [x] Alpha-first 自適應自治監督器已升級
- Technical Dependency: `scripts/alpha_supervisor.py`.
- Business Value: 每個 cycle 會依 `gated/ungated` 差異、`low_credibility` 拒絕率、validation 表現自動調整 gate 與可信度門檻，最後一輪切回 institutional 驗證定稿。
- Evidence: 新增參數 `--cycles/--target-deploy-symbols/--target-deploy-rules/--target-pass-rate` 與 cycle metrics 輸出。

### [x] Feature-Native 的 trade floor 自適應已修正
- Technical Dependency: `engine/src/iterate_optimize.py`.
- Business Value: 自動監督器調整 `ENGINE_TRADE_FLOOR` 不再被 baseline profile 蓋掉，調參迭代可直接反映到實際回測/驗證行為。
- Evidence: `_clone_config_for_profile` 在 `feature_native` 模式改用 `cfg.trade_floor`。

### [x] 即時監控面板已上線（不用看 log）
- Technical Dependency: `scripts/progress_monitor.py`, `monitor/index.html`, `monitor/README.md`, `engine/artifacts/monitor/live_status.json`.
- Business Value: 可直接白話查看「目前進度、剩餘時間 ETA、近期事件、品質快照」，大幅降低人工監控成本。
- Evidence: `python scripts/progress_monitor.py --interval 2` + `http://localhost:8787/monitor/`。

### [x] 監控面板已加 Symbol 完成熱圖與目標燈號
- Technical Dependency: `scripts/progress_monitor.py`, `monitor/index.html`.
- Business Value: 可即時看每個幣目前完成度（heatmap）與 cycle 目標是否達標（燈號），不需要再解讀技術 log。
- Evidence: `engine/artifacts/monitor/live_status.json` 已有 `symbol_progress` 與 `targets.checks`，前端已可視化。

### [x] 監控面板已改為繁中白話與本地時間
- Technical Dependency: `monitor/index.html`, `monitor/README.md`.
- Business Value: 你可直接用中文讀懂進度與 ETA，且時間以本地顯示，避免 UTC 換算造成判讀錯誤。
- Evidence: 監控頁標題/KPI/表格/按鈕/狀態訊息已中文化；更新時間、預估完成時間、事件時間改為本地時間顯示。

### [x] 監控程序抗鎖檔容錯與訓練自帶啟停已上線
- Technical Dependency: `scripts/progress_monitor.py`, `scripts/alpha_supervisor.py`, `monitor/index.html`.
- Business Value: 即使 Windows 短暫鎖檔也不會讓監控中斷；你只要啟動 supervisor 與刷新頁面，就能持續看到即時進度。
- Evidence: `progress_monitor` 新增重試/退避與不中斷迴圈；`alpha_supervisor` 新增自動啟停 monitor；monitor 前端新增資料過舊警示。

### [ ] Alpha-first 全量六核自治迭代進行中（adaptive cycles）
- Technical Dependency: `scripts/alpha_supervisor.py`, `engine/src/main.py --mode iterate`.
- Business Value: 目標是把全量 15 幣在 `all/360d/90d/30d` 的 `alpha_vs_spot` 推升，並維持可部署池覆蓋。
- Evidence: background run started at `2026-02-28` with log `engine/artifacts/logs/alpha_supervisor_autopilot_20260228_092535.out.log`.

### [ ] ClickHouse 寫回與 SaaS 推播待接續
- Technical Dependency: B11 + B12.
- Business Value: 打通即時服務化交付鏈路。

### [x] 支援競榜站 MVP 已獨立落地（support.leimaitech.com 路徑）
- Technical Dependency: `support/server.mjs`, `support/worker.mjs`, `support/.env.example`, `support/README.md`.
- Business Value: 在主模型訓練期間先行啟動打賞/支持現金流與品牌導流，不等待主站完工。

### [x] 三語 SEO/GEO 資產與機器可讀接口已上線
- Technical Dependency: `support/lib/seo.mjs`, `support/lib/content.mjs`, `/sitemap.xml`, `/robots.txt`, `/llms.txt`, `/api/v1/knowledge`.
- Business Value: 在不違反平台政策前提下最大化冷流量可見度，並為主站 Pro/Elite 提供穩定導流入口。

### [x] 宣言先審後發與廣告位機制已落地
- Technical Dependency: `support/lib/moderation.mjs`, `support/server.mjs` admin endpoints.
- Business Value: 保留高淨值用戶宣言與廣告投放空間，並以先審後發控制品牌與合規風險。

### [x] Support 站點 Apex 視覺版已完成
- Technical Dependency: `support/web/styles.css`, `support/web/app.js`, `support/server.mjs`.
- Business Value: 首屏改為高辨識王座面板，新增即時同步狀態與王座改寫提示，桌機/手機體驗一致。

### [x] 三語內容與 SEO/GEO 已修復
- Technical Dependency: `support/lib/content.mjs`, `support/lib/seo.mjs`, `support/server.mjs`.
- Business Value: 繁中/簡中亂碼已清除，`sitemap.xml`、`robots.txt`、`llms.txt` 與 `knowledge` 端點可直接投入導流。

### [x] 本地一鍵啟停流程已上線
- Technical Dependency: `scripts/support_run_local.ps1`, `scripts/support_stop_local.ps1`, `package.json`.
- Business Value: 以 `npm run support:run-local` / `npm run support:stop-local` 完成本地啟停，縮短迭代週期。

### [x] 三模板示意已上線（待你選版）
- Technical Dependency: `support/preview/*`, `support/server.mjs`, `support/.env.example`.
- Business Value: 可直接用 `http://localhost:4310/preview/a|b|c` 比較三套 UIUX 方向，先決策再做正式落地，避免重工與風格漂移。

### [x] Vercel 建置故障已定位並完成架構修正
- Technical Dependency: `package.json`, `vercel.json`, `api/index.mjs`, `api/internal/poll-chain.mjs`, `support/server.mjs`.
- Business Value: 已移除舊 Next build 依賴造成的 `precompute.ts` 錯誤，改為 Vercel Serverless 可執行形態並加上排程刷新入口。

## Governance Checks

- Read/Write Isolation Verdict: `PASS`
- Bai Ben (Minimalism) Verdict: `PASS`
