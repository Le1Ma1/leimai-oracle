import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import { CORE_LOCALE_MESSAGES } from "../lib/text";

const PROJECT_ROOT = process.cwd();
const SCAN_DIRS = [path.join(PROJECT_ROOT, "app", "[locale]"), path.join(PROJECT_ROOT, "components")];
const SCAN_EXTENSIONS = new Set([".tsx"]);

type Finding = {
  file: string;
  line: number;
  reason: string;
  value: string;
};

function walkFiles(dir: string, collector: string[]) {
  const entries = readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const absolute = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkFiles(absolute, collector);
      continue;
    }
    if (!entry.isFile()) {
      continue;
    }
    if (SCAN_EXTENSIONS.has(path.extname(entry.name))) {
      collector.push(absolute);
    }
  }
}

function hasNaturalLanguage(value: string): boolean {
  return /[\p{L}\p{Script=Han}]/u.test(value);
}

function shouldIgnoreLiteral(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed) {
    return true;
  }
  if (trimmed.startsWith("/") || trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
    return true;
  }
  if (/^[0-9\s.,:%|+_\-=()[\]{}]+$/.test(trimmed)) {
    return true;
  }
  if (/^[A-Z0-9_,-]+$/.test(trimmed)) {
    return true;
  }
  if (trimmed.includes("`") || trimmed.includes("${")) {
    return true;
  }
  return !hasNaturalLanguage(trimmed);
}

function collectHardcodedFindings(file: string): Finding[] {
  const source = readFileSync(file, "utf8");
  const lines = source.split(/\r?\n/);
  const findings: Finding[] = [];
  const relative = path.relative(PROJECT_ROOT, file).replace(/\\/g, "/");
  const inLocalePage = relative.startsWith("app/[locale]/");

  for (let idx = 0; idx < lines.length; idx += 1) {
    const lineNumber = idx + 1;
    const line = lines[idx];
    if (!line || line.includes("i18n-ignore-line")) {
      continue;
    }

    const jsxTextRegex = />\s*([^<{][^<]*)</g;
    let match = jsxTextRegex.exec(line);
    while (match) {
      const value = match[1]?.trim() ?? "";
      if (value && !line.includes("t(") && !shouldIgnoreLiteral(value)) {
        findings.push({
          file: relative,
          line: lineNumber,
          reason: "jsx-text",
          value
        });
      }
      match = jsxTextRegex.exec(line);
    }

    const jsxPropRegex = /\b(?:alt|title|placeholder|aria-label)\s*=\s*["']([^"']+)["']/g;
    let propMatch = jsxPropRegex.exec(line);
    while (propMatch) {
      const value = propMatch[1]?.trim() ?? "";
      if (value && !shouldIgnoreLiteral(value)) {
        findings.push({
          file: relative,
          line: lineNumber,
          reason: "jsx-prop",
          value
        });
      }
      propMatch = jsxPropRegex.exec(line);
    }

    if (inLocalePage) {
      const metadataRegex = /\b(?:title|description)\s*:\s*["']([^"']+)["']/g;
      let metadataMatch = metadataRegex.exec(line);
      while (metadataMatch) {
        const value = metadataMatch[1]?.trim() ?? "";
        if (value && !shouldIgnoreLiteral(value)) {
          findings.push({
            file: relative,
            line: lineNumber,
            reason: "metadata",
            value
          });
        }
        metadataMatch = metadataRegex.exec(line);
      }
    }
  }

  return findings;
}

function checkLocaleCoverage(): string[] {
  const errors: string[] = [];
  const baseline = Object.keys(CORE_LOCALE_MESSAGES.en).sort();
  for (const [locale, messages] of Object.entries(CORE_LOCALE_MESSAGES)) {
    const keys = Object.keys(messages).sort();
    const missing = baseline.filter((key) => !keys.includes(key));
    const extra = keys.filter((key) => !baseline.includes(key));
    if (missing.length) {
      errors.push(`[coverage] ${locale} missing keys: ${missing.join(", ")}`);
    }
    if (extra.length) {
      errors.push(`[coverage] ${locale} extra keys: ${extra.join(", ")}`);
    }
    for (const key of baseline) {
      const value = messages[key as keyof typeof messages];
      if (typeof value !== "string" || !value.trim()) {
        errors.push(`[coverage] ${locale}.${key} is empty`);
      }
    }
  }
  return errors;
}

function main() {
  for (const dir of SCAN_DIRS) {
    if (!statSync(dir).isDirectory()) {
      throw new Error(`scan dir not found: ${dir}`);
    }
  }

  const files: string[] = [];
  for (const dir of SCAN_DIRS) {
    walkFiles(dir, files);
  }

  const findings = files.flatMap((file) => collectHardcodedFindings(file));
  const coverageErrors = checkLocaleCoverage();

  if (!findings.length && !coverageErrors.length) {
    console.log("[i18n-check] pass");
    return;
  }

  for (const error of coverageErrors) {
    console.error(error);
  }
  for (const finding of findings) {
    console.error(`[hardcoded] ${finding.file}:${finding.line} (${finding.reason}) -> "${finding.value}"`);
  }

  process.exitCode = 1;
}

main();
