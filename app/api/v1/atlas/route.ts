import { NextResponse } from "next/server";

import { parseCoin, parseIndicator, parseLocaleWithFallback, parseLookback, parseRegime, parseTimeframe } from "@/lib/api";
import { computeAtlas } from "@/lib/engine";

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const locale = parseLocaleWithFallback(url.searchParams.get("locale"));
    const coin = parseCoin(url.searchParams.get("coin"));
    const timeframe = parseTimeframe(url.searchParams.get("timeframe"));
    if (!timeframe) {
      return NextResponse.json({ ok: false, error: "unsupported timeframe" }, { status: 400 });
    }
    const indicatorSlug = parseIndicator(url.searchParams.get("indicator_set"));
    const lookback = parseLookback(url.searchParams.get("lookback"));
    const regime = parseRegime(url.searchParams.get("regime"));

    const data = await computeAtlas({
      locale,
      coin,
      timeframe,
      indicatorSlug,
      lookback,
      regime
    });
    return NextResponse.json({ ok: true, data }, { headers: { "Cache-Control": "s-maxage=120, stale-while-revalidate=300" } });
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : "unexpected error" },
      { status: 500 }
    );
  }
}
