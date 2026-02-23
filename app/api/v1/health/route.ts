import { NextResponse } from "next/server";

import { SUPPORTED_LOCALES } from "@/lib/i18n";

export async function GET() {
  return NextResponse.json({
    ok: true,
    data: {
      app: "project-panopticon",
      status: "ok",
      locales: SUPPORTED_LOCALES,
      data_source: "binance_api",
      i18n_day1: true
    }
  });
}
