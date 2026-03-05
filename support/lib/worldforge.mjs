import { createHmac } from "node:crypto";

export function clamp(value, min, max) {
  const n = Number(value);
  if (!Number.isFinite(n)) return min;
  return Math.max(min, Math.min(max, n));
}

export function clamp01(value) {
  return clamp(value, 0, 1);
}

export function normalizeCoordinatePair(latRaw, lngRaw) {
  const lat = Number(latRaw);
  const lng = Number(lngRaw);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
    return { ok: false, error: "invalid_coordinates" };
  }
  if (lat < -90 || lat > 90) {
    return { ok: false, error: "invalid_latitude" };
  }
  if (lng < -180 || lng > 180) {
    return { ok: false, error: "invalid_longitude" };
  }
  return { ok: true, lat, lng };
}

export function quantizeCoordinate(value, decimals = 3) {
  const scale = 10 ** Math.max(0, Number(decimals) || 0);
  return Math.round(Number(value) * scale) / scale;
}

export function wrapLng(value) {
  const lng = Number(value);
  if (!Number.isFinite(lng)) return 0;
  return ((((lng + 180) % 360) + 360) % 360) - 180;
}

export function quantizeCoordinates(lat, lng, decimals = 3) {
  return {
    lat: quantizeCoordinate(lat, decimals),
    lng: wrapLng(quantizeCoordinate(lng, decimals)),
  };
}

export function seedHashFromCell(lat, lng, decimals = 3, salt = "worldforge-v1") {
  const q = quantizeCoordinates(lat, lng, decimals);
  const cell = `${q.lat.toFixed(decimals)}:${q.lng.toFixed(decimals)}`;
  const digest = createHmac("sha256", String(salt || "worldforge-v1")).update(cell).digest("hex");
  return {
    seedHash: digest,
    cell,
    lat: q.lat,
    lng: q.lng,
  };
}

export function hashUnit(seedHash, offset = 0) {
  const safe = String(seedHash || "");
  const from = Math.max(0, Math.min(safe.length - 8, Number(offset) || 0));
  const slice = safe.slice(from, from + 8).padEnd(8, "0");
  const n = parseInt(slice, 16);
  if (!Number.isFinite(n)) return 0;
  return n / 0xffffffff;
}

export function baseEntropyFromSeed(seedHash) {
  return clamp01(0.22 + hashUnit(seedHash, 4) * 0.36);
}

function pickBySeed(seedHash, list, offset) {
  if (!Array.isArray(list) || !list.length) return "";
  const idx = Math.floor(hashUnit(seedHash, offset) * list.length) % list.length;
  return String(list[idx] || "");
}

export function buildRulesSummary(rules) {
  const src = rules && typeof rules === "object" ? rules : {};
  const parts = [
    String(src.visual_theme || "").trim(),
    String(src.narrative || "").trim(),
    String(src.physical_rule || "").trim(),
    String(src.dev_task || "").trim(),
  ].filter(Boolean);
  return parts.join(" | ").slice(0, 600);
}

export function buildFallbackGenesis({ seedHash, lat, lng, entropy, previousRule = "" }) {
  const themes = [
    "Crystalized signal dunes with obsidian fractures",
    "Neon-violet rust over a black-gold memory lattice",
    "Glitched aurora canopy above compressed data plains",
    "Monolithic mirror shards wrapped in quantum fog",
    "Fractal city ruins growing from magnetic dust",
  ];
  const narratives = [
    "A broken archive keeps replaying one future and deleting nine alternatives.",
    "Local clocks drift with market panic, making every choice feel pre-committed.",
    "An invisible choir of validators rewrites landscape permissions every dusk.",
    "Ancient autonomous agents harvest intent and leave only probability shadows.",
    "A failed settlement protocol became a self-aware weather system.",
  ];
  const ruleTemplates = [
    "Gravity scales with BTC 4h volatility. Higher volatility means lower jump arc.",
    "Forward movement speed decays when local entropy rises above 0.73.",
    "All projectiles curve toward the nearest unresolved task node.",
    "Healing is converted into map reveal radius when liquidation pressure spikes.",
    "Time dilation starts when two players share identical entropy signatures.",
  ];
  const taskTemplates = [
    "Stabilize three anomaly anchors without crossing the violet fault line.",
    "Collect mirrored fragments and reconcile conflicting event timelines.",
    "Decode the relay obelisk and publish one lawful patch to the zone.",
    "Escort a drifting memory shard to the nearest canonical beacon.",
    "Trade entropy between two adjacent cells until both fall below 0.62.",
  ];
  const lawTemplates = [
    "Nothing persists unless observed twice.",
    "Price and gravity are legally coupled in this district.",
    "Entropy is a tax on indecision.",
    "Canonized ground rejects mutation for one solar cycle.",
    "Unresolved tasks attract environmental hostility.",
    "Narrative coherence increases traversal speed.",
  ];
  const theme = pickBySeed(seedHash, themes, 6);
  const narrative = pickBySeed(seedHash, narratives, 12);
  const rule = pickBySeed(seedHash, ruleTemplates, 18);
  const task = pickBySeed(seedHash, taskTemplates, 24);
  const lawA = pickBySeed(seedHash, lawTemplates, 30);
  const lawB = pickBySeed(seedHash, lawTemplates, 36);
  const lawC = pickBySeed(seedHash, lawTemplates, 42);
  const prior = String(previousRule || "").trim();
  const combinedRule = prior ? `${rule} Previous law residue: ${prior.slice(0, 120)}.` : rule;
  const entropyText = Number.isFinite(Number(entropy)) ? Number(entropy).toFixed(3) : "0.500";
  return {
    visual_theme: theme,
    narrative: `${narrative} Coordinates ${Number(lat).toFixed(3)}, ${Number(lng).toFixed(3)}.`,
    physical_rule: `${combinedRule} [seed:${String(seedHash).slice(0, 10)}|e:${entropyText}]`,
    dev_task: task,
    heavenly_laws: [lawA, lawB, lawC].filter(Boolean),
    summary: `${theme}. ${narrative}. ${combinedRule}`.slice(0, 600),
  };
}

export function deriveSpaceStage(totalDevelopments, moonThreshold, marsThreshold) {
  const total = Math.max(0, Number(totalDevelopments) || 0);
  const moon = Math.max(1, Number(moonThreshold) || 500);
  const mars = Math.max(moon + 1, Number(marsThreshold) || 2000);
  if (total >= mars) {
    return { stage: "mars", unlocked: true, required: mars };
  }
  if (total >= moon) {
    return { stage: "moon", unlocked: true, required: moon };
  }
  return { stage: "earth", unlocked: false, required: moon };
}

export function buildSemanticOrbit({ lat, lng, target, points = 24 }) {
  const n = Math.max(8, Math.min(96, Number(points) || 24));
  const baseLat = Number(lat);
  const baseLng = Number(lng);
  const radiusLat = target === "mars" ? 12.5 : 7.5;
  const radiusLng = target === "mars" ? 26 : 16;
  const out = [];
  for (let i = 0; i < n; i += 1) {
    const t = (Math.PI * 2 * i) / n;
    const pLat = clamp(baseLat + Math.cos(t) * radiusLat, -85, 85);
    const pLng = wrapLng(baseLng + Math.sin(t) * radiusLng);
    out.push({
      order: i + 1,
      lat: Number(pLat.toFixed(6)),
      lng: Number(pLng.toFixed(6)),
    });
  }
  return out;
}

export function toVectorLiteral(values) {
  if (!Array.isArray(values) || values.length === 0) return null;
  const normalized = values
    .map((v) => Number(v))
    .filter((v) => Number.isFinite(v))
    .map((v) => Number(v.toFixed(6)));
  if (!normalized.length) return null;
  return `[${normalized.join(",")}]`;
}

