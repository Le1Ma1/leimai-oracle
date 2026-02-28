import fs from "node:fs/promises";
import path from "node:path";

const WRITE_RETRY_ATTEMPTS = 8;
const WRITE_RETRY_BASE_DELAY_MS = 40;
const WRITE_RETRY_BACKOFF = 1.7;

export const DEFAULT_CHAIN_STATE = {
  meta: {
    chain: "TRON",
    token: "USDT",
    support_address: "",
    created_at_utc: "",
    updated_at_utc: "",
  },
  tx_receipts: [],
  source_status: {
    tronscan: {
      ok: false,
      last_success_utc: null,
      last_error_utc: null,
      last_error: null,
      last_count: 0,
    },
    trongrid: {
      ok: false,
      last_success_utc: null,
      last_error_utc: null,
      last_error: null,
      last_count: 0,
    },
  },
  current_king_tx_hash: null,
  events: [],
};

export const DEFAULT_APP_STATE = {
  declarations: [],
  blacklist: {
    wallets: [],
    keywords: [
      "guaranteed return",
      "guaranteed profit",
      "profit guarantee",
      "scam",
      "fraud",
      "hate",
      "terror",
      "porn",
      "drug",
      "weapon",
    ],
  },
  events: [],
  moderation_stats: {
    approved: 0,
    rejected: 0,
    pending: 0,
  },
  created_at_utc: "",
  updated_at_utc: "",
};

export function nowIso() {
  return new Date().toISOString();
}

function deepClone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function ensureJsonFile(filePath, fallbackData) {
  const dir = path.dirname(filePath);
  await fs.mkdir(dir, { recursive: true });

  try {
    await fs.access(filePath);
  } catch {
    const payload = deepClone(fallbackData);
    if (payload && typeof payload === "object") {
      if ("created_at_utc" in payload && !payload.created_at_utc) {
        payload.created_at_utc = nowIso();
      }
      if ("updated_at_utc" in payload && !payload.updated_at_utc) {
        payload.updated_at_utc = nowIso();
      }
      if (payload.meta && typeof payload.meta === "object") {
        if (!payload.meta.created_at_utc) payload.meta.created_at_utc = nowIso();
        if (!payload.meta.updated_at_utc) payload.meta.updated_at_utc = nowIso();
      }
    }
    await fs.writeFile(filePath, JSON.stringify(payload, null, 2), "utf-8");
  }
}

export async function readJsonFile(filePath, fallbackData) {
  try {
    const raw = await fs.readFile(filePath, "utf-8");
    return JSON.parse(raw);
  } catch {
    return deepClone(fallbackData);
  }
}

export async function writeJsonAtomic(filePath, data) {
  const dir = path.dirname(filePath);
  await fs.mkdir(dir, { recursive: true });
  const serialized = JSON.stringify(data, null, 2);
  let lastError = null;

  for (let attempt = 1; attempt <= WRITE_RETRY_ATTEMPTS; attempt += 1) {
    const tmpPath = `${filePath}.tmp.${process.pid}.${attempt}`;
    try {
      await fs.writeFile(tmpPath, serialized, "utf-8");
      await fs.rename(tmpPath, filePath);
      return true;
    } catch (error) {
      lastError = error;
      try {
        await fs.unlink(tmpPath);
      } catch {
        // ignore cleanup errors
      }
      if (attempt < WRITE_RETRY_ATTEMPTS) {
        const waitMs = WRITE_RETRY_BASE_DELAY_MS * (WRITE_RETRY_BACKOFF ** (attempt - 1));
        await sleep(waitMs);
      }
    }
  }

  try {
    await fs.writeFile(filePath, serialized, "utf-8");
    return true;
  } catch (error) {
    lastError = error;
  }

  // eslint-disable-next-line no-console
  console.error("[support][write_failed]", filePath, lastError?.message || lastError);
  return false;
}

export function maskWallet(wallet) {
  if (!wallet || typeof wallet !== "string") return "";
  if (wallet.length <= 10) return wallet;
  return `${wallet.slice(0, 6)}...${wallet.slice(-4)}`;
}

export function uniqueStrings(items) {
  const seen = new Set();
  const out = [];
  for (const item of items || []) {
    if (typeof item !== "string") continue;
    const trimmed = item.trim();
    if (!trimmed) continue;
    const key = trimmed.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(trimmed);
  }
  return out;
}
