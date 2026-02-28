function toIso(ts) {
  const n = Number(ts);
  if (Number.isFinite(n) && n > 0) {
    const ms = n > 1e12 ? n : n * 1000;
    return new Date(ms).toISOString();
  }
  const parsed = Date.parse(String(ts || ""));
  if (Number.isFinite(parsed) && parsed > 0) {
    return new Date(parsed).toISOString();
  }
  return null;
}

function parseAmount(raw, decimals = 6) {
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) return null;
  return n / (10 ** decimals);
}

function toArray(obj) {
  if (Array.isArray(obj)) return obj;
  return [];
}

async function fetchJson(url, headers = {}, timeoutMs = 12000) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      method: "GET",
      headers,
      signal: ctl.signal,
      cache: "no-store",
    });
    if (!res.ok) {
      throw new Error(`HTTP_${res.status}`);
    }
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

function normalizeTronscan(row, config) {
  if (!row || typeof row !== "object") return null;
  const token = String(
    row.tokenAbbr ||
    row.tokenName ||
    row.tokenSymbol ||
    row.symbol ||
    ""
  ).toUpperCase();
  if (token !== "USDT") return null;

  const txHash = String(row.transaction_id || row.hash || row.txID || "").toLowerCase();
  const from = String(row.from_address || row.from || row.ownerAddress || "");
  const to = String(row.to_address || row.to || row.toAddress || "");
  if (!txHash || !to) return null;
  if (to !== config.supportAddress) return null;

  const decimals = Number(row.tokenDecimal ?? row.decimals ?? 6);
  const amount = parseAmount(row.quant ?? row.amount_str ?? row.amount, decimals);
  if (!Number.isFinite(amount) || amount <= 0) return null;

  return {
    tx_hash: txHash,
    chain: "TRON",
    token: "USDT",
    from_addr: from,
    to_addr: to,
    amount,
    confirmed_at_utc: toIso(row.block_ts ?? row.timestamp ?? row.block_timestamp),
    confirmations: Number(row.confirmed ? row.confirmations || 20 : row.confirmations || 0),
    source: "tronscan",
    status: (row.confirmed === false) ? "pending" : "verified",
  };
}

function normalizeTrongrid(row, config) {
  if (!row || typeof row !== "object") return null;
  const token = String(
    row.token_info?.symbol ||
    row.token_info?.name ||
    row.tokenName ||
    row.token_symbol ||
    ""
  ).toUpperCase();
  if (token !== "USDT") return null;

  const txHash = String(row.transaction_id || row.txID || row.hash || "").toLowerCase();
  const from = String(row.from || row.from_address || "");
  const to = String(row.to || row.to_address || "");
  if (!txHash || !to) return null;
  if (to !== config.supportAddress) return null;

  const decimals = Number(row.token_info?.decimals ?? row.decimals ?? 6);
  const amount = parseAmount(row.value ?? row.amount, decimals);
  if (!Number.isFinite(amount) || amount <= 0) return null;

  return {
    tx_hash: txHash,
    chain: "TRON",
    token: "USDT",
    from_addr: from,
    to_addr: to,
    amount,
    confirmed_at_utc: toIso(row.block_timestamp ?? row.timestamp),
    confirmations: Number(row.confirmed ? row.confirmations || 20 : row.confirmations || 0),
    source: "trongrid",
    status: (row.confirmed === false) ? "pending" : "verified",
  };
}

export async function fetchTronscan(config) {
  const out = {
    source: "tronscan",
    ok: false,
    fetched_at_utc: new Date().toISOString(),
    transfers: [],
    error: null,
  };
  try {
    const url = `${config.tronscanBase}/api/token_trc20/transfers?toAddress=${encodeURIComponent(config.supportAddress)}&limit=${config.fetchLimit}&start=0&sort=-timestamp`;
    const payload = await fetchJson(url, {}, config.fetchTimeoutMs);
    const rows = [
      ...toArray(payload?.token_transfers),
      ...toArray(payload?.data),
      ...toArray(payload?.trc20_transfers),
    ];
    out.transfers = rows
      .map((row) => normalizeTronscan(row, config))
      .filter(Boolean);
    out.ok = true;
    return out;
  } catch (error) {
    out.error = String(error?.message || error);
    return out;
  }
}

export async function fetchTrongrid(config) {
  const out = {
    source: "trongrid",
    ok: false,
    fetched_at_utc: new Date().toISOString(),
    transfers: [],
    error: null,
  };
  try {
    const headers = {};
    if (config.trongridApiKey) {
      headers["TRON-PRO-API-KEY"] = config.trongridApiKey;
    }
    const url = `${config.trongridBase}/v1/accounts/${encodeURIComponent(config.supportAddress)}/transactions/trc20?limit=${config.fetchLimit}&only_confirmed=true&order_by=block_timestamp,desc`;
    const payload = await fetchJson(url, headers, config.fetchTimeoutMs);
    const rows = toArray(payload?.data);
    out.transfers = rows
      .map((row) => normalizeTrongrid(row, config))
      .filter(Boolean);
    out.ok = true;
    return out;
  } catch (error) {
    out.error = String(error?.message || error);
    return out;
  }
}

export function mergeTransfers(primaryRows, secondaryRows) {
  const map = new Map();
  for (const row of [...(primaryRows || []), ...(secondaryRows || [])]) {
    if (!row || typeof row !== "object") continue;
    const txHash = row.tx_hash;
    if (!txHash) continue;
    const prev = map.get(txHash);
    if (!prev) {
      map.set(txHash, row);
      continue;
    }
    const merged = {
      ...prev,
      confirmations: Math.max(Number(prev.confirmations || 0), Number(row.confirmations || 0)),
      confirmed_at_utc: prev.confirmed_at_utc || row.confirmed_at_utc,
      amount: Number(prev.amount || 0) > 0 ? prev.amount : row.amount,
      source: prev.source === row.source ? prev.source : "dual",
      status: (prev.status === "verified" || row.status === "verified") ? "verified" : "pending",
    };
    map.set(txHash, merged);
  }
  return Array.from(map.values());
}
