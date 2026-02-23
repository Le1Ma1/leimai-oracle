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
    { coin: "btc", tf: "15m", indicator: "macd-rsi" },
    { coin: "eth", tf: "1h", indicator: "ema-bollinger" },
    { coin: "sol", tf: "4h", indicator: "rsi-macd" }
  ] as const;

  return (
    <section className="grid" style={{ gap: "1rem" }}>
      <article className="panel">
        <span className="badge">{locale}</span>
        <h1 style={{ marginTop: "0.75rem", marginBottom: "0.25rem" }}>{t(locale, "title")}</h1>
        <p className="muted">{t(locale, "subtitle")}</p>
        <p className="mono" style={{ marginTop: "0.75rem" }}>
          {t(locale, "homeRoutePattern")}: /{locale}/[coin]/[timeframe]/best-[indicator]-settings
        </p>
        <p className="mono">
          {t(locale, "homeLookbackLabel")}: 30d / 90d / 1y / 2020-now | {t(locale, "homeRegimeLabel")}: all / bull / range /
          bear
        </p>
      </article>

      <article className="grid two">
        {seeds.map((seed) => (
          <Link
            key={`${seed.coin}-${seed.tf}-${seed.indicator}`}
            href={`/${locale}/${seed.coin}/${seed.tf}/best-${seed.indicator}-settings?lookback=90d&regime=all`}
            className="panel"
            style={{ display: "block" }}
          >
            <h2 style={{ marginTop: 0, marginBottom: "0.4rem" }}>
              {seed.coin.toUpperCase()} {seed.tf} / {seed.indicator}
            </h2>
            <p className="muted">{t(locale, "homeOpenSnapshot")}</p>
          </Link>
        ))}
      </article>
    </section>
  );
}
