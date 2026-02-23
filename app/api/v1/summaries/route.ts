import { NextResponse } from "next/server";

import { parseCoin, parseLocaleWithFallback } from "@/lib/api";
import { buildSummariesData } from "@/lib/engine";

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const locale = parseLocaleWithFallback(url.searchParams.get("locale"));
    const symbol = parseCoin(url.searchParams.get("symbol"));
    const data = await buildSummariesData({ locale, symbol });
    return NextResponse.json({ ok: true, data }, { headers: { "Cache-Control": "s-maxage=120, stale-while-revalidate=300" } });
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : "unexpected error" },
      { status: 500 }
    );
  }
}
