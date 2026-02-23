import Link from "next/link";
import Image from "next/image";

import { SUPPORTED_LOCALES, type SupportedLocale } from "@/lib/i18n";
import { t } from "@/lib/text";

type Props = {
  locale: SupportedLocale;
};

export function LocaleNav({ locale }: Props) {
  return (
    <header className="panel" style={{ marginBottom: "1rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: "0.75rem" }}>
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
          <Image src="/logo.png" alt={t(locale, "logoAlt")} width={32} height={32} />
          <strong>{t(locale, "title")}</strong>
          <span className="badge">{t(locale, "globalI18n")}</span>
        </div>
        <nav style={{ display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
          <Link href={`/${locale}`}>{t(locale, "home")}</Link>
          <Link href={`/${locale}/methodology`}>{t(locale, "methodology")}</Link>
          <Link href={`/${locale}/summaries`}>{t(locale, "summaries")}</Link>
          <Link href={`/${locale}/atlas/btc`}>{t(locale, "atlas")}</Link>
        </nav>
      </div>
      <div style={{ marginTop: "0.75rem", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        {SUPPORTED_LOCALES.map((item) => (
          <Link
            key={item}
            href={`/${item}`}
            className="mono"
            style={{
              border: "1px solid rgba(57,255,20,0.35)",
              borderRadius: "2px",
              padding: "0.2rem 0.5rem",
              color: item === locale ? "#050505" : "#39ff14",
              background: item === locale ? "#39ff14" : "transparent"
            }}
          >
            {item}
          </Link>
        ))}
      </div>
    </header>
  );
}
