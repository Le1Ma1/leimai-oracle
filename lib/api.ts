import { coerceLocale, DEFAULT_LOCALE } from "@/lib/i18n";
import { DEFAULT_INDICATOR_SET, DEFAULT_QUERY, isSupportedIndicatorSet, isSupportedRegime } from "@/lib/catalog";
import { coerceCoin, isSupportedLookback, isSupportedTimeframe } from "@/lib/market";
import type { Coin, IndicatorSetSlug, Lookback, Regime, Timeframe } from "@/lib/types";

export function parseLocale(input: string | null): ReturnType<typeof coerceLocale> {
  return coerceLocale(input ?? "");
}

export function parseTimeframe(input: string | null): Timeframe | null {
  if (!input) {
    return DEFAULT_QUERY.timeframe;
  }
  return isSupportedTimeframe(input) ? input : null;
}

export function parseRegime(input: string | null): Regime | null {
  if (!input) {
    return DEFAULT_QUERY.regime;
  }
  return isSupportedRegime(input) ? input : null;
}

export function parseLookback(input: string | null): Lookback | null {
  if (!input) {
    return DEFAULT_QUERY.lookback;
  }
  return isSupportedLookback(input) ? input : null;
}

export function parseCoin(input: string | null): Coin | null {
  if (!input) {
    return DEFAULT_QUERY.coin;
  }
  return coerceCoin(input);
}

export function parseIndicator(input: string | null): IndicatorSetSlug | null {
  if (!input) {
    return DEFAULT_INDICATOR_SET;
  }
  const token = input.trim().toLowerCase();
  return isSupportedIndicatorSet(token) ? token : null;
}

export function parseLocaleWithFallback(input: string | null) {
  return parseLocale(input) ?? DEFAULT_LOCALE;
}
