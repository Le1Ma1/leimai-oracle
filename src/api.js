const { randomUUID } = require("node:crypto");

const {
  FEE_ASSUMPTION,
  METHOD_VERSION,
  MODALITY,
  SLIPPAGE_ASSUMPTION,
  UNIVERSE,
} = require("./constants");
const { resolveSnapshotTimestamp } = require("./cadence");
const { stripLockedData } = require("./denylist");
const {
  parseModality,
  parseTf,
  parseVariant,
  parseWindow,
} = require("./validators");
const { chooseBestVariant, getVariantSet, validateTuple } = require("./variant");

function parseSymbol(rawValue) {
  if (rawValue === undefined || rawValue === null || rawValue === "") {
    return UNIVERSE[0];
  }
  if (!UNIVERSE.includes(rawValue)) {
    return null;
  }
  return rawValue;
}

function parseTier(rawValue) {
  if (rawValue === undefined || rawValue === null || rawValue === "") {
    return "free";
  }
  const normalized = String(rawValue).toLowerCase();
  return ["free", "pro", "elite", "buyout"].includes(normalized)
    ? normalized
    : "free";
}

function createErrorEnvelope(errorCode, message, status = 400) {
  return stripLockedData({
    status,
    payload: {
      error_code: errorCode,
      message,
      request_id: randomUUID(),
      timestamp: new Date().toISOString(),
    },
  });
}

function buildIndexAssetBlocks({ symbol, tf, window, methodVersion, modality, timestamp }) {
  return {
    ranking_slice: {
      symbol,
      tf,
      window,
    },
    methodology_summary: {
      method_version: methodVersion,
      modality,
    },
    period_stats: {
      window,
      tf,
      snapshot_timestamp: timestamp,
    },
  };
}

function buildEntryAssetBlocks({
  proofId,
  methodVersion,
  timestamp,
  variantSet,
}) {
  return {
    instrument_metrics: {
      long: {
        risk_adjusted_score: variantSet.long.risk_adjusted_score,
        roi_score: variantSet.long.roi_score,
      },
      short: {
        risk_adjusted_score: variantSet.short.risk_adjusted_score,
        roi_score: variantSet.short.roi_score,
      },
      long_short: {
        risk_adjusted_score: variantSet.long_short.risk_adjusted_score,
        roi_score: variantSet.long_short.roi_score,
      },
    },
    variant_comparison: {
      long: variantSet.long.risk_adjusted_score,
      short: variantSet.short.risk_adjusted_score,
      long_short: variantSet.long_short.risk_adjusted_score,
    },
    timestamped_proof_fields: {
      proof_id: proofId,
      method_version: methodVersion,
      timestamp,
    },
  };
}

function buildRankingsLikePayload(query, now = new Date(), endpointType = "rankings") {
  const variant = parseVariant(query.variant);
  const tf = parseTf(query.tf);
  const window = parseWindow(query.window);
  const symbol = parseSymbol(query.symbol);
  const modality = parseModality(query.modality);
  const tier = parseTier(query.tier);

  if (!variant) {
    return createErrorEnvelope(
      "BAD_REQUEST",
      "variant must be one of: long, short, long_short",
      400
    );
  }
  if (!tf) {
    return createErrorEnvelope("BAD_REQUEST", "invalid tf", 400);
  }
  if (!window) {
    return createErrorEnvelope("BAD_REQUEST", "invalid window", 400);
  }
  if (!symbol) {
    return createErrorEnvelope("BAD_REQUEST", "invalid symbol", 400);
  }
  if (!modality) {
    return createErrorEnvelope("BAD_REQUEST", "invalid modality", 400);
  }

  const tupleError = validateTuple({ symbol, tf, window, modality });
  if (tupleError) {
    return createErrorEnvelope("BAD_REQUEST", tupleError, 400);
  }

  const variantSet = getVariantSet({ symbol, tf, window, modality });
  const bestVariant = chooseBestVariant(variantSet);
  const snapshotTimestamp = resolveSnapshotTimestamp({
    tier,
    tf,
    nowMs: now.getTime(),
  });

  const selectedMetrics = variantSet[variant];
  const bestMetrics = variantSet[bestVariant];
  const proofId = `${symbol}|${tf}|${window}|${modality}|${snapshotTimestamp}`;

  const payload = {
    proof_id: proofId,
    method_version: METHOD_VERSION,
    tf,
    window,
    modality,
    variant,
    risk_adjusted_score: selectedMetrics.risk_adjusted_score,
    roi_score: selectedMetrics.roi_score,
    drawdown: selectedMetrics.drawdown,
    trade_count: selectedMetrics.trade_count,
    best_variant: bestVariant,
    best_variant_scores: {
      risk_adjusted_score: bestMetrics.risk_adjusted_score,
      roi_score: bestMetrics.roi_score,
      drawdown: bestMetrics.drawdown,
      trade_count: bestMetrics.trade_count,
    },
    fee_assumption: FEE_ASSUMPTION,
    slippage_assumption: SLIPPAGE_ASSUMPTION,
    timestamp: snapshotTimestamp,
  };

  if (endpointType === "rankings") {
    payload.asset_blocks = buildIndexAssetBlocks({
      symbol,
      tf,
      window,
      methodVersion: METHOD_VERSION,
      modality,
      timestamp: snapshotTimestamp,
    });
  } else if (endpointType === "summaries") {
    payload.asset_blocks = buildEntryAssetBlocks({
      proofId,
      methodVersion: METHOD_VERSION,
      timestamp: snapshotTimestamp,
      variantSet,
    });
  }

  return {
    status: 200,
    payload: stripLockedData(payload),
  };
}

function buildMethodologyPayload(now = new Date()) {
  return {
    status: 200,
    payload: stripLockedData({
      method_version: METHOD_VERSION,
      timestamp: now.toISOString(),
    }),
  };
}

function maybeRequireAuth(query, headers) {
  if (query.scope !== "private") {
    return null;
  }

  if (!headers["x-member-id"]) {
    return createErrorEnvelope(
      "UNAUTHORIZED",
      "member authentication is required",
      401
    );
  }

  return null;
}

module.exports = {
  buildMethodologyPayload,
  buildRankingsLikePayload,
  createErrorEnvelope,
  maybeRequireAuth,
};
