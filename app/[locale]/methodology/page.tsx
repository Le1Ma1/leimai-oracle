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
        <pre className="overflow-x-auto border border-[#39ff14]/20 p-4 text-xs leading-relaxed text-[#39ff14]/80">
          {JSON.stringify({ scoring: payload.scoring, friction: payload.friction }, null, 2)}
        </pre>
      </article>
    </section>
  );
}
