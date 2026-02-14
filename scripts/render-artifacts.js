const fs = require("node:fs");
const path = require("node:path");

const {
  LOGO_SOT,
  SIGNATURE_SOT,
  auditBrandSourceOfTruth,
  auditLogoUsage,
  auditSignaturePlacements,
} = require("../src/brand_audit");
const { getRankingsUiState } = require("../src/rankings_ui");
const { generateProofCardSpec, renderLogoMarkFromSource, renderProofCardArtifacts } = require("../src/proofcard");
const { getVariantSet } = require("../src/variant");

function writeJson(filePath, data) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2), "utf8");
}

function renderArtifacts() {
  const artifactRoot = path.join(process.cwd(), "artifacts");
  const brandDir = path.join(artifactRoot, "brand");
  const proofDir = path.join(artifactRoot, "proofcard");
  const uiDir = path.join(artifactRoot, "ui");

  fs.mkdirSync(brandDir, { recursive: true });
  fs.mkdirSync(proofDir, { recursive: true });
  fs.mkdirSync(uiDir, { recursive: true });

  const brandSotReport = auditBrandSourceOfTruth({
    logo: "logo.png",
    signature: "signature.jpg",
  });
  writeJson(path.join(brandDir, "sot_audit.json"), brandSotReport);

  const logoUsageReport = auditLogoUsage([
    {
      id: "primary-home",
      form: "primary",
      distorted: false,
      recolored_unapproved: false,
      contrast_ok: true,
    },
    {
      id: "badge-share",
      form: "badge",
      distorted: false,
      recolored_unapproved: false,
      contrast_ok: true,
    },
    {
      id: "micro-favicon",
      form: "micro",
      distorted: false,
      recolored_unapproved: false,
      contrast_ok: true,
    },
  ]);
  writeJson(path.join(brandDir, "logo_usage_report.json"), logoUsageReport);

  const signaturePlacementReport = auditSignaturePlacements([
    { id: "proofcard", surface: "proof_card" },
    { id: "buyout", surface: "buyout_certificate" },
    { id: "report-cover", surface: "report_cover" },
    { id: "footer", surface: "footer" },
  ]);
  writeJson(path.join(brandDir, "signature_placement_allowlist.json"), signaturePlacementReport);

  const signatureProhibitedReport = auditSignaturePlacements([
    { id: "header", surface: "header" },
    { id: "nav", surface: "nav" },
    { id: "card-grid", surface: "every_card" },
  ]);
  writeJson(
    path.join(brandDir, "signature_placement_prohibited.json"),
    signatureProhibitedReport
  );

  const proofSpec = generateProofCardSpec({
    proof_id: "proof-demo-001",
    method_version: "v0.1",
    timestamp: "2026-02-14T00:00:00.000Z",
    width: 1200,
    height: 630,
  });
  proofSpec.proof_id = "proof-demo-001";
  proofSpec.method_version = "v0.1";
  proofSpec.timestamp = "2026-02-14T00:00:00.000Z";
  const proofArtifacts = renderProofCardArtifacts(proofDir, proofSpec);
  writeJson(path.join(proofDir, "proof_card_render_report.json"), proofArtifacts);

  const logoSource = fs.readFileSync(LOGO_SOT);
  renderLogoMarkFromSource(logoSource, path.join(brandDir, "logo_16.png"), 16);
  renderLogoMarkFromSource(logoSource, path.join(brandDir, "logo_24.png"), 24);
  renderLogoMarkFromSource(logoSource, path.join(brandDir, "logo_32.png"), 32);

  const variantSet = getVariantSet({
    symbol: "ASSET_01",
    tf: "1h",
    window: "30D",
    modality: "technical_indicators_plus_price_volume",
  });
  const uiDefault = getRankingsUiState({
    rawTab: undefined,
    variant: undefined,
    variantSet,
  });
  const uiRoi = getRankingsUiState({
    rawTab: "roi",
    variant: "short",
    variantSet,
  });
  writeJson(path.join(uiDir, "rankings_ui_default.json"), uiDefault);
  writeJson(path.join(uiDir, "rankings_ui_roi.json"), uiRoi);

  writeJson(path.join(brandDir, "sot_paths.json"), {
    logo_sot: LOGO_SOT,
    signature_sot: SIGNATURE_SOT,
  });
}

if (require.main === module) {
  renderArtifacts();
}

module.exports = {
  renderArtifacts,
};
