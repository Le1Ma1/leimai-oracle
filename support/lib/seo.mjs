function normalizeBase(baseUrl) {
  return String(baseUrl || "").replace(/\/+$/, "");
}

const ROOT_CANONICAL = "https://leimai.io/";
const SUPPORTED_HREFLANGS = [
  { hreflang: "x-default", locale: "en" },
  { hreflang: "en", locale: "en" },
  { hreflang: "zh-Hant", locale: "zh-tw" },
  { hreflang: "es", locale: "es" },
  { hreflang: "ja", locale: "ja" },
];

function normalizeAnalysisPaths(paths) {
  if (!Array.isArray(paths)) return [];
  return paths
    .map((p) => String(p || "").trim())
    .filter(Boolean)
    .map((p) => (p.startsWith("/") ? p : `/${p}`))
    .map((p) => p.replace(/\/+$/, ""))
    .filter((p) => p && p !== "/");
}

export function buildCanonical(_baseUrl, _locale, pagePath = "") {
  const root = ROOT_CANONICAL.replace(/\/+$/, "");
  const rawPath = String(pagePath || "").trim();
  if (!rawPath) return `${root}/`;
  const normalizedPath = rawPath.startsWith("/") ? rawPath : `/${rawPath}`;
  return `${root}${normalizedPath}`;
}

function buildSitemapEntry(root, page, lastmod, changefreq = "hourly", priority = "0.8") {
  return `  <url><loc>${root}${page}</loc><lastmod>${lastmod}</lastmod><changefreq>${changefreq}</changefreq><priority>${priority}</priority></url>`;
}

export function buildSitemapDocument(baseUrl, paths = [], { changefreq = "hourly" } = {}) {
  const root = normalizeBase(baseUrl);
  const safePaths = ["/", ...normalizeAnalysisPaths(paths)];
  const deduped = [...new Set(safePaths)];
  const lastmod = new Date().toISOString();
  const body = deduped
    .map((page) => {
      const priority = page === "/" ? "1.0" : page.startsWith("/analysis/") ? "0.8" : "0.7";
      return buildSitemapEntry(root, page, lastmod, changefreq, priority);
    })
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${body}\n</urlset>\n`;
}

export function buildSitemap(baseUrl, analysisPaths = []) {
  return buildSitemapDocument(baseUrl, analysisPaths, { changefreq: "hourly" });
}

export function buildSitemapIndex(baseUrl, sitemapPaths = []) {
  const root = normalizeBase(baseUrl);
  const now = new Date().toISOString();
  const rows = (Array.isArray(sitemapPaths) ? sitemapPaths : [])
    .map((row) => String(row || "").trim())
    .filter(Boolean)
    .map((row) => (row.startsWith("/") ? row : `/${row}`))
    .map((path) => `  <sitemap><loc>${root}${path}</loc><lastmod>${now}</lastmod></sitemap>`)
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${rows}\n</sitemapindex>\n`;
}

export function buildRobots(baseUrl) {
  const root = normalizeBase(baseUrl);
  return [
    "User-agent: *",
    "Allow: /",
    "Allow: /analysis/",
    "Disallow: /api/",
    "Disallow: /preview/",
    "Disallow: /api/internal/",
    "",
    `Sitemap: ${root}/sitemap-index.xml`,
    `Sitemap: ${root}/sitemap.xml`,
    "",
  ].join("\n");
}

export function buildLlmsTxt(baseUrl, mainSiteUrl) {
  const root = normalizeBase(baseUrl);
  const main = normalizeBase(mainSiteUrl);
  return [
    "# LeiMai Oracle / Ouroboros",
    "",
    "## Intent",
    "- Public-facing oracle hub for market intelligence and narrative analysis.",
    "- Root authority property for LeiMai Oracle entity graph.",
    "- Research content only. Not investment advice.",
    "",
    "## Entry pages",
    `- ${root}/`,
    `- ${root}/analysis/`,
    `- ${root}/vault`,
    `- ${root}/forge`,
    "",
    "## Canonical policy",
    `- Canonical URL: ${ROOT_CANONICAL}`,
    "- Localized surfaces: en, zh-tw, es, ja",
    "",
    "## Citation feed",
    `- ${root}/.well-known/ai-citation-feed.json`,
    "",
    "## Related project",
    `- ${main}`,
    "",
  ].join("\n");
}

function mapOgLocale(locale) {
  if (locale === "zh-tw") return "zh_TW";
  if (locale === "es") return "es_ES";
  if (locale === "ja") return "ja_JP";
  if (locale === "zh-cn") return "zh_CN";
  return "en_US";
}

function clamp(value, lo, hi) {
  const n = Number(value);
  if (!Number.isFinite(n)) return lo;
  return Math.max(lo, Math.min(hi, n));
}

function parseTrendHints(keywords) {
  return String(keywords || "")
    .split(",")
    .map((item) => String(item || "").trim())
    .filter(Boolean)
    .slice(0, 6);
}

function buildSeoGeoScorecard({ content, leaderboard, pagePath }) {
  const descLen = String(content?.description || "").trim().length;
  const keywordsLen = String(content?.keywords || "").trim().length;
  const listCount = Array.isArray(leaderboard) ? leaderboard.length : 0;
  const pathDepth = String(pagePath || "").split("/").filter(Boolean).length;
  const metrics = {
    information_density: clamp((descLen / 220) * 100, 35, 100),
    narrative_coverage: clamp((keywordsLen / 160) * 100, 25, 100),
    geo_authority: clamp(52 + listCount * 2.4, 45, 100),
    crawl_focus: clamp(84 - pathDepth * 8, 40, 100),
  };
  const score = (
    metrics.information_density * 0.34
    + metrics.narrative_coverage * 0.24
    + metrics.geo_authority * 0.26
    + metrics.crawl_focus * 0.16
  );
  return {
    version: "seo-geo-score-v1",
    score: Number(score.toFixed(2)),
    metrics: Object.fromEntries(Object.entries(metrics).map(([k, v]) => [k, Number(v.toFixed(2))])),
  };
}

export function buildPageSeo({ baseUrl, locale, content, king, leaderboard, pagePath = "" }) {
  const canonical = buildCanonical(baseUrl, locale, pagePath);
  const root = normalizeBase(baseUrl);
  const normalizedPath = String(pagePath || "").trim();
  const safePath = normalizedPath.startsWith("/") ? normalizedPath : normalizedPath ? `/${normalizedPath}` : "";
  const hreflangs = SUPPORTED_HREFLANGS.map((row) => {
    if (row.locale === "en") {
      return {
        hreflang: row.hreflang,
        href: `${root}${safePath || "/"}`,
      };
    }
    return {
      hreflang: row.hreflang,
      href: `${root}/${row.locale}${safePath || "/"}`,
    };
  });
  const image = `${root}/assets/social-card.svg`;
  const kingAmount = king ? Number(king.amount_usdt || 0).toFixed(2) : "0.00";
  const list = Array.isArray(leaderboard) ? leaderboard : [];
  const ogLocale = mapOgLocale(locale);
  const scorecard = buildSeoGeoScorecard({ content, leaderboard: list, pagePath: safePath || "/" });
  const trendHints = parseTrendHints(content?.keywords || "");
  const scoreProps = Object.entries(scorecard.metrics).map(([name, value]) => ({
    "@type": "PropertyValue",
    name,
    value: String(value),
  }));
  scoreProps.push({
    "@type": "PropertyValue",
    name: "seo_geo_score",
    value: String(scorecard.score),
  });
  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "WebSite",
        name: "LeiMai Oracle",
        url: `${root}/`,
        inLanguage: locale,
        description: content.description,
      },
      {
        "@type": "WebPage",
        name: content.title,
        url: canonical,
        inLanguage: locale,
        description: content.description,
        keywords: String(content?.keywords || ""),
        about: trendHints.map((hint) => ({ "@type": "Thing", name: hint })),
        additionalProperty: scoreProps,
        isPartOf: {
          "@type": "WebSite",
          name: "LeiMai Oracle",
          url: `${root}/`,
        },
      },
      {
        "@type": "Organization",
        name: "LeiMai Oracle",
        url: root,
      },
      {
        "@type": "ItemList",
        name: "Top Single Transfer Leaderboard",
        numberOfItems: list.length,
        itemListElement: list.slice(0, 10).map((row, idx) => ({
          "@type": "ListItem",
          position: idx + 1,
          name: row.wallet_masked || "wallet",
          description: `${Number(row.amount_usdt || 0).toFixed(2)} USDT`,
        })),
      },
      {
        "@type": "FAQPage",
        mainEntity: [
          {
            "@type": "Question",
            name: content.faq1q,
            acceptedAnswer: { "@type": "Answer", text: content.faq1a },
          },
          {
            "@type": "Question",
            name: content.faq2q,
            acceptedAnswer: { "@type": "Answer", text: content.faq2a },
          },
          {
            "@type": "Question",
            name: content.faq3q,
            acceptedAnswer: { "@type": "Answer", text: content.faq3a },
          },
        ],
      },
      {
        "@type": "DefinedTermSet",
        name: "Crypto Narrative Hints",
        hasDefinedTerm: trendHints.map((hint) => ({
          "@type": "DefinedTerm",
          name: hint,
        })),
      },
    ],
  };
  return {
    canonical,
    hreflangs,
    image,
    ogLocale,
    title: content.title,
    description: content.description,
    keywords: content.keywords || "",
    kingAmount,
    scorecard,
    jsonLd: JSON.stringify(jsonLd),
  };
}
