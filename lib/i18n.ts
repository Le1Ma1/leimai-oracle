export const SUPPORTED_LOCALES = ["en", "zh-TW", "zh-CN", "ko", "tr", "vi"] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

export const DEFAULT_LOCALE: SupportedLocale = "en";

const LOCALE_SET = new Set<string>(SUPPORTED_LOCALES);
const LOCALE_BY_LOWERCASE = Object.fromEntries(
  SUPPORTED_LOCALES.map((locale) => [locale.toLowerCase(), locale])
) as Record<string, SupportedLocale>;

const COUNTRY_TO_LOCALE: Record<string, SupportedLocale> = {
  TW: "zh-TW",
  HK: "zh-TW",
  MO: "zh-TW",
  CN: "zh-CN",
  SG: "zh-CN",
  KR: "ko",
  TR: "tr",
  VN: "vi"
};

const LOCALE_ALIASES: Record<string, SupportedLocale> = {
  zh: "zh-CN",
  "zh-hans": "zh-CN",
  "zh-cn": "zh-CN",
  "zh-sg": "zh-CN",
  "zh-hant": "zh-TW",
  "zh-tw": "zh-TW",
  "zh-hk": "zh-TW",
  "zh-mo": "zh-TW"
};

function normalizeLocaleToken(token: string): string {
  return token.trim().replace(/_/g, "-");
}

export function isSupportedLocale(value: string): value is SupportedLocale {
  return LOCALE_SET.has(value);
}

export function coerceLocale(value: string | null | undefined): SupportedLocale | null {
  if (!value) {
    return null;
  }
  const normalized = normalizeLocaleToken(value);
  const lower = normalized.toLowerCase();
  if (LOCALE_ALIASES[lower]) {
    return LOCALE_ALIASES[lower];
  }
  if (isSupportedLocale(normalized)) {
    return normalized;
  }
  if (LOCALE_BY_LOWERCASE[lower]) {
    return LOCALE_BY_LOWERCASE[lower];
  }
  const base = lower.split("-")[0] ?? "";
  if (LOCALE_ALIASES[base]) {
    return LOCALE_ALIASES[base];
  }
  return LOCALE_BY_LOWERCASE[base] ?? null;
}

export function resolveLocaleFromAcceptLanguage(
  acceptLanguage: string | null | undefined
): SupportedLocale | null {
  if (!acceptLanguage) {
    return null;
  }

  const ranked = acceptLanguage
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const [lang, qPart] = part.split(";q=");
      const q = qPart ? Number.parseFloat(qPart) : 1;
      return { lang: normalizeLocaleToken(lang ?? ""), q: Number.isFinite(q) ? q : 0 };
    })
    .sort((a, b) => b.q - a.q);

  for (const entry of ranked) {
    const locale = coerceLocale(entry.lang);
    if (locale) {
      return locale;
    }
  }
  return null;
}

export function resolveLocaleFromCountry(countryCode: string | null | undefined): SupportedLocale | null {
  if (!countryCode) {
    return null;
  }
  return COUNTRY_TO_LOCALE[countryCode.toUpperCase()] ?? null;
}

export function resolveBestLocale(input: {
  cookieLocale?: string | null;
  pathLocale?: string | null;
  acceptLanguage?: string | null;
  countryCode?: string | null;
}): SupportedLocale {
  const fromCookie = coerceLocale(input.cookieLocale);
  if (fromCookie) {
    return fromCookie;
  }
  const fromPath = coerceLocale(input.pathLocale);
  if (fromPath) {
    return fromPath;
  }
  const fromAccept = resolveLocaleFromAcceptLanguage(input.acceptLanguage);
  if (fromAccept) {
    return fromAccept;
  }
  const fromCountry = resolveLocaleFromCountry(input.countryCode);
  if (fromCountry) {
    return fromCountry;
  }
  return DEFAULT_LOCALE;
}

export function stripLocalePrefix(pathname: string): { locale: SupportedLocale | null; path: string } {
  const parts = pathname.split("/").filter(Boolean);
  const head = parts[0] ?? "";
  const locale = coerceLocale(head);
  if (!locale) {
    return { locale: null, path: pathname };
  }
  const rest = `/${parts.slice(1).join("/")}`;
  return { locale, path: rest === "/" ? "/" : rest.replace(/\/$/, "") || "/" };
}

export function withLocale(pathname: string, locale: SupportedLocale): string {
  const normalized = pathname.startsWith("/") ? pathname : `/${pathname}`;
  const cleaned = normalized === "/" ? "" : normalized;
  return `/${locale}${cleaned}`;
}
