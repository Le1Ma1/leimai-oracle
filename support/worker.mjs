import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { fetchTronscan, fetchTrongrid, mergeTransfers } from "./lib/chain-sources.mjs";
import { buildLeaderboard } from "./lib/leaderboard.mjs";
import {
  DEFAULT_CHAIN_STATE,
  DEFAULT_APP_STATE,
  ensureJsonFile,
  nowIso,
  readJsonFile,
  writeJsonAtomic,
} from "./lib/storage.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function parseDotEnv(content) {
  const out = {};
  for (const line of String(content || "").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const idx = trimmed.indexOf("=");
    if (idx <= 0) continue;
    const key = trimmed.slice(0, idx).trim();
    const val = trimmed.slice(idx + 1).trim().replace(/^['"]|['"]$/g, "");
    out[key] = val;
  }
  return out;
}

async function loadLocalEnv(filePath) {
  try {
    const raw = await fs.readFile(filePath, "utf-8");
    const parsed = parseDotEnv(raw);
    for (const [key, val] of Object.entries(parsed)) {
      if (!(key in process.env)) process.env[key] = val;
    }
  } catch {
    // ignore
  }
}

function numberEnv(name, fallback) {
  const raw = Number(process.env[name]);
  return Number.isFinite(raw) ? raw : fallback;
}

await loadLocalEnv(path.join(__dirname, ".env"));

const CONFIG = {
  supportAddress: process.env.SUPPORT_TRC20_ADDRESS || "TXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
  minAmount: numberEnv("SUPPORT_MIN_AMOUNT", 1),
  minConfirmations: numberEnv("SUPPORT_MIN_CONFIRMATIONS", 15),
  tronscanBase: (process.env.SUPPORT_TRONSCAN_API_BASE || "https://apilist.tronscanapi.com").replace(/\/+$/, ""),
  trongridBase: (process.env.SUPPORT_TRONGRID_API_BASE || "https://api.trongrid.io").replace(/\/+$/, ""),
  trongridApiKey: process.env.SUPPORT_TRONGRID_API_KEY || "",
  fetchLimit: numberEnv("SUPPORT_FETCH_LIMIT", 120),
  fetchTimeoutMs: numberEnv("SUPPORT_FETCH_TIMEOUT_MS", 12000),
  intervalSec: numberEnv("SUPPORT_WORKER_INTERVAL_SEC", 45),
};

const runtimeDir = process.env.SUPPORT_RUNTIME_DIR || path.join(__dirname, "runtime");
const chainStatePath = process.env.SUPPORT_CHAIN_STATE_PATH || path.join(runtimeDir, "chain-state.json");
const appStatePath = process.env.SUPPORT_APP_STATE_PATH || path.join(runtimeDir, "app-state.json");
await ensureJsonFile(chainStatePath, DEFAULT_CHAIN_STATE);
await ensureJsonFile(appStatePath, DEFAULT_APP_STATE);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizeTxHash(raw) {
  return String(raw || "").trim().toLowerCase();
}

function upsertReceipts(currentRows, incomingRows) {
  const map = new Map();
  for (const row of currentRows || []) {
    if (!row || typeof row !== "object") continue;
    const key = normalizeTxHash(row.tx_hash);
    if (!key) continue;
    map.set(key, row);
  }

  let inserted = 0;
  let updated = 0;
  for (const row of incomingRows || []) {
    if (!row || typeof row !== "object") continue;
    const key = normalizeTxHash(row.tx_hash);
    if (!key) continue;
    const prev = map.get(key);
    if (!prev) {
      map.set(key, row);
      inserted += 1;
      continue;
    }
    const merged = {
      ...prev,
      ...row,
      source: prev.source === row.source ? prev.source : "dual",
      confirmations: Math.max(Number(prev.confirmations || 0), Number(row.confirmations || 0)),
      amount: Number(prev.amount || 0) > 0 ? prev.amount : row.amount,
      confirmed_at_utc: prev.confirmed_at_utc || row.confirmed_at_utc || null,
      status: (prev.status === "verified" || row.status === "verified") ? "verified" : "pending",
    };
    map.set(key, merged);
    updated += 1;
  }

  const rows = Array.from(map.values()).sort((a, b) => {
    const aTs = Date.parse(a.confirmed_at_utc || "") || 0;
    const bTs = Date.parse(b.confirmed_at_utc || "") || 0;
    return bTs - aTs;
  });
  return { rows, inserted, updated };
}

function normalizeStatuses(rows, minConfirmations) {
  return (rows || []).map((row) => {
    const confirmations = Number(row.confirmations || 0);
    const status = confirmations >= minConfirmations ? "verified" : (row.status === "verified" ? "verified" : "pending");
    return { ...row, confirmations, status };
  });
}

function updateSourceState(sourceState, result) {
  const current = sourceState[result.source] || {
    ok: false,
    last_success_utc: null,
    last_error_utc: null,
    last_error: null,
    last_count: 0,
  };
  if (result.ok) {
    sourceState[result.source] = {
      ...current,
      ok: true,
      last_success_utc: nowIso(),
      last_error: null,
      last_count: Array.isArray(result.transfers) ? result.transfers.length : 0,
    };
  } else {
    sourceState[result.source] = {
      ...current,
      ok: false,
      last_error_utc: nowIso(),
      last_error: result.error || "unknown_error",
      last_count: 0,
    };
  }
}

function appendEvent(state, eventType, payload) {
  if (!Array.isArray(state.events)) state.events = [];
  state.events.push({
    id: `evt_${Math.random().toString(36).slice(2, 12)}`,
    event_type: eventType,
    payload,
    created_at_utc: nowIso(),
  });
  state.events = state.events.slice(-2000);
}

async function pollOnce() {
  const chainState = await readJsonFile(chainStatePath, DEFAULT_CHAIN_STATE);
  const appState = await readJsonFile(appStatePath, DEFAULT_APP_STATE);

  const sourceConfig = {
    supportAddress: CONFIG.supportAddress,
    tronscanBase: CONFIG.tronscanBase,
    trongridBase: CONFIG.trongridBase,
    trongridApiKey: CONFIG.trongridApiKey,
    fetchLimit: CONFIG.fetchLimit,
    fetchTimeoutMs: CONFIG.fetchTimeoutMs,
  };

  const [tronscan, trongrid] = await Promise.all([
    fetchTronscan(sourceConfig),
    fetchTrongrid(sourceConfig),
  ]);
  updateSourceState(chainState.source_status || (chainState.source_status = {}), tronscan);
  updateSourceState(chainState.source_status, trongrid);

  const mergedRows = mergeTransfers(tronscan.transfers, trongrid.transfers)
    .filter((row) => Number(row.amount || 0) >= CONFIG.minAmount)
    .filter((row) => row.to_addr === CONFIG.supportAddress);
  const normalizedRows = normalizeStatuses(mergedRows, CONFIG.minConfirmations);
  const upserted = upsertReceipts(chainState.tx_receipts || [], normalizedRows);
  chainState.tx_receipts = upserted.rows;

  const board = buildLeaderboard(chainState, appState, { minAmount: CONFIG.minAmount, limit: 1 });
  const newKing = board.king ? normalizeTxHash(board.king.tx_hash) : null;
  const oldKing = normalizeTxHash(chainState.current_king_tx_hash);
  if (newKing && newKing !== oldKing) {
    appendEvent(chainState, "king_replaced", {
      previous_king_tx_hash: oldKing || null,
      new_king_tx_hash: newKing,
      amount_usdt: board.king.amount_usdt,
      wallet_masked: board.king.wallet_masked,
    });
  }
  chainState.current_king_tx_hash = newKing || null;
  chainState.meta = chainState.meta || {};
  chainState.meta.chain = "TRON";
  chainState.meta.token = "USDT";
  chainState.meta.support_address = CONFIG.supportAddress;
  if (!chainState.meta.created_at_utc) chainState.meta.created_at_utc = nowIso();
  chainState.meta.updated_at_utc = nowIso();

  await writeJsonAtomic(chainStatePath, chainState);

  // eslint-disable-next-line no-console
  console.log(
    JSON.stringify({
      ts_utc: nowIso(),
      event: "SUPPORT_WORKER_POLL",
      tronscan_ok: tronscan.ok,
      trongrid_ok: trongrid.ok,
      merged: mergedRows.length,
      inserted: upserted.inserted,
      updated: upserted.updated,
      king_tx_hash: newKing,
    }),
  );
}

async function main() {
  // eslint-disable-next-line no-console
  console.log(
    `[support-worker] started | interval=${CONFIG.intervalSec}s | address=${CONFIG.supportAddress} | min=${CONFIG.minAmount}`,
  );
  while (true) {
    try {
      await pollOnce();
    } catch (error) {
      // eslint-disable-next-line no-console
      console.error("[support-worker][error]", error?.message || error);
    }
    await sleep(Math.max(5, CONFIG.intervalSec) * 1000);
  }
}

main().catch((error) => {
  // eslint-disable-next-line no-console
  console.error("[support-worker][fatal]", error?.message || error);
  process.exit(1);
});
