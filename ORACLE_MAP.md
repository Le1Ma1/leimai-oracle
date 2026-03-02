# ORACLE_MAP

Source of Truth for LeiMai Oracle architecture and execution status.

- Last Updated (UTC): `2026-03-02T19:22:42Z`
- Operating Protocol: read this file before coding; sync this file after execution.
- Governance Principles: MECE modules, Read/Write Isolation, Bai Ben (Minimalism).

## [LOGIC_CORE]

### [x] G0_PROTOCOL_BASELINE
- Technical Dependency: `ORACLE_MAP.md`, `.cursorrules`
- Business Value: Persistent governance baseline for autonomous implementation.
- Read/Write Isolation Review: Pass.
- Bai Ben (Minimalism) Review: Pass.

### [x] G0_1_SUPERVISOR_TARGET_STABILITY_CONTRACT
- Technical Dependency: `scripts/alpha_supervisor.py`, `scripts/progress_monitor.py`.
- Business Value: supervisor now supports explicit alpha targets and consecutive-hit early-stop (`stable_rounds`) to avoid one-round luck exits.
- Read/Write Isolation Review: Pass. Changes are isolated to local orchestration/monitor scripts.
- Bai Ben (Minimalism) Review: Pass. Added only target controls needed by current optimization contract.

### [x] G0_2_MONITOR_STATE_MACHINE_HARDENING
- Technical Dependency: `scripts/progress_monitor.py`, `monitor/index.html`.
- Business Value: monitor now distinguishes `running/validation/finalizing/stalled/completed`, exposes `stall_reason`, `last_event_age_sec`, and `round.completed` for operational clarity.
- Read/Write Isolation Review: Pass. Monitoring-only contract; no strategy mutation.
- Bai Ben (Minimalism) Review: Pass. Added state fields only; no new runtime service.

### [x] B10_18_ALL_WINDOW_DIAGNOSTICS_CONTRACT
- Technical Dependency: `engine/src/reporting.py`, `engine/artifacts/optimization/single/*/summary.json`.
- Business Value: summary now includes `all_window_diagnostics` (symbol/core alpha contribution, rejection breakdown, symbol-core trade density) to target all-window alpha bottlenecks directly.
- Read/Write Isolation Review: Pass. Pure artifact extension in engine backend.
- Bai Ben (Minimalism) Review: Pass. One focused diagnostics payload reused by review/monitor layers.

### [x] B15_1_ITERATION_OBJECTIVE_BALANCE_AND_DELTA_CONTRACT
- Technical Dependency: `engine/src/iterate_optimize.py`, `engine/artifacts/optimization/single/iterations/*`.
- Business Value: iteration report now emits `objective_balance_score`, `delta_vs_prev_round`, and `stability_streak` to make convergence quality explicit round-by-round.
- Read/Write Isolation Review: Pass. Iteration metadata only; no frontend coupling.
- Bai Ben (Minimalism) Review: Pass. Added lightweight numeric fields to existing report schema.

### [x] B21_CAUSAL_FEATURE_PIPELINE_HARDENING
- Technical Dependency: `engine/src/features.py`, `engine/src/optimization.py`, `engine/src/validation.py`.
- Business Value: removed non-causal fill path (`bfill`), shifted dynamic shock/jump thresholds by one bar, and enforced fold-safe winsorization (`fit(train) -> apply`) in optimization/validation paths.
- Read/Write Isolation Review: Pass. Backend data/feature pipeline only; no frontend runtime mutation.
- Bai Ben (Minimalism) Review: Pass. Surgical changes on existing feature/fusion interfaces.

### [x] B21_1_CAUSAL_FUSION_ONLINE_LAGGED_WEIGHTS
- Technical Dependency: `engine/src/optimization.py::build_fusion_components`.
- Business Value: replaced future-looking `target.shift(-1)` relevance weighting with lagged online correlation weighting using only realized history up to t.
- Read/Write Isolation Review: Pass. Fusion score contract upgraded in-place.
- Bai Ben (Minimalism) Review: Pass. Kept same output keys (`fusion_score/oracle_score/confidence` + family weights).

### [x] B21_2_CAUSAL_ACCEPTANCE_TESTS
- Technical Dependency: `engine/tests/test_causal_contract.py`.
- Business Value: added minimal acceptance suite for no-future features, fold-safe winsor bounds, causal fusion consistency, and purged CV embargo effect.
- Read/Write Isolation Review: Pass. Test-only module.
- Bai Ben (Minimalism) Review: Pass. Single focused test file.

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
- Evidence: `summary.json` now includes `delta_views.gate_delta_by_window`; review renders `??憛榆?啁蜇閬窯.
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
- Evidence: review panel `Unified Matrix Atlas嚗???` with `hmSortFilter`, `hmTimeframeBadge`, G/U pass flags, rank-shift tags, and dual mini-bars in each cell.
- Read/Write Isolation Review: Pass. Static frontend reads existing artifact JSON only.
- Bai Ben (Minimalism) Review: Pass. Reuses one panel and existing payload without new runtime module.

### [x] B10_17_REVIEW_FEATURE_CONVERGENCE_INTELLIGENCE_LAYER
- Technical Dependency: `review/index.html`, `review/README.md`, `engine/src/reporting.py`.
- Business Value: adds feature convergence cockpit (family contribution ranking, top-importance features, prune candidates, plain-language weakness/improvement/advantage insights) and explicit high-dimensional two-bar feature family mapping for faster operator interpretation.
- Evidence: review panel `?孵噩?嗆?蝮質汗嚗振??/ ?? / ?芣?嚗, tables `featureFamilyTable/featureTopTable/featurePruneTable`, and guide block `featureConvergenceGuide`.
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
- Evidence: `review/index.html` includes `matrixMode` selector, delta cards, and dual-cell render (`? alpha`, `G/U` values).
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
- Evidence: toolbar source selector (`?砍 Monitor` / `?脩垢 Manifest`) and schema normalization for `lmo.cloud_run_manifest.v1`.
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

### [x] B19_CLOUD_AUTO_QUALITY_MANIFEST
- Technical Dependency: `scripts/cloud_dispatch.py`.
- Business Value: cloud manifest now auto-populates quality snapshot from optimization artifacts (`summary/validation/deploy`) for monitor-ready decision signals.
- Read/Write Isolation Review: Pass. Reads artifacts and writes one manifest file only.
- Bai Ben (Minimalism) Review: Pass. One flag (`--auto-quality`) added to existing dispatcher, no new service layer.

### [x] B19_1_NOTEBOOK_TOKEN_CLONE_AND_AUTO_QUALITY_WIRING
- Technical Dependency: `cloud/kaggle/runner.ipynb`, `cloud/colab/runner.ipynb`, `cloud/kaggle/env.template`, `cloud/colab/env.template`.
- Business Value: notebooks support private token clone and emit manifest with real quality metrics at batch completion.
- Read/Write Isolation Review: Pass. Notebook runtime only updates backend artifacts and manifest paths.
- Bai Ben (Minimalism) Review: Pass. Reused existing notebook flow and appended minimal operator controls.

### [x] B19_2_CLOUD_CLONE_AUTH_FALLBACK_HARDENING
- Technical Dependency: `cloud/colab/runner.ipynb`, `cloud/kaggle/runner.ipynb`, `cloud/*/env.template`.
- Business Value: clone bootstrap now uses Basic `http.extraHeader` with auth-principal fallback (`x-access-token` + `GITHUB_USERNAME`) and returns actionable diagnostics without token leakage.
- Read/Write Isolation Review: Pass. Only notebook bootstrap path changed.
- Bai Ben (Minimalism) Review: Pass. Existing runner flow retained; authentication hardening added in-place.

### [x] B19_3_COLAB_SECRETS_FIRST_AUTH_BOOTSTRAP
- Technical Dependency: `cloud/colab/runner.ipynb`, `cloud/colab/README.md`.
- Business Value: Colab runner now defaults to `google.colab.userdata.get()` for `GITHUB_TOKEN`/`GITHUB_USERNAME`, with explicit manual fallback and fail-fast diagnostics when token is empty.
- Read/Write Isolation Review: Pass. Bootstrap auth layer only; no compute/strategy path changes.
- Bai Ben (Minimalism) Review: Pass. Reused existing cell structure; added one secrets helper and one runtime guard.

### [x] B19_4_ITERATE_CLI_COMPAT_FIX_FOR_NOTEBOOK_RUNNERS
- Technical Dependency: `cloud/colab/runner.ipynb`, `cloud/kaggle/runner.ipynb`, `cloud/colab/README.md`, `cloud/kaggle/README.md`.
- Business Value: removed unsupported `--skip-ingest` argument from iterate command path and added stderr/stdout tail logging for direct failure diagnostics.
- Read/Write Isolation Review: Pass. Runner shell invocation only; no backend engine logic changed.
- Bai Ben (Minimalism) Review: Pass. Patched existing execution cells and docs without new modules.

### [x] B19_5_BATCH_TOPN_ALIGNMENT_FOR_ITERATE_RUNNER
- Technical Dependency: `cloud/colab/runner.ipynb`, `cloud/kaggle/runner.ipynb`.
- Business Value: batch runners now set `ENGINE_TOP_N` to batch symbol count, preventing `expected=15, got=5` guard failures in split execution mode.
- Read/Write Isolation Review: Pass. Environment wiring only; compute logic untouched.
- Bai Ben (Minimalism) Review: Pass. Added one env assignment in existing batch setup cells.

### [x] B19_6_NOTEBOOK_AUTO_INGEST_AND_VALIDATE_GUARD
- Technical Dependency: `cloud/colab/runner.ipynb`, `cloud/kaggle/runner.ipynb`.
- Business Value: runners now auto-ingest missing raw `1m` symbol data before iterate and skip/guard validate when summary has zero results, with stderr/stdout tails for direct diagnostics.
- Read/Write Isolation Review: Pass. Notebook orchestration only; engine strategy modules unchanged.
- Bai Ben (Minimalism) Review: Pass. Added pre-check + guarded invocation in existing execution cells.

### [x] B20_LOCAL_ONLY_CLOUD_RETIREMENT
- Technical Dependency: removed `cloud/*`, `scripts/cloud_dispatch.py`, `scripts/cloud_data_sync.py`, `monitor/CLOUD.md`; monitor now local-source only.
- Business Value: execution path simplified to deterministic local-only training/review, eliminating remote orchestration drift.
- Read/Write Isolation Review: Pass. No cloud write path remains in runtime entrypoints.
- Bai Ben (Minimalism) Review: Pass. Retired entire unused cloud branch and reduced operator surface.

### [x] B20_1_ARTIFACT_RETENTION_LATEST_PLUS_ITERATIONS
- Technical Dependency: local artifact cleanup under `engine/artifacts/optimization/single`.
- Business Value: retained only latest benchmark set (`2026-02-28`) plus `iterations` decision history, reducing storage noise while preserving audit trail.
- Read/Write Isolation Review: Pass. Cleanup affects artifact cache only.
- Bai Ben (Minimalism) Review: Pass. Historical clutter removed with one clear retention contract.

### [x] W1_OUROBOROS_ROOT_ROUTING_410
- Technical Dependency: `support/server.mjs`, `support/web/ouroboros.css`, `support/web/ouroboros.js`, `api/index.mjs`.
- Business Value: Enforced hard route whitelist: only `/` and `/analysis/*` are public entry routes; all legacy noise paths now return `410 Gone`.
- Read/Write Isolation Review: Pass. Change isolated to web routing and static rendering layer.
- Bai Ben (Minimalism) Review: Pass. Reused existing server runtime; added only one focused route policy.

### [x] W1_1_CANONICAL_ROOT_CONSOLIDATION
- Technical Dependency: `support/lib/seo.mjs`, `support/server.mjs`, `vercel.json`, `api/internal/poll-chain.mjs`.
- Business Value: Canonical is now uniformly fixed to `https://leimaitech.com/`; sitemap/robots aligned to root authority and analysis namespace; legacy cron endpoint decommissioned.
- Read/Write Isolation Review: Pass. SEO and platform config updated without touching engine training pipeline.
- Bai Ben (Minimalism) Review: Pass. Surgical edits to existing config and SEO helpers only.

### [x] W1_2_VERCEL_PRODUCTION_ALIAS_REALIGNMENT
- Technical Dependency: Vercel API (`/v13/deployments`, `/v13/deployments/{id}`, `/v2/aliases`), project `leimai-oracle`.
- Business Value: Production domain `leimaitech.com` is now aligned to latest commit `0aef91c8ece709c6dfef5a04debac7c77919f29f` deployment, eliminating domain drift to stale build.
- Read/Write Isolation Review: Pass. Change applied at deployment control-plane only; no engine data path mutation.
- Bai Ben (Minimalism) Review: Pass. Single forced production deploy + alias verification.

### [x] B22_SUPABASE_PHASE1_SCHEMA_AND_RLS_BOOTSTRAP
- Technical Dependency: `supabase/schema.sql`.
- Business Value: established ingestion storage contract with `market_liquidations` and `anomaly_events`, plus RLS enabled and service-role full write path.
- Read/Write Isolation Review: Pass. Storage layer added without touching frontend route runtime.
- Bai Ben (Minimalism) Review: Pass. Two core tables only, no extra denormalized replicas.

### [x] B22_1_GITHUB_ACTIONS_INGEST_4H_AND_MARKET_SCRIPT
- Technical Dependency: `.github/workflows/ingest_4h.yml`, `engine/src/ingest_market.py`, `engine/requirements.txt`, `engine/.env.example`.
- Business Value: zero-budget scheduled ingestion now pulls Binance momentum signals every 4h and upserts anomaly/liquidation feed state to Supabase with fault-tolerant exits.
- Read/Write Isolation Review: Pass. Pure backend automation path; no coupling to `support/server.mjs` render layer.
- Bai Ben (Minimalism) Review: Pass. Single workflow + single script; no orchestration sprawl.

### [x] B22_2_PHASE1_SUPABASE_RUNTIME_VERIFICATION
- Technical Dependency: `supabase/schema.sql`, `engine/src/ingest_market.py`, Supabase project `mprzdnlpiginhabgajjh`.
- Business Value: schema applied and ingestion path verified against real Supabase write target; `anomaly_events` now receives live entries from Binance-derived anomalies.
- Read/Write Isolation Review: Pass. Validation performed in backend storage/runtime layer only.
- Bai Ben (Minimalism) Review: Pass. No additional services introduced; verification reused the same ingestion contract.

## [BUSINESS_STATUS]

### [x] 撠?撌脣?? Local-only ?瑁??箇?
- Technical Dependency: `monitor/index.html`, `engine/README.md`, removed `cloud/*` and cloud scripts.
- Business Value: 敺? R2/R3 餈凋誨?芾粥?砍鞈???啗?蝺氬?啣祟?梧?銝??蝡臬?甇亥?甈???撟脫??
### [x] R1 ?Ｙ摰??嗆?靽?蝑
- Technical Dependency: `engine/artifacts/optimization/single/2026-02-28`, `engine/artifacts/optimization/single/iterations`.
- Business Value: ?????啣?典皞?瘙箇???嚗噶?澆翰?祟?梯????餈凋誨??
### [x] Cloud ?寞活撌脣撖怠?祕?釭敹怎嚗? 0 雿?嚗?- Technical Dependency: `scripts/cloud_dispatch.py --auto-quality`, `engine/artifacts/cloud/cloud_run_manifest.json`.
- Business Value: monitor ?舐?亦???`validation_pass_rate`?all_window_alpha_vs_spot`?deploy_symbols/rules/avg_alpha`嚗???閬?????json??
### [x] Colab/Kaggle 隞????摰?蝘???????- Technical Dependency: `cloud/kaggle/runner.ipynb`, `cloud/colab/runner.ipynb`, `cloud/*/README.md`.
- Business Value: ?舐 `GITHUB_TOKEN` ?湔 clone 銝西?摰甈∴??Ｙ?神敺?舐 monitor 撖拚 Round-2??
### [x] Colab clone 憭望?撌脣???Auth Fallback 鈭活靽桀儔
- Technical Dependency: `cloud/colab/runner.ipynb`, `cloud/kaggle/runner.ipynb`.
- Business Value: ??PAT principal 銝摰對?runner ???fallback嚗仃???舐?亙?雿 token scope/owner/repo access嚗?雿?????
### [x] Colab 撌脣???Secrets-First 撽?頝臬?
- Technical Dependency: `cloud/colab/runner.ipynb`, `cloud/colab/README.md`.
- Business Value: ?身敺?Colab Secrets 霈??token嚗??notebook ?? token ?征摮葡隤方?嚗撩?潭??湔 fail-fast ?內鋆? Secret ?迂??
### [x] Colab/Kaggle iterate ???航炊嚗xit 2嚗歇靽桀儔
- Technical Dependency: `cloud/colab/runner.ipynb`, `cloud/kaggle/runner.ipynb`.
- Business Value: ?脩垢隞??銝????CLI ?銝剜迫嚗?憭望????湔?啣?航??? stderr ??嚗葬?剜??艘??
### [x] ?寞活??嚗? 瑼???TopN ?瑼颱?銝?游歇靽桀儔
- Technical Dependency: `cloud/colab/runner.ipynb`, `cloud/kaggle/runner.ipynb`.
- Business Value: 3-way batch ?舐?亥?嚗??◤ `Not enough symbols expected=15 got=5` 銝剜迫??
### [x] ?脩垢?寞活 validate ?函征???撌脣??脣?
- Technical Dependency: `cloud/colab/runner.ipynb`, `cloud/kaggle/runner.ipynb`.
- Business Value: ?交甈∟??朣?runner ?????餈凋誨嚗 summary ?箇征??甇?validate 銝西撓?箏銵?閮嚗??仃?艘??
### [x] ?脩垢?楝蝺??洵銝?挾?賢嚗aggle 銝餉? / Colab ?嚗?- Technical Dependency: `cloud/kaggle/*`, `cloud/colab/*`, `scripts/cloud_dispatch.py`.
- Business Value: 蝑 CPU ?ａ?憿???啣?鞎駁蝡舀甈∟?蝺湛?靽? 1m-only ?拚憟?銝???
### [x] ???Ｘ?舀?砍?蝡舫?靘?
- Technical Dependency: `monitor/index.html`, `monitor/CLOUD.md`, `engine/artifacts/cloud/cloud_run_manifest.json`.
- Business Value: ?臬????Monitor 隞???亦??砍餈凋誨?蝡舀甈⊿脣漲??
### [x] 2026-02-28 ?拚閮毀?嗆?銝西?朣?霅??- Technical Dependency: `engine/artifacts/optimization/single/2026-02-28/summary.json`, `engine/artifacts/optimization/single/2026-02-28/validation_report.json`, `engine/artifacts/optimization/single/2026-02-28/deploy_pool.json`.
- Business Value: 銝餅挾 `180` 隞餃?摰?敺?撌脰?朣?validation/deploy 鈭支??Ｘ???詨?瑼?嚗?翰?抒 `validation_pass_rate=0.7273`, `deploy_symbols=15`, `deploy_rules=29`, `deploy_avg_alpha_vs_spot=0.3804`??
### [x] ?脩垢?寞活瘣曉極瞍毀摰?嚗? ?孵???
- Technical Dependency: `scripts/cloud_dispatch.py`, `engine/artifacts/cloud/cloud_run_manifest.json`.
- Business Value: Kaggle 銝餉??舐?交? `batch 1/3, 2/3, 3/3` ?脰?嚗?雿璈頝?銝剜憸券??
### [x] ??15 鈭斗?璅??風??1m ?豢?摰?
- Technical Dependency: `engine/src/universe.py`, `engine/src/ingest_1m.py`, `engine/data/raw/symbol=*/timeframe=1m/*`.
- Business Value: 2020-01-01 ?喃??舐?仿脰?蝖祆??銝????蝷??
### [x] 蝯梯?憿航??批摰歇靽桀儔
- Technical Dependency: `engine/src/optimization.py`.
- Business Value: 蝟餌絞銝???銝??曇疏?炊?斤?見?砌?頞喋??葫閫???渡移皞?
### [x] ?格??芸??雿喳??豢?撌脖?蝺?- Technical Dependency: `engine/src/optimization.py::_prioritize_objective_candidates`.
- Business Value: ?嗅??典???曇疏蝯????雿喳?????曇府蝯?嚗?炊撠抒?甈∪頛詨??
### [x] Phase B 餈凋誨?釭?瑼駁?璅?- Technical Dependency: `engine/src/iterate_optimize.py`, `engine/src/main.py`.
- Business Value: 銝頛芸??銝西???`gated=0.9167`?ungated=0.9833`?insufficient=0`??
### [x] ?砍撖拚?Ｘ?舐?交???啁???- Technical Dependency: `review/index.html`, `engine/artifacts/optimization/single/2026-02-24/summary.json`.
- Business Value: ?臬?祟?望?蝯撓?綽??舀鈭支??犖撌亙?瑼Ｕ?
### [x] ?孵噩甈??縑??皞閬?撌脖?蝺?- Technical Dependency: `engine/src/optimization.py`, `engine/src/reporting.py`, `review/index.html`.
- Business Value: ?舐?交?隅???賡?/?祈釭/???脩蔑撠縑????嚗??????
### [x] ?孵噩撅文?蝝鈭之摰嗆?銝血??交??扯?拇??孵噩
- Technical Dependency: `engine/src/features.py`, `engine/src/run_once.py`, `engine/src/iterate_optimize.py`.
- Business Value: 敺?蝬剜?璅???蝝 `頞典/?/憸券/瘚?????` ?函敺萄???銝憓餈賣滲??`feature_registry` 靘?蝥?瘙啗翮隞??- Evidence: `engine/artifacts/optimization/single/2026-02-26/summary.json` -> `feature_registry`嚗?09 甈???
### [x] 蝖祇?瑼颱漱?活?詨歇?寧????臭縑摨行蝵?- Technical Dependency: `engine/src/optimization.py`, `engine/src/validation.py`.
- Business Value: 銝?雿輻 `trades > 100` 銝????寧 soft penalty 閰?嚗?雿??見?祉????炊??- Evidence: `rule_competition.rejected_breakdown` ?啣? `low_credibility` 銝?gated/ungated 隞甇?虜?Ｗ?雿喳??
### [x] ?孵噩閮毀瘛掠撅歹???摨西??芣??嚗歇?賢
- Technical Dependency: `engine/src/optimization.py`, `engine/src/reporting.py`, `engine/src/types.py`.
- Business Value: 瘥???頛詨 top feature ??prune candidates嚗?氬??游?敺?瘙啜??芸??翮隞???啜?- Evidence: `summary.json` -> `feature_importance_leaderboard` / `feature_pruning_candidates`; `explainability.json` -> `feature_diagnostics`.

### [x] ?葫?舫?霅扳???鈭辣?賣見 + ?⊥靘?閮祟閮?
- Technical Dependency: `engine/src/optimization.py`, `engine/src/reporting.py`, `engine/artifacts/optimization/single/2026-02-24/events/*`.
- Business Value: ?臭犖撌亥蕭頩斗芋????箏銝行炎?交?血??冽靘?閮情??
### [x] ?格?璅?奎鞈賢歇銝?嚗? ??嚗?- Technical Dependency: `engine/src/single_indicators.py`, `engine/src/optimization.py`, `engine/src/run_once.py`, `engine/.env.example`.
- Business Value: 銝?靘琿? RSI嚗?湔瘥???璅???????雿唾???頞????
### [x] 撖拚?Ｘ?寧?質店憭?璅?
- Technical Dependency: `review/index.html`, `review/README.md`, `engine/src/reporting.py`.
- Business Value: ?舐?交?泵??x ???????冪?詻敺菜??閰望?蝐歹???銵祟?勗?賢??
### [x] Phase C 撽?瘛掠撅文歇銝?
- Technical Dependency: `engine/src/validation.py`, `engine/src/run_once.py`, `engine/src/iterate_optimize.py`.
- Business Value: ?閬?銝??湔閬?臭?蝺??伐?????瑞宏/蝯梯??臭縑/?拇擳舀??折?霅?
### [x] Deploy Pool ?撠銵惜撌脖?蝺?- Technical Dependency: `engine/src/validation.py`, `engine/.env.example`.
- Business Value: 瘥??憭???2 璇???撠??亥??漲憯??舀蝭?嚗泵?鞈扔蝪∪???
### [x] Deploy Pool 撌脣?銝?alpha 銝?靽風
- Technical Dependency: `engine/src/validation.py::_build_deploy_pool`, `engine/artifacts/optimization/single/2026-02-25/deploy_pool.json`.
- Business Value: 銝??銝??箇頞??箄?????瘙箇??渡閫銝鞎潸???韐鞎具璅?
### [x] 餈凋誨瘙箇??航蕭皞舀隤歇銝?
- Technical Dependency: `engine/src/iterate_optimize.py`, `engine/artifacts/optimization/single/iterations/*`.
- Business Value: 瘥憚?園?矽??餈質馱嚗??蝞勗???閰阡??
### [x] Validation ?舐蝡?撱箔?撌脖耨甇??璅∪?瞍?
- Technical Dependency: `engine/src/validation.py`, `engine/src/main.py`, `engine/artifacts/optimization/single/2026-02-25/*`.
- Business Value: `validate` 璅∪??寧?芸?霈??`results_by_gate_mode`嚗?撽? `gated` ??蝞◢?迎??桀? `summary / validation / deploy` run_id 撌脣??其??氬?
### [x] 撖拚?Ｘ???箔??湔折??+ ?質店撠汗
- Technical Dependency: `review/index.html`, `review/README.md`.
- Business Value: ?舐?亦??啗???血?銝頛芥?郊撽閰梁?閫??????瘙箇?隤文??隤?蝷?
### [x] ??憛榆?啗???頞????歇銝?
- Technical Dependency: `review/index.html`, `engine/src/reporting.py`, `engine/artifacts/optimization/single/2026-02-25/summary.json`.
- Business Value: ??摰?撌桃嚗ated vs ungated嚗?銝?拚嚗泵?犖憿捱蝑楝敺?憭雁瘥??航??折＊????
### [x] 憭雁?拚撌脫???桐? Atlas 閬?
- Technical Dependency: `review/index.html`, `engine/src/reporting.py`, `engine/artifacts/optimization/single/*/summary.json`.
- Business Value: 隞亙?停?賣?頛???馳蝔柴?璅ated/ungated 撌桃??甈∟???憿航???撖拚?銝行??捱蝑漲??
### [x] ?孵噩?嗆?蝮質汗?閰勗?祟?勗歇銝?
- Technical Dependency: `review/index.html`, `review/README.md`, `engine/artifacts/optimization/single/*/summary.json`, `engine/artifacts/optimization/single/*/explainability.json`.
- Business Value: ?舐?亙?垢?亦??孵噩摰嗆?鞎Ｙ???op ??摨艾??閰梁撩暺??孵?/?芸??嚗蒂?Ⅱ撅內???K 擃雁?孵噩?飛撅砍振????銵??瑼餉?撖拚???
### [x] 餈凋誨?瑼餃??詨??摨瑕?銵典歇?賢
- Technical Dependency: `engine/src/config.py`, `engine/src/iterate_optimize.py`, `engine/src/reporting.py`, `review/index.html`.
- Business Value: ?舐?乩誑?瑼駁??翮隞??甇Ｘ?隞塚?銝血?垢?函?蝬???敹恍?瑟?阡?璅?- Evidence: `iter_r1_cbaa4494575e`, `engine/artifacts/optimization/single/iterations/2026-02-26/iteration_20260226T015905Z_6798768a.json`.

### [x] ?啣?蝝?雿歇摰? smoke 撽?
- Technical Dependency: `engine/artifacts/optimization/single/2026-02-26/*`.
- Business Value: ?啣???`health_dashboard / rank_shift / heatmap payload / indicator overview` 撌脣鋡怠祟?梢?輯???鞈?憟??舐??- Evidence: `run_id=0ecf1f527d20437186eb5b115e1ea5b9`.

### [x] Feature-Native ?剜撘?撌脣???蝝?霅?- Technical Dependency: `engine/src/feature_cores.py`, `engine/src/optimization.py`, `engine/src/reporting.py`, `engine/artifacts/optimization/single/2026-02-26/summary.json`.
- Business Value: 敺?璅??柴?蝝???皜???垢???湔霈 `strategy_mode=feature_native` ??`signal_cores`嚗噶?澆?蝥??孵噩?翮隞??- Evidence: `run_id=4745ff586edc4560bdff53db2a450a88`, `strategy_mode=feature_native`.

### [x] 撖拚?Ｘ???粹?璅∪??拚嚗 gate / ??gate嚗?- Technical Dependency: `review/index.html`.
- Business Value: 銝撘萇???喳瘥? `gated` ??`ungated` ???澆榆?潘?? alpha嚗???撖拚????炊霈??- Evidence: `matrixMode` ?詨 + `deltaCards` + ?芋撘?cell嚗G/U` + `?`嚗?
### [x] 憿臬? 15 撟???株?甇瑕蝚西?摰孵?璈撌脰??- Technical Dependency: `engine/src/config.py`, `engine/src/universe.py`, `engine/src/iterate_optimize.py`, `engine/.env.example`.
- Business Value: ?臬摰? `BTC,ETH,BNB,XRP,ADA,DOGE,LTC,LINK,BCH,TRX,ETC,XLM,EOS,XMR,ATOM`嚗????單?撣潸?鈭斗?????僕?整?- Evidence: `ENGINE_UNIVERSE_SYMBOLS` ?舀憿臬?閬?嚗EOSUSDT/XMRUSDT` 撌脰?朣??1m parquet??
### [x] Alpha-first Aggressive ???單撌脖?蝺?- Technical Dependency: `scripts/alpha_supervisor.py`, `engine/README.md`.
- Business Value: ?芸?鋆撩鞈?????aggressive ??銵翮隞?蒂頛詨 alpha ??嚗?雿犖撌交?雿??祈?瞍郊憸券??- Evidence: `python scripts/alpha_supervisor.py --max-rounds 2`.

### [x] Alpha-first ?芷?瘝餌??撌脣?蝝?- Technical Dependency: `scripts/alpha_supervisor.py`.
- Business Value: 瘥?cycle ?? `gated/ungated` 撌桃?low_credibility` ???alidation 銵函?芸?隤踵 gate ?靽∪漲?瑼鳴??敺?頛芸???institutional 撽?摰阮??- Evidence: ?啣?? `--cycles/--target-deploy-symbols/--target-deploy-rules/--target-pass-rate` ??cycle metrics 頛詨??
### [x] Feature-Native ??trade floor ?芷?歇靽格迤
- Technical Dependency: `engine/src/iterate_optimize.py`.
- Business Value: ?芸????刻矽??`ENGINE_TRADE_FLOOR` 銝?鋡?baseline profile ??嚗矽?翮隞??湔???啣祕??皜?撽?銵??- Evidence: `_clone_config_for_profile` ??`feature_native` 璅∪??寧 `cfg.trade_floor`??
### [x] ?單????Ｘ撌脖?蝺?銝??log嚗?- Technical Dependency: `scripts/progress_monitor.py`, `monitor/index.html`, `monitor/README.md`, `engine/artifacts/monitor/live_status.json`.
- Business Value: ?舐?亦閰望??脣漲?擗???ETA????隞嗚?鞈芸翰?扼?憭批???鈭箏極?????- Evidence: `python scripts/progress_monitor.py --interval 2` + `http://localhost:8787/monitor/`??
### [x] ???Ｘ撌脣? Symbol 摰??勗??璅???- Technical Dependency: `scripts/progress_monitor.py`, `monitor/index.html`.
- Business Value: ?臬??瘥馳?桀?摰?摨佗?heatmap嚗? cycle ?格??臬??嚗???嚗??閬?閫???銵?log??- Evidence: `engine/artifacts/monitor/live_status.json` 撌脫? `symbol_progress` ??`targets.checks`嚗?蝡臬歇?航???
### [x] ???Ｘ撌脫?箇?銝剔閰梯??砍??
- Technical Dependency: `monitor/index.html`, `monitor/README.md`.
- Business Value: 雿?湔?其葉???脣漲??ETA嚗???隞交?圈＊蝷綽??踹? UTC ?????方??航炊??- Evidence: ????憿?KPI/銵冽/??/????臬歇銝剜????湔????隡啣?????隞嗆???箸?唳??＊蝷箝?
### [x] ??蝔???瑼捆?航?閮毀?芸葆??撌脖?蝺?- Technical Dependency: `scripts/progress_monitor.py`, `scripts/alpha_supervisor.py`, `monitor/index.html`.
- Business Value: ?喃蝙 Windows ?剜??銋?????銝剜嚗??芾??? supervisor ??圈??ｇ?撠梯????單??脣漲??- Evidence: `progress_monitor` ?啣??岫/??輯?銝葉?瑁艘??`alpha_supervisor` ?啣??芸??? monitor嚗onitor ?垢?啣?鞈???霅衣內??
### [ ] Alpha-first ?券??剜?芣祥餈凋誨?脰?銝哨?adaptive cycles嚗?- Technical Dependency: `scripts/alpha_supervisor.py`, `engine/src/main.py --mode iterate`.
- Business Value: ?格??舀??券? 15 撟? `all/360d/90d/30d` ??`alpha_vs_spot` ?典?嚗蒂蝬剜??舫蝵脫?閬???- Evidence: background run started at `2026-02-28` with log `engine/artifacts/logs/alpha_supervisor_autopilot_20260228_092535.out.log`.

### [ ] ClickHouse 撖怠???SaaS ?冽敺蝥?- Technical Dependency: B11 + B12.
- Business Value: ?????鈭支??楝??
### [x] ?舀蝡嗆?蝡?MVP 撌脩蝡?堆?support.leimaitech.com 頝臬?嚗?- Technical Dependency: `support/server.mjs`, `support/worker.mjs`, `support/.env.example`, `support/README.md`.
- Business Value: ?其蜓璅∪?閮毀????????/?舀??暸?瘚???撠?嚗?蝑?銝餌?摰極??
### [x] 銝? SEO/GEO 鞈???典霈?亙撌脖?蝺?- Technical Dependency: `support/lib/seo.mjs`, `support/lib/content.mjs`, `/sitemap.xml`, `/robots.txt`, `/llms.txt`, `/api/v1/knowledge`.
- Business Value: ?其???撟喳?輻???銝?憭批??瑟??閬漲嚗蒂?箔蜓蝡?Pro/Elite ??蝛拙?撠??亙??
### [x] 摰???祟敺?誨??璈撌脰??- Technical Dependency: `support/lib/moderation.mjs`, `support/server.mjs` admin endpoints.
- Business Value: 靽?擃楊?潛?嗅恐閮?誨???曄征??銝虫誑?祟敺?批????閬◢?芥?
### [x] Support 蝡? Apex 閬死?歇摰?
- Technical Dependency: `support/web/styles.css`, `support/web/app.js`, `support/server.mjs`.
- Business Value: 擐??寧擃儘霅?摨折?選??啣??單??郊????漣?孵神?內嚗?璈???擃?銝?氬?
### [x] 銝??批捆??SEO/GEO 撌脖耨敺?- Technical Dependency: `support/lib/content.mjs`, `support/lib/seo.mjs`, `support/server.mjs`.
- Business Value: 蝜葉/蝪∩葉鈭Ⅳ撌脫??歹?`sitemap.xml`?robots.txt`?llms.txt` ??`knowledge` 蝡舫??舐?交??亙?瘚?
### [x] ?砍銝?萄???蝔歇銝?
- Technical Dependency: `scripts/support_run_local.ps1`, `scripts/support_stop_local.ps1`, `package.json`.
- Business Value: 隞?`npm run support:run-local` / `npm run support:stop-local` 摰??砍??嚗葬?剛翮隞?望???
### [x] 銝芋?輻內?歇銝?嚗?雿??
- Technical Dependency: `support/preview/*`, `support/server.mjs`, `support/.env.example`.
- Business Value: ?舐?亦 `http://localhost:4310/preview/a|b|c` 瘥?銝? UIUX ?孵?嚗?瘙箇???甇???賢嚗??撌亥?憸冽瞍宏??
### [x] Vercel 撱箇蔭??撌脣?雿蒂摰??嗆?靽格迤
- Technical Dependency: `package.json`, `vercel.json`, `api/index.mjs`, `api/internal/poll-chain.mjs`, `support/server.mjs`.
- Business Value: 撌脩宏?方? Next build 靘陷????`precompute.ts` ?航炊嚗??Vercel Serverless ?臬銵耦?蒂?????瑟?亙??
### [x] 監督器門檻強化已落地
- Technical Dependency: `scripts/alpha_supervisor.py`, `scripts/progress_monitor.py`.
- Business Value: 已加入可配置 `target_all_alpha`、`target_deploy_alpha` 與 `stable_rounds`，並同步到監控面板目標檢核，避免單輪偶發達標誤判。

### [ ] 本地嚴格 R2 自動迭代進行中
- Technical Dependency: `scripts/alpha_supervisor.py --skip-ingest --cycles 8 --max-rounds 2 --target-pass-rate 0.70 --target-deploy-symbols 12 --target-deploy-rules 24 --target-all-alpha 0.00 --target-deploy-alpha 0.00 --stable-rounds 2`.
- Business Value: 以 15 檔、1m-only、四窗口（all/360d/90d/30d）持續迭代，目標是取得可穩定連續達標的 deploy 結果。
- Evidence: active processes `alpha_supervisor` PID `11564`, `engine iterate` PID `14100`; log `engine/artifacts/logs/alpha_supervisor_autopilot_20260228_233701.out.log`.

### [x] 監控狀態機與完成判定已修補
- Technical Dependency: `scripts/progress_monitor.py`, `monitor/index.html`.
- Business Value: 已可清楚辨識 `completed/stalled`，並回報卡住原因，避免「其實跑完但看起來還在跑」的誤判。

### [x] all-window 診斷載荷已進 summary
- Technical Dependency: `engine/src/reporting.py`, `engine/artifacts/optimization/single/2026-03-01/summary.json`.
- Business Value: 可直接看 all-window 拖累來源（symbol/core）與拒絕原因分解，後續調參可針對瓶頸而非盲目擴參。
- Evidence: run_id `ca5803af15c945e38ef0e45ecefe02a8` has `all_window_diagnostics`.

### [x] iteration 回報新增收斂品質欄位
- Technical Dependency: `engine/src/iterate_optimize.py`, `engine/artifacts/optimization/single/iterations/2026-03-01/iteration_20260301T052107Z_a976e477.json`.
- Business Value: 每輪可追蹤 `objective_balance_score`、`delta_vs_prev_round`、`stability_streak`，利於自動迭代監督。

### [ ] 新一輪本地自動迭代已重啟（監督中）
- Technical Dependency: `scripts/alpha_supervisor.py --skip-ingest --cycles 6 --max-rounds 2 --target-pass-rate 0.70 --target-deploy-symbols 12 --target-deploy-rules 24 --target-all-alpha 0.00 --target-deploy-alpha 0.00 --stable-rounds 2`.
- Business Value: 以最新監控/診斷契約持續迭代，目標修復 all-window alpha 並維持 deploy 穩定。
- Evidence: active processes `alpha_supervisor` PID `11292`, `engine iterate` PID `30416`; log `engine/artifacts/logs/alpha_supervisor_autopilot_20260301_132144.out.log`.

### [x] 因果重構已落地並重新啟動本地迭代
- Technical Dependency: `engine/src/features.py`, `engine/src/optimization.py`, `engine/src/validation.py`, `scripts/progress_monitor.py`.
- Business Value: 特徵/融合/驗證路徑已切換為因果版，監控輸出新增 `causal_contract`，避免舊 run 的 time-travel 偏差繼續污染決策。
- Evidence: test `python -m unittest engine.tests.test_causal_contract -v` 全數通過；active run `iter_r1_06529f4be8bd`; PIDs `alpha_supervisor=4704`, `iterate=19364`, `progress_monitor=18136`.

### [x] B21_3_SUPERVISOR_SYMBOL_OVERRIDE_RUNTIME
- Technical Dependency: `scripts/alpha_supervisor.py`.
- Business Value: supervisor supports explicit `--symbols` selection and derives `ENGINE_UNIVERSE_SYMBOLS` / `ENGINE_TOP_N` from that list, removing hardcoded 15-symbol override.
- Read/Write Isolation Review: Pass. Runtime orchestration only.
- Bai Ben (Minimalism) Review: Pass. Single-argument extension; no engine strategy mutation.

### [x] B21_4_BTC_PRIORITY_SWITCH_RUNTIME
- Technical Dependency: `scripts/alpha_supervisor.py`, `scripts/progress_monitor.py`, `engine/artifacts/monitor/live_status.json`.
- Business Value: execution lane switched from 4-symbol run to BTC-first single-symbol training lane to accelerate production-readiness for BTC.
- Read/Write Isolation Review: Pass. Changes are orchestration/runtime-process switching only; no frontend or strategy-code mutation in this step.
- Bai Ben (Minimalism) Review: Pass. Reused existing supervisor/monitor contracts and only changed runtime scope/targets.

### [x] B21_5_VALIDATE_REBUILD_SYNC_FOR_BTC_R1
- Technical Dependency: `engine/src/main.py --mode validate`, `engine/artifacts/optimization/single/2026-03-02/*`.
- Business Value: rebuilt validation/deploy artifacts from BTC R1 summary to remove stale run mismatch and recover decision-consistent metrics.
- Read/Write Isolation Review: Pass. Backend artifact regeneration only; no UI/runtime code mutation.
- Bai Ben (Minimalism) Review: Pass. Reused existing validate-only mode without introducing new modules.

### [x] B21_6_BTC_PHASE_RUNNER_AUTOPILOT
- Technical Dependency: `scripts/btc_phase_runner.py`, `scripts/alpha_supervisor.py`, `engine/src/main.py --mode validate`.
- Business Value: added a deterministic phase orchestrator for BTC that auto-sequences `bootstrap_recovery -> bootstrap_plus -> institutional_55 -> institutional_65 -> institutional_70` using artifact-aligned validation/deploy metrics.
- Read/Write Isolation Review: Pass. Orchestration-only; no strategy core or frontend code mutation.
- Bai Ben (Minimalism) Review: Pass. Reuses existing supervisor and validate-only paths with one thin coordinator script.

### [x] 4 檔訓練模式已切換（BTC/ETH/BNB/XRP）
- Technical Dependency: `scripts/alpha_supervisor.py --symbols BTCUSDT,ETHUSDT,BNBUSDT,XRPUSDT ...`, `engine/artifacts/monitor/live_status.json`.
- Business Value: 訓練宇宙從 15 檔縮到 4 檔，`tasks_total` 由 180 降為 48，便於快速迭代與驗證。
- Evidence: active run `iter_r1_26d063ae33e3`; monitor shows `symbols_total=4`, `tasks_total=48`; targets aligned to `deploy_symbols>=4`, `deploy_rules>=8`.

### [x] BTC 優先訓練模式已啟動（單檔先上架）
- Technical Dependency: `scripts/alpha_supervisor.py --symbols BTCUSDT --skip-ingest --cycles 6 --max-rounds 2 --target-pass-rate 0.70 --target-deploy-symbols 1 --target-deploy-rules 4 --target-all-alpha 0.00 --target-deploy-alpha 0.00 --stable-rounds 2 --with-monitor --monitor-interval 2`, `engine/artifacts/monitor/live_status.json`.
- Business Value: 依產品策略改為 BTC 先行，將單輪任務縮至 `tasks_total=12`，優先取得可上架 BTC deploy 候選，再擴展 ETH。
- Evidence: active run `iter_r1_2d737fcad4b6`; monitor shows `symbols_total=1`, `tasks_total=12`, `target_deploy_symbols=1`, `target_deploy_rules=4`.
- 讀寫分離檢查: 通過（僅後端運行時調度變更，前端與資料契約未被污染）。
- 白賁極簡檢查: 通過（復用既有監督/監控流程，僅調整符號範圍與目標門檻）。

### [x] BTC R1 驗證重建完成，決策基準已校正
- Technical Dependency: `python -m engine.src.main --mode validate --summary-path engine/artifacts/optimization/single/2026-03-02/summary.json`.
- Business Value: 同步完成 BTC R1 的 validation/deploy，消除先前「summary 新、validation 舊」的決策污染；目前基準為 `pass_rate=0.3571`, `deploy_symbols=1`, `deploy_rules=2`。
- Evidence: `validation_report.json` 與 `deploy_pool.json` 皆對齊 `run_id=iter_r1_2d737fcad4b6`。
- 讀寫分離檢查: 通過（僅產物重建，無前端與策略代碼改動）。
- 白賁極簡檢查: 通過（使用既有 validate-only 模式，無新增模組）。

### [x] BTC Bootstrap 續跑已啟動（先可上架再強化）
- Technical Dependency: `scripts/alpha_supervisor.py --symbols BTCUSDT --skip-ingest --cycles 3 --max-rounds 2 --target-pass-rate 0.40 --target-deploy-symbols 1 --target-deploy-rules 2 --target-all-alpha -20.00 --target-deploy-alpha -1.00 --stable-rounds 1 --with-monitor --monitor-interval 2`, `engine/artifacts/monitor/live_status.json`.
- Business Value: 先衝可上架候選（非空 deploy pool + 正向部署品質），縮短等待時間，再銜接 institutional 門檻。
- Evidence: active run `iter_r1_afc805b2eb0b`; monitor targets updated to bootstrap profile.
- 讀寫分離檢查: 通過（純運行時調度參數變更）。
- 白賁極簡檢查: 通過（重用既有監督流程，僅切換門檻配置）。

### [x] BTC 三段式自動升壓執行器已上線
- Technical Dependency: `scripts/btc_phase_runner.py --wait-existing --monitor-interval 2 --poll-sec 20`, `engine/artifacts/logs/btc_phase_runner_*.{out,err}.log`.
- Business Value: 由系統自動判斷每階段是否達標，先求可上架穩定再升級機構門檻，避免人工盯盤與手動切參。
- Evidence: phase-runner process active (`btc_phase_runner.py`), currently waiting/handling `validate` sync before next phase launch.
- 讀寫分離檢查: 通過（只調度流程，未污染前端與資料契約）。
- 白賁極簡檢查: 通過（沿用既有 artifacts 作判斷，無新增資料格式）。
### [x] 根網域 Ouroboros 新中樞與 410 清場完成
- Technical Dependency: `support/server.mjs`, `support/lib/seo.mjs`, `support/web/ouroboros.css`, `support/web/ouroboros.js`, `vercel.json`, `api/internal/poll-chain.mjs`.
- Business Value: `leimaitech.com` 已回收為唯一權威入口；`/analysis/*` 作為 pSEO 矩陣命名空間；舊路徑統一 410，避免舊實體訊號污染 GEO/SEO。
- Evidence: route contract verified locally (`/`=200, `/analysis/`=200, `/analysis/btc-2020-now-regime`=200, `/en`=410, canonical fixed to `https://leimaitech.com/`).
- 讀寫分離檢查: 通過（僅網站路由與 SEO 層變更，未動量化引擎訓練管線）。
- 白賁極簡檢查: 通過（沿用現有 serverless 入口，最小化新增檔案）。

### [x] Vercel 生產環境漂移修復完成（Domain Drift -> 最新 Commit）
- Technical Dependency: Vercel project `leimai-oracle`, deployment `dpl_HqF8jjVChJcq4LURoV8QsNN3MJXE`, aliases API.
- Business Value: `leimaitech.com` 從舊部署 `f4bf0b59...` 漂移狀態恢復到最新 `0aef91c...`；線上已生效新路由與 canonical 策略。
- Evidence: alias `leimaitech.com -> dpl_HqF8jjVChJcq4LURoV8QsNN3MJXE`; live checks `/`=200, `/analysis/`=200, `/analysis/btc-2020-now-regime`=200, `/en`=410, canonical=`https://leimaitech.com/`.
- 讀寫分離檢查: 通過（僅部署控制層操作）。
- 白賁極簡檢查: 通過（未新增服務，僅切換到正確部署）。

### [x] Phase 1 數據流水線骨架完成（Supabase + GitHub Actions + Python Ingest）
- Technical Dependency: `supabase/schema.sql`, `.github/workflows/ingest_4h.yml`, `engine/src/ingest_market.py`, `engine/requirements.txt`, `engine/.env.example`.
- Business Value: 已建立 4 小時定時抓取與異常寫入契約；`market_liquidations`/`anomaly_events` 可作為後續 AI 報告與 `/analysis/*` 真實內容來源。
- Evidence: local run `python -m engine.src.ingest_market` completed with resilient logs; anomalies detected; force-orders unauthorized path handled without pipeline interruption.
- 讀寫分離檢查: 通過（純後端 ingestion，不污染前端展示層）。
- 白賁極簡檢查: 通過（只新增最小必要腳本與 workflow）。

### [x] Phase 1 實庫驗證完成（anomaly_events 已落地）
- Technical Dependency: Supabase DB (`mprzdnlpiginhabgajjh`), `engine/src/ingest_market.py`.
- Business Value: 透過 service_role 寫入實測成功，`anomaly_events` 已有真實新資料；現階段 `forceOrders` 在當前環境回 `401`，系統以 `liquidation_feed_unavailable` 低嚴重度事件降級運行。
- Evidence: query result `anomaly_events=6`, `market_liquidations=0` after runtime ingestion at `2026-03-02T19:22Z`.
- 讀寫分離檢查: 通過（僅後端數據層與排程層）。
- 白賁極簡檢查: 通過（採用單一路徑降級策略，不引入備援服務）。

### [ ] GitHub Actions Secrets 自動寫入受 PAT 權限阻擋（待補權限或手動設置）
- Technical Dependency: GitHub REST `/actions/secrets/*`, provided fine-grained PAT.
- Business Value: 目前 PAT 對 repository secrets API 返回 `403 Resource not accessible by personal access token`，因此需補 `Actions secrets write` 權限或由你在 UI 手動新增兩個 secrets。
- Required: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.

## Governance Checks

- Read/Write Isolation Verdict: `PASS`
- Bai Ben (Minimalism) Verdict: `PASS`

