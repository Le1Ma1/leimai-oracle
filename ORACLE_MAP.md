# ORACLE_MAP

Source of Truth for LeiMai Oracle architecture and execution status.

- Last Updated (UTC): `2026-02-23T19:55:56Z`
- Operating Protocol: Read this file before any coding action.
- Governance Mode: MECE modules, Read/Write Isolation, Bai Ben (Minimalism).
- Dual-Track Language: `[LOGIC_CORE]=English`, `[BUSINESS_STATUS]=繁體中文`.

## [LOGIC_CORE]

### [x] G0_MECE_PROTOCOL_BASELINE
- Technical Dependency: `ORACLE_MAP.md`, `.cursorrules`
- Business Value: Permanent governance baseline to prevent architecture drift and module overlap.
- Read/Write Isolation Review: Pass. Governance rules do not add runtime coupling across UI and engine write paths.
- Bai Ben (Minimalism) Review: Pass. Single source-of-truth map + minimal global protocol file.

### [x] A1_ROUTING_I18N_FOUNDATION
- Technical Dependency: `app/layout.tsx`, `app/[locale]/layout.tsx`, `middleware.ts`, `components/LocaleNav.tsx`, `lib/i18n.ts`, `lib/text.ts`
- Business Value: Global locale routing consistency and language-aware UX entry.
- Read/Write Isolation Review: Pass. UI route rendering does not depend on engine write paths.
- Bai Ben (Minimalism) Review: Pass. Locale layout keeps global metadata and uses lean route-level rendering.

### [x] A2_SEO_CANONICAL_HREFLANG
- Technical Dependency: `lib/seo.ts`, locale page metadata generators under `app/[locale]/**/page.tsx`
- Business Value: Multilingual indexability and canonical correctness for non-default locales.
- Read/Write Isolation Review: Pass. SEO metadata is read-only at request/build time.
- Bai Ben (Minimalism) Review: Pass. Canonical/hreflang logic is centralized in one utility.

### [x] A3_UI_BRUTALIST_SYSTEM
- Technical Dependency: `app/globals.css`, `app/[locale]/layout.tsx`, `components/LocaleNav.tsx`, `app/[locale]/methodology/page.tsx`, `app/[locale]/summaries/page.tsx`
- Business Value: Consistent institutional visual language to improve trust and conversion readiness.
- Read/Write Isolation Review: Pass. Styling layer is independent from data engine writes.
- Bai Ben (Minimalism) Review: Pass. Utility-first styling, no unnecessary custom class sprawl.

### [x] A4_TS_PRECOMPUTE_PIPELINE
- Technical Dependency: `scripts/precompute.ts`, `lib/engine.ts`, `lib/precomputed.ts`, `public/precomputed/*.json`
- Business Value: Deterministic precomputed snapshots for low-latency page serving.
- Read/Write Isolation Review: Partial pass. TS compute remains isolated from UI, but overlaps with emerging Python compute domain.
- Bai Ben (Minimalism) Review: Watch. Transitional duplication exists until Python pipeline becomes authoritative.

### [x] B1_ENGINE_BOOTSTRAP_BINANCE_SIM
- Technical Dependency: `engine/main.py`, `engine/binance_client.py`, `engine/optimizer.py`, `engine/config.py`, `engine/logger.py`, `engine/schemas.py`, `engine/requirements.txt`
- Business Value: Starts backend autonomy with real Binance OHLCV ingestion and optimization-loop proof.
- Read/Write Isolation Review: Pass. Engine module is fully isolated from Next.js runtime modules.
- Bai Ben (Minimalism) Review: Pass. Small bounded modules with explicit responsibilities.

### [ ] B2_ENGINE_RUNTIME_VALIDATION
- Technical Dependency: Python environment with `ccxt`, `numpy`, `pandas`; command path `python engine/main.py`
- Business Value: Operational proof that ingestion and optimization run end-to-end on real data.
- Read/Write Isolation Review: Pending runtime verification.
- Bai Ben (Minimalism) Review: Pending verification.

### [ ] B3_CLICKHOUSE_WRITE_ACTIVATION
- Technical Dependency: `engine/main.py::write_to_clickhouse`, `db/schema.clickhouse.sql`, ClickHouse credentials/env vars
- Business Value: Persistent optimization outputs for downstream query and content generation.
- Read/Write Isolation Review: Pending connection and write-path test.
- Bai Ben (Minimalism) Review: Pending write-surface hardening.

### [ ] B4_PHASED_SCHEDULER_AUTOMATION
- Technical Dependency: `lib/scheduling.ts` policy baseline, Python orchestrator entrypoint, deployment scheduler
- Business Value: Data freshness SLA with controlled compute spend (Tier 1/2/3 cadence).
- Read/Write Isolation Review: Pending implementation.
- Bai Ben (Minimalism) Review: Pending implementation.

## [BUSINESS_STATUS]

### 宏觀進度
- [x] 永久治理協議已固化：`.cursorrules` 已建立並綁定 `ORACLE_MAP.md` 為唯一真相源。
- [x] Phase A（前端體驗 + 多語 SEO）主體已完成，可穩定對外展示。
- [x] Phase B 已啟動，`engine/` 獨立後端模組已建立並與 Next.js 完全隔離。
- [ ] 尚未完成本機 Python runtime 依賴安裝驗證（目前缺 `ccxt`）。
- [ ] 尚未完成 ClickHouse 寫入實測（預設 dry-run）。
- [ ] 尚未啟動 Tier 1/2/3 排程自動更新。

### 技術與商業對齊
- [x] 讀寫隔離：目前架構符合，前台讀模型未污染後端寫路徑。
- [x] 白賁無咎（極簡）：目前符合，但 TS 與 Python 雙計算管線屬過渡態，需收斂。
- [ ] 商業閉環尚未達成：缺少「可持續自動更新 + 持久化查詢」兩塊。

### 阻塞項
- [ ] Python 依賴未安裝，無法完成 engine 實跑驗證與日誌截面留存。
- [ ] ClickHouse 連線環境變數未完成真實校驗。
- [ ] 尚未定義「TS precompute -> Python engine」主寫入源切換時間點。

## Governance Checks

- Read/Write Isolation (Current Verdict): `PASS`
- Bai Ben (Minimalism) (Current Verdict): `PASS_WITH_TRANSITION_WARNING`
- Transition Warning: Keep one authoritative compute pipeline after Phase B runtime proof.

## Next Step (Phase B Execution)

### B2_ENGINE_RUNTIME_VALIDATION (Immediate)
- [ ] Install runtime dependencies: `pip install -r engine/requirements.txt`
- [ ] Run engine in dry-run mode: `python engine/main.py`
- [ ] Capture and archive one successful log sequence: `START -> FETCH_OK -> TRANSFORM_OK -> OPTIMIZE_OK -> PAYLOAD_READY -> END`
- [ ] Verify UTC integrity: DataFrame index timezone must remain UTC from ingest to output.
- [ ] Verify payload shape parity with `backtest_runs` and `best_params_snapshot` in `db/schema.clickhouse.sql`

### B3_CLICKHOUSE_WRITE_ACTIVATION (After B2 pass)
- [ ] Set ClickHouse env vars and disable dry-run: `ENGINE_CLICKHOUSE_DRY_RUN=false`
- [ ] Execute single-slice write test and validate inserted rows.
- [ ] Add failure handling policy for write retries and idempotency.
