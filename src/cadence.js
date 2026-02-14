const TF_TO_MS = {
  "1m": 60 * 1000,
  "5m": 5 * 60 * 1000,
  "15m": 15 * 60 * 1000,
  "1h": 60 * 60 * 1000,
  "4h": 4 * 60 * 60 * 1000,
  "1d": 24 * 60 * 60 * 1000,
};

const FREE_CADENCE_MS = 6 * 60 * 60 * 1000;

function floorToBucket(nowMs, bucketMs) {
  return Math.floor(nowMs / bucketMs) * bucketMs;
}

function toIso(ms) {
  return new Date(ms).toISOString();
}

function getFreeSnapshotTimestamp(nowMs) {
  return toIso(floorToBucket(nowMs, FREE_CADENCE_MS));
}

function getCadenceMsByTf(tf) {
  return TF_TO_MS[tf];
}

function getProEliteSnapshotTimestamp(tf, nowMs) {
  const cadenceMs = getCadenceMsByTf(tf);
  if (!cadenceMs) {
    throw new Error(`Unsupported tf: ${tf}`);
  }
  return toIso(floorToBucket(nowMs, cadenceMs));
}

function resolveSnapshotTimestamp({ tier, tf, nowMs }) {
  const normalizedTier = String(tier || "free").toLowerCase();
  if (normalizedTier === "pro" || normalizedTier === "elite") {
    return getProEliteSnapshotTimestamp(tf, nowMs);
  }
  return getFreeSnapshotTimestamp(nowMs);
}

module.exports = {
  FREE_CADENCE_MS,
  TF_TO_MS,
  getCadenceMsByTf,
  getFreeSnapshotTimestamp,
  getProEliteSnapshotTimestamp,
  resolveSnapshotTimestamp,
};
