import Link from "next/link";
import { notFound } from "next/navigation";

import { buildSummariesData } from "@/lib/engine";
import { coerceLocale } from "@/lib/i18n";
import { buildPageMetadata } from "@/lib/seo";

export async function generateMetadata({ params }: { params: { locale: string } }) {
  const locale = coerceLocale(params.locale);
  if (!locale) {
    return {};
  }
  return buildPageMetadata({
    locale,
    title: "Summaries",
    description: "Long-tail summary cards for crypto optimization pages.",
    pathWithoutLocale: "/summaries"
  });
}

export default async function SummariesPage({ params }: { params: { locale: string } }) {
  const locale = coerceLocale(params.locale);
  if (!locale) {
    notFound();
  }
  const payload = await buildSummariesData({ locale });

  return (
    <section className="grid" style={{ gap: "1rem" }}>
      <article className="panel">
        <h1 style={{ marginTop: 0 }}>Summaries</h1>
        <p className="muted">Programmatic summary feed for high-intent entry pages.</p>
      </article>

      <article className="grid two">
        {payload.cards.map((card) => (
          <div key={card.key} className="panel">
            <h2 style={{ marginTop: 0 }}>{card.title}</h2>
            <p className="mono">IS: {card.headline_return_is}%</p>
            <p className="mono">After friction: {card.headline_return_after_friction}%</p>
            <Link href={`/${locale}/verify/${card.proof_id}`}>/verify/{card.proof_id}</Link>
          </div>
        ))}
      </article>
    </section>
  );
}
