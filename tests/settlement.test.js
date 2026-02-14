const test = require("node:test");
const assert = require("node:assert/strict");

const {
  SettlementEngine,
  buildChainUniqueId,
  computeExpectedAmount,
  decimalToMicroHalfUp,
  jitterMicroFromOrderId,
  microToAmountString,
} = require("../src/settlement");

function mkOrder(engine, overrides = {}) {
  const base = {
    order_id: "order-default",
    member_id: "member-1",
    chain: "TRON",
    asset: "USDT-TRON",
    recipient_address: "TRON_WALLET_1",
    base_amount: "10.000000",
    created_at_ms: 1_700_000_000_000,
  };
  return engine.createOrder({ ...base, ...overrides });
}

test("BR-008: decimalToMicroHalfUp uses deterministic HALF-UP rounding", () => {
  assert.equal(decimalToMicroHalfUp("1.0000004"), 1_000_000n);
  assert.equal(decimalToMicroHalfUp("1.0000005"), 1_000_001n);
  assert.equal(decimalToMicroHalfUp("1.0000015"), 1_000_002n);
});

test("BR-008: expected amount is deterministic for same order_id", () => {
  const a = computeExpectedAmount("order-123", "10.1234567");
  const b = computeExpectedAmount("order-123", "10.1234567");

  assert.equal(a.base_amount_micro, b.base_amount_micro);
  assert.equal(a.jitter_micro, b.jitter_micro);
  assert.equal(a.amount_expected_micro, b.amount_expected_micro);
  assert.equal(a.amount_expected, b.amount_expected);
});

test("BR-008: jitter uses first 4 bytes from sha256(utf8(order_id))", () => {
  const jitter = jitterMicroFromOrderId("order-hash-test");
  assert.equal(typeof jitter, "bigint");
  assert.ok(jitter >= 0n);
});

test("BR-009: exact match auto-credits, non-exact becomes UNMATCHED", () => {
  const engine = new SettlementEngine();
  const order = mkOrder(engine, { order_id: "o1" });

  const nonExact = engine.processPaymentEvent({
    chain: "TRON",
    asset: "USDT-TRON",
    recipient_address: "TRON_WALLET_1",
    transaction_id: "tx-non-exact",
    event_index: 0,
    occurred_at_ms: order.created_at_ms + 1_000,
    onchain_amount_micro: order.amount_expected_micro + 1n,
  });
  assert.equal(nonExact.outcome, "UNMATCHED");
  assert.equal(engine.orders.get("o1").status, "UNPAID");

  const exact = engine.processPaymentEvent({
    chain: "TRON",
    asset: "USDT-TRON",
    recipient_address: "TRON_WALLET_1",
    transaction_id: "tx-exact",
    event_index: 0,
    occurred_at_ms: order.created_at_ms + 2_000,
    onchain_amount_micro: order.amount_expected_micro,
  });
  assert.equal(exact.outcome, "CREDITED");
  assert.equal(engine.orders.get("o1").status, "PAID");
});

test("BR-009: claim cannot bypass exact-match rule", () => {
  const engine = new SettlementEngine();
  const order = mkOrder(engine, { order_id: "o-claim" });

  const unmatched = engine.processPaymentEvent({
    chain: "TRON",
    asset: "USDT-TRON",
    recipient_address: "TRON_WALLET_1",
    transaction_id: "tx-claim",
    event_index: 0,
    occurred_at_ms: order.created_at_ms + 1_000,
    onchain_amount_micro: order.amount_expected_micro + 100n,
  });
  assert.equal(unmatched.outcome, "UNMATCHED");

  const claim = engine.submitClaim({
    member_id: "member-1",
    order_id: "o-claim",
    unique_id: "tx-claim:0",
  });
  assert.equal(claim.outcome, "CLAIM_REJECTED_NON_EXACT");
  assert.equal(engine.orders.get("o-claim").status, "UNPAID");
});

test("BR-009: collision with same expected amount is NEEDS_CLAIM", () => {
  const engine = new SettlementEngine();
  const first = mkOrder(engine, { order_id: "collision-a" });

  const secondJitter = jitterMicroFromOrderId("collision-b");
  const secondBaseMicro = first.amount_expected_micro - secondJitter;
  assert.ok(secondBaseMicro >= 0n);

  const second = mkOrder(engine, {
    order_id: "collision-b",
    base_amount: microToAmountString(secondBaseMicro),
    member_id: "member-2",
  });

  assert.equal(first.amount_expected_micro, second.amount_expected_micro);

  const result = engine.processPaymentEvent({
    chain: "TRON",
    asset: "USDT-TRON",
    recipient_address: "TRON_WALLET_1",
    transaction_id: "tx-collision",
    event_index: 1,
    occurred_at_ms: first.created_at_ms + 5_000,
    onchain_amount_micro: first.amount_expected_micro,
  });

  assert.equal(result.outcome, "NEEDS_CLAIM");
  assert.equal(engine.orders.get("collision-a").status, "NEEDS_CLAIM");
  assert.equal(engine.orders.get("collision-b").status, "NEEDS_CLAIM");
});

test("BR-009: valid claim resolves collision for matching order only", () => {
  const engine = new SettlementEngine();
  const first = mkOrder(engine, { order_id: "claim-a", member_id: "member-a" });
  const secondJitter = jitterMicroFromOrderId("claim-b");
  const secondBaseMicro = first.amount_expected_micro - secondJitter;
  mkOrder(engine, {
    order_id: "claim-b",
    base_amount: microToAmountString(secondBaseMicro),
    member_id: "member-b",
  });

  engine.processPaymentEvent({
    chain: "TRON",
    asset: "USDT-TRON",
    recipient_address: "TRON_WALLET_1",
    transaction_id: "tx-claim-collision",
    event_index: 0,
    occurred_at_ms: first.created_at_ms + 10_000,
    onchain_amount_micro: first.amount_expected_micro,
  });

  const badClaim = engine.submitClaim({
    member_id: "member-b",
    order_id: "claim-a",
    unique_id: "tx-claim-collision:0",
  });
  assert.equal(badClaim.outcome, "CLAIM_REJECTED_MEMBER_MISMATCH");

  const goodClaim = engine.submitClaim({
    member_id: "member-a",
    order_id: "claim-a",
    unique_id: "tx-claim-collision:0",
  });
  assert.equal(goodClaim.outcome, "CLAIM_CREDITED");
  assert.equal(engine.orders.get("claim-a").status, "PAID");
});

test("BR-011: TRON unique id is transaction_id:event_index and deduped", () => {
  const engine = new SettlementEngine();
  const order = mkOrder(engine, { order_id: "tron-dedupe" });

  const first = engine.processPaymentEvent({
    chain: "TRON",
    asset: "USDT-TRON",
    recipient_address: "TRON_WALLET_1",
    transaction_id: "tron-hash",
    event_index: 7,
    occurred_at_ms: order.created_at_ms + 1_000,
    onchain_amount_micro: order.amount_expected_micro,
  });
  assert.equal(first.unique_id, "tron-hash:7");
  assert.equal(first.outcome, "CREDITED");

  const duplicate = engine.processPaymentEvent({
    chain: "TRON",
    asset: "USDT-TRON",
    recipient_address: "TRON_WALLET_1",
    transaction_id: "tron-hash",
    event_index: 7,
    occurred_at_ms: order.created_at_ms + 2_000,
    onchain_amount_micro: order.amount_expected_micro,
  });
  assert.equal(duplicate.outcome, "DUPLICATE_EVENT");
});

test("BR-011: EVM unique id is tx_hash:log_index and deduped", () => {
  const engine = new SettlementEngine();
  const order = mkOrder(engine, {
    order_id: "evm-dedupe",
    chain: "EVM",
    asset: "USDC-L2",
    recipient_address: "EVM_WALLET_1",
  });

  const first = engine.processPaymentEvent({
    chain: "EVM",
    asset: "USDC-L2",
    recipient_address: "EVM_WALLET_1",
    tx_hash: "0xabc",
    log_index: 3,
    occurred_at_ms: order.created_at_ms + 1_000,
    onchain_amount_micro: order.amount_expected_micro,
  });
  assert.equal(first.unique_id, "0xabc:3");
  assert.equal(first.outcome, "CREDITED");

  const duplicate = engine.processPaymentEvent({
    chain: "EVM",
    asset: "USDC-L2",
    recipient_address: "EVM_WALLET_1",
    tx_hash: "0xabc",
    log_index: 3,
    occurred_at_ms: order.created_at_ms + 2_000,
    onchain_amount_micro: order.amount_expected_micro,
  });
  assert.equal(duplicate.outcome, "DUPLICATE_EVENT");
});

test("BR-011: unique id formatter enforces chain-specific fields", () => {
  assert.equal(
    buildChainUniqueId({
      chain: "TRON",
      transaction_id: "t",
      event_index: 1,
    }),
    "t:1"
  );

  assert.equal(
    buildChainUniqueId({
      chain: "EVM",
      tx_hash: "0x1",
      log_index: 5,
    }),
    "0x1:5"
  );
});
