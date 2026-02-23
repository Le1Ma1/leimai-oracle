import type { Candle, Timeframe } from "@/lib/types";

const BINANCE_BASE_URL = "https://api.binance.com/api/v3/klines";

export const SUPPORTED_TIMEFRAMES: Timeframe[] = ["1m", "5m", "15m", "1h", "4h", "1d"];
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

function lookbackToDays(lookback: string): number {
  switch (lookback) {
    case "30d":
      return 30;
    case "90d":
      return 90;
    case "1y":
      return 365;
    case "3y":
      return 365 * 3;
    case "all":
      return 365 * 5;
    default:
      return 90;
  }
}

export function barsForLookback(lookback: string, timeframe: Timeframe): number {
  const days = lookbackToDays(lookback);
  const barsPerDay = Math.max(1, Math.floor(86_400_000 / timeframeToMs(timeframe)));
  return Math.max(120, Math.min(days * barsPerDay, 1000));
}

function parseKline(row: unknown): Candle | null {
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

export async function fetchCandles(input: {
  symbol: string;
  timeframe: Timeframe;
  lookback: string;
}): Promise<Candle[]> {
  const limit = barsForLookback(input.lookback, input.timeframe);
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

  const rows = json.map(parseKline).filter((item): item is Candle => item !== null);
  if (rows.length < 100) {
    throw new Error("Insufficient market data");
  }
  return rows;
}
