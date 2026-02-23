import { notFound } from "next/navigation";

import { parseLookback, parseRegime } from "@/lib/api";
import { DEFAULT_INDICATOR_SET, isSupportedIndicatorSet } from "@/lib/catalog";
import { coerceLocale } from "@/lib/i18n";
import { coerceCoin, isSupportedTimeframe } from "@/lib/market";
import { getPrecomputedAtlas } from "@/lib/precomputed";
import { buildPageMetadata } from "@/lib/seo";
import { t } from "@/lib/text";

export async function generateMetadata({ params }: { params: { locale: string; coin: string } }) {
  const locale = coerceLocale(params.locale);
  const coin = coerceCoin(params.coin);
  if (!locale || !coin) {
    return {};
  }
  return buildPageMetadata({
    locale,
    title: `${coin.toUpperCase()} ${t(locale, "atlas")}`,
    description: `${t(locale, "atlasMetaDescriptionPrefix")} ${coin.toUpperCase()}.`.trim(),
    pathWithoutLocale: `/atlas/${coin}`
  });
}

export default async function AtlasPage({
  params,
  searchParams
}: {
  params: { locale: string; coin: string };
  searchParams: { tf?: string; lookback?: string; regime?: string; indicator?: string };
}) {
  const locale = coerceLocale(params.locale);
  const coin = coerceCoin(params.coin);
  if (!locale || !coin) {
    notFound();
  }

  const timeframe = searchParams.tf ?? "1h";
  if (!isSupportedTimeframe(timeframe)) {
    notFound();
  }
  const lookback = parseLookback(searchParams.lookback ?? null);
  const regime = parseRegime(searchParams.regime ?? null);
  const indicatorSlug = (searchParams.indicator ?? DEFAULT_INDICATOR_SET).toLowerCase();
  if (!lookback || !regime || !isSupportedIndicatorSet(indicatorSlug)) {
    notFound();
  }

  const payload = await getPrecomputedAtlas({
    locale,
    coin,
    timeframe,
    indicatorSlug,
    lookback,
    regime
  });
  if (!payload) {
    notFound();
  }

  return (
    <section className="grid" style={{ gap: "1rem" }}>
      <article className="panel">
        <h1 style={{ marginTop: 0 }}>
          {t(locale, "atlasHeadingPrefix")} {payload.coin} {payload.timeframe}
        </h1>
        <p className="muted mono">
          {t(locale, "atlasIndicatorSetLabel")}={payload.indicatorSet.join(",")} | {t(locale, "atlasPointsLabel")}=
          {payload.points.length} | {t(locale, "atlasAsofLabel")}={payload.asof}
        </p>
        <p className="muted mono">
          {t(locale, "atlasTruthFlagsLabel")}={payload.truthFlags.join(",")} | {t(locale, "atlasPrecomputedLabel")}=
          {payload.precomputedAt}
        </p>
      </article>

      <article className="panel">
        <h2 style={{ marginTop: 0 }}>{t(locale, "atlasPeakCoordinate")}</h2>
        <pre className="mono">{JSON.stringify(payload.peak, null, 2)}</pre>
      </article>

      <article className="panel">
        <h2 style={{ marginTop: 0 }}>{t(locale, "atlasHeatmapGrid")}</h2>
        <pre className="mono" style={{ maxHeight: "360px", overflow: "auto" }}>
          {JSON.stringify(payload.points, null, 2)}
        </pre>
      </article>
    </section>
  );
}
