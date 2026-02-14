const { createHash } = require("node:crypto");
const { PAYMENT_MATCH_WINDOW_MS } = require("./constants");
const { isValidPaymentRail } = require("./validators");
const {
  normalizePaymentAsset,
  normalizePaymentChain,
  resolveOrderRail,
} = require("./payment_rails");

function assertNonNegativeDecimalString(raw) {
  if (typeof raw !== "string" && typeof raw !== "number") {
    throw new Error("base_amount must be a decimal string or number");
  }

  const asString = String(raw);
  if (!/^\d+(\.\d+)?$/.test(asString)) {
    throw new Error("base_amount must be a non-negative decimal");
  }

  return asString;
}

function decimalToMicroHalfUp(baseAmount) {
  const amount = assertNonNegativeDecimalString(baseAmount);
  const [integerPart, fractionalPartRaw = ""] = amount.split(".");
  const firstSix = (fractionalPartRaw + "000000").slice(0, 6);
  const tieDigit = fractionalPartRaw.length > 6 ? Number(fractionalPartRaw[6]) : 0;

  let micro = BigInt(integerPart) * 1_000_000n + BigInt(firstSix);
  if (tieDigit >= 5) {
    micro += 1n;
  }
  return micro;
}

function microToAmountString(microValue) {
  const micro = BigInt(microValue);
  const integer = micro / 1_000_000n;
  const fractional = (micro % 1_000_000n).toString().padStart(6, "0");
  return `${integer.toString()}.${fractional}`;
}

function jitterMicroFromOrderId(orderId) {
  if (typeof orderId !== "string") {
    throw new Error("order_id must be a string");
  }

  const digest = createHash("sha256").update(Buffer.from(orderId, "utf8")).digest();
  const u32 = digest.readUInt32BE(0);
  return BigInt((u32 % 10000) * 100);
}

function computeExpectedAmount(orderId, baseAmount) {
  const base_amount_micro = decimalToMicroHalfUp(baseAmount);
  const jitter_micro = jitterMicroFromOrderId(orderId);
  const amount_expected_micro = base_amount_micro + jitter_micro;

  return {
    base_amount_micro,
    jitter_micro,
    amount_expected_micro,
    amount_expected: microToAmountString(amount_expected_micro),
  };
}

function parseMicroValue(value, fieldName) {
  if (typeof value === "bigint") {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isInteger(value) || value < 0) {
      throw new Error(`${fieldName} must be a non-negative integer`);
    }
    return BigInt(value);
  }
  if (typeof value === "string" && /^\d+$/.test(value)) {
    return BigInt(value);
  }
  throw new Error(`${fieldName} must be a non-negative integer`);
}

function buildChainUniqueId(event) {
  if (event.chain === "TRON") {
    if (event.transaction_id === undefined || event.event_index === undefined) {
      throw new Error("TRON events require transaction_id and event_index");
    }
    return `${event.transaction_id}:${event.event_index}`;
  }

  if (event.chain === "EVM") {
    if (event.tx_hash === undefined || event.log_index === undefined) {
      throw new Error("EVM events require tx_hash and log_index");
    }
    return `${event.tx_hash}:${event.log_index}`;
  }

  throw new Error(`Unsupported chain: ${event.chain}`);
}

function keysMatch(order, event) {
  return (
    order.chain === event.chain &&
    order.asset === event.asset &&
    order.recipient_address === event.recipient_address
  );
}

function withinWindow(order, event) {
  return (
    event.occurred_at_ms >= order.created_at_ms &&
    event.occurred_at_ms <= order.created_at_ms + PAYMENT_MATCH_WINDOW_MS
  );
}

class SettlementEngine {
  constructor() {
    this.orders = new Map();
    this.events = new Map();
  }

  createOrder(input) {
    if (this.orders.has(input.order_id)) {
      throw new Error(`Duplicate order_id: ${input.order_id}`);
    }
    if (!isValidPaymentRail(input.asset)) {
      throw new Error(`Unsupported payment rail: ${input.asset}`);
    }
    const rail = resolveOrderRail({
      railKey: input.asset,
      paymentAsset: input.payment_asset,
    });
    if (input.chain !== undefined && input.chain !== rail.chain_kind) {
      throw new Error(
        `Unsupported chain for rail ${input.asset}: ${input.chain}`
      );
    }

    const expected = computeExpectedAmount(input.order_id, input.base_amount);
    const order = {
      order_id: input.order_id,
      member_id: input.member_id,
      chain: input.chain || rail.chain_kind,
      asset: input.asset,
      payment_chain: rail.chain,
      payment_asset: rail.payment_asset,
      recipient_address: input.recipient_address || rail.recipient_address,
      base_amount: String(input.base_amount),
      base_amount_micro: expected.base_amount_micro,
      jitter_micro: expected.jitter_micro,
      amount_expected_micro: expected.amount_expected_micro,
      amount_expected: expected.amount_expected,
      created_at_ms: input.created_at_ms,
      identity_wallet: input.identity_wallet || null,
      status: "UNPAID",
      credited_unique_id: null,
    };

    this.orders.set(order.order_id, order);
    return order;
  }

  processPaymentEvent(inputEvent) {
    if (!isValidPaymentRail(inputEvent.asset)) {
      throw new Error(`Unsupported payment rail: ${inputEvent.asset}`);
    }
    const rail = resolveOrderRail({
      railKey: inputEvent.asset,
      paymentAsset:
        inputEvent.payment_asset !== undefined
          ? inputEvent.payment_asset
          : inputEvent.asset_symbol,
    });
    if (inputEvent.chain !== rail.chain_kind) {
      throw new Error(
        `Unsupported chain for rail ${inputEvent.asset}: ${inputEvent.chain}`
      );
    }
    const payloadChain = normalizePaymentChain(inputEvent.payment_chain);
    if (inputEvent.payment_chain !== undefined && !payloadChain) {
      throw new Error(`Unsupported payment chain: ${inputEvent.payment_chain}`);
    }
    if (payloadChain && payloadChain !== rail.chain) {
      throw new Error(
        `Payment chain mismatch, expected ${rail.chain}, got ${payloadChain}`
      );
    }
    const payloadAssetRaw =
      inputEvent.asset_symbol !== undefined
        ? inputEvent.asset_symbol
        : inputEvent.payment_asset;
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
      inputEvent.recipient_address !== undefined &&
      inputEvent.recipient_address !== rail.recipient_address
    ) {
      // Settlement engine allows overrides in test harness orders, so this only
      // rejects explicit payload recipient mismatch against rail SoT.
      const matchingOrderExists = Array.from(this.orders.values()).some(
        (order) =>
          order.asset === inputEvent.asset &&
          order.recipient_address === inputEvent.recipient_address
      );
      if (!matchingOrderExists) {
        throw new Error("recipient_address mismatch");
      }
    }
    const unique_id = buildChainUniqueId(inputEvent);
    if (this.events.has(unique_id)) {
      return {
        outcome: "DUPLICATE_EVENT",
        unique_id,
      };
    }

    const event = {
      unique_id,
      chain: inputEvent.chain,
      asset: inputEvent.asset,
      recipient_address: inputEvent.recipient_address,
      onchain_amount_micro: parseMicroValue(
        inputEvent.onchain_amount_micro,
        "onchain_amount_micro"
      ),
      payer_wallet: inputEvent.payer_wallet || null,
      occurred_at_ms: inputEvent.occurred_at_ms,
      status: "RECEIVED",
      candidate_order_ids: [],
    };

    const candidates = [];
    for (const order of this.orders.values()) {
      if (order.status === "PAID") {
        continue;
      }
      if (!keysMatch(order, event)) {
        continue;
      }
      if (!withinWindow(order, event)) {
        continue;
      }
      candidates.push(order);
    }

    const exactCandidates = candidates.filter(
      (order) => order.amount_expected_micro === event.onchain_amount_micro
    );

    if (exactCandidates.length === 0) {
      event.status = "UNMATCHED";
      this.events.set(unique_id, event);
      return {
        outcome: "UNMATCHED",
        unique_id,
      };
    }

    if (exactCandidates.length > 1) {
      event.status = "NEEDS_CLAIM";
      event.candidate_order_ids = exactCandidates.map((order) => order.order_id);
      for (const order of exactCandidates) {
        order.status = "NEEDS_CLAIM";
      }
      this.events.set(unique_id, event);
      return {
        outcome: "NEEDS_CLAIM",
        unique_id,
        order_ids: [...event.candidate_order_ids],
      };
    }

    const [winner] = exactCandidates;
    winner.status = "PAID";
    winner.credited_unique_id = unique_id;
    event.status = "CREDITED";
    event.candidate_order_ids = [winner.order_id];
    this.events.set(unique_id, event);

    return {
      outcome: "CREDITED",
      unique_id,
      order_id: winner.order_id,
    };
  }

  submitClaim({ member_id, order_id, unique_id }) {
    const order = this.orders.get(order_id);
    if (!order) {
      return { outcome: "CLAIM_REJECTED_ORDER_NOT_FOUND" };
    }

    const event = this.events.get(unique_id);
    if (!event) {
      return { outcome: "CLAIM_REJECTED_EVENT_NOT_FOUND" };
    }

    if (order.member_id !== member_id) {
      return { outcome: "CLAIM_REJECTED_MEMBER_MISMATCH" };
    }

    if (order.status === "PAID") {
      return { outcome: "CLAIM_ALREADY_PAID" };
    }

    if (!keysMatch(order, event) || !withinWindow(order, event)) {
      return { outcome: "CLAIM_REJECTED_KEY_MISMATCH" };
    }

    if (order.amount_expected_micro !== event.onchain_amount_micro) {
      return { outcome: "CLAIM_REJECTED_NON_EXACT" };
    }

    if (
      event.status === "NEEDS_CLAIM" &&
      event.candidate_order_ids.length > 0 &&
      !event.candidate_order_ids.includes(order_id)
    ) {
      return { outcome: "CLAIM_REJECTED_ORDER_NOT_IN_COLLISION_SET" };
    }

    order.status = "PAID";
    order.credited_unique_id = unique_id;
    event.status = "CLAIM_CREDITED";
    event.candidate_order_ids = [order.order_id];

    return {
      outcome: "CLAIM_CREDITED",
      order_id,
      unique_id,
    };
  }
}

module.exports = {
  SettlementEngine,
  buildChainUniqueId,
  computeExpectedAmount,
  decimalToMicroHalfUp,
  jitterMicroFromOrderId,
  microToAmountString,
};
