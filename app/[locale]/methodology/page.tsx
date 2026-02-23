import { notFound } from "next/navigation";

import { buildMethodologyData } from "@/lib/engine";
import { coerceLocale } from "@/lib/i18n";
import { buildPageMetadata } from "@/lib/seo";
import { t } from "@/lib/text";

export async function generateMetadata({ params }: { params: { locale: string } }) {
  const locale = coerceLocale(params.locale);
  if (!locale) {
    return {};
  }
  return buildPageMetadata({
    locale,
    title: t(locale, "methodologyMetaTitle"),
    description: t(locale, "methodologyMetaDescription"),
    pathWithoutLocale: "/methodology"
  });
}

export default function MethodologyPage({ params }: { params: { locale: string } }) {
  const locale = coerceLocale(params.locale);
  if (!locale) {
    notFound();
  }

  const payload = buildMethodologyData(locale);
  const scoringRows: Array<{ key: string; value: string }> = [
    { key: "SCORING_FORMULA", value: payload.scoring },
    { key: "CAGR_WEIGHT", value: "1.00" },
    { key: "MAX_DRAWDOWN_PENALTY", value: "0.50" },
    { key: "TURNOVER_PENALTY", value: "0.10" }
  ];
  const frictionRows: Array<{ key: string; value: string }> = [
    { key: "TAKER_FEE_BPS", value: String(payload.friction.takerFeeBps) },
    { key: "SLIPPAGE_BPS", value: String(payload.friction.slippageBps) },
    { key: "FUNDING_BPS", value: String(payload.friction.fundingBps) },
    {
      key: "ROUND_TRIP_TOTAL_BPS",
      value: String((payload.friction.takerFeeBps + payload.friction.slippageBps) * 2 + payload.friction.fundingBps)
    }
  ];

  return (
    <section className="space-y-4">
      <article className="border border-[#39ff14]/30 bg-[#050505] p-6 md:p-8">
        <h1 className="mb-4 border-b border-[#39ff14]/30 pb-2 text-xl font-bold uppercase tracking-widest text-white">
          {t(locale, "methodologyHeading")}
        </h1>
        <p className="text-sm leading-relaxed text-[#39ff14]/80">{payload.objective}</p>
      </article>

      <article className="border border-[#39ff14]/30 bg-[#050505] p-6 md:p-8">
        <h2 className="mb-4 border-b border-[#39ff14]/30 pb-2 text-lg font-bold uppercase tracking-widest text-white">
          {t(locale, "methodologyConstraintsHeading")}
        </h2>
        <ul className="space-y-2 text-sm leading-relaxed text-[#39ff14]/80">
          {payload.constraints.map((item) => (
            <li key={item} className="border border-[#39ff14]/20 px-3 py-2">
              {item}
            </li>
          ))}
        </ul>
      </article>

      <article className="border border-[#39ff14]/30 bg-[#050505] p-6 md:p-8">
        <h2 className="mb-4 border-b border-[#39ff14]/30 pb-2 text-lg font-bold uppercase tracking-widest text-white">
          {t(locale, "methodologyScoringHeading")}
        </h2>
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="border border-[#39ff14]/20 p-4">
            <p className="mb-3 border-b border-[#39ff14]/20 pb-2 text-[11px] uppercase tracking-[0.16em] text-white">Scoring Model</p>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2">
              {scoringRows.map((row) => (
                <div key={row.key} className="contents">
                  <span className="text-xs uppercase tracking-[0.12em] text-[#39ff14]/60">{row.key}</span>
                  <span className="text-right text-sm font-bold text-white">{row.value}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="border border-[#39ff14]/20 p-4">
            <p className="mb-3 border-b border-[#39ff14]/20 pb-2 text-[11px] uppercase tracking-[0.16em] text-white">Friction Registry</p>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2">
              {frictionRows.map((row) => (
                <div key={row.key} className="contents">
                  <span className="text-xs uppercase tracking-[0.12em] text-[#39ff14]/60">{row.key}</span>
                  <span className="text-right text-sm font-bold tabular-nums text-white">{row.value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </article>
    </section>
  );
}
