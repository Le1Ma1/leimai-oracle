const fs = require("node:fs");
const path = require("node:path");

const {
  normalizePaymentAsset,
  normalizePaymentChain,
} = require("./payment_rails");

function toInt(value, fallback = 0) {
  const num = Number(value);
  if (!Number.isFinite(num) || num < 0) {
    return fallback;
  }
  return Math.floor(num);
}

function normalizeAmountMicro(value) {
  if (typeof value === "bigint") {
    return value.toString();
  }
  if (typeof value === "number") {
    if (!Number.isInteger(value) || value < 0) {
      throw new Error("amount_micro must be a non-negative integer");
    }
    return String(value);
  }
  if (typeof value === "string" && /^\d+$/.test(value)) {
    return value;
  }
  throw new Error("amount_micro must be a non-negative integer");
}

function fixturePath(fixturesDir, chain, txId) {
  return path.join(fixturesDir, chain, `${txId}.json`);
}

function normalizeTronEvent(txId, fixtureEvent, fallbackConfirmations) {
  const idx = toInt(
    fixtureEvent.event_index !== undefined
      ? fixtureEvent.event_index
      : fixtureEvent.index,
    0
  );
  const asset = normalizePaymentAsset(fixtureEvent.asset);
  if (asset !== "usdt") {
    return null;
  }
  const recipient = String(fixtureEvent.recipient_address || "").trim();
  if (!recipient) {
    return null;
  }
  return {
    chain: "tron",
    asset,
    recipient_address: recipient,
    amount_micro: normalizeAmountMicro(fixtureEvent.amount_micro),
    unique_id: `${txId}:${idx}`,
    confirmations: toInt(
      fixtureEvent.confirmations !== undefined
        ? fixtureEvent.confirmations
        : fallbackConfirmations,
      0
    ),
    tx_id: txId,
    event_index: idx,
    log_index: idx,
    timestamp: fixtureEvent.timestamp || null,
    raw: fixtureEvent,
  };
}

function normalizeArbitrumEvent(txId, fixtureEvent, fallbackConfirmations) {
  const idx = toInt(
    fixtureEvent.log_index !== undefined
      ? fixtureEvent.log_index
      : fixtureEvent.event_index,
    0
  );
  const asset = normalizePaymentAsset(fixtureEvent.asset);
  if (asset !== "usdc") {
    return null;
  }
  const recipient = String(fixtureEvent.recipient_address || "").trim();
  if (!recipient) {
    return null;
  }
  return {
    chain: "arbitrum",
    asset,
    recipient_address: recipient,
    amount_micro: normalizeAmountMicro(fixtureEvent.amount_micro),
    unique_id: `${txId}:${idx}`,
    confirmations: toInt(
      fixtureEvent.confirmations !== undefined
        ? fixtureEvent.confirmations
        : fallbackConfirmations,
      0
    ),
    tx_id: txId,
    event_index: idx,
    log_index: idx,
    timestamp: fixtureEvent.timestamp || null,
    raw: fixtureEvent,
  };
}

function normalizeFixtureEvents(chain, txId, payload) {
  const events = Array.isArray(payload.events) ? payload.events : [];
  const fallbackConfirmations = toInt(payload.confirmations, 0);
  const normalized = [];
  for (const event of events) {
    const item =
      chain === "tron"
        ? normalizeTronEvent(txId, event, fallbackConfirmations)
        : normalizeArbitrumEvent(txId, event, fallbackConfirmations);
    if (item) {
      normalized.push(item);
    }
  }
  return normalized;
}

class FixtureChainProvider {
  constructor(options = {}) {
    this.fixtures_dir =
      options.fixtures_dir ||
      path.join(process.cwd(), "tests", "fixtures", "chain");
  }

  getTransfersByTx({ chain, tx_id }) {
    const normalizedChain = normalizePaymentChain(chain);
    if (!normalizedChain || !["tron", "arbitrum"].includes(normalizedChain)) {
      throw new Error(`Unsupported chain provider request: ${chain}`);
    }
    const txId = String(tx_id || "").trim();
    if (!txId) {
      throw new Error("tx_id is required");
    }
    const fp = fixturePath(this.fixtures_dir, normalizedChain, txId);
    if (!fs.existsSync(fp)) {
      return [];
    }
    const payload = JSON.parse(fs.readFileSync(fp, "utf8"));
    return normalizeFixtureEvents(normalizedChain, txId, payload);
  }
}

function createChainProviderFromEnv(options = {}) {
  if (options.chain_provider) {
    return options.chain_provider;
  }
  const shouldMock =
    options.chain_mock === true || String(process.env.CHAIN_MOCK || "") === "1";
  if (!shouldMock) {
    return null;
  }
  return new FixtureChainProvider({
    fixtures_dir:
      options.chain_fixtures_dir ||
      process.env.CHAIN_FIXTURES_DIR ||
      path.join(process.cwd(), "tests", "fixtures", "chain"),
  });
}

module.exports = {
  FixtureChainProvider,
  createChainProviderFromEnv,
};
