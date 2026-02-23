import Link from "next/link";
import { notFound } from "next/navigation";

import { coerceLocale } from "@/lib/i18n";
import { getPrecomputedSummaries } from "@/lib/precomputed";
import { buildPageMetadata } from "@/lib/seo";
import { t } from "@/lib/text";

export async function generateMetadata({ params }: { params: { locale: string } }) {
  const locale = coerceLocale(params.locale);
  if (!locale) {
    return {};
  }
  return buildPageMetadata({
    locale,
    title: t(locale, "summariesMetaTitle"),
    description: t(locale, "summariesMetaDescription"),
    pathWithoutLocale: "/summaries"
  });
}

export default async function SummariesPage({ params }: { params: { locale: string } }) {
  const locale = coerceLocale(params.locale);
  if (!locale) {
    notFound();
  }
  const payload = await getPrecomputedSummaries({ locale });
  if (!payload) {
    notFound();
  }

  return (
    <section className="grid" style={{ gap: "1rem" }}>
      <article className="panel">
        <h1 style={{ marginTop: 0 }}>{t(locale, "summariesHeading")}</h1>
        <p className="muted">{t(locale, "summariesSubtitle")}</p>
        <p className="muted mono">
          {t(locale, "summariesTruthFlags")}={t(locale, "disclaimerA")},{t(locale, "disclaimerB")},{t(locale, "disclaimerC")}
        </p>
      </article>

      <article className="grid two">
        {payload.cards.map((card) => (
          <div key={card.key} className="panel">
            <h2 style={{ marginTop: 0 }}>{card.title}</h2>
            <p className="mono">
              {t(locale, "summariesIsLabel")}: {card.headline_return_is}%
            </p>
            <p className="mono">
              {t(locale, "summariesAfterFrictionLabel")}: {card.headline_return_after_friction}%
            </p>
            <Link href={`/${locale}/verify/${card.proof_id}`}>/verify/{card.proof_id}</Link>
          </div>
        ))}
      </article>
    </section>
  );
}
