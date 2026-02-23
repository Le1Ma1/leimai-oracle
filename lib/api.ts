import { coerceLocale, DEFAULT_LOCALE } from "@/lib/i18n";
import { isSupportedTimeframe } from "@/lib/market";
import type { Regime, Timeframe } from "@/lib/types";

export function parseLocale(input: string | null): ReturnType<typeof coerceLocale> {
  return coerceLocale(input ?? "");
}

export function parseTimeframe(input: string | null): Timeframe | null {
  if (!input) {
    return null;
  }
  return isSupportedTimeframe(input) ? input : null;
}

export function parseRegime(input: string | null): Regime {
  if (input === "bull" || input === "bear" || input === "range") {
    return input;
  }
  return "all";
}

export function parseLookback(input: string | null): string {
  if (!input) return "90d";
  const allowed = new Set(["30d", "90d", "1y", "3y", "all"]);
  return allowed.has(input) ? input : "90d";
}

export function parseCoin(input: string | null): string {
  const token = (input ?? "btc").trim().toLowerCase();
  return token || "btc";
}

export function parseIndicator(input: string | null): string {
  return (input ?? "macd-rsi").trim().toLowerCase() || "macd-rsi";
}

export function parseLocaleWithFallback(input: string | null) {
  return parseLocale(input) ?? DEFAULT_LOCALE;
}
