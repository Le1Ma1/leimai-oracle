import { NextResponse } from "next/server";

import { parseLocaleWithFallback } from "@/lib/api";
import { buildMethodologyData } from "@/lib/engine";
import { getPrecomputedManifest } from "@/lib/precomputed";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const locale = parseLocaleWithFallback(url.searchParams.get("locale"));
  const data = buildMethodologyData(locale);
  const manifest = await getPrecomputedManifest();
  return NextResponse.json(
    {
      ok: true,
      data: {
        ...data,
        precomputed_at: manifest?.generatedAt ?? null,
        coverage: manifest?.coverage ?? null
      }
    },
    { headers: { "Cache-Control": "public, max-age=3600" } }
  );
}
