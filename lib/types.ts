import type { SupportedLocale } from "@/lib/i18n";

export type Timeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
export type Regime = "all" | "bull" | "range" | "bear";

export type Candle = {
  openTime: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type PageDataRequest = {
  locale: SupportedLocale;
  coin: string;
  timeframe: Timeframe;
  indicatorSlug: string;
  lookback: string;
  regime: Regime;
};

export type StrategyRun = {
  params: Record<string, number>;
  equity: number;
  cagr: number;
  maxDrawdown: number;
  turnoverPenalty: number;
  tradeCount: number;
  score: number;
};

export type PageDataResult = {
  locale: SupportedLocale;
  coin: string;
  symbol: string;
  timeframe: Timeframe;
  lookback: string;
  regime: Regime;
  indicatorSet: string[];
  headlineReturnIS: number;
  headlineReturnAfterFriction: number;
  maxDrawdown: number;
  tradeCount: number;
  score: number;
  bestParams: Record<string, number>;
  proofId: string;
  asof: string;
  friction: {
    takerFeeBps: number;
    slippageBps: number;
    fundingBps: number;
    totalCostBpsPerRoundTrip: number;
  };
  disclaimerFlags: string[];
  analysis: string;
};

export type AtlasPoint = {
  x: number;
  y: number;
  score: number;
  returnAfterFriction: number;
};

export type AtlasResult = {
  locale: SupportedLocale;
  coin: string;
  symbol: string;
  timeframe: Timeframe;
  lookback: string;
  regime: Regime;
  indicatorSet: string[];
  points: AtlasPoint[];
  peak: AtlasPoint | null;
  asof: string;
};
