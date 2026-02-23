import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import path from "node:path";

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
