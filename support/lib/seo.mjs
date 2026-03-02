function normalizeBase(baseUrl) {
  return String(baseUrl || "").replace(/\/+$/, "");
}

const ROOT_CANONICAL = "https://leimaitech.com/";

function normalizeAnalysisPaths(paths) {
  if (!Array.isArray(paths)) return [];
  return paths
    .map((p) => String(p || "").trim())
    .filter(Boolean)
    .map((p) => (p.startsWith("/") ? p : `/${p}`))
    .map((p) => p.replace(/\/+$/, ""))
    .filter((p) => p && p !== "/");
}

export function buildCanonical() {
  return ROOT_CANONICAL;
}

export function buildSitemap(baseUrl, analysisPaths = []) {
  const root = normalizeBase(baseUrl);
  const pages = ["/", ...normalizeAnalysisPaths(analysisPaths)];
  const lastmod = new Date().toISOString();
  const body = pages
    .map((page) => {
      const priority = page === "/" ? "1.0" : "0.8";
      return `  <url><loc>${root}${page}</loc><lastmod>${lastmod}</lastmod><changefreq>hourly</changefreq><priority>${priority}</priority></url>`;
    })
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${body}\n</urlset>\n`;
}

export function buildRobots(baseUrl) {
  const root = normalizeBase(baseUrl);
  return [
    "User-agent: *",
    "Allow: /",
    "Allow: /analysis/",
    "Disallow: /api/",
    "Disallow: /preview/",
    "",
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
    "",
    "## Canonical policy",
    `- Canonical URL: ${ROOT_CANONICAL}`,
    "",
    "## Related project",
    `- ${main}`,
    "",
  ].join("\n");
}

function mapOgLocale(locale) {
  if (locale === "zh-tw") return "zh_TW";
  if (locale === "zh-cn") return "zh_CN";
  return "en_US";
}

export function buildPageSeo({ baseUrl, locale, content, king, leaderboard, pagePath = "" }) {
  const canonical = buildCanonical(baseUrl, locale, pagePath);
  const root = normalizeBase(baseUrl);
  const hreflangs = [
    { hreflang: "x-default", href: `${root}/` },
    { hreflang: "en", href: `${root}/` },
  ];
  const image = `${root}/assets/social-card.svg`;
  const kingAmount = king ? Number(king.amount_usdt || 0).toFixed(2) : "0.00";
  const list = Array.isArray(leaderboard) ? leaderboard : [];
  const ogLocale = mapOgLocale(locale);
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
    jsonLd: JSON.stringify(jsonLd),
  };
}
