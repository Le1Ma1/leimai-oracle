import { NextResponse } from "next/server";

import { parseCoin, parseIndicator, parseLocaleWithFallback, parseLookback, parseRegime, parseTimeframe } from "@/lib/api";
import { getPrecomputedAtlas } from "@/lib/precomputed";

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const locale = parseLocaleWithFallback(url.searchParams.get("locale"));
    const coin = parseCoin(url.searchParams.get("coin"));
    if (!coin) {
      return NextResponse.json({ ok: false, error: "unsupported coin" }, { status: 400 });
    }
    const timeframe = parseTimeframe(url.searchParams.get("timeframe"));
    if (!timeframe) {
      return NextResponse.json({ ok: false, error: "unsupported timeframe" }, { status: 400 });
    }
    const indicatorSlug = parseIndicator(url.searchParams.get("indicator_set"));
    if (!indicatorSlug) {
      return NextResponse.json({ ok: false, error: "unsupported indicator_set" }, { status: 400 });
    }
    const lookback = parseLookback(url.searchParams.get("lookback"));
    if (!lookback) {
      return NextResponse.json({ ok: false, error: "unsupported lookback" }, { status: 400 });
    }
    const regime = parseRegime(url.searchParams.get("regime"));
    if (!regime) {
      return NextResponse.json({ ok: false, error: "unsupported regime" }, { status: 400 });
    }

    const data = await getPrecomputedAtlas({
      locale,
      coin,
      timeframe,
      indicatorSlug,
      lookback,
      regime
    });
    if (!data) {
      return NextResponse.json({ ok: false, error: "precomputed slice not found" }, { status: 404 });
    }
    return NextResponse.json({ ok: true, data }, { headers: { "Cache-Control": "s-maxage=600, stale-while-revalidate=3600" } });
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : "unexpected error" },
      { status: 500 }
    );
  }
}
