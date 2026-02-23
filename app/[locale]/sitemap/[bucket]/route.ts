import { NextResponse } from "next/server";

import { coerceLocale } from "@/lib/i18n";
import { buildSitemapXml, type SitemapBucket } from "@/lib/sitemap";

function isBucket(value: string): value is SitemapBucket {
  return value === "tier-1" || value === "tier-2" || value === "tier-3";
}

export async function GET(_request: Request, context: { params: { locale: string; bucket: string } }) {
  const locale = coerceLocale(context.params.locale);
  if (!locale || !isBucket(context.params.bucket)) {
    return NextResponse.json({ ok: false, error: "not found" }, { status: 404 });
  }

  return new NextResponse(buildSitemapXml(locale, context.params.bucket), {
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "public, max-age=1800"
    }
  });
}
