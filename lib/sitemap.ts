import { SITEMAP_TIER_1_COINS, SITEMAP_TIER_2_COINS, SUPPORTED_INDICATOR_SETS } from "@/lib/catalog";
import { SUPPORTED_LOCALES } from "@/lib/i18n";
import { SUPPORTED_COINS, SUPPORTED_TIMEFRAMES, type SupportedCoin } from "@/lib/market";
import { getBaseUrl } from "@/lib/seo";

export type SitemapBucket = "tier-1" | "tier-2" | "tier-3";

type Entry = {
  locale: string;
  path: string;
  priority: number;
  coin: SupportedCoin | null;
};

const TIER_3_COINS: SupportedCoin[] = SUPPORTED_COINS.filter(
  (coin) => !SITEMAP_TIER_1_COINS.includes(coin) && !SITEMAP_TIER_2_COINS.includes(coin)
);

function buildEntries(): Entry[] {
  const entries: Entry[] = [];
  for (const locale of SUPPORTED_LOCALES) {
    entries.push(
      { locale, path: "", priority: 1, coin: null },
      { locale, path: "/methodology", priority: 0.9, coin: null },
      { locale, path: "/summaries", priority: 0.8, coin: null }
    );

    for (const coin of SUPPORTED_COINS) {
      entries.push({ locale, path: `/atlas/${coin}`, priority: coin === "btc" || coin === "eth" ? 0.9 : 0.7, coin });
      for (const timeframe of SUPPORTED_TIMEFRAMES) {
        for (const indicator of SUPPORTED_INDICATOR_SETS) {
          entries.push({
            locale,
            path: `/${coin}/${timeframe}/best-${indicator}-settings`,
            priority: coin === "btc" || coin === "eth" ? 0.8 : 0.6,
            coin
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
    return all.filter((item) => item.coin === null || SITEMAP_TIER_1_COINS.includes(item.coin));
  }
  if (bucket === "tier-2") {
    return all.filter((item) => item.coin !== null && SITEMAP_TIER_2_COINS.includes(item.coin));
  }
  return all.filter((item) => item.coin !== null && TIER_3_COINS.includes(item.coin));
}

export function buildSitemapIndexXml(): string {
  const base = getBaseUrl().toString().replace(/\/$/, "");
  const chunks: string[] = ['<?xml version="1.0" encoding="UTF-8"?>', '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'];
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
  const chunks: string[] = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'];
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

