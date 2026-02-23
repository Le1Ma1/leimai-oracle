import { copyFileSync, existsSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import pngToIco from "png-to-ico";
import sharp from "sharp";

const root = process.cwd();
const logoSource = path.join(root, "logo.png");
const signatureSource = path.join(root, "signature.jpg");
const publicDir = path.join(root, "public");

if (!existsSync(logoSource)) {
  throw new Error("Missing brand source file: logo.png");
}
if (!existsSync(signatureSource)) {
  throw new Error("Missing brand source file: signature.jpg");
}

mkdirSync(publicDir, { recursive: true });
copyFileSync(logoSource, path.join(publicDir, "logo.png"));
copyFileSync(signatureSource, path.join(publicDir, "signature.jpg"));

const iconSizes = [16, 32, 48, 180, 192];

async function renderSquareIcon(size) {
  return sharp(logoSource)
    .rotate()
    .ensureAlpha()
    .resize(size, size, {
      fit: "cover",
      position: "centre",
      kernel: sharp.kernel.lanczos3
    })
    .sharpen()
    .png({ compressionLevel: 9, adaptiveFiltering: true })
    .toBuffer();
}

const icons = new Map();
for (const size of iconSizes) {
  icons.set(size, await renderSquareIcon(size));
}

writeFileSync(path.join(publicDir, "icon-32x32.png"), icons.get(32));
writeFileSync(path.join(publicDir, "icon-192x192.png"), icons.get(192));
writeFileSync(path.join(publicDir, "apple-touch-icon.png"), icons.get(180));

const faviconIco = await pngToIco([icons.get(16), icons.get(32), icons.get(48)]);
writeFileSync(path.join(publicDir, "favicon.ico"), faviconIco);
