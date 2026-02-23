import { NextResponse } from "next/server";

import { buildSitemapIndexXml } from "@/lib/sitemap";

export async function GET() {
  return new NextResponse(buildSitemapIndexXml(), {
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "public, max-age=1800"
    }
  });
}
