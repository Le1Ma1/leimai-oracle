import type { SupportedLocale } from "@/lib/i18n";
import { EN_MESSAGES } from "@/lib/locales/en";
import type { LocaleMessages } from "@/lib/locales/schema";
import { ZH_CN_MESSAGES } from "@/lib/locales/zh-CN";
import { ZH_TW_MESSAGES } from "@/lib/locales/zh-TW";

type CoreLocale = "en" | "zh-TW" | "zh-CN";

export const CORE_LOCALE_MESSAGES: Record<CoreLocale, LocaleMessages> = {
  en: EN_MESSAGES,
  "zh-TW": ZH_TW_MESSAGES,
  "zh-CN": ZH_CN_MESSAGES
};

export type TextKey = keyof LocaleMessages;

const LOCALE_FALLBACK: Record<SupportedLocale, CoreLocale> = {
  en: "en",
  "zh-TW": "zh-TW",
  "zh-CN": "zh-CN",
  ko: "en",
  tr: "en",
  vi: "en"
};

export function t(locale: SupportedLocale, key: TextKey): string {
  const coreLocale = LOCALE_FALLBACK[locale] ?? "en";
  return CORE_LOCALE_MESSAGES[coreLocale][key] ?? CORE_LOCALE_MESSAGES.en[key];
}

export function getTextKeys(): TextKey[] {
  return Object.keys(CORE_LOCALE_MESSAGES.en) as TextKey[];
}
