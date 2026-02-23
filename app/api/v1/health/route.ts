import { NextResponse } from "next/server";

import { SUPPORTED_LOCALES } from "@/lib/i18n";
import { getPrecomputedManifest } from "@/lib/precomputed";

export async function GET() {
  const manifest = await getPrecomputedManifest();
  return NextResponse.json({
    ok: true,
    data: {
      app: "leimai-oracle",
      brand: "LeiMai Oracle",
      status: "ok",
      locales: SUPPORTED_LOCALES,
      data_source: "binance_api",
      i18n_day1: true,
      precomputed_available: Boolean(manifest),
      precomputed_at: manifest?.generatedAt ?? null,
      coverage: manifest?.coverage ?? null
    }
  });
}
