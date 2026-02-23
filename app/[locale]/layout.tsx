import { notFound } from "next/navigation";

import Link from "next/link";

import { LocaleNav } from "@/components/LocaleNav";
import { coerceLocale } from "@/lib/i18n";
import { t } from "@/lib/text";

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
    <html lang={locale}>
      <body>
        <main className="shell">
          <LocaleNav locale={locale} />
          {children}
          <footer className="panel" style={{ marginTop: "1rem" }}>
            <p className="muted" style={{ marginTop: 0 }}>
              {t(locale, "footerDisclaimer")}
            </p>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
              {[t(locale, "disclaimerA"), t(locale, "disclaimerB"), t(locale, "disclaimerC")].map((flag) => (
                <span key={flag} className="badge">
                  {flag}
                </span>
              ))}
              <Link href={`/${locale}/methodology`} className="mono">
                {t(locale, "footerMethodologyLink")}
              </Link>
            </div>
          </footer>
        </main>
      </body>
    </html>
  );
}
