const fs = require("node:fs");
const path = require("node:path");
const { randomUUID, createHash } = require("node:crypto");

const { checkEntitlement, normalizeTier } = require("./entitlements");
const { buildPageMeta } = require("./i18n_meta");
const { PAYMENT_MATCH_WINDOW_MS } = require("./constants");
const { isConfirmationSufficient } = require("./confirmations");
const {
  normalizeLocale,
} = require("./validators");
const {
  getPaymentRailKeys,
  getPublicRails,
  normalizePaymentAsset,
  normalizePaymentChain,
  resolveOrderRail,
} = require("./payment_rails");
const { createChainProviderFromEnv } = require("./chain_provider");
const { buildChainUniqueId, computeExpectedAmount } = require("./settlement");

const ORDER_STATES = {
  CREATED: "CREATED",
  AWAITING_PAYMENT: "AWAITING_PAYMENT",
  CONFIRMED: "CONFIRMED",
  ACTIVE: "ACTIVE",
};

const DEFAULT_STATE_VERSION = 1;

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function stableStringify(value) {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  }
  const keys = Object.keys(value).sort();
  const parts = keys.map(
    (key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`
  );
  return `{${parts.join(",")}}`;
}

function hashRequestBody(value) {
  const normalized = stableStringify(value ?? {});
  return createHash("sha256").update(normalized, "utf8").digest("hex");
}

function toMs(rawValue, fieldName) {
  const value = Number(rawValue);
  if (!Number.isFinite(value) || value < 0) {
    throw new Error(`${fieldName} must be a non-negative number`);
  }
  return Math.floor(value);
}

function toConfirmations(rawValue) {
  const value = Number(rawValue ?? 0);
  if (!Number.isFinite(value) || value < 0) {
    throw new Error("confirmations must be a non-negative number");
  }
  return Math.floor(value);
}

function parseMicro(rawValue) {
  if (typeof rawValue === "bigint") {
    if (rawValue < 0n) {
      throw new Error("onchain_amount_micro must be >= 0");
    }
    return rawValue;
  }
  if (typeof rawValue === "number") {
    if (!Number.isInteger(rawValue) || rawValue < 0) {
      throw new Error("onchain_amount_micro must be a non-negative integer");
    }
    return BigInt(rawValue);
  }
  if (typeof rawValue === "string" && /^\d+$/.test(rawValue)) {
    return BigInt(rawValue);
  }
  throw new Error("onchain_amount_micro must be a non-negative integer");
}

function hasChainProofInput(input) {
  return (
    input.chain !== undefined ||
    input.tx_id !== undefined ||
    input.tx_hash !== undefined
  );
}

function normalizeRequestedTier(rawTier) {
  const normalized = normalizeTier(rawTier);
  if (!normalized) {
    throw new Error("requested_tier is invalid");
  }
  if (normalized === "free") {
    throw new Error("requested_tier must be pro|elite|buyout");
  }
  return normalized;
}

class MonetizationService {
  constructor(options = {}) {
    this.persistence_path =
      options.persistence_path && String(options.persistence_path).trim() !== ""
        ? String(options.persistence_path)
        : null;
    this.orders = new Map();
    this.entitlements = new Map();
    this.payments = new Map();
    this.idempotency = new Map();
    this.audit_trail = [];
    this.reconcile_timer = null;
    this.reconcile_provider = null;
    this.chain_provider = createChainProviderFromEnv(options);

    if (this.persistence_path) {
      this.#loadState();
    }

    if (options.enable_reconcile_timer) {
      this.startReconcileTimer({
        interval_ms: options.reconcile_interval_ms,
        getConfirmationsByUniqueId: options.getConfirmationsByUniqueId,
      });
    }
  }

  dispose() {
    this.stopReconcileTimer();
  }

  executeIdempotent({
    scope,
    member_id,
    idempotency_key,
    request_body,
    status_code = 200,
    handler,
  }) {
    if (!scope) {
      throw new Error("scope is required");
    }
    if (!member_id) {
      throw new Error("member_id is required");
    }
    if (!idempotency_key || String(idempotency_key).trim() === "") {
      throw new Error("x-idempotency-key is required");
    }
    if (typeof handler !== "function") {
      throw new Error("handler must be a function");
    }

    const fullKey = `${scope}:${member_id}:${String(idempotency_key).trim()}`;
    const request_hash = hashRequestBody(request_body);
    const existing = this.idempotency.get(fullKey);
    if (existing) {
      if (existing.request_hash !== request_hash) {
        throw new Error("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD");
      }
      return {
        replayed: true,
        status_code: existing.status_code,
        response: deepClone(existing.response),
      };
    }

    const response = handler();
    this.idempotency.set(fullKey, {
      key: fullKey,
      request_hash,
      status_code,
      response: deepClone(response),
      created_at_ms: Date.now(),
    });
    this.#saveState();
    return {
      replayed: false,
      status_code,
      response,
    };
  }

  buildPlanPayload({ locale } = {}) {
    const normalizedLocale = normalizeLocale(locale || "zh-Hant");
    if (!normalizedLocale) {
      throw new Error(`Unsupported locale: ${locale}`);
    }

    return {
      page: "plan",
      locale: normalizedLocale,
      rails: getPaymentRailKeys(),
      rail_options: getPublicRails(),
      plans: [
        {
          tier: "free",
          summary: "single-indicator snapshot",
        },
        {
          tier: "pro",
          summary: "realtime signal and push with x+y combos",
        },
        {
          tier: "elite",
          summary: "3+ combos and advanced features",
        },
      ],
      meta: buildPageMeta("/plan", normalizedLocale),
    };
  }

  createOrder(input) {
    if (!input || typeof input !== "object") {
      throw new Error("createOrder input is required");
    }
    const order_id = input.order_id ? String(input.order_id) : randomUUID();
    if (this.orders.has(order_id)) {
      throw new Error(`Duplicate order_id: ${order_id}`);
    }
    const member_id = String(input.member_id || "").trim();
    if (!member_id) {
      throw new Error("member_id is required");
    }
    const requested_tier = normalizeRequestedTier(input.requested_tier);
    const rail = resolveOrderRail({
      railKey: input.asset,
      paymentAsset:
        input.payment_asset !== undefined
          ? input.payment_asset
          : input.asset_symbol,
    });
    const requestedChain = normalizePaymentChain(input.chain);
    if (input.chain !== undefined && !requestedChain) {
      throw new Error(`Unsupported payment chain: ${input.chain}`);
    }
    if (requestedChain && requestedChain !== rail.chain) {
      throw new Error(
        `Payment chain mismatch, expected ${rail.chain}, got ${requestedChain}`
      );
    }
    const base_amount = String(input.base_amount ?? "");
    if (!base_amount || !/^\d+(\.\d+)?$/.test(base_amount)) {
      throw new Error("base_amount must be a non-negative decimal");
    }
    const created_at_ms = toMs(input.created_at_ms ?? Date.now(), "created_at_ms");
    const expected = computeExpectedAmount(order_id, base_amount);

    const order = {
      order_id,
      member_id,
      requested_tier,
      unlocked_tier: "free",
      asset: rail.rail_key,
      payment_chain: rail.chain,
      payment_asset: rail.payment_asset,
      chain: rail.chain_kind,
      chain_profile: rail.chain_profile,
      recipient_address: rail.recipient_address,
      base_amount,
      base_amount_micro: expected.base_amount_micro.toString(),
      jitter_micro: expected.jitter_micro.toString(),
      amount_expected_micro: expected.amount_expected_micro.toString(),
      amount_expected: expected.amount_expected,
      identity_wallet: input.identity_wallet || null,
      payer_wallet: null,
      state: ORDER_STATES.CREATED,
      created_at_ms,
      updated_at_ms: created_at_ms,
      credited_unique_id: null,
      payment_status: "UNPAID",
      match_status: "UNPAID",
      confirmations: 0,
      state_history: [],
    };

    this.#transition(order, ORDER_STATES.AWAITING_PAYMENT, "ORDER_CREATED", created_at_ms);
    this.orders.set(order_id, order);
    this.#saveState();
    return this.#serializeOrder(order);
  }

  getOrder(order_id) {
    const order = this.orders.get(order_id);
    if (!order) {
      return null;
    }
    const rail = resolveOrderRail({
      railKey: order.asset,
      paymentAsset: order.payment_asset,
    });
    const serialized = this.#serializeOrder(order);
    serialized.recipient_address = rail.recipient_address;
    serialized.payment_chain = rail.chain;
    serialized.payment_asset = rail.payment_asset;
    return serialized;
  }

  submitPayment(input) {
    if (!input || typeof input !== "object") {
      throw new Error("submitPayment input is required");
    }
    const order = this.orders.get(input.order_id);
    if (!order) {
      throw new Error("order not found");
    }
    const rail = resolveOrderRail({
      railKey: order.asset,
      paymentAsset: order.payment_asset,
    });
    const payloadChain = normalizePaymentChain(input.chain);
    if (input.chain !== undefined && !payloadChain) {
      throw new Error(`Unsupported payment chain: ${input.chain}`);
    }
    if (payloadChain && payloadChain !== rail.chain) {
      throw new Error(
        `Payment chain mismatch, expected ${rail.chain}, got ${payloadChain}`
      );
    }
    const payloadAssetRaw =
      input.asset_symbol !== undefined
        ? input.asset_symbol
        : input.payment_asset !== undefined
          ? input.payment_asset
          : undefined;
    const payloadAsset = normalizePaymentAsset(payloadAssetRaw);
    if (payloadAssetRaw !== undefined && !payloadAsset) {
      throw new Error(`Unsupported payment asset: ${payloadAssetRaw}`);
    }
    if (payloadAsset && payloadAsset !== rail.payment_asset) {
      throw new Error(
        `Payment asset mismatch, expected ${rail.payment_asset}, got ${payloadAsset}`
      );
    }
    if (
      input.recipient_address !== undefined &&
      input.recipient_address !== rail.recipient_address
    ) {
      throw new Error("recipient_address mismatch");
    }

    const occurred_at_ms = toMs(input.occurred_at_ms ?? Date.now(), "occurred_at_ms");

    const unique_id = buildChainUniqueId({
      chain: order.chain,
      transaction_id: input.transaction_id,
      event_index: input.event_index,
      tx_hash: input.tx_hash,
      log_index: input.log_index,
    });
    const confirmations = toConfirmations(input.confirmations);

    const duplicate = this.payments.get(unique_id);
    if (duplicate) {
      if (duplicate.order_id === order.order_id && confirmations > duplicate.confirmations) {
        duplicate.confirmations = confirmations;
        if (confirmations > order.confirmations) {
          order.confirmations = confirmations;
        }
        if (
          order.state === ORDER_STATES.CONFIRMED &&
          isConfirmationSufficient(order.chain_profile, order.confirmations)
        ) {
          this.#activateOrder(order, "DUPLICATE_EVENT_CONFIRMATIONS_UPDATED", Date.now());
        }
        this.#saveState();
      }
      return {
        settlement: {
          outcome: "DUPLICATE_EVENT",
          unique_id,
          order_id: duplicate.order_id || null,
        },
        order: this.#serializeOrder(order),
      };
    }

    const onchain_amount_micro = parseMicro(input.onchain_amount_micro);
    const paymentRecord = {
      unique_id,
      order_id: order.order_id,
      chain: order.chain,
      asset: order.asset,
      recipient_address: rail.recipient_address,
      occurred_at_ms,
      onchain_amount_micro: onchain_amount_micro.toString(),
      confirmations,
      outcome: "RECEIVED",
      candidate_order_ids: [],
      payer_wallet: input.payer_wallet || null,
      transaction_id: input.transaction_id || null,
      tx_hash: input.tx_hash || null,
      event_index:
        input.event_index !== undefined
          ? toConfirmations(input.event_index)
          : input.log_index !== undefined
            ? toConfirmations(input.log_index)
            : null,
    };

    if (onchain_amount_micro !== BigInt(order.amount_expected_micro)) {
      paymentRecord.outcome = "UNMATCHED";
      order.match_status = "UNMATCHED";
      this.payments.set(unique_id, paymentRecord);
      this.#saveState();
      return {
        settlement: {
          outcome: "UNMATCHED",
          unique_id,
        },
        order: this.#serializeOrder(order),
      };
    }

    const collisions = this.#findCollisionCandidates(order, occurred_at_ms);
    if (collisions.length > 1) {
      paymentRecord.outcome = "NEEDS_CLAIM";
      paymentRecord.candidate_order_ids = collisions.map((item) => item.order_id);
      for (const collisionOrder of collisions) {
        collisionOrder.match_status = "NEEDS_CLAIM";
      }
      this.payments.set(unique_id, paymentRecord);
      this.#saveState();
      return {
        settlement: {
          outcome: "NEEDS_CLAIM",
          unique_id,
          order_ids: [...paymentRecord.candidate_order_ids],
        },
        order: this.#serializeOrder(order),
      };
    }

    paymentRecord.outcome = "CREDITED";
    paymentRecord.candidate_order_ids = [order.order_id];
    this.payments.set(unique_id, paymentRecord);

    order.payment_status = "CREDITED";
    order.match_status = "EXACT_MATCH";
    order.payer_wallet = input.payer_wallet || null;
    order.credited_unique_id = unique_id;
    order.confirmations = confirmations;

    this.#transition(
      order,
      ORDER_STATES.CONFIRMED,
      "PAYMENT_MATCHED_EXACT",
      occurred_at_ms
    );
    if (isConfirmationSufficient(order.chain_profile, confirmations)) {
      this.#activateOrder(order, "CONFIRMATIONS_SUFFICIENT", occurred_at_ms);
    }
    this.#saveState();

    return {
      settlement: {
        outcome: "CREDITED",
        unique_id,
        order_id: order.order_id,
      },
      order: this.#serializeOrder(order),
    };
  }

  confirmOrder(input) {
    if (!input || typeof input !== "object") {
      throw new Error("confirmOrder input is required");
    }
    const order = this.orders.get(input.order_id);
    if (!order) {
      throw new Error("order not found");
    }
    if (hasChainProofInput(input)) {
      return this.#confirmOrderByChainProof(order, input);
    }
    const confirmations = toConfirmations(input.confirmations);
    if (confirmations > order.confirmations) {
      order.confirmations = confirmations;
    }
    if (order.credited_unique_id && this.payments.has(order.credited_unique_id)) {
      const payment = this.payments.get(order.credited_unique_id);
      if (confirmations > payment.confirmations) {
        payment.confirmations = confirmations;
      }
    }

    if (
      order.state === ORDER_STATES.CONFIRMED &&
      isConfirmationSufficient(order.chain_profile, order.confirmations)
    ) {
      this.#activateOrder(order, "CONFIRM_ENDPOINT_CONFIRMED", Date.now());
    }

    this.#saveState();
    return this.#serializeOrder(order);
  }

  #confirmOrderByChainProof(order, input) {
    const txId = String(input.tx_id || input.tx_hash || "").trim();
    if (!txId) {
      throw new Error("tx_id is required for chain proof confirm");
    }
    const rail = resolveOrderRail({
      railKey: order.asset,
      paymentAsset: order.payment_asset,
    });
    const chain = normalizePaymentChain(input.chain || rail.chain);
    if (!chain) {
      throw new Error(`Unsupported payment chain: ${input.chain}`);
    }
    if (chain !== rail.chain) {
      throw new Error(`Payment chain mismatch, expected ${rail.chain}, got ${chain}`);
    }
    if (!["tron", "arbitrum"].includes(chain)) {
      throw new Error(`v0.4 chain proof not supported for ${chain}`);
    }
    if (!this.chain_provider) {
      throw new Error("chain provider is not configured");
    }
    if (typeof this.chain_provider.getTransferEvidence !== "function") {
      throw new Error("chain provider does not implement getTransferEvidence");
    }

    const evidence = this.chain_provider.getTransferEvidence({
      chain,
      asset: rail.payment_asset,
      tx_hash_or_id: txId,
      recipient_address: rail.recipient_address,
      amount_expected_micro: order.amount_expected_micro,
    });
    if (!evidence) {
      order.match_status = "UNMATCHED";
      this.#saveState();
      return this.#serializeOrder(order);
    }
    if (normalizePaymentAsset(evidence.asset) !== rail.payment_asset) {
      order.match_status = "UNMATCHED";
      this.#saveState();
      return this.#serializeOrder(order);
    }
    const occurredAtMs = Number.isFinite(Number(evidence.observed_at_epoch))
      ? Number(evidence.observed_at_epoch)
      : Date.now();
    const paymentInput = {
      order_id: order.order_id,
      chain,
      asset_symbol: rail.payment_asset,
      recipient_address: rail.recipient_address,
      onchain_amount_micro: String(evidence.amount_micro),
      confirmations:
        evidence.confirmations !== undefined
          ? toConfirmations(evidence.confirmations)
          : toConfirmations(input.confirmations),
      occurred_at_ms: Number.isFinite(occurredAtMs) ? occurredAtMs : Date.now(),
      tx_id: txId,
    };
    if (chain === "tron") {
      paymentInput.transaction_id =
        evidence.transaction_id || evidence.tx_hash || txId;
      paymentInput.event_index = toConfirmations(
        evidence.event_index
      );
    } else {
      paymentInput.tx_hash = evidence.tx_hash || evidence.transaction_id || txId;
      paymentInput.log_index = toConfirmations(
        evidence.event_index
      );
    }

    this.submitPayment(paymentInput);
    return this.#serializeOrder(order);
  }

  runReconcile({ now_ms, confirmations_by_unique_id } = {}) {
    const nowMs = toMs(now_ms ?? Date.now(), "now_ms");
    const updates =
      confirmations_by_unique_id instanceof Map
        ? confirmations_by_unique_id
        : new Map(Object.entries(confirmations_by_unique_id || {}));

    let checked = 0;
    let activated = 0;
    let updated_confirmations = 0;
    for (const order of this.orders.values()) {
      if (order.state !== ORDER_STATES.CONFIRMED || !order.credited_unique_id) {
        continue;
      }
      checked += 1;
      const payment = this.payments.get(order.credited_unique_id);
      if (!payment) {
        continue;
      }

      const updateValue = updates.get(order.credited_unique_id);
      if (updateValue !== undefined) {
        const nextConfirmations = toConfirmations(updateValue);
        if (nextConfirmations > payment.confirmations) {
          payment.confirmations = nextConfirmations;
          order.confirmations = nextConfirmations;
          updated_confirmations += 1;
        }
      } else if (this.chain_provider && typeof this.chain_provider.getTransferEvidence === "function") {
        try {
          const txId = payment.transaction_id || payment.tx_hash;
          if (txId) {
            const evidence = this.chain_provider.getTransferEvidence({
              chain: order.payment_chain,
              asset: order.payment_asset,
              tx_hash_or_id: txId,
              recipient_address: order.recipient_address,
              amount_expected_micro: order.amount_expected_micro,
            });
            if (evidence) {
              const nextConfirmations = toConfirmations(evidence.confirmations);
              if (nextConfirmations > payment.confirmations) {
                payment.confirmations = nextConfirmations;
                order.confirmations = nextConfirmations;
                updated_confirmations += 1;
              }
            }
          }
        } catch (error) {
          // Keep reconcile robust for partial provider outages/misconfig.
        }
      }

      if (isConfirmationSufficient(order.chain_profile, order.confirmations)) {
        const changed = this.#activateOrder(order, "RECONCILE_CONFIRMED", nowMs);
        if (changed) {
          activated += 1;
        }
      }
    }

    if (checked > 0 || updated_confirmations > 0 || activated > 0) {
      this.#saveState();
    }

    return {
      checked,
      activated,
      updated_confirmations,
    };
  }

  startReconcileTimer({ interval_ms = 15_000, getConfirmationsByUniqueId } = {}) {
    if (this.reconcile_timer) {
      return false;
    }
    this.reconcile_provider =
      typeof getConfirmationsByUniqueId === "function"
        ? getConfirmationsByUniqueId
        : null;
    const interval = toMs(interval_ms, "interval_ms");
    this.reconcile_timer = setInterval(() => {
      const updatePayload = this.reconcile_provider
        ? this.reconcile_provider()
        : {};
      this.runReconcile({
        confirmations_by_unique_id: updatePayload,
        now_ms: Date.now(),
      });
    }, interval);
    if (typeof this.reconcile_timer.unref === "function") {
      this.reconcile_timer.unref();
    }
    return true;
  }

  stopReconcileTimer() {
    if (!this.reconcile_timer) {
      return false;
    }
    clearInterval(this.reconcile_timer);
    this.reconcile_timer = null;
    this.reconcile_provider = null;
    return true;
  }

  isFeatureUnlocked(member_id, feature) {
    const key = String(member_id || "");
    const entitlement = this.entitlements.get(key);
    const tier = entitlement ? entitlement.tier : "free";
    return checkEntitlement({
      member_id: key,
      tier,
      feature,
    });
  }

  getAuditTrail() {
    return deepClone(this.audit_trail);
  }

  #findCollisionCandidates(order, occurredAtMs) {
    const expected = order.amount_expected_micro;
    const results = [];
    for (const item of this.orders.values()) {
      if (item.state === ORDER_STATES.ACTIVE) {
        continue;
      }
      if (item.chain !== order.chain || item.asset !== order.asset) {
        continue;
      }
      if (item.recipient_address !== order.recipient_address) {
        continue;
      }
      if (item.amount_expected_micro !== expected) {
        continue;
      }
      const inWindow =
        occurredAtMs >= item.created_at_ms &&
        occurredAtMs <= item.created_at_ms + PAYMENT_MATCH_WINDOW_MS;
      if (!inWindow) {
        continue;
      }
      results.push(item);
    }
    return results;
  }

  #transition(order, nextState, reason, atMs) {
    if (order.state === nextState) {
      return false;
    }
    const entry = {
      order_id: order.order_id,
      from_state: order.state,
      to_state: nextState,
      reason,
      at_ms: atMs,
    };
    order.state = nextState;
    order.updated_at_ms = atMs;
    order.state_history.push(entry);
    this.audit_trail.push({
      kind: "ORDER_STATE_TRANSITION",
      ...entry,
    });
    return true;
  }

  #activateOrder(order, reason, atMs) {
    const changed = this.#transition(order, ORDER_STATES.ACTIVE, reason, atMs);
    if (!changed) {
      return false;
    }
    order.unlocked_tier = order.requested_tier;
    const existing = this.entitlements.get(order.member_id);
    if (
      !existing ||
      existing.tier !== order.requested_tier ||
      existing.order_id !== order.order_id
    ) {
      this.entitlements.set(order.member_id, {
        member_id: order.member_id,
        tier: order.requested_tier,
        order_id: order.order_id,
        activated_at_ms: atMs,
      });
      this.audit_trail.push({
        kind: "ENTITLEMENT_GRANTED",
        member_id: order.member_id,
        tier: order.requested_tier,
        order_id: order.order_id,
        at_ms: atMs,
      });
    }
    return true;
  }

  #serializeOrder(order) {
    return deepClone(order);
  }

  #loadState() {
    if (!this.persistence_path || !fs.existsSync(this.persistence_path)) {
      return;
    }
    const raw = fs.readFileSync(this.persistence_path, "utf8");
    if (!raw.trim()) {
      return;
    }
    const parsed = JSON.parse(raw);
    if (parsed.version !== DEFAULT_STATE_VERSION) {
      return;
    }

    for (const order of parsed.orders || []) {
      try {
        const rail = resolveOrderRail({
          railKey: order.asset,
          paymentAsset: order.payment_asset,
        });
        order.recipient_address = rail.recipient_address;
        order.payment_chain = rail.chain;
        order.payment_asset = rail.payment_asset;
        order.chain = rail.chain_kind;
        order.chain_profile = rail.chain_profile;
      } catch (error) {
        // Keep backward compatibility for legacy records while still loading state.
      }
      this.orders.set(order.order_id, order);
    }
    for (const entry of parsed.entitlements || []) {
      this.entitlements.set(entry.member_id, entry);
    }
    for (const payment of parsed.payments || []) {
      this.payments.set(payment.unique_id, payment);
    }
    for (const idem of parsed.idempotency || []) {
      this.idempotency.set(idem.key, idem);
    }
    this.audit_trail = Array.isArray(parsed.audit_trail)
      ? parsed.audit_trail
      : [];
  }

  #saveState() {
    if (!this.persistence_path) {
      return;
    }
    const state = {
      version: DEFAULT_STATE_VERSION,
      orders: Array.from(this.orders.values()),
      entitlements: Array.from(this.entitlements.values()),
      payments: Array.from(this.payments.values()),
      idempotency: Array.from(this.idempotency.values()),
      audit_trail: this.audit_trail,
    };
    const dir = path.dirname(this.persistence_path);
    fs.mkdirSync(dir, { recursive: true });
    const tmpPath = `${this.persistence_path}.tmp`;
    fs.writeFileSync(tmpPath, JSON.stringify(state, null, 2), "utf8");
    fs.renameSync(tmpPath, this.persistence_path);
  }
}

module.exports = {
  MonetizationService,
  ORDER_STATES,
};
