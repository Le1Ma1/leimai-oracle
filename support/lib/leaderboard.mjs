import { maskWallet } from "./storage.mjs";

function normalizeAmount(value) {
  const num = Number(value);
  if (!Number.isFinite(num) || num < 0) return 0;
  return num;
}

function extractApprovedDeclarationMap(appState) {
  const map = new Map();
  const declarations = Array.isArray(appState?.declarations) ? appState.declarations : [];
  for (const row of declarations) {
    if (!row || typeof row !== "object") continue;
    if (row.status !== "approved") continue;
    if (typeof row.tx_hash !== "string" || !row.tx_hash) continue;
    if (!map.has(row.tx_hash)) {
      map.set(row.tx_hash, row);
    }
  }
  return map;
}

function isVerifiedReceipt(row) {
  if (!row || typeof row !== "object") return false;
  return row.status === "verified";
}

export function buildLeaderboard(chainState, appState, options = {}) {
  const minAmount = Number.isFinite(Number(options.minAmount)) ? Number(options.minAmount) : 0;
  const limit = Number.isFinite(Number(options.limit)) ? Number(options.limit) : 100;
  const receipts = Array.isArray(chainState?.tx_receipts) ? chainState.tx_receipts : [];
  const declarationMap = extractApprovedDeclarationMap(appState);

  const rows = receipts
    .filter(isVerifiedReceipt)
    .filter((row) => normalizeAmount(row.amount) >= minAmount)
    .map((row) => {
      const declaration = declarationMap.get(row.tx_hash) || null;
      return {
        tx_hash: row.tx_hash,
        chain: row.chain || "TRON",
        token: row.token || "USDT",
        amount_usdt: normalizeAmount(row.amount),
        from_addr: row.from_addr || "",
        to_addr: row.to_addr || "",
        wallet_masked: maskWallet(row.from_addr || ""),
        confirmed_at_utc: row.confirmed_at_utc || null,
        confirmations: Number(row.confirmations || 0),
        source: row.source || "unknown",
        declaration: declaration
          ? {
              id: declaration.id,
              type: declaration.type,
              content: declaration.content,
              lang: declaration.lang,
            }
          : null,
      };
    })
    .sort((a, b) => {
      if (b.amount_usdt !== a.amount_usdt) return b.amount_usdt - a.amount_usdt;
      const aTs = Date.parse(a.confirmed_at_utc || "") || 0;
      const bTs = Date.parse(b.confirmed_at_utc || "") || 0;
      return aTs - bTs;
    })
    .slice(0, limit)
    .map((row, idx) => ({ ...row, rank: idx + 1, is_king: idx === 0 }));

  const king = rows.length > 0 ? rows[0] : null;
  return { rows, king };
}

export function extractAds(appState, options = {}) {
  const limit = Number.isFinite(Number(options.limit)) ? Number(options.limit) : 3;
  const declarations = Array.isArray(appState?.declarations) ? appState.declarations : [];
  const rows = declarations
    .filter((row) => row && typeof row === "object")
    .filter((row) => row.status === "approved" && row.type === "ad")
    .sort((a, b) => {
      const aTs = Date.parse(a.updated_at_utc || a.created_at_utc || "") || 0;
      const bTs = Date.parse(b.updated_at_utc || b.created_at_utc || "") || 0;
      return bTs - aTs;
    })
    .slice(0, limit)
    .map((row, idx) => ({
      slot: idx + 1,
      declaration_id: row.id,
      tx_hash: row.tx_hash,
      wallet_masked: maskWallet(row.wallet || row.from_addr || ""),
      content: row.content,
      lang: row.lang || "en",
      updated_at_utc: row.updated_at_utc || row.created_at_utc || null,
    }));

  return {
    total_slots: limit,
    used_slots: rows.length,
    available_slots: Math.max(0, limit - rows.length),
    rows,
  };
}

export function summarizeCounts(chainState, appState, leaderboard) {
  const receipts = Array.isArray(chainState?.tx_receipts) ? chainState.tx_receipts : [];
  const declarations = Array.isArray(appState?.declarations) ? appState.declarations : [];
  const verifiedCount = receipts.filter((row) => row?.status === "verified").length;
  const pendingDecl = declarations.filter((row) => row?.status === "pending").length;
  return {
    tx_total: receipts.length,
    tx_verified: verifiedCount,
    declarations_total: declarations.length,
    declarations_pending: pendingDecl,
    leaderboard_entries: Array.isArray(leaderboard?.rows) ? leaderboard.rows.length : 0,
  };
}
