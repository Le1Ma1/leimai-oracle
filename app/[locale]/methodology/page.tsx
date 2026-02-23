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
    <section className="grid" style={{ gap: "1rem" }}>
      <article className="panel">
        <h1 style={{ marginTop: 0 }}>{t(locale, "methodologyHeading")}</h1>
        <p className="muted">{payload.objective}</p>
      </article>

      <article className="panel">
        <h2 style={{ marginTop: 0 }}>{t(locale, "methodologyConstraintsHeading")}</h2>
        <ul>
          {payload.constraints.map((item) => (
            <li key={item} className="mono">
              {item}
            </li>
          ))}
        </ul>
      </article>

      <article className="panel">
        <h2 style={{ marginTop: 0 }}>{t(locale, "methodologyScoringHeading")}</h2>
        <pre className="mono">{JSON.stringify({ scoring: payload.scoring, friction: payload.friction }, null, 2)}</pre>
      </article>
    </section>
  );
}
