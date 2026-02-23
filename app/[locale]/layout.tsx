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

  const disclaimers = [t(locale, "disclaimerA"), t(locale, "disclaimerB"), t(locale, "disclaimerC")];
  const statusItems = [t(locale, "footerStatusPipeline"), t(locale, "footerStatusSource"), t(locale, "footerStatusScope")];

  return (
    <html lang={locale}>
      <body className="bg-[#050505] text-[#39ff14] font-mono">
        <main className="flex min-h-screen flex-col p-4 md:p-6">
          <LocaleNav locale={locale} />
          <div className="flex-1">{children}</div>
          <footer className="border-t border-[#39ff14]/30 pt-2 text-[10px] uppercase tracking-[0.12em] text-[#39ff14]/80">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="max-w-4xl leading-relaxed">{t(locale, "footerDisclaimer")}</p>
              <Link
                href={`/${locale}/methodology`}
                className="border border-[#39ff14]/30 px-2 py-1 text-[#39ff14] transition-colors hover:bg-[#39ff14] hover:text-black"
              >
                {t(locale, "footerMethodologyLink")}
              </Link>
            </div>
            <div className="mt-2 grid gap-2 md:grid-cols-2">
              <div className="flex flex-wrap gap-2">
                {disclaimers.map((item) => (
                  <span key={item} className="border border-[#39ff14]/30 px-2 py-1">
                    {item}
                  </span>
                ))}
              </div>
              <div className="flex flex-wrap gap-2 md:justify-end">
                {statusItems.map((item) => (
                  <span key={item} className="border border-[#39ff14]/30 px-2 py-1">
                    {item}
                  </span>
                ))}
              </div>
            </div>
          </footer>
        </main>
      </body>
    </html>
  );
}
