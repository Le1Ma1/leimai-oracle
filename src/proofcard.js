const fs = require("node:fs");
const path = require("node:path");
const { createHash } = require("node:crypto");

const { writePng } = require("./png");

function generateProofCardSpec({
  proof_id,
  method_version,
  timestamp,
  width = 1200,
  height = 630,
}) {
  const signatureWidth = 220;
  const signatureHeight = 64;
  const margin = 24;
  const signatureX = width - signatureWidth - margin;
  const signatureY = height - signatureHeight - margin;

  const svg = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`,
    `<rect x="0" y="0" width="${width}" height="${height}" fill="#f8f9fb"/>`,
    `<text x="40" y="80" font-size="34" font-family="serif" fill="#111">LeiMai Proof Card</text>`,
    `<text x="40" y="150" font-size="24" font-family="monospace" fill="#111">proof_id: ${proof_id}</text>`,
    `<text x="40" y="200" font-size="24" font-family="monospace" fill="#111">method_version: ${method_version}</text>`,
    `<text x="40" y="250" font-size="24" font-family="monospace" fill="#111">timestamp: ${timestamp}</text>`,
    `<rect x="${signatureX}" y="${signatureY}" width="${signatureWidth}" height="${signatureHeight}" fill="#ffffff" stroke="#111"/>`,
    `<image id="signature" href="/signature.jpg" x="${signatureX + 6}" y="${signatureY + 6}" width="${signatureWidth - 12}" height="${signatureHeight - 12}" preserveAspectRatio="xMidYMid meet"/>`,
    `</svg>`,
  ].join("");

  return {
    svg,
    width,
    height,
    signature: {
      x: signatureX,
      y: signatureY,
      width: signatureWidth,
      height: signatureHeight,
      source: "/signature.jpg",
      placement: "bottom-right",
    },
  };
}

function hashByte(seed, offset) {
  const digest = createHash("sha256").update(seed, "utf8").digest();
  return digest[offset % digest.length];
}

function renderProofCardArtifacts(outputDir, spec) {
  fs.mkdirSync(outputDir, { recursive: true });
  const svgPath = path.join(outputDir, "proof_card.svg");
  const pngPath = path.join(outputDir, "proof_card.png");
  const metaPath = path.join(outputDir, "proof_card_meta.json");

  fs.writeFileSync(svgPath, spec.svg, "utf8");

  writePng(pngPath, spec.width, spec.height, (x, y) => {
    const sig = spec.signature;
    const inSignature =
      x >= sig.x &&
      x < sig.x + sig.width &&
      y >= sig.y &&
      y < sig.y + sig.height;
    if (inSignature) {
      return [20, 20, 20, 255];
    }
    const r = 220 + (hashByte(`${x}:${y}`, 0) % 20);
    const g = 220 + (hashByte(`${x}:${y}`, 1) % 20);
    const b = 230 + (hashByte(`${x}:${y}`, 2) % 20);
    return [r, g, b, 255];
  });

  fs.writeFileSync(
    metaPath,
    JSON.stringify(
      {
        proof_id: spec.proof_id,
        method_version: spec.method_version,
        timestamp: spec.timestamp,
        signature: spec.signature,
        svg_path: svgPath,
        png_path: pngPath,
      },
      null,
      2
    ),
    "utf8"
  );

  return {
    svgPath,
    pngPath,
    metaPath,
  };
}

function renderLogoMarkFromSource(sourceBuffer, filePath, size) {
  const seed = createHash("sha256").update(sourceBuffer).digest("hex");
  writePng(filePath, size, size, (x, y) => {
    const band = Math.floor((x + y) / Math.max(1, Math.floor(size / 4))) % 2;
    const base = band === 0 ? 30 : 220;
    const tint = hashByte(seed, (x + y) % 32) % 20;
    return [base + tint, base + tint, base + tint, 255];
  });
}

module.exports = {
  generateProofCardSpec,
  renderLogoMarkFromSource,
  renderProofCardArtifacts,
};
