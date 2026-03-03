const SUPPORTED_LOCALES = new Set(["en", "zh-tw"]);
const ZH_COUNTRIES = new Set(["TW", "HK", "MO"]);

function normalizeLocale(raw) {
  const value = String(raw || "").trim().toLowerCase();
  if (SUPPORTED_LOCALES.has(value)) return value;
  if (value === "zh" || value === "zh-hant" || value === "zh_tw") return "zh-tw";
  return "en";
}

function firstHeader(headers, keys) {
  for (const key of keys) {
    const val = headers?.[key];
    if (!val) continue;
    if (Array.isArray(val)) {
      const first = String(val[0] || "").trim();
      if (first) return first;
      continue;
    }
    const text = String(val).trim();
    if (text) return text;
  }
  return "";
}

function parseCookies(cookieHeader) {
  const out = {};
  for (const entry of String(cookieHeader || "").split(";")) {
    const idx = entry.indexOf("=");
    if (idx <= 0) continue;
    const key = entry.slice(0, idx).trim();
    const val = entry.slice(idx + 1).trim();
    if (!key) continue;
    try {
      out[key] = decodeURIComponent(val);
    } catch {
      out[key] = val;
    }
  }
  return out;
}

function resolveByCountry(country) {
  const code = String(country || "").trim().toUpperCase();
  if (!code) return null;
  if (ZH_COUNTRIES.has(code)) return "zh-tw";
  return "en";
}

function resolveByAcceptLanguage(raw) {
  const text = String(raw || "").toLowerCase();
  if (!text) return "en";
  if (/(zh-tw|zh-hk|zh-mo|zh-hant)/.test(text)) return "zh-tw";
  return "en";
}

export function resolvePreferredLocale(req) {
  const headers = req?.headers || {};
  const cookieHeader = firstHeader(headers, ["cookie"]);
  const cookies = parseCookies(cookieHeader);
  const cookieLocale = normalizeLocale(cookies.lm_locale);
  if (cookieLocale !== "en" || String(cookies.lm_locale || "").toLowerCase() === "en") {
    return cookieLocale;
  }

  const countryHeader = firstHeader(headers, [
    "cf-ipcountry",
    "x-vercel-ip-country",
    "x-forwarded-country",
  ]);
  const fromCountry = resolveByCountry(countryHeader);
  if (fromCountry) return fromCountry;

  const acceptLanguage = firstHeader(headers, ["accept-language"]);
  return resolveByAcceptLanguage(acceptLanguage);
}

