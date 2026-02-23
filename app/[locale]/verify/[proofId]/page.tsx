import { notFound } from "next/navigation";

import { TRUTH_FLAGS } from "@/lib/compliance";
import { coerceLocale } from "@/lib/i18n";
import { buildPageMetadata } from "@/lib/seo";

export async function generateMetadata({
  params
}: {
  params: { locale: string; proofId: string };
}) {
  const locale = coerceLocale(params.locale);
  if (!locale) {
    return {};
  }
  return buildPageMetadata({
    locale,
    title: `Verify ${params.proofId}`,
    description: "Proof and metadata validation page.",
    pathWithoutLocale: `/verify/${params.proofId}`,
    noindex: true
  });
}

export default function VerifyPage({
  params
}: {
  params: { locale: string; proofId: string };
}) {
  const locale = coerceLocale(params.locale);
  if (!locale) {
    notFound();
  }

  return (
    <section className="grid" style={{ gap: "1rem" }}>
      <article className="panel">
        <h1 style={{ marginTop: 0 }}>Verify Proof</h1>
        <p className="mono">proof_id={params.proofId}</p>
      </article>

      <article className="panel">
        <h2 style={{ marginTop: 0 }}>Truth Banner</h2>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          {TRUTH_FLAGS.map((flag) => (
            <span className="badge" key={flag}>
              {flag}
            </span>
          ))}
        </div>
      </article>
    </section>
  );
}
