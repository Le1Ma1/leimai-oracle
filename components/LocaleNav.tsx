import Link from "next/link";
import Image from "next/image";

import { SUPPORTED_LOCALES, type SupportedLocale } from "@/lib/i18n";
import { t } from "@/lib/text";

type Props = {
  locale: SupportedLocale;
};

const NAV_ITEMS: Array<{ key: "home" | "methodology" | "summaries" | "atlas"; href: string }> = [
  { key: "home", href: "" },
  { key: "methodology", href: "/methodology" },
  { key: "summaries", href: "/summaries" },
  { key: "atlas", href: "/atlas/btc" }
];

export function LocaleNav({ locale }: Props) {
  return (
    <header className="mb-6 border border-[#39ff14]/30 bg-[#050505] p-3">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex items-center gap-3">
          <Image src="/logo.png" alt={t(locale, "logoAlt")} width={32} height={32} />
          <div className="space-y-1">
            <p className="text-sm font-bold uppercase tracking-[0.14em] text-white">{t(locale, "title")}</p>
            <p className="text-[10px] tracking-[0.16em] text-[#39ff14]/70">{t(locale, "navEngineVersion")}</p>
          </div>
        </div>
        <nav className="flex flex-wrap items-center gap-2">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.key}
              href={`/${locale}${item.href}`}
              className="border border-[#39ff14]/30 px-3 py-1 text-xs uppercase tracking-[0.14em] text-[#39ff14] transition-colors hover:bg-[#39ff14] hover:text-black"
            >
              {t(locale, item.key)}
            </Link>
          ))}
        </nav>
      </div>
      <div className="mt-3 flex flex-wrap gap-2 border-t border-[#39ff14]/30 pt-3">
        {SUPPORTED_LOCALES.map((item) => (
          <Link
            key={item}
            href={`/${item}`}
            className={
              item === locale
                ? "bg-[#39ff14] px-2 py-1 text-[11px] uppercase tracking-[0.14em] text-black"
                : "border border-[#39ff14]/30 px-2 py-1 text-[11px] uppercase tracking-[0.14em] text-[#39ff14]/60 transition-colors hover:bg-[#39ff14] hover:text-black"
            }
          >
            {item}
          </Link>
        ))}
      </div>
    </header>
  );
}
