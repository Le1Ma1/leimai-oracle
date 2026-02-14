const test = require("node:test");
const assert = require("node:assert/strict");

const {
  buildRankingsLikePayload,
  createErrorEnvelope,
  maybeRequireAuth,
} = require("../src/api");
const { hasLockedData, stripLockedData } = require("../src/denylist");
const { getVariantSet, chooseBestVariant } = require("../src/variant");

const REQUIRED_TOP_LEVEL_FIELDS = [
  "proof_id",
  "method_version",
  "tf",
  "window",
  "modality",
  "variant",
  "risk_adjusted_score",
  "roi_score",
  "drawdown",
  "trade_count",
  "best_variant",
  "best_variant_scores",
  "fee_assumption",
  "slippage_assumption",
  "timestamp",
];

const REQUIRED_BEST_VARIANT_FIELDS = [
  "risk_adjusted_score",
  "roi_score",
  "drawdown",
  "trade_count",
];

function hasPath(payload, path) {
  const parts = path.split(".");
  let cursor = payload;
  for (const part of parts) {
    if (cursor === null || typeof cursor !== "object" || !(part in cursor)) {
      return false;
    }
    cursor = cursor[part];
  }
  return true;
}

function validatePS012Allowlist(payload) {
  const required = [
    "proof_id",
    "method_version",
    "tf",
    "window",
    "modality",
    "variant",
    "risk_adjusted_score",
    "roi_score",
    "drawdown",
    "trade_count",
    "fee_assumption",
    "slippage_assumption",
    "timestamp",
    "best_variant",
    "best_variant_scores.risk_adjusted_score",
    "best_variant_scores.roi_score",
    "best_variant_scores.drawdown",
    "best_variant_scores.trade_count",
  ];

  return required.every((path) => hasPath(payload, path));
}

test("A1: variant defaults to long when query param is missing", () => {
  const { status, payload } = buildRankingsLikePayload({
    symbol: "ASSET_01",
    tf: "1h",
    window: "30D",
  });
  assert.equal(status, 200);
  assert.equal(payload.variant, "long");
});

test("A1: each variant request returns selected variant metrics only", () => {
  const tuple = {
    symbol: "ASSET_01",
    tf: "1h",
    window: "30D",
    modality: "technical_indicators_plus_price_volume",
  };
  const fullSet = getVariantSet(tuple);

  for (const variant of ["long", "short", "long_short"]) {
    const { status, payload } = buildRankingsLikePayload({
      ...tuple,
      variant,
    });
    assert.equal(status, 200);
    assert.equal(payload.variant, variant);
    assert.equal(payload.risk_adjusted_score, fullSet[variant].risk_adjusted_score);
    assert.equal(payload.roi_score, fullSet[variant].roi_score);
    assert.equal(payload.drawdown, fullSet[variant].drawdown);
    assert.equal(payload.trade_count, fullSet[variant].trade_count);
  }
});

test("A1: best_variant equals argmax with deterministic tie-break", () => {
  const tuple = {
    symbol: "ASSET_01",
    tf: "1h",
    window: "30D",
    modality: "technical_indicators_plus_price_volume",
    variant: "short",
  };
  const { status, payload } = buildRankingsLikePayload(tuple);
  const fullSet = getVariantSet(tuple);
  const expectedBest = chooseBestVariant(fullSet);

  assert.equal(status, 200);
  assert.equal(payload.best_variant, expectedBest);
});

test("A1 tie-break comparator order: risk desc, drawdown asc, trades desc, long > long_short > short", () => {
  const fullTie = {
    long: { risk_adjusted_score: 1, drawdown: 0.1, trade_count: 10 },
    short: { risk_adjusted_score: 1, drawdown: 0.1, trade_count: 10 },
    long_short: { risk_adjusted_score: 1, drawdown: 0.1, trade_count: 10 },
  };
  assert.equal(chooseBestVariant(fullTie), "long");

  const drawdownTie = {
    long: { risk_adjusted_score: 1, drawdown: 0.2, trade_count: 10 },
    short: { risk_adjusted_score: 1, drawdown: 0.1, trade_count: 10 },
    long_short: { risk_adjusted_score: 1, drawdown: 0.15, trade_count: 10 },
  };
  assert.equal(chooseBestVariant(drawdownTie), "short");

  const tradeTie = {
    long: { risk_adjusted_score: 1, drawdown: 0.1, trade_count: 10 },
    short: { risk_adjusted_score: 1, drawdown: 0.1, trade_count: 15 },
    long_short: { risk_adjusted_score: 1, drawdown: 0.1, trade_count: 12 },
  };
  assert.equal(chooseBestVariant(tradeTie), "short");
});

test("PS-012: full allowlist field set is present and no extra top-level fields", () => {
  const { status, payload } = buildRankingsLikePayload({
    symbol: "ASSET_01",
    tf: "1h",
    window: "30D",
    variant: "long",
  });
  assert.equal(status, 200);
  assert.equal(validatePS012Allowlist(payload), true);
  assert.deepEqual(Object.keys(payload).sort(), REQUIRED_TOP_LEVEL_FIELDS.sort());
  assert.deepEqual(
    Object.keys(payload.best_variant_scores).sort(),
    REQUIRED_BEST_VARIANT_FIELDS.sort()
  );
});

test("PS-012 negative: missing any required field fails allowlist validation", () => {
  const { payload } = buildRankingsLikePayload({
    symbol: "ASSET_01",
    tf: "1h",
    window: "30D",
    variant: "long",
  });
  const missing = { ...payload };
  delete missing.fee_assumption;
  assert.equal(validatePS012Allowlist(missing), false);
});

test("invalid variant is rejected", () => {
  const { status, payload } = buildRankingsLikePayload({
    symbol: "ASSET_01",
    tf: "1h",
    window: "30D",
    variant: "bad",
  });
  assert.equal(status, 400);
  assert.equal(payload.error_code, "BAD_REQUEST");
});

test("recursive denylist strips locked_data at any depth", () => {
  const raw = {
    a: 1,
    locked_data: { x: 1 },
    nested: {
      b: 2,
      arr: [{ c: 3, locked_data: "x" }],
    },
  };
  const stripped = stripLockedData(raw);
  assert.equal(hasLockedData(stripped), false);
});

test("unauthorized envelope shape is safe and has no locked_data", () => {
  const maybeError = maybeRequireAuth({ scope: "private" }, {});
  assert.ok(maybeError);
  assert.equal(maybeError.status, 401);
  assert.deepEqual(Object.keys(maybeError.payload).sort(), [
    "error_code",
    "message",
    "request_id",
    "timestamp",
  ]);
  assert.equal(hasLockedData(maybeError.payload), false);
});

test("error envelopes are denylist-clean", () => {
  const error = createErrorEnvelope("BAD_REQUEST", "x", 400);
  assert.equal(hasLockedData(error.payload), false);
});
