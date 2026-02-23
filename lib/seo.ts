import type { Metadata } from "next";

import { DEFAULT_LOCALE, SUPPORTED_LOCALES, type SupportedLocale } from "@/lib/i18n";

const BASE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://leimaitech.com";

export function getBaseUrl(): URL {
  return new URL(BASE_URL);
}

export function buildAlternates(pathWithoutLocale: string): Metadata["alternates"] {
  const clean = pathWithoutLocale.startsWith("/") ? pathWithoutLocale : `/${pathWithoutLocale}`;
  const languages = Object.fromEntries(
    SUPPORTED_LOCALES.map((locale) => [locale, `/${locale}${clean === "/" ? "" : clean}`])
  );

  return {
    canonical: `/${DEFAULT_LOCALE}${clean === "/" ? "" : clean}`,
    languages: {
      ...languages,
      "x-default": `/${DEFAULT_LOCALE}${clean === "/" ? "" : clean}`
    }
  };
}

export function buildPageMetadata(input: {
  locale: SupportedLocale;
  title: string;
  description: string;
  pathWithoutLocale: string;
}): Metadata {
  return {
    title: input.title,
    description: input.description,
    metadataBase: getBaseUrl(),
    alternates: buildAlternates(input.pathWithoutLocale),
    openGraph: {
      title: input.title,
      description: input.description,
      url: `/${input.locale}${input.pathWithoutLocale === "/" ? "" : input.pathWithoutLocale}`,
      images: ["/logo.png"]
    },
    twitter: {
      card: "summary_large_image",
      title: input.title,
      description: input.description,
      images: ["/logo.png"]
    },
    icons: {
      icon: [
        { url: "/favicon.ico", sizes: "any" },
        { url: "/icon-32x32.png", sizes: "32x32", type: "image/png" },
        { url: "/icon-192x192.png", sizes: "192x192", type: "image/png" }
      ],
      shortcut: ["/favicon.ico"],
      apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }]
    }
  };
}

export function buildHreflangRecord(pathWithoutLocale: string): Record<string, string> {
  const clean = pathWithoutLocale.startsWith("/") ? pathWithoutLocale : `/${pathWithoutLocale}`;
  const base = getBaseUrl().toString().replace(/\/$/, "");
  return Object.fromEntries(
    SUPPORTED_LOCALES.map((locale) => [locale, `${base}/${locale}${clean === "/" ? "" : clean}`])
  );
}
