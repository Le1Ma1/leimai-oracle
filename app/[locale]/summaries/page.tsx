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
    <section className="space-y-4">
      <article className="border border-[#39ff14]/30 bg-[#050505] p-6 md:p-8">
        <h1 className="mb-4 border-b border-[#39ff14]/30 pb-2 text-xl font-bold uppercase tracking-widest text-white">
          {t(locale, "summariesHeading")}
        </h1>
        <p className="text-sm leading-relaxed text-[#39ff14]/80">{t(locale, "summariesSubtitle")}</p>
        <p className="mt-3 border border-[#39ff14]/20 p-3 text-[11px] uppercase tracking-[0.12em] text-[#39ff14]/70">
          {t(locale, "summariesTruthFlags")}={t(locale, "disclaimerA")},{t(locale, "disclaimerB")},{t(locale, "disclaimerC")}
        </p>
      </article>

      <article className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {payload.cards.map((card) => (
          <div key={card.key} className="border border-[#39ff14]/30 bg-[#050505] p-6 md:p-8">
            <h2 className="mb-4 border-b border-[#39ff14]/30 pb-2 text-base font-bold uppercase tracking-widest text-white">
              {card.title}
            </h2>
            <div className="space-y-2 text-sm leading-relaxed text-[#39ff14]/80">
              <p>
                {t(locale, "summariesIsLabel")}: <span className="text-[#39ff14]">{card.headline_return_is}%</span>
              </p>
              <p>
                {t(locale, "summariesAfterFrictionLabel")}:{" "}
                <span className="text-[#ff3131]">{card.headline_return_after_friction}%</span>
              </p>
            </div>
            <Link
              href={`/${locale}/verify/${card.proof_id}`}
              className="mt-4 inline-block border border-[#39ff14]/30 px-3 py-1 text-xs uppercase tracking-[0.14em] text-[#39ff14] transition-colors hover:bg-[#39ff14] hover:text-black"
            >
              /verify/{card.proof_id}
            </Link>
          </div>
        ))}
      </article>
    </section>
  );
}
