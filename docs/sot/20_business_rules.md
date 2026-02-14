# MDP v0.1 Business Rules (SoT)

Document ID: `SOT-20`  
Version: `v0.1`  
Status: `Approved baseline`

## 1) Membership tiers and entitlements

### BR-001 Tier definition
- Input: Member tier lookup request.
- Output:
  - Free: single-indicator best-parameter snapshots only.
  - Pro: real-time signals/push + `x+y` combinations.
  - Elite: `3+` combinations + advanced features.
  - Buyout: exclusive seat for a model/proof package.
- Boundary: Unknown tier, downgraded tier, expired subscription.
- Acceptance method: Tier-to-feature entitlement matrix check; verify no cross-tier leakage.

### BR-002 Entitlement primary key
- Input: Access check for any protected feature.
- Output: Entitlement decision is keyed by `member_id` only.
- Boundary: Payer address changes, multiple wallets, IP changes.
- Acceptance method: Verify access remains consistent for same `member_id` despite payer wallet/IP changes.

## 2) Identity binding (SIWE / EIP-4361 style)

### BR-003 Identity wallet scope
- Input: Wallet binding attempt.
- Output: SIWE binds an EVM identity wallet for account identity only.
- Boundary: Non-EVM wallet for SIWE binding.
- Acceptance method: Ensure SIWE flow accepts EVM identity wallet context and rejects incompatible identity signature contexts.

### BR-004 SIWE required message fields
- Input: SIWE sign-in message payload.
- Output: Required fields must be present:
  - `domain`
  - `uri`
  - `version`
  - `chain_id`
  - `nonce`
  - `issued_at`
  - `expiration_time`
- Boundary: Missing field, malformed timestamp, wrong version.
- Acceptance method: Message schema validation on sign-in request.

### BR-005 SIWE security checks
- Input: Signed SIWE message submission.
- Output:
  - Nonce can be used once only.
  - Message must be unexpired.
  - Signature must match claimed signer.
  - `domain` and `uri` must match expected relying-party context.
- Boundary: Nonce replay, expired message, signature mismatch, domain/uri mismatch.
- Acceptance method: Negative test set for replay/expiry/signature/domain-uri mismatch.

## 3) Payment rails and verification

### BR-006 Payment rails
- Input: Purchase payment initiation.
- Output: Supported rails are `USDT-TRON`, `USDC-L2`, and `ERC20`.
- Boundary: Unsupported chain/token combination.
- Acceptance method: Route matrix test for allowed and blocked chain/token paths.

### BR-007 Identity-wallet and payer-wallet decoupling
- Input: Payment from an address different from SIWE identity wallet.
- Output: Payment remains valid if order matching succeeds; identity wallet equality with payer wallet is not required.
- Boundary: Third-party payer, custodial payout address, multi-wallet member.
- Acceptance method: Simulate purchase where SIWE wallet differs from payer wallet; verify entitlement attaches to `member_id`.

### BR-008 Deterministic per-order expected amount (V0)
- Input: `order_id` and `base_amount` (quoted amount in USDT units).
- Output:
  - Amount matching precision is fixed at `6` decimals (micro-unit).
  - `base_amount` is treated as a decimal number; multiplication by `1_000_000` is exact before rounding.
  - Rounding mode is `HALF-UP` (ties go away from zero).
  - Canonicalization for hashing: `order_id` is hashed as UTF-8 bytes of its exact stored string (no trimming, no case-folding), unless explicitly stated otherwise.
  - `base_amount_micro = floor(base_amount * 1_000_000 + 0.5)`
  - `jitter_micro = ((u32_be(sha256(utf8(order_id))[0..3]) % 10000) * 100)`
  - `amount_expected_micro = base_amount_micro + jitter_micro`
  - `amount_expected = amount_expected_micro / 1_000_000`
  - `jitter_micro` range is `0..999900` micro with step `100` micro (`0.0001` USDT).
- Boundary:
  - Rounding edge at 6 decimals.
  - Same `order_id` recomputation must be stable.
  - Old tolerance-band matching formula is not valid for settlement matching.
- Acceptance method: Recompute expected amount from same `order_id` multiple times and verify deterministic equality at micro precision.

### BR-009 Order matching keys and time window
- Input: Candidate on-chain payment event.
- Output: Matching uses keys:
  - `chain`
  - `asset`
  - `amount_expected`
  - `recipient_address`
  - `time_window`
  where `payment_match_window = 30 minutes` from order creation.
  Settlement auto-credit requires exact 6-decimal equality (`onchain_amount_micro == amount_expected_micro`).
  For non-exact amounts, do not auto-credit; mark `UNMATCHED` and require manual handling or explicit claim workflow that does not bypass the exact-match rule.
  Collision rule: if multiple unpaid orders share the same `amount_expected` within `match_window`, do not auto-credit; mark `NEEDS_CLAIM`.
  Claim requirement: user submits `member_id + order_id` and identity signature if available.
- Boundary:
  - Correct amount outside window.
  - Correct window but wrong recipient or asset.
  - Non-exact amount even with explicit claim request.
  - Multiple unpaid orders with same `amount_expected` in the same window.
- Acceptance method: Permutation tests for keys/window plus non-exact amount tests verifying `UNMATCHED` and no auto-credit, and collision tests verifying `NEEDS_CLAIM` and no auto-credit.

### BR-010 Chain confirmations defaults
- Input: Matched on-chain payment event.
- Output:
  - TRON confirmations required: `20`
  - L2 (EVM) confirmations required: `12`
  - ERC20 (L1) confirmations required: `12`
- Boundary: Event observed but not enough confirmations.
- Acceptance method: Confirmation-depth tests per chain profile.

### BR-011 Transaction-unique identifier and dedupe
- Input: Confirmed payment event.
- Output:
  - TRON USDT (TRC20): `tron_unique_id = transaction_id + ":" + event_index`
  - EVM: `evm_unique_id = tx_hash + ":" + log_index`
  - Same unique id cannot be credited twice.
- Boundary: Reorg/replay processing, duplicate webhook.
- Acceptance method: Submit duplicate TRON and EVM unique ids separately and verify single credit outcome for each chain format.

## 4) Notifications

### BR-012 Push channels
- Input: Eligible signal event.
- Output: Supported channels are `Web Push`, `Email`, and `Telegram`.
- Boundary: Channel disabled by user, channel transport failure.
- Acceptance method: Channel routing tests confirm event fan-out follows user preference and supported channels.

### BR-013 Notification dedupe alignment
- Input: Retries and duplicate signal events.
- Output: Delivery obeys dedupe key defined in `SOT-10 PS-010`; retries do not create duplicates.
- Boundary: Same signal re-fired in same minute bucket.
- Acceptance method: Cross-channel dedupe test with repeated triggers.

## 5) Buyout conflict state machine

### BR-014 Capacity fields and buyout lock
- Input: Buyout proposal accepted.
- Output:
  - Track `cap_total` and `cap_active`.
  - Set `cap_total_future = 0` after buyout takes effect.
- Boundary: Existing active seats at buyout approval time.
- Acceptance method: State snapshot before and after effective date.

### BR-015 Effective Date epoch rule
- Input: Buyout agreement creation.
- Output: Buyout activation is keyed to `effective_date_epoch` as the single source of activation time.
- Boundary: Timezone conversion differences.
- Acceptance method: Convert across timezones and confirm same epoch activation.

### BR-016 Grandfathering rule
- Input: Seat sold before buyout effective date.
- Output: Existing seat remains valid until current period end; no forced early cancellation by default.
- Boundary: Seat ending exactly at effective timestamp.
- Acceptance method: Seat lifecycle test for pre-effective seats across period boundaries.

### BR-017 Tender Offer early effectiveness threshold
- Input: Voluntary buyback campaign result.
- Output: If tender buyback participation is `>=80%`, early effectiveness is permitted before the original effective date.
- Boundary: `79.99%`, `80.00%`, and delayed settlement cases.
- Acceptance method: Threshold boundary tests for early-effective transition.

### BR-018 Buyout state transitions
- Input: State transition trigger events.
- Output: Minimum state machine:
  - `OPEN -> BUYOUT_PENDING`
  - `BUYOUT_PENDING -> BUYOUT_EFFECTIVE` (at effective epoch)
  - `BUYOUT_PENDING -> BUYOUT_EARLY_EFFECTIVE` (tender threshold met)
  - After effective states, no new seats can be sold.
- Boundary: Repeated trigger events, out-of-order events.
- Acceptance method: Transition table test ensuring only allowed transitions execute.
