import Link from "next/link";
import { notFound } from "next/navigation";

import { isSupportedIndicatorSet } from "@/lib/catalog";
import { parseLookback, parseRegime } from "@/lib/api";
import { coerceLocale } from "@/lib/i18n";
import { coerceCoin, isSupportedTimeframe } from "@/lib/market";
import { getPrecomputedPageData } from "@/lib/precomputed";
import { buildPageMetadata } from "@/lib/seo";

function parseIndicatorRoute(route: string) {
  const match = /^best-([a-z0-9-]+)-settings$/i.exec(route);
  const indicator = match?.[1]?.toLowerCase();
  return indicator && isSupportedIndicatorSet(indicator) ? indicator : null;
}

export async function generateMetadata({
  params
}: {
  params: { locale: string; coin: string; timeframe: string; indicatorRoute: string };
}) {
  const locale = coerceLocale(params.locale);
  const indicatorSlug = parseIndicatorRoute(params.indicatorRoute);
  const coin = coerceCoin(params.coin);
  if (!locale || !coin || !indicatorSlug || !isSupportedTimeframe(params.timeframe)) {
    return {};
  }
  return buildPageMetadata({
    locale,
    title: `${params.coin.toUpperCase()} ${params.timeframe} ${indicatorSlug}`,
    description: `Historical in-sample snapshot for ${params.coin.toUpperCase()} ${params.timeframe}.`,
    pathWithoutLocale: `/${params.coin}/${params.timeframe}/${params.indicatorRoute}`
  });
}

export default async function BestIndicatorPage({
  params,
  searchParams
}: {
  params: { locale: string; coin: string; timeframe: string; indicatorRoute: string };
  searchParams: { lookback?: string; regime?: string };
}) {
  const locale = coerceLocale(params.locale);
  const coin = coerceCoin(params.coin);
  const indicatorSlug = parseIndicatorRoute(params.indicatorRoute);
  if (!locale || !coin || !indicatorSlug || !isSupportedTimeframe(params.timeframe)) {
    notFound();
  }

  const lookback = parseLookback(searchParams.lookback ?? null);
  const regime = parseRegime(searchParams.regime ?? null);
  if (!lookback || !regime) {
    notFound();
  }

  const payload = await getPrecomputedPageData({
    locale,
    coin,
    timeframe: params.timeframe,
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
        <span className="badge">{payload.locale}</span>
        <h1 style={{ marginTop: "0.75rem" }}>
          {payload.coin} {payload.timeframe} best-{indicatorSlug}-settings
        </h1>
        <p className="muted mono">
          symbol={payload.symbol} | lookback={payload.lookback} | regime={payload.regime} | proof={payload.proofId}
        </p>
      </article>

      <article className="grid two">
        <div className="panel">
          <div className="muted">HISTORICAL RETURN (IN-SAMPLE)</div>
          <div className="kpi">{payload.headlineReturnIS}%</div>
        </div>
        <div className="panel">
          <div className="muted">AFTER FRICTION</div>
          <div className="kpi">{payload.headlineReturnAfterFriction}%</div>
        </div>
      </article>

      <article className="panel">
        <h2 style={{ marginTop: 0 }}>Best Params</h2>
        <pre className="mono" style={{ overflowX: "auto" }}>
          {JSON.stringify(payload.bestParams, null, 2)}
        </pre>
        <p className="muted">{payload.analysis}</p>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          {payload.disclaimerFlags.map((flag) => (
            <span key={flag} className="badge">
              {flag}
            </span>
          ))}
        </div>
        <p className="muted mono" style={{ marginTop: "0.75rem" }}>
          truth_flags={payload.truthFlags.join(",")} | precomputed_at={payload.precomputedAt}
        </p>
      </article>

      <article className="panel">
        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          <Link href={`/${locale}/atlas/${params.coin}?tf=${params.timeframe}&lookback=${lookback}&regime=${regime}`}>
            Open Atlas
          </Link>
          <Link href={`/${locale}/verify/${payload.proofId}`}>Open Verify</Link>
          <Link href={`/${locale}/methodology`}>Methodology</Link>
        </div>
      </article>
    </section>
  );
}
