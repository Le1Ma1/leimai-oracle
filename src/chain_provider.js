const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const {
  normalizePaymentAsset,
  normalizePaymentChain,
} = require("./payment_rails");

const ERC20_TRANSFER_TOPIC =
  "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";
const RETRYABLE_CODES = new Set(["RPC_TIMEOUT", "RPC_BAD_RESPONSE"]);

class ChainProviderError extends Error {
  constructor(code, message, details = null) {
    super(message || code);
    this.code = code;
    this.details = details;
  }
}

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
      throw new ChainProviderError("RPC_BAD_RESPONSE", "amount_micro must be >= 0");
    }
    if (value > BigInt(Number.MAX_SAFE_INTEGER)) {
      throw new ChainProviderError("RPC_BAD_RESPONSE", "amount_micro over safe range");
    }
    return Number(value);
  }
  if (typeof value === "number") {
    if (!Number.isInteger(value) || value < 0) {
      throw new ChainProviderError("RPC_BAD_RESPONSE", "amount_micro must be integer >= 0");
    }
    return value;
  }
  if (typeof value === "string" && /^\d+$/.test(value)) {
    const parsed = Number(value);
    if (!Number.isSafeInteger(parsed)) {
      throw new ChainProviderError("RPC_BAD_RESPONSE", "amount_micro over safe range");
    }
    return parsed;
  }
  throw new ChainProviderError("RPC_BAD_RESPONSE", "amount_micro must be integer >= 0");
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

function normalizeProviderError(error, fallbackCode = "RPC_BAD_RESPONSE") {
  if (error instanceof ChainProviderError) {
    return error;
  }
  const code = String(error && error.code ? error.code : "").trim();
  if (code.startsWith("RPC_") || code.startsWith("RPC_CONFIG_MISSING_")) {
    return new ChainProviderError(code, code, { cause: error });
  }
  const message = String(error && error.message ? error.message : error || "");
  if (message.includes("timed out")) {
    return new ChainProviderError("RPC_TIMEOUT", "RPC_TIMEOUT", { cause: message });
  }
  return new ChainProviderError(fallbackCode, fallbackCode, { cause: message });
}

function parseHexAmountMicro(raw) {
  const normalized =
    typeof raw === "string" && raw.startsWith("0x") ? raw : `0x${raw || "0"}`;
  try {
    return normalizeAmountMicro(BigInt(normalized));
  } catch (error) {
    throw normalizeProviderError(error, "RPC_BAD_RESPONSE");
  }
}

function ensureMode(modeRaw) {
  const mode = String(modeRaw || "mock").trim().toLowerCase();
  if (!["mock", "rpc"].includes(mode)) {
    throw new ChainProviderError("RPC_BAD_RESPONSE", `Unsupported CHAIN_MODE: ${mode}`);
  }
  return mode;
}

function fixturePath(fixturesDir, chain, txId) {
  return path.join(fixturesDir, chain, `${txId}.json`);
}

function attachTrace(evidence, trace) {
  if (!evidence) {
    return null;
  }
  return {
    ...evidence,
    provider_mode: trace.provider_mode,
    provider_name: trace.provider_name,
    fetched_at_epoch: trace.fetched_at_epoch,
    source: trace.source,
  };
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

function deterministicSleep(ms) {
  if (!Number.isFinite(ms) || ms <= 0) {
    return;
  }
  if (typeof SharedArrayBuffer === "undefined" || typeof Atomics === "undefined") {
    return;
  }
  const sab = new SharedArrayBuffer(4);
  const int32 = new Int32Array(sab);
  Atomics.wait(int32, 0, 0, Math.floor(ms));
}

function defaultHttpRequest(input) {
  const method = input.method || "GET";
  const url = input.url;
  const headers = input.headers || {};
  const body = input.body;
  const timeoutMs = toInt(input.timeout_ms, 3000);
  const args = [
    "-sS",
    "-X",
    method,
    "--max-time",
    String(Math.max(1, Math.ceil(timeoutMs / 1000))),
    url,
  ];
  for (const [k, v] of Object.entries(headers)) {
    args.push("-H", `${k}: ${v}`);
  }
  if (body !== undefined) {
    args.push("-H", "content-type: application/json", "-d", JSON.stringify(body));
  }
  let output = "";
  try {
    output = execFileSync("curl", args, {
      encoding: "utf8",
      timeout: timeoutMs,
    });
  } catch (error) {
    const msg = String(error && error.message ? error.message : error || "");
    if (msg.includes("timed out") || error.signal === "SIGTERM") {
      throw new ChainProviderError("RPC_TIMEOUT", "RPC_TIMEOUT");
    }
    throw new ChainProviderError("RPC_BAD_RESPONSE", "RPC_BAD_RESPONSE", {
      cause: msg,
    });
  }
  if (!output || output.trim() === "") {
    return {};
  }
  try {
    return JSON.parse(output);
  } catch (error) {
    throw new ChainProviderError("RPC_BAD_RESPONSE", "RPC_BAD_RESPONSE");
  }
}

class MockChainProvider {
  constructor(options = {}) {
    this.fixtures_path =
      options.fixturesPath ||
      path.join(process.cwd(), "tests", "fixtures", "chain");
    this.now_fn = options.now_fn || Date.now;
  }

  getTransfersByTx({ chain, tx_id }) {
    const normalizedChain = normalizePaymentChain(chain);
    if (!normalizedChain || !["tron", "arbitrum"].includes(normalizedChain)) {
      throw new ChainProviderError("RPC_UNSUPPORTED_CHAIN", "RPC_UNSUPPORTED_CHAIN");
    }
    const txId = String(tx_id || "").trim();
    if (!txId) {
      throw new ChainProviderError("RPC_BAD_RESPONSE", "tx_id is required");
    }
    const fp = fixturePath(this.fixtures_path, normalizedChain, txId);
    if (!fs.existsSync(fp)) {
      return [];
    }
    const payload = JSON.parse(fs.readFileSync(fp, "utf8"));
    return normalizeFixtureEvents(normalizedChain, txId, payload).map((event) =>
      attachTrace(event, {
        provider_mode: "mock",
        provider_name: "fixture",
        fetched_at_epoch: this.now_fn(),
        source: "mock",
      })
    );
  }

  preflightValidate(input = {}) {
    const chainRaw = input.chain;
    if (chainRaw === undefined || chainRaw === null || chainRaw === "") {
      return {
        provider_mode: "mock",
        source: "mock",
        ok: true,
      };
    }
    const chain = normalizePaymentChain(chainRaw);
    if (!chain || !["tron", "arbitrum", "ethereum"].includes(chain)) {
      throw new ChainProviderError("RPC_UNSUPPORTED_CHAIN", "RPC_UNSUPPORTED_CHAIN");
    }
    return {
      provider_mode: "mock",
      source: "mock",
      ok: true,
      chain,
    };
  }

  getTransferEvidence(input) {
    const chain = normalizePaymentChain(input.chain);
    if (!chain) {
      throw new ChainProviderError("RPC_UNSUPPORTED_CHAIN", "RPC_UNSUPPORTED_CHAIN");
    }
    const txId = String(input.tx_hash_or_id || "").trim();
    const asset = normalizePaymentAsset(input.asset);
    if (!txId || !asset) {
      throw new ChainProviderError("RPC_BAD_RESPONSE", "tx_hash_or_id and asset are required");
    }
    const recipient =
      chain === "tron"
        ? normalizeTronAddress(input.recipient_address)
        : normalizeEvmAddress(input.recipient_address);
    if (!recipient) {
      throw new ChainProviderError("RPC_BAD_RESPONSE", "recipient_address is required");
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
    this.request_timeout_ms = toInt(options.request_timeout_ms, 3000);
    this.max_attempts = Math.max(1, toInt(options.max_attempts, 3));
    this.base_backoff_ms = Math.max(0, toInt(options.base_backoff_ms, 100));
    this.rate_limit_per_minute = Math.max(1, toInt(options.rate_limit_per_minute, 120));
    this.rate_state = new Map();
    this.sleep_impl = options.sleep_impl || deterministicSleep;
    this.now_fn = options.now_fn || Date.now;
    this.provider_name = options.provider_name || "rpc";
  }

  #requireRpcUrl(chain) {
    if (chain === "tron") {
      if (!this.urls.tron) {
        throw new ChainProviderError(
          "RPC_CONFIG_MISSING_TRON_RPC_URL",
          "RPC_CONFIG_MISSING_TRON_RPC_URL"
        );
      }
      return this.urls.tron;
    }
    if (chain === "arbitrum") {
      if (!this.urls.arbitrum) {
        throw new ChainProviderError(
          "RPC_CONFIG_MISSING_ARBITRUM_RPC_URL",
          "RPC_CONFIG_MISSING_ARBITRUM_RPC_URL"
        );
      }
      return this.urls.arbitrum;
    }
    if (chain === "ethereum") {
      if (!this.urls.ethereum) {
        throw new ChainProviderError(
          "RPC_CONFIG_MISSING_ETHEREUM_RPC_URL",
          "RPC_CONFIG_MISSING_ETHEREUM_RPC_URL"
        );
      }
      return this.urls.ethereum;
    }
    throw new ChainProviderError("RPC_UNSUPPORTED_CHAIN", "RPC_UNSUPPORTED_CHAIN");
  }

  #checkRateLimit(chain) {
    const nowMs = this.now_fn();
    const bucket = Math.floor(nowMs / 60000);
    const current = this.rate_state.get(chain);
    if (!current || current.bucket !== bucket) {
      this.rate_state.set(chain, {
        bucket,
        count: 1,
      });
      return;
    }
    if (current.count >= this.rate_limit_per_minute) {
      throw new ChainProviderError("RPC_RATE_LIMITED", "RPC_RATE_LIMITED");
    }
    current.count += 1;
  }

  #withRetry(action) {
    for (let attempt = 1; attempt <= this.max_attempts; attempt += 1) {
      try {
        return action();
      } catch (error) {
        const normalized = normalizeProviderError(error);
        const canRetry =
          RETRYABLE_CODES.has(normalized.code) && attempt < this.max_attempts;
        if (!canRetry) {
          throw normalized;
        }
        const backoffMs = this.base_backoff_ms * attempt;
        this.sleep_impl(backoffMs);
      }
    }
    throw new ChainProviderError("RPC_BAD_RESPONSE", "RPC_BAD_RESPONSE");
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
      timeout_ms: this.request_timeout_ms,
    });
    if (!response || typeof response !== "object") {
      throw new ChainProviderError("RPC_BAD_RESPONSE", "RPC_BAD_RESPONSE");
    }
    if (response.error) {
      throw new ChainProviderError("RPC_BAD_RESPONSE", "RPC_BAD_RESPONSE", {
        method,
      });
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
      timeout_ms: this.request_timeout_ms,
    });
    if (!response || typeof response !== "object") {
      throw new ChainProviderError("RPC_BAD_RESPONSE", "RPC_BAD_RESPONSE");
    }
    return response;
  }

  #buildTrace(chain) {
    return {
      provider_mode: "rpc",
      provider_name: `${this.provider_name}:${chain}`,
      fetched_at_epoch: this.now_fn(),
      source: "rpc",
    };
  }

  preflightValidate(input = {}) {
    const chainRaw = input.chain;
    if (chainRaw !== undefined && chainRaw !== null && chainRaw !== "") {
      const chain = normalizePaymentChain(chainRaw);
      if (!chain || !["tron", "arbitrum", "ethereum"].includes(chain)) {
        throw new ChainProviderError("RPC_UNSUPPORTED_CHAIN", "RPC_UNSUPPORTED_CHAIN");
      }
      this.#requireRpcUrl(chain);
      return {
        provider_mode: "rpc",
        provider_name: `${this.provider_name}:${chain}`,
        source: "rpc",
        ok: true,
        chain,
      };
    }
    // v0.8 preflight baseline: rails-relevant rpc urls must all be configured.
    this.#requireRpcUrl("tron");
    this.#requireRpcUrl("arbitrum");
    return {
      provider_mode: "rpc",
      provider_name: this.provider_name,
      source: "rpc",
      ok: true,
    };
  }

  #resolveRpcEvmEvidence(input) {
    const chain = normalizePaymentChain(input.chain);
    const txHash = String(input.tx_hash_or_id || "").trim();
    const asset = normalizePaymentAsset(input.asset);
    const recipient = normalizeEvmAddress(input.recipient_address);
    const amountExpectedMicro = normalizeAmountMicro(input.amount_expected_micro);
    if (!chain || !txHash || !asset || !recipient) {
      throw new ChainProviderError("RPC_BAD_RESPONSE", "RPC_BAD_RESPONSE");
    }

    const rpcUrl = this.#requireRpcUrl(chain);
    const receipt = this.#rpcCall(rpcUrl, "eth_getTransactionReceipt", [txHash]);
    if (!receipt) {
      throw new ChainProviderError("RPC_TX_NOT_FOUND", "RPC_TX_NOT_FOUND");
    }
    if (!Array.isArray(receipt.logs)) {
      throw new ChainProviderError("RPC_BAD_RESPONSE", "RPC_BAD_RESPONSE");
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
      if (topic0 !== ERC20_TRANSFER_TOPIC) {
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
      return attachTrace(
        {
          chain,
          asset,
          recipient_address: recipient,
          amount_micro: amountMicro,
          confirmations: blockNumber > 0 ? Math.max(0, latest - blockNumber + 1) : 0,
          unique_id: `${txHash}:${logIndex}`,
          tx_hash: txHash,
          transaction_id: null,
          event_index: logIndex,
          observed_at_epoch: this.now_fn(),
          raw: {
            receipt,
            log,
          },
        },
        this.#buildTrace(chain)
      );
    }
    return null;
  }

  #resolveRpcTronEvidence(input) {
    const txId = String(input.tx_hash_or_id || "").trim();
    const recipient = normalizeTronAddress(input.recipient_address);
    const asset = normalizePaymentAsset(input.asset);
    const amountExpectedMicro = normalizeAmountMicro(input.amount_expected_micro);
    if (!txId || !recipient || !asset) {
      throw new ChainProviderError("RPC_BAD_RESPONSE", "RPC_BAD_RESPONSE");
    }
    const rpcUrl = this.#requireRpcUrl("tron");
    const response = this.#fetchTronEvents(rpcUrl, txId);
    const events = Array.isArray(response?.data)
      ? response.data
      : Array.isArray(response?.events)
        ? response.events
        : [];
    if (events.length === 0) {
      throw new ChainProviderError("RPC_TX_NOT_FOUND", "RPC_TX_NOT_FOUND");
    }
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
      return attachTrace(
        {
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
        },
        this.#buildTrace("tron")
      );
    }
    return null;
  }

  getTransferEvidence(input) {
    const chain = normalizePaymentChain(input.chain);
    if (!chain || !["tron", "arbitrum", "ethereum"].includes(chain)) {
      throw new ChainProviderError("RPC_UNSUPPORTED_CHAIN", "RPC_UNSUPPORTED_CHAIN");
    }
    this.#checkRateLimit(chain);
    return this.#withRetry(() => {
      if (chain === "tron") {
        return this.#resolveRpcTronEvidence(input);
      }
      return this.#resolveRpcEvmEvidence({
        ...input,
        chain,
      });
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
      now_fn: config.now_fn,
    });
  }
  return new RpcChainProvider({
    urls: config.urls || {},
    fetchImpl: config.fetchImpl,
    tron_api_key: config.tron_api_key,
    request_timeout_ms: config.request_timeout_ms,
    max_attempts: config.max_attempts,
    base_backoff_ms: config.base_backoff_ms,
    rate_limit_per_minute: config.rate_limit_per_minute,
    sleep_impl: config.sleep_impl,
    now_fn: config.now_fn,
    provider_name: config.provider_name,
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
    request_timeout_ms:
      options.rpc_request_timeout_ms ||
      process.env.CHAIN_RPC_TIMEOUT_MS ||
      3000,
    max_attempts:
      options.rpc_max_attempts || process.env.CHAIN_RPC_MAX_ATTEMPTS || 3,
    base_backoff_ms:
      options.rpc_base_backoff_ms || process.env.CHAIN_RPC_BACKOFF_MS || 100,
    rate_limit_per_minute:
      options.rpc_rate_limit_per_minute ||
      process.env.CHAIN_RPC_RATE_LIMIT_PER_MIN ||
      120,
    sleep_impl: options.rpc_sleep_impl,
    now_fn: options.rpc_now_fn,
  });
}

const FixtureChainProvider = MockChainProvider;

module.exports = {
  ChainProviderError,
  FixtureChainProvider,
  MockChainProvider,
  RpcChainProvider,
  createChainProvider,
  createChainProviderFromEnv,
  normalizeProviderError,
};
