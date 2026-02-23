import { notFound } from "next/navigation";

import Link from "next/link";

import { LocaleNav } from "@/components/LocaleNav";
import { coerceLocale } from "@/lib/i18n";

export default function LocaleLayout({
  children,
  params
}: {
  children: React.ReactNode;
  params: { locale: string };
}) {
  const locale = coerceLocale(params.locale);
  if (!locale) {
    notFound();
  }

  return (
    <main className="shell">
      <LocaleNav locale={locale} />
      {children}
      <footer className="panel" style={{ marginTop: "1rem" }}>
        <p className="muted" style={{ marginTop: 0 }}>
          LeiMai Oracle publishes historical in-sample research snapshots only. Results are not out-of-sample forecasts and
          are not investment advice.
        </p>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
          {["IN_SAMPLE", "NOT_OOS", "NOT_ADVICE"].map((flag) => (
            <span key={flag} className="badge">
              {flag}
            </span>
          ))}
          <Link href={`/${locale}/methodology`} className="mono">
            Methodology
          </Link>
        </div>
      </footer>
    </main>
  );
}
