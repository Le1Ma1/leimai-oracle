import http from "node:http";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { createClient } from "@supabase/supabase-js";
import { getAddress, verifyMessage } from "ethers";
import { marked } from "marked";
import sanitizeHtml from "sanitize-html";

import { fetchTronscan, fetchTrongrid, mergeTransfers } from "./lib/chain-sources.mjs";
import { getContent, listLocales, resolveLocale } from "./lib/content.mjs";
import { buildLeaderboard, extractAds, summarizeCounts } from "./lib/leaderboard.mjs";
import { createDeclarationRecord, moderateDeclaration, validateDeclarationPayload } from "./lib/moderation.mjs";
import {
  DEFAULT_APP_STATE,
  DEFAULT_CHAIN_STATE,
  ensureJsonFile,
  nowIso,
  readJsonFile,
  uniqueStrings,
  writeJsonAtomic,
} from "./lib/storage.mjs";
import { buildLlmsTxt, buildPageSeo, buildRobots, buildSitemap } from "./lib/seo.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const LOCALES = listLocales();
const PREVIEW_DIR = path.join(__dirname, "preview");
const IS_VERCEL_RUNTIME = String(process.env.VERCEL || "").toLowerCase() === "1";
const ROOT_CANONICAL_URL = "https://leimaitech.com/";
const DEFAULT_REPORT_LOCALE = "en";
const REPORT_SELECT_FIELDS = "report_id,event_id,locale,title,slug,body_md,jsonld,unique_entity,created_at,updated_at";
const REPORT_PREVIEW_RATIO = 0.2;
const PAYWALL_SELECTOR = ".paywall-locked-content";
const PAYWALL_NOTICE = "\u6b64\u9810\u8a00\u53d7 LeiMai \u6b0a\u9650\u5354\u8b70\u4fdd\u8b77\uff0c\u8acb\u9023\u63a5\u51b7\u9322\u5305\u7c3d\u7f72\u300e\u929c\u5c3e\u86c7\u5951\u7d04\u300f\u4ee5\u89e3\u9396 Alpha \u5168\u6587\u3002";
const NEGOTIATING_NOTICE = "Negotiating Secure Enclave...";
const UNLOCK_COOKIE_NAME = "leimai_unlock";
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
      if (!(key in process.env)) {
        process.env[key] = val;
      }
    }
  } catch {
    // .env is optional
  }
}

function numberEnv(name, fallback) {
  const raw = Number(process.env[name]);
  return Number.isFinite(raw) ? raw : fallback;
}

function boolEnv(name, fallback) {
  const raw = process.env[name];
  if (raw == null) return fallback;
  return ["1", "true", "yes", "on"].includes(String(raw).toLowerCase());
}

await loadLocalEnv(path.join(__dirname, ".env"));

const CONFIG = {
  port: numberEnv("SUPPORT_PORT", 4310),
  siteUrl: (process.env.SUPPORT_SITE_URL || "http://localhost:4310").replace(/\/+$/, ""),
  mainSiteUrl: (process.env.SUPPORT_MAIN_SITE_URL || "https://leimaitech.com").replace(/\/+$/, ""),
  supportAddress: process.env.SUPPORT_TRC20_ADDRESS || "TXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
  minAmount: numberEnv("SUPPORT_MIN_AMOUNT", 1),
  minConfirmations: numberEnv("SUPPORT_MIN_CONFIRMATIONS", 15),
  declarationMaxLength: numberEnv("SUPPORT_DECLARATION_MAX_LENGTH", 280),
  adminToken: process.env.SUPPORT_ADMIN_TOKEN || "",
  rateLimitPerMinute: numberEnv("SUPPORT_RATE_LIMIT_PER_MINUTE", 20),
  fetchLimit: numberEnv("SUPPORT_FETCH_LIMIT", 120),
  fetchTimeoutMs: numberEnv("SUPPORT_FETCH_TIMEOUT_MS", 12000),
  tronscanBase: (process.env.SUPPORT_TRONSCAN_API_BASE || "https://apilist.tronscanapi.com").replace(/\/+$/, ""),
  trongridBase: (process.env.SUPPORT_TRONGRID_API_BASE || "https://api.trongrid.io").replace(/\/+$/, ""),
  trongridApiKey: process.env.SUPPORT_TRONGRID_API_KEY || "",
  supabaseUrl: (process.env.SUPABASE_URL || "").replace(/\/+$/, ""),
  supabaseAnonKey: process.env.SUPABASE_ANON_KEY || "",
  supabaseServiceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY || "",
  cronSecret: process.env.CRON_SECRET || "",
  sessionSecret: process.env.SUPPORT_SESSION_SECRET || "",
  authNonceTtlSec: numberEnv("SUPPORT_AUTH_NONCE_TTL_SEC", 300),
  unlockTtlSec: numberEnv("SUPPORT_UNLOCK_TTL_SEC", 86400),
  cookieSecure: boolEnv("SUPPORT_COOKIE_SECURE", IS_VERCEL_RUNTIME),
  exposeDebug: boolEnv("SUPPORT_EXPOSE_DEBUG", false),
};

const runtimeDir = process.env.SUPPORT_RUNTIME_DIR || (IS_VERCEL_RUNTIME ? "/tmp/support-runtime" : path.join(__dirname, "runtime"));
const chainStatePath = process.env.SUPPORT_CHAIN_STATE_PATH || path.join(runtimeDir, "chain-state.json");
const appStatePath = process.env.SUPPORT_APP_STATE_PATH || path.join(runtimeDir, "app-state.json");
await ensureJsonFile(chainStatePath, DEFAULT_CHAIN_STATE);
await ensureJsonFile(appStatePath, DEFAULT_APP_STATE);

const rateBucket = new Map();
const walletChallengeStore = new Map();

function nowMs() {
  return Date.now();
}

function base64UrlEncode(raw) {
  return Buffer.from(raw, "utf-8").toString("base64url");
}

function base64UrlDecode(raw) {
  return Buffer.from(String(raw || ""), "base64url").toString("utf-8");
}

function toCanonicalAddress(address) {
  try {
    return getAddress(String(address || "").trim());
  } catch {
    return null;
  }
}

function parseCookies(req) {
  const raw = String(req.headers?.cookie || "");
  const out = {};
  for (const entry of raw.split(";")) {
    const idx = entry.indexOf("=");
    if (idx <= 0) continue;
    const key = entry.slice(0, idx).trim();
    const val = entry.slice(idx + 1).trim();
    if (!key) continue;
    try {
      out[key] = decodeURIComponent(val);
    } catch {
      out[key] = val;
    }
  }
  return out;
}

function hmacHex(secret, data) {
  return createHmac("sha256", secret).update(data).digest("hex");
}

function signUnlockToken(payloadObj) {
  if (!CONFIG.sessionSecret) return null;
  const payload = base64UrlEncode(JSON.stringify(payloadObj));
  const sig = hmacHex(CONFIG.sessionSecret, payload);
  return `${payload}.${sig}`;
}

function verifyUnlockToken(token) {
  if (!CONFIG.sessionSecret) return null;
  const raw = String(token || "");
  const idx = raw.indexOf(".");
  if (idx <= 0) return null;
  const payload = raw.slice(0, idx);
  const sig = raw.slice(idx + 1);
  const expected = hmacHex(CONFIG.sessionSecret, payload);
  const a = Buffer.from(sig, "utf-8");
  const b = Buffer.from(expected, "utf-8");
  if (a.length !== b.length || !timingSafeEqual(a, b)) return null;

  try {
    const decoded = JSON.parse(base64UrlDecode(payload));
    const exp = Number(decoded?.exp || 0);
    const addr = toCanonicalAddress(decoded?.addr || "");
    if (!addr || !Number.isFinite(exp) || nowMs() >= exp * 1000) return null;
    if (decoded?.scope !== "analysis:*") return null;
    return {
      addr,
      iat: Number(decoded?.iat || 0),
      exp,
      scope: String(decoded?.scope || ""),
    };
  } catch {
    return null;
  }
}

function buildUnlockCookie(token) {
  const attrs = [
    `${UNLOCK_COOKIE_NAME}=${encodeURIComponent(token)}`,
    "Path=/analysis",
    "HttpOnly",
    "SameSite=Lax",
    `Max-Age=${Math.max(60, Math.floor(CONFIG.unlockTtlSec))}`,
  ];
  if (CONFIG.cookieSecure) attrs.push("Secure");
  return attrs.join("; ");
}

function clearUnlockCookie() {
  const attrs = [
    `${UNLOCK_COOKIE_NAME}=`,
    "Path=/analysis",
    "HttpOnly",
    "SameSite=Lax",
    "Max-Age=0",
  ];
  if (CONFIG.cookieSecure) attrs.push("Secure");
  return attrs.join("; ");
}

function getUnlockSessionFromReq(req) {
  const cookies = parseCookies(req);
  const token = cookies[UNLOCK_COOKIE_NAME];
  if (!token) return null;
  return verifyUnlockToken(token);
}

function generateWalletChallenge(slug) {
  const normalizedSlug = normalizeReportSlug(slug) || "analysis";
  const nonce = randomBytes(16).toString("hex");
  const timestamp = new Date(nowMs()).toISOString();
  const message = [
    "I am a Sovereign Entity accessing LeiMai Oracle. I agree to the Ouroboros Protocol.",
    `Timestamp: ${timestamp}.`,
    `Nonce: ${nonce}.`,
    `Slug: ${normalizedSlug}`,
  ].join(" ");
  const expiresAtMs = nowMs() + Math.max(60, Math.floor(CONFIG.authNonceTtlSec)) * 1000;
  walletChallengeStore.set(nonce, {
    nonce,
    slug: normalizedSlug,
    message,
    expiresAtMs,
    consumed: false,
  });
  return {
    nonce,
    message,
    expiresAtUtc: new Date(expiresAtMs).toISOString(),
  };
}

function extractNonceFromMessage(message) {
  const m = String(message || "").match(/Nonce:\s*([a-fA-F0-9]{8,64})\./);
  return m ? String(m[1]).toLowerCase() : "";
}

function consumeWalletChallenge(nonce) {
  const key = String(nonce || "").toLowerCase();
  const row = walletChallengeStore.get(key);
  if (!row) return null;
  walletChallengeStore.delete(key);
  if (row.consumed) return null;
  if (!Number.isFinite(row.expiresAtMs) || nowMs() > row.expiresAtMs) return null;
  return row;
}

function purgeExpiredChallenges() {
  const ts = nowMs();
  for (const [key, row] of walletChallengeStore.entries()) {
    if (!row || !Number.isFinite(row.expiresAtMs) || ts > row.expiresAtMs) {
      walletChallengeStore.delete(key);
    }
  }
}

function jsonResponse(res, status, payload) {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  res.end(JSON.stringify(payload));
}

function textResponse(res, status, text, type = "text/plain; charset=utf-8") {
  res.writeHead(status, { "Content-Type": type });
  res.end(text);
}

async function servePreviewFile(res, fileName, contentType = "text/html; charset=utf-8") {
  const filePath = path.join(PREVIEW_DIR, fileName);
  const payload = await fs.readFile(filePath, "utf-8");
  return textResponse(res, 200, payload, contentType);
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function buildSocialCardSvg() {
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" role="img" aria-label="LeiMai Throne">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0a210f"/>
      <stop offset="100%" stop-color="#050505"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#g)"/>
  <rect x="36" y="36" width="1128" height="558" fill="none" stroke="#39ff14" stroke-opacity="0.35"/>
  <text x="72" y="140" fill="#39ff14" font-size="30" font-family="Consolas, monospace">LEIMAI THRONE</text>
  <text x="72" y="250" fill="#ffffff" font-size="66" font-family="Consolas, monospace">PROOF OF WEALTH</text>
  <text x="72" y="340" fill="#9fc89d" font-size="26" font-family="Consolas, monospace">Highest single verified USDT transfer rules the throne.</text>
  <text x="72" y="500" fill="#39ff14" font-size="22" font-family="Consolas, monospace">support.leimaitech.com</text>
</svg>`;
}

function normalizeTxHash(raw) {
  return String(raw || "").trim().toLowerCase();
}

function normalizeWallet(raw) {
  return String(raw || "").trim();
}

function normalizeReportSlug(raw) {
  return String(raw || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, "");
}

function getBearerToken(req) {
  const auth = String(req.headers?.authorization || "");
  const m = auth.match(/^Bearer\s+(.+)$/i);
  return m ? m[1].trim() : "";
}

function isCronAuthorized(req) {
  if (!CONFIG.cronSecret) return false;
  const headerSecret = String(req.headers["x-cron-secret"] || "");
  const bearer = getBearerToken(req);
  return headerSecret === CONFIG.cronSecret || bearer === CONFIG.cronSecret;
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

export async function pollChainNow() {
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

  return {
    ts_utc: nowIso(),
    event: "SUPPORT_CHAIN_POLL",
    tronscan_ok: tronscan.ok,
    trongrid_ok: trongrid.ok,
    merged: mergedRows.length,
    inserted: upserted.inserted,
    updated: upserted.updated,
    king_tx_hash: newKing,
  };
}

function ipFromReq(req) {
  const fwd = req.headers["x-forwarded-for"];
  if (typeof fwd === "string" && fwd.trim()) return fwd.split(",")[0].trim();
  return req.socket.remoteAddress || "unknown";
}

function checkRateLimit(req, scope, limitPerMin) {
  const ip = ipFromReq(req);
  const key = `${scope}:${ip}`;
  const now = Date.now();
  const windowMs = 60_000;
  const bucket = rateBucket.get(key) || [];
  const filtered = bucket.filter((ts) => now - ts < windowMs);
  if (filtered.length >= limitPerMin) {
    rateBucket.set(key, filtered);
    return false;
  }
  filtered.push(now);
  rateBucket.set(key, filtered);
  return true;
}

async function readStates() {
  const [chainState, appState] = await Promise.all([
    readJsonFile(chainStatePath, DEFAULT_CHAIN_STATE),
    readJsonFile(appStatePath, DEFAULT_APP_STATE),
  ]);
  return { chainState, appState };
}

function syncModerationStats(appState) {
  const declarations = Array.isArray(appState.declarations) ? appState.declarations : [];
  appState.moderation_stats = {
    approved: declarations.filter((x) => x?.status === "approved").length,
    rejected: declarations.filter((x) => x?.status === "rejected").length,
    pending: declarations.filter((x) => x?.status === "pending").length,
  };
}

async function saveAppState(appState) {
  syncModerationStats(appState);
  appState.updated_at_utc = nowIso();
  if (!appState.created_at_utc) {
    appState.created_at_utc = nowIso();
  }
  await writeJsonAtomic(appStatePath, appState);
}

function requireAdmin(req, res) {
  if (!CONFIG.adminToken) {
    jsonResponse(res, 500, { ok: false, error: "admin_token_not_configured" });
    return false;
  }
  const token = String(req.headers["x-admin-token"] || "");
  if (token !== CONFIG.adminToken) {
    jsonResponse(res, 401, { ok: false, error: "unauthorized" });
    return false;
  }
  return true;
}

async function parseJsonBody(req, maxBytes = 64 * 1024) {
  const chunks = [];
  let total = 0;
  for await (const chunk of req) {
    total += chunk.length;
    if (total > maxBytes) {
      throw new Error("payload_too_large");
    }
    chunks.push(chunk);
  }
  if (chunks.length === 0) return {};
  const raw = Buffer.concat(chunks).toString("utf-8");
  return JSON.parse(raw);
}

function appendEvent(stateObj, eventType, payload) {
  if (!Array.isArray(stateObj.events)) stateObj.events = [];
  stateObj.events.push({
    id: `evt_${Math.random().toString(36).slice(2, 12)}`,
    event_type: eventType,
    payload,
    created_at_utc: nowIso(),
  });
  stateObj.events = stateObj.events.slice(-2000);
}

function buildKnowledgePayload(locale, leaderboard, king, ads) {
  const content = getContent(locale);
  return {
    site: "LeiMai Throne",
    locale,
    title: content.title,
    description: content.description,
    keywords: content.keywords,
    intent: "support_and_social_signaling",
    ranking_formula: "highest_single_verified_transfer",
    ranking_asset: "USDT",
    ranking_chain: "TRON",
    routes: {
      home: `/${locale}`,
      faq: `/${locale}/faq`,
      rules: `/${locale}/rules`,
    },
    compliance: [content.policy1, content.policy2, content.policy3],
    king,
    leaderboard_top5: leaderboard.slice(0, 5),
    approved_ads: ads.rows,
    generated_at_utc: nowIso(),
  };
}

function formatMoney(v) {
  const n = Number(v || 0);
  if (!Number.isFinite(n)) return "0.00";
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

let supabaseClientSingleton = null;
let supabaseServiceClientSingleton = null;

function getSupabaseClient() {
  if (supabaseClientSingleton) return supabaseClientSingleton;
  if (!CONFIG.supabaseUrl || !CONFIG.supabaseAnonKey) return null;
  supabaseClientSingleton = createClient(CONFIG.supabaseUrl, CONFIG.supabaseAnonKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  return supabaseClientSingleton;
}

function getSupabaseServiceClient() {
  if (supabaseServiceClientSingleton) return supabaseServiceClientSingleton;
  if (!CONFIG.supabaseUrl || !CONFIG.supabaseServiceRoleKey) return null;
  supabaseServiceClientSingleton = createClient(CONFIG.supabaseUrl, CONFIG.supabaseServiceRoleKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  return supabaseServiceClientSingleton;
}

async function logUserAccess({ walletAddress, slug }) {
  const client = getSupabaseServiceClient();
  if (!client) return false;
  const canonicalAddress = toCanonicalAddress(walletAddress);
  const normalizedSlug = String(slug || "").trim().toLowerCase();
  if (!canonicalAddress || !normalizedSlug) return false;
  const { error } = await client.from("user_access_logs").insert({
    wallet_address: canonicalAddress,
    slug: normalizedSlug,
    signed_at_utc: nowIso(),
    source: "wallet_signature",
  });
  return !error;
}

function normalizeReportRow(raw) {
  const row = raw && typeof raw === "object" ? raw : {};
  return {
    report_id: Number(row.report_id || 0),
    event_id: String(row.event_id || ""),
    locale: String(row.locale || DEFAULT_REPORT_LOCALE),
    title: String(row.title || ""),
    slug: String(row.slug || ""),
    body_md: String(row.body_md || ""),
    jsonld: row.jsonld && typeof row.jsonld === "object" ? row.jsonld : {},
    unique_entity: String(row.unique_entity || ""),
    created_at: String(row.created_at || ""),
    updated_at: String(row.updated_at || row.created_at || ""),
  };
}

function markdownToPlainText(md) {
  return String(md || "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\!\[([^\]]*)\]\([^)]+\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[#>*_~\-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function buildSummary(md, maxLen = 180) {
  const plain = markdownToPlainText(md);
  if (plain.length <= maxLen) return plain;
  return `${plain.slice(0, maxLen).trimEnd()}...`;
}

function buildPreviewMarkdown(md, ratio = REPORT_PREVIEW_RATIO) {
  const src = String(md || "").trim();
  if (!src) return "";

  const safeRatio = Math.min(0.95, Math.max(0.05, Number(ratio) || REPORT_PREVIEW_RATIO));
  const targetChars = Math.max(220, Math.floor(src.length * safeRatio));
  const blocks = src.split(/\n{2,}/).map((block) => block.trim()).filter(Boolean);

  let preview = "";
  for (const block of blocks) {
    const candidate = preview ? `${preview}\n\n${block}` : block;
    if (candidate.length <= targetChars || !preview) {
      preview = candidate;
      continue;
    }
    break;
  }

  if (!preview) {
    preview = src.slice(0, targetChars);
  }
  if (preview.length < Math.min(targetChars, src.length)) {
    preview = src.slice(0, targetChars);
  }
  return preview.trim();
}

function sanitizeMarkdownHtml(md) {
  const rawHtml = String(marked.parse(String(md || ""), { breaks: true, gfm: true }));
  return sanitizeHtml(rawHtml, {
    allowedTags: [
      ...sanitizeHtml.defaults.allowedTags,
      "h1",
      "h2",
      "h3",
      "h4",
      "img",
      "pre",
      "code",
      "hr",
      "table",
      "thead",
      "tbody",
      "tr",
      "th",
      "td",
    ],
    allowedAttributes: {
      ...sanitizeHtml.defaults.allowedAttributes,
      a: ["href", "name", "target", "rel"],
      img: ["src", "alt"],
    },
    allowedSchemes: ["http", "https", "mailto"],
    transformTags: {
      a: sanitizeHtml.simpleTransform("a", { target: "_blank", rel: "noopener noreferrer" }),
    },
  });
}

function normalizeJsonLd(raw, fallback = {}) {
  if (raw && typeof raw === "object") return raw;
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : fallback;
    } catch {
      return fallback;
    }
  }
  return fallback;
}

function serializeJsonLd(raw) {
  return JSON.stringify(normalizeJsonLd(raw)).replace(/</g, "\\u003c");
}

function paywallHasPart() {
  return [
    {
      "@type": "WebPageElement",
      "isAccessibleForFree": false,
      "cssSelector": PAYWALL_SELECTOR,
    },
  ];
}

function withPaywallJsonLd(raw) {
  const jsonLd = normalizeJsonLd(raw, {});
  if (Array.isArray(jsonLd["@graph"])) {
    return {
      ...jsonLd,
      "@graph": jsonLd["@graph"].map((node) => {
        if (!node || typeof node !== "object") return node;
        const nodeType = String(node["@type"] || "");
        const isPaywallNode =
          nodeType === "Article" ||
          nodeType === "NewsArticle" ||
          nodeType === "Report" ||
          nodeType === "WebPage";
        if (!isPaywallNode) return node;
        return {
          ...node,
          isAccessibleForFree: false,
          hasPart: paywallHasPart(),
        };
      }),
    };
  }
  const nodeType = String(jsonLd["@type"] || "");
  const isPaywallNode =
    nodeType === "Article" ||
    nodeType === "NewsArticle" ||
    nodeType === "Report" ||
    nodeType === "WebPage";
  if (!isPaywallNode) return jsonLd;
  return {
    ...jsonLd,
    isAccessibleForFree: false,
    hasPart: paywallHasPart(),
  };
}

async function fetchLatestReports(limit = 5) {
  const client = getSupabaseClient();
  if (!client) return [];
  const safeLimit = Math.min(Math.max(1, Number(limit) || 5), 50);

  const primary = await client
    .from("oracle_reports")
    .select(REPORT_SELECT_FIELDS)
    .eq("locale", DEFAULT_REPORT_LOCALE)
    .order("updated_at", { ascending: false })
    .limit(safeLimit);
  if (!primary.error && Array.isArray(primary.data) && primary.data.length > 0) {
    return primary.data.map(normalizeReportRow);
  }

  const fallback = await client
    .from("oracle_reports")
    .select(REPORT_SELECT_FIELDS)
    .order("updated_at", { ascending: false })
    .limit(safeLimit);
  if (fallback.error || !Array.isArray(fallback.data)) {
    return [];
  }
  return fallback.data.map(normalizeReportRow);
}

async function fetchReportsForIndex(limit = 200) {
  const client = getSupabaseClient();
  if (!client) return [];
  const safeLimit = Math.min(Math.max(1, Number(limit) || 200), 5000);
  const { data, error } = await client
    .from("oracle_reports")
    .select(REPORT_SELECT_FIELDS)
    .order("updated_at", { ascending: false })
    .limit(safeLimit);
  if (error || !Array.isArray(data)) return [];
  return data.map(normalizeReportRow);
}

async function fetchReportBySlug(slug) {
  const client = getSupabaseClient();
  if (!client) return null;
  const cleaned = String(slug || "").trim().toLowerCase();
  if (!cleaned) return null;
  const { data, error } = await client
    .from("oracle_reports")
    .select(REPORT_SELECT_FIELDS)
    .eq("slug", cleaned)
    .maybeSingle();
  if (error || !data) return null;
  return normalizeReportRow(data);
}

async function fetchAnalysisPaths(limit = 5000) {
  const rows = await fetchReportsForIndex(limit);
  return rows.map((row) => `/analysis/${row.slug}`);
}

function normalizeAnalysisPath(pathname) {
  return String(pathname || "").replace(/\/+$/, "");
}

function renderOuroborosDocument({
  title,
  description,
  bodyHtml,
  jsonLd,
  canonicalUrl = ROOT_CANONICAL_URL,
  pageType = "generic",
}) {
  const ldPayload = serializeJsonLd(jsonLd || {});
  const ogUrl = String(canonicalUrl || ROOT_CANONICAL_URL);
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(title)}</title>
  <meta name="description" content="${escapeHtml(description)}">
  <meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">
  <meta property="og:type" content="website">
  <meta property="og:title" content="${escapeHtml(title)}">
  <meta property="og:description" content="${escapeHtml(description)}">
  <meta property="og:url" content="${escapeHtml(ogUrl)}">
  <meta property="og:image" content="${escapeHtml(CONFIG.siteUrl)}/assets/social-card.svg">
  <meta property="twitter:card" content="summary_large_image">
  <meta property="twitter:title" content="${escapeHtml(title)}">
  <meta property="twitter:description" content="${escapeHtml(description)}">
  <meta property="twitter:image" content="${escapeHtml(CONFIG.siteUrl)}/assets/social-card.svg">
  <link rel="canonical" href="${escapeHtml(ogUrl)}">
  <script type="application/ld+json">${ldPayload}</script>
  <link rel="stylesheet" href="/assets/ouroboros.css">
</head>
<body data-page="${escapeHtml(pageType)}">
  <canvas id="matrix-bg" aria-hidden="true"></canvas>
  <div class="page-noise" aria-hidden="true"></div>
  ${bodyHtml}
  <script src="/assets/ouroboros.js"></script>
</body>
</html>`;
}

function buildReportCard(report) {
  const summary = buildSummary(report.body_md, 220);
  const updatedAt = report.updated_at || report.created_at || "";
  return `<a class="matrix-card glass-panel cyber-border report-card" href="/analysis/${escapeHtml(report.slug)}" data-filter="${escapeHtml(`${report.locale} ${report.unique_entity} ${report.title}`)}">
    <div class="card-top terminal-font">
      <span>${escapeHtml(report.locale.toUpperCase())}</span>
      <span class="report-time terminal-font" data-utc="${escapeHtml(updatedAt)}">${escapeHtml(updatedAt || "-")}</span>
    </div>
    <div class="card-mid neon-text">${escapeHtml(report.title)}</div>
    <div class="card-sub">${escapeHtml(summary || "No summary available.")}</div>
    <div class="report-entity terminal-font">${escapeHtml(report.unique_entity || "LeiMai Liquidity Friction")}</div>
  </a>`;
}

function renderRootLandingPage(reports) {
  const rows = Array.isArray(reports) ? reports.slice(0, 5) : [];
  const cardHtml = rows.map(buildReportCard).join("");
  const hasRows = rows.length > 0;

  const bodyHtml = `<div id="vaultOverlay" class="vault-overlay">
    <div class="vault-door top"></div>
    <div class="vault-laser"></div>
    <div class="vault-door bottom">
      <button id="vaultEnterBtn" class="vault-enter-btn" type="button">[ Enter The Void ]</button>
    </div>
  </div>

  <main class="site-wrap">
    <header class="hero glass-panel cyber-border">
      <div class="hero-kicker terminal-font">LEIMAI ORACLE / OUROBOROS CORE</div>
      <h1 class="neon-text">Oracle Reports Wall</h1>
      <p>Live intelligence stream powered by real <code>oracle_reports</code> records from Supabase.</p>
      <div class="geo-badge terminal-font">
        <span>Hub:</span>
        <strong id="geoHub">Global</strong>
        <span id="geoTier">Platinum Node</span>
      </div>
      <div class="hero-cta-row">
        <a class="btn btn-main" href="/analysis/">Open Full Report Index</a>
        <a class="btn" href="https://leimaitech.com/" target="_blank" rel="noopener">Main Domain</a>
      </div>
    </header>

    <section class="panel glass-panel cyber-border">
      <h2>Latest 5 Oracle Reports</h2>
      <p class="muted">Realtime read from <code>public.oracle_reports</code>.</p>
      ${hasRows ? `<div id="analysisCards" class="matrix-grid">${cardHtml}</div>` : '<div class="empty-box">No reports available yet. Check ingestion/report pipeline.</div>'}
    </section>
  </main>`;

  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "WebSite",
        name: "LeiMai Oracle",
        url: ROOT_CANONICAL_URL,
        description: "Root authority endpoint for LeiMai Oracle Ouroboros entity.",
      },
      {
        "@type": "CollectionPage",
        name: "Oracle Reports Wall",
        url: `${CONFIG.siteUrl}/analysis/`,
        isPartOf: { "@type": "WebSite", name: "LeiMai Oracle", url: ROOT_CANONICAL_URL },
      },
    ],
  };

  return renderOuroborosDocument({
    title: "LeiMai Oracle | Ouroboros Root Authority",
    description:
      "Root authority node for LeiMai Oracle. Access realtime oracle reports and pSEO analysis pages backed by Supabase.",
    bodyHtml,
    jsonLd,
    canonicalUrl: ROOT_CANONICAL_URL,
    pageType: "home",
  });
}

function renderAnalysisIndexPage(reports) {
  const rows = Array.isArray(reports) ? reports : [];
  const cardHtml = rows.map(buildReportCard).join("");

  const bodyHtml = `<main class="site-wrap">
    <header class="hero hero-compact glass-panel cyber-border">
      <div class="hero-kicker terminal-font">ANALYSIS INDEX</div>
      <h1 class="neon-text">Oracle Report Index</h1>
      <p>Dynamic pSEO pages generated from anomaly-driven multilingual reports.</p>
      <div class="hero-cta-row">
        <input id="analysisSearch" class="input" type="search" placeholder="Filter: locale / entity / title">
        <a class="btn" href="/">Back to Root</a>
      </div>
    </header>

    <section class="panel glass-panel cyber-border">
      <h2>All Analysis Pages</h2>
      <p class="muted">Current total: ${rows.length} reports</p>
      ${rows.length > 0 ? `<div id="analysisCards" class="matrix-grid">${cardHtml}</div>` : '<div class="empty-box">No reports available yet.</div>'}
    </section>
  </main>`;

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: "LeiMai Oracle Analysis Matrix",
    url: `${CONFIG.siteUrl}/analysis/`,
    isPartOf: { "@type": "WebSite", name: "LeiMai Oracle", url: ROOT_CANONICAL_URL },
  };

  return renderOuroborosDocument({
    title: "LeiMai Oracle | Analysis Matrix",
    description: "Structured pSEO report index sourced from Oracle Brain outputs.",
    bodyHtml,
    jsonLd,
    canonicalUrl: `${ROOT_CANONICAL_URL}analysis/`,
    pageType: "analysis-index",
  });
}

function buildFallbackJsonLd(report) {
  return {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: report.title,
    description: buildSummary(report.body_md, 240),
    mainEntityOfPage: `${CONFIG.siteUrl}/analysis/${report.slug}`,
    isPartOf: { "@type": "WebSite", name: "LeiMai Oracle", url: ROOT_CANONICAL_URL },
    author: { "@type": "Organization", name: "LeiMai Oracle" },
    dateModified: report.updated_at || report.created_at || nowIso(),
    inLanguage: report.locale,
    isAccessibleForFree: false,
    hasPart: paywallHasPart(),
  };
}

function buildMandalaSvg() {
  const rings = Array.from({ length: 12 })
    .map((_, i) => {
      const pieces = Array.from({ length: 12 })
        .map((__, j) => {
          const angle = (j * 30 * Math.PI) / 180;
          const radius = 52 + i * 14;
          const cx = 250 + Math.cos(angle) * radius;
          const cy = 250 + Math.sin(angle) * radius;
          return `<path d="M250,250 L${cx.toFixed(2)},${cy.toFixed(2)} L${(cx + 8).toFixed(2)},${(cy + 8).toFixed(2)} Z" />`;
        })
        .join("");
      const spinSec = 38 + i * 8;
      const spinDir = i % 2 === 0 ? "normal" : "reverse";
      return `<g class="mandala-ring" style="--spin:${spinSec}s;--spin-dir:${spinDir};">${pieces}</g>`;
    })
    .join("");

  return `<svg class="mandala-svg" viewBox="0 0 500 500" role="img" aria-label="Algorithmic Mandala">
    <defs>
      <radialGradient id="mandalaGlow" cx="50%" cy="50%" r="50%">
        <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.30" />
        <stop offset="100%" stop-color="var(--accent)" stop-opacity="0.00" />
      </radialGradient>
    </defs>
    <circle cx="250" cy="250" r="238" fill="url(#mandalaGlow)"></circle>
    ${rings}
    <polygon points="250,220 270,250 250,280 230,250" class="mandala-core"></polygon>
    <circle cx="250" cy="250" r="4" class="mandala-center"></circle>
  </svg>`;
}

function renderAnalysisDetailPage(report, { unlocked = false, unlockedAddress = null } = {}) {
  const previewMarkdown = unlocked ? String(report.body_md || "") : buildPreviewMarkdown(report.body_md, REPORT_PREVIEW_RATIO);
  const summary = buildSummary(previewMarkdown || report.body_md, 220);
  const markdownHtml = sanitizeMarkdownHtml(previewMarkdown);
  const canonicalUrl = `${ROOT_CANONICAL_URL}analysis/${encodeURIComponent(report.slug)}`;
  const sourceJsonLd = normalizeJsonLd(report.jsonld, buildFallbackJsonLd(report));
  const paywallJsonLd = withPaywallJsonLd(sourceJsonLd);
  const paywallShellClass = unlocked ? "paywall-shell is-unlocked" : "paywall-shell";
  const lockMessage = unlocked ? "Access verified. Reload complete." : PAYWALL_NOTICE;
  const bodyHtml = `<main class="site-wrap">
    <header class="hero hero-compact glass-panel cyber-border">
      <div class="hero-kicker terminal-font">ANALYSIS DETAIL</div>
      <h1 class="neon-text">${escapeHtml(report.title)}</h1>
      <p>${escapeHtml(summary)}</p>
      <div class="hero-cta-row">
        <a class="btn btn-main" href="/analysis/">Back to Report Index</a>
        <a class="btn" href="/">Root</a>
      </div>
    </header>

    <section class="panel glass-panel cyber-border">
      <h2>Metadata</h2>
      <div class="kv-grid">
        <div class="kv-item"><span>Event</span><strong>${escapeHtml(report.event_id || "-")}</strong></div>
        <div class="kv-item"><span>Locale</span><strong>${escapeHtml(report.locale.toUpperCase())}</strong></div>
        <div class="kv-item"><span>Unique Entity</span><strong>${escapeHtml(report.unique_entity || "-")}</strong></div>
        <div class="kv-item"><span>Updated (UTC)</span><strong class="report-time terminal-font" data-utc="${escapeHtml(report.updated_at)}">${escapeHtml(report.updated_at || "-")}</strong></div>
        <div class="kv-item"><span>Access</span><strong>${unlocked ? "UNLOCKED" : "LOCKED"}</strong></div>
      </div>
    </section>

    <section class="panel glass-panel cyber-border">
      <h2>${unlocked ? "Full Report" : "Report Preview (20%)"}</h2>
      <div class="${paywallShellClass}" data-unlocked="${unlocked ? "1" : "0"}" data-slug="${escapeHtml(report.slug)}" data-unlocked-address="${escapeHtml(unlockedAddress || "")}">
        <div class="obsidian-container">
          <article class="report-article article-body paywall-preview">${markdownHtml}</article>
        </div>
        <div class="paywall-locked-content" aria-label="locked-content">
          <div class="paywall-fog obsidian-fog"></div>
          <div class="mandala-wrap">${buildMandalaSvg()}</div>
          <div class="lock-message">${escapeHtml(lockMessage)}</div>
          <button class="unlock-btn pulse-glow" type="button" ${unlocked ? "disabled" : ""}>${unlocked ? "[ ACCESS VERIFIED ]" : "[ SIGN OUROBOROS CONTRACT ]"}</button>
        </div>
      </div>
      <div class="route-line terminal-font">/analysis/${escapeHtml(report.slug)}</div>
      <div class="muted">${unlocked ? "Access policy: signed wallet verified for this session." : "Access policy: preview only for public web distribution."}</div>
    </section>

    <section class="panel glass-panel cyber-border">
      <h2>Structured Data (JSON-LD)</h2>
      <pre class="jsonld-preview">${escapeHtml(JSON.stringify(paywallJsonLd, null, 2))}</pre>
      <div class="muted">This payload is also embedded in &lt;head&gt; for GEO indexing.</div>
    </section>
  </main>`;

  return renderOuroborosDocument({
    title: `LeiMai Oracle | ${report.title}`,
    description: summary || "Oracle report detail page.",
    bodyHtml,
    jsonLd: paywallJsonLd,
    canonicalUrl,
    pageType: "analysis-detail",
  });
}

function renderAnalysisNotFoundPage(slug) {
  return renderOuroborosDocument({
    title: "Not Found | Analysis",
    description: "Requested analysis page does not exist.",
    bodyHtml: `<main class="site-wrap">
      <section class="panel glass-panel cyber-border">
        <h1>Analysis page not found</h1>
        <p class="muted">No report matched slug: <code>${escapeHtml(slug)}</code></p>
        <a class="btn btn-main" href="/analysis/">Back to report index</a>
      </section>
    </main>`,
    jsonLd: { "@context": "https://schema.org", "@type": "WebPage", name: "Analysis Not Found", url: ROOT_CANONICAL_URL },
    canonicalUrl: `${ROOT_CANONICAL_URL}analysis/`,
    pageType: "analysis-not-found",
  });
}

function goneResponse(res, pathname) {
  const html = renderOuroborosDocument({
    title: "410 Gone | LeiMai Oracle",
    description: "This legacy route has been permanently removed.",
    bodyHtml: `<main class="site-wrap">
      <section class="panel glass-panel cyber-border">
        <div class="hero-kicker terminal-font">410 GONE</div>
        <h1>Legacy route removed</h1>
        <p>Path <code>${escapeHtml(pathname)}</code> has been permanently decommissioned.</p>
        <div class="hero-cta-row">
          <a class="btn btn-main" href="/">Go to root</a>
          <a class="btn" href="/analysis/">Analysis matrix</a>
        </div>
      </section>
    </main>`,
    jsonLd: {
      "@context": "https://schema.org",
      "@type": "WebPage",
      name: "410 Gone",
      url: ROOT_CANONICAL_URL,
      description: "Legacy route removed.",
    },
    pageType: "gone",
  });
  res.writeHead(410, {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
  });
  res.end(html);
}

async function handleOuroborosRoutes({ method, pathname, req, res }) {
  if (String(pathname || "").startsWith("/api/")) {
    return false;
  }

  if (method !== "GET") {
    goneResponse(res, pathname);
    return true;
  }

  if (pathname === "/assets/ouroboros.css") {
    const css = await fs.readFile(path.join(__dirname, "web", "ouroboros.css"), "utf-8");
    textResponse(res, 200, css, "text/css; charset=utf-8");
    return true;
  }
  if (pathname === "/assets/ouroboros.js") {
    const js = await fs.readFile(path.join(__dirname, "web", "ouroboros.js"), "utf-8");
    textResponse(res, 200, js, "application/javascript; charset=utf-8");
    return true;
  }
  if (pathname === "/assets/social-card.svg") {
    textResponse(res, 200, buildSocialCardSvg(), "image/svg+xml; charset=utf-8");
    return true;
  }
  if (pathname === "/robots.txt") {
    textResponse(res, 200, buildRobots(CONFIG.siteUrl));
    return true;
  }
  if (pathname === "/sitemap.xml") {
    const analysisPaths = await fetchAnalysisPaths(5000);
    textResponse(res, 200, buildSitemap(CONFIG.siteUrl, analysisPaths), "application/xml; charset=utf-8");
    return true;
  }
  if (pathname === "/llms.txt") {
    textResponse(res, 200, buildLlmsTxt(CONFIG.siteUrl, CONFIG.mainSiteUrl));
    return true;
  }
  if (pathname === "/") {
    const reports = await fetchLatestReports(5);
    textResponse(res, 200, renderRootLandingPage(reports), "text/html; charset=utf-8");
    return true;
  }

  const normalized = normalizeAnalysisPath(pathname);
  if (normalized === "/analysis") {
    const reports = await fetchReportsForIndex(500);
    textResponse(res, 200, renderAnalysisIndexPage(reports), "text/html; charset=utf-8");
    return true;
  }
  if (normalized.startsWith("/analysis/")) {
    const slug = normalized.slice("/analysis/".length).trim().toLowerCase();
    const entry = await fetchReportBySlug(slug);
    if (!entry) {
      textResponse(res, 404, renderAnalysisNotFoundPage(slug), "text/html; charset=utf-8");
      return true;
    }
    const unlockSession = getUnlockSessionFromReq(req);
    if (!unlockSession && req?.headers?.cookie && CONFIG.sessionSecret) {
      res.setHeader("Set-Cookie", clearUnlockCookie());
    }
    textResponse(
      res,
      200,
      renderAnalysisDetailPage(entry, {
        unlocked: Boolean(unlockSession),
        unlockedAddress: unlockSession?.addr || null,
      }),
      "text/html; charset=utf-8",
    );
    return true;
  }

  goneResponse(res, pathname);
  return true;
}

function renderPage({ locale, section, content, leaderboard, king, ads, sourceStatus }) {
  const pagePath = section ? `/${section}` : "";
  const seo = buildPageSeo({
    baseUrl: CONFIG.siteUrl,
    locale,
    content,
    king,
    leaderboard,
    pagePath,
  });
  const canonical = seo.canonical;
  const langLinks = seo.hreflangs
    .map((row) => `<link rel="alternate" hreflang="${row.hreflang}" href="${row.href}${pagePath}">`)
    .join("\n");
  const tronscanOk = Boolean(sourceStatus?.tronscan?.ok);
  const trongridOk = Boolean(sourceStatus?.trongrid?.ok);
  const dualSourceLive = tronscanOk && trongridOk;
  const sourceClass = dualSourceLive ? "status-ok" : "status-warn";
  const sourceText = dualSourceLive ? content.sourceDualLive : content.sourceLimited;

  const initialState = {
    locale,
    section: section || "home",
    supportAddress: CONFIG.supportAddress,
    minAmount: CONFIG.minAmount,
    mainSiteUrl: CONFIG.mainSiteUrl,
    content,
    king,
    leaderboard,
    ads: ads.rows,
    sourceStatus,
  };
  const initialScriptJson = escapeHtml(JSON.stringify(initialState));

  const navLocales = LOCALES.map((lc) => {
    const active = lc === locale ? "active" : "";
    const href = `/${lc}${section ? `/${section}` : ""}`;
    return `<a class="locale-link ${active}" href="${href}">${escapeHtml(getContent(lc).languageLabel)}</a>`;
  }).join("");

  const sectionClass = section ? `section-${section}` : "section-home";
  return `<!doctype html>
<html lang="${locale}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(seo.title)}</title>
  <meta name="description" content="${escapeHtml(seo.description)}">
  <meta name="keywords" content="${escapeHtml(seo.keywords || "")}">
  <meta name="application-name" content="LeiMai Throne">
  <meta name="theme-color" content="#39ff14">
  <meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">
  <meta property="og:type" content="website">
  <meta property="og:locale" content="${escapeHtml(seo.ogLocale)}">
  <meta property="og:title" content="${escapeHtml(seo.title)}">
  <meta property="og:description" content="${escapeHtml(seo.description)}">
  <meta property="og:url" content="${escapeHtml(canonical)}">
  <meta property="og:image" content="${escapeHtml(seo.image)}">
  <meta property="twitter:card" content="summary_large_image">
  <meta property="twitter:title" content="${escapeHtml(seo.title)}">
  <meta property="twitter:description" content="${escapeHtml(seo.description)}">
  <meta property="twitter:image" content="${escapeHtml(seo.image)}">
  <link rel="canonical" href="${escapeHtml(canonical)}">
  ${langLinks}
  <script type="application/ld+json">${seo.jsonLd}</script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="/assets/styles.css">
</head>
<body class="${sectionClass}">
  <div class="bg-grid" aria-hidden="true"></div>
  <header class="topbar">
    <div class="brand">
      <div class="brand-title">LEIMAI THRONE</div>
      <div class="brand-sub">${escapeHtml(content.brandSub)}</div>
    </div>
    <div class="topbar-right">
      <nav class="locale-nav">${navLocales}</nav>
      <a class="btn topbar-bridge" href="${escapeHtml(CONFIG.mainSiteUrl)}?utm_source=throne&utm_medium=topbar&utm_campaign=support_bridge">${escapeHtml(content.ctaMain)}</a>
    </div>
  </header>

  <main class="layout">
    <section class="hero panel">
      <div class="hero-grid">
        <div>
          <div class="hero-tag">${escapeHtml(content.heroTag)}</div>
          <h1>${escapeHtml(content.heroHeadline)}</h1>
          <p>${escapeHtml(content.heroSub)}</p>
          <div class="cta-row">
            <a class="btn btn-main" href="#support">${escapeHtml(content.ctaSupport)}</a>
            <a class="btn" href="#declare">${escapeHtml(content.ctaClaim)}</a>
            <a class="btn btn-outline" href="${escapeHtml(CONFIG.mainSiteUrl)}?utm_source=throne&utm_medium=cta&utm_campaign=support_bridge">${escapeHtml(content.ctaMain)}</a>
          </div>
        </div>
        <aside class="hero-stream">
          <div class="stream-row">
            <span>${escapeHtml(content.sourceLabel)}</span>
            <strong class="${sourceClass}">${escapeHtml(sourceText)}</strong>
          </div>
          <div class="stream-row">
            <span>${escapeHtml(content.syncLabel)}</span>
            <strong id="lastRefresh">${escapeHtml(nowIso())}</strong>
          </div>
          <div class="stream-row">
            <span>${escapeHtml(content.refreshInLabel)}</span>
            <strong id="refreshCountdown">30s</strong>
          </div>
          <div class="stream-row">
            <span>${escapeHtml(content.minRankLabel)}</span>
            <strong>${formatMoney(CONFIG.minAmount)} USDT</strong>
          </div>
        </aside>
      </div>
      <div id="throneEvent" class="throne-event" aria-live="polite">${escapeHtml(content.liveSyncText)}</div>
    </section>

    <section class="panel king-panel">
      <h2>${escapeHtml(content.kingTitle)}</h2>
      <div id="kingBlock" class="king-block">
        ${
          king
            ? `<div class="king-amount">${formatMoney(king.amount_usdt)} <span>USDT</span></div>
               <div class="king-meta">${escapeHtml(content.walletLabel)}: ${escapeHtml(king.wallet_masked || "-")}</div>
               <div class="king-meta">${escapeHtml(content.timeLabel)}: ${escapeHtml(king.confirmed_at_utc || "-")}</div>
               <div class="king-meta">${escapeHtml(content.txLabel)}: ${escapeHtml(String(king.tx_hash || "-").slice(0, 20))}${String(king.tx_hash || "").length > 20 ? "..." : ""}</div>`
            : `<div class="king-empty">${escapeHtml(content.noKing)}</div>`
        }
      </div>
    </section>

    <section id="support" class="panel pay-panel">
      <h2>${escapeHtml(content.paymentTitle)}</h2>
      <div class="address-row">
        <code id="supportAddress">${escapeHtml(CONFIG.supportAddress)}</code>
        <button id="copyAddressBtn" class="btn">${escapeHtml(content.copyAddress)}</button>
      </div>
      <div class="qr-wrap">
        <img id="qrCode" alt="support address qr">
      </div>
      <div class="network-tags">
        <span>TRON(TRC20)</span>
        <span>USDT</span>
        <span>${escapeHtml(content.minRankLabel)} ${formatMoney(CONFIG.minAmount)} USDT</span>
      </div>
      <p class="muted">${escapeHtml(content.liveSyncText)}</p>
    </section>

    <section class="panel board-panel">
      <h2>${escapeHtml(content.leaderboardTitle)}</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>${escapeHtml(content.rankLabel)}</th>
              <th>${escapeHtml(content.walletLabel)}</th>
              <th>${escapeHtml(content.amountLabel)}</th>
              <th>${escapeHtml(content.timeLabel)}</th>
            </tr>
          </thead>
          <tbody id="leaderboardBody"></tbody>
        </table>
      </div>
    </section>

    <section id="declare" class="panel declare-panel">
      <h2>${escapeHtml(content.declarationTitle)}</h2>
      <form id="declarationForm" class="form-grid">
        <input type="text" name="tx_hash" placeholder="tx_hash" required>
        <input type="text" name="wallet" placeholder="wallet (optional)">
        <select name="lang">
          <option value="en">EN</option>
          <option value="zh-tw">ZH-TW</option>
          <option value="zh-cn">ZH-CN</option>
        </select>
        <select name="type">
          <option value="personal">personal</option>
          <option value="ad">ad</option>
        </select>
        <textarea name="content" placeholder="${escapeHtml(content.declarationPlaceholder)}" required></textarea>
        <button class="btn btn-main" type="submit">${escapeHtml(content.submitText)}</button>
      </form>
      <div id="declarationResult" class="inline-result"></div>
    </section>

    <section class="panel status-panel">
      <h2>${escapeHtml(content.statusTitle)}</h2>
      <div class="status-row">
        <input id="statusIdInput" type="text" placeholder="${escapeHtml(content.statusPlaceholder)}">
        <button id="statusCheckBtn" class="btn">${escapeHtml(content.checkStatusText)}</button>
      </div>
      <div id="statusResult" class="inline-result"></div>
    </section>

    <section class="panel ads-panel">
      <h2>${escapeHtml(content.adsTitle)}</h2>
      <ul id="adsList" class="ads-list"></ul>
    </section>

    <section class="panel policy-panel ${section === "rules" ? "spotlight" : ""}">
      <h2>${escapeHtml(content.policyTitle)}</h2>
      <ul class="policy-list">
        <li>${escapeHtml(content.policy1)}</li>
        <li>${escapeHtml(content.policy2)}</li>
        <li>${escapeHtml(content.policy3)}</li>
      </ul>
    </section>

    <section class="panel faq-panel ${section === "faq" ? "spotlight" : ""}">
      <h2>${escapeHtml(content.faqTitle)}</h2>
      <dl class="faq-list">
        <dt>${escapeHtml(content.faq1q)}</dt>
        <dd>${escapeHtml(content.faq1a)}</dd>
        <dt>${escapeHtml(content.faq2q)}</dt>
        <dd>${escapeHtml(content.faq2a)}</dd>
        <dt>${escapeHtml(content.faq3q)}</dt>
        <dd>${escapeHtml(content.faq3a)}</dd>
      </dl>
    </section>
  </main>

  <footer class="footer">
    <p>${escapeHtml(content.footer)}</p>
  </footer>

  <script id="initial-data" type="application/json">${initialScriptJson}</script>
  <script src="/assets/app.js"></script>
</body>
</html>`;
}

function declarationStatusPayload(content, status, note) {
  if (status === "approved") return { label: content.approvedText, note: note || "" };
  if (status === "rejected") return { label: content.rejectedText, note: note || "" };
  return { label: content.pendingText, note: note || "" };
}

export async function handleRequest(req, res) {
  try {
    const reqUrl = new URL(req.url || "/", `http://${req.headers.host || `localhost:${CONFIG.port}`}`);
    const { pathname, searchParams } = reqUrl;
    const method = (req.method || "GET").toUpperCase();
    purgeExpiredChallenges();
    const routed = await handleOuroborosRoutes({ method, pathname, req, res });
    if (routed) return;

    if (method === "POST" && pathname === "/api/v1/auth/wallet/challenge") {
      if (!CONFIG.sessionSecret) {
        return jsonResponse(res, 500, { ok: false, error: "unlock_not_configured" });
      }
      if (!checkRateLimit(req, "wallet_challenge", CONFIG.rateLimitPerMinute)) {
        return jsonResponse(res, 429, { ok: false, error: "rate_limited" });
      }
      const body = await parseJsonBody(req).catch(() => ({}));
      const slug = normalizeReportSlug(body?.slug || "analysis");
      const challenge = generateWalletChallenge(slug);
      return jsonResponse(res, 200, {
        ok: true,
        nonce: challenge.nonce,
        message: challenge.message,
        expires_at_utc: challenge.expiresAtUtc,
      });
    }

    if (method === "POST" && pathname === "/api/v1/auth/wallet/verify") {
      if (!CONFIG.sessionSecret) {
        return jsonResponse(res, 500, { ok: false, error: "unlock_not_configured" });
      }
      if (!checkRateLimit(req, "wallet_verify", CONFIG.rateLimitPerMinute)) {
        return jsonResponse(res, 429, { ok: false, error: "rate_limited" });
      }
      const body = await parseJsonBody(req).catch(() => ({}));
      const address = toCanonicalAddress(body?.address || "");
      const signature = String(body?.signature || "").trim();
      const message = String(body?.message || "").trim();
      const slug = normalizeReportSlug(body?.slug || "");
      if (!address || !signature || !message || !slug) {
        return jsonResponse(res, 400, { ok: false, error: "invalid_payload" });
      }

      const nonce = extractNonceFromMessage(message);
      if (!nonce) {
        return jsonResponse(res, 400, { ok: false, error: "invalid_challenge_message" });
      }
      const challenge = consumeWalletChallenge(nonce);
      if (!challenge) {
        return jsonResponse(res, 401, { ok: false, error: "challenge_expired_or_reused" });
      }
      if (challenge.message !== message || challenge.slug !== slug) {
        return jsonResponse(res, 401, { ok: false, error: "challenge_mismatch" });
      }

      let recoveredAddress = null;
      try {
        recoveredAddress = toCanonicalAddress(verifyMessage(message, signature));
      } catch {
        return jsonResponse(res, 401, { ok: false, error: "invalid_signature" });
      }
      if (!recoveredAddress || recoveredAddress !== address) {
        return jsonResponse(res, 401, { ok: false, error: "signature_address_mismatch" });
      }

      const issuedAtSec = Math.floor(nowMs() / 1000);
      const expireSec = issuedAtSec + Math.max(60, Math.floor(CONFIG.unlockTtlSec));
      const token = signUnlockToken({
        addr: address,
        iat: issuedAtSec,
        exp: expireSec,
        scope: "analysis:*",
      });
      if (!token) {
        return jsonResponse(res, 500, { ok: false, error: "session_sign_failed" });
      }
      res.setHeader("Set-Cookie", buildUnlockCookie(token));
      await logUserAccess({ walletAddress: address, slug }).catch(() => false);

      return jsonResponse(res, 200, {
        ok: true,
        address,
        unlock_expires_at_utc: new Date(expireSec * 1000).toISOString(),
      });
    }

    if (method === "GET" && pathname === "/assets/styles.css") {
      const css = await fs.readFile(path.join(__dirname, "web", "styles.css"), "utf-8");
      return textResponse(res, 200, css, "text/css; charset=utf-8");
    }
    if (method === "GET" && pathname === "/assets/app.js") {
      const js = await fs.readFile(path.join(__dirname, "web", "app.js"), "utf-8");
      return textResponse(res, 200, js, "application/javascript; charset=utf-8");
    }
    if (method === "GET" && pathname === "/assets/social-card.svg") {
      return textResponse(res, 200, buildSocialCardSvg(), "image/svg+xml; charset=utf-8");
    }

    if (method === "GET" && (pathname === "/preview" || pathname === "/preview/" || pathname === "/preview/index.html")) {
      return servePreviewFile(res, "index.html");
    }
    if (method === "GET" && pathname === "/preview/assets/preview.css") {
      return servePreviewFile(res, "preview.css", "text/css; charset=utf-8");
    }
    const previewPageMatch = pathname.match(/^\/preview\/([abc])\/?$/i);
    if (method === "GET" && previewPageMatch) {
      const pageKey = String(previewPageMatch[1]).toLowerCase();
      return servePreviewFile(res, `${pageKey}.html`);
    }

    if (method === "GET" && pathname === "/robots.txt") {
      return textResponse(res, 200, buildRobots(CONFIG.siteUrl));
    }
    if (method === "GET" && pathname === "/sitemap.xml") {
      return textResponse(res, 200, buildSitemap(CONFIG.siteUrl), "application/xml; charset=utf-8");
    }
    if (method === "GET" && pathname === "/llms.txt") {
      return textResponse(res, 200, buildLlmsTxt(CONFIG.siteUrl, CONFIG.mainSiteUrl));
    }

    const pageMatch = pathname.match(/^\/(?:(en|zh-tw|zh-cn))(?:\/(faq|rules))?\/?$/i);
    if (method === "GET" && (pathname === "/" || pageMatch)) {
      const locale = pageMatch?.[1] ? resolveLocale(pageMatch[1]) : "en";
      const section = pageMatch?.[2] ? String(pageMatch[2]).toLowerCase() : "";
      const content = getContent(locale);

      const { chainState, appState } = await readStates();
      const board = buildLeaderboard(chainState, appState, { minAmount: CONFIG.minAmount, limit: 50 });
      const ads = extractAds(appState, { limit: 3 });

      const html = renderPage({
        locale,
        section,
        content,
        leaderboard: board.rows,
        king: board.king,
        ads,
        sourceStatus: chainState.source_status || {},
      });
      return textResponse(res, 200, html, "text/html; charset=utf-8");
    }

    if (method === "GET" && pathname === "/api/v1/leaderboard") {
      const locale = resolveLocale(searchParams.get("lang") || "en");
      const { chainState, appState } = await readStates();
      const board = buildLeaderboard(chainState, appState, { minAmount: CONFIG.minAmount, limit: 100 });
      return jsonResponse(res, 200, {
        ok: true,
        locale,
        generated_at_utc: nowIso(),
        king: board.king,
        rows: board.rows,
      });
    }

    if (method === "GET" && pathname === "/api/v1/king") {
      const { chainState, appState } = await readStates();
      const board = buildLeaderboard(chainState, appState, { minAmount: CONFIG.minAmount, limit: 1 });
      return jsonResponse(res, 200, { ok: true, king: board.king, generated_at_utc: nowIso() });
    }

    if (method === "GET" && pathname === "/api/v1/ads/slots") {
      const { appState } = await readStates();
      const slots = extractAds(appState, { limit: 3 });
      return jsonResponse(res, 200, { ok: true, ...slots, generated_at_utc: nowIso() });
    }

    if (method === "GET" && pathname === "/api/v1/health") {
      const { chainState, appState } = await readStates();
      const board = buildLeaderboard(chainState, appState, { minAmount: CONFIG.minAmount, limit: 100 });
      const sourceStatus = chainState.source_status || {};
      return jsonResponse(res, 200, {
        ok: true,
        version: "support-v1",
        generated_at_utc: nowIso(),
        source_status: sourceStatus,
        counts: summarizeCounts(chainState, appState, board),
      });
    }

    if (method === "GET" && pathname === "/api/v1/knowledge") {
      const locale = resolveLocale(searchParams.get("lang") || "en");
      const { chainState, appState } = await readStates();
      const board = buildLeaderboard(chainState, appState, { minAmount: CONFIG.minAmount, limit: 20 });
      const ads = extractAds(appState, { limit: 3 });
      return jsonResponse(res, 200, {
        ok: true,
        payload: buildKnowledgePayload(locale, board.rows, board.king, ads),
      });
    }

    if ((method === "POST" || method === "GET") && pathname === "/api/internal/poll-chain") {
      if (!isCronAuthorized(req)) {
        return jsonResponse(res, 401, { ok: false, error: "unauthorized_cron" });
      }
      const summary = await pollChainNow();
      return jsonResponse(res, 200, { ok: true, ...summary });
    }

    const declarationStatusMatch = pathname.match(/^\/api\/v1\/declarations\/([A-Za-z0-9_-]+)\/status$/);
    if (method === "GET" && declarationStatusMatch) {
      const id = declarationStatusMatch[1];
      const locale = resolveLocale(searchParams.get("lang") || "en");
      const content = getContent(locale);
      const { appState } = await readStates();
      const row = (appState.declarations || []).find((item) => item?.id === id);
      if (!row) {
        return jsonResponse(res, 404, { ok: false, error: "declaration_not_found" });
      }
      const statusInfo = declarationStatusPayload(content, row.status, row.review_note);
      return jsonResponse(res, 200, {
        ok: true,
        id: row.id,
        status: row.status,
        status_label: statusInfo.label,
        note: statusInfo.note,
        updated_at_utc: row.updated_at_utc,
      });
    }

    if (method === "POST" && pathname === "/api/v1/declarations") {
      if (!checkRateLimit(req, "declare", CONFIG.rateLimitPerMinute)) {
        return jsonResponse(res, 429, { ok: false, error: "rate_limited" });
      }

      const payload = await parseJsonBody(req);
      const parsed = validateDeclarationPayload(payload, CONFIG);
      if (!parsed.ok) {
        return jsonResponse(res, 400, { ok: false, error: parsed.error });
      }

      const { chainState, appState } = await readStates();
      const txHash = normalizeTxHash(parsed.data.tx_hash);
      const txReceipt = (chainState.tx_receipts || []).find((row) => normalizeTxHash(row.tx_hash) === txHash && row.status === "verified");
      if (!txReceipt) {
        return jsonResponse(res, 404, { ok: false, error: "tx_not_verified" });
      }
      if (Number(txReceipt.amount || 0) < CONFIG.minAmount) {
        return jsonResponse(res, 400, { ok: false, error: "amount_below_minimum" });
      }

      const postedWallet = normalizeWallet(parsed.data.wallet);
      if (postedWallet && postedWallet !== txReceipt.from_addr) {
        return jsonResponse(res, 400, { ok: false, error: "wallet_mismatch_with_tx" });
      }

      const existing = (appState.declarations || []).find((row) => normalizeTxHash(row.tx_hash) === txHash && row.status !== "rejected");
      if (existing) {
        return jsonResponse(res, 409, {
          ok: false,
          error: "declaration_already_exists",
          declaration_id: existing.id,
          status: existing.status,
        });
      }

      const moderation = moderateDeclaration(parsed.data, appState);
      if (!moderation.ok) {
        return jsonResponse(res, 400, { ok: false, error: moderation.error });
      }

      const row = createDeclarationRecord(parsed.data, txReceipt);
      appState.declarations.push(row);
      appendEvent(appState, "declaration_submitted", { declaration_id: row.id, tx_hash: row.tx_hash, type: row.type });
      await saveAppState(appState);

      return jsonResponse(res, 202, { ok: true, declaration_id: row.id, status: row.status });
    }

    if (method === "GET" && pathname === "/api/v1/admin/moderation/queue") {
      if (!requireAdmin(req, res)) return;
      const { chainState, appState } = await readStates();
      const queue = (appState.declarations || [])
        .filter((row) => row?.status === "pending")
        .map((row) => {
          const tx = (chainState.tx_receipts || []).find((item) => normalizeTxHash(item.tx_hash) === normalizeTxHash(row.tx_hash));
          return { ...row, tx_amount_usdt: tx?.amount || null, tx_confirmed_at_utc: tx?.confirmed_at_utc || null };
        })
        .sort((a, b) => Date.parse(a.created_at_utc || "") - Date.parse(b.created_at_utc || ""));
      return jsonResponse(res, 200, { ok: true, queue, total: queue.length });
    }

    const approveMatch = pathname.match(/^\/api\/v1\/admin\/declarations\/([A-Za-z0-9_-]+)\/approve$/);
    if (method === "POST" && approveMatch) {
      if (!requireAdmin(req, res)) return;
      const id = approveMatch[1];
      const body = await parseJsonBody(req).catch(() => ({}));
      const note = String(body?.note || "").trim();
      const { appState } = await readStates();
      const row = (appState.declarations || []).find((item) => item?.id === id);
      if (!row) return jsonResponse(res, 404, { ok: false, error: "declaration_not_found" });
      row.status = "approved";
      row.review_note = note;
      row.updated_at_utc = nowIso();
      appendEvent(appState, "declaration_approved", { declaration_id: row.id, tx_hash: row.tx_hash });
      await saveAppState(appState);
      return jsonResponse(res, 200, { ok: true, id: row.id, status: row.status });
    }

    const rejectMatch = pathname.match(/^\/api\/v1\/admin\/declarations\/([A-Za-z0-9_-]+)\/reject$/);
    if (method === "POST" && rejectMatch) {
      if (!requireAdmin(req, res)) return;
      const id = rejectMatch[1];
      const body = await parseJsonBody(req).catch(() => ({}));
      const note = String(body?.note || "").trim();
      const { appState } = await readStates();
      const row = (appState.declarations || []).find((item) => item?.id === id);
      if (!row) return jsonResponse(res, 404, { ok: false, error: "declaration_not_found" });
      row.status = "rejected";
      row.review_note = note;
      row.updated_at_utc = nowIso();
      appendEvent(appState, "declaration_rejected", { declaration_id: row.id, tx_hash: row.tx_hash });
      await saveAppState(appState);
      return jsonResponse(res, 200, { ok: true, id: row.id, status: row.status });
    }

    if (method === "POST" && pathname === "/api/v1/admin/blacklist") {
      if (!requireAdmin(req, res)) return;
      const body = await parseJsonBody(req).catch(() => ({}));
      const addWallets = uniqueStrings(Array.isArray(body?.wallets) ? body.wallets : []);
      const addKeywords = uniqueStrings(Array.isArray(body?.keywords) ? body.keywords : []);
      const { appState } = await readStates();
      const currentWallets = Array.isArray(appState?.blacklist?.wallets) ? appState.blacklist.wallets : [];
      const currentKeywords = Array.isArray(appState?.blacklist?.keywords) ? appState.blacklist.keywords : [];
      appState.blacklist = {
        wallets: uniqueStrings([...currentWallets, ...addWallets]),
        keywords: uniqueStrings([...currentKeywords, ...addKeywords]),
      };
      appendEvent(appState, "blacklist_updated", { wallets_added: addWallets.length, keywords_added: addKeywords.length });
      await saveAppState(appState);
      return jsonResponse(res, 200, { ok: true, blacklist: appState.blacklist });
    }

    if (method === "POST" && pathname === "/api/v1/admin/fetch-now") {
      if (!requireAdmin(req, res)) return;
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
      const merged = mergeTransfers(tronscan.transfers, trongrid.transfers).filter((row) => Number(row.amount || 0) >= CONFIG.minAmount);
      return jsonResponse(res, 200, { ok: true, tronscan, trongrid, merged_count: merged.length });
    }

    if (CONFIG.exposeDebug && method === "GET" && pathname === "/api/v1/debug/state") {
      const states = await readStates();
      return jsonResponse(res, 200, { ok: true, ...states });
    }

    return jsonResponse(res, 404, { ok: false, error: "not_found" });
  } catch (error) {
    return jsonResponse(res, 500, { ok: false, error: "internal_error", detail: String(error?.message || error) });
  }
}

export function createServer() {
  return http.createServer((req, res) => {
    void handleRequest(req, res);
  });
}

const isDirectRun = process.argv[1] && path.resolve(process.argv[1]) === __filename;
if (isDirectRun) {
  const server = createServer();
  server.listen(CONFIG.port, () => {
    // eslint-disable-next-line no-console
    console.log(`[support] server listening on http://localhost:${CONFIG.port}`);
    // eslint-disable-next-line no-console
    console.log(`[support] canonical site url: ${CONFIG.siteUrl}`);
  });
}

