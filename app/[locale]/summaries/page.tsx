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
            <div className="mb-3 flex justify-between border-b border-[#39ff14]/20 pb-2 text-[9px] uppercase tracking-[0.14em]">
              <span className="animate-pulse text-[#ff3131]"> LIVE</span>
              <span className="text-[#39ff14]/50">NODE: K8S-01</span>
            </div>
            <h2 className="mb-4 border-b border-[#39ff14]/30 pb-2 text-base font-bold uppercase tracking-widest text-white">
              {card.title}
            </h2>
            <div className="grid grid-cols-2 gap-x-4 gap-y-3 border border-[#39ff14]/20 p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-[#39ff14]/60">{t(locale, "summariesIsLabel")}</p>
              <p className="text-right text-2xl font-bold tabular-nums text-[#39ff14]">{card.headline_return_is.toFixed(2)}%</p>
              <p className="text-[11px] uppercase tracking-[0.12em] text-[#39ff14]/60">{t(locale, "summariesAfterFrictionLabel")}</p>
              <p className="text-right text-2xl font-bold tabular-nums text-[#ff3131]">
                {card.headline_return_after_friction.toFixed(2)}%
              </p>
              <p className="text-[11px] uppercase tracking-[0.12em] text-[#39ff14]/60">PROOF_ID</p>
              <p className="truncate text-right text-[11px] font-bold uppercase tracking-[0.08em] text-white">{card.proof_id}</p>
            </div>
            <Link
              href={`/${locale}/verify/${card.proof_id}`}
              className="mt-4 inline-flex w-full items-center justify-center border border-[#39ff14]/30 px-3 py-2 text-[11px] font-bold uppercase tracking-[0.14em] text-[#39ff14] transition-colors hover:bg-[#39ff14] hover:text-black"
            >
              [ EXECUTE_VERIFICATION_SEQUENCE ]
            </Link>
          </div>
        ))}
      </article>
    </section>
  );
}
