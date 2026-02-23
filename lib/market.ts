import JSZip from "jszip";

import type { Candle, Timeframe } from "@/lib/types";

const BINANCE_BASE_URL = "https://api.binance.com/api/v3/klines";
const BINANCE_ARCHIVE_BASE_URL = "https://data.binance.vision/data/spot/monthly/klines";
const DAY_MS = 86_400_000;
const LOOKBACK_2020_START_MS = Date.UTC(2020, 0, 1);
const BINANCE_API_LIMIT = 1000;
const MIN_REQUIRED_CANDLES = 100;
const SMALL_TIMEFRAME_SET = new Set<Timeframe>(["1m", "5m", "15m"]);

export const SUPPORTED_COINS = ["btc", "eth", "sol", "bnb", "xrp", "ada", "doge", "ton", "avax", "link"] as const;
export type SupportedCoin = (typeof SUPPORTED_COINS)[number];
export const DEFAULT_COIN: SupportedCoin = "btc";

export const SUPPORTED_TIMEFRAMES: Timeframe[] = ["1m", "5m", "15m", "1h", "4h", "1d"];
export const SUPPORTED_LOOKBACKS = ["30d", "90d", "1y", "2020-now"] as const;
export type SupportedLookback = (typeof SUPPORTED_LOOKBACKS)[number];
export const DEFAULT_LOOKBACK: SupportedLookback = "90d";

export type CandleFetchMode = "fast" | "hybrid";

const TIMEFRAME_TO_MS: Record<Timeframe, number> = {
  "1m": 60_000,
  "5m": 300_000,
  "15m": 900_000,
  "1h": 3_600_000,
  "4h": 14_400_000,
  "1d": 86_400_000
};

export function isSupportedTimeframe(value: string): value is Timeframe {
  return SUPPORTED_TIMEFRAMES.includes(value as Timeframe);
}

export function isSupportedCoin(value: string): value is SupportedCoin {
  return SUPPORTED_COINS.includes(value as SupportedCoin);
}

export function coerceCoin(value: string | null | undefined): SupportedCoin | null {
  if (!value) {
    return null;
  }
  const token = value.trim().toLowerCase();
  return isSupportedCoin(token) ? token : null;
}

export function isSupportedLookback(value: string): value is SupportedLookback {
  return SUPPORTED_LOOKBACKS.includes(value as SupportedLookback);
}

export function normalizeSymbol(coin: string): string {
  const token = coin.replace(/[^a-zA-Z0-9]/g, "").toUpperCase();
  if (token.endsWith("USDT")) {
    return token;
  }
  return `${token}USDT`;
}

export function timeframeToMs(tf: Timeframe): number {
  return TIMEFRAME_TO_MS[tf];
}

function lookbackToDays(lookback: SupportedLookback): number {
  switch (lookback) {
    case "30d":
      return 30;
    case "90d":
      return 90;
    case "1y":
      return 365;
    case "2020-now":
      return Math.max(1, Math.ceil((Date.now() - LOOKBACK_2020_START_MS) / DAY_MS));
    default:
      return 90;
  }
}

function lookbackToStartMs(lookback: SupportedLookback, nowMs: number): number {
  if (lookback === "2020-now") {
    return LOOKBACK_2020_START_MS;
  }
  return nowMs - lookbackToDays(lookback) * DAY_MS;
}

function alignToStep(ms: number, stepMs: number): number {
  return Math.floor(ms / stepMs) * stepMs;
}

function resolveLookbackWindow(lookback: SupportedLookback, timeframe: Timeframe) {
  const nowMs = Date.now();
  const tfMs = timeframeToMs(timeframe);
  const startMs = alignToStep(lookbackToStartMs(lookback, nowMs), tfMs);
  const endMs = alignToStep(nowMs, tfMs);
  return {
    startMs,
    endMs
  };
}

function resolveTargetBars(input: { lookback: SupportedLookback; timeframe: Timeframe; maxBars?: number | null }): number {
  if (input.maxBars === null) {
    return Number.POSITIVE_INFINITY;
  }
  if (typeof input.maxBars === "number") {
    return Math.max(MIN_REQUIRED_CANDLES, Math.floor(input.maxBars));
  }
  return barsForLookback(input.lookback, input.timeframe);
}

function clampWindowByTarget(input: {
  lookback: SupportedLookback;
  timeframe: Timeframe;
  targetBars: number;
}): { startMs: number; endMs: number } {
  const base = resolveLookbackWindow(input.lookback, input.timeframe);
  if (!Number.isFinite(input.targetBars)) {
    return base;
  }
  const tfMs = timeframeToMs(input.timeframe);
  const spanMs = Math.max(0, Math.floor(input.targetBars)) * tfMs;
  const startMs = Math.max(base.startMs, base.endMs - spanMs);
  return {
    startMs: alignToStep(startMs, tfMs),
    endMs: base.endMs
  };
}

function trimToTarget(candles: Candle[], targetBars: number): Candle[] {
  if (!Number.isFinite(targetBars) || candles.length <= targetBars) {
    return candles;
  }
  return candles.slice(candles.length - targetBars);
}

function makeArchiveMonthUrl(input: { symbol: string; timeframe: Timeframe; year: number; month: number }): string {
  const monthToken = String(input.month).padStart(2, "0");
  const filename = `${input.symbol}-${input.timeframe}-${input.year}-${monthToken}.zip`;
  return `${BINANCE_ARCHIVE_BASE_URL}/${input.symbol}/${input.timeframe}/${filename}`;
}

function iterateMonths(startMs: number, endMs: number): Array<{ year: number; month: number }> {
  const out: Array<{ year: number; month: number }> = [];
  const cursor = new Date(startMs);
  cursor.setUTCDate(1);
  cursor.setUTCHours(0, 0, 0, 0);

  const limit = new Date(endMs);
  limit.setUTCDate(1);
  limit.setUTCHours(0, 0, 0, 0);

  while (cursor.getTime() <= limit.getTime()) {
    out.push({
      year: cursor.getUTCFullYear(),
      month: cursor.getUTCMonth() + 1
    });
    cursor.setUTCMonth(cursor.getUTCMonth() + 1);
  }
  return out;
}

export function barsForLookback(lookback: SupportedLookback, timeframe: Timeframe): number {
  const days = lookbackToDays(lookback);
  const barsPerDay = Math.max(1, Math.floor(DAY_MS / timeframeToMs(timeframe)));
  return Math.max(120, Math.min(days * barsPerDay, 1000));
}

function parseKlineRow(row: unknown): Candle | null {
  if (!Array.isArray(row) || row.length < 6) {
    return null;
  }
  const openTime = Number(row[0]);
  const open = Number(row[1]);
  const high = Number(row[2]);
  const low = Number(row[3]);
  const close = Number(row[4]);
  const volume = Number(row[5]);
  if (![openTime, open, high, low, close, volume].every(Number.isFinite)) {
    return null;
  }
  return { openTime, open, high, low, close, volume };
}

function parseCsvLine(line: string): Candle | null {
  const trimmed = line.trim();
  if (!trimmed) {
    return null;
  }
  const parts = trimmed.split(",");
  if (parts.length < 6) {
    return null;
  }
  if (parts[0].toLowerCase().includes("open")) {
    return null;
  }
  const openTime = Number(parts[0]);
  const open = Number(parts[1]);
  const high = Number(parts[2]);
  const low = Number(parts[3]);
  const close = Number(parts[4]);
  const volume = Number(parts[5]);
  if (![openTime, open, high, low, close, volume].every(Number.isFinite)) {
    return null;
  }
  return { openTime, open, high, low, close, volume };
}

function dedupeAndSortCandles(candles: Candle[]): Candle[] {
  const byOpenTime = new Map<number, Candle>();
  for (const candle of candles) {
    byOpenTime.set(candle.openTime, candle);
  }
  return [...byOpenTime.values()].sort((a, b) => a.openTime - b.openTime);
}

function filterWindow(candles: Candle[], startMs: number, endMs: number): Candle[] {
  return candles.filter((candle) => candle.openTime >= startMs && candle.openTime <= endMs);
}

async function fetchArchiveMonthCandles(input: {
  symbol: string;
  timeframe: Timeframe;
  year: number;
  month: number;
}): Promise<Candle[]> {
  const archiveUrl = makeArchiveMonthUrl(input);
  const response = await fetch(archiveUrl, {
    method: "GET",
    cache: "no-store"
  });

  if (response.status === 404) {
    return [];
  }
  if (!response.ok) {
    throw new Error(`Binance archive fetch failed (${response.status}) ${archiveUrl}`);
  }

  const zipBuffer = await response.arrayBuffer();
  const zip = await JSZip.loadAsync(zipBuffer);
  const csvEntry = Object.values(zip.files).find((file) => !file.dir && file.name.toLowerCase().endsWith(".csv"));
  if (!csvEntry) {
    return [];
  }

  const csvText = await csvEntry.async("string");
  const rows = csvText
    .split(/\r?\n/)
    .map(parseCsvLine)
    .filter((item): item is Candle => item !== null);
  return rows;
}

async function fetchCandlesFromApiWindow(input: {
  symbol: string;
  timeframe: Timeframe;
  startMs: number;
  endMs: number;
}): Promise<Candle[]> {
  if (input.startMs > input.endMs) {
    return [];
  }

  const tfMs = timeframeToMs(input.timeframe);
  const rows: Candle[] = [];
  let cursor = input.startMs;

  while (cursor <= input.endMs) {
    const url = new URL(BINANCE_BASE_URL);
    url.searchParams.set("symbol", input.symbol);
    url.searchParams.set("interval", input.timeframe);
    url.searchParams.set("startTime", String(cursor));
    url.searchParams.set("endTime", String(input.endMs));
    url.searchParams.set("limit", String(BINANCE_API_LIMIT));

    const response = await fetch(url, {
      method: "GET",
      next: { revalidate: 300 }
    });

    if (!response.ok) {
      throw new Error(`Binance fetch failed (${response.status})`);
    }

    const json = (await response.json()) as unknown;
    if (!Array.isArray(json)) {
      throw new Error("Binance payload malformed");
    }

    const page = json.map(parseKlineRow).filter((item): item is Candle => item !== null);
    if (!page.length) {
      break;
    }

    rows.push(...page);
    const lastOpenTime = page[page.length - 1].openTime;
    const nextCursor = lastOpenTime + tfMs;
    if (nextCursor <= cursor) {
      break;
    }
    cursor = nextCursor;
    if (page.length < BINANCE_API_LIMIT) {
      break;
    }
  }

  return rows;
}

function findMissingRanges(input: {
  candles: Candle[];
  timeframe: Timeframe;
  startMs: number;
  endMs: number;
}): Array<{ startMs: number; endMs: number }> {
  if (!input.candles.length) {
    return [{ startMs: input.startMs, endMs: input.endMs }];
  }

  const tfMs = timeframeToMs(input.timeframe);
  const ranges: Array<{ startMs: number; endMs: number }> = [];
  const candles = input.candles;

  let firstOpen = candles[0].openTime;
  if (firstOpen > input.startMs) {
    ranges.push({ startMs: input.startMs, endMs: firstOpen - tfMs });
  }

  for (let i = 1; i < candles.length; i += 1) {
    const prev = candles[i - 1].openTime;
    const current = candles[i].openTime;
    if (current - prev <= tfMs) {
      continue;
    }
    ranges.push({
      startMs: prev + tfMs,
      endMs: current - tfMs
    });
  }

  const lastOpen = candles[candles.length - 1].openTime;
  if (lastOpen < input.endMs) {
    ranges.push({
      startMs: lastOpen + tfMs,
      endMs: input.endMs
    });
  }

  return ranges.filter((range) => range.startMs <= range.endMs);
}

async function fetchCandlesFromArchiveThenApi(input: {
  symbol: string;
  timeframe: Timeframe;
  startMs: number;
  endMs: number;
}): Promise<Candle[]> {
  const monthly = iterateMonths(input.startMs, input.endMs);
  const archiveRows: Candle[] = [];

  for (const month of monthly) {
    const rows = await fetchArchiveMonthCandles({
      symbol: input.symbol,
      timeframe: input.timeframe,
      year: month.year,
      month: month.month
    });
    if (rows.length) {
      archiveRows.push(...rows);
    }
  }

  let merged = dedupeAndSortCandles(filterWindow(archiveRows, input.startMs, input.endMs));
  const missingRanges = findMissingRanges({
    candles: merged,
    timeframe: input.timeframe,
    startMs: input.startMs,
    endMs: input.endMs
  });

  for (const range of missingRanges) {
    const gapRows = await fetchCandlesFromApiWindow({
      symbol: input.symbol,
      timeframe: input.timeframe,
      startMs: range.startMs,
      endMs: range.endMs
    });
    if (gapRows.length) {
      merged = dedupeAndSortCandles([...merged, ...gapRows]);
    }
  }

  return merged;
}

async function fetchCandlesFast(input: {
  symbol: string;
  timeframe: Timeframe;
  lookback: SupportedLookback;
  targetBars: number;
}): Promise<Candle[]> {
  const limit = Math.min(BINANCE_API_LIMIT, Math.max(MIN_REQUIRED_CANDLES, Math.floor(input.targetBars)));
  const url = new URL(BINANCE_BASE_URL);
  url.searchParams.set("symbol", input.symbol);
  url.searchParams.set("interval", input.timeframe);
  url.searchParams.set("limit", String(limit));

  const response = await fetch(url, {
    method: "GET",
    next: { revalidate: 300 }
  });

  if (!response.ok) {
    throw new Error(`Binance fetch failed (${response.status})`);
  }

  const json = (await response.json()) as unknown;
  if (!Array.isArray(json)) {
    throw new Error("Binance payload malformed");
  }

  return json.map(parseKlineRow).filter((item): item is Candle => item !== null);
}

export async function fetchCandles(input: {
  symbol: string;
  timeframe: Timeframe;
  lookback: SupportedLookback;
  mode?: CandleFetchMode;
  maxBars?: number | null;
}): Promise<Candle[]> {
  const mode = input.mode ?? "fast";
  const targetBars = resolveTargetBars({
    lookback: input.lookback,
    timeframe: input.timeframe,
    maxBars: input.maxBars
  });

  let rows: Candle[];
  if (mode === "hybrid" && SMALL_TIMEFRAME_SET.has(input.timeframe)) {
    const window = clampWindowByTarget({
      lookback: input.lookback,
      timeframe: input.timeframe,
      targetBars
    });
    rows = await fetchCandlesFromArchiveThenApi({
      symbol: input.symbol,
      timeframe: input.timeframe,
      startMs: window.startMs,
      endMs: window.endMs
    });
    rows = trimToTarget(rows, targetBars);
  } else {
    rows = await fetchCandlesFast({
      symbol: input.symbol,
      timeframe: input.timeframe,
      lookback: input.lookback,
      targetBars
    });
  }

  if (rows.length < MIN_REQUIRED_CANDLES) {
    throw new Error("Insufficient market data");
  }

  return rows;
}
