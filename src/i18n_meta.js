const { detectLocaleFromPath, normalizeLocale } = require("./validators");

function normalizeBasePath(pathname) {
  if (!pathname || pathname === "") {
    return "/";
  }
  let path = pathname.startsWith("/") ? pathname : `/${pathname}`;

  if (path === "/en") {
    return "/";
  }
  if (path.startsWith("/en/")) {
    return path.slice(3);
  }
  if (path === "/zh-hans") {
    return "/";
  }
  if (path.startsWith("/zh-hans/")) {
    return path.slice(8);
  }
  return path;
}

function buildLocalizedPath(basePath, locale) {
  const normalized = normalizeBasePath(basePath);
  const language = normalizeLocale(locale);
  if (!language) {
    throw new Error(`Unsupported locale: ${locale}`);
  }

  if (language === "zh-Hant") {
    return normalized;
  }
  if (language === "en") {
    return normalized === "/" ? "/en/" : `/en${normalized}`;
  }
  if (language === "zh-Hans") {
    return normalized === "/" ? "/zh-hans/" : `/zh-hans${normalized}`;
  }
  throw new Error(`Unsupported locale: ${language}`);
}

function resolveRoute(pathname) {
  const locale = detectLocaleFromPath(pathname || "/");
  const basePath = normalizeBasePath(pathname || "/");
  return {
    locale,
    basePath,
    localizedPath: buildLocalizedPath(basePath, locale),
  };
}

function resolveRouteIgnoringCookie(pathname) {
  return resolveRoute(pathname);
}

function buildPageMeta(basePath, locale) {
  const language = normalizeLocale(locale);
  if (!language) {
    throw new Error(`Unsupported locale: ${locale}`);
  }

  const canonical = buildLocalizedPath(basePath, language);
  const hreflang = {
    "zh-Hant": buildLocalizedPath(basePath, "zh-Hant"),
    en: buildLocalizedPath(basePath, "en"),
    "zh-Hans": buildLocalizedPath(basePath, "zh-Hans"),
    "x-default": buildLocalizedPath(basePath, "zh-Hant"),
  };

  return {
    canonical,
    hreflang,
  };
}

module.exports = {
  buildLocalizedPath,
  buildPageMeta,
  normalizeBasePath,
  resolveRoute,
  resolveRouteIgnoringCookie,
};
