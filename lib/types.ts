import type { SupportedLocale } from "@/lib/i18n";

export type Coin = "btc" | "eth" | "sol" | "bnb" | "xrp" | "ada" | "doge" | "ton" | "avax" | "link";
export type Timeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
export type Lookback = "30d" | "90d" | "1y" | "2020-now";
export type Regime = "all" | "bull" | "range" | "bear";
export type IndicatorSetSlug = "macd-rsi" | "ema-bollinger" | "rsi-macd";
export type TruthFlag = "THEORETICAL" | "IN_SAMPLE" | "SNAPSHOT" | "NOT_OOS" | "NOT_EXECUTABLE" | "NOT_ADVICE";

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
  coin: Coin;
  timeframe: Timeframe;
  indicatorSlug: IndicatorSetSlug;
  lookback: Lookback;
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
  lookback: Lookback;
  regime: Regime;
  indicatorSlug: IndicatorSetSlug;
  indicatorSet: string[];
  headlineReturnIS: number;
  headlineReturnAfterFriction: number;
  maxDrawdown: number;
  tradeCount: number;
  score: number;
  bestParams: Record<string, number>;
  proofId: string;
  asof: string;
  isSampleScope: "in-sample";
  dataSource: "binance_api";
  precomputedAt: string;
  truthFlags: TruthFlag[];
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
  lookback: Lookback;
  regime: Regime;
  indicatorSlug: IndicatorSetSlug;
  indicatorSet: string[];
  points: AtlasPoint[];
  peak: AtlasPoint | null;
  asof: string;
  isSampleScope: "in-sample";
  dataSource: "binance_api";
  precomputedAt: string;
  truthFlags: TruthFlag[];
};

export type PageDataCore = Omit<PageDataResult, "locale" | "analysis" | "disclaimerFlags" | "precomputedAt">;

export type AtlasCore = Omit<AtlasResult, "locale" | "precomputedAt">;

export type SummariesCard = {
  key: string;
  title: string;
  headline_return_is: number;
  headline_return_after_friction: number;
  proof_id: string;
};

export type SummariesResult = {
  locale: SupportedLocale;
  cards: SummariesCard[];
};

export type PrecomputedManifest = {
  brand: "LeiMai Oracle";
  version: number;
  generatedAt: string;
  source: "binance_api";
  locales: SupportedLocale[];
  dimensions: {
    coins: Coin[];
    timeframes: Timeframe[];
    lookbacks: Lookback[];
    regimes: Regime[];
    indicatorSets: IndicatorSetSlug[];
  };
  coverage: {
    marketSlices: number;
    pageDataCombos: number;
    atlasCombos: number;
    summariesCoins: number;
  };
};
