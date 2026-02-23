import { SUPPORTED_LOCALES } from "@/lib/i18n";
import { getBaseUrl } from "@/lib/seo";

const COINS = ["btc", "eth", "sol", "bnb", "xrp"];
const TIMEFRAMES = ["15m", "1h", "4h", "1d"];
const INDICATOR_SLUGS = ["macd-rsi", "ema-bollinger", "rsi-macd"];

export type SitemapBucket = "tier-1" | "tier-2" | "tier-3";

type Entry = {
  locale: string;
  path: string;
  priority: number;
};

function buildEntries(): Entry[] {
  const entries: Entry[] = [];
  for (const locale of SUPPORTED_LOCALES) {
    entries.push(
      { locale, path: "", priority: 1 },
      { locale, path: "/methodology", priority: 0.9 },
      { locale, path: "/summaries", priority: 0.8 },
      { locale, path: "/atlas/btc", priority: 0.8 }
    );
    for (const coin of COINS) {
      for (const tf of TIMEFRAMES) {
        for (const indicator of INDICATOR_SLUGS) {
          entries.push({
            locale,
            path: `/${coin}/${tf}/best-${indicator}-settings`,
            priority: coin === "btc" || coin === "eth" ? 0.8 : 0.6
          });
        }
      }
    }
  }
  return entries;
}

export function getBucketEntries(bucket: SitemapBucket): Entry[] {
  const all = buildEntries();
  if (bucket === "tier-1") {
    return all.filter((item) => item.path.includes("/btc/") || item.path.includes("/eth/") || item.path === "");
  }
  if (bucket === "tier-2") {
    return all.filter((item) => item.path.includes("/sol/") || item.path.includes("/bnb/") || item.path.includes("/xrp/"));
  }
  return all.filter((item) => item.path.includes("/methodology") || item.path.includes("/summaries") || item.path.includes("/atlas/"));
}

export function buildSitemapIndexXml(): string {
  const base = getBaseUrl().toString().replace(/\/$/, "");
  const chunks: string[] = ['<?xml version="1.0" encoding="UTF-8"?>', "<sitemapindex xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"];
  for (const locale of SUPPORTED_LOCALES) {
    for (const bucket of ["tier-1", "tier-2", "tier-3"] as const) {
      chunks.push("  <sitemap>");
      chunks.push(`    <loc>${base}/${locale}/sitemap/${bucket}</loc>`);
      chunks.push(`    <lastmod>${new Date().toISOString()}</lastmod>`);
      chunks.push("  </sitemap>");
    }
  }
  chunks.push("</sitemapindex>");
  return chunks.join("\n");
}

export function buildSitemapXml(locale: string, bucket: SitemapBucket): string {
  const base = getBaseUrl().toString().replace(/\/$/, "");
  const entries = getBucketEntries(bucket).filter((entry) => entry.locale === locale);
  const chunks: string[] = ['<?xml version="1.0" encoding="UTF-8"?>', "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"];
  for (const entry of entries) {
    chunks.push("  <url>");
    chunks.push(`    <loc>${base}/${locale}${entry.path}</loc>`);
    chunks.push(`    <lastmod>${new Date().toISOString()}</lastmod>`);
    chunks.push(`    <priority>${entry.priority.toFixed(1)}</priority>`);
    chunks.push("  </url>");
  }
  chunks.push("</urlset>");
  return chunks.join("\n");
}
