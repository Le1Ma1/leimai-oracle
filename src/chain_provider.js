const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const {
  normalizePaymentAsset,
  normalizePaymentChain,
} = require("./payment_rails");

const TRANSFER_TOPIC =
  "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55aeb";

function toInt(value, fallback = 0) {
  const num = Number(value);
  if (!Number.isFinite(num) || num < 0) {
    return fallback;
  }
  return Math.floor(num);
}

function normalizeAmountMicro(value) {
  if (typeof value === "bigint") {
    if (value < 0n) {
      throw new Error("amount_micro must be a non-negative integer");
    }
    return Number(value);
  }
  if (typeof value === "number") {
    if (!Number.isInteger(value) || value < 0) {
      throw new Error("amount_micro must be a non-negative integer");
    }
    return value;
  }
  if (typeof value === "string" && /^\d+$/.test(value)) {
    const parsed = Number(value);
    if (!Number.isSafeInteger(parsed)) {
      throw new Error("amount_micro over safe integer range");
    }
    return parsed;
  }
  throw new Error("amount_micro must be a non-negative integer");
}

function normalizeEpochMs(value, fallback = Date.now()) {
  if (typeof value === "number" && Number.isFinite(value)) {
    if (value > 1e12) {
      return Math.floor(value);
    }
    if (value > 1e9) {
      return Math.floor(value * 1000);
    }
  }
  if (typeof value === "string" && value.trim() !== "") {
    if (/^\d+$/.test(value)) {
      return normalizeEpochMs(Number(value), fallback);
    }
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return fallback;
}

function normalizeEvmAddress(value) {
  const raw = String(value || "").trim().toLowerCase();
  if (!/^0x[a-f0-9]{40}$/.test(raw)) {
    return null;
  }
  return raw;
}

function normalizeTronAddress(value) {
  const raw = String(value || "").trim();
  return raw === "" ? null : raw;
}

function parseHexToInt(raw) {
  if (typeof raw !== "string") {
    return 0;
  }
  const normalized = raw.startsWith("0x") ? raw : `0x${raw}`;
  const n = Number.parseInt(normalized, 16);
  if (!Number.isFinite(n) || n < 0) {
    return 0;
  }
  return Math.floor(n);
}

function parseHexAmountMicro(raw) {
  const normalized =
    typeof raw === "string" && raw.startsWith("0x") ? raw : `0x${raw || "0"}`;
  const value = BigInt(normalized);
  if (value > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new Error("amount_micro over safe integer range");
  }
  return Number(value);
}

function ensureMode(modeRaw) {
  const mode = String(modeRaw || "mock").trim().toLowerCase();
  if (!["mock", "rpc"].includes(mode)) {
    throw new Error(`Unsupported CHAIN_MODE: ${mode}`);
  }
  return mode;
}

function fixturePath(fixturesDir, chain, txId) {
  return path.join(fixturesDir, chain, `${txId}.json`);
}

function normalizeFixtureEvents(chain, txId, payload) {
  const events = Array.isArray(payload.events) ? payload.events : [];
  const fallbackConfirmations = toInt(payload.confirmations, 0);
  const out = [];

  for (const event of events) {
    const idx = toInt(
      event.event_index !== undefined ? event.event_index : event.log_index,
      0
    );
    const asset = normalizePaymentAsset(event.asset);
    const recipient =
      chain === "tron"
        ? normalizeTronAddress(event.recipient_address || event.to)
        : normalizeEvmAddress(event.recipient_address || event.to);
    if (!asset || !recipient) {
      continue;
    }
    const amountMicro = normalizeAmountMicro(event.amount_micro);
    const confirmations = toInt(
      event.confirmations !== undefined ? event.confirmations : fallbackConfirmations,
      0
    );
    const observedAt = normalizeEpochMs(
      event.observed_at_epoch || event.timestamp || payload.timestamp
    );
    out.push({
      chain,
      asset,
      recipient_address: recipient,
      amount_micro: amountMicro,
      confirmations,
      unique_id: `${txId}:${idx}`,
      tx_hash: chain === "tron" ? null : txId,
      transaction_id: chain === "tron" ? txId : null,
      event_index: idx,
      observed_at_epoch: observedAt,
      raw: event,
    });
  }

  return out;
}

function matchEvidence(events, wanted) {
  for (const event of events) {
    if (event.asset !== wanted.asset) {
      continue;
    }
    if (event.amount_micro !== wanted.amount_expected_micro) {
      continue;
    }
    if (event.chain === "tron") {
      if (event.recipient_address !== wanted.recipient_address) {
        continue;
      }
    } else if (
      String(event.recipient_address).toLowerCase() !==
      String(wanted.recipient_address).toLowerCase()
    ) {
      continue;
    }
    return event;
  }
  return null;
}

function defaultHttpRequest(input) {
  const method = input.method || "GET";
  const url = input.url;
  const headers = input.headers || {};
  const body = input.body;
  const args = ["-sS", "-X", method, url];
  for (const [k, v] of Object.entries(headers)) {
    args.push("-H", `${k}: ${v}`);
  }
  if (body !== undefined) {
    args.push("-H", "content-type: application/json", "-d", JSON.stringify(body));
  }
  let output = "";
  try {
    output = execFileSync("curl", args, { encoding: "utf8" });
  } catch (error) {
    throw new Error("RPC_HTTP_REQUEST_FAILED");
  }
  if (!output || output.trim() === "") {
    return {};
  }
  try {
    return JSON.parse(output);
  } catch (error) {
    throw new Error("RPC_HTTP_RESPONSE_NOT_JSON");
  }
}

class MockChainProvider {
  constructor(options = {}) {
    this.fixtures_path =
      options.fixturesPath ||
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
    const fp = fixturePath(this.fixtures_path, normalizedChain, txId);
    if (!fs.existsSync(fp)) {
      return [];
    }
    const payload = JSON.parse(fs.readFileSync(fp, "utf8"));
    return normalizeFixtureEvents(normalizedChain, txId, payload);
  }

  getTransferEvidence(input) {
    const chain = normalizePaymentChain(input.chain);
    if (!chain) {
      throw new Error(`Unsupported chain provider request: ${input.chain}`);
    }
    const txId = String(input.tx_hash_or_id || "").trim();
    const asset = normalizePaymentAsset(input.asset);
    if (!txId || !asset) {
      throw new Error("tx_hash_or_id and asset are required");
    }
    const recipient =
      chain === "tron"
        ? normalizeTronAddress(input.recipient_address)
        : normalizeEvmAddress(input.recipient_address);
    if (!recipient) {
      throw new Error("recipient_address is required");
    }
    const amountExpectedMicro = normalizeAmountMicro(input.amount_expected_micro);
    const events = this.getTransfersByTx({
      chain,
      tx_id: txId,
    });
    return matchEvidence(events, {
      asset,
      recipient_address: recipient,
      amount_expected_micro: amountExpectedMicro,
    });
  }
}

class RpcChainProvider {
  constructor(options = {}) {
    this.urls = {
      tron: options.urls?.tron || null,
      arbitrum: options.urls?.arbitrum || null,
      ethereum: options.urls?.ethereum || null,
    };
    this.fetch_impl = options.fetchImpl || defaultHttpRequest;
    this.tron_api_key = options.tron_api_key || null;
  }

  #requireRpcUrl(chain) {
    if (chain === "tron") {
      if (!this.urls.tron) {
        throw new Error("RPC_CONFIG_MISSING_TRON_RPC_URL");
      }
      return this.urls.tron;
    }
    if (chain === "arbitrum") {
      if (!this.urls.arbitrum) {
        throw new Error("RPC_CONFIG_MISSING_ARBITRUM_RPC_URL");
      }
      return this.urls.arbitrum;
    }
    if (chain === "ethereum") {
      if (!this.urls.ethereum) {
        throw new Error("RPC_CONFIG_MISSING_ETHEREUM_RPC_URL");
      }
      return this.urls.ethereum;
    }
    throw new Error(`Unsupported chain provider request: ${chain}`);
  }

  #rpcCall(url, method, params) {
    const payload = {
      jsonrpc: "2.0",
      id: 1,
      method,
      params,
    };
    const response = this.fetch_impl({
      chain: "evm",
      transport: "jsonrpc",
      url,
      method: "POST",
      body: payload,
      headers: {},
    });
    if (!response || typeof response !== "object") {
      throw new Error("RPC_RESPONSE_INVALID");
    }
    if (response.error) {
      throw new Error(`RPC_ERROR_${method}`);
    }
    return response.result;
  }

  #fetchTronEvents(baseUrl, txId) {
    const url = `${String(baseUrl).replace(/\/+$/, "")}/v1/transactions/${txId}/events`;
    const headers = {};
    if (this.tron_api_key) {
      headers["TRON-PRO-API-KEY"] = this.tron_api_key;
    }
    const response = this.fetch_impl({
      chain: "tron",
      transport: "http",
      url,
      method: "GET",
      headers,
    });
    return response;
  }

  #normalizeRpcEvmEvidence(input) {
    const chain = normalizePaymentChain(input.chain);
    const txHash = String(input.tx_hash_or_id || "").trim();
    const asset = normalizePaymentAsset(input.asset);
    const recipient = normalizeEvmAddress(input.recipient_address);
    const amountExpectedMicro = normalizeAmountMicro(input.amount_expected_micro);
    if (!chain || !txHash || !asset || !recipient) {
      throw new Error("invalid rpc evm evidence input");
    }
    const rpcUrl = this.#requireRpcUrl(chain);
    const receipt = this.#rpcCall(rpcUrl, "eth_getTransactionReceipt", [txHash]);
    if (!receipt || !Array.isArray(receipt.logs)) {
      return null;
    }
    const latestHex = this.#rpcCall(rpcUrl, "eth_blockNumber", []);
    const latest = parseHexToInt(latestHex);
    const blockNumber = parseHexToInt(receipt.blockNumber);

    for (const log of receipt.logs) {
      const topics = Array.isArray(log.topics) ? log.topics : [];
      if (topics.length < 3) {
        continue;
      }
      const topic0 = String(topics[0] || "").toLowerCase();
      if (!topic0.startsWith(TRANSFER_TOPIC)) {
        continue;
      }
      const toAddress = normalizeEvmAddress(`0x${String(topics[2]).slice(-40)}`);
      if (!toAddress || toAddress !== recipient) {
        continue;
      }
      const amountMicro = parseHexAmountMicro(log.data || "0x0");
      if (amountMicro !== amountExpectedMicro) {
        continue;
      }
      const logIndex = parseHexToInt(log.logIndex);
      return {
        chain,
        asset,
        recipient_address: recipient,
        amount_micro: amountMicro,
        confirmations: blockNumber > 0 ? Math.max(0, latest - blockNumber + 1) : 0,
        unique_id: `${txHash}:${logIndex}`,
        tx_hash: txHash,
        transaction_id: null,
        event_index: logIndex,
        observed_at_epoch: Date.now(),
        raw: {
          receipt,
          log,
        },
      };
    }
    return null;
  }

  #normalizeRpcTronEvidence(input) {
    const txId = String(input.tx_hash_or_id || "").trim();
    const recipient = normalizeTronAddress(input.recipient_address);
    const asset = normalizePaymentAsset(input.asset);
    const amountExpectedMicro = normalizeAmountMicro(input.amount_expected_micro);
    if (!txId || !recipient || !asset) {
      throw new Error("invalid rpc tron evidence input");
    }
    const rpcUrl = this.#requireRpcUrl("tron");
    const response = this.#fetchTronEvents(rpcUrl, txId);
    const events = Array.isArray(response?.data)
      ? response.data
      : Array.isArray(response?.events)
        ? response.events
        : [];
    const fallbackConfirmations = toInt(response?.confirmations, 0);

    for (let i = 0; i < events.length; i += 1) {
      const event = events[i];
      const eventRecipient = normalizeTronAddress(
        event.recipient_address ||
          event.to ||
          event.to_address ||
          event.result?.to ||
          event.result?.to_address
      );
      if (!eventRecipient || eventRecipient !== recipient) {
        continue;
      }
      const eventAsset = normalizePaymentAsset(
        event.asset || event.token || event.token_symbol || event.symbol
      );
      if (eventAsset !== asset) {
        continue;
      }
      const rawAmount =
        event.amount_micro !== undefined
          ? event.amount_micro
          : event.amount !== undefined
            ? event.amount
            : event.result?.value;
      const amountMicro = normalizeAmountMicro(rawAmount);
      if (amountMicro !== amountExpectedMicro) {
        continue;
      }
      const idx = toInt(
        event.event_index !== undefined
          ? event.event_index
          : event.log_index !== undefined
            ? event.log_index
            : i,
        i
      );
      return {
        chain: "tron",
        asset,
        recipient_address: recipient,
        amount_micro: amountMicro,
        confirmations: toInt(
          event.confirmations !== undefined
            ? event.confirmations
            : fallbackConfirmations,
          0
        ),
        unique_id: `${txId}:${idx}`,
        tx_hash: null,
        transaction_id: txId,
        event_index: idx,
        observed_at_epoch: normalizeEpochMs(
          event.timestamp || event.block_timestamp || event.observed_at_epoch
        ),
        raw: event,
      };
    }
    return null;
  }

  getTransferEvidence(input) {
    const chain = normalizePaymentChain(input.chain);
    if (!chain || !["tron", "arbitrum", "ethereum"].includes(chain)) {
      throw new Error(`Unsupported chain provider request: ${input.chain}`);
    }
    if (chain === "tron") {
      return this.#normalizeRpcTronEvidence(input);
    }
    return this.#normalizeRpcEvmEvidence({
      ...input,
      chain,
    });
  }
}

function resolveMode(options = {}) {
  if (options.mode) {
    return ensureMode(options.mode);
  }
  if (options.chain_mode) {
    return ensureMode(options.chain_mode);
  }
  if (options.chain_mock === true || String(process.env.CHAIN_MOCK || "") === "1") {
    return "mock";
  }
  if (process.env.CHAIN_MODE) {
    return ensureMode(process.env.CHAIN_MODE);
  }
  return "mock";
}

function createChainProvider(config = {}) {
  const mode = ensureMode(config.mode || "mock");
  if (mode === "mock") {
    return new MockChainProvider({
      fixturesPath:
        config.fixturesPath ||
        config.chain_fixtures_dir ||
        path.join(process.cwd(), "tests", "fixtures", "chain"),
    });
  }
  return new RpcChainProvider({
    urls: config.urls || {},
    fetchImpl: config.fetchImpl,
    tron_api_key: config.tron_api_key,
  });
}

function createChainProviderFromEnv(options = {}) {
  if (options.chain_provider) {
    return options.chain_provider;
  }
  const mode = resolveMode(options);
  return createChainProvider({
    mode,
    fixturesPath:
      options.chain_fixtures_dir ||
      process.env.CHAIN_FIXTURES_DIR ||
      path.join(process.cwd(), "tests", "fixtures", "chain"),
    urls: {
      tron: options.tron_rpc_url || process.env.TRON_RPC_URL || null,
      arbitrum: options.arbitrum_rpc_url || process.env.ARBITRUM_RPC_URL || null,
      ethereum: options.ethereum_rpc_url || process.env.ETHEREUM_RPC_URL || null,
    },
    fetchImpl: options.rpc_fetch_impl,
    tron_api_key: options.tron_api_key || process.env.TRON_API_KEY || null,
  });
}

const FixtureChainProvider = MockChainProvider;

module.exports = {
  FixtureChainProvider,
  MockChainProvider,
  RpcChainProvider,
  createChainProvider,
  createChainProviderFromEnv,
};
