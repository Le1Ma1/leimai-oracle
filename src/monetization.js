const { buildPageMeta, buildLocalizedPath } = require("./i18n_meta");
const { SettlementEngine, computeExpectedAmount } = require("./settlement");
const { getRequiredConfirmations } = require("./confirmations");
const { checkEntitlement } = require("./entitlements");
const { isValidPaymentRail, normalizeLocale } = require("./validators");

const ORDER_STATES = {
  CREATED: "CREATED",
  AWAITING_PAYMENT: "AWAITING_PAYMENT",
  CONFIRMED: "CONFIRMED",
  ACTIVE: "ACTIVE",
};

const TIER_RANK = {
  free: 0,
  pro: 1,
  elite: 2,
  buyout: 3,
};

function railToSettlementChain(asset) {
  if (asset === "USDT-TRON") {
    return "TRON";
  }
  return "EVM";
}

function railToChainProfile(asset) {
  if (asset === "USDT-TRON") {
    return "TRON";
  }
  if (asset === "USDC-L2") {
    return "L2";
  }
  if (asset === "ERC20") {
    return "ERC20";
  }
  return null;
}

function chooseHigherTier(current, candidate) {
  const currentTier = current || "free";
  const candidateTier = candidate || "free";
  return TIER_RANK[candidateTier] > TIER_RANK[currentTier]
    ? candidateTier
    : currentTier;
}

class MonetizationService {
  constructor() {
    this.orders = new Map();
    this.orderCounter = 0;
    this.settlement = new SettlementEngine();
    this.memberTier = new Map();
  }

  buildPlanPayload({ locale = "zh-Hant" }) {
    const normalizedLocale = normalizeLocale(locale) || "zh-Hant";
    return {
      page: "plan",
      locale: normalizedLocale,
      path: buildLocalizedPath("/plan", normalizedLocale),
      meta: buildPageMeta("/plan", normalizedLocale),
      plans: [
        {
          tier: "free",
          features: ["single_indicator_snapshot"],
        },
        {
          tier: "pro",
          features: ["realtime_signal", "push", "combo_xy"],
        },
        {
          tier: "elite",
          features: ["realtime_signal", "push", "combo_xy", "combo_3plus", "advanced_features"],
        },
      ],
      rails: ["USDT-TRON", "USDC-L2", "ERC20"],
    };
  }

  createOrder(input) {
    const member_id = input.member_id || "anon";
    const requested_tier = String(input.requested_tier || "pro").toLowerCase();
    if (!["pro", "elite"].includes(requested_tier)) {
      throw new Error("requested_tier must be pro or elite");
    }

    const asset = input.asset || "USDT-TRON";
    if (!isValidPaymentRail(asset)) {
      throw new Error(`Unsupported payment rail: ${asset}`);
    }

    const chainProfile = railToChainProfile(asset);
    const requiredConfirmations = getRequiredConfirmations(chainProfile);
    if (requiredConfirmations === null) {
      throw new Error(`Unsupported chain profile for asset: ${asset}`);
    }

    this.orderCounter += 1;
    const order_id = input.order_id || `ord_${this.orderCounter}`;
    const settlementChain = railToSettlementChain(asset);
    const recipient_address =
      input.recipient_address ||
      (settlementChain === "TRON" ? "TRON_WALLET_1" : "EVM_WALLET_1");
    const base_amount = input.base_amount || "10.000000";
    const nowMs = Number(input.created_at_ms || Date.now());

    const expected = computeExpectedAmount(order_id, base_amount);
    this.settlement.createOrder({
      order_id,
      member_id,
      chain: settlementChain,
      asset,
      recipient_address,
      base_amount,
      created_at_ms: nowMs,
      identity_wallet: input.identity_wallet || null,
    });

    const order = {
      order_id,
      member_id,
      requested_tier,
      state: ORDER_STATES.CREATED,
      settlement_chain: settlementChain,
      chain_profile: chainProfile,
      required_confirmations: requiredConfirmations,
      recipient_address,
      base_amount,
      amount_expected_micro: expected.amount_expected_micro.toString(),
      amount_expected: expected.amount_expected,
      identity_wallet: input.identity_wallet || null,
      payer_wallet: null,
      confirmation_count: 0,
      settlement_outcome: null,
      unique_id: null,
      created_at_ms: nowMs,
      state_history: [ORDER_STATES.CREATED],
    };

    this._transition(order, ORDER_STATES.AWAITING_PAYMENT);
    this.orders.set(order_id, order);
    return this._publicOrder(order);
  }

  getOrder(order_id) {
    const order = this.orders.get(order_id);
    if (!order) {
      return null;
    }
    return this._publicOrder(order);
  }

  submitPayment(input) {
    const order = this.orders.get(input.order_id);
    if (!order) {
      throw new Error("order not found");
    }

    const event = {
      chain: order.settlement_chain,
      asset: order.chain_profile === "TRON" ? "USDT-TRON" : order.chain_profile === "L2" ? "USDC-L2" : "ERC20",
      recipient_address: order.recipient_address,
      onchain_amount_micro: input.onchain_amount_micro,
      occurred_at_ms: Number(input.occurred_at_ms || Date.now()),
      payer_wallet: input.payer_wallet || null,
    };
    if (order.settlement_chain === "TRON") {
      event.transaction_id = input.transaction_id;
      event.event_index = input.event_index;
    } else {
      event.tx_hash = input.tx_hash;
      event.log_index = input.log_index;
    }

    const settlementResult = this.settlement.processPaymentEvent(event);
    order.settlement_outcome = settlementResult.outcome;
    order.payer_wallet = input.payer_wallet || null;
    order.confirmation_count = Number(input.confirmations || 0);
    order.unique_id = settlementResult.unique_id || order.unique_id;

    if (settlementResult.outcome === "CREDITED") {
      if (order.confirmation_count >= order.required_confirmations) {
        this._activateOrder(order);
      } else {
        this._transition(order, ORDER_STATES.CONFIRMED);
      }
    } else if (settlementResult.outcome === "DUPLICATE_EVENT") {
      if (
        order.state === ORDER_STATES.CONFIRMED &&
        order.confirmation_count >= order.required_confirmations
      ) {
        this._activateOrder(order);
      }
    }

    return {
      order: this._publicOrder(order),
      settlement: settlementResult,
    };
  }

  confirmOrder(input) {
    const order = this.orders.get(input.order_id);
    if (!order) {
      throw new Error("order not found");
    }
    order.confirmation_count = Number(input.confirmations || order.confirmation_count || 0);

    if (
      order.confirmation_count >= order.required_confirmations &&
      (order.state === ORDER_STATES.CONFIRMED || order.settlement_outcome === "CREDITED")
    ) {
      this._activateOrder(order);
    }

    return this._publicOrder(order);
  }

  getMemberTier(member_id) {
    return this.memberTier.get(member_id) || "free";
  }

  isFeatureUnlocked(member_id, feature) {
    const tier = this.getMemberTier(member_id);
    const decision = checkEntitlement({
      member_id,
      tier,
      feature,
    });
    return {
      tier,
      ...decision,
    };
  }

  _activateOrder(order) {
    if (order.state !== ORDER_STATES.CONFIRMED) {
      this._transition(order, ORDER_STATES.CONFIRMED);
    }
    this._transition(order, ORDER_STATES.ACTIVE);
    const currentTier = this.getMemberTier(order.member_id);
    this.memberTier.set(
      order.member_id,
      chooseHigherTier(currentTier, order.requested_tier)
    );
  }

  _transition(order, state) {
    if (order.state !== state) {
      order.state = state;
      order.state_history.push(state);
    }
  }

  _publicOrder(order) {
    return {
      order_id: order.order_id,
      member_id: order.member_id,
      requested_tier: order.requested_tier,
      state: order.state,
      amount_expected_micro: order.amount_expected_micro,
      amount_expected: order.amount_expected,
      required_confirmations: order.required_confirmations,
      confirmation_count: order.confirmation_count,
      settlement_outcome: order.settlement_outcome,
      unique_id: order.unique_id,
      payer_wallet: order.payer_wallet,
      identity_wallet: order.identity_wallet,
      unlocked_tier: this.getMemberTier(order.member_id),
    };
  }
}

module.exports = {
  MonetizationService,
  ORDER_STATES,
};
