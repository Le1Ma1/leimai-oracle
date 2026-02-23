import type { Regime, Timeframe } from "@/lib/types";
import { DEFAULT_COIN, DEFAULT_LOOKBACK, SUPPORTED_COINS, SUPPORTED_LOOKBACKS, SUPPORTED_TIMEFRAMES, type SupportedCoin, type SupportedLookback } from "@/lib/market";

export const SUPPORTED_REGIMES: Regime[] = ["all", "bull", "range", "bear"];

export const SUPPORTED_INDICATOR_SETS = ["macd-rsi", "ema-bollinger", "rsi-macd"] as const;
export type SupportedIndicatorSet = (typeof SUPPORTED_INDICATOR_SETS)[number];

export const DEFAULT_TIMEFRAME: Timeframe = "1h";
export const DEFAULT_REGIME: Regime = "all";
export const DEFAULT_INDICATOR_SET: SupportedIndicatorSet = "macd-rsi";

export const SITEMAP_TIER_1_COINS: SupportedCoin[] = ["btc", "eth"];
export const SITEMAP_TIER_2_COINS: SupportedCoin[] = ["sol", "bnb", "xrp"];

export function isSupportedRegime(value: string): value is Regime {
  return SUPPORTED_REGIMES.includes(value as Regime);
}

export function isSupportedIndicatorSet(value: string): value is SupportedIndicatorSet {
  return SUPPORTED_INDICATOR_SETS.includes(value as SupportedIndicatorSet);
}

export function buildQueryKey(input: {
  coin: SupportedCoin;
  timeframe: Timeframe;
  lookback: SupportedLookback;
  regime: Regime;
  indicatorSlug: SupportedIndicatorSet;
}): string {
  return [input.coin, input.timeframe, input.lookback, input.regime, input.indicatorSlug].join("__");
}

export function getPrecomputeSpace() {
  return {
    coins: SUPPORTED_COINS,
    timeframes: SUPPORTED_TIMEFRAMES,
    lookbacks: SUPPORTED_LOOKBACKS,
    regimes: SUPPORTED_REGIMES,
    indicatorSets: SUPPORTED_INDICATOR_SETS
  };
}

export const DEFAULT_QUERY = {
  coin: DEFAULT_COIN,
  timeframe: DEFAULT_TIMEFRAME,
  lookback: DEFAULT_LOOKBACK,
  regime: DEFAULT_REGIME,
  indicatorSlug: DEFAULT_INDICATOR_SET
} as const;
