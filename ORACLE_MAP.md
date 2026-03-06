# ORACLE_MAP

Source of Truth for LeiMai Oracle system architecture, governance, and live execution status.

- Last Updated (UTC): `2026-03-07T00:00:00Z`
- Operating Principles: First Principles, MECE decomposition, Read/Write Isolation, Bai Ben (Minimalism).

## [LOGIC_CORE]

### [x] M0_SOVEREIGN_GOVERNANCE_KERNEL
- [LOGIC_CORE] Technical Dependency: `.cursorrules`, `ORACLE_MAP.md`.
- [LOGIC_CORE] Core Rule: no optimization claim without artifact evidence; no deployment promotion without gate compliance.
- [LOGIC_CORE] Business Value: governance remains stable under long-running autonomous iterations.

### [x] M1_LEGACY_ML_PIPELINE_BASELINE
- [LOGIC_CORE] Technical Dependency: `engine/src/*`, `scripts/ml_progress_report.py`, `scripts/btc_phase_runner.py`, `scripts/alpha_supervisor.py`.
- [LOGIC_CORE] Core Rule: causal feature pipeline + validation bundle (WF/CV/PBO/DSR/friction) is mandatory before deploy pool inclusion.
- [LOGIC_CORE] Business Value: training quality is auditable, comparable, and rollback-safe.

### [x] M2_LEGACY_FIRST_EXECUTION_CONTRACT
- [LOGIC_CORE] Technical Dependency: `scripts/btc_phase_runner.py`, `logs/ml_priority_state.json`, `logs/ml_progress_report.json`, `engine/artifacts/monitor/live_status.json`.
- [LOGIC_CORE] Core Rule: if key targets are unmet, legacy track is prioritized and new model promotion is deferred.
- [LOGIC_CORE] Business Value: protects downside while restoring core deployability.

### [x] M3_EXECUTIVE_DASHBOARD_FRONTEND_REBUILD
- [LOGIC_CORE] Technical Dependency: `app/*`, `middleware.js`, `lib/dashboard-data.js`, `lib/locale.js`.
- [LOGIC_CORE] Core Rule: homepage must present real ML telemetry (no static placeholders), strict bilingual (`zh-TW` / `en`), free language switch, and region-aware default locale.
- [LOGIC_CORE] Business Value: CEO sees current risk, progress, and bottlenecks in one view.

### [x] M4_DASHBOARD_DATA_CONTRACT
- [LOGIC_CORE] Technical Dependency: `app/api/dashboard/*`, `lib/dashboard-data.js`.
- [LOGIC_CORE] Core Rule: all dashboard APIs are read-only projections from local artifacts (`ml_progress_report`, `live_status`, `ml_priority_state`).
- [LOGIC_CORE] Business Value: single source of truth for executive and operator decisions.

### [x] M5_REPO_HYGIENE_AND_SIGNAL_DENSITY
- [LOGIC_CORE] Technical Dependency: `.gitignore`, root cleanup patterns (`tmp_*`, zipped temp logs).
- [LOGIC_CORE] Core Rule: keep durable assets and ML evidence; remove disposable temporary dumps.
- [LOGIC_CORE] Business Value: lower operational noise and faster iteration cycles.

### [x] M6_PLATFORM_SYNC_SENTINEL
- [LOGIC_CORE] Technical Dependency: `scripts/platform_sync_probe.py`, `logs/platform_sync_status.json`, `lib/dashboard-data.js`.
- [LOGIC_CORE] Core Rule: deployment validity requires GitHub main SHA == Vercel production SHA and public page marker match.
- [LOGIC_CORE] Business Value: eliminates silent version drift and makes deployment mismatch observable on homepage.

## [BUSINESS_STATUS]

### [x] S0_治理核心已重建
- [BUSINESS_STATUS] 目前已用第一性原理重整治理規則：以「證據驅動、因果安全、可回滾」為最高優先。
- [BUSINESS_STATUS] 影響：後續所有優化都可追溯，不再依賴口語判斷。

### [x] S1_舊模型仍在修復期（legacy_recovery）
- [BUSINESS_STATUS] 來自最新報告：`priority_mode=legacy_recovery`。
- [BUSINESS_STATUS] 核心狀態：驗證與部署覆蓋尚未穩定達標，全窗 alpha 仍是主要卡點。
- [BUSINESS_STATUS] 商業意義：目前應持續集中資源在舊模型恢復，不宜提前放大新模型權重。

### [x] S2_CEO 儀表板策略已落地
- [BUSINESS_STATUS] 前端首頁重建為訓練中樞，聚焦路線圖、門檻檢查、趨勢、角色決策與建議。
- [BUSINESS_STATUS] 已要求雙語自由切換與地區預設語言，降低跨團隊溝通摩擦。

### [x] S3_檔案治理進入高密度模式
- [BUSINESS_STATUS] 不必要暫存檔將持續清理，保留品牌資產與核心治理文檔（`logo.png`, `signature.jpg`, `.cursorrules`, `ORACLE_MAP.md`）。
- [BUSINESS_STATUS] 商業意義：提高專案可維護性，縮短定位問題與交付時間。

### [x] S4_部署同步改為可驗證治理
- [BUSINESS_STATUS] 首頁新增平台同步哨兵，直接顯示「本地/部署/公開頁面」是否一致與失敗原因。
- [BUSINESS_STATUS] 商業意義：CEO 不需再靠人工比對，即可判斷「是不是已上線最新版」。

---

Execution Note
- Every major implementation cycle must update this file with:
  - `[LOGIC_CORE]` in English (technical contract)
  - `[BUSINESS_STATUS]` in Traditional Chinese (business impact)
