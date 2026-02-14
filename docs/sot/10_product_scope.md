# MDP v0.1 Product Scope (SoT)

Document ID: `SOT-10`  
Version: `v0.1`  
Status: `Approved baseline`

## 1) Scope and hard locks

### PS-001 Default ranking tab
- Input: User opens rankings page without tab parameter.
- Output: `risk_adjusted` tab is selected by default; `roi` appears as secondary tab.
- Boundary: Missing tab, invalid tab value, legacy alias values.
- Acceptance method: Open page with `tab` absent and invalid values; confirm default is `risk_adjusted` and `roi` is selectable.

### PS-002 Fixed universe (placeholder list, size constrained)
- Input: Ranking request with no symbol filter, or with symbol filter.
- Output: Results are limited to fixed universe list only.
- Boundary: Universe size must stay between 20 and 30; duplicates and invalid symbols are rejected from the source list.
- Acceptance method: Verify list length and uniqueness; test non-member symbol request is excluded.

Current placeholder universe (`24` items, owner to replace later):
`ASSET_01`, `ASSET_02`, `ASSET_03`, `ASSET_04`, `ASSET_05`, `ASSET_06`, `ASSET_07`, `ASSET_08`, `ASSET_09`, `ASSET_10`, `ASSET_11`, `ASSET_12`, `ASSET_13`, `ASSET_14`, `ASSET_15`, `ASSET_16`, `ASSET_17`, `ASSET_18`, `ASSET_19`, `ASSET_20`, `ASSET_21`, `ASSET_22`, `ASSET_23`, `ASSET_24`.

### PS-003 Timeframe enum
- Input: `tf` query parameter.
- Output: Only `1m`, `5m`, `15m`, `1h`, `4h`, `1d` are accepted.
- Boundary: Empty, mixed-case, unsupported values.
- Acceptance method: Enum validation test matrix for valid and invalid `tf`.

### PS-004 Window enum
- Input: `window` query parameter.
- Output: Only `7D`, `30D`, `180D`, `All` are accepted.
- Boundary: Empty, wrong case, unsupported values.
- Acceptance method: Enum validation test matrix for valid and invalid `window`.

### PS-005 Modality v0
- Input: Ranking/summaries request.
- Output: Modality is fixed to `technical_indicators_plus_price_volume`.
- Boundary: Any request attempting other modality values in v0.
- Acceptance method: Confirm response `modality` field stays fixed to v0 value.

### PS-006 Variant API contract (A1) and UI default
- Input: Ranking request for a fixed `(symbol, tf, window, modality)` with optional query param `variant`.
- Output:
  - `variant` request enum is `long|short|long_short`.
  - If `variant` is missing, selected variant defaults to `long`.
  - Response returns metrics for exactly one selected variant (the requested/default `variant`).
  - Response must also include `best_variant` computed from all three variants for the same `(symbol, tf, window, modality)`.
  - Response must include `best_variant_scores` with `risk_adjusted_score`, `roi_score`, `drawdown`, `trade_count`.
  - UI default view is Long-only and shows Best Variant badge with variant switch controls.
- Boundary:
  - Missing/invalid `variant`.
  - Equal `risk_adjusted_score` across variants.
  - Further tie on `drawdown` and `trade_count`.
- Acceptance method:
  - Verify missing `variant` defaults to `long`.
  - Verify each requested `variant` returns that variant metrics.
  - Verify `best_variant` is argmax of `risk_adjusted_score` across three variants.
  - Apply deterministic tie-break in this order:
    1. Lower `drawdown` wins.
    2. If tie, higher `trade_count` wins.
    3. If tie, fixed order `long > long_short > short`.

## 2) Live-check, cadence, rate-limit, and notification dedupe

### PS-007 Free snapshot cadence
- Input: Free-tier request to snapshot resources.
- Output: Snapshot refresh interval is exactly `6h`.
- Boundary: Requests within same 6-hour window.
- Acceptance method: Compare two reads in-window (same snapshot timestamp) and across window boundary (new timestamp).

### PS-008 Pro/Elite update cadence by timeframe
- Input: Pro/Elite request by `tf`.
- Output: Update cadence mapping is:
  - `1m -> 1m`
  - `5m -> 5m`
  - `15m -> 15m`
  - `1h -> 1h`
  - `4h -> 4h`
  - `1d -> 1d`
- Boundary: Invalid `tf`, missing `tf`.
- Acceptance method: For each valid `tf`, verify update timestamp deltas follow mapping.

### PS-009 Per-member per-minute cap
- Input: Consecutive requests from the same member within one minute.
- Output: Allow up to `N=10`; requests over limit are rate-limited.
- Boundary: Exactly at 10, first request after minute rollover.
- Acceptance method: Send 11 requests in one minute and verify first 10 pass, 11th is limited; verify reset on next minute bucket.

### PS-010 Notification dedupe rule
- Input: Multiple notification triggers with same logical signal.
- Output: At most one notification per dedupe key:
  - `(member_id, channel, proof_id, variant, tf, window, signal_type, minute_bucket)`
- Boundary: Retry events and channel retries with same key.
- Acceptance method: Trigger duplicated events and verify one delivery record per dedupe key.

## 3) Public API contract (docs-only)

### PS-011 Public endpoints and access model
- Input: Anonymous and authorized requests.
- Output:
  - Public read endpoints are `GET /rankings`, `GET /methodology`, `GET /summaries`.
  - `variant` query param allowlist for rankings is `long|short|long_short`; default is `long` when omitted.
  - Locked data is never exposed from public responses.
- Boundary: Unauthorized access to locked resources, invalid `variant` enum.
- Acceptance method: Call endpoints as anonymous and authorized users; validate variant enum/default behavior and confirm no locked fields in public payload.

### PS-012 Response allowlist (required fields)
- Input: Successful public response from rankings/summaries.
- Output: Required fields must be present:
  - `proof_id`
  - `method_version`
  - `tf`
  - `window`
  - `modality`
  - `variant` (selected variant in response)
  - `risk_adjusted_score` (selected variant)
  - `roi_score` (selected variant)
  - `drawdown` (selected variant)
  - `trade_count` (selected variant)
  - `best_variant`
  - `best_variant_scores.risk_adjusted_score`
  - `best_variant_scores.roi_score`
  - `best_variant_scores.drawdown`
  - `best_variant_scores.trade_count`
  - `fee_assumption`
  - `slippage_assumption`
  - `timestamp`
- Boundary:
  - Missing any required field.
  - `best_variant` not in enum.
  - `best_variant_scores` inconsistent with tie-break rule in `PS-006`.
- Acceptance method: Schema assertion across sampled responses plus best-variant correctness/tie-break verification.

### PS-013 Recursive denylist (`locked_data` at any depth)
- Input: Any API payload object tree.
- Output: `locked_data` key must not exist at any depth (root, nested object, array item object).
- Boundary: Deep nesting, mixed arrays/objects, similarly named keys.
- Acceptance method: Recursive payload scan test over full JSON tree for exact key match `locked_data`.

### PS-014 Unauthorized response rule
- Input: Request without required entitlement for non-public data.
- Output: Denied response must use a safe error envelope with `error_code`, `message`, `request_id`, `timestamp`; must not disclose locked field names/values.
- Boundary: Invalid token, expired token, missing member binding.
- Acceptance method: Inspect denied payloads for envelope shape and absence of locked details.

## 4) SEO and i18n URL strategy

### PS-015 Language URL routing strategy (fixed)
- Input: Request for localized page.
- Output:
  - `zh-Hant` uses root path: `/...`
  - `en` uses `/en/...`
  - `zh-Hans` uses `/zh-hans/...`
- Boundary: Unsupported locale, missing locale hint.
- Acceptance method: Resolve representative pages and verify route shape matches language strategy.

### PS-016 No cookie-based language routing
- Input: Crawler request with and without cookies.
- Output: Language route must not depend on cookies.
- Boundary: First visit without cookie, conflicting cookie value.
- Acceptance method: Compare crawler fetch results with/without language cookies; confirm same URL resolution policy.

### PS-017 Canonical and hreflang rules
- Input: Rendered page metadata for each locale variant.
- Output:
  - Exactly one canonical URL per page.
  - `hreflang` entries include available locale peers.
  - `x-default` is present and points to `zh-Hant` root-path version in v0.
- Boundary: Missing translation page, partial locale rollout.
- Acceptance method: Page-level metadata assertions for canonical uniqueness and hreflang/x-default correctness.

### PS-018 Unique data asset minimums by page type
- Input: Content payload for index page and entry page.
- Output:
  - Index page includes at least three unique asset types: ranking slice, methodology summary, period stats.
  - Entry page includes at least three unique asset types: instrument metrics, variant comparison, timestamped proof fields.
- Boundary: Thin-template pages with repeated generic text only.
- Acceptance method: Content audit checklist verifies required asset types are present and page-specific.
