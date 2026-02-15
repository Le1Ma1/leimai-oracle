const assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { buildRankingsLikePayload, maybeRequireAuth } = require("../src/api");
const {
  auditBrandSourceOfTruth,
  auditLogoUsage,
  auditSignaturePlacements,
  LOGO_SOT,
  SIGNATURE_SOT,
} = require("../src/brand_audit");
const {
  addSeat,
  applyEffective,
  applyTenderOffer,
  canSellNewSeats,
  createBuyoutState,
  isGrandfatheredSeatActive,
  startBuyout,
} = require("../src/buyout");
const { getCadenceMsByTf, resolveSnapshotTimestamp } = require("../src/cadence");
const {
  getRequiredConfirmations,
  isConfirmationSufficient,
} = require("../src/confirmations");
const { NotificationDedupeLedger, minuteBucket } = require("../src/dedupe");
const { checkEntitlement } = require("../src/entitlements");
const {
  buildLocalizedPath,
  buildPageMeta,
  resolveRouteIgnoringCookie,
} = require("../src/i18n_meta");
const { MinuteRateLimiter } = require("../src/ratelimit");
const { getRankingsUiState, getTabState } = require("../src/rankings_ui");
const { createAppServer } = require("../src/server");
const { MonetizationService, ORDER_STATES } = require("../src/monetization");
const {
  SettlementEngine,
  buildChainUniqueId,
  computeExpectedAmount,
  decimalToMicroHalfUp,
  jitterMicroFromOrderId,
  microToAmountString,
} = require("../src/settlement");
const { NonceLedger, signSiweMessage, verifySiweSubmission } = require("../src/siwe");
const { PUSH_CHANNELS, PushDispatcher } = require("../src/push");
const { getUniverse, isUniverseValid } = require("../src/universe");
const { parseTf } = require("../src/validators");
const { hasLockedData, stripLockedData } = require("../src/denylist");
const { isValidPaymentRail } = require("../src/validators");
const { chooseBestVariant, getVariantSet } = require("../src/variant");
const { getPaymentRailsMap } = require("../src/payment_rails");
const {
  FixtureChainProvider,
  createChainProvider,
  createChainProviderFromEnv,
} = require("../src/chain_provider");
const { renderArtifacts } = require("./render-artifacts");

const RESULTS = [];

function hasPath(payload, pathValue) {
  const parts = pathValue.split(".");
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
  return required.every((pathValue) => hasPath(payload, pathValue));
}

function readPngSize(filePath) {
  const buf = fs.readFileSync(filePath);
  if (buf.length < 24) {
    throw new Error(`PNG too small: ${filePath}`);
  }
  const signature = "89504e470d0a1a0a";
  if (buf.slice(0, 8).toString("hex") !== signature) {
    throw new Error(`Not a PNG: ${filePath}`);
  }
  return {
    width: buf.readUInt32BE(16),
    height: buf.readUInt32BE(20),
  };
}

function hashFile(filePath) {
  return createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

async function runTest(name, fn, evidence) {
  try {
    await fn();
    RESULTS.push({
      name,
      status: "PASS",
      evidence,
    });
  } catch (error) {
    RESULTS.push({
      name,
      status: "FAIL",
      evidence,
      error: error && error.stack ? error.stack : String(error),
    });
  }
}

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

function deriveBaseAmountForExpected(orderId, expectedAmountMicro) {
  const target = BigInt(expectedAmountMicro);
  const jitter = jitterMicroFromOrderId(orderId);
  if (target <= jitter) {
    throw new Error(`target amount must be greater than jitter for order ${orderId}`);
  }
  return microToAmountString(target - jitter);
}

function mkTempStatePath(prefix) {
  const tempDir = fs.mkdtempSync(
    path.join(os.tmpdir(), `mdp-${prefix}-`)
  );
  return {
    filePath: path.join(tempDir, "state.json"),
    cleanup: () => fs.rmSync(tempDir, { recursive: true, force: true }),
  };
}

function withTempEnv(pairs, fn) {
  const backup = new Map();
  for (const key of Object.keys(pairs)) {
    backup.set(key, Object.prototype.hasOwnProperty.call(process.env, key) ? process.env[key] : undefined);
    const value = pairs[key];
    if (value === undefined || value === null) {
      delete process.env[key];
    } else {
      process.env[key] = String(value);
    }
  }
  try {
    return fn();
  } finally {
    for (const [key, value] of backup.entries()) {
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
  }
}

async function withServer(fn, serverOptions = {}) {
  const server = createAppServer(serverOptions);
  await new Promise((resolve) => server.listen(0, resolve));
  const address = server.address();
  const baseUrl = `http://127.0.0.1:${address.port}`;
  try {
    await fn(baseUrl);
  } finally {
    await new Promise((resolve, reject) => {
      server.close((err) => (err ? reject(err) : resolve()));
    });
  }
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const json = await response.json();
  return { status: response.status, json };
}

async function run() {
  renderArtifacts();

  await runTest(
    "AC-001 default ranking tab is risk_adjusted",
    () => {
      const tabState = getTabState(undefined);
      assert.equal(tabState.active_tab, "risk_adjusted");
      assert.ok(tabState.available_tabs.includes("roi"));
    },
    "artifacts/ui/rankings_ui_default.json"
  );

  await runTest(
    "AC-002 roi is secondary tab",
    () => {
      const tabState = getTabState("risk_adjusted");
      assert.equal(tabState.active_tab, "risk_adjusted");
      assert.deepEqual(tabState.secondary_tabs, ["roi"]);
    },
    "artifacts/ui/rankings_ui_default.json"
  );

  await runTest(
    "AC-003 universe size fixed 20..30",
    () => {
      const list = getUniverse();
      assert.equal(list.length >= 20 && list.length <= 30, true);
      assert.equal(isUniverseValid(list), true);
    },
    "scripts/run-tests.js#AC-003"
  );

  await runTest(
    "AC-004 universe placeholder list is exactly 24 ordered symbols",
    () => {
      const list = getUniverse();
      assert.equal(list.length, 24);
      for (let i = 0; i < 24; i += 1) {
        const expected = `ASSET_${String(i + 1).padStart(2, "0")}`;
        assert.equal(list[i], expected);
      }
      assert.equal(new Set(list).size, 24);
    },
    "scripts/run-tests.js#AC-004"
  );

  await runTest(
    "AC-005 tf enum strict validation",
    () => {
      for (const tf of ["1m", "5m", "15m", "1h", "4h", "1d"]) {
        assert.equal(parseTf(tf), tf);
      }
      assert.equal(parseTf(""), "1h");
      assert.equal(parseTf("2h"), null);
      assert.equal(parseTf("1H"), null);
    },
    "scripts/run-tests.js#AC-005"
  );

  await runTest(
    "AC-006 window enum strict validation",
    () => {
      for (const windowValue of ["7D", "30D", "180D", "All"]) {
        const res = buildRankingsLikePayload({
          symbol: "ASSET_01",
          tf: "1h",
          window: windowValue,
        });
        assert.equal(res.status, 200);
      }
      const invalid = buildRankingsLikePayload({
        symbol: "ASSET_01",
        tf: "1h",
        window: "all",
      });
      assert.equal(invalid.status, 400);
    },
    "scripts/run-tests.js#AC-006"
  );

  await runTest(
    "AC-007 modality fixed to v0",
    () => {
      const defaultRes = buildRankingsLikePayload({
        symbol: "ASSET_01",
        tf: "1h",
        window: "30D",
      });
      assert.equal(defaultRes.status, 200);
      assert.equal(
        defaultRes.payload.modality,
        "technical_indicators_plus_price_volume"
      );

      const invalid = buildRankingsLikePayload({
        symbol: "ASSET_01",
        tf: "1h",
        window: "30D",
        modality: "other",
      });
      assert.equal(invalid.status, 400);
    },
    "scripts/run-tests.js#AC-007"
  );

  await runTest(
    "AC-008 variant defaults to long",
    () => {
      const { status, payload } = buildRankingsLikePayload({
        symbol: "ASSET_01",
        tf: "1h",
        window: "30D",
      });
      assert.equal(status, 200);
      assert.equal(payload.variant, "long");
    },
    "scripts/run-tests.js#AC-008"
  );

  await runTest(
    "AC-009 UI default long-only and best variant badge behavior",
    () => {
      const variantSet = getVariantSet({
        symbol: "ASSET_01",
        tf: "1h",
        window: "30D",
        modality: "technical_indicators_plus_price_volume",
      });
      const ui = getRankingsUiState({
        rawTab: undefined,
        variant: undefined,
        variantSet,
      });
      assert.equal(ui.default_variant, "long");
      assert.equal(ui.selected_variant, "long");
      assert.deepEqual(ui.switchable_variants.sort(), [
        "long",
        "long_short",
        "short",
      ]);
      assert.equal(ui.best_variant_badge, chooseBestVariant(variantSet));
    },
    "artifacts/ui/rankings_ui_default.json"
  );

  await runTest(
    "AC-010 free snapshot cadence is 6h",
    () => {
      const withinOne = buildRankingsLikePayload(
        {
          symbol: "ASSET_01",
          tf: "1h",
          window: "30D",
          tier: "free",
        },
        new Date("2026-02-14T01:10:00.000Z")
      );
      const withinTwo = buildRankingsLikePayload(
        {
          symbol: "ASSET_01",
          tf: "1h",
          window: "30D",
          tier: "free",
        },
        new Date("2026-02-14T05:59:59.000Z")
      );
      const nextBucket = buildRankingsLikePayload(
        {
          symbol: "ASSET_01",
          tf: "1h",
          window: "30D",
          tier: "free",
        },
        new Date("2026-02-14T06:00:01.000Z")
      );
      assert.equal(withinOne.payload.timestamp, withinTwo.payload.timestamp);
      assert.notEqual(withinOne.payload.timestamp, nextBucket.payload.timestamp);
    },
    "scripts/run-tests.js#AC-010"
  );

  await runTest(
    "AC-011 pro/elite cadence follows tf map",
    () => {
      for (const tf of ["1m", "5m", "15m", "1h", "4h", "1d"]) {
        const cadenceMs = getCadenceMsByTf(tf);
        const now = 1_700_000_000_000;
        const baseBucket = Math.floor(now / cadenceMs) * cadenceMs;
        const withinA = resolveSnapshotTimestamp({
          tier: "pro",
          tf,
          nowMs: baseBucket + 1_000,
        });
        const withinB = resolveSnapshotTimestamp({
          tier: "pro",
          tf,
          nowMs: baseBucket + cadenceMs - 1,
        });
        const next = resolveSnapshotTimestamp({
          tier: "pro",
          tf,
          nowMs: baseBucket + cadenceMs + 1,
        });
        const eliteWithin = resolveSnapshotTimestamp({
          tier: "elite",
          tf,
          nowMs: baseBucket + 1_000,
        });
        assert.equal(withinA, withinB);
        assert.notEqual(withinA, next);
        assert.equal(withinA, eliteWithin);
      }
    },
    "scripts/run-tests.js#AC-011"
  );

  await runTest(
    "AC-012 per-member per-minute cap N=10",
    () => {
      const limiter = new MinuteRateLimiter(10);
      const now = 1_700_000_000_000;
      for (let i = 0; i < 10; i += 1) {
        const result = limiter.check("member-A", now);
        assert.equal(result.allowed, true);
      }
      const blocked = limiter.check("member-A", now);
      assert.equal(blocked.allowed, false);
      const reset = limiter.check("member-A", now + 60_000);
      assert.equal(reset.allowed, true);
    },
    "scripts/run-tests.js#AC-012"
  );

  await runTest(
    "AC-013 notification dedupe key enforcement",
    () => {
      const ledger = new NotificationDedupeLedger();
      const now = 1_700_000_010_000;
      const payload = {
        member_id: "member-A",
        channel: "email",
        proof_id: "proof-1",
        variant: "long",
        tf: "1h",
        window: "30D",
        signal_type: "ENTRY",
        minute_bucket: minuteBucket(now),
      };
      const first = ledger.record(payload, now);
      const second = ledger.record(payload, now);
      assert.equal(first.deduped, false);
      assert.equal(second.deduped, true);
      assert.equal(ledger.getRecords().length, 1);
    },
    "scripts/run-tests.js#AC-013"
  );

  await runTest(
    "AC-014 public endpoint availability",
    async () => {
      await withServer(async (baseUrl) => {
        const rankings = await fetch(`${baseUrl}/rankings`);
        const summaries = await fetch(`${baseUrl}/summaries`);
        const methodology = await fetch(`${baseUrl}/methodology`);
        assert.equal(rankings.status, 200);
        assert.equal(summaries.status, 200);
        assert.equal(methodology.status, 200);
      });
    },
    "scripts/run-tests.js#AC-014"
  );

  await runTest(
    "AC-015 full PS-012 allowlist validation",
    () => {
      const response = buildRankingsLikePayload({
        symbol: "ASSET_01",
        tf: "1h",
        window: "30D",
        variant: "long",
      });
      assert.equal(response.status, 200);
      assert.equal(validatePS012Allowlist(response.payload), true);

      const missing = { ...response.payload };
      delete missing.fee_assumption;
      assert.equal(validatePS012Allowlist(missing), false);
    },
    "scripts/run-tests.js#AC-015"
  );

  await runTest(
    "AC-016 recursive denylist strips locked_data at any depth",
    () => {
      const stripped = stripLockedData({
        a: 1,
        locked_data: { x: 1 },
        arr: [{ b: 2, locked_data: 3 }],
      });
      assert.equal(hasLockedData(stripped), false);
    },
    "scripts/run-tests.js#AC-016"
  );

  await runTest(
    "AC-017 unauthorized envelope shape",
    () => {
      const result = maybeRequireAuth({ scope: "private" }, {});
      assert.ok(result);
      assert.equal(result.status, 401);
      assert.deepEqual(Object.keys(result.payload).sort(), [
        "error_code",
        "message",
        "request_id",
        "timestamp",
      ]);
    },
    "scripts/run-tests.js#AC-017"
  );

  await runTest(
    "AC-018 i18n route strategy mapping",
    () => {
      assert.equal(buildLocalizedPath("/rankings", "zh-Hant"), "/rankings");
      assert.equal(buildLocalizedPath("/rankings", "en"), "/en/rankings");
      assert.equal(buildLocalizedPath("/rankings", "zh-Hans"), "/zh-hans/rankings");
      assert.equal(buildLocalizedPath("/", "zh-Hant"), "/");
      assert.equal(buildLocalizedPath("/", "en"), "/en/");
      assert.equal(buildLocalizedPath("/", "zh-Hans"), "/zh-hans/");
    },
    "scripts/run-tests.js#AC-018"
  );

  await runTest(
    "AC-019 cookie-independent route resolution for crawler",
    () => {
      const withoutCookie = resolveRouteIgnoringCookie("/zh-hans/summaries");
      const withCookie = resolveRouteIgnoringCookie("/zh-hans/summaries", "lang=en");
      assert.deepEqual(withCookie, withoutCookie);
    },
    "scripts/run-tests.js#AC-019"
  );

  await runTest(
    "AC-020 canonical/hreflang/x-default correctness",
    () => {
      const meta = buildPageMeta("/rankings", "en");
      assert.equal(meta.canonical, "/en/rankings");
      assert.deepEqual(Object.keys(meta.hreflang).sort(), [
        "en",
        "x-default",
        "zh-Hans",
        "zh-Hant",
      ]);
      assert.equal(meta.hreflang["zh-Hant"], "/rankings");
      assert.equal(meta.hreflang["x-default"], "/rankings");
      assert.equal(meta.hreflang.en, "/en/rankings");
      assert.equal(meta.hreflang["zh-Hans"], "/zh-hans/rankings");
    },
    "scripts/run-tests.js#AC-020"
  );

  await runTest(
    "AC-021 index payload contains required asset blocks",
    () => {
      const response = buildRankingsLikePayload({
        symbol: "ASSET_01",
        tf: "1h",
        window: "30D",
      });
      assert.equal(response.status, 200);
      const blocks = response.payload.asset_blocks;
      assert.ok(blocks.ranking_slice);
      assert.ok(blocks.methodology_summary);
      assert.ok(blocks.period_stats);
    },
    "scripts/run-tests.js#AC-021"
  );

  await runTest(
    "AC-022 entry payload contains required asset blocks",
    () => {
      const response = buildRankingsLikePayload(
        {
          symbol: "ASSET_01",
          tf: "1h",
          window: "30D",
        },
        new Date(),
        "summaries"
      );
      assert.equal(response.status, 200);
      const blocks = response.payload.asset_blocks;
      assert.ok(blocks.instrument_metrics);
      assert.ok(blocks.variant_comparison);
      assert.ok(blocks.timestamped_proof_fields);
    },
    "scripts/run-tests.js#AC-022"
  );

  await runTest(
    "AC-023 entitlement matrix denies cross-tier leakage",
    () => {
      assert.equal(
        checkEntitlement({
          member_id: "m1",
          tier: "free",
          feature: "realtime_signal",
        }).allowed,
        false
      );
      assert.equal(
        checkEntitlement({
          member_id: "m1",
          tier: "pro",
          feature: "advanced_features",
        }).allowed,
        false
      );
      assert.equal(
        checkEntitlement({
          member_id: "m1",
          tier: "elite",
          feature: "advanced_features",
        }).allowed,
        true
      );
    },
    "scripts/run-tests.js#AC-023"
  );

  await runTest(
    "AC-024 entitlement key is member_id (independent of payer/ip)",
    () => {
      const first = checkEntitlement({
        member_id: "member-X",
        tier: "pro",
        payer: "payer-1",
        ip: "1.1.1.1",
        feature: "push",
      });
      const second = checkEntitlement({
        member_id: "member-X",
        tier: "pro",
        payer: "payer-2",
        ip: "2.2.2.2",
        feature: "push",
      });
      assert.equal(first.allowed, true);
      assert.equal(second.allowed, true);
      assert.equal(first.member_id, second.member_id);
    },
    "scripts/run-tests.js#AC-024"
  );

  await runTest(
    "AC-025 SIWE required fields validation",
    () => {
      const ledger = new NonceLedger();
      const now = new Date("2026-02-14T00:00:00.000Z");
      const message = {
        domain: "leimai.example",
        uri: "https://leimai.example/signin",
        version: "1",
        chain_id: "1",
        nonce: "abc123",
        issued_at: "2026-02-14T00:00:00.000Z",
        expiration_time: "2026-02-14T01:00:00.000Z",
      };
      const signature = signSiweMessage(message, "signer-A");
      const ok = verifySiweSubmission({
        message,
        signature,
        expectedDomain: "leimai.example",
        expectedUri: "https://leimai.example/signin",
        signerId: "signer-A",
        nonceLedger: ledger,
        now,
      });
      assert.equal(ok.ok, true);

      const missingNonce = { ...message };
      delete missingNonce.nonce;
      const fail = verifySiweSubmission({
        message: missingNonce,
        signature: "x",
        expectedDomain: "leimai.example",
        expectedUri: "https://leimai.example/signin",
        signerId: "signer-A",
        nonceLedger: new NonceLedger(),
        now,
      });
      assert.equal(fail.ok, false);
      assert.equal(fail.code, "MISSING_FIELD");
    },
    "scripts/run-tests.js#AC-025"
  );

  await runTest(
    "AC-026 SIWE replay/expiry/signature/domain-uri negatives",
    () => {
      const now = new Date("2026-02-14T00:10:00.000Z");
      const message = {
        domain: "leimai.example",
        uri: "https://leimai.example/signin",
        version: "1",
        chain_id: "1",
        nonce: "nonce-1",
        issued_at: "2026-02-14T00:00:00.000Z",
        expiration_time: "2026-02-14T01:00:00.000Z",
      };

      const ledgerReplay = new NonceLedger();
      const signature = signSiweMessage(message, "signer-A");
      const first = verifySiweSubmission({
        message,
        signature,
        expectedDomain: "leimai.example",
        expectedUri: "https://leimai.example/signin",
        signerId: "signer-A",
        nonceLedger: ledgerReplay,
        now,
      });
      assert.equal(first.ok, true);
      const replay = verifySiweSubmission({
        message,
        signature,
        expectedDomain: "leimai.example",
        expectedUri: "https://leimai.example/signin",
        signerId: "signer-A",
        nonceLedger: ledgerReplay,
        now,
      });
      assert.equal(replay.ok, false);
      assert.equal(replay.code, "NONCE_REPLAY");

      const expired = verifySiweSubmission({
        message: {
          ...message,
          nonce: "nonce-expired",
          expiration_time: "2026-02-14T00:00:00.000Z",
        },
        signature: signSiweMessage(
          {
            ...message,
            nonce: "nonce-expired",
            expiration_time: "2026-02-14T00:00:00.000Z",
          },
          "signer-A"
        ),
        expectedDomain: "leimai.example",
        expectedUri: "https://leimai.example/signin",
        signerId: "signer-A",
        nonceLedger: new NonceLedger(),
        now,
      });
      assert.equal(expired.ok, false);
      assert.equal(expired.code, "EXPIRED");

      const badSig = verifySiweSubmission({
        message: { ...message, nonce: "nonce-badsig" },
        signature: "bad-signature",
        expectedDomain: "leimai.example",
        expectedUri: "https://leimai.example/signin",
        signerId: "signer-A",
        nonceLedger: new NonceLedger(),
        now,
      });
      assert.equal(badSig.ok, false);
      assert.equal(badSig.code, "SIGNATURE_MISMATCH");

      const mismatch = verifySiweSubmission({
        message: { ...message, nonce: "nonce-domain" },
        signature: signSiweMessage(
          { ...message, nonce: "nonce-domain" },
          "signer-A"
        ),
        expectedDomain: "other.example",
        expectedUri: "https://other.example/signin",
        signerId: "signer-A",
        nonceLedger: new NonceLedger(),
        now,
      });
      assert.equal(mismatch.ok, false);
      assert.equal(mismatch.code, "DOMAIN_URI_MISMATCH");
    },
    "scripts/run-tests.js#AC-026"
  );

  await runTest(
    "AC-027 payment rails allowlist enforcement",
    () => {
      assert.equal(isValidPaymentRail("USDT-TRON"), true);
      assert.equal(isValidPaymentRail("USDC-L2"), true);
      assert.equal(isValidPaymentRail("ERC20"), true);
      assert.equal(isValidPaymentRail("BTC"), false);

      const engine = new SettlementEngine();
      assert.throws(() =>
        mkOrder(engine, { order_id: "bad-rail", asset: "BTC" })
      );
    },
    "scripts/run-tests.js#AC-027"
  );

  await runTest(
    "AC-028 identity wallet can differ from payer wallet",
    () => {
      const engine = new SettlementEngine();
      const order = mkOrder(engine, {
        order_id: "wallet-decouple",
        member_id: "member-decouple",
        identity_wallet: "0xIDENTITY",
      });
      const event = engine.processPaymentEvent({
        chain: "TRON",
        asset: "USDT-TRON",
        recipient_address: "TRON_WALLET_1",
        payer_wallet: "T_PAYER_DIFFERENT",
        transaction_id: "tx-decouple",
        event_index: 0,
        occurred_at_ms: order.created_at_ms + 1_000,
        onchain_amount_micro: order.amount_expected_micro,
      });
      assert.equal(event.outcome, "CREDITED");
      assert.equal(engine.orders.get("wallet-decouple").status, "PAID");
    },
    "scripts/run-tests.js#AC-028"
  );

  await runTest(
    "AC-029 deterministic HALF-UP rounding and jitter",
    () => {
      assert.equal(decimalToMicroHalfUp("1.0000004"), 1_000_000n);
      assert.equal(decimalToMicroHalfUp("1.0000005"), 1_000_001n);

      const a = computeExpectedAmount("order-123", "10.1234567");
      const b = computeExpectedAmount("order-123", "10.1234567");
      assert.equal(a.amount_expected_micro, b.amount_expected_micro);
      assert.equal(typeof jitterMicroFromOrderId("order-123"), "bigint");
    },
    "scripts/run-tests.js#AC-029"
  );

  await runTest(
    "AC-030 exact amount matching only, non-exact UNMATCHED",
    () => {
      const engine = new SettlementEngine();
      const order = mkOrder(engine, { order_id: "o1" });

      const nonExact = engine.processPaymentEvent({
        chain: "TRON",
        asset: "USDT-TRON",
        recipient_address: "TRON_WALLET_1",
        transaction_id: "tx-unmatched",
        event_index: 0,
        occurred_at_ms: order.created_at_ms + 1_000,
        onchain_amount_micro: order.amount_expected_micro + 1n,
      });
      assert.equal(nonExact.outcome, "UNMATCHED");

      const exact = engine.processPaymentEvent({
        chain: "TRON",
        asset: "USDT-TRON",
        recipient_address: "TRON_WALLET_1",
        transaction_id: "tx-exact",
        event_index: 1,
        occurred_at_ms: order.created_at_ms + 2_000,
        onchain_amount_micro: order.amount_expected_micro,
      });
      assert.equal(exact.outcome, "CREDITED");
    },
    "scripts/run-tests.js#AC-030"
  );

  await runTest(
    "AC-031 confirmations defaults by chain profile",
    () => {
      assert.equal(getRequiredConfirmations("TRON"), 20);
      assert.equal(getRequiredConfirmations("L2"), 12);
      assert.equal(getRequiredConfirmations("ERC20"), 12);
      assert.equal(isConfirmationSufficient("TRON", 19), false);
      assert.equal(isConfirmationSufficient("TRON", 20), true);
      assert.equal(isConfirmationSufficient("L2", 11), false);
      assert.equal(isConfirmationSufficient("L2", 12), true);
      assert.equal(isConfirmationSufficient("ERC20", 11), false);
      assert.equal(isConfirmationSufficient("ERC20", 12), true);
    },
    "scripts/run-tests.js#AC-031"
  );

  await runTest(
    "AC-032 chain-specific unique id formatter",
    () => {
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
    },
    "scripts/run-tests.js#AC-032"
  );

  await runTest(
    "AC-033 push channels support webpush/email/telegram",
    () => {
      assert.deepEqual(PUSH_CHANNELS.sort(), ["email", "telegram", "webpush"]);
      const dedupe = new NotificationDedupeLedger();
      const dispatcher = new PushDispatcher({ dedupeLedger: dedupe });
      const now = 1_700_000_100_000;
      for (const channel of ["webpush", "email", "telegram"]) {
        const res = dispatcher.send(
          {
            member_id: "m-push",
            channel,
            proof_id: "proof-push",
            variant: "long",
            tf: "1h",
            window: "30D",
            signal_type: "ENTRY",
          },
          now
        );
        assert.equal(res.sent, true);
      }
      assert.equal(dispatcher.getDeliveryLog().length, 3);
    },
    "scripts/run-tests.js#AC-033"
  );

  await runTest(
    "AC-034 buyout sets cap_total_future=0 after effective",
    () => {
      const buyout = createBuyoutState({ cap_total: 100, cap_active: 60 });
      startBuyout(buyout, 1_700_000_000);
      const result = applyEffective(buyout, 1_700_000_000);
      assert.equal(result.ok, true);
      assert.equal(buyout.cap_total_future, 0);
      assert.equal(canSellNewSeats(buyout), false);
    },
    "scripts/run-tests.js#AC-034"
  );

  await runTest(
    "AC-035 effective_date_epoch is single activation trigger",
    () => {
      const buyout = createBuyoutState({ cap_total: 50, cap_active: 10 });
      startBuyout(buyout, 1_700_000_500);
      const before = applyEffective(buyout, 1_700_000_499);
      assert.equal(before.ok, false);
      const at = applyEffective(buyout, 1_700_000_500);
      assert.equal(at.ok, true);
    },
    "scripts/run-tests.js#AC-035"
  );

  await runTest(
    "AC-036 grandfathering seat remains until period end",
    () => {
      const buyout = createBuyoutState({ cap_total: 10, cap_active: 0 });
      addSeat(buyout, {
        seat_id: "seat-1",
        sold_epoch: 100,
        end_epoch: 1_000,
      });
      startBuyout(buyout, 500);
      applyEffective(buyout, 500);
      assert.equal(isGrandfatheredSeatActive(buyout, "seat-1", 700), true);
      assert.equal(isGrandfatheredSeatActive(buyout, "seat-1", 1_001), false);
    },
    "scripts/run-tests.js#AC-036"
  );

  await runTest(
    "AC-037 tender threshold >=80% enables early effectiveness",
    () => {
      const buyout = createBuyoutState({ cap_total: 20, cap_active: 5 });
      startBuyout(buyout, 9_999_999);
      const below = applyTenderOffer(buyout, 0.7999);
      assert.equal(below.ok, false);
      const at = applyTenderOffer(buyout, 0.8);
      assert.equal(at.ok, true);
      assert.equal(buyout.cap_total_future, 0);
    },
    "scripts/run-tests.js#AC-037"
  );

  await runTest(
    "AC-038 buyout state transitions reject invalid edges",
    () => {
      const buyout = createBuyoutState({ cap_total: 20, cap_active: 5 });
      const invalidEarly = applyEffective(buyout, 1);
      assert.equal(invalidEarly.ok, false);
      const pending = startBuyout(buyout, 1_000);
      assert.equal(pending.ok, true);
      const invalidRestart = startBuyout(buyout, 2_000);
      assert.equal(invalidRestart.ok, false);
      const effective = applyEffective(buyout, 1_000);
      assert.equal(effective.ok, true);
      const invalidTenderPostEffective = applyTenderOffer(buyout, 0.9);
      assert.equal(invalidTenderPostEffective.ok, false);
    },
    "scripts/run-tests.js#AC-038"
  );

  await runTest(
    "AC-039 brand SoT root path strategy",
    () => {
      const pass = auditBrandSourceOfTruth({
        logo: "logo.png",
        signature: "signature.jpg",
      });
      assert.equal(pass.pass, true);
      assert.equal(pass.actual.logo, LOGO_SOT);
      assert.equal(pass.actual.signature, SIGNATURE_SOT);
    },
    "artifacts/brand/sot_audit.json"
  );

  await runTest(
    "AC-040 logo usage has no prohibited transforms",
    () => {
      const report = auditLogoUsage([
        {
          id: "primary",
          form: "primary",
          distorted: false,
          recolored_unapproved: false,
          contrast_ok: true,
        },
        {
          id: "badge",
          form: "badge",
          distorted: false,
          recolored_unapproved: false,
          contrast_ok: true,
        },
      ]);
      assert.equal(report.pass, true);
      assert.equal(report.violations.length, 0);
    },
    "artifacts/brand/logo_usage_report.json"
  );

  await runTest(
    "AC-041 signature appears only in allowed surfaces",
    () => {
      const report = auditSignaturePlacements([
        { id: "proof", surface: "proof_card" },
        { id: "buyout", surface: "buyout_certificate" },
        { id: "report_end", surface: "report_end" },
        { id: "footer", surface: "footer" },
      ]);
      assert.equal(report.pass, true);
    },
    "artifacts/brand/signature_placement_allowlist.json"
  );

  await runTest(
    "AC-042 signature prohibited zones are detected",
    () => {
      const report = auditSignaturePlacements([
        { id: "header", surface: "header" },
        { id: "nav", surface: "nav" },
        { id: "cards", surface: "every_card" },
      ]);
      assert.equal(report.pass, false);
      assert.ok(report.violations.length >= 3);
    },
    "artifacts/brand/signature_placement_prohibited.json"
  );

  await runTest(
    "AC-043 proof card includes proof_id/method_version/timestamp",
    () => {
      const svgPath = path.join(process.cwd(), "artifacts", "proofcard", "proof_card.svg");
      const metaPath = path.join(process.cwd(), "artifacts", "proofcard", "proof_card_meta.json");
      const svg = fs.readFileSync(svgPath, "utf8");
      const meta = JSON.parse(fs.readFileSync(metaPath, "utf8"));
      assert.ok(svg.includes("proof_id: proof-demo-001"));
      assert.ok(svg.includes("method_version: v0.1"));
      assert.ok(svg.includes("timestamp: 2026-02-14T00:00:00.000Z"));
      assert.equal(meta.proof_id, "proof-demo-001");
      assert.equal(meta.method_version, "v0.1");
      assert.equal(meta.timestamp, "2026-02-14T00:00:00.000Z");
    },
    "artifacts/proofcard/proof_card.svg"
  );

  await runTest(
    "AC-044 proof card signature is bottom-right with safe box",
    () => {
      const metaPath = path.join(process.cwd(), "artifacts", "proofcard", "proof_card_meta.json");
      const meta = JSON.parse(fs.readFileSync(metaPath, "utf8"));
      const sig = meta.signature;
      assert.equal(sig.placement, "bottom-right");
      assert.ok(sig.x + sig.width <= 1200);
      assert.ok(sig.y + sig.height <= 630);
      assert.equal(sig.source, "/signature.jpg");
    },
    "artifacts/proofcard/proof_card_meta.json"
  );

  await runTest(
    "AC-045 logo recognizability artifacts exist at 16/24/32",
    () => {
      const p16 = path.join(process.cwd(), "artifacts", "brand", "logo_16.png");
      const p24 = path.join(process.cwd(), "artifacts", "brand", "logo_24.png");
      const p32 = path.join(process.cwd(), "artifacts", "brand", "logo_32.png");

      const s16 = readPngSize(p16);
      const s24 = readPngSize(p24);
      const s32 = readPngSize(p32);
      assert.deepEqual(s16, { width: 16, height: 16 });
      assert.deepEqual(s24, { width: 24, height: 24 });
      assert.deepEqual(s32, { width: 32, height: 32 });

      const h16 = hashFile(p16);
      const h24 = hashFile(p24);
      const h32 = hashFile(p32);
      assert.notEqual(h16, h24);
      assert.notEqual(h24, h32);
      assert.notEqual(h16, h32);
    },
    "artifacts/brand/logo_16.png"
  );

  await runTest(
    "AC-046 each variant returns selected metrics",
    () => {
      const tuple = {
        symbol: "ASSET_01",
        tf: "1h",
        window: "30D",
        modality: "technical_indicators_plus_price_volume",
      };
      const fullSet = getVariantSet(tuple);
      for (const variant of ["long", "short", "long_short"]) {
        const { status, payload } = buildRankingsLikePayload({ ...tuple, variant });
        assert.equal(status, 200);
        assert.equal(payload.variant, variant);
        assert.equal(payload.risk_adjusted_score, fullSet[variant].risk_adjusted_score);
        assert.equal(payload.roi_score, fullSet[variant].roi_score);
        assert.equal(payload.drawdown, fullSet[variant].drawdown);
        assert.equal(payload.trade_count, fullSet[variant].trade_count);
      }
    },
    "scripts/run-tests.js#AC-046"
  );

  await runTest(
    "AC-047 best_variant equals argmax",
    () => {
      const tuple = {
        symbol: "ASSET_01",
        tf: "1h",
        window: "30D",
        modality: "technical_indicators_plus_price_volume",
        variant: "short",
      };
      const response = buildRankingsLikePayload(tuple);
      const expectedBest = chooseBestVariant(getVariantSet(tuple));
      assert.equal(response.status, 200);
      assert.equal(response.payload.best_variant, expectedBest);
    },
    "scripts/run-tests.js#AC-047"
  );

  await runTest(
    "AC-048 tie-break deterministic order",
    () => {
      const fullTie = {
        long: { risk_adjusted_score: 1, drawdown: 0.1, trade_count: 10 },
        short: { risk_adjusted_score: 1, drawdown: 0.1, trade_count: 10 },
        long_short: { risk_adjusted_score: 1, drawdown: 0.1, trade_count: 10 },
      };
      assert.equal(chooseBestVariant(fullTie), "long");
    },
    "scripts/run-tests.js#AC-048"
  );

  await runTest(
    "AC-049 collision marks NEEDS_CLAIM without auto-credit",
    () => {
      const engine = new SettlementEngine();
      const first = mkOrder(engine, { order_id: "collision-a" });
      const secondJitter = jitterMicroFromOrderId("collision-b");
      const secondBaseMicro = first.amount_expected_micro - secondJitter;
      mkOrder(engine, {
        order_id: "collision-b",
        base_amount: microToAmountString(secondBaseMicro),
        member_id: "member-2",
      });

      const outcome = engine.processPaymentEvent({
        chain: "TRON",
        asset: "USDT-TRON",
        recipient_address: "TRON_WALLET_1",
        transaction_id: "tx-collision",
        event_index: 0,
        occurred_at_ms: first.created_at_ms + 1_000,
        onchain_amount_micro: first.amount_expected_micro,
      });
      assert.equal(outcome.outcome, "NEEDS_CLAIM");
    },
    "scripts/run-tests.js#AC-049"
  );

  await runTest(
    "AC-050 claim cannot bypass exact-match rule",
    () => {
      const engine = new SettlementEngine();
      const order = mkOrder(engine, { order_id: "claim-non-exact" });
      engine.processPaymentEvent({
        chain: "TRON",
        asset: "USDT-TRON",
        recipient_address: "TRON_WALLET_1",
        transaction_id: "tx-claim",
        event_index: 0,
        occurred_at_ms: order.created_at_ms + 1_000,
        onchain_amount_micro: order.amount_expected_micro + 100n,
      });

      const claim = engine.submitClaim({
        member_id: order.member_id,
        order_id: order.order_id,
        unique_id: "tx-claim:0",
      });
      assert.equal(claim.outcome, "CLAIM_REJECTED_NON_EXACT");
    },
    "scripts/run-tests.js#AC-050"
  );

  await runTest(
    "AC-051 legacy tolerance-band matching is removed",
    () => {
      const engine = new SettlementEngine();
      const order = mkOrder(engine, { order_id: "legacy-band" });
      const res = engine.processPaymentEvent({
        chain: "TRON",
        asset: "USDT-TRON",
        recipient_address: "TRON_WALLET_1",
        transaction_id: "tx-legacy",
        event_index: 0,
        occurred_at_ms: order.created_at_ms + 1_000,
        onchain_amount_micro: order.amount_expected_micro + 1n,
      });
      assert.equal(res.outcome, "UNMATCHED");
    },
    "scripts/run-tests.js#AC-051"
  );

  await runTest(
    "AC-052 TRON unique id dedupe transaction_id:event_index",
    () => {
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
    },
    "scripts/run-tests.js#AC-052"
  );

  await runTest(
    "AC-053 EVM unique id dedupe tx_hash:log_index",
    () => {
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
    },
    "scripts/run-tests.js#AC-053"
  );

  await runTest(
    "V2-001 /plan endpoint returns static plans + i18n meta",
    async () => {
      await withServer(async (baseUrl) => {
        const { status, json } = await fetchJson(
          `${baseUrl}/plan?locale=en`,
          {
            headers: {
              "x-member-id": "v2-plan",
              "x-now-ms": "1700000000000",
            },
          }
        );
        assert.equal(status, 200);
        assert.equal(json.page, "plan");
        assert.equal(json.locale, "en");
        assert.deepEqual(json.rails.sort(), ["ERC20", "USDC-L2", "USDT-TRON"]);
        assert.equal(json.meta.canonical, "/en/plan");
      });
    },
    "scripts/run-tests.js#V2-001"
  );

  await runTest(
    "V2-002 create order exposes deterministic amount and AWAITING_PAYMENT",
    () => {
      const service = new MonetizationService();
      const order = service.createOrder({
        member_id: "v2-user",
        requested_tier: "pro",
        asset: "USDT-TRON",
        base_amount: "12.340001",
        order_id: "v2-order-1",
        created_at_ms: 1700000000000,
      });
      const expected = computeExpectedAmount("v2-order-1", "12.340001");
      assert.equal(order.state, ORDER_STATES.AWAITING_PAYMENT);
      assert.equal(order.amount_expected_micro, expected.amount_expected_micro.toString());
      assert.equal(order.amount_expected, expected.amount_expected);
    },
    "scripts/run-tests.js#V2-002"
  );

  await runTest(
    "V2-003 conversion loop happy path unlocks entitlement",
    () => {
      const service = new MonetizationService();
      const order = service.createOrder({
        member_id: "v2-happy",
        requested_tier: "pro",
        asset: "USDT-TRON",
        base_amount: "9.500000",
        order_id: "v2-order-happy",
        identity_wallet: "0xID-HAPPY",
        created_at_ms: 1700000000000,
      });
      const pay = service.submitPayment({
        order_id: order.order_id,
        transaction_id: "v2txhappy",
        event_index: 0,
        onchain_amount_micro: BigInt(order.amount_expected_micro),
        confirmations: 20,
        payer_wallet: "T_PAYER_OTHER",
        occurred_at_ms: 1700000001000,
      });
      assert.equal(pay.order.state, ORDER_STATES.ACTIVE);
      const unlocked = service.isFeatureUnlocked("v2-happy", "realtime_signal");
      assert.equal(unlocked.allowed, true);
      assert.equal(unlocked.tier, "pro");
    },
    "scripts/run-tests.js#V2-003"
  );

  await runTest(
    "V2-004 non-exact payment remains UNMATCHED and does not activate",
    () => {
      const service = new MonetizationService();
      const order = service.createOrder({
        member_id: "v2-non-exact",
        requested_tier: "pro",
        asset: "USDT-TRON",
        base_amount: "8.000000",
        order_id: "v2-order-bad",
        created_at_ms: 1700000000000,
      });
      const result = service.submitPayment({
        order_id: order.order_id,
        transaction_id: "v2txbad",
        event_index: 0,
        onchain_amount_micro: BigInt(order.amount_expected_micro) + 1n,
        confirmations: 30,
        occurred_at_ms: 1700000001000,
      });
      assert.equal(result.settlement.outcome, "UNMATCHED");
      assert.equal(result.order.state, ORDER_STATES.AWAITING_PAYMENT);
      const unlocked = service.isFeatureUnlocked("v2-non-exact", "realtime_signal");
      assert.equal(unlocked.allowed, false);
      assert.equal(unlocked.tier, "free");
    },
    "scripts/run-tests.js#V2-004"
  );

  await runTest(
    "V2-005 insufficient confirmations delay ACTIVE until confirm",
    () => {
      const service = new MonetizationService();
      const order = service.createOrder({
        member_id: "v2-confirm",
        requested_tier: "elite",
        asset: "USDC-L2",
        base_amount: "15.000000",
        order_id: "v2-order-confirm",
        created_at_ms: 1700000000000,
      });
      const first = service.submitPayment({
        order_id: order.order_id,
        tx_hash: "0xv2confirm",
        log_index: 0,
        onchain_amount_micro: BigInt(order.amount_expected_micro),
        confirmations: 11,
        occurred_at_ms: 1700000001000,
      });
      assert.equal(first.settlement.outcome, "CREDITED");
      assert.equal(first.order.state, ORDER_STATES.CONFIRMED);

      const confirmed = service.confirmOrder({
        order_id: order.order_id,
        confirmations: 12,
      });
      assert.equal(confirmed.state, ORDER_STATES.ACTIVE);
      const unlocked = service.isFeatureUnlocked("v2-confirm", "advanced_features");
      assert.equal(unlocked.allowed, true);
      assert.equal(unlocked.tier, "elite");
    },
    "scripts/run-tests.js#V2-005"
  );

  await runTest(
    "V2-006 identity wallet may differ from payer wallet in checkout flow",
    () => {
      const service = new MonetizationService();
      const order = service.createOrder({
        member_id: "v2-wallet",
        requested_tier: "pro",
        asset: "USDT-TRON",
        base_amount: "7.000000",
        order_id: "v2-order-wallet",
        identity_wallet: "0xIDENTITY_ONLY",
        created_at_ms: 1700000000000,
      });
      const pay = service.submitPayment({
        order_id: order.order_id,
        transaction_id: "v2txwallet",
        event_index: 0,
        onchain_amount_micro: BigInt(order.amount_expected_micro),
        confirmations: 20,
        payer_wallet: "T_PAYER_DIFFERENT",
        occurred_at_ms: 1700000001000,
      });
      assert.equal(pay.order.state, ORDER_STATES.ACTIVE);
      assert.notEqual(pay.order.identity_wallet, pay.order.payer_wallet);
    },
    "scripts/run-tests.js#V2-006"
  );

  await runTest(
    "V2-007 /checkout endpoints create->pay->confirm status loop",
    async () => {
      await withServer(async (baseUrl) => {
        const create = await fetchJson(`${baseUrl}/checkout/create`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-member-id": "v2-endpoint",
            "x-now-ms": "1700000010000",
            "x-idempotency-key": "v2-create-1",
          },
          body: JSON.stringify({
            requested_tier: "pro",
            asset: "USDT-TRON",
            base_amount: "11.000000",
            order_id: "v2-endpoint-order",
            identity_wallet: "0xV2END",
          }),
        });
        assert.equal(create.status, 200);
        assert.equal(create.json.state, "AWAITING_PAYMENT");

        const pay = await fetchJson(`${baseUrl}/checkout/pay`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-member-id": "v2-endpoint",
            "x-now-ms": "1700000011000",
            "x-idempotency-key": "v2-pay-1",
          },
          body: JSON.stringify({
            order_id: "v2-endpoint-order",
            transaction_id: "v2endpointtx",
            event_index: 1,
            onchain_amount_micro: create.json.amount_expected_micro,
            confirmations: 20,
            payer_wallet: "T_ENDPOINT_PAYER",
          }),
        });
        assert.equal(pay.status, 200);
        assert.equal(pay.json.order.state, "ACTIVE");

        const checkout = await fetchJson(
          `${baseUrl}/checkout?order_id=v2-endpoint-order`,
          {
            headers: {
              "x-member-id": "v2-endpoint",
              "x-now-ms": "1700000012000",
            },
          }
        );
        assert.equal(checkout.status, 200);
        assert.equal(checkout.json.state, "ACTIVE");
        assert.equal(checkout.json.unlocked_tier, "pro");
      });
    },
    "scripts/run-tests.js#V2-007"
  );

  await runTest(
    "V3-001 idempotency on /checkout/create replays same response and no duplicate order",
    async () => {
      await withServer(async (baseUrl) => {
        const first = await fetchJson(`${baseUrl}/checkout/create`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-member-id": "v3-idem-create",
            "x-idempotency-key": "v3-create-key-1",
            "x-now-ms": "1700000100000",
          },
          body: JSON.stringify({
            requested_tier: "pro",
            asset: "USDT-TRON",
            base_amount: "13.000000",
            order_id: "v3-idem-order-1",
          }),
        });
        const replay = await fetchJson(`${baseUrl}/checkout/create`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-member-id": "v3-idem-create",
            "x-idempotency-key": "v3-create-key-1",
            "x-now-ms": "1700000100001",
          },
          body: JSON.stringify({
            requested_tier: "pro",
            asset: "USDT-TRON",
            base_amount: "13.000000",
            order_id: "v3-idem-order-1",
          }),
        });
        assert.equal(first.status, 200);
        assert.equal(replay.status, 200);
        assert.deepEqual(replay.json, first.json);
      });
    },
    "scripts/run-tests.js#V3-001"
  );

  await runTest(
    "V3-002 idempotency keys apply on /checkout/pay and /checkout/confirm",
    async () => {
      await withServer(async (baseUrl) => {
        const create = await fetchJson(`${baseUrl}/checkout/create`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-member-id": "v3-idem-pay",
            "x-idempotency-key": "v3-create-key-2",
            "x-now-ms": "1700000110000",
          },
          body: JSON.stringify({
            requested_tier: "elite",
            asset: "USDC-L2",
            base_amount: "20.000000",
            order_id: "v3-idem-order-2",
          }),
        });
        assert.equal(create.status, 200);

        const payBody = {
          order_id: "v3-idem-order-2",
          tx_hash: "0xv3idem2",
          log_index: 1,
          onchain_amount_micro: create.json.amount_expected_micro,
          confirmations: 11,
        };
        const payA = await fetchJson(`${baseUrl}/checkout/pay`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-member-id": "v3-idem-pay",
            "x-idempotency-key": "v3-pay-key-2",
            "x-now-ms": "1700000110100",
          },
          body: JSON.stringify(payBody),
        });
        const payB = await fetchJson(`${baseUrl}/checkout/pay`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-member-id": "v3-idem-pay",
            "x-idempotency-key": "v3-pay-key-2",
            "x-now-ms": "1700000110200",
          },
          body: JSON.stringify(payBody),
        });
        assert.equal(payA.status, 200);
        assert.equal(payB.status, 200);
        assert.deepEqual(payB.json, payA.json);
        assert.equal(payA.json.order.state, "CONFIRMED");

        const confirmBody = {
          order_id: "v3-idem-order-2",
          confirmations: 12,
        };
        const confirmA = await fetchJson(`${baseUrl}/checkout/confirm`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-member-id": "v3-idem-pay",
            "x-idempotency-key": "v3-confirm-key-2",
            "x-now-ms": "1700000110300",
          },
          body: JSON.stringify(confirmBody),
        });
        const confirmB = await fetchJson(`${baseUrl}/checkout/confirm`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-member-id": "v3-idem-pay",
            "x-idempotency-key": "v3-confirm-key-2",
            "x-now-ms": "1700000110400",
          },
          body: JSON.stringify(confirmBody),
        });
        assert.equal(confirmA.status, 200);
        assert.equal(confirmB.status, 200);
        assert.deepEqual(confirmB.json, confirmA.json);
        assert.equal(confirmA.json.state, "ACTIVE");
      });
    },
    "scripts/run-tests.js#V3-002"
  );

  await runTest(
    "V3-003 idempotency conflict with same key and different payload is rejected",
    async () => {
      await withServer(async (baseUrl) => {
        const first = await fetchJson(`${baseUrl}/checkout/create`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-member-id": "v3-idem-conflict",
            "x-idempotency-key": "v3-create-key-3",
            "x-now-ms": "1700000120000",
          },
          body: JSON.stringify({
            requested_tier: "pro",
            asset: "USDT-TRON",
            base_amount: "10.000000",
            order_id: "v3-conflict-order",
          }),
        });
        assert.equal(first.status, 200);

        const second = await fetchJson(`${baseUrl}/checkout/create`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-member-id": "v3-idem-conflict",
            "x-idempotency-key": "v3-create-key-3",
            "x-now-ms": "1700000120010",
          },
          body: JSON.stringify({
            requested_tier: "pro",
            asset: "USDT-TRON",
            base_amount: "10.100000",
            order_id: "v3-conflict-order",
          }),
        });
        assert.equal(second.status, 400);
        assert.equal(second.json.error_code, "BAD_REQUEST");
      });
    },
    "scripts/run-tests.js#V3-003"
  );

  await runTest(
    "V3-004 checkout endpoint rate-limit blocks 11th request in same minute",
    async () => {
      await withServer(async (baseUrl) => {
        const nowMs = "1700000130000";
        for (let i = 0; i < 10; i += 1) {
          const response = await fetchJson(`${baseUrl}/checkout/create`, {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-member-id": "v3-rate-limit",
              "x-idempotency-key": `v3-rate-key-${i}`,
              "x-now-ms": nowMs,
            },
            body: JSON.stringify({
              requested_tier: "pro",
              asset: "USDT-TRON",
              base_amount: "5.000000",
              order_id: `v3-rate-order-${i}`,
            }),
          });
          assert.equal(response.status, 200);
        }
        const blocked = await fetchJson(`${baseUrl}/checkout/create`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-member-id": "v3-rate-limit",
            "x-idempotency-key": "v3-rate-key-11",
            "x-now-ms": nowMs,
          },
          body: JSON.stringify({
            requested_tier: "pro",
            asset: "USDT-TRON",
            base_amount: "5.000000",
            order_id: "v3-rate-order-11",
          }),
        });
        assert.equal(blocked.status, 429);
        assert.equal(blocked.json.error_code, "RATE_LIMITED");
      });
    },
    "scripts/run-tests.js#V3-004"
  );

  await runTest(
    "V3-005 persisted orders and entitlements survive service restart",
    () => {
      const temp = mkTempStatePath("persist");
      try {
        const serviceA = new MonetizationService({
          persistence_path: temp.filePath,
        });
        const order = serviceA.createOrder({
          member_id: "v3-persist-member",
          requested_tier: "pro",
          asset: "USDT-TRON",
          base_amount: "9.000000",
          order_id: "v3-persist-order",
          created_at_ms: 1700000140000,
        });
        const paid = serviceA.submitPayment({
          order_id: order.order_id,
          transaction_id: "v3persisttx",
          event_index: 0,
          onchain_amount_micro: order.amount_expected_micro,
          confirmations: 20,
          occurred_at_ms: 1700000141000,
        });
        assert.equal(paid.order.state, ORDER_STATES.ACTIVE);
        serviceA.dispose();

        const serviceB = new MonetizationService({
          persistence_path: temp.filePath,
        });
        const loadedOrder = serviceB.getOrder("v3-persist-order");
        assert.ok(loadedOrder);
        assert.equal(loadedOrder.state, ORDER_STATES.ACTIVE);
        const unlocked = serviceB.isFeatureUnlocked(
          "v3-persist-member",
          "realtime_signal"
        );
        assert.equal(unlocked.allowed, true);
        assert.equal(unlocked.tier, "pro");
        serviceB.dispose();
      } finally {
        temp.cleanup();
      }
    },
    "scripts/run-tests.js#V3-005"
  );

  await runTest(
    "V3-006 audit trail records CREATED->AWAITING_PAYMENT->CONFIRMED->ACTIVE",
    () => {
      const service = new MonetizationService();
      const order = service.createOrder({
        member_id: "v3-audit",
        requested_tier: "pro",
        asset: "USDT-TRON",
        base_amount: "6.000000",
        order_id: "v3-audit-order",
        created_at_ms: 1700000150000,
      });
      service.submitPayment({
        order_id: order.order_id,
        transaction_id: "v3audittx",
        event_index: 0,
        onchain_amount_micro: order.amount_expected_micro,
        confirmations: 20,
        occurred_at_ms: 1700000151000,
      });

      const transitions = service
        .getAuditTrail()
        .filter(
          (item) =>
            item.kind === "ORDER_STATE_TRANSITION" &&
            item.order_id === order.order_id
        )
        .map((item) => `${item.from_state}->${item.to_state}`);
      assert.deepEqual(transitions, [
        "CREATED->AWAITING_PAYMENT",
        "AWAITING_PAYMENT->CONFIRMED",
        "CONFIRMED->ACTIVE",
      ]);
    },
    "scripts/run-tests.js#V3-006"
  );

  await runTest(
    "V3-007 reconcile activates missed confirmations and remains deduped on rerun",
    () => {
      const service = new MonetizationService();
      const order = service.createOrder({
        member_id: "v3-reconcile",
        requested_tier: "elite",
        asset: "USDC-L2",
        base_amount: "17.000000",
        order_id: "v3-reconcile-order",
        created_at_ms: 1700000160000,
      });
      const pay = service.submitPayment({
        order_id: order.order_id,
        tx_hash: "0xv3reconcile",
        log_index: 2,
        onchain_amount_micro: order.amount_expected_micro,
        confirmations: 1,
        occurred_at_ms: 1700000161000,
      });
      assert.equal(pay.order.state, ORDER_STATES.CONFIRMED);

      const first = service.runReconcile({
        now_ms: 1700000162000,
        confirmations_by_unique_id: {
          [pay.settlement.unique_id]: 12,
        },
      });
      assert.equal(first.activated, 1);
      const postFirst = service.getOrder(order.order_id);
      assert.equal(postFirst.state, ORDER_STATES.ACTIVE);

      const second = service.runReconcile({
        now_ms: 1700000163000,
        confirmations_by_unique_id: {
          [pay.settlement.unique_id]: 12,
        },
      });
      assert.equal(second.activated, 0);

      const activeTransitions = service
        .getAuditTrail()
        .filter(
          (item) =>
            item.kind === "ORDER_STATE_TRANSITION" &&
            item.order_id === order.order_id &&
            item.to_state === ORDER_STATES.ACTIVE
        );
      assert.equal(activeTransitions.length, 1);
    },
    "scripts/run-tests.js#V3-007"
  );

  await runTest(
    "V3-008 GET /checkout recipient_address is always sourced from rail SoT",
    async () => {
      const railsMap = getPaymentRailsMap();
      const expectedRecipient = railsMap["USDT-TRON"].recipient_address;
      await withServer(async (baseUrl) => {
        const created = await fetchJson(`${baseUrl}/checkout/create`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-member-id": "v3-recipient",
            "x-idempotency-key": "v3-recipient-create-1",
            "x-now-ms": "1700000170000",
          },
          body: JSON.stringify({
            requested_tier: "pro",
            asset: "USDT-TRON",
            base_amount: "4.500000",
            order_id: "v3-recipient-order-1",
            recipient_address: "ATTACKER_ADDRESS_OVERRIDE",
          }),
        });
        assert.equal(created.status, 200);
        assert.equal(created.json.recipient_address, expectedRecipient);
        assert.notEqual(created.json.recipient_address, "ATTACKER_ADDRESS_OVERRIDE");

        const checkout = await fetchJson(
          `${baseUrl}/checkout?order_id=v3-recipient-order-1`,
          {
            headers: {
              "x-member-id": "v3-recipient",
              "x-now-ms": "1700000170100",
            },
          }
        );
        assert.equal(checkout.status, 200);
        assert.equal(checkout.json.recipient_address, expectedRecipient);
      });
    },
    "scripts/run-tests.js#V3-008"
  );

  await runTest(
    "V3-009 payment verification enforces strict chain/asset allowlist pairs",
    () => {
      const railsMap = getPaymentRailsMap();
      const service = new MonetizationService();
      const tronOrder = service.createOrder({
        member_id: "v3-pair-member",
        requested_tier: "pro",
        asset: "USDT-TRON",
        base_amount: "10.500000",
        order_id: "v3-pair-tron-order",
        created_at_ms: 1700000180000,
      });

      assert.throws(() =>
        service.submitPayment({
          order_id: tronOrder.order_id,
          chain: "ethereum",
          asset_symbol: "usdt",
          transaction_id: "v3pairtxbad1",
          event_index: 0,
          onchain_amount_micro: tronOrder.amount_expected_micro,
          confirmations: 20,
          occurred_at_ms: 1700000181000,
        })
      );

      assert.throws(() =>
        service.submitPayment({
          order_id: tronOrder.order_id,
          chain: "tron",
          asset_symbol: "usdc",
          transaction_id: "v3pairtxbad2",
          event_index: 1,
          onchain_amount_micro: tronOrder.amount_expected_micro,
          confirmations: 20,
          occurred_at_ms: 1700000182000,
        })
      );

      const l1Order = service.createOrder({
        member_id: "v3-pair-member-2",
        requested_tier: "elite",
        asset: "ERC20",
        payment_asset: "usdc",
        base_amount: "11.000000",
        order_id: "v3-pair-erc20-order",
        created_at_ms: 1700000183000,
      });
      assert.equal(l1Order.payment_chain, "ethereum");
      assert.equal(l1Order.payment_asset, "usdc");
      assert.equal(
        l1Order.recipient_address,
        railsMap.ERC20.recipient_address
      );

      const paid = service.submitPayment({
        order_id: l1Order.order_id,
        chain: "ethereum",
        asset_symbol: "usdc",
        tx_hash: "0xv3pairgood",
        log_index: 3,
        onchain_amount_micro: l1Order.amount_expected_micro,
        confirmations: 12,
        occurred_at_ms: 1700000184000,
      });
      assert.equal(paid.order.state, ORDER_STATES.ACTIVE);
    },
    "scripts/run-tests.js#V3-009"
  );

  await runTest(
    "V4-001 TRON chain proof via /checkout/confirm activates order when confirmations are sufficient",
    async () => {
      const fixturesDir = path.join(process.cwd(), "tests", "fixtures", "chain");
      const orderId = "v4-tron-endpoint-order";
      const baseAmount = deriveBaseAmountForExpected(orderId, "25000000");
      await withServer(
        async (baseUrl) => {
          const create = await fetchJson(`${baseUrl}/checkout/create`, {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-member-id": "v4-tron-member",
              "x-idempotency-key": "v4-tron-create-key",
              "x-now-ms": "1700000190000",
            },
            body: JSON.stringify({
              requested_tier: "pro",
              asset: "USDT-TRON",
              base_amount: baseAmount,
              order_id: orderId,
            }),
          });
          assert.equal(create.status, 200);
          assert.equal(create.json.state, ORDER_STATES.AWAITING_PAYMENT);

          const confirm = await fetchJson(`${baseUrl}/checkout/confirm`, {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-member-id": "v4-tron-member",
              "x-idempotency-key": "v4-tron-confirm-key",
              "x-now-ms": "1700000191000",
            },
            body: JSON.stringify({
              order_id: orderId,
              chain: "tron",
              tx_id: "v4_tron_ok_tx",
            }),
          });
          assert.equal(confirm.status, 200);
          assert.equal(confirm.json.state, ORDER_STATES.ACTIVE);

          const checkout = await fetchJson(`${baseUrl}/checkout?order_id=${orderId}`, {
            headers: {
              "x-member-id": "v4-tron-member",
              "x-now-ms": "1700000192000",
            },
          });
          assert.equal(checkout.status, 200);
          assert.equal(checkout.json.state, ORDER_STATES.ACTIVE);
        },
        {
          chainMock: true,
          chainFixturesDir: fixturesDir,
        }
      );
    },
    "scripts/run-tests.js#V4-001"
  );

  await runTest(
    "V4-002 Arbitrum chain proof activates USDC-L2 order when confirmations are sufficient",
    () => {
      const fixturesDir = path.join(process.cwd(), "tests", "fixtures", "chain");
      const service = new MonetizationService({
        chain_provider: new FixtureChainProvider({ fixtures_dir: fixturesDir }),
      });
      const orderId = "v4-arb-order";
      const baseAmount = deriveBaseAmountForExpected(orderId, "35000000");
      const order = service.createOrder({
        member_id: "v4-arb-member",
        requested_tier: "elite",
        asset: "USDC-L2",
        base_amount: baseAmount,
        order_id: orderId,
        created_at_ms: 1700000200000,
      });
      assert.equal(order.state, ORDER_STATES.AWAITING_PAYMENT);

      const confirmed = service.confirmOrder({
        order_id: orderId,
        chain: "arbitrum",
        tx_id: "v4_arb_ok_tx",
      });
      assert.equal(confirmed.state, ORDER_STATES.ACTIVE);
      const unlocked = service.isFeatureUnlocked("v4-arb-member", "advanced_features");
      assert.equal(unlocked.allowed, true);
      assert.equal(unlocked.tier, "elite");
    },
    "scripts/run-tests.js#V4-002"
  );

  await runTest(
    "V4-003 insufficient confirmations stay non-ACTIVE until reconcile updates same tx confirmations",
    () => {
      const fixturesDir = path.join(process.cwd(), "tests", "fixtures", "chain");
      const service = new MonetizationService({
        chain_provider: new FixtureChainProvider({ fixtures_dir: fixturesDir }),
      });
      const orderId = "v4-low-conf-order";
      const baseAmount = deriveBaseAmountForExpected(orderId, "26000000");
      service.createOrder({
        member_id: "v4-low-conf-member",
        requested_tier: "pro",
        asset: "USDT-TRON",
        base_amount: baseAmount,
        order_id: orderId,
        created_at_ms: 1700000210000,
      });

      const first = service.confirmOrder({
        order_id: orderId,
        chain: "tron",
        tx_id: "v4_tron_low_conf_tx",
      });
      assert.equal(first.state, ORDER_STATES.CONFIRMED);

      const beforeReconcile = service.getOrder(orderId);
      assert.ok(beforeReconcile.credited_unique_id);
      const reconcile = service.runReconcile({
        now_ms: 1700000211000,
        confirmations_by_unique_id: {
          [beforeReconcile.credited_unique_id]: 20,
        },
      });
      assert.equal(reconcile.activated, 1);

      const second = service.confirmOrder({
        order_id: orderId,
        chain: "tron",
        tx_id: "v4_tron_low_conf_tx",
      });
      assert.equal(second.state, ORDER_STATES.ACTIVE);

      const activeTransitions = service
        .getAuditTrail()
        .filter(
          (item) =>
            item.kind === "ORDER_STATE_TRANSITION" &&
            item.order_id === orderId &&
            item.to_state === ORDER_STATES.ACTIVE
        );
      assert.equal(activeTransitions.length, 1);
    },
    "scripts/run-tests.js#V4-003"
  );

  await runTest(
    "V4-004 wrong recipient transfer cannot activate order",
    () => {
      const fixturesDir = path.join(process.cwd(), "tests", "fixtures", "chain");
      const service = new MonetizationService({
        chain_provider: new FixtureChainProvider({ fixtures_dir: fixturesDir }),
      });
      const orderId = "v4-wrong-recipient-order";
      const baseAmount = deriveBaseAmountForExpected(orderId, "27000000");
      service.createOrder({
        member_id: "v4-wrong-recipient-member",
        requested_tier: "pro",
        asset: "USDT-TRON",
        base_amount: baseAmount,
        order_id: orderId,
        created_at_ms: 1700000220000,
      });

      const result = service.confirmOrder({
        order_id: orderId,
        chain: "tron",
        tx_id: "v4_tron_wrong_recipient_tx",
      });
      assert.equal(result.state, ORDER_STATES.AWAITING_PAYMENT);
      assert.equal(result.match_status, "UNMATCHED");
    },
    "scripts/run-tests.js#V4-004"
  );

  await runTest(
    "V4-005 non-exact onchain amount (1 micro off) remains UNMATCHED",
    () => {
      const fixturesDir = path.join(process.cwd(), "tests", "fixtures", "chain");
      const service = new MonetizationService({
        chain_provider: new FixtureChainProvider({ fixtures_dir: fixturesDir }),
      });
      const orderId = "v4-non-exact-order";
      const baseAmount = deriveBaseAmountForExpected(orderId, "28000000");
      service.createOrder({
        member_id: "v4-non-exact-member",
        requested_tier: "pro",
        asset: "USDT-TRON",
        base_amount: baseAmount,
        order_id: orderId,
        created_at_ms: 1700000230000,
      });

      const result = service.confirmOrder({
        order_id: orderId,
        chain: "tron",
        tx_id: "v4_tron_non_exact_tx",
      });
      assert.equal(result.state, ORDER_STATES.AWAITING_PAYMENT);
      assert.equal(result.match_status, "UNMATCHED");
      const unlocked = service.isFeatureUnlocked("v4-non-exact-member", "realtime_signal");
      assert.equal(unlocked.allowed, false);
    },
    "scripts/run-tests.js#V4-005"
  );

  await runTest(
    "V4-006 same unique_id replay cannot credit twice",
    () => {
      const fixturesDir = path.join(process.cwd(), "tests", "fixtures", "chain");
      const service = new MonetizationService({
        chain_provider: new FixtureChainProvider({ fixtures_dir: fixturesDir }),
      });

      const firstOrderId = "v4-replay-first-order";
      const firstBase = deriveBaseAmountForExpected(firstOrderId, "25000000");
      service.createOrder({
        member_id: "v4-replay-member-a",
        requested_tier: "pro",
        asset: "USDT-TRON",
        base_amount: firstBase,
        order_id: firstOrderId,
        created_at_ms: 1700000240000,
      });
      const first = service.confirmOrder({
        order_id: firstOrderId,
        chain: "tron",
        tx_id: "v4_tron_ok_tx",
      });
      assert.equal(first.state, ORDER_STATES.ACTIVE);

      const secondOrderId = "v4-replay-second-order";
      const secondBase = deriveBaseAmountForExpected(secondOrderId, "25000000");
      service.createOrder({
        member_id: "v4-replay-member-b",
        requested_tier: "pro",
        asset: "USDT-TRON",
        base_amount: secondBase,
        order_id: secondOrderId,
        created_at_ms: 1700000241000,
      });
      const replay = service.confirmOrder({
        order_id: secondOrderId,
        chain: "tron",
        tx_id: "v4_tron_ok_tx",
      });
      assert.equal(replay.state, ORDER_STATES.AWAITING_PAYMENT);

      const activeTransitions = service
        .getAuditTrail()
        .filter(
          (item) =>
            item.kind === "ORDER_STATE_TRANSITION" &&
            item.to_state === ORDER_STATES.ACTIVE
        );
      assert.equal(activeTransitions.length, 1);
      assert.equal(activeTransitions[0].order_id, firstOrderId);

      const secondUnlocked = service.isFeatureUnlocked(
        "v4-replay-member-b",
        "realtime_signal"
      );
      assert.equal(secondUnlocked.allowed, false);
    },
    "scripts/run-tests.js#V4-006"
  );

  await runTest(
    "V5-001 CHAIN_MODE=mock never attempts network calls",
    () => {
      const railsMap = getPaymentRailsMap();
      let rpcCalls = 0;
      withTempEnv(
        {
          CHAIN_MODE: "mock",
          TRON_RPC_URL: "http://invalid-tron-rpc.local",
          ARBITRUM_RPC_URL: "http://invalid-arb-rpc.local",
        },
        () => {
          const provider = createChainProviderFromEnv({
            rpc_fetch_impl: () => {
              rpcCalls += 1;
              throw new Error("network should not be called in mock mode");
            },
            chain_fixtures_dir: path.join(process.cwd(), "tests", "fixtures", "chain"),
          });
          const evidence = provider.getTransferEvidence({
            chain: "tron",
            asset: "usdt",
            tx_hash_or_id: "v4_tron_ok_tx",
            recipient_address: railsMap["USDT-TRON"].recipient_address,
            amount_expected_micro: 25000000,
          });
          assert.ok(evidence);
          assert.equal(evidence.unique_id, "v4_tron_ok_tx:0");
        }
      );
      assert.equal(rpcCalls, 0);
    },
    "scripts/run-tests.js#V5-001"
  );

  await runTest(
    "V5-002 CHAIN_MODE=rpc missing RPC URL returns deterministic error and preserves order state",
    async () => {
      await withServer(
        async (baseUrl) => {
          const create = await fetchJson(`${baseUrl}/checkout/create`, {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-member-id": "v5-missing-url",
              "x-idempotency-key": "v5-create-1",
              "x-now-ms": "1700000250000",
            },
            body: JSON.stringify({
              requested_tier: "pro",
              asset: "USDC-L2",
              base_amount: "10.000000",
              order_id: "v5-missing-url-order",
            }),
          });
          assert.equal(create.status, 200);
          assert.equal(create.json.state, ORDER_STATES.AWAITING_PAYMENT);

          const confirm = await fetchJson(`${baseUrl}/checkout/confirm`, {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-member-id": "v5-missing-url",
              "x-idempotency-key": "v5-confirm-1",
              "x-now-ms": "1700000251000",
            },
            body: JSON.stringify({
              order_id: "v5-missing-url-order",
              chain: "arbitrum",
              tx_id: "0xv5missing",
            }),
          });
          assert.equal(confirm.status, 400);
          assert.equal(confirm.json.error_code, "BAD_REQUEST");
          assert.equal(
            String(confirm.json.message).includes("RPC_CONFIG_MISSING_ARBITRUM_RPC_URL"),
            true
          );

          const checkout = await fetchJson(
            `${baseUrl}/checkout?order_id=v5-missing-url-order`,
            {
              headers: {
                "x-member-id": "v5-missing-url",
                "x-now-ms": "1700000252000",
              },
            }
          );
          assert.equal(checkout.status, 200);
          assert.equal(checkout.json.state, ORDER_STATES.AWAITING_PAYMENT);
        },
        {
          chainMode: "rpc",
          tronRpcUrl: null,
          arbitrumRpcUrl: null,
          ethereumRpcUrl: null,
        }
      );
    },
    "scripts/run-tests.js#V5-002"
  );

  await runTest(
    "V5-003 rpc-mode evidence normalization shape and unique_id formats",
    () => {
      const railsMap = getPaymentRailsMap();
      const arbRecipient = railsMap["USDC-L2"].recipient_address;
      const tronRecipient = railsMap["USDT-TRON"].recipient_address;
      const arbAmount = 1234500;
      const tronAmount = 2500000;
      const arbAmountHex = `0x${arbAmount.toString(16).padStart(64, "0")}`;
      const provider = createChainProvider({
        mode: "rpc",
        urls: {
          tron: "http://tron.rpc.local",
          arbitrum: "http://arb.rpc.local",
          ethereum: "http://eth.rpc.local",
        },
        fetchImpl: (request) => {
          if (request.transport === "jsonrpc") {
            const method = request.body.method;
            if (method === "eth_getTransactionReceipt") {
              return {
                jsonrpc: "2.0",
                id: 1,
                result: {
                  blockNumber: "0x64",
                  logs: [
                    {
                      transactionHash: "0xv5arbtx",
                      logIndex: "0x3",
                      topics: [
                        "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                        "0x0000000000000000000000001111111111111111111111111111111111111111",
                        `0x000000000000000000000000${arbRecipient
                          .toLowerCase()
                          .slice(2)}`,
                      ],
                      data: arbAmountHex,
                    },
                  ],
                },
              };
            }
            if (method === "eth_blockNumber") {
              return {
                jsonrpc: "2.0",
                id: 1,
                result: "0x6f",
              };
            }
          }
          if (request.transport === "http" && String(request.url).includes("/v1/transactions/v5trontx/events")) {
            return {
              confirmations: 21,
              data: [
                {
                  event_index: 2,
                  asset: "usdt",
                  recipient_address: tronRecipient,
                  amount_micro: tronAmount,
                  timestamp: "2026-02-14T00:00:00.000Z",
                },
              ],
            };
          }
          throw new Error(`unexpected request ${JSON.stringify(request)}`);
        },
      });

      const arbEvidence = provider.getTransferEvidence({
        chain: "arbitrum",
        asset: "usdc",
        tx_hash_or_id: "0xv5arbtx",
        recipient_address: arbRecipient,
        amount_expected_micro: arbAmount,
      });
      assert.ok(arbEvidence);
      assert.equal(arbEvidence.chain, "arbitrum");
      assert.equal(arbEvidence.asset, "usdc");
      assert.equal(arbEvidence.unique_id, "0xv5arbtx:3");
      assert.equal(arbEvidence.tx_hash, "0xv5arbtx");
      assert.equal(arbEvidence.transaction_id, null);
      assert.equal(Number.isInteger(arbEvidence.amount_micro), true);
      assert.equal(Number.isInteger(arbEvidence.confirmations), true);
      assert.equal(Number.isInteger(arbEvidence.event_index), true);
      assert.equal(Number.isInteger(arbEvidence.observed_at_epoch), true);

      const tronEvidence = provider.getTransferEvidence({
        chain: "tron",
        asset: "usdt",
        tx_hash_or_id: "v5trontx",
        recipient_address: tronRecipient,
        amount_expected_micro: tronAmount,
      });
      assert.ok(tronEvidence);
      assert.equal(tronEvidence.chain, "tron");
      assert.equal(tronEvidence.asset, "usdt");
      assert.equal(tronEvidence.unique_id, "v5trontx:2");
      assert.equal(tronEvidence.transaction_id, "v5trontx");
      assert.equal(tronEvidence.tx_hash, null);
      assert.equal(Number.isInteger(tronEvidence.amount_micro), true);
      assert.equal(Number.isInteger(tronEvidence.confirmations), true);
      assert.equal(Number.isInteger(tronEvidence.event_index), true);
      assert.equal(Number.isInteger(tronEvidence.observed_at_epoch), true);
    },
    "scripts/run-tests.js#V5-003"
  );

  await runTest(
    "V5-004 rpc-mode rejects recipient mismatch even when tx otherwise matches",
    () => {
      const railsMap = getPaymentRailsMap();
      const orderId = "v5-rpc-recipient-order";
      const expectedAmount = 4200000;
      const baseAmount = deriveBaseAmountForExpected(orderId, String(expectedAmount));
      const wrongRecipient = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
      const provider = createChainProvider({
        mode: "rpc",
        urls: {
          arbitrum: "http://arb.rpc.local",
          tron: "http://tron.rpc.local",
          ethereum: "http://eth.rpc.local",
        },
        fetchImpl: (request) => {
          if (request.transport === "jsonrpc" && request.body.method === "eth_getTransactionReceipt") {
            return {
              jsonrpc: "2.0",
              id: 1,
              result: {
                blockNumber: "0x64",
                logs: [
                  {
                    transactionHash: "0xv5reject",
                    logIndex: "0x0",
                    topics: [
                      "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                      "0x0000000000000000000000001111111111111111111111111111111111111111",
                      `0x000000000000000000000000${wrongRecipient.slice(2)}`,
                    ],
                    data: `0x${expectedAmount.toString(16).padStart(64, "0")}`,
                  },
                ],
              },
            };
          }
          if (request.transport === "jsonrpc" && request.body.method === "eth_blockNumber") {
            return {
              jsonrpc: "2.0",
              id: 1,
              result: "0x70",
            };
          }
          throw new Error("unexpected rpc call");
        },
      });

      const service = new MonetizationService({
        chain_provider: provider,
      });
      const created = service.createOrder({
        member_id: "v5-rpc-reject-member",
        requested_tier: "pro",
        asset: "USDC-L2",
        base_amount: baseAmount,
        order_id: orderId,
        created_at_ms: 1700000260000,
      });
      assert.equal(created.recipient_address, railsMap["USDC-L2"].recipient_address);

      const result = service.confirmOrder({
        order_id: orderId,
        chain: "arbitrum",
        tx_id: "0xv5reject",
      });
      assert.equal(result.state, ORDER_STATES.AWAITING_PAYMENT);
      assert.equal(result.match_status, "UNMATCHED");
    },
    "scripts/run-tests.js#V5-004"
  );

  await runTest(
    "V6-001 timeout path returns deterministic error and order remains non-ACTIVE",
    async () => {
      await withServer(
        async (baseUrl) => {
          const create = await fetchJson(`${baseUrl}/checkout/create`, {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-member-id": "v6-timeout-member",
              "x-idempotency-key": "v6-timeout-create",
              "x-now-ms": "1700000270000",
            },
            body: JSON.stringify({
              requested_tier: "pro",
              asset: "USDC-L2",
              base_amount: "11.000000",
              order_id: "v6-timeout-order",
            }),
          });
          assert.equal(create.status, 200);
          assert.equal(create.json.state, ORDER_STATES.AWAITING_PAYMENT);

          const confirm = await fetchJson(`${baseUrl}/checkout/confirm`, {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-member-id": "v6-timeout-member",
              "x-idempotency-key": "v6-timeout-confirm",
              "x-now-ms": "1700000271000",
            },
            body: JSON.stringify({
              order_id: "v6-timeout-order",
              chain: "arbitrum",
              tx_id: "0xv6timeout",
            }),
          });
          assert.equal(confirm.status, 504);
          assert.equal(confirm.json.error_code, "RPC_TIMEOUT");
          assert.equal(confirm.json.message, "RPC_TIMEOUT");

          const checkout = await fetchJson(
            `${baseUrl}/checkout?order_id=v6-timeout-order`,
            {
              headers: {
                "x-member-id": "v6-timeout-member",
                "x-now-ms": "1700000272000",
              },
            }
          );
          assert.equal(checkout.status, 200);
          assert.equal(checkout.json.state, ORDER_STATES.AWAITING_PAYMENT);
          assert.equal(checkout.json.credited_unique_id, null);
        },
        {
          chainMode: "rpc",
          arbitrumRpcUrl: "http://arb.rpc.local",
          tronRpcUrl: "http://tron.rpc.local",
          ethereumRpcUrl: "http://eth.rpc.local",
          rpcFetchImpl: () => {
            throw new Error("request timed out");
          },
        }
      );
    },
    "scripts/run-tests.js#V6-001"
  );

  await runTest(
    "V6-002 rpc retry bounded by configured max attempts",
    () => {
      const railsMap = getPaymentRailsMap();
      let attempts = 0;
      const backoffCalls = [];
      const provider = createChainProvider({
        mode: "rpc",
        urls: {
          tron: "http://tron.rpc.local",
          arbitrum: "http://arb.rpc.local",
          ethereum: "http://eth.rpc.local",
        },
        max_attempts: 3,
        base_backoff_ms: 7,
        sleep_impl: (ms) => {
          backoffCalls.push(ms);
        },
        fetchImpl: () => {
          attempts += 1;
          throw new Error("request timed out");
        },
      });

      assert.throws(
        () =>
          provider.getTransferEvidence({
            chain: "arbitrum",
            asset: "usdc",
            tx_hash_or_id: "0xv6retry",
            recipient_address: railsMap["USDC-L2"].recipient_address,
            amount_expected_micro: 1000000,
          }),
        (error) => {
          assert.equal(error.code, "RPC_TIMEOUT");
          return true;
        }
      );
      assert.equal(attempts, 3);
      assert.deepEqual(backoffCalls, [7, 14]);
    },
    "scripts/run-tests.js#V6-002"
  );

  await runTest(
    "V6-003 rpc rate-limit guard triggers deterministic error",
    () => {
      const railsMap = getPaymentRailsMap();
      let fetchCalls = 0;
      const provider = createChainProvider({
        mode: "rpc",
        urls: {
          tron: "http://tron.rpc.local",
          arbitrum: "http://arb.rpc.local",
          ethereum: "http://eth.rpc.local",
        },
        rate_limit_per_minute: 1,
        now_fn: () => 1700000280000,
        fetchImpl: (request) => {
          fetchCalls += 1;
          if (
            request.transport === "jsonrpc" &&
            request.body &&
            request.body.method === "eth_getTransactionReceipt"
          ) {
            return {
              jsonrpc: "2.0",
              id: 1,
              result: null,
            };
          }
          throw new Error(`unexpected request ${JSON.stringify(request)}`);
        },
      });

      assert.throws(
        () =>
          provider.getTransferEvidence({
            chain: "arbitrum",
            asset: "usdc",
            tx_hash_or_id: "0xv6rate",
            recipient_address: railsMap["USDC-L2"].recipient_address,
            amount_expected_micro: 1200000,
          }),
        (error) => {
          assert.equal(error.code, "RPC_TX_NOT_FOUND");
          return true;
        }
      );

      assert.throws(
        () =>
          provider.getTransferEvidence({
            chain: "arbitrum",
            asset: "usdc",
            tx_hash_or_id: "0xv6rate",
            recipient_address: railsMap["USDC-L2"].recipient_address,
            amount_expected_micro: 1200000,
          }),
        (error) => {
          assert.equal(error.code, "RPC_RATE_LIMITED");
          return true;
        }
      );
      assert.equal(fetchCalls, 1);
    },
    "scripts/run-tests.js#V6-003"
  );

  await runTest(
    "V6-004 provider error mapping does not mutate order state",
    async () => {
      await withServer(
        async (baseUrl) => {
          const create = await fetchJson(`${baseUrl}/checkout/create`, {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-member-id": "v6-bad-response-member",
              "x-idempotency-key": "v6-bad-create",
              "x-now-ms": "1700000290000",
            },
            body: JSON.stringify({
              requested_tier: "pro",
              asset: "USDC-L2",
              base_amount: "12.000000",
              order_id: "v6-bad-response-order",
            }),
          });
          assert.equal(create.status, 200);
          assert.equal(create.json.state, ORDER_STATES.AWAITING_PAYMENT);

          const confirm = await fetchJson(`${baseUrl}/checkout/confirm`, {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-member-id": "v6-bad-response-member",
              "x-idempotency-key": "v6-bad-confirm",
              "x-now-ms": "1700000291000",
            },
            body: JSON.stringify({
              order_id: "v6-bad-response-order",
              chain: "arbitrum",
              tx_id: "0xv6bad",
            }),
          });
          assert.equal(confirm.status, 502);
          assert.equal(confirm.json.error_code, "RPC_BAD_RESPONSE");
          assert.equal(confirm.json.message, "RPC_BAD_RESPONSE");

          const checkout = await fetchJson(
            `${baseUrl}/checkout?order_id=v6-bad-response-order`,
            {
              headers: {
                "x-member-id": "v6-bad-response-member",
                "x-now-ms": "1700000292000",
              },
            }
          );
          assert.equal(checkout.status, 200);
          assert.equal(checkout.json.state, ORDER_STATES.AWAITING_PAYMENT);
          assert.equal(checkout.json.credited_unique_id, null);
          assert.equal(checkout.json.match_status, "UNPAID");
        },
        {
          chainMode: "rpc",
          arbitrumRpcUrl: "http://arb.rpc.local",
          tronRpcUrl: "http://tron.rpc.local",
          ethereumRpcUrl: "http://eth.rpc.local",
          rpcFetchImpl: () => {
            throw new Error("invalid rpc payload");
          },
        }
      );
    },
    "scripts/run-tests.js#V6-004"
  );

  await runTest(
    "V7-001 status endpoint does not leak locked_data and returns stable shape",
    async () => {
      await withServer(async (baseUrl) => {
        const create = await fetchJson(`${baseUrl}/checkout/create`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-member-id": "v7-status-member",
            "x-idempotency-key": "v7-status-create",
            "x-now-ms": "1700000300000",
          },
          body: JSON.stringify({
            requested_tier: "pro",
            asset: "USDC-L2",
            base_amount: "13.000000",
            order_id: "v7-status-order",
          }),
        });
        assert.equal(create.status, 200);

        const status = await fetchJson(
          `${baseUrl}/checkout/status?order_id=v7-status-order`,
          {
            headers: {
              "x-member-id": "v7-status-member",
              "x-now-ms": "1700000301000",
            },
          }
        );
        assert.equal(status.status, 200);
        assert.equal(hasLockedData(status.json), false);
        assert.deepEqual(Object.keys(status.json).sort(), [
          "confirmations_observed",
          "expected_amount",
          "last_checked_at",
          "last_error_code",
          "order_id",
          "order_state",
          "rail",
        ]);
        assert.equal(status.json.order_state, ORDER_STATES.AWAITING_PAYMENT);
        assert.equal(typeof status.json.expected_amount, "string");
        assert.equal(typeof status.json.rail, "object");
        assert.equal(typeof status.json.confirmations_observed, "number");
      });
    },
    "scripts/run-tests.js#V7-001"
  );

  await runTest(
    "V7-002 NEEDS_CLAIM flow does not bypass exact-match and triggers reconcile attempt",
    async () => {
      const railsMap = getPaymentRailsMap();
      const expectedMicro = "25000000";
      const orderA = "v7-claim-order-a";
      const orderB = "v7-claim-order-b";
      const baseA = deriveBaseAmountForExpected(orderA, expectedMicro);
      const baseB = deriveBaseAmountForExpected(orderB, expectedMicro);
      const fixturesDir = path.join(process.cwd(), "tests", "fixtures", "chain");

      await withServer(
        async (baseUrl) => {
          const createA = await fetchJson(`${baseUrl}/checkout/create`, {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-member-id": "v7-claim-member",
              "x-idempotency-key": "v7-claim-create-a",
              "x-now-ms": "1700000310000",
            },
            body: JSON.stringify({
              requested_tier: "pro",
              asset: "USDT-TRON",
              base_amount: baseA,
              order_id: orderA,
            }),
          });
          const createB = await fetchJson(`${baseUrl}/checkout/create`, {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-member-id": "v7-claim-member",
              "x-idempotency-key": "v7-claim-create-b",
              "x-now-ms": "1700000310100",
            },
            body: JSON.stringify({
              requested_tier: "pro",
              asset: "USDT-TRON",
              base_amount: baseB,
              order_id: orderB,
            }),
          });
          assert.equal(createA.status, 200);
          assert.equal(createB.status, 200);

          const pay = await fetchJson(`${baseUrl}/checkout/pay`, {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-member-id": "v7-claim-member",
              "x-idempotency-key": "v7-claim-pay",
              "x-now-ms": "1700000310200",
            },
            body: JSON.stringify({
              order_id: orderA,
              chain: "tron",
              asset_symbol: "usdt",
              recipient_address: railsMap["USDT-TRON"].recipient_address,
              onchain_amount_micro: expectedMicro,
              confirmations: 20,
              transaction_id: "v7_claim_collision_tx",
              event_index: 0,
            }),
          });
          assert.equal(pay.status, 200);
          assert.equal(pay.json.settlement.outcome, "NEEDS_CLAIM");

          const claimCreate = await fetchJson(`${baseUrl}/claim/create`, {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-member-id": "v7-claim-member",
              "x-idempotency-key": "v7-claim-create",
              "x-now-ms": "1700000310300",
            },
            body: JSON.stringify({
              order_id: orderA,
            }),
          });
          assert.equal(claimCreate.status, 200);
          assert.equal(claimCreate.json.state, "CREATED");

          const claimSubmit = await fetchJson(`${baseUrl}/claim/submit`, {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-member-id": "v7-claim-member",
              "x-idempotency-key": "v7-claim-submit",
              "x-now-ms": "1700000310400",
            },
            body: JSON.stringify({
              order_id: orderA,
              chain: "tron",
              tx_id: "v4_tron_non_exact_tx",
            }),
          });
          assert.equal(claimSubmit.status, 200);
          assert.equal(claimSubmit.json.reconcile_scheduled, true);
          assert.equal(claimSubmit.json.claim.reconcile_attempts, 1);
          assert.notEqual(
            claimSubmit.json.order_status.order_state,
            ORDER_STATES.ACTIVE
          );
        },
        {
          chainMock: true,
          chainFixturesDir: fixturesDir,
        }
      );
    },
    "scripts/run-tests.js#V7-002"
  );

  await runTest(
    "V7-003 claim replay is idempotent and does not duplicate actions",
    async () => {
      const railsMap = getPaymentRailsMap();
      const expectedMicro = "25000000";
      const orderA = "v7-idem-order-a";
      const orderB = "v7-idem-order-b";
      const baseA = deriveBaseAmountForExpected(orderA, expectedMicro);
      const baseB = deriveBaseAmountForExpected(orderB, expectedMicro);
      const fixturesDir = path.join(process.cwd(), "tests", "fixtures", "chain");

      await withServer(
        async (baseUrl) => {
          for (const [orderId, baseAmount, idemKey] of [
            [orderA, baseA, "v7-idem-create-a"],
            [orderB, baseB, "v7-idem-create-b"],
          ]) {
            const create = await fetchJson(`${baseUrl}/checkout/create`, {
              method: "POST",
              headers: {
                "content-type": "application/json",
                "x-member-id": "v7-idem-member",
                "x-idempotency-key": idemKey,
                "x-now-ms": "1700000320000",
              },
              body: JSON.stringify({
                requested_tier: "pro",
                asset: "USDT-TRON",
                base_amount: baseAmount,
                order_id: orderId,
              }),
            });
            assert.equal(create.status, 200);
          }

          const pay = await fetchJson(`${baseUrl}/checkout/pay`, {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-member-id": "v7-idem-member",
              "x-idempotency-key": "v7-idem-pay",
              "x-now-ms": "1700000320100",
            },
            body: JSON.stringify({
              order_id: orderA,
              chain: "tron",
              asset_symbol: "usdt",
              recipient_address: railsMap["USDT-TRON"].recipient_address,
              onchain_amount_micro: expectedMicro,
              confirmations: 20,
              transaction_id: "v7_idem_collision_tx",
              event_index: 0,
            }),
          });
          assert.equal(pay.status, 200);
          assert.equal(pay.json.settlement.outcome, "NEEDS_CLAIM");

          const claimCreate = await fetchJson(`${baseUrl}/claim/create`, {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-member-id": "v7-idem-member",
              "x-idempotency-key": "v7-idem-claim-create",
              "x-now-ms": "1700000320200",
            },
            body: JSON.stringify({
              order_id: orderA,
            }),
          });
          assert.equal(claimCreate.status, 200);

          const payload = {
            order_id: orderA,
            chain: "tron",
            tx_id: "v4_tron_non_exact_tx",
          };
          const first = await fetchJson(`${baseUrl}/claim/submit`, {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-member-id": "v7-idem-member",
              "x-idempotency-key": "v7-idem-submit",
              "x-now-ms": "1700000320300",
            },
            body: JSON.stringify(payload),
          });
          const second = await fetchJson(`${baseUrl}/claim/submit`, {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "x-member-id": "v7-idem-member",
              "x-idempotency-key": "v7-idem-submit",
              "x-now-ms": "1700000320400",
            },
            body: JSON.stringify(payload),
          });
          assert.equal(first.status, 200);
          assert.equal(second.status, 200);
          assert.deepEqual(second.json, first.json);
          assert.equal(first.json.claim.reconcile_attempts, 1);
          assert.equal(first.json.claim.submissions.length, 1);
        },
        {
          chainMock: true,
          chainFixturesDir: fixturesDir,
        }
      );
    },
    "scripts/run-tests.js#V7-003"
  );

  await runTest(
    "V7-004 unauthorized access to status/claim is denied by entitlement rules",
    async () => {
      await withServer(async (baseUrl) => {
        const create = await fetchJson(`${baseUrl}/checkout/create`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-member-id": "v7-auth-owner",
            "x-idempotency-key": "v7-auth-create",
            "x-now-ms": "1700000330000",
          },
          body: JSON.stringify({
            requested_tier: "pro",
            asset: "USDC-L2",
            base_amount: "14.000000",
            order_id: "v7-auth-order",
          }),
        });
        assert.equal(create.status, 200);

        const statusNoAuth = await fetchJson(
          `${baseUrl}/checkout/status?order_id=v7-auth-order`
        );
        assert.equal(statusNoAuth.status, 401);
        assert.equal(statusNoAuth.json.error_code, "UNAUTHORIZED");

        const statusWrongMember = await fetchJson(
          `${baseUrl}/checkout/status?order_id=v7-auth-order`,
          {
            headers: {
              "x-member-id": "v7-auth-other",
              "x-now-ms": "1700000331000",
            },
          }
        );
        assert.equal(statusWrongMember.status, 403);
        assert.equal(statusWrongMember.json.error_code, "FORBIDDEN");

        const claimWrongMember = await fetchJson(`${baseUrl}/claim/create`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-member-id": "v7-auth-other",
            "x-idempotency-key": "v7-auth-claim",
            "x-now-ms": "1700000332000",
          },
          body: JSON.stringify({
            order_id: "v7-auth-order",
          }),
        });
        assert.equal(claimWrongMember.status, 403);
        assert.equal(claimWrongMember.json.error_code, "FORBIDDEN");
      });
    },
    "scripts/run-tests.js#V7-004"
  );

  const passCount = RESULTS.filter((item) => item.status === "PASS").length;
  const failCount = RESULTS.length - passCount;
  const summary = {
    total: RESULTS.length,
    pass: passCount,
    fail: failCount,
    generated_at: new Date().toISOString(),
  };

  const artifactDir = path.join(process.cwd(), "artifacts");
  fs.mkdirSync(artifactDir, { recursive: true });
  fs.writeFileSync(
    path.join(artifactDir, "test-results.json"),
    JSON.stringify({ summary, results: RESULTS }, null, 2),
    "utf8"
  );

  for (const item of RESULTS) {
    if (item.status === "PASS") {
      process.stdout.write(`PASS ${item.name}\n`);
    } else {
      process.stdout.write(`FAIL ${item.name}\n${item.error}\n`);
    }
  }
  process.stdout.write(
    `\nSummary: ${summary.pass} passed, ${summary.fail} failed, ${summary.total} total\n`
  );

  if (summary.fail > 0) {
    process.exitCode = 1;
  }
}

run().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
