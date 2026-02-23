import Link from "next/link";
import { notFound } from "next/navigation";

import { buildPageMetadata } from "@/lib/seo";
import { t } from "@/lib/text";
import { coerceLocale } from "@/lib/i18n";

export async function generateMetadata({ params }: { params: { locale: string } }) {
  const locale = coerceLocale(params.locale);
  if (!locale) {
    return {};
  }
  return buildPageMetadata({
    locale,
    title: t(locale, "homeMetaTitle"),
    description: t(locale, "subtitle"),
    pathWithoutLocale: "/"
  });
}

export default function LocaleHomePage({ params }: { params: { locale: string } }) {
  const locale = coerceLocale(params.locale);
  if (!locale) {
    notFound();
  }

  const seeds = [
    { coin: "btc", tf: "15m", indicator: "macd-rsi", winRate: "64%", mdd: "-12%" },
    { coin: "eth", tf: "1h", indicator: "ema-bollinger", winRate: "59%", mdd: "-9%" },
    { coin: "sol", tf: "4h", indicator: "rsi-macd", winRate: "67%", mdd: "-18%" }
  ] as const;

  return (
    <section className="space-y-6 bg-[#050505] p-4 font-mono text-white md:p-6">
      <div className="border border-[#39ff14]/30 px-5 py-6 md:px-8 md:py-8">
        <div className="mb-4 flex flex-wrap gap-3 text-[10px] tracking-[0.18em] text-[#39ff14]">
          <span>{t(locale, "homeHeroModeTag")}</span>
          <span>{t(locale, "homeHeroStatusTag")}</span>
        </div>
        <h1 className="mb-3 text-xl font-bold tracking-[0.08em] text-white md:text-2xl">{t(locale, "title")}</h1>
        <p className="mb-3 text-[10px] tracking-[0.2em] text-[#39ff14]">{t(locale, "homeHeroAlphaLabel")}</p>
        <p className="mb-4 text-5xl font-bold leading-none text-[#39ff14] md:text-7xl">+8,420.55%</p>
        <p className="mb-4 max-w-4xl text-xs leading-relaxed text-[#39ff14]/90 md:text-sm">{t(locale, "subtitle")}</p>
        <div className="space-y-1 text-[11px] leading-relaxed text-white/80">
          <p>
            {t(locale, "homeRoutePattern")}: /{locale}/[coin]/[timeframe]/best-[indicator]-settings
          </p>
          <p>
            {t(locale, "homeLookbackLabel")}: 30d / 90d / 1y / 2020-now | {t(locale, "homeRegimeLabel")}: all / bull / range /
            bear
          </p>
        </div>
      </div>

      <div className="border border-[#39ff14]/30 px-5 py-6 md:px-8 md:py-8">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold tracking-[0.08em] text-white md:text-xl">{t(locale, "homeMatrixHeading")}</h2>
            <p className="mt-2 text-[11px] tracking-[0.14em] text-[#39ff14]/90">{t(locale, "homeMatrixSubheading")}</p>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          {seeds.map((seed) => (
            <Link
              key={`${seed.coin}-${seed.tf}-${seed.indicator}`}
              href={`/${locale}/${seed.coin}/${seed.tf}/best-${seed.indicator}-settings?lookback=90d&regime=all`}
              className="border border-[#39ff14]/20 px-4 py-4 transition-colors hover:bg-[#39ff14]/10"
            >
              <div className="mb-4 flex items-center justify-between">
                <p className="text-lg font-bold tracking-[0.06em] text-[#39ff14]">{seed.coin.toUpperCase()}</p>
                <p className="text-xs tracking-[0.14em] text-white/80">{seed.tf.toUpperCase()}</p>
              </div>

              <p className="mb-4 text-xs tracking-[0.12em] text-white/90">{seed.indicator.toUpperCase()}</p>

              <div className="space-y-1 text-[11px]">
                <p className="text-white/80">
                  {t(locale, "homeMatrixWinRateLabel")}: <span className="text-[#39ff14]">{seed.winRate}</span>
                </p>
                <p className="text-white/80">
                  {t(locale, "homeMatrixMddLabel")}: <span className="text-[#ff3131]">{seed.mdd}</span>
                </p>
              </div>

              <p className="mt-4 text-[10px] tracking-[0.14em] text-[#39ff14]">{t(locale, "homeOpenSnapshot")}</p>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}
