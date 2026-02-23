import { notFound } from "next/navigation";

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
    </main>
  );
}
