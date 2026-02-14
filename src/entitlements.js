const TIER_FEATURES = {
  free: new Set(["single_indicator_snapshot"]),
  pro: new Set([
    "single_indicator_snapshot",
    "realtime_signal",
    "push",
    "combo_xy",
  ]),
  elite: new Set([
    "single_indicator_snapshot",
    "realtime_signal",
    "push",
    "combo_xy",
    "combo_3plus",
    "advanced_features",
  ]),
  buyout: new Set(["exclusive_seat"]),
};

function normalizeTier(tier) {
  const normalized = String(tier || "free").toLowerCase();
  return TIER_FEATURES[normalized] ? normalized : null;
}

function checkEntitlement(input) {
  const normalizedTier = normalizeTier(input.tier);
  if (!normalizedTier) {
    return {
      allowed: false,
      reason: "UNKNOWN_TIER",
      member_id: input.member_id,
    };
  }

  const features = TIER_FEATURES[normalizedTier];
  return {
    allowed: features.has(input.feature),
    reason: features.has(input.feature) ? "ALLOWED" : "DENIED_BY_TIER",
    member_id: input.member_id,
    tier: normalizedTier,
  };
}

module.exports = {
  TIER_FEATURES,
  checkEntitlement,
  normalizeTier,
};
