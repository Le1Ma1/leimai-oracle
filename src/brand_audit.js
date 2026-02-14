const path = require("node:path");

const LOGO_SOT = path.resolve(process.cwd(), "logo.png");
const SIGNATURE_SOT = path.resolve(process.cwd(), "signature.jpg");

const SIGNATURE_ALLOWED_SURFACES = new Set([
  "proof_card",
  "buyout_certificate",
  "report_cover",
  "report_end",
  "footer",
]);

const SIGNATURE_PROHIBITED_SURFACES = new Set([
  "header",
  "nav",
  "every_card",
  "rankings_list_card",
]);

function normalizePath(p) {
  return path.resolve(process.cwd(), p);
}

function auditBrandSourceOfTruth(sources) {
  const normalized = {
    logo: normalizePath(sources.logo),
    signature: normalizePath(sources.signature),
  };
  return {
    pass:
      normalized.logo === LOGO_SOT && normalized.signature === SIGNATURE_SOT,
    expected: {
      logo: LOGO_SOT,
      signature: SIGNATURE_SOT,
    },
    actual: normalized,
  };
}

function auditLogoUsage(usageList) {
  const violations = [];
  for (const usage of usageList) {
    if (usage.distorted) {
      violations.push(`${usage.id}:distorted`);
    }
    if (usage.recolored_unapproved) {
      violations.push(`${usage.id}:recolor`);
    }
    if (!usage.contrast_ok) {
      violations.push(`${usage.id}:contrast`);
    }
  }
  return {
    pass: violations.length === 0,
    violations,
  };
}

function auditSignaturePlacements(placements) {
  const violations = [];
  for (const placement of placements) {
    if (SIGNATURE_PROHIBITED_SURFACES.has(placement.surface)) {
      violations.push(`${placement.id}:prohibited_surface`);
      continue;
    }
    if (!SIGNATURE_ALLOWED_SURFACES.has(placement.surface)) {
      violations.push(`${placement.id}:unknown_surface`);
    }
  }
  return {
    pass: violations.length === 0,
    violations,
  };
}

module.exports = {
  LOGO_SOT,
  SIGNATURE_SOT,
  SIGNATURE_ALLOWED_SURFACES,
  SIGNATURE_PROHIBITED_SURFACES,
  auditBrandSourceOfTruth,
  auditLogoUsage,
  auditSignaturePlacements,
};
