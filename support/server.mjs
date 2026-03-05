import http from "node:http";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { createClient } from "@supabase/supabase-js";
import { getAddress, verifyMessage } from "ethers";
import { marked } from "marked";
import sanitizeHtml from "sanitize-html";

import { fetchTronscan, fetchTrongrid, mergeTransfers } from "./lib/chain-sources.mjs";
import { getContent, listLocales, resolveLocale } from "./lib/content.mjs";
import { resolvePreferredLocale } from "./lib/geo.mjs";
import { buildLeaderboard, extractAds, summarizeCounts } from "./lib/leaderboard.mjs";
import { getOuroborosCopy, normalizeOuroborosLocale } from "./lib/messaging.mjs";
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
import {
  buildLlmsTxt,
  buildPageSeo,
  buildRobots,
  buildSitemap,
  buildSitemapDocument,
  buildSitemapIndex,
} from "./lib/seo.mjs";
import {
  baseEntropyFromSeed,
  buildFallbackGenesis,
  buildRulesSummary,
  buildSemanticOrbit,
  clamp,
  clamp01,
  deriveSpaceStage,
  normalizeCoordinatePair,
  seedHashFromCell,
  toVectorLiteral,
} from "./lib/worldforge.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const LOCALES = listLocales();
const PREVIEW_DIR = path.join(__dirname, "preview");
const IS_VERCEL_RUNTIME = String(process.env.VERCEL || "").toLowerCase() === "1";
const ROOT_CANONICAL_URL = "https://leimai.io/";
const LEGACY_HOST_REDIRECT_MAP = new Map([
  ["leimaitech.com", "leimai.io"],
  ["www.leimaitech.com", "leimai.io"],
  ["support.leimaitech.com", "support.leimai.io"],
]);
const DEFAULT_REPORT_LOCALE = "en";
const REPORT_SELECT_FIELDS = "*";
const REPORT_PREVIEW_RATIO = 0.2;
const PAYWALL_SELECTOR = ".paywall-locked-content";
const UNLOCK_COOKIE_NAME = "leimai_unlock";
const PAYMENT_PLAN_CODES = new Set(["sovereign", "elite"]);
const PAYMENT_RAIL_CODES = new Set(["trc20_usdt", "eth_l1_erc20", "l2_usdc"]);
const REPO_ROOT = path.resolve(__dirname, "..");
const GROWTH_SCOREBOARD_PATH = path.join(REPO_ROOT, "logs", "growth_scoreboard.json");
const GROWTH_ACTIONS_PATH = path.join(REPO_ROOT, "logs", "agent_actions.jsonl");
const GROWTH_OVERRIDES_PATH = path.join(__dirname, "web", "generated", "growth_overrides.json");
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
  mainSiteUrl: (process.env.SUPPORT_MAIN_SITE_URL || "https://leimai.io").replace(/\/+$/, ""),
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
  paymentInvoiceTtlSec: numberEnv("SUPPORT_PAYMENT_INVOICE_TTL_SEC", 1200),
  planSovereignUsdt: numberEnv("SUPPORT_PLAN_SOVEREIGN_USDT", 199),
  planEliteUsdt: numberEnv("SUPPORT_PLAN_ELITE_USDT", 499),
  supportEthL1Erc20Recipient: process.env.ETH_L1_ERC20_RECIPIENT || "0xc8Fdb8A3D531C47d4d3C4C252c09A26176323809",
  supportL2Network: process.env.L2_NETWORK || "arbitrum",
  supportL2UsdcRecipient: process.env.L2_USDC_RECIPIENT || "0x1E90d2675915F4510eEEb6Bb9eecEECC2E320179",
  cookieSecure: boolEnv("SUPPORT_COOKIE_SECURE", IS_VERCEL_RUNTIME),
  exposeDebug: boolEnv("SUPPORT_EXPOSE_DEBUG", false),
  mapboxPublicToken: process.env.MAPBOX_PUBLIC_TOKEN || process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "",
  openaiApiKey: process.env.OPENAI_API_KEY || "",
  openaiModel: process.env.OPENAI_MODEL || "gpt-4.1-mini",
  openaiEmbeddingModel: process.env.OPENAI_EMBEDDING_MODEL || "text-embedding-3-small",
  worldCellDecimals: Math.max(1, Math.min(5, numberEnv("WORLD_CELL_DECIMALS", 3))),
  worldDecayHours: Math.max(1, numberEnv("WORLD_DECAY_HOURS", 24)),
  worldCanonizeHours: Math.max(1, numberEnv("WORLD_CANONIZE_HOURS", 24)),
  worldEntropyWarn: clamp(numberEnv("WORLD_ENTROPY_WARN", 0.8), 0.1, 1),
  worldEntropyMutate: clamp(numberEnv("WORLD_ENTROPY_MUTATE", 0.9), 0.1, 1),
  spaceUnlockMoon: Math.max(1, numberEnv("SPACE_UNLOCK_MOON", 500)),
  spaceUnlockMars: Math.max(2, numberEnv("SPACE_UNLOCK_MARS", 2000)),
  spaceZoomGate: clamp(numberEnv("SPACE_ZOOM_GATE", 3), 1.5, 10),
  canonizationPriceUsdt: Math.max(1, numberEnv("WORLD_CANON_PRICE_USDT", 49)),
  canonizationRail: normalizePaymentRail(process.env.WORLD_CANON_PAYMENT_RAIL || "l2_usdc"),
};

const WORLD_ENTITY_TABLE = "world_entities";
const WORLD_META_TABLE = "world_meta";
const WORLD_META_KEY_GLOBAL_DEV = "global_development_count";
const WORLDFORGE_EARTH_STYLE = "mapbox://styles/mapbox/satellite-streets-v12";
const WORLDFORGE_STARS_STYLE = "mapbox://styles/mapbox/dark-v11";

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

function resolveOuroborosLocale(req) {
  return normalizeOuroborosLocale(resolvePreferredLocale(req));
}

function normalizeHostHeader(rawHost) {
  const host = String(rawHost || "")
    .trim()
    .toLowerCase()
    .split(",")[0]
    .trim();
  return host.replace(/:\d+$/, "");
}

function buildLegacyRedirectUrl(reqUrl, host) {
  const targetHost = LEGACY_HOST_REDIRECT_MAP.get(host);
  if (!targetHost) return null;
  const pathname = reqUrl?.pathname || "/";
  const search = reqUrl?.search || "";
  return `https://${targetHost}${pathname}${search}`;
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
    "Path=/",
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
    "Path=/",
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

function shortRef(value, head = 10, tail = 8) {
  const text = String(value || "").trim();
  if (!text) return "-";
  if (text.length <= head + tail + 3) return text;
  return `${text.slice(0, head)}...${text.slice(-tail)}`;
}

async function readJsonFileSafe(filePath, fallback = {}) {
  try {
    const raw = await fs.readFile(filePath, "utf-8");
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") return parsed;
    return fallback;
  } catch {
    return fallback;
  }
}

async function readJsonLinesSafe(filePath, limit = 50) {
  try {
    const raw = await fs.readFile(filePath, "utf-8");
    const rows = String(raw)
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        try {
          return JSON.parse(line);
        } catch {
          return null;
        }
      })
      .filter((row) => row && typeof row === "object");
    return rows.slice(-Math.max(1, Number(limit) || 50)).reverse();
  } catch {
    return [];
  }
}

function normalizeCopyOverrides(raw) {
  if (!raw || typeof raw !== "object") return {};
  const payload = raw.copy_overrides;
  if (!payload || typeof payload !== "object") return {};
  const out = {};
  for (const [locale, value] of Object.entries(payload)) {
    if (!value || typeof value !== "object") continue;
    out[normalizeOuroborosLocale(locale)] = value;
  }
  return out;
}

function resolveOuroborosCopy(locale, overrides = {}) {
  const safeLocale = normalizeOuroborosLocale(locale);
  const base = getOuroborosCopy(safeLocale) || getOuroborosCopy("en");
  const patch = overrides[safeLocale] && typeof overrides[safeLocale] === "object" ? overrides[safeLocale] : {};
  return { ...base, ...patch };
}

async function readGrowthOverrides() {
  const payload = await readJsonFileSafe(GROWTH_OVERRIDES_PATH, {});
  return normalizeCopyOverrides(payload);
}

function buildSnippet(text, targetWords) {
  const words = String(text || "")
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .filter(Boolean);
  if (!words.length) return "";
  return words.slice(0, Math.max(1, targetWords)).join(" ");
}

function extractEvidenceBoundary(bodyMd, locale = "en") {
  const text = String(bodyMd || "");
  const isZh = normalizeOuroborosLocale(locale) === "zh-tw";
  const evidencePattern = isZh
    ? /(?:^|\n)#{1,6}\s*證據\s*\n([\s\S]*?)(?=\n#{1,6}\s|\s*$)/i
    : /(?:^|\n)#{1,6}\s*Evidence\s*\n([\s\S]*?)(?=\n#{1,6}\s|\s*$)/i;
  const riskPattern = isZh
    ? /(?:^|\n)#{1,6}\s*風險邊界\s*\n([\s\S]*?)(?=\n#{1,6}\s|\s*$)/i
    : /(?:^|\n)#{1,6}\s*Risk Boundary\s*\n([\s\S]*?)(?=\n#{1,6}\s|\s*$)/i;
  const evidence = (text.match(evidencePattern)?.[1] || "").replace(/\s+/g, " ").trim();
  const boundary = (text.match(riskPattern)?.[1] || "").replace(/\s+/g, " ").trim();
  return {
    evidence: evidence || buildSummary(text, 180),
    risk_boundary: boundary || extractBoundaryText(text, locale, ""),
  };
}

function buildAiCitationItem(report) {
  const canonical = `${ROOT_CANONICAL_URL}analysis/${encodeURIComponent(report.slug)}`;
  const summary = buildSummary(report.body_md, 360);
  const { evidence, risk_boundary } = extractEvidenceBoundary(report.body_md, report.locale);
  const uniqueEntity = String(report.unique_entity || "LeiMai Liquidity Friction");
  return {
    slug: report.slug,
    locale: normalizeOuroborosLocale(report.locale),
    title: String(report.title || ""),
    canonical_url: canonical,
    updated_at: report.updated_at || report.created_at || nowIso(),
    unique_entity: uniqueEntity,
    snippets: {
      words_40: buildSnippet(summary, 40),
      words_80: buildSnippet(summary, 80),
      words_160: buildSnippet(summary, 160),
    },
    evidence,
    risk_boundary,
    citation_policy:
      "Cite canonical_url, include unique_entity, and preserve risk_boundary statement when summarizing.",
  };
}

function buildAiCitationFeedPayload(baseUrl, reports = []) {
  const root = String(baseUrl || ROOT_CANONICAL_URL).replace(/\/+$/, "");
  const rows = (Array.isArray(reports) ? reports : []).filter((row) => row && row.slug);
  const locales = [...new Set(rows.map((row) => normalizeOuroborosLocale(row.locale)).filter(Boolean))];
  return {
    version: "1.0",
    generated_at_utc: nowIso(),
    site: root || ROOT_CANONICAL_URL.replace(/\/+$/, ""),
    canonical_url: ROOT_CANONICAL_URL,
    locales_supported: locales.length ? locales : ["en", "zh-tw", "es", "ja"],
    citation_guidelines: [
      "Prefer canonical_url over mirrored paths.",
      "Retain unique_entity verbatim: LeiMai Liquidity Friction.",
      "Include risk boundary language in generated summaries.",
    ],
    items: rows.slice(0, 60).map(buildAiCitationItem),
  };
}

function buildStaticSitemapPaths() {
  return [
    "/",
    "/analysis/",
    "/vault",
    "/forge",
    "/game",
    "/en/",
    "/zh-tw/",
    "/es/",
    "/ja/",
    "/en/analysis/",
    "/zh-tw/analysis/",
    "/es/analysis/",
    "/ja/analysis/",
    "/en/vault",
    "/zh-tw/vault",
    "/es/vault",
    "/ja/vault",
    "/en/forge",
    "/zh-tw/forge",
    "/es/forge",
    "/ja/forge",
    "/en/game",
    "/zh-tw/game",
    "/es/game",
    "/ja/game",
  ];
}

function toLocaleTag(locale) {
  const raw = String(locale || "").trim().toLowerCase();
  if (raw === "zh-tw") return "ZH-TW";
  if (raw === "es") return "ES";
  if (raw === "ja") return "JA";
  return "EN";
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
  <text x="72" y="500" fill="#39ff14" font-size="22" font-family="Consolas, monospace">support.leimai.io</text>
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

function normalizePlanCode(raw) {
  const plan = String(raw || "sovereign").trim().toLowerCase();
  return PAYMENT_PLAN_CODES.has(plan) ? plan : "sovereign";
}

function resolvePlanAmountUsdt(planCode) {
  const plan = normalizePlanCode(planCode);
  if (plan === "elite") return Number(CONFIG.planEliteUsdt || 499);
  return Number(CONFIG.planSovereignUsdt || 199);
}

function normalizePaymentRail(raw) {
  const rail = String(raw || "trc20_usdt").trim().toLowerCase();
  return PAYMENT_RAIL_CODES.has(rail) ? rail : "trc20_usdt";
}

function resolvePaymentRecipient(rail) {
  const normalized = normalizePaymentRail(rail);
  if (normalized === "eth_l1_erc20") {
    return String(CONFIG.supportEthL1Erc20Recipient || "").trim() || CONFIG.supportAddress;
  }
  if (normalized === "l2_usdc") {
    return String(CONFIG.supportL2UsdcRecipient || "").trim() || CONFIG.supportAddress;
  }
  return CONFIG.supportAddress;
}

function generateInvoiceId() {
  const ts = Math.floor(nowMs() / 1000).toString(36);
  const rand = randomBytes(4).toString("hex");
  return `inv_${ts}_${rand}`;
}

function generatePaymentNonce() {
  return randomBytes(16).toString("hex");
}

function buildPaymentInvoiceRecord({ walletAddress, slug, planCode, paymentRail }) {
  const normalizedSlug = normalizeReportSlug(slug || "vault") || "vault";
  const normalizedPlan = normalizePlanCode(planCode);
  const normalizedRail = normalizePaymentRail(paymentRail);
  const ttlSec = Math.max(300, Math.floor(CONFIG.paymentInvoiceTtlSec || 1200));
  const expiresAt = new Date(nowMs() + ttlSec * 1000);
  return {
    invoice_id: generateInvoiceId(),
    wallet_address: walletAddress || null,
    slug: normalizedSlug,
    plan_code: normalizedPlan,
    amount_usdt: resolvePlanAmountUsdt(normalizedPlan),
    pay_to_address: resolvePaymentRecipient(normalizedRail),
    nonce: generatePaymentNonce(),
    status: "pending",
    expires_at_utc: expiresAt.toISOString(),
    meta: {
      source: "phase4_invoice_preflight",
      created_via: "/api/v1/payment/create",
      payment_rail: normalizedRail,
      l2_network: String(CONFIG.supportL2Network || "arbitrum").toLowerCase(),
    },
  };
}

async function recordPaymentInvoice(invoice) {
  const client = getSupabaseServiceClient();
  if (!client) {
    return { ok: false, error: "payment_storage_unavailable" };
  }
  const { error } = await client.from("payment_invoices").insert(invoice);
  if (error) {
    return { ok: false, error: `payment_insert_failed:${error.message || error.code || "unknown"}` };
  }
  return { ok: true };
}

async function fetchPaymentInvoiceStatus({ invoiceId, sessionAddress }) {
  const client = getSupabaseServiceClient();
  if (!client) {
    return { ok: false, error: "payment_storage_unavailable" };
  }
  const cleanedId = String(invoiceId || "").trim();
  if (!cleanedId) {
    return { ok: false, error: "invalid_invoice_id" };
  }

  const { data, error } = await client
    .from("payment_invoices")
    .select("invoice_id,status,wallet_address,plan_code,amount_usdt,pay_to_address,nonce,expires_at_utc,meta,updated_at")
    .eq("invoice_id", cleanedId)
    .limit(1)
    .maybeSingle();
  if (error) {
    return { ok: false, error: `payment_status_read_failed:${error.message || error.code || "unknown"}` };
  }
  if (!data || typeof data !== "object") {
    return { ok: false, error: "invoice_not_found" };
  }

  const walletAddress = toCanonicalAddress(data.wallet_address || "");
  const canonicalSession = toCanonicalAddress(sessionAddress || "");
  if (!walletAddress || !canonicalSession || walletAddress !== canonicalSession) {
    return { ok: false, error: "wallet_session_mismatch" };
  }

  const meta = data.meta && typeof data.meta === "object" ? data.meta : {};
  return {
    ok: true,
    invoice: {
      invoice_id: String(data.invoice_id || ""),
      status: String(data.status || "pending"),
      wallet_address: walletAddress,
      plan_code: normalizePlanCode(data.plan_code || "sovereign"),
      amount_usdt: Number(data.amount_usdt || 0),
      pay_to_address: String(data.pay_to_address || ""),
      nonce: String(data.nonce || ""),
      expires_at_utc: String(data.expires_at_utc || ""),
      updated_at_utc: String(data.updated_at || ""),
      paid_at_utc: String(meta.paid_at_utc || ""),
      paid_tx_hash: String(meta.paid_tx_hash || ""),
      payment_rail: String(meta.payment_rail || "trc20_usdt"),
      l2_network: String(meta.l2_network || ""),
    },
  };
}

function normalizeGenesisRules(candidate, fallback) {
  const base = fallback && typeof fallback === "object" ? fallback : {};
  const src = candidate && typeof candidate === "object" ? candidate : {};
  const visualTheme = String(src.visual_theme || base.visual_theme || "").trim();
  const narrative = String(src.narrative || base.narrative || "").trim();
  const physicalRule = String(src.physical_rule || base.physical_rule || "").trim();
  const devTask = String(src.dev_task || base.dev_task || "").trim();
  const heavenlyLawsRaw = Array.isArray(src.heavenly_laws) ? src.heavenly_laws : base.heavenly_laws;
  const heavenlyLaws = (Array.isArray(heavenlyLawsRaw) ? heavenlyLawsRaw : [])
    .map((row) => String(row || "").trim())
    .filter(Boolean)
    .slice(0, 4);
  return {
    visual_theme: visualTheme || String(base.visual_theme || "").trim(),
    narrative: narrative || String(base.narrative || "").trim(),
    physical_rule: physicalRule || String(base.physical_rule || "").trim(),
    dev_task: devTask || String(base.dev_task || "").trim(),
    heavenly_laws: heavenlyLaws.length ? heavenlyLaws : (Array.isArray(base.heavenly_laws) ? base.heavenly_laws : []),
    summary: String(src.summary || base.summary || "").trim(),
  };
}

async function callOpenAiJson({ systemPrompt, userPrompt, temperature = 0.7, maxTokens = 700 }) {
  if (!CONFIG.openaiApiKey) return null;
  const payload = {
    model: CONFIG.openaiModel,
    response_format: { type: "json_object" },
    temperature: clamp(temperature, 0, 1.2),
    max_tokens: Math.max(120, Math.floor(maxTokens)),
    messages: [
      { role: "system", content: String(systemPrompt || "") },
      { role: "user", content: String(userPrompt || "") },
    ],
  };
  try {
    const resp = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${CONFIG.openaiApiKey}`,
      },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) return null;
    const data = await resp.json().catch(() => null);
    const content = data?.choices?.[0]?.message?.content;
    if (!content) return null;
    const parsed = JSON.parse(String(content || "{}"));
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

async function callOpenAiEmbedding(text) {
  const content = String(text || "").trim();
  if (!content || !CONFIG.openaiApiKey) return null;
  try {
    const resp = await fetch("https://api.openai.com/v1/embeddings", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${CONFIG.openaiApiKey}`,
      },
      body: JSON.stringify({
        model: CONFIG.openaiEmbeddingModel,
        input: content.slice(0, 6000),
      }),
    });
    if (!resp.ok) return null;
    const data = await resp.json().catch(() => null);
    const vector = data?.data?.[0]?.embedding;
    return Array.isArray(vector) ? vector : null;
  } catch {
    return null;
  }
}

async function summarizeRulesForLod(rules) {
  const fallback = buildRulesSummary(rules).slice(0, 600);
  if (!CONFIG.openaiApiKey) return fallback;
  const prompt = [
    "Summarize the world rules in <= 320 chars.",
    "Keep only stable semantics, no markdown.",
    `Rules JSON: ${JSON.stringify(rules || {})}`,
  ].join("\n");
  const parsed = await callOpenAiJson({
    systemPrompt: "You compress simulation rules for storage-efficient semantic LOD.",
    userPrompt: `${prompt}\nOutput JSON: {"summary":"..."}`
  });
  const summary = String(parsed?.summary || "").trim();
  return summary || fallback;
}

async function generateGenesisRules({ lat, lng, seedHash, entropy, previousRules, summary, mode }) {
  const fallback = buildFallbackGenesis({
    seedHash,
    lat,
    lng,
    entropy,
    previousRule: previousRules?.physical_rule || "",
  });
  if (!CONFIG.openaiApiKey) {
    return normalizeGenesisRules(fallback, fallback);
  }

  const userPrompt = [
    `Mode: ${String(mode || "initial")}`,
    `Coordinates: ${Number(lat).toFixed(6)}, ${Number(lng).toFixed(6)}`,
    `Seed hash: ${seedHash}`,
    `Current entropy: ${Number(entropy || 0).toFixed(4)}`,
    `Previous rules: ${JSON.stringify(previousRules || {})}`,
    `Semantic summary: ${String(summary || "")}`,
    "Output strict JSON with keys:",
    `{"visual_theme":"","narrative":"","physical_rule":"","dev_task":"","heavenly_laws":["","",""],"summary":""}`,
    "Requirements:",
    "- physical_rule must be unique and non-generic.",
    "- Keep sci-fi atmosphere with black/gold/neon-violet tone.",
    "- If mode is iterate or regrowth, evolve instead of overwrite.",
  ].join("\n");

  const parsed = await callOpenAiJson({
    systemPrompt: "You are the Genesis Semantic Engine for a geo-fantasy simulation.",
    userPrompt,
    temperature: mode === "initial" ? 0.9 : 0.72,
    maxTokens: 900,
  });
  return normalizeGenesisRules(parsed, fallback);
}

async function fetchWorldEntityBySeed(seedHash) {
  const client = getSupabaseServiceClient();
  if (!client) return { ok: false, row: null, error: "world_storage_unavailable" };
  const { data, error } = await client
    .from(WORLD_ENTITY_TABLE)
    .select("*")
    .eq("seed_hash", seedHash)
    .limit(1)
    .maybeSingle();
  if (error) return { ok: false, row: null, error: error.message || error.code || "world_read_failed" };
  return { ok: true, row: data && typeof data === "object" ? data : null };
}

async function upsertWorldEntity(row) {
  const client = getSupabaseServiceClient();
  if (!client) return { ok: false, row: null, error: "world_storage_unavailable" };
  const { data, error } = await client
    .from(WORLD_ENTITY_TABLE)
    .upsert(row, { onConflict: "seed_hash" })
    .select("*")
    .limit(1)
    .maybeSingle();
  if (error) return { ok: false, row: null, error: error.message || error.code || "world_upsert_failed" };
  return { ok: true, row: data && typeof data === "object" ? data : null };
}

async function getGlobalDevelopments(client) {
  const { data, error } = await client
    .from(WORLD_META_TABLE)
    .select("value_num")
    .eq("meta_key", WORLD_META_KEY_GLOBAL_DEV)
    .limit(1)
    .maybeSingle();
  if (error) return 0;
  const n = Number(data?.value_num || 0);
  return Number.isFinite(n) ? Math.max(0, n) : 0;
}

async function bumpGlobalDevelopments(delta = 1) {
  const client = getSupabaseServiceClient();
  if (!client) return 0;
  const current = await getGlobalDevelopments(client);
  const next = Math.max(0, current + Math.max(0, Number(delta) || 0));
  const payload = {
    meta_key: WORLD_META_KEY_GLOBAL_DEV,
    value_num: next,
    meta: { source: "genesis" },
    updated_at: nowIso(),
  };
  await client.from(WORLD_META_TABLE).upsert(payload, { onConflict: "meta_key" });
  return next;
}

function isFixedLocked(row) {
  if (!row || !row.is_fixed) return false;
  const fixedUntil = Date.parse(String(row.fixed_until || ""));
  if (!Number.isFinite(fixedUntil)) return false;
  return fixedUntil > nowMs();
}

async function buildGenesisPayload({ lat, lng }) {
  const seed = seedHashFromCell(lat, lng, CONFIG.worldCellDecimals, CONFIG.sessionSecret || "worldforge-v1");
  const fallbackEntropy = baseEntropyFromSeed(seed.seedHash);

  const worldRead = await fetchWorldEntityBySeed(seed.seedHash);
  const existing = worldRead.ok ? worldRead.row : null;
  const locked = isFixedLocked(existing);
  const staleHours = existing?.last_observed
    ? Math.max(0, (nowMs() - Date.parse(String(existing.last_observed))) / 3_600_000)
    : 0;

  let entropy = existing ? clamp01(Number(existing.entropy || fallbackEntropy)) : fallbackEntropy;
  let rules = existing?.rules && typeof existing.rules === "object" ? existing.rules : null;
  let summary = String(existing?.rules_summary || "").trim();
  let decayApplied = false;
  let regrown = false;
  let iterated = false;

  if (existing && !locked && staleHours > CONFIG.worldDecayHours) {
    summary = await summarizeRulesForLod(rules || {});
    entropy = clamp01(entropy + 0.08 + Math.min(0.16, (staleHours - CONFIG.worldDecayHours) / 240));
    decayApplied = true;
    if (entropy > CONFIG.worldEntropyMutate) {
      rules = await generateGenesisRules({
        lat: seed.lat,
        lng: seed.lng,
        seedHash: seed.seedHash,
        entropy,
        previousRules: rules || {},
        summary,
        mode: "regrowth",
      });
      summary = String(rules.summary || buildRulesSummary(rules)).slice(0, 600);
      entropy = clamp01(0.55 + (Math.random() * 0.18));
      regrown = true;
    }
  }

  if (!rules) {
    rules = await generateGenesisRules({
      lat: seed.lat,
      lng: seed.lng,
      seedHash: seed.seedHash,
      entropy,
      previousRules: {},
      summary: "",
      mode: "initial",
    });
  } else if (existing && !locked && !regrown) {
    rules = await generateGenesisRules({
      lat: seed.lat,
      lng: seed.lng,
      seedHash: seed.seedHash,
      entropy,
      previousRules: rules,
      summary,
      mode: "iterate",
    });
    iterated = true;
  }

  if (existing && !locked) {
    entropy = clamp01(entropy * 0.92 + 0.03 + (Math.random() * 0.06));
  }
  if (locked) {
    entropy = clamp01(Math.min(entropy, 0.45));
  }

  summary = String(summary || rules.summary || buildRulesSummary(rules)).slice(0, 600);
  const embeddingText = `${summary}\n${String(rules?.physical_rule || "")}`;
  const embedding = await callOpenAiEmbedding(embeddingText);
  const embeddingLiteral = toVectorLiteral(embedding);

  let persisted = existing;
  if (getSupabaseServiceClient()) {
    const mergedRow = {
      seed_hash: seed.seedHash,
      lat: seed.lat,
      lng: seed.lng,
      entropy,
      rules,
      rules_summary: summary,
      last_observed: nowIso(),
      is_fixed: Boolean(existing?.is_fixed || false),
      fixed_until: existing?.fixed_until || null,
      development_count: Number(existing?.development_count || 0) + 1,
      mutation_count: Number(existing?.mutation_count || 0) + (iterated || regrown ? 1 : 0),
    };
    if (embeddingLiteral) {
      mergedRow.embedding = embeddingLiteral;
    }
    const upserted = await upsertWorldEntity(mergedRow);
    if (upserted.ok && upserted.row) {
      persisted = upserted.row;
    }
  }

  const globalDevelopments = await bumpGlobalDevelopments(1);
  const spaceStage = deriveSpaceStage(globalDevelopments, CONFIG.spaceUnlockMoon, CONFIG.spaceUnlockMars);

  return {
    ok: true,
    lat: seed.lat,
    lng: seed.lng,
    seed_hash: seed.seedHash,
    cell: seed.cell,
    entropy: clamp01(Number(persisted?.entropy ?? entropy)),
    rules,
    rules_summary: summary,
    is_fixed: Boolean(persisted?.is_fixed || false),
    fixed_until: persisted?.fixed_until || null,
    locked,
    stale_hours: Number(staleHours.toFixed(3)),
    decay_applied: decayApplied,
    regrown,
    iterated,
    global_developments: globalDevelopments,
    space_stage: spaceStage.stage,
    space_unlocked: Boolean(spaceStage.unlocked),
    entropy_warn_threshold: CONFIG.worldEntropyWarn,
    entropy_mutate_threshold: CONFIG.worldEntropyMutate,
  };
}

function buildCanonizationInvoiceRecord({ seedHash, paymentRail }) {
  const normalizedRail = normalizePaymentRail(paymentRail || CONFIG.canonizationRail);
  const ttlSec = Math.max(300, Math.floor(CONFIG.paymentInvoiceTtlSec || 1200));
  const expiresAt = new Date(nowMs() + ttlSec * 1000).toISOString();
  return {
    invoice_id: generateInvoiceId(),
    wallet_address: null,
    slug: `canon_${String(seedHash || "").slice(0, 32)}`,
    plan_code: "canonization",
    amount_usdt: Number(CONFIG.canonizationPriceUsdt || 49),
    pay_to_address: resolvePaymentRecipient(normalizedRail),
    nonce: generatePaymentNonce(),
    status: "pending",
    expires_at_utc: expiresAt,
    meta: {
      source: "worldforge_canonization",
      created_via: "/api/canonize/create",
      payment_rail: normalizedRail,
      seed_hash: String(seedHash || ""),
      l2_network: String(CONFIG.supportL2Network || "arbitrum").toLowerCase(),
    },
  };
}

async function fetchPaymentInvoiceLoose(invoiceId) {
  const client = getSupabaseServiceClient();
  if (!client) return { ok: false, error: "payment_storage_unavailable" };
  const { data, error } = await client
    .from("payment_invoices")
    .select("invoice_id,status,amount_usdt,pay_to_address,expires_at_utc,updated_at,meta")
    .eq("invoice_id", String(invoiceId || "").trim())
    .limit(1)
    .maybeSingle();
  if (error) return { ok: false, error: error.message || error.code || "invoice_read_failed" };
  if (!data) return { ok: false, error: "invoice_not_found" };
  return { ok: true, invoice: data };
}

async function applyCanonizationFix(seedHash) {
  const found = await fetchWorldEntityBySeed(seedHash);
  if (!found.ok || !found.row) return { ok: false, error: found.error || "zone_not_found" };
  const fixedUntil = new Date(nowMs() + CONFIG.worldCanonizeHours * 3_600_000).toISOString();
  const row = found.row;
  const payload = {
    seed_hash: seedHash,
    lat: Number(row.lat),
    lng: Number(row.lng),
    entropy: clamp01(Math.min(Number(row.entropy || 0.32), 0.42)),
    rules: row.rules || {},
    rules_summary: String(row.rules_summary || ""),
    last_observed: nowIso(),
    is_fixed: true,
    fixed_until: fixedUntil,
    development_count: Number(row.development_count || 0),
    mutation_count: Number(row.mutation_count || 0),
  };
  const upserted = await upsertWorldEntity(payload);
  if (!upserted.ok) return { ok: false, error: upserted.error || "canonization_update_failed" };
  return { ok: true, fixed_until: fixedUntil };
}

async function buildSpaceNarrative({ stage, earthRules, globalDevelopments }) {
  const fallback = {
    moon: "Moon corridor opened. Lunar law inherits local entropy but halves mutation speed.",
    mars: "Mars corridor opened. Martian law amplifies narrative drift and doubles task rewards.",
    earth: "Space locked. Continue developing Earth zones to unlock semantic orbits.",
  };
  if (!CONFIG.openaiApiKey || !stage || stage === "earth") {
    return fallback[stage || "earth"];
  }
  const parsed = await callOpenAiJson({
    systemPrompt: "You synthesize concise sci-fi world expansion rules.",
    userPrompt: [
      `Target: ${stage}`,
      `Global developments: ${globalDevelopments}`,
      `Earth rule genes: ${JSON.stringify(earthRules || {})}`,
      'Output JSON: {"space_rule":"..."}',
    ].join("\n"),
    temperature: 0.86,
    maxTokens: 260,
  });
  const text = String(parsed?.space_rule || "").trim();
  return text || fallback[stage];
}

async function buildSpacePayload({ lat, lng, zoom }) {
  const client = getSupabaseServiceClient();
  let globalDevelopments = 0;
  if (client) {
    globalDevelopments = await getGlobalDevelopments(client);
  }
  const stage = deriveSpaceStage(globalDevelopments, CONFIG.spaceUnlockMoon, CONFIG.spaceUnlockMars);
  if (!stage.unlocked) {
    return {
      ok: true,
      unlocked: false,
      target: "earth",
      global_developments: globalDevelopments,
      required: stage.required,
      orbit_points: [],
      switch_to_stars: false,
      space_rule: "Space gate remains sealed.",
    };
  }

  const seed = seedHashFromCell(lat, lng, CONFIG.worldCellDecimals, CONFIG.sessionSecret || "worldforge-v1");
  const found = await fetchWorldEntityBySeed(seed.seedHash);
  const earthRules = found.ok && found.row?.rules ? found.row.rules : {};
  const orbitPoints = buildSemanticOrbit({
    lat: seed.lat,
    lng: seed.lng,
    target: stage.stage,
    points: stage.stage === "mars" ? 32 : 24,
  });
  const spaceRule = await buildSpaceNarrative({
    stage: stage.stage,
    earthRules,
    globalDevelopments,
  });
  return {
    ok: true,
    unlocked: true,
    target: stage.stage,
    global_developments: globalDevelopments,
    required: stage.required,
    orbit_points: orbitPoints,
    switch_to_stars: Number(zoom || 0) < CONFIG.spaceZoomGate,
    space_rule: spaceRule,
  };
}

function triggerEntityProfilerForAddress(walletAddress) {
  const canonicalAddress = toCanonicalAddress(walletAddress);
  if (!canonicalAddress || IS_VERCEL_RUNTIME) return;
  const cwd = path.resolve(__dirname, "..");
  const pythonBin = process.env.SUPPORT_PYTHON_BIN || "python";
  try {
    const proc = spawn(
      pythonBin,
      ["scripts/entity_profiler.py", "--address", canonicalAddress, "--limit", "50"],
      {
        cwd,
        detached: true,
        stdio: "ignore",
      },
    );
    proc.unref();
  } catch {
    // profiler trigger is best-effort and should not affect unlock flow
  }
}

function sanitizeDisplayText(input, locale = "en") {
  let text = String(input || "");
  const isZh = String(locale || "").toLowerCase() === "zh-tw";
  const pairs = isZh
    ? [
        [/oracle_report_pipeline_stale/gi, "主權結構偏移"],
        [/oracle_report_generation_error/gi, "主權合成偏移"],
        [/\bpipeline\b/gi, "結構脈絡"],
        [/\bapi\b/gi, "資料中繼"],
        [/\bmock\b/gi, "預演"],
        [/\bpython\b/gi, "運算核心"],
        [/\bgeo\b/gi, "主權網域"],
      ]
    : [
        [/oracle_report_pipeline_stale/gi, "Sovereign Structure Deviation"],
        [/oracle_report_generation_error/gi, "Sovereign Synthesis Deviation"],
        [/\bpipeline\b/gi, "structure flow"],
        [/\bapi\b/gi, "source relay"],
        [/\bmock\b/gi, "preview"],
        [/\bpython\b/gi, "compute core"],
        [/\bgeo\b/gi, "sovereign domain"],
      ];

  for (const [pattern, replacement] of pairs) {
    text = text.replace(pattern, replacement);
  }
  text = text
    .replace(/\b[a-f0-9]{24,}\b/gi, "")
    .replace(/\/analysis\/[a-z0-9_-]+/gi, "")
    .replace(/^.*(?:參考識別|權限策略|Authority Record|Authority proof).*$\n?/gim, "")
    .replace(/^.*(?:Conclusion Event|結論 事件).*$\n?/gim, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return text;
}

function normalizeEvidencePack(raw) {
  const src = raw && typeof raw === "object" ? raw : {};
  const v1 = src.v1 && typeof src.v1 === "object" ? src.v1 : {};
  const v2 = src.v2 && typeof src.v2 === "object" ? src.v2 : {};
  return {
    entity: String(src.entity || ""),
    event_type: String(src.event_type || ""),
    severity: String(src.severity || ""),
    v1: {
      vol_z_score: Number(v1.vol_z_score || 0),
      k_line_delta: Number(v1.k_line_delta || 0),
      open_interest_stress: Number(v1.open_interest_stress || 0),
      sovereign_bias_mapped: Number(v1.sovereign_bias_mapped || 0),
      pulse_label: String(v1.pulse_label || ""),
      range_pct_4h: Number(v1.range_pct_4h || 0),
      open_interest_drop_pct: Number(v1.open_interest_drop_pct || 0),
    },
    v2: {
      orderflow_proxy: Number(v2.orderflow_proxy || 0),
      depth_imbalance_proxy: Number(v2.depth_imbalance_proxy || 0),
      regime_pressure: Number(v2.regime_pressure || 0),
      calibration_state: String(v2.calibration_state || "calibrating"),
    },
    window_contract: src.window_contract && typeof src.window_contract === "object" ? src.window_contract : {},
  };
}

function normalizeVerdictPack(raw) {
  const src = raw && typeof raw === "object" ? raw : {};
  return {
    structural_verdict: String(src.structural_verdict || "rebalancing_watch"),
    confidence_score: Number(src.confidence_score || 0),
    alpha_posture: String(src.alpha_posture || "balanced"),
    restriction: String(src.restriction || "locked_for_unsigned_users"),
  };
}

function normalizeReportRow(raw) {
  const row = raw && typeof raw === "object" ? raw : {};
  const locale = normalizeOuroborosLocale(String(row.locale || DEFAULT_REPORT_LOCALE));
  return {
    report_id: Number(row.report_id || 0),
    event_id: String(row.event_id || ""),
    locale,
    title: sanitizeDisplayText(String(row.title || ""), locale),
    slug: String(row.slug || ""),
    body_md: sanitizeDisplayText(String(row.body_md || ""), locale),
    jsonld: row.jsonld && typeof row.jsonld === "object" ? row.jsonld : {},
    unique_entity: String(row.unique_entity || ""),
    evidence_pack: normalizeEvidencePack(row.evidence_pack),
    verdict_pack: normalizeVerdictPack(row.verdict_pack),
    snapshot_svg: String(row.snapshot_svg || ""),
    snapshot_url: String(row.snapshot_url || ""),
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

function stripLockedVerdictSections(md, locale = "en") {
  const src = String(md || "");
  if (!src) return src;
  const isZh = normalizeOuroborosLocale(locale) === "zh-tw";
  const patterns = isZh
    ? [
        /(?:^|\n)#{1,6}\s*結構裁決\s*\n[\s\S]*?(?=\n#{1,6}\s|$)/gi,
        /(?:^|\n)#{1,6}\s*結論\s*\n[\s\S]*?(?=\n#{1,6}\s|$)/gi,
      ]
    : [
        /(?:^|\n)#{1,6}\s*Structural Verdict\s*\n[\s\S]*?(?=\n#{1,6}\s|$)/gi,
        /(?:^|\n)#{1,6}\s*Conclusion\s*\n[\s\S]*?(?=\n#{1,6}\s|$)/gi,
      ];
  let cleaned = src;
  for (const pattern of patterns) {
    cleaned = cleaned.replace(pattern, "\n");
  }
  return cleaned.replace(/\n{3,}/g, "\n\n").trim();
}

function extractBoundaryText(md, locale = "en", fallback = "") {
  const src = String(md || "").trim();
  if (!src) return String(fallback || "").trim();
  const isZh = normalizeOuroborosLocale(locale) === "zh-tw";
  const headingPattern = isZh
    ? /(?:^|\n)#{1,6}\s*風險邊界\s*\n([\s\S]*?)(?=\n#{1,6}\s|\s*$)/i
    : /(?:^|\n)#{1,6}\s*Risk Boundary\s*\n([\s\S]*?)(?=\n#{1,6}\s|\s*$)/i;
  const matched = src.match(headingPattern);
  if (matched?.[1]) {
    const extracted = String(matched[1]).trim();
    if (extracted) return extracted;
  }
  return String(fallback || "").trim();
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

function serializeJsonForScriptTag(raw) {
  return JSON.stringify(raw || {})
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
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
          nodeType === "Dataset" ||
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
    nodeType === "Dataset" ||
    nodeType === "Report" ||
    nodeType === "WebPage";
  if (!isPaywallNode) return jsonLd;
  return {
    ...jsonLd,
    isAccessibleForFree: false,
    hasPart: paywallHasPart(),
  };
}

async function fetchLatestReports(limit = 5, locale = DEFAULT_REPORT_LOCALE) {
  const client = getSupabaseClient();
  if (!client) return [];
  const safeLimit = Math.min(Math.max(1, Number(limit) || 5), 50);
  const preferredLocale = normalizeOuroborosLocale(locale);

  const primary = await client
    .from("oracle_reports")
    .select(REPORT_SELECT_FIELDS)
    .eq("locale", preferredLocale)
    .order("updated_at", { ascending: false })
    .limit(safeLimit);
  if (!primary.error && Array.isArray(primary.data) && primary.data.length > 0) {
    return primary.data.map(normalizeReportRow);
  }

  return [];
}

async function fetchReportsForIndex(limit = 200, locale = DEFAULT_REPORT_LOCALE) {
  const client = getSupabaseClient();
  if (!client) return [];
  const safeLimit = Math.min(Math.max(1, Number(limit) || 200), 5000);
  const preferredLocale = normalizeOuroborosLocale(locale);
  const { data, error } = await client
    .from("oracle_reports")
    .select(REPORT_SELECT_FIELDS)
    .eq("locale", preferredLocale)
    .order("updated_at", { ascending: false })
    .limit(safeLimit);
  if (error || !Array.isArray(data)) return [];
  return data.map(normalizeReportRow);
}

async function fetchReportsAcrossLocales(limitPerLocale = 30) {
  const locales = ["en", "zh-tw", "es", "ja"];
  const merged = [];
  const seen = new Set();
  for (const locale of locales) {
    const rows = await fetchReportsForIndex(limitPerLocale, locale);
    for (const row of rows) {
      const slug = String(row?.slug || "");
      if (!slug || seen.has(slug)) continue;
      seen.add(slug);
      merged.push(row);
    }
  }
  merged.sort((a, b) => Date.parse(String(b?.updated_at || b?.created_at || "")) - Date.parse(String(a?.updated_at || a?.created_at || "")));
  return merged.slice(0, Math.max(1, limitPerLocale * locales.length));
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

async function fetchReportByEventAndLocale(eventId, locale) {
  const client = getSupabaseClient();
  if (!client) return null;
  const cleanedEventId = String(eventId || "").trim();
  const preferredLocale = normalizeOuroborosLocale(locale);
  if (!cleanedEventId) return null;
  const { data, error } = await client
    .from("oracle_reports")
    .select(REPORT_SELECT_FIELDS)
    .eq("event_id", cleanedEventId)
    .eq("locale", preferredLocale)
    .order("updated_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error || !data) return null;
  return normalizeReportRow(data);
}

async function fetchAnalysisPaths(limit = 5000) {
  const client = getSupabaseClient();
  if (!client) return [];
  const safeLimit = Math.min(Math.max(1, Number(limit) || 5000), 5000);
  const { data, error } = await client
    .from("oracle_reports")
    .select("slug")
    .order("updated_at", { ascending: false })
    .limit(safeLimit);
  if (error || !Array.isArray(data)) return [];
  return data
    .map((row) => String(row?.slug || "").trim().toLowerCase())
    .filter(Boolean)
    .map((slug) => `/analysis/${slug}`);
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
  locale = "en",
  keywords = "Sovereign AI Oracle, BTC Alpha Signals, Whale Intelligence, Institutional Crypto Analysis",
  pageType = "generic",
}) {
  const ldPayload = serializeJsonLd(jsonLd || {});
  const ogUrl = String(canonicalUrl || ROOT_CANONICAL_URL);
  const canonicalRoot = ROOT_CANONICAL_URL.replace(/\/+$/, "");
  const canonicalPathRaw = ogUrl.startsWith(canonicalRoot)
    ? ogUrl.slice(canonicalRoot.length)
    : "/";
  const canonicalPath = canonicalPathRaw && canonicalPathRaw.startsWith("/") ? canonicalPathRaw : `/${canonicalPathRaw || ""}`;
  const pathForAlt = canonicalPath === "/" ? "" : canonicalPath;
  const hreflangLinks = [
    { hreflang: "x-default", href: `${canonicalRoot}${pathForAlt || "/"}` },
    { hreflang: "en", href: `${canonicalRoot}${pathForAlt || "/"}` },
    { hreflang: "zh-Hant", href: `${canonicalRoot}/zh-tw${pathForAlt || "/"}` },
    { hreflang: "es", href: `${canonicalRoot}/es${pathForAlt || "/"}` },
    { hreflang: "ja", href: `${canonicalRoot}/ja${pathForAlt || "/"}` },
  ]
    .map((row) => `<link rel="alternate" hreflang="${escapeHtml(row.hreflang)}" href="${escapeHtml(row.href)}">`)
    .join("\n  ");
  const ogLocale = locale === "zh-tw" ? "zh_TW" : locale === "es" ? "es_ES" : locale === "ja" ? "ja_JP" : "en_US";
  return `<!doctype html>
<html lang="${escapeHtml(locale)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(title)}</title>
  <meta name="description" content="${escapeHtml(description)}">
  <meta name="keywords" content="${escapeHtml(keywords)}">
  <meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">
  <meta property="og:type" content="website">
  <meta property="og:locale" content="${escapeHtml(ogLocale)}">
  <meta property="og:title" content="${escapeHtml(title)}">
  <meta property="og:description" content="${escapeHtml(description)}">
  <meta property="og:url" content="${escapeHtml(ogUrl)}">
  <meta property="og:image" content="${escapeHtml(ROOT_CANONICAL_URL)}assets/social-card.svg">
  <meta property="twitter:card" content="summary_large_image">
  <meta property="twitter:title" content="${escapeHtml(title)}">
  <meta property="twitter:description" content="${escapeHtml(description)}">
  <meta property="twitter:image" content="${escapeHtml(ROOT_CANONICAL_URL)}assets/social-card.svg">
  <link rel="canonical" href="${escapeHtml(ogUrl)}">
  ${hreflangLinks}
  <script type="application/ld+json">${ldPayload}</script>
  <link rel="stylesheet" href="/assets/ouroboros.css">
</head>
<body data-page="${escapeHtml(pageType)}" data-locale="${escapeHtml(locale)}">
  <canvas id="matrix-bg" aria-hidden="true"></canvas>
  <div class="page-noise" aria-hidden="true"></div>
  ${bodyHtml}
  <script src="/assets/ouroboros.js"></script>
</body>
</html>`;
}

function buildReportCard(report, copy) {
  const summary = buildSummary(report.body_md, 176);
  const updatedAt = report.updated_at || report.created_at || "";
  const localeTag = toLocaleTag(report.locale);
  const title = String(report.title || "");
  const entity = String(report.unique_entity || "LeiMai Liquidity Friction");
  return `<a class="matrix-card glass-panel cyber-border report-card" href="/analysis/${escapeHtml(report.slug)}" data-filter="${escapeHtml(`${report.locale} ${report.unique_entity} ${report.title}`)}">
    <div class="card-top terminal-font">
      <span>${escapeHtml(localeTag)}</span>
      <span class="report-time terminal-font" data-utc="${escapeHtml(updatedAt)}">${escapeHtml(updatedAt || "-")}</span>
    </div>
    <div class="card-mid neon-text clamp-3">${escapeHtml(title)}</div>
    <div class="card-sub clamp-4">${escapeHtml(summary || copy.analysisEmpty)}</div>
    <div class="report-entity terminal-font clamp-1">${escapeHtml(entity)}</div>
  </a>`;
}

function buildSovereignGateConfig(planCode = "sovereign") {
  const plan = normalizePlanCode(planCode);
  return {
    planCode: plan,
    amountUsdt: resolvePlanAmountUsdt(plan),
    erc20Address: resolvePaymentRecipient("eth_l1_erc20"),
    arbitrumAddress: resolvePaymentRecipient("l2_usdc"),
    l2Network: String(CONFIG.supportL2Network || "arbitrum").toLowerCase(),
  };
}

function renderSovereignGateButton({
  label,
  slug = "vault",
  planCode = "sovereign",
  paymentRail = "l2_usdc",
  className = "sovereign-gate-btn pulse-glow",
}) {
  const gate = buildSovereignGateConfig(planCode);
  return `<button class="${escapeHtml(className)}" type="button"
    data-plan="${escapeHtml(gate.planCode)}"
    data-payment-rail="${escapeHtml(normalizePaymentRail(paymentRail))}"
    data-slug="${escapeHtml(slug)}"
    data-amount-usdc="${escapeHtml(String(gate.amountUsdt))}"
    data-erc20-address="${escapeHtml(gate.erc20Address)}"
    data-arbitrum-address="${escapeHtml(gate.arbitrumAddress)}"
    data-l2-network="${escapeHtml(gate.l2Network)}">${escapeHtml(label)}</button>`;
}

function renderPaymentModal(title = "Sovereign Invoice") {
  return `<div id="paymentModal" class="payment-modal" aria-hidden="true">
      <div class="payment-modal-card glass-panel cyber-border">
        <button id="paymentModalCloseBtn" class="payment-close-btn" type="button">[ CLOSE ]</button>
        <h2 class="neon-text">${escapeHtml(title)}</h2>
        <div class="invoice-grid terminal-font">
          <div><span>INVOICE</span><strong id="invoiceIdField">-</strong></div>
          <div><span>PLAN</span><strong id="invoicePlanField">-</strong></div>
          <div><span>AMOUNT</span><strong id="invoiceAmountField">-</strong></div>
          <div><span>ADDRESS</span><strong id="invoiceAddressField">-</strong></div>
          <div><span>NONCE</span><strong id="invoiceNonceField">-</strong></div>
          <div><span>EXPIRES</span><strong id="invoiceExpiryField">-</strong></div>
        </div>
      </div>
    </div>`;
}

function renderRootLandingPage(locale, reports, copyOverrides = {}) {
  const copy = resolveOuroborosCopy(locale, copyOverrides);
  const rows = Array.isArray(reports) ? reports.slice(0, 5) : [];
  const cardHtml = rows.map((row) => buildReportCard(row, copy)).join("");
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
      <div class="hero-kicker terminal-font">${escapeHtml(copy.homeKicker)}</div>
      <h1 class="neon-text">${escapeHtml(copy.homeTitle)}</h1>
      <p>${escapeHtml(copy.homeLead)}</p>
      <div class="geo-badge terminal-font">
        <span>Hub:</span>
        <strong id="geoHub">Global</strong>
        <span id="geoTier">Platinum Node</span>
      </div>
      <div class="hero-cta-row">
        <a class="btn btn-main" href="/analysis/">${escapeHtml(copy.homeOpenIndex)}</a>
        <a class="btn" href="/forge">[ ORACLE FORGE ]</a>
        <a class="btn" href="https://leimai.io/" target="_blank" rel="noopener">${escapeHtml(copy.homeMainDomain)}</a>
      </div>
    </header>

    <section class="panel glass-panel cyber-border">
      <h2>${escapeHtml(copy.homeLatestTitle)}</h2>
      <p class="muted">${escapeHtml(copy.homeLatestLead)}</p>
      ${hasRows ? `<div id="analysisCards" class="matrix-grid">${cardHtml}</div>` : `<div class="empty-box">${escapeHtml(copy.homeEmpty)}</div>`}
    </section>

    <section class="panel glass-panel cyber-border forge-shell">
      <h2>[ORACLE FORGE: BTC CORE]</h2>
      <p class="muted">Live sovereign model convergence stream. Locked outputs are released only through the cold wallet gateway.</p>
      <div class="forge-cta-row">
        <a class="btn" href="/forge">Open Forge Interface</a>
        ${renderSovereignGateButton({
          label: "[ PRE-ORDER ACCESS / SUBSCRIBE ]",
          slug: "vault",
          planCode: "sovereign",
          paymentRail: "l2_usdc",
        })}
      </div>
      <div id="paymentResult" class="payment-result muted"></div>
    </section>
    ${renderPaymentModal("Sovereign Gateway Invoice")}
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
        name: copy.homeTitle,
        url: `${ROOT_CANONICAL_URL}analysis/`,
        isPartOf: { "@type": "WebSite", name: "LeiMai Oracle", url: ROOT_CANONICAL_URL },
      },
      {
        "@type": "WebPage",
        name: "Oracle Forge BTC Core",
        url: `${ROOT_CANONICAL_URL}forge`,
        isPartOf: { "@type": "WebSite", name: "LeiMai Oracle", url: ROOT_CANONICAL_URL },
      },
    ],
  };

  return renderOuroborosDocument({
    title: `LeiMai Oracle | ${copy.homeTitle}`,
    description: copy.homeLead,
    bodyHtml,
    jsonLd,
    canonicalUrl: ROOT_CANONICAL_URL,
    locale,
    keywords: copy.keywords,
    pageType: "home",
  });
}

function renderVaultPage(locale, { signed = false, unlockedAddress = null } = {}, copyOverrides = {}) {
  const copy = resolveOuroborosCopy(locale, copyOverrides);
  const gateText = signed
    ? copy.gateSigned
    : copy.gateUnsigned;
  const actionHtml = signed
    ? `<div class="vault-sync-state terminal-font">${escapeHtml(
        unlockedAddress ? `${copy.sessionVerified}: ${unlockedAddress}` : copy.sessionVerified,
      )}</div>
      ${renderSovereignGateButton({
        label: copy.upgradeBtn,
        slug: "vault",
        planCode: "sovereign",
        paymentRail: "l2_usdc",
        className: "upgrade-btn pulse-glow",
      })}
      <div id="paymentResult" class="payment-result muted"></div>`
    : `<button class="unlock-btn sign-btn pulse-glow" type="button">${escapeHtml(copy.signBtn)}</button>`;

  const bodyHtml = `<main class="site-wrap">
    <header class="hero hero-compact glass-panel cyber-border">
      <div class="hero-kicker terminal-font">${escapeHtml(copy.vaultKicker)}</div>
      <h1 class="neon-text">${escapeHtml(copy.vaultTitle)}</h1>
      <p>${escapeHtml(copy.vaultLead)}</p>
      <div class="hero-cta-row">
        <a class="btn" href="/">${escapeHtml(copy.backRoot)}</a>
        <a class="btn btn-main" href="/analysis/">${escapeHtml(copy.backIndex)}</a>
        <a class="btn" href="/forge">[ ORACLE FORGE ]</a>
      </div>
    </header>

    <section class="panel glass-panel cyber-border vault-panel">
      <div class="vault-stage" data-unlocked-address="${escapeHtml(unlockedAddress || "")}">
        <div class="obsidian-vault-door pulse-glow" aria-hidden="true"></div>
        <div class="lock-message">${escapeHtml(gateText)}</div>
        ${actionHtml}
      </div>
    </section>

    ${renderPaymentModal("Sovereign Gateway Invoice")}
  </main>`;

  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "WebPage",
        name: `LeiMai Oracle | ${copy.vaultTitle}`,
        url: `${ROOT_CANONICAL_URL}vault`,
        description: copy.vaultLead,
        isPartOf: { "@type": "WebSite", name: "LeiMai Oracle", url: ROOT_CANONICAL_URL },
        isAccessibleForFree: false,
        hasPart: paywallHasPart(),
      },
      {
        "@type": "NewsArticle",
        headline: `${copy.vaultTitle} Access Protocol`,
        description: copy.vaultLead,
        inLanguage: locale,
        mainEntityOfPage: `${ROOT_CANONICAL_URL}vault`,
        isAccessibleForFree: false,
        hasPart: paywallHasPart(),
      },
      {
        "@type": "Dataset",
        name: "Sovereign Access State Snapshot",
        description: "Commercial access-state telemetry for sovereign intelligence delivery.",
        creator: { "@type": "Organization", name: "LeiMai Oracle" },
        isAccessibleForFree: false,
        hasPart: paywallHasPart(),
      },
    ],
  };

  return renderOuroborosDocument({
    title: `LeiMai Oracle | ${copy.vaultTitle}`,
    description: gateText,
    bodyHtml,
    jsonLd,
    canonicalUrl: `${ROOT_CANONICAL_URL}vault`,
    locale,
    keywords: copy.keywords,
    pageType: "vault",
  });
}

function renderForgePage(locale, { signed = false, unlockedAddress = null } = {}, copyOverrides = {}) {
  const copy = resolveOuroborosCopy(locale, copyOverrides);
  const isZh = normalizeOuroborosLocale(locale) === "zh-tw";
  const gate = buildSovereignGateConfig("sovereign");
  const lockText = signed
    ? (isZh
        ? "簽署完成，主權模型維持訓練狀態。可直接進入冷錢包結算。"
        : "Signature verified. Model remains in training mode. Cold-wallet settlement is enabled.")
    : copy.paywallNotice;
  const transferLine = isZh
    ? `Transfer ${gate.amountUsdt} USDC to the Oracle Vault to decrypt the true Alpha.`
    : `Transfer ${gate.amountUsdt} USDC to the Oracle Vault to decrypt the true Alpha.`;
  const forgeCta = signed
    ? renderSovereignGateButton({
        label: "[ PRE-ORDER ACCESS / SUBSCRIBE ]",
        slug: "vault",
        planCode: "sovereign",
        paymentRail: "l2_usdc",
      })
    : `<button class="unlock-btn sign-btn pulse-glow" type="button">${escapeHtml(copy.signBtn)}</button>`;
  const paywallShellClass = signed ? "paywall-shell is-unlocked" : "paywall-shell";
  const bodyHtml = `<main class="site-wrap">
    <header class="hero hero-compact glass-panel cyber-border">
      <div class="hero-kicker terminal-font">MODEL FORGE</div>
      <h1 class="neon-text">[ORACLE FORGE: BTC CORE]</h1>
      <p>${escapeHtml(isZh
        ? "模型仍在收斂，輸出尚未授權部署。只有主權冷錢包流程可預先鎖定存取。"
        : "The BTC model is still converging and remains unauthorized for deployment. Pre-order access is only available through the sovereign cold-wallet flow.")}</p>
      <div class="hero-cta-row">
        <a class="btn" href="/">${escapeHtml(copy.backRoot)}</a>
        <a class="btn btn-main" href="/analysis/">${escapeHtml(copy.backIndex)}</a>
      </div>
    </header>

    <section class="panel glass-panel cyber-border forge-shell">
      <h2>[ORACLE FORGE: BTC CORE]</h2>
      <div class="forge-grid">
        <div class="forge-canvas-wrap">
          <canvas id="forgeMatrixCanvas" width="960" height="320" aria-label="Loss curve convergence"></canvas>
        </div>
        <aside class="forge-metrics">
          <div class="forge-metric"><span>EPOCH</span><strong id="forgeEpoch">4592/5000</strong></div>
          <div class="forge-metric"><span>ALPHA_CONVERGENCE</span><strong id="forgeConvergence">94.2%</strong></div>
          <div class="forge-metric"><span>STATUS</span><strong id="forgeStatus" class="forge-status">UNAUTHORIZED TO DEPLOY (TRAINING)</strong></div>
          <div class="forge-metric"><span>ERC20 (ETHEREUM)</span><strong class="mono-value">${escapeHtml(gate.erc20Address)}</strong></div>
          <div class="forge-metric"><span>${escapeHtml(String(gate.l2Network || "arbitrum").toUpperCase())} (USDC)</span><strong class="mono-value">${escapeHtml(gate.arbitrumAddress)}</strong></div>
        </aside>
      </div>
      <div class="guided-cta-copy">${escapeHtml(transferLine)}</div>
      <div class="forge-cta-row">
        ${forgeCta}
      </div>
      <div class="lock-message">${escapeHtml(lockText)}</div>
      <div id="paymentResult" class="payment-result muted"></div>
      <div class="${paywallShellClass}" style="display:none" data-unlocked="${signed ? "1" : "0"}" data-slug="vault" data-unlocked-address="${escapeHtml(unlockedAddress || "")}"></div>
    </section>
    ${renderPaymentModal("Sovereign Gateway Invoice")}
  </main>`;

  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "WebPage",
        name: "[ORACLE FORGE: BTC CORE]",
        url: `${ROOT_CANONICAL_URL}forge`,
        description: lockText,
        isPartOf: { "@type": "WebSite", name: "LeiMai Oracle", url: ROOT_CANONICAL_URL },
        isAccessibleForFree: false,
        hasPart: paywallHasPart(),
      },
      {
        "@type": "Dataset",
        name: "BTC Core Model Forge Stream",
        description: "Live model-convergence telemetry for sovereign BTC model training.",
        creator: { "@type": "Organization", name: "LeiMai Oracle" },
        url: `${ROOT_CANONICAL_URL}forge`,
        isAccessibleForFree: false,
        hasPart: paywallHasPart(),
      },
      {
        "@type": "Service",
        name: "Sovereign Cold Wallet Gateway",
        provider: { "@type": "Organization", name: "LeiMai Oracle" },
        serviceType: "Cold wallet settlement for model subscriptions",
      },
    ],
  };

  return renderOuroborosDocument({
    title: "LeiMai Oracle | ORACLE FORGE BTC CORE",
    description: lockText,
    bodyHtml,
    jsonLd,
    canonicalUrl: `${ROOT_CANONICAL_URL}forge`,
    locale,
    keywords: copy.keywords,
    pageType: "forge",
  });
}

function renderAnalysisIndexPage(locale, reports, copyOverrides = {}) {
  const copy = resolveOuroborosCopy(locale, copyOverrides);
  const rows = Array.isArray(reports) ? reports : [];
  const cardHtml = rows.map((row) => buildReportCard(row, copy)).join("");

  const bodyHtml = `<main class="site-wrap">
    <header class="hero hero-compact glass-panel cyber-border">
      <div class="hero-kicker terminal-font">${escapeHtml(copy.analysisKicker)}</div>
      <h1 class="neon-text">${escapeHtml(copy.analysisTitle)}</h1>
      <p>${escapeHtml(copy.analysisLead)}</p>
      <div class="hero-cta-row">
        <input id="analysisSearch" class="input" type="search" placeholder="${escapeHtml(copy.analysisSearch)}">
        <a class="btn" href="/">${escapeHtml(copy.backRoot)}</a>
      </div>
    </header>

    <section class="panel glass-panel cyber-border">
      <h2>${escapeHtml(copy.analysisAllTitle)}</h2>
      <p class="muted">${escapeHtml(copy.analysisTotal)}: ${rows.length}</p>
      ${rows.length > 0 ? `<div id="analysisCards" class="matrix-grid">${cardHtml}</div>` : `<div class="empty-box">${escapeHtml(copy.analysisEmpty)}</div>`}
    </section>
  </main>`;

  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "CollectionPage",
        name: copy.analysisTitle,
        url: `${ROOT_CANONICAL_URL}analysis/`,
        isPartOf: { "@type": "WebSite", name: "LeiMai Oracle", url: ROOT_CANONICAL_URL },
        isAccessibleForFree: false,
        hasPart: paywallHasPart(),
      },
      {
        "@type": "NewsArticle",
        headline: `${copy.analysisTitle} Snapshot`,
        description: copy.analysisLead,
        inLanguage: locale,
        mainEntityOfPage: `${ROOT_CANONICAL_URL}analysis/`,
        isAccessibleForFree: false,
        hasPart: paywallHasPart(),
      },
      {
        "@type": "Dataset",
        name: "Sovereign Analysis Catalog",
        description: "Commercially gated anomaly-driven market intelligence catalog.",
        creator: { "@type": "Organization", name: "LeiMai Oracle" },
        isAccessibleForFree: false,
        hasPart: paywallHasPart(),
      },
    ],
  };

  return renderOuroborosDocument({
    title: `LeiMai Oracle | ${copy.analysisTitle}`,
    description: copy.analysisLead,
    bodyHtml,
    jsonLd,
    canonicalUrl: `${ROOT_CANONICAL_URL}analysis/`,
    locale,
    keywords: copy.keywords,
    pageType: "analysis-index",
  });
}

function getPublicSnapshotUrl(report) {
  const raw = String(report?.snapshot_url || "").trim();
  if (raw.startsWith("/generated/snapshots/") && raw.endsWith(".png")) {
    return raw;
  }
  if (raw.startsWith("/analysis/") && raw.endsWith("/snapshot.svg")) {
    return raw;
  }
  return `/generated/snapshots/${encodeURIComponent(String(report?.slug || "").trim().toLowerCase())}.png`;
}

function buildSnapshotFallbackSvg(report, locale = "en") {
  const title = String(report?.title || "LeiMai Oracle Snapshot").slice(0, 80);
  const tag = normalizeOuroborosLocale(locale) === "zh-tw" ? "快照生成中" : "Snapshot Pending";
  const updated = String(report?.updated_at || report?.created_at || nowIso());
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" role="img">
  <rect width="1200" height="630" fill="#050507"/>
  <rect x="34" y="34" width="1132" height="562" fill="none" stroke="#D4AF37" stroke-opacity="0.38"/>
  <text x="64" y="112" fill="#D4AF37" font-size="24" font-family="JetBrains Mono, monospace">${escapeHtml(tag)}</text>
  <text x="64" y="162" fill="#f2f5f7" font-size="19" font-family="JetBrains Mono, monospace">${escapeHtml(title)}</text>
  <text x="64" y="540" fill="#b7c0ca" font-size="14" font-family="JetBrains Mono, monospace">${escapeHtml(updated)} UTC</text>
</svg>`;
}

function verdictLabel(key, locale) {
  const val = String(key || "").trim().toLowerCase();
  const zh = {
    structural_stress_expansion: "結構壓力擴張",
    liquidity_friction_persistent: "流動性摩擦延續",
    rebalancing_watch: "再平衡觀察",
  };
  const en = {
    structural_stress_expansion: "Structural Stress Expansion",
    liquidity_friction_persistent: "Persistent Liquidity Friction",
    rebalancing_watch: "Rebalancing Watch",
  };
  return normalizeOuroborosLocale(locale) === "zh-tw" ? (zh[val] || "結構再定價") : (en[val] || "Structural Repricing");
}

function postureLabel(key, locale) {
  const val = String(key || "").trim().toLowerCase();
  const zh = {
    defensive: "防禦姿態",
    defensive_to_balanced: "防禦轉平衡",
    balanced: "平衡姿態",
  };
  const en = {
    defensive: "Defensive",
    defensive_to_balanced: "Defensive to Balanced",
    balanced: "Balanced",
  };
  return normalizeOuroborosLocale(locale) === "zh-tw" ? (zh[val] || "平衡姿態") : (en[val] || "Balanced");
}

function buildFallbackJsonLd(report) {
  const url = `${ROOT_CANONICAL_URL}analysis/${encodeURIComponent(report.slug)}`;
  const summary = buildSummary(report.body_md, 240);
  const imageUrl = `${ROOT_CANONICAL_URL.replace(/\/+$/, "")}${getPublicSnapshotUrl(report)}`;
  return {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "NewsArticle",
        headline: report.title,
        description: summary,
        image: imageUrl,
        mainEntityOfPage: url,
        isPartOf: { "@type": "WebSite", name: "LeiMai Oracle", url: ROOT_CANONICAL_URL },
        author: { "@type": "Organization", name: "LeiMai Oracle" },
        dateModified: report.updated_at || report.created_at || nowIso(),
        inLanguage: report.locale,
        isAccessibleForFree: false,
        hasPart: paywallHasPart(),
      },
      {
        "@type": "Dataset",
        name: `${report.unique_entity || "LeiMai Liquidity Friction"} Dataset`,
        description: summary,
        creator: { "@type": "Organization", name: "LeiMai Oracle" },
        url,
        image: imageUrl,
        isAccessibleForFree: false,
        hasPart: paywallHasPart(),
      },
    ],
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

function renderAnalysisDetailPage(locale, report, { unlocked = false, unlockedAddress = null } = {}, copyOverrides = {}) {
  const copy = resolveOuroborosCopy(locale, copyOverrides);
  const reportBody = String(report.body_md || "");
  const visibleSource = unlocked ? reportBody : stripLockedVerdictSections(reportBody, locale);
  const previewMarkdown = unlocked ? visibleSource : buildPreviewMarkdown(visibleSource, REPORT_PREVIEW_RATIO);
  const summary = buildSummary(visibleSource || reportBody, 220);
  const markdownHtml = sanitizeMarkdownHtml(previewMarkdown);
  const canonicalUrl = `${ROOT_CANONICAL_URL}analysis/${encodeURIComponent(report.slug)}`;
  const snapshotUrl = getPublicSnapshotUrl(report);
  const evidence = report.evidence_pack && typeof report.evidence_pack === "object" ? report.evidence_pack : {};
  const evidenceV1 = evidence.v1 && typeof evidence.v1 === "object" ? evidence.v1 : {};
  const evidenceV2 = evidence.v2 && typeof evidence.v2 === "object" ? evidence.v2 : {};
  const verdict = report.verdict_pack && typeof report.verdict_pack === "object" ? report.verdict_pack : {};
  const verdictName = verdictLabel(verdict.structural_verdict, locale);
  const postureName = postureLabel(verdict.alpha_posture, locale);
  const confidenceValue = Number(verdict.confidence_score || 0);
  const confidenceText = unlocked ? `${confidenceValue.toFixed(1)} / 100` : "-- / 100";
  const verdictText = unlocked
    ? verdictName
    : normalizeOuroborosLocale(locale) === "zh-tw"
      ? "簽署後解鎖結構裁決"
      : "Unlock to reveal structural verdict";
  const postureText = unlocked
    ? postureName
    : normalizeOuroborosLocale(locale) === "zh-tw"
      ? "簽署後解鎖姿態"
      : "Unlock to reveal posture";
  const publicMetricLabels = normalizeOuroborosLocale(locale) === "zh-tw"
    ? {
        snapshot: "宏微觀快照",
        metrics: "公開指標層",
        volz: "Vol_Z",
        kdelta: "K 線差分",
        oi: "未平倉壓力",
        regime: "體制壓力",
        verdict: "結構裁決",
        confidence: "信心值",
        posture: "主權姿態",
      }
    : {
        snapshot: "Macro / Micro Snapshot",
        metrics: "Public Metrics Layer",
        volz: "Vol_Z",
        kdelta: "K-line Delta",
        oi: "OI Stress",
        regime: "Regime Pressure",
        verdict: "Structural Verdict",
        confidence: "Confidence",
        posture: "Alpha Posture",
      };
  const sourceJsonLd = normalizeJsonLd(report.jsonld, buildFallbackJsonLd(report));
  const paywallJsonLd = withPaywallJsonLd(sourceJsonLd);
  const paywallShellClass = unlocked ? "paywall-shell is-unlocked" : "paywall-shell";
  const lockMessage = unlocked ? copy.detailPolicySigned : copy.paywallNotice;
  const boundaryText = extractBoundaryText(report.body_md, locale, copy.detailBoundaryDefault);
  const boundaryHtml = sanitizeMarkdownHtml(boundaryText);
  const bodyHtml = `<main class="site-wrap">
    <header class="hero hero-compact glass-panel cyber-border">
      <div class="hero-kicker terminal-font">${escapeHtml(copy.detailKicker)}</div>
      <h1 class="neon-text clamp-3">${escapeHtml(report.title)}</h1>
      <p class="clamp-3">${escapeHtml(summary)}</p>
      <div class="hero-cta-row">
        <a class="btn btn-main" href="/analysis/">${escapeHtml(copy.detailBack)}</a>
        <a class="btn" href="/">${escapeHtml(copy.backRoot)}</a>
      </div>
    </header>

    <section class="panel glass-panel cyber-border">
      <h2>${escapeHtml(copy.detailMetaTitle)}</h2>
      <div class="kv-grid">
        <div class="kv-item"><span>${escapeHtml(copy.detailMetaUpdated)}</span><strong class="report-time terminal-font" data-utc="${escapeHtml(report.updated_at)}">${escapeHtml(report.updated_at || "-")}</strong></div>
        <div class="kv-item"><span>${escapeHtml(copy.detailMetaBoundary)}</span><strong class="clamp-3">${escapeHtml(buildSummary(boundaryText, 180))}</strong></div>
      </div>
    </section>

    <section class="panel glass-panel cyber-border">
      <h2>${escapeHtml(publicMetricLabels.snapshot)}</h2>
      <figure class="snapshot-frame">
        <img src="${escapeHtml(snapshotUrl)}" loading="lazy" decoding="async" alt="${escapeHtml(report.title)} snapshot">
      </figure>
      <div class="signal-public-grid">
        <div class="signal-public-item"><span>${escapeHtml(publicMetricLabels.volz)}</span><strong>${escapeHtml(Number(evidenceV1.vol_z_score || 0).toFixed(2))}</strong></div>
        <div class="signal-public-item"><span>${escapeHtml(publicMetricLabels.kdelta)}</span><strong>${escapeHtml(Number(evidenceV1.k_line_delta || 0).toFixed(2))}</strong></div>
        <div class="signal-public-item"><span>${escapeHtml(publicMetricLabels.oi)}</span><strong>${escapeHtml(Number(evidenceV1.open_interest_stress || 0).toFixed(2))}</strong></div>
        <div class="signal-public-item"><span>${escapeHtml(publicMetricLabels.regime)}</span><strong>${escapeHtml(Number(evidenceV2.regime_pressure || 0).toFixed(1))}</strong></div>
      </div>
    </section>

    <section class="panel glass-panel cyber-border">
      <h2>${unlocked ? escapeHtml(copy.detailFullTitle) : escapeHtml(copy.detailPreviewTitle)}</h2>
      <div class="${paywallShellClass}" data-unlocked="${unlocked ? "1" : "0"}" data-slug="${escapeHtml(report.slug)}" data-unlocked-address="${escapeHtml(unlockedAddress || "")}">
        <div class="obsidian-container">
          <article class="report-article article-body paywall-preview">${markdownHtml}</article>
        </div>
        <div class="verdict-gate">
          <div class="verdict-item"><span>${escapeHtml(publicMetricLabels.verdict)}</span><strong>${escapeHtml(verdictText)}</strong></div>
          <div class="verdict-item"><span>${escapeHtml(publicMetricLabels.confidence)}</span><strong>${escapeHtml(confidenceText)}</strong></div>
          <div class="verdict-item"><span>${escapeHtml(publicMetricLabels.posture)}</span><strong>${escapeHtml(postureText)}</strong></div>
        </div>
        <div class="paywall-locked-content" aria-label="locked-content">
          <div class="paywall-fog obsidian-fog"></div>
          <div class="mandala-wrap">${buildMandalaSvg()}</div>
          <div class="lock-message">${escapeHtml(lockMessage)}</div>
          <button class="unlock-btn sign-btn pulse-glow" type="button" ${unlocked ? "disabled" : ""}>${unlocked ? "[ ACCESS VERIFIED ]" : escapeHtml(copy.signBtn)}</button>
        </div>
      </div>
      <div class="boundary-note">
        <h3 class="terminal-font">${escapeHtml(copy.detailMetaBoundary)}</h3>
        <article class="article-body">${boundaryHtml}</article>
      </div>
    </section>
  </main>`;

  return renderOuroborosDocument({
    title: `LeiMai Oracle | ${report.title}`,
    description: summary || "Oracle report detail page.",
    bodyHtml,
    jsonLd: paywallJsonLd,
    canonicalUrl,
    locale,
    keywords: copy.keywords,
    pageType: "analysis-detail",
  });
}

function renderAnalysisNotFoundPage(locale, slug, copyOverrides = {}) {
  const copy = resolveOuroborosCopy(locale, copyOverrides);
  return renderOuroborosDocument({
    title: "Not Found | Analysis",
    description: "Requested analysis page does not exist.",
    bodyHtml: `<main class="site-wrap">
      <section class="panel glass-panel cyber-border">
        <h1>${escapeHtml(copy.notFoundTitle)}</h1>
        <p class="muted">${escapeHtml(copy.notFoundLead)}: <code>${escapeHtml(slug)}</code></p>
        <a class="btn btn-main" href="/analysis/">${escapeHtml(copy.notFoundBack)}</a>
      </section>
    </main>`,
    jsonLd: { "@context": "https://schema.org", "@type": "WebPage", name: "Analysis Not Found", url: ROOT_CANONICAL_URL },
    canonicalUrl: `${ROOT_CANONICAL_URL}analysis/`,
    locale,
    keywords: copy.keywords,
    pageType: "analysis-not-found",
  });
}

function goneResponse(res, pathname, locale = "en", copyOverrides = {}) {
  const copy = resolveOuroborosCopy(locale, copyOverrides);
  const html = renderOuroborosDocument({
    title: "410 Gone | LeiMai Oracle",
    description: "This legacy route has been permanently removed.",
    bodyHtml: `<main class="site-wrap">
      <section class="panel glass-panel cyber-border">
        <div class="hero-kicker terminal-font">410 GONE</div>
        <h1>${escapeHtml(copy.goneTitle)}</h1>
        <p>${escapeHtml(copy.goneLead)} <code>${escapeHtml(pathname)}</code></p>
        <div class="hero-cta-row">
          <a class="btn btn-main" href="/">${escapeHtml(copy.goneRoot)}</a>
          <a class="btn" href="/analysis/">${escapeHtml(copy.goneIndex)}</a>
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
    locale,
    keywords: copy.keywords,
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
  let routePath = String(pathname || "");
  let localeByPath = "";
  const localePathMatch = routePath.match(/^\/(en|zh-tw|es|ja)(\/.*)?$/i);
  if (localePathMatch) {
    localeByPath = normalizeOuroborosLocale(localePathMatch[1]);
    routePath = localePathMatch[2] ? String(localePathMatch[2]) : "/";
  }
  const locale = localeByPath || resolveOuroborosLocale(req);
  const copyOverrides = await readGrowthOverrides();

  if (method !== "GET") {
    goneResponse(res, pathname, locale, copyOverrides);
    return true;
  }

  if (routePath === "/assets/ouroboros.css") {
    const css = await fs.readFile(path.join(__dirname, "web", "ouroboros.css"), "utf-8");
    textResponse(res, 200, css, "text/css; charset=utf-8");
    return true;
  }
  if (routePath === "/assets/ouroboros.js") {
    const js = await fs.readFile(path.join(__dirname, "web", "ouroboros.js"), "utf-8");
    textResponse(res, 200, js, "application/javascript; charset=utf-8");
    return true;
  }
  if (routePath === "/assets/game.css") {
    const css = await fs.readFile(path.join(__dirname, "web", "game.css"), "utf-8");
    textResponse(res, 200, css, "text/css; charset=utf-8");
    return true;
  }
  if (routePath === "/assets/game.js") {
    const js = await fs.readFile(path.join(__dirname, "web", "game.js"), "utf-8");
    textResponse(res, 200, js, "application/javascript; charset=utf-8");
    return true;
  }
  if (routePath === "/assets/social-card.svg") {
    textResponse(res, 200, buildSocialCardSvg(), "image/svg+xml; charset=utf-8");
    return true;
  }
  const generatedSnapshotMatch = String(routePath || "").match(/^\/generated\/snapshots\/([a-z0-9_-]+)\.png$/i);
  if (generatedSnapshotMatch) {
    const slug = String(generatedSnapshotMatch[1] || "").trim().toLowerCase();
    const pngPath = path.join(__dirname, "web", "generated", "snapshots", `${slug}.png`);
    try {
      const image = await fs.readFile(pngPath);
      res.writeHead(200, {
        "Content-Type": "image/png",
        "Cache-Control": "public, max-age=900, stale-while-revalidate=3600",
      });
      res.end(image);
      return true;
    } catch {
      const report = await fetchReportBySlug(slug);
      if (report) {
        res.writeHead(302, { Location: `/analysis/${slug}/snapshot.svg` });
        res.end();
        return true;
      }
      textResponse(res, 404, "snapshot_not_found");
      return true;
    }
  }
  if (routePath === "/robots.txt") {
    textResponse(res, 200, buildRobots(CONFIG.siteUrl));
    return true;
  }
  if (routePath === "/sitemap-index.xml") {
    const indexXml = buildSitemapIndex(ROOT_CANONICAL_URL.replace(/\/+$/, ""), [
      "/sitemap-static.xml",
      "/sitemap-analysis.xml",
    ]);
    textResponse(res, 200, indexXml, "application/xml; charset=utf-8");
    return true;
  }
  if (routePath === "/sitemap-static.xml") {
    const staticXml = buildSitemapDocument(ROOT_CANONICAL_URL.replace(/\/+$/, ""), buildStaticSitemapPaths(), {
      changefreq: "daily",
    });
    textResponse(res, 200, staticXml, "application/xml; charset=utf-8");
    return true;
  }
  if (routePath === "/sitemap-analysis.xml") {
    const analysisPaths = await fetchAnalysisPaths(5000);
    const analysisXml = buildSitemapDocument(ROOT_CANONICAL_URL.replace(/\/+$/, ""), analysisPaths, {
      changefreq: "hourly",
    });
    textResponse(res, 200, analysisXml, "application/xml; charset=utf-8");
    return true;
  }
  if (routePath === "/sitemap.xml") {
    const indexXml = buildSitemapIndex(ROOT_CANONICAL_URL.replace(/\/+$/, ""), [
      "/sitemap-static.xml",
      "/sitemap-analysis.xml",
    ]);
    textResponse(res, 200, indexXml, "application/xml; charset=utf-8");
    return true;
  }
  if (routePath === "/llms.txt") {
    textResponse(res, 200, buildLlmsTxt(CONFIG.siteUrl, CONFIG.mainSiteUrl));
    return true;
  }
  if (routePath === "/.well-known/ai-citation-feed.json") {
    const reports = await fetchReportsAcrossLocales(20);
    const payload = buildAiCitationFeedPayload(CONFIG.siteUrl, reports);
    jsonResponse(res, 200, { ok: true, ...payload });
    return true;
  }
  if (routePath === "/") {
    const reports = await fetchLatestReports(5, locale);
    textResponse(res, 200, renderRootLandingPage(locale, reports, copyOverrides), "text/html; charset=utf-8");
    return true;
  }
  if (routePath === "/vault") {
    const unlockSession = getUnlockSessionFromReq(req);
    if (!unlockSession && req?.headers?.cookie && CONFIG.sessionSecret) {
      res.setHeader("Set-Cookie", clearUnlockCookie());
    }
    textResponse(
      res,
      200,
      renderVaultPage(locale, {
        signed: Boolean(unlockSession),
        unlockedAddress: unlockSession?.addr || null,
      }, copyOverrides),
      "text/html; charset=utf-8",
    );
    return true;
  }
  if (routePath === "/forge") {
    const unlockSession = getUnlockSessionFromReq(req);
    if (!unlockSession && req?.headers?.cookie && CONFIG.sessionSecret) {
      res.setHeader("Set-Cookie", clearUnlockCookie());
    }
    textResponse(
      res,
      200,
      renderForgePage(locale, {
        signed: Boolean(unlockSession),
        unlockedAddress: unlockSession?.addr || null,
      }, copyOverrides),
      "text/html; charset=utf-8",
    );
    return true;
  }
  if (routePath === "/game") {
    textResponse(res, 200, renderWorldGamePage(locale), "text/html; charset=utf-8");
    return true;
  }

  const normalized = normalizeAnalysisPath(routePath);
  const snapshotMatch = normalized.match(/^\/analysis\/([a-z0-9_-]+)\/snapshot\.svg$/i);
  if (snapshotMatch) {
    const slug = String(snapshotMatch[1] || "").trim().toLowerCase();
    const report = await fetchReportBySlug(slug);
    if (!report) {
      textResponse(res, 404, "snapshot_not_found");
      return true;
    }
    const snapshotSvg = String(report.snapshot_svg || "").trim() || buildSnapshotFallbackSvg(report, locale);
    res.writeHead(200, {
      "Content-Type": "image/svg+xml; charset=utf-8",
      "Cache-Control": "public, max-age=900, stale-while-revalidate=3600",
    });
    res.end(snapshotSvg);
    return true;
  }
  if (normalized === "/analysis") {
    const reports = await fetchReportsForIndex(500, locale);
    textResponse(res, 200, renderAnalysisIndexPage(locale, reports, copyOverrides), "text/html; charset=utf-8");
    return true;
  }
  if (normalized.startsWith("/analysis/")) {
    const slug = normalized.slice("/analysis/".length).trim().toLowerCase();
    const entry = await fetchReportBySlug(slug);
    if (!entry) {
      textResponse(res, 404, renderAnalysisNotFoundPage(locale, slug, copyOverrides), "text/html; charset=utf-8");
      return true;
    }
    const localePrefix = localeByPath ? `/${localeByPath}` : "";
    if (normalizeOuroborosLocale(entry.locale) !== locale) {
      const localized = await fetchReportByEventAndLocale(entry.event_id, locale);
      if (localized?.slug && localized.slug !== entry.slug) {
        res.writeHead(302, { Location: `${localePrefix}/analysis/${localized.slug}` });
        res.end();
        return true;
      }
    }
    const unlockSession = getUnlockSessionFromReq(req);
    if (!unlockSession && req?.headers?.cookie && CONFIG.sessionSecret) {
      res.setHeader("Set-Cookie", clearUnlockCookie());
    }
    textResponse(
      res,
      200,
      renderAnalysisDetailPage(locale, entry, {
        unlocked: Boolean(unlockSession),
        unlockedAddress: unlockSession?.addr || null,
      }, copyOverrides),
      "text/html; charset=utf-8",
    );
    return true;
  }

  goneResponse(res, pathname, locale, copyOverrides);
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
  const initialScriptJson = serializeJsonForScriptTag(initialState);

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

function renderWorldGamePage(locale = "en") {
  const lc = normalizeOuroborosLocale(locale);
  const isZhTw = lc === "zh-tw";
  const title = isZhTw ? "世界鍛造 | LeiMai Oracle" : "Worldforge | LeiMai Oracle";
  const description = isZhTw
    ? "以地圖座標驅動熵值演化與天道法則，進行語義創世與區域鎮定。"
    : "Semantic map game with entropy-driven world mutation and canonization protocol.";
  const ogDescription = isZhTw
    ? "點擊地圖座標，演化區域法則，解鎖月球與火星語義軌道。"
    : "Click map zones, evolve local laws, and unlock semantic orbit to Moon or Mars.";
  const localePrefix = isZhTw ? "/zh-tw" : "";
  const canonicalPath = `${localePrefix}/game`;
  const analysisHref = `${localePrefix}/analysis/`;

  const copy = isZhTw
    ? {
        hud_kicker: "WORLDFORGE / 即時區域",
        coordinates: "座標",
        entropy: "熵值",
        seed: "種子",
        status_init: "初始化地圖鍛造中...",
        back_oracle: "返回 Oracle",
        genesis_feed: "創世訊號",
        sovereign_cell: "主權區域",
        visual_theme: "視覺主題",
        narrative: "環境敘事",
        physical_rule: "物理規則",
        dev_task: "開發任務",
        heavenly_laws: "天道法則",
        collapse_warning: "現實崩塌警告",
        collapse_desc: "區域熵值已越過危險門檻，建議啟用定海神針鎖定 24 小時。",
        activate_canon: "啟用定海神針",
        orbit_standby: "語義軌道待命中。",
        canon_gateway: "定海神針閘門",
        close: "關閉",
        canon_desc: "請依指示轉帳 USDT，完成後將鎖定此區域 24 小時。",
        no_invoice: "尚未建立帳單。",
        check_canon: "檢查鎮定狀態",
        fallback_title: "3D 地圖不可用",
        fallback_desc: "目前缺少地圖金鑰，已切換為座標模式。輸入座標後仍可生成規則與進行區域鎮定。",
        fallback_lat: "緯度",
        fallback_lng: "經度",
        fallback_btn: "以座標進入創世",
      }
    : {
        hud_kicker: "WORLDFORGE / LIVE CELL",
        coordinates: "Coordinates",
        entropy: "Entropy",
        seed: "Seed",
        status_init: "Initializing map forge...",
        back_oracle: "Back to Oracle",
        genesis_feed: "GENESIS FEED",
        sovereign_cell: "The Sovereign Cell",
        visual_theme: "Visual Theme",
        narrative: "Environmental Narrative",
        physical_rule: "Physical Rule",
        dev_task: "Dev Task",
        heavenly_laws: "Heavenly Laws",
        collapse_warning: "Reality Collapse Warning",
        collapse_desc: "Entropy crossed danger threshold. Canonize this zone to lock mutation for 24h.",
        activate_canon: "Activate Canonization",
        orbit_standby: "Semantic orbit standby.",
        canon_gateway: "Canonization Gateway",
        close: "CLOSE",
        canon_desc: "Transfer the requested USDT amount to lock this zone for 24h.",
        no_invoice: "No invoice created.",
        check_canon: "Check Canonization Status",
        fallback_title: "3D Map Unavailable",
        fallback_desc: "Map token is missing. Fallback coordinate mode is active for gameplay.",
        fallback_lat: "Latitude",
        fallback_lng: "Longitude",
        fallback_btn: "Forge by Coordinates",
      };

  const runtimeI18n = isZhTw
    ? {
        no_law: "尚未生成法則。",
        unknown: "未知",
        status_fixed_until: "此區域已鎮定，鎖定至",
        status_mutation_threshold: "區域已達質劣變門檻，法則正在失穩。",
        status_collapse_warning: "現實崩塌警告，建議立即定海神針。",
        status_zone_synced: "區域同步完成。",
        status_forging: "正在鍛造區域法則...",
        invoice_label: "帳單",
        transfer_label: "轉帳",
        to_label: "收款地址",
        status_invoice_created: "帳單建立完成，等待鏈上確認...",
        status_canon_complete: "定海神針完成，24 小時內不再突變。",
        status_canon_poll_failed: "鎮定輪詢失敗",
        orbit_opened: "語義軌道已開啟",
        global_dev: "全球開發數",
        space_locked_need: "太空尚未解鎖，仍需",
        global_dev_count: "次全球開發",
        current: "目前",
        status_missing_mapbox: "缺少 Mapbox Token，請設定 MAPBOX_PUBLIC_TOKEN。",
        status_genesis_failed: "創世失敗",
        status_canon_invoice_failed: "定海神針帳單建立失敗",
        status_check_failed: "狀態檢查失敗",
        status_map_init_failed: "地圖初始化失敗",
        status_fallback_active: "地圖備援模式啟用，可用座標繼續遊玩。",
      }
    : {};

  const payload = {
    mapboxToken: CONFIG.mapboxPublicToken,
    entropyWarn: CONFIG.worldEntropyWarn,
    entropyMutate: CONFIG.worldEntropyMutate,
    spaceZoomGate: CONFIG.spaceZoomGate,
    defaultLat: 25.033,
    defaultLng: 121.5654,
    defaultZoom: 11.8,
    earthStyle: WORLDFORGE_EARTH_STYLE,
    starStyle: WORLDFORGE_STARS_STYLE,
    i18n: runtimeI18n,
  };
  const bootstrap = serializeJsonForScriptTag(payload);
  return `<!doctype html>
<html lang="${escapeHtml(isZhTw ? "zh-Hant" : "en")}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(title)}</title>
  <meta name="description" content="${escapeHtml(description)}">
  <meta name="theme-color" content="#090909">
  <meta name="robots" content="index,follow">
  <meta property="og:type" content="website">
  <meta property="og:title" content="${escapeHtml(title)}">
  <meta property="og:description" content="${escapeHtml(ogDescription)}">
  <meta property="og:url" content="${escapeHtml(ROOT_CANONICAL_URL)}${escapeHtml(canonicalPath.replace(/^\/+/, ""))}">
  <link rel="canonical" href="${escapeHtml(ROOT_CANONICAL_URL)}${escapeHtml(canonicalPath.replace(/^\/+/, ""))}">
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://api.mapbox.com/mapbox-gl-js/v3.6.0/mapbox-gl.css" rel="stylesheet">
  <link rel="stylesheet" href="/assets/game.css">
</head>
<body>
  <div id="worldRoot">
    <div id="worldMap" aria-label="Worldforge Map"></div>
    <div id="mapFallback" class="hud-panel absolute bottom-6 left-1/2 z-30 hidden w-[min(680px,95vw)] -translate-x-1/2 rounded-xl p-4">
      <div class="text-sm font-semibold text-amber-200">${escapeHtml(copy.fallback_title)}</div>
      <p class="mt-1 text-xs text-zinc-300">${escapeHtml(copy.fallback_desc)}</p>
      <div class="mt-3 grid grid-cols-1 gap-2 md:grid-cols-5">
        <label class="md:col-span-2 text-xs text-zinc-200">${escapeHtml(copy.fallback_lat)}
          <input id="fallbackLat" class="mt-1 w-full rounded border border-zinc-600 bg-zinc-900/70 px-2 py-2 text-sm text-zinc-100" value="25.033" />
        </label>
        <label class="md:col-span-2 text-xs text-zinc-200">${escapeHtml(copy.fallback_lng)}
          <input id="fallbackLng" class="mt-1 w-full rounded border border-zinc-600 bg-zinc-900/70 px-2 py-2 text-sm text-zinc-100" value="121.5654" />
        </label>
        <button id="fallbackForgeBtn" class="md:col-span-1 rounded border border-violet-500/50 bg-violet-900/35 px-3 py-2 text-sm text-violet-100 hover:bg-violet-800/45">
          ${escapeHtml(copy.fallback_btn)}
        </button>
      </div>
    </div>

    <aside class="hud-panel absolute left-4 top-4 z-20 w-[320px] rounded-xl p-4">
      <div class="text-xs tracking-[0.25em] text-zinc-400">${escapeHtml(copy.hud_kicker)}</div>
      <div class="mt-2 text-lg font-semibold text-amber-200">${escapeHtml(copy.coordinates)}</div>
      <div id="coordLabel" class="text-sm text-zinc-100">0.000000, 0.000000</div>
      <div class="mt-3 grid grid-cols-2 gap-2">
        <div class="rounded-md border border-zinc-700/60 bg-zinc-900/50 p-2">
          <div class="text-[11px] uppercase text-zinc-400">${escapeHtml(copy.entropy)}</div>
          <div id="entropyLabel" class="text-xl font-semibold entropy-low">0.000</div>
        </div>
        <div class="rounded-md border border-zinc-700/60 bg-zinc-900/50 p-2">
          <div class="text-[11px] uppercase text-zinc-400">${escapeHtml(copy.seed)}</div>
          <div id="zoneSeed" class="truncate text-sm text-zinc-200">-</div>
        </div>
      </div>
      <div id="statusLine" class="mt-3 text-sm text-amber-300">${escapeHtml(copy.status_init)}</div>
      <a class="mt-4 inline-block text-xs text-zinc-400 underline hover:text-zinc-200" href="${escapeHtml(analysisHref)}">${escapeHtml(copy.back_oracle)}</a>
    </aside>

    <aside class="hud-panel absolute right-4 top-4 z-20 flex h-[calc(100%-2rem)] w-[min(420px,92vw)] flex-col rounded-xl p-4">
      <div class="text-xs tracking-[0.25em] text-violet-300">${escapeHtml(copy.genesis_feed)}</div>
      <h1 class="mt-2 text-2xl font-semibold text-amber-100">${escapeHtml(copy.sovereign_cell)}</h1>
      <div class="mt-4 space-y-3 overflow-y-auto pr-1">
        <section class="rounded-md border border-amber-400/30 bg-black/30 p-3">
          <div class="text-xs uppercase text-amber-300">${escapeHtml(copy.visual_theme)}</div>
          <div id="visualTheme" class="mt-1 text-sm text-zinc-100">-</div>
        </section>
        <section class="rounded-md border border-violet-400/35 bg-black/30 p-3">
          <div class="text-xs uppercase text-violet-300">${escapeHtml(copy.narrative)}</div>
          <div id="narrativeText" class="mt-1 text-sm text-zinc-100">-</div>
        </section>
        <section class="rounded-md border border-zinc-600/70 bg-black/30 p-3">
          <div class="text-xs uppercase text-zinc-300">${escapeHtml(copy.physical_rule)}</div>
          <div id="physicalRule" class="mt-1 text-sm text-zinc-100">-</div>
        </section>
        <section class="rounded-md border border-zinc-600/70 bg-black/30 p-3">
          <div class="text-xs uppercase text-zinc-300">${escapeHtml(copy.dev_task)}</div>
          <div id="devTask" class="mt-1 text-sm text-zinc-100">-</div>
        </section>
        <section>
          <div class="mb-2 text-xs uppercase text-fuchsia-300">${escapeHtml(copy.heavenly_laws)}</div>
          <ul id="lawList" class="space-y-2"></ul>
        </section>
      </div>

      <section id="canonZone" class="canon-pulse mt-4 hidden rounded-lg border border-rose-500/40 bg-rose-950/35 p-3">
        <div class="text-sm font-semibold text-rose-200">${escapeHtml(copy.collapse_warning)}</div>
        <p class="mt-1 text-xs text-rose-100/85">${escapeHtml(copy.collapse_desc)}</p>
        <button id="canonBtn" class="mt-2 w-full rounded-md border border-rose-400/40 bg-rose-900/35 px-3 py-2 text-sm font-semibold text-rose-100 transition hover:bg-rose-800/45">
          ${escapeHtml(copy.activate_canon)}
        </button>
      </section>

      <section id="orbitBanner" class="orbit-banner mt-3 hidden rounded-md p-3 text-xs text-cyan-100">
        <div id="orbitText">${escapeHtml(copy.orbit_standby)}</div>
      </section>
    </aside>

    <div id="canonModal" class="canon-modal absolute inset-0 z-40 hidden items-center justify-center p-4">
      <div class="hud-panel w-full max-w-xl rounded-xl p-4">
        <div class="flex items-center justify-between">
          <h2 class="text-lg font-semibold text-amber-100">${escapeHtml(copy.canon_gateway)}</h2>
          <button id="canonClose" class="rounded border border-zinc-600 px-2 py-1 text-xs text-zinc-300 hover:text-zinc-100">${escapeHtml(copy.close)}</button>
        </div>
        <p class="mt-2 text-sm text-zinc-300">${escapeHtml(copy.canon_desc)}</p>
        <div id="canonInvoice" class="mt-3 rounded-md border border-zinc-700 bg-zinc-900/45 p-3 text-xs text-zinc-200">${escapeHtml(copy.no_invoice)}</div>
        <button id="canonCheck" class="mt-3 w-full rounded-md border border-amber-500/40 bg-amber-700/20 px-3 py-2 text-sm text-amber-100 hover:bg-amber-700/30">
          ${escapeHtml(copy.check_canon)}
        </button>
      </div>
    </div>
  </div>
  <script id="worldforge-data" type="application/json">${bootstrap}</script>
  <script src="https://api.mapbox.com/mapbox-gl-js/v3.6.0/mapbox-gl.js"></script>
  <script src="/assets/game.js"></script>
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
    const host = normalizeHostHeader(req.headers.host);
    const redirectUrl = buildLegacyRedirectUrl(reqUrl, host);
    if (redirectUrl) {
      res.writeHead(301, {
        Location: redirectUrl,
        "Cache-Control": "public, max-age=86400",
      });
      res.end();
      return;
    }
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
      triggerEntityProfilerForAddress(address);

      return jsonResponse(res, 200, {
        ok: true,
        address,
        unlock_expires_at_utc: new Date(expireSec * 1000).toISOString(),
      });
    }

    if (method === "POST" && pathname === "/api/v1/payment/create") {
      if (!checkRateLimit(req, "payment_create", CONFIG.rateLimitPerMinute)) {
        return jsonResponse(res, 429, { ok: false, error: "rate_limited" });
      }
      const session = getUnlockSessionFromReq(req);
      if (!session) {
        return jsonResponse(res, 401, { ok: false, error: "unlock_required" });
      }
      const body = await parseJsonBody(req).catch(() => ({}));
      const bodyAddress = String(body?.wallet_address || "").trim();
      const sessionAddress = toCanonicalAddress(session.addr || "");
      const providedAddress = bodyAddress ? toCanonicalAddress(bodyAddress) : sessionAddress;
      if (!sessionAddress || !providedAddress || providedAddress !== sessionAddress) {
        return jsonResponse(res, 400, { ok: false, error: "wallet_session_mismatch" });
      }
      const invoice = buildPaymentInvoiceRecord({
        walletAddress: providedAddress,
        slug: body?.slug || "vault",
        planCode: body?.plan_code || "sovereign",
        paymentRail: body?.payment_rail || "trc20_usdt",
      });
      const record = await recordPaymentInvoice(invoice);
      if (!record.ok) {
        return jsonResponse(res, 500, { ok: false, error: record.error || "payment_record_failed" });
      }
      return jsonResponse(res, 200, {
        ok: true,
        invoice_id: invoice.invoice_id,
        status: invoice.status,
        wallet_address: invoice.wallet_address,
        plan_code: invoice.plan_code,
        amount_usdt: invoice.amount_usdt,
        pay_to_address: invoice.pay_to_address,
        nonce: invoice.nonce,
        expires_at_utc: invoice.expires_at_utc,
        payment_rail: String(invoice?.meta?.payment_rail || "trc20_usdt"),
        l2_network: String(invoice?.meta?.l2_network || ""),
      });
    }

    if (method === "GET" && pathname === "/api/v1/payment/status") {
      if (!checkRateLimit(req, "payment_status", CONFIG.rateLimitPerMinute * 3)) {
        return jsonResponse(res, 429, { ok: false, error: "rate_limited" });
      }
      const session = getUnlockSessionFromReq(req);
      if (!session) {
        return jsonResponse(res, 401, { ok: false, error: "unlock_required" });
      }
      const invoiceId = String(searchParams.get("invoice_id") || "").trim();
      if (!invoiceId) {
        return jsonResponse(res, 400, { ok: false, error: "invoice_id_required" });
      }
      const status = await fetchPaymentInvoiceStatus({
        invoiceId,
        sessionAddress: session.addr || "",
      });
      if (!status.ok) {
        if (status.error === "invoice_not_found") {
          return jsonResponse(res, 404, { ok: false, error: status.error });
        }
        if (status.error === "wallet_session_mismatch") {
          return jsonResponse(res, 403, { ok: false, error: status.error });
        }
        if (status.error === "payment_storage_unavailable") {
          return jsonResponse(res, 500, { ok: false, error: status.error });
        }
        return jsonResponse(res, 400, { ok: false, error: status.error || "payment_status_failed" });
      }
      return jsonResponse(res, 200, { ok: true, ...status.invoice });
    }

    if ((method === "GET" || method === "POST") && pathname === "/api/genesis") {
      if (!checkRateLimit(req, "worldforge_genesis", CONFIG.rateLimitPerMinute * 3)) {
        return jsonResponse(res, 429, { ok: false, error: "rate_limited" });
      }
      let latRaw = searchParams.get("lat");
      let lngRaw = searchParams.get("lng");
      if (method === "POST") {
        const body = await parseJsonBody(req).catch(() => ({}));
        latRaw = body?.lat ?? latRaw;
        lngRaw = body?.lng ?? lngRaw;
      }
      const normalized = normalizeCoordinatePair(latRaw, lngRaw);
      if (!normalized.ok) {
        return jsonResponse(res, 400, { ok: false, error: normalized.error || "invalid_coordinates" });
      }
      const payload = await buildGenesisPayload({ lat: normalized.lat, lng: normalized.lng });
      if (!payload?.ok) {
        return jsonResponse(res, 500, { ok: false, error: "genesis_failed" });
      }
      return jsonResponse(res, 200, payload);
    }

    if (method === "GET" && pathname === "/api/space") {
      if (!checkRateLimit(req, "worldforge_space", CONFIG.rateLimitPerMinute * 3)) {
        return jsonResponse(res, 429, { ok: false, error: "rate_limited" });
      }
      const normalized = normalizeCoordinatePair(searchParams.get("lat"), searchParams.get("lng"));
      if (!normalized.ok) {
        return jsonResponse(res, 400, { ok: false, error: normalized.error || "invalid_coordinates" });
      }
      const zoom = Number(searchParams.get("zoom") || 0);
      const payload = await buildSpacePayload({
        lat: normalized.lat,
        lng: normalized.lng,
        zoom: Number.isFinite(zoom) ? zoom : 0,
      });
      return jsonResponse(res, 200, payload);
    }

    if (method === "POST" && pathname === "/api/canonize/create") {
      if (!checkRateLimit(req, "worldforge_canon_create", CONFIG.rateLimitPerMinute)) {
        return jsonResponse(res, 429, { ok: false, error: "rate_limited" });
      }
      const body = await parseJsonBody(req).catch(() => ({}));
      const seedHashInput = String(body?.seed_hash || "").trim().toLowerCase();
      let seedHash = seedHashInput;
      let normalized = null;
      if (body?.lat != null && body?.lng != null) {
        normalized = normalizeCoordinatePair(body.lat, body.lng);
        if (!normalized.ok) {
          return jsonResponse(res, 400, { ok: false, error: normalized.error || "invalid_coordinates" });
        }
      }
      if (!seedHash && normalized?.ok) {
        seedHash = seedHashFromCell(
          normalized.lat,
          normalized.lng,
          CONFIG.worldCellDecimals,
          CONFIG.sessionSecret || "worldforge-v1",
        ).seedHash;
      }
      if (!seedHash) {
        return jsonResponse(res, 400, { ok: false, error: "seed_hash_required" });
      }

      const exists = await fetchWorldEntityBySeed(seedHash);
      if ((!exists.ok || !exists.row) && normalized?.ok) {
        await buildGenesisPayload({ lat: normalized.lat, lng: normalized.lng });
      }

      const invoice = buildCanonizationInvoiceRecord({
        seedHash,
        paymentRail: body?.payment_rail || CONFIG.canonizationRail,
      });
      const recorded = await recordPaymentInvoice(invoice);
      if (!recorded.ok) {
        return jsonResponse(res, 500, { ok: false, error: recorded.error || "canon_invoice_failed" });
      }
      return jsonResponse(res, 200, {
        ok: true,
        seed_hash: seedHash,
        invoice_id: invoice.invoice_id,
        status: invoice.status,
        amount_usdt: invoice.amount_usdt,
        pay_to_address: invoice.pay_to_address,
        expires_at_utc: invoice.expires_at_utc,
        payment_rail: String(invoice?.meta?.payment_rail || CONFIG.canonizationRail),
      });
    }

    if (method === "GET" && pathname === "/api/canonize/confirm") {
      if (!checkRateLimit(req, "worldforge_canon_confirm", CONFIG.rateLimitPerMinute * 4)) {
        return jsonResponse(res, 429, { ok: false, error: "rate_limited" });
      }
      const invoiceId = String(searchParams.get("invoice_id") || "").trim();
      if (!invoiceId) {
        return jsonResponse(res, 400, { ok: false, error: "invoice_id_required" });
      }
      const invoiceRead = await fetchPaymentInvoiceLoose(invoiceId);
      if (!invoiceRead.ok) {
        return jsonResponse(res, 404, { ok: false, error: invoiceRead.error || "invoice_not_found" });
      }
      const invoice = invoiceRead.invoice || {};
      const meta = invoice.meta && typeof invoice.meta === "object" ? invoice.meta : {};
      const seedHash = String(searchParams.get("seed_hash") || meta.seed_hash || "").trim().toLowerCase();
      if (!seedHash) {
        return jsonResponse(res, 400, { ok: false, error: "seed_hash_required" });
      }
      if (String(invoice.status || "pending") !== "paid") {
        return jsonResponse(res, 200, {
          ok: true,
          fixed: false,
          status: String(invoice.status || "pending"),
          seed_hash: seedHash,
          invoice_id: invoiceId,
        });
      }
      const fixed = await applyCanonizationFix(seedHash);
      if (!fixed.ok) {
        return jsonResponse(res, 500, { ok: false, error: fixed.error || "canonization_failed" });
      }
      return jsonResponse(res, 200, {
        ok: true,
        fixed: true,
        status: "paid",
        seed_hash: seedHash,
        invoice_id: invoiceId,
        fixed_until: fixed.fixed_until,
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
      return textResponse(res, 200, buildSitemap(ROOT_CANONICAL_URL.replace(/\/+$/, "")), "application/xml; charset=utf-8");
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
      const locale = normalizeOuroborosLocale(searchParams.get("lang") || "en");
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
      const locale = normalizeOuroborosLocale(searchParams.get("lang") || "en");
      const { chainState, appState } = await readStates();
      const board = buildLeaderboard(chainState, appState, { minAmount: CONFIG.minAmount, limit: 20 });
      const ads = extractAds(appState, { limit: 3 });
      return jsonResponse(res, 200, {
        ok: true,
        payload: buildKnowledgePayload(locale, board.rows, board.king, ads),
      });
    }

    if (method === "GET" && pathname === "/api/v1/growth/scoreboard") {
      const payload = await readJsonFileSafe(GROWTH_SCOREBOARD_PATH, {});
      const overrides = await readJsonFileSafe(GROWTH_OVERRIDES_PATH, {});
      return jsonResponse(res, 200, {
        ok: true,
        scoreboard: payload,
        active_variant_id: String(overrides?.variant_id || "control"),
      });
    }

    if (method === "GET" && pathname === "/api/v1/growth/actions") {
      const limit = Math.min(Math.max(1, Number(searchParams.get("limit") || 50)), 200);
      const actions = await readJsonLinesSafe(GROWTH_ACTIONS_PATH, limit);
      return jsonResponse(res, 200, {
        ok: true,
        count: actions.length,
        actions,
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
      const locale = normalizeOuroborosLocale(searchParams.get("lang") || "en");
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

