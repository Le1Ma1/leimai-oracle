export const SUPPORTED_LOCALES = ["en", "zh-TW", "ko", "tr", "vi"] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

export const DEFAULT_LOCALE: SupportedLocale = "en";

const LOCALE_SET = new Set<string>(SUPPORTED_LOCALES);

const COUNTRY_TO_LOCALE: Record<string, SupportedLocale> = {
  TW: "zh-TW",
  HK: "zh-TW",
  MO: "zh-TW",
  KR: "ko",
  TR: "tr",
  VN: "vi"
};

function normalizeLocaleToken(token: string): string {
  return token.trim().replace("_", "-");
}

export function isSupportedLocale(value: string): value is SupportedLocale {
  return LOCALE_SET.has(value);
}

export function coerceLocale(value: string | null | undefined): SupportedLocale | null {
  if (!value) {
    return null;
  }
  const normalized = normalizeLocaleToken(value);
  if (isSupportedLocale(normalized)) {
    return normalized;
  }
  const base = normalized.split("-")[0] ?? "";
  const match = SUPPORTED_LOCALES.find((locale) => locale.toLowerCase() === base.toLowerCase());
  return match ?? null;
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
