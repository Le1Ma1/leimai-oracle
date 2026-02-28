import { getHreflangUrls } from "./content.mjs";

function normalizeBase(baseUrl) {
  return String(baseUrl || "").replace(/\/+$/, "");
}

function normalizePath(pagePath = "") {
  const p = String(pagePath || "").trim();
  if (!p || p === "/") return "";
  return p.startsWith("/") ? p : `/${p}`;
}

export function buildCanonical(baseUrl, locale, pagePath = "") {
  const root = normalizeBase(baseUrl);
  const suffix = normalizePath(pagePath);
  return `${root}/${locale}${suffix}`;
}

export function buildSitemap(baseUrl) {
  const root = normalizeBase(baseUrl);
  const pages = [
    "/en",
    "/zh-tw",
    "/zh-cn",
    "/en/rules",
    "/zh-tw/rules",
    "/zh-cn/rules",
    "/en/faq",
    "/zh-tw/faq",
    "/zh-cn/faq",
  ];
  const lastmod = new Date().toISOString();
  const body = pages
    .map((page) => {
      const priority = page.includes("/faq") || page.includes("/rules") ? "0.7" : "0.9";
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
    "",
    `Sitemap: ${root}/sitemap.xml`,
    `Sitemap: ${root}/llms.txt`,
    "",
  ].join("\n");
}

export function buildLlmsTxt(baseUrl, mainSiteUrl) {
  const root = normalizeBase(baseUrl);
  const main = normalizeBase(mainSiteUrl);
  return [
    "# LeiMai Throne",
    "",
    "## Intent",
    "- Public support and proof-of-wealth leaderboard for LeiMai Oracle.",
    "- Ranking is based on highest single verified USDT (TRC20) transfer.",
    "- This property is not investment advice and has no guaranteed return.",
    "",
    "## Entry pages",
    `- ${root}/en`,
    `- ${root}/zh-tw`,
    `- ${root}/zh-cn`,
    "",
    "## APIs",
    `- ${root}/api/v1/leaderboard`,
    `- ${root}/api/v1/king`,
    `- ${root}/api/v1/health`,
    `- ${root}/api/v1/knowledge`,
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
  const hreflangs = getHreflangUrls(baseUrl);
  const image = `${root}/assets/social-card.svg`;
  const kingAmount = king ? Number(king.amount_usdt || 0).toFixed(2) : "0.00";
  const list = Array.isArray(leaderboard) ? leaderboard : [];
  const ogLocale = mapOgLocale(locale);
  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "WebSite",
        name: "LeiMai Throne",
        url: `${root}/${locale}`,
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
          name: "LeiMai Throne",
          url: `${root}/${locale}`,
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
