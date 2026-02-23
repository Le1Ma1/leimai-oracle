import { notFound } from "next/navigation";

import { computeAtlas } from "@/lib/engine";
import { coerceLocale } from "@/lib/i18n";
import { isSupportedTimeframe } from "@/lib/market";
import { buildPageMetadata } from "@/lib/seo";

export async function generateMetadata({ params }: { params: { locale: string; coin: string } }) {
  const locale = coerceLocale(params.locale);
  if (!locale) {
    return {};
  }
  return buildPageMetadata({
    locale,
    title: `${params.coin.toUpperCase()} Atlas | Panopticon`,
    description: `Parameter surface atlas for ${params.coin.toUpperCase()}.`,
    pathWithoutLocale: `/atlas/${params.coin}`
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
  if (!locale) {
    notFound();
  }

  const timeframe = searchParams.tf ?? "1h";
  if (!isSupportedTimeframe(timeframe)) {
    notFound();
  }

  const payload = await computeAtlas({
    locale,
    coin: params.coin,
    timeframe,
    indicatorSlug: searchParams.indicator ?? "macd-rsi",
    lookback: searchParams.lookback ?? "90d",
    regime: (searchParams.regime ?? "all") as "all" | "bull" | "range" | "bear"
  });

  return (
    <section className="grid" style={{ gap: "1rem" }}>
      <article className="panel">
        <h1 style={{ marginTop: 0 }}>
          Atlas {payload.coin} {payload.timeframe}
        </h1>
        <p className="muted mono">
          indicator_set={payload.indicatorSet.join(",")} | points={payload.points.length} | asof={payload.asof}
        </p>
      </article>

      <article className="panel">
        <h2 style={{ marginTop: 0 }}>Peak Coordinate</h2>
        <pre className="mono">{JSON.stringify(payload.peak, null, 2)}</pre>
      </article>

      <article className="panel">
        <h2 style={{ marginTop: 0 }}>Heatmap Grid (MVP JSON)</h2>
        <pre className="mono" style={{ maxHeight: "360px", overflow: "auto" }}>
          {JSON.stringify(payload.points, null, 2)}
        </pre>
      </article>
    </section>
  );
}
