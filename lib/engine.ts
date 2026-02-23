import { createHash } from "node:crypto";

import { fetchCandles, normalizeSymbol, timeframeToMs } from "@/lib/market";
import { t } from "@/lib/text";
import type { AtlasPoint, AtlasResult, Candle, PageDataRequest, PageDataResult, Regime, StrategyRun } from "@/lib/types";

const ALLOWED_INDICATORS = new Set(["rsi", "macd", "bollinger", "ema"]);
const FALLBACK_INDICATORS = ["rsi", "macd"];

const FRICTION = {
  takerFeeBps: 10,
  slippageBps: 5,
  fundingBps: 2
};

function parseIndicators(slug: string): string[] {
  const cleaned = slug.toLowerCase().replace(/settings/g, "");
  const parts = cleaned
    .split("-")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => (item === "ema-cross" ? "ema" : item));
  const indicators = parts.filter((item) => ALLOWED_INDICATORS.has(item));
  const deduped = [...new Set(indicators)];
  return deduped.length ? deduped.slice(0, 3) : FALLBACK_INDICATORS;
}

function ema(values: number[], period: number): number[] {
  const alpha = 2 / (period + 1);
  const out = new Array(values.length).fill(values[0] ?? 0);
  for (let i = 1; i < values.length; i += 1) {
    out[i] = alpha * values[i] + (1 - alpha) * out[i - 1];
  }
  return out;
}

function rsi(values: number[], period: number): number[] {
  const out = new Array(values.length).fill(50);
  let gains = 0;
  let losses = 0;
  for (let i = 1; i <= period && i < values.length; i += 1) {
    const delta = values[i] - values[i - 1];
    if (delta >= 0) gains += delta;
    else losses -= delta;
  }
  let avgGain = gains / period;
  let avgLoss = losses / period;
  for (let i = period + 1; i < values.length; i += 1) {
    const delta = values[i] - values[i - 1];
    const gain = Math.max(delta, 0);
    const loss = Math.max(-delta, 0);
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
    out[i] = 100 - 100 / (1 + rs);
  }
  return out;
}

function rollingStd(values: number[], period: number): number[] {
  const out = new Array(values.length).fill(0);
  for (let i = period - 1; i < values.length; i += 1) {
    const window = values.slice(i - period + 1, i + 1);
    const mean = window.reduce((sum, n) => sum + n, 0) / window.length;
    const variance = window.reduce((sum, n) => sum + (n - mean) ** 2, 0) / window.length;
    out[i] = Math.sqrt(variance);
  }
  return out;
}

function cartesian(params: Record<string, number[]>): Record<string, number>[] {
  const keys = Object.keys(params);
  if (!keys.length) {
    return [{}];
  }
  const result: Record<string, number>[] = [];
  const walk = (idx: number, current: Record<string, number>) => {
    if (idx >= keys.length) {
      result.push({ ...current });
      return;
    }
    const key = keys[idx];
    for (const value of params[key]) {
      current[key] = value;
      walk(idx + 1, current);
    }
  };
  walk(0, {});
  return result.slice(0, 80);
}

function buildParameterSpace(indicators: string[]): Record<string, number[]> {
  const params: Record<string, number[]> = {};
  if (indicators.includes("rsi")) {
    params.rsiPeriod = [7, 14];
    params.rsiLower = [25, 30, 35];
    params.rsiUpper = [65, 70, 75];
  }
  if (indicators.includes("macd")) {
    params.macdFast = [8, 12];
    params.macdSlow = [21, 26];
    params.macdSignal = [9];
  }
  if (indicators.includes("ema")) {
    params.emaShort = [8, 12];
    params.emaLong = [21, 34, 55];
  }
  if (indicators.includes("bollinger")) {
    params.bbPeriod = [20];
    params.bbK = [18, 20, 22];
  }
  return params;
}

function applyRegime(candles: Candle[], regime: Regime): Candle[] {
  if (regime === "all") {
    return candles;
  }
  const close = candles.map((c) => c.close);
  const trend = ema(close, 100);
  const filtered = candles.filter((candle, idx) => {
    const delta = candle.close / (trend[idx] || candle.close) - 1;
    if (regime === "bull") return delta > 0.01;
    if (regime === "bear") return delta < -0.01;
    return Math.abs(delta) <= 0.01;
  });
  return filtered.length >= 120 ? filtered : candles;
}

function backtest(candles: Candle[], indicators: string[], params: Record<string, number>): StrategyRun {
  const close = candles.map((c) => c.close);
  const baseEmaShort = ema(close, params.emaShort ?? 12);
  const baseEmaLong = ema(close, params.emaLong ?? 26);
  const rsiSeries = rsi(close, params.rsiPeriod ?? 14);
  const macdFast = ema(close, params.macdFast ?? 12);
  const macdSlow = ema(close, params.macdSlow ?? 26);
  const macdLine = macdFast.map((value, i) => value - macdSlow[i]);
  const macdSignal = ema(macdLine, params.macdSignal ?? 9);
  const bbPeriod = params.bbPeriod ?? 20;
  const bbMid = ema(close, bbPeriod);
  const bbStd = rollingStd(close, bbPeriod);
  const bbK = (params.bbK ?? 20) / 10;
  const bbUpper = bbMid.map((mid, i) => mid + bbStd[i] * bbK);
  const bbLower = bbMid.map((mid, i) => mid - bbStd[i] * bbK);

  const warmup = 120;
  let equity = 1;
  let inPosition = false;
  let entryPrice = 0;
  let trades = 0;
  const curve: number[] = [];

  for (let i = warmup; i < close.length; i += 1) {
    const buySignals: boolean[] = [];
    const sellSignals: boolean[] = [];

    if (indicators.includes("rsi")) {
      buySignals.push(rsiSeries[i] < (params.rsiLower ?? 30));
      sellSignals.push(rsiSeries[i] > (params.rsiUpper ?? 70));
    }
    if (indicators.includes("macd")) {
      buySignals.push(macdLine[i] > macdSignal[i]);
      sellSignals.push(macdLine[i] < macdSignal[i]);
    }
    if (indicators.includes("ema")) {
      buySignals.push(baseEmaShort[i] > baseEmaLong[i]);
      sellSignals.push(baseEmaShort[i] < baseEmaLong[i]);
    }
    if (indicators.includes("bollinger")) {
      buySignals.push(close[i] < bbLower[i]);
      sellSignals.push(close[i] > bbUpper[i] || close[i] > bbMid[i]);
    }

    const buy = buySignals.length ? buySignals.every(Boolean) : false;
    const sell = sellSignals.length ? sellSignals.some(Boolean) : false;

    if (!inPosition && buy) {
      inPosition = true;
      entryPrice = close[i];
      trades += 1;
    } else if (inPosition && sell) {
      equity *= close[i] / entryPrice;
      inPosition = false;
      entryPrice = 0;
    }

    const markToMarket = inPosition ? equity * (close[i] / entryPrice) : equity;
    curve.push(markToMarket);
  }

  if (inPosition) {
    equity *= close[close.length - 1] / entryPrice;
  }

  let peak = 1;
  let maxDrawdown = 0;
  for (const point of curve) {
    peak = Math.max(peak, point);
    const dd = peak === 0 ? 0 : (peak - point) / peak;
    maxDrawdown = Math.max(maxDrawdown, dd);
  }

  const durationMs = candles[candles.length - 1].openTime - candles[0].openTime;
  const years = Math.max(1 / 365, durationMs / (365 * 24 * 60 * 60 * 1000));
  const cagr = Math.pow(Math.max(equity, 0.0001), 1 / years) - 1;
  const turnoverPenalty = trades / Math.max(1, candles.length / 32);
  const score = cagr - 0.5 * maxDrawdown - 0.1 * turnoverPenalty;

  return {
    params,
    equity,
    cagr,
    maxDrawdown,
    turnoverPenalty,
    tradeCount: trades,
    score
  };
}

function applyFriction(equity: number, tradeCount: number): number {
  const perRoundTripBps = (FRICTION.takerFeeBps + FRICTION.slippageBps) * 2 + FRICTION.fundingBps;
  const multiplier = Math.pow(1 - perRoundTripBps / 10_000, tradeCount);
  return equity * multiplier;
}

function createProofId(input: {
  symbol: string;
  timeframe: string;
  lookback: string;
  regime: string;
  indicatorSlug: string;
  params: Record<string, number>;
  asof: number;
}): string {
  const raw = JSON.stringify(input);
  return createHash("sha256").update(raw).digest("hex").slice(0, 24);
}

function percent(value: number): number {
  return Number((value * 100).toFixed(2));
}

function sortRuns(runs: StrategyRun[]): StrategyRun[] {
  return [...runs].sort((a, b) => b.score - a.score);
}

export async function computePageData(input: PageDataRequest): Promise<PageDataResult> {
  const symbol = normalizeSymbol(input.coin);
  const indicators = parseIndicators(input.indicatorSlug);
  const candles = await fetchCandles({
    symbol,
    timeframe: input.timeframe,
    lookback: input.lookback
  });
  const regimeCandles = applyRegime(candles, input.regime);
  const paramSpace = buildParameterSpace(indicators);
  const candidates = cartesian(paramSpace);
  const runs = sortRuns(candidates.map((params) => backtest(regimeCandles, indicators, params)));
  const winner = runs[0];
  const frictionEquity = applyFriction(winner.equity, winner.tradeCount);
  const nowIso = new Date().toISOString();
  const proofId = createProofId({
    symbol,
    timeframe: input.timeframe,
    lookback: input.lookback,
    regime: input.regime,
    indicatorSlug: input.indicatorSlug,
    params: winner.params,
    asof: regimeCandles[regimeCandles.length - 1].openTime
  });

  return {
    locale: input.locale,
    coin: input.coin.toUpperCase(),
    symbol,
    timeframe: input.timeframe,
    lookback: input.lookback,
    regime: input.regime,
    indicatorSet: indicators,
    headlineReturnIS: percent(winner.equity - 1),
    headlineReturnAfterFriction: percent(frictionEquity - 1),
    maxDrawdown: percent(winner.maxDrawdown),
    tradeCount: winner.tradeCount,
    score: Number(winner.score.toFixed(4)),
    bestParams: winner.params,
    proofId,
    asof: nowIso,
    friction: {
      ...FRICTION,
      totalCostBpsPerRoundTrip: (FRICTION.takerFeeBps + FRICTION.slippageBps) * 2 + FRICTION.fundingBps
    },
    disclaimerFlags: [t(input.locale, "disclaimerA"), t(input.locale, "disclaimerB"), t(input.locale, "disclaimerC")],
    analysis: `${t(input.locale, "analysisPrefix")} IS=${percent(winner.equity - 1)}%, friction-adjusted=${percent(
      frictionEquity - 1
    )}%, trades=${winner.tradeCount}.`
  };
}

export async function computeAtlas(input: Omit<PageDataRequest, "indicatorSlug"> & { indicatorSlug: string }): Promise<AtlasResult> {
  const symbol = normalizeSymbol(input.coin);
  const indicators = parseIndicators(input.indicatorSlug);
  const candles = await fetchCandles({
    symbol,
    timeframe: input.timeframe,
    lookback: input.lookback
  });
  const regimeCandles = applyRegime(candles, input.regime);
  const paramSpace = buildParameterSpace(indicators);
  const candidates = cartesian(paramSpace);
  const points: AtlasPoint[] = candidates.slice(0, 60).map((params) => {
    const run = backtest(regimeCandles, indicators, params);
    const frictionEquity = applyFriction(run.equity, run.tradeCount);
    const values = Object.values(params);
    return {
      x: values[0] ?? 0,
      y: values[1] ?? 0,
      score: Number(run.score.toFixed(4)),
      returnAfterFriction: percent(frictionEquity - 1)
    };
  });
  const peak = points.length
    ? points.reduce((best, curr) => (curr.score > best.score ? curr : best), points[0])
    : null;
  return {
    locale: input.locale,
    coin: input.coin.toUpperCase(),
    symbol,
    timeframe: input.timeframe,
    lookback: input.lookback,
    regime: input.regime,
    indicatorSet: indicators,
    points,
    peak,
    asof: new Date().toISOString()
  };
}

export function buildMethodologyData(locale: PageDataRequest["locale"]) {
  return {
    locale,
    objective:
      "Programmatic historical parameter exploration with deterministic scoring and friction-aware adjustment.",
    constraints: [
      "IN_SAMPLE_ONLY",
      "BAR_CLOSE_EXECUTION_ASSUMPTION",
      "NOT_INVESTMENT_ADVICE",
      "BINANCE_MARKET_DATA_SOURCE"
    ],
    scoring: "score = CAGR - 0.5 * MaxDrawdown - 0.1 * TurnoverPenalty",
    friction: FRICTION,
    locales: ["en", "zh-TW", "ko", "tr", "vi"]
  };
}

export async function buildSummariesData(input: Pick<PageDataRequest, "locale"> & { symbol?: string }) {
  const coin = (input.symbol || "BTC").replace(/USDT$/i, "");
  const page = await computePageData({
    locale: input.locale,
    coin,
    timeframe: "1h",
    indicatorSlug: "macd-rsi",
    lookback: "90d",
    regime: "all"
  });
  return {
    locale: input.locale,
    cards: [
      {
        key: `${page.symbol}-1h-macd-rsi`,
        title: `${page.symbol} 1h MACD+RSI`,
        headline_return_is: page.headlineReturnIS,
        headline_return_after_friction: page.headlineReturnAfterFriction,
        proof_id: page.proofId
      }
    ]
  };
}

export function expectedBars(input: { lookback: string; timeframe: PageDataRequest["timeframe"] }): number {
  return Math.floor((90 * 86_400_000) / timeframeToMs(input.timeframe));
}
