import { NextResponse } from "next/server";

import { parseLocaleWithFallback } from "@/lib/api";
import { TRUTH_FLAGS } from "@/lib/compliance";

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
      truth_flags: TRUTH_FLAGS,
      canonical_url: `/${locale}/verify/${proofId}`
    }
  });
}
