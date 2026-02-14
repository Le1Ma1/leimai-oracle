const { createHash } = require("node:crypto");

const {
  MODALITY,
  TIMEFRAMES,
  UNIVERSE,
  VARIANTS,
  VARIANT_TIEBREAK_PRIORITY,
  WINDOWS,
} = require("./constants");

function hashU32(input) {
  const digest = createHash("sha256").update(input, "utf8").digest();
  return digest.readUInt32BE(0);
}

function toScore(value, divisor) {
  return Number((value / divisor).toFixed(6));
}

function generateVariantMetrics(symbol, tf, window, modality, variant) {
  const key = `${symbol}|${tf}|${window}|${modality}|${variant}`;
  const riskRaw = hashU32(`${key}|risk`) % 250000; // 0..249999
  const roiRaw = hashU32(`${key}|roi`) % 200001; // 0..200000
  const drawRaw = hashU32(`${key}|draw`) % 50001; // 0..50000
  const tradesRaw = hashU32(`${key}|trades`) % 5000; // 0..4999

  return {
    risk_adjusted_score: toScore(100000 + riskRaw, 100000),
    roi_score: toScore(roiRaw - 100000, 100000),
    drawdown: toScore(1000 + drawRaw, 100000),
    trade_count: tradesRaw + 1,
    // Internal-only field, used to validate recursive denylist enforcement.
    locked_data: {
      internal_key: "never_public",
    },
  };
}

function getVariantSet({ symbol, tf, window, modality = MODALITY }) {
  return {
    long: generateVariantMetrics(symbol, tf, window, modality, "long"),
    short: generateVariantMetrics(symbol, tf, window, modality, "short"),
    long_short: generateVariantMetrics(symbol, tf, window, modality, "long_short"),
  };
}

function compareVariantMetrics(leftVariant, left, rightVariant, right) {
  if (left.risk_adjusted_score !== right.risk_adjusted_score) {
    return left.risk_adjusted_score - right.risk_adjusted_score;
  }

  if (left.drawdown !== right.drawdown) {
    return right.drawdown - left.drawdown;
  }

  if (left.trade_count !== right.trade_count) {
    return left.trade_count - right.trade_count;
  }

  return (
    VARIANT_TIEBREAK_PRIORITY[leftVariant] -
    VARIANT_TIEBREAK_PRIORITY[rightVariant]
  );
}

function chooseBestVariant(variantSet) {
  let winner = VARIANTS[0];
  for (const candidate of VARIANTS.slice(1)) {
    if (
      compareVariantMetrics(
        candidate,
        variantSet[candidate],
        winner,
        variantSet[winner]
      ) > 0
    ) {
      winner = candidate;
    }
  }
  return winner;
}

function validateTuple({ symbol, tf, window, modality }) {
  if (!UNIVERSE.includes(symbol)) {
    return `Invalid symbol: ${symbol}`;
  }
  if (!TIMEFRAMES.includes(tf)) {
    return `Invalid tf: ${tf}`;
  }
  if (!WINDOWS.includes(window)) {
    return `Invalid window: ${window}`;
  }
  if (modality !== MODALITY) {
    return `Invalid modality: ${modality}`;
  }
  return null;
}

module.exports = {
  chooseBestVariant,
  getVariantSet,
  validateTuple,
};
