import { NextResponse } from "next/server";

import { parseLocaleWithFallback } from "@/lib/api";
import { buildMethodologyData } from "@/lib/engine";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const locale = parseLocaleWithFallback(url.searchParams.get("locale"));
  const data = buildMethodologyData(locale);
  return NextResponse.json({ ok: true, data }, { headers: { "Cache-Control": "public, max-age=3600" } });
}
