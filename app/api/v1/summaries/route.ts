import { NextResponse } from "next/server";

import { parseCoin, parseLocaleWithFallback } from "@/lib/api";
import { getPrecomputedSummaries } from "@/lib/precomputed";

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const locale = parseLocaleWithFallback(url.searchParams.get("locale"));
    const rawSymbol = url.searchParams.get("symbol");
    const coin = rawSymbol ? parseCoin(rawSymbol) : null;
    if (rawSymbol && !coin) {
      return NextResponse.json({ ok: false, error: "unsupported symbol" }, { status: 400 });
    }
    const data = await getPrecomputedSummaries({ locale, coin });
    if (!data) {
      return NextResponse.json({ ok: false, error: "precomputed summaries unavailable" }, { status: 404 });
    }
    return NextResponse.json({ ok: true, data }, { headers: { "Cache-Control": "s-maxage=600, stale-while-revalidate=3600" } });
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : "unexpected error" },
      { status: 500 }
    );
  }
}
