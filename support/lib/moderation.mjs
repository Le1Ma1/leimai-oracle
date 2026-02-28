import crypto from "node:crypto";

const DECLARATION_TYPES = new Set(["personal", "ad"]);

function cleanText(text) {
  return String(text || "")
    .replace(/\s+/g, " ")
    .trim();
}

function hasBlockedKeyword(text, keywords) {
  const hay = cleanText(text).toLowerCase();
  for (const kw of keywords || []) {
    const needle = String(kw || "").trim().toLowerCase();
    if (!needle) continue;
    if (hay.includes(needle)) return needle;
  }
  return null;
}

function isWalletBlocked(wallet, blocked) {
  const w = String(wallet || "").trim().toLowerCase();
  if (!w) return false;
  return (blocked || []).some((item) => String(item || "").trim().toLowerCase() === w);
}

export function validateDeclarationPayload(payload, config) {
  const tx_hash = cleanText(payload?.tx_hash).toLowerCase();
  const wallet = cleanText(payload?.wallet);
  const content = cleanText(payload?.content);
  const lang = cleanText(payload?.lang || "en").toLowerCase();
  const type = cleanText(payload?.type || "personal").toLowerCase();
  const maxLen = Number(config.declarationMaxLength || 280);

  if (!tx_hash || tx_hash.length < 8) {
    return { ok: false, error: "invalid_tx_hash" };
  }
  if (!content || content.length < 8) {
    return { ok: false, error: "content_too_short" };
  }
  if (content.length > maxLen) {
    return { ok: false, error: "content_too_long" };
  }
  if (!DECLARATION_TYPES.has(type)) {
    return { ok: false, error: "invalid_declaration_type" };
  }
  if (!["en", "zh-tw", "zh-cn"].includes(lang)) {
    return { ok: false, error: "invalid_lang" };
  }
  return { ok: true, data: { tx_hash, wallet, content, lang, type } };
}

export function moderateDeclaration(payload, appState) {
  const blockedWallets = appState?.blacklist?.wallets || [];
  const blockedKeywords = appState?.blacklist?.keywords || [];

  if (isWalletBlocked(payload.wallet, blockedWallets)) {
    return { ok: false, error: "wallet_blocked" };
  }
  const keyword = hasBlockedKeyword(payload.content, blockedKeywords);
  if (keyword) {
    return { ok: false, error: `keyword_blocked:${keyword}` };
  }
  return { ok: true };
}

export function createDeclarationRecord(payload, txReceipt) {
  const now = new Date().toISOString();
  return {
    id: `dec_${crypto.randomUUID().replace(/-/g, "").slice(0, 16)}`,
    tx_hash: payload.tx_hash,
    wallet: payload.wallet || txReceipt?.from_addr || "",
    lang: payload.lang,
    type: payload.type,
    content: payload.content,
    status: "pending",
    review_note: "",
    created_at_utc: now,
    updated_at_utc: now,
  };
}
