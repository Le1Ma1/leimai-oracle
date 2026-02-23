import { NextResponse } from "next/server";

import { parseLocaleWithFallback } from "@/lib/api";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const locale = parseLocaleWithFallback(url.searchParams.get("locale"));
  const proofId = (url.searchParams.get("proof_id") || "").trim();
  if (!proofId) {
    return NextResponse.json({ ok: false, error: "proof_id is required" }, { status: 400 });
  }
  return NextResponse.json({
    ok: true,
    data: {
      locale,
      proof_id: proofId,
      truth_flags: ["THEORETICAL", "IN_SAMPLE", "SNAPSHOT", "NOT_OOS", "NOT_EXECUTABLE", "NOT_ADVICE"],
      canonical_url: `/${locale}/verify/${proofId}`
    }
  });
}
