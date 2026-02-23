import type { Timeframe } from "@/lib/types";

type PhaseBUpdateTier = {
  tier: "tier_1" | "tier_2" | "tier_3";
  label: string;
  timeframes: Timeframe[];
  cadenceHours: number;
  cadenceWindowHours: [number, number];
  target: "clickhouse";
};

export const PHASE_B_UPDATE_TIERS: PhaseBUpdateTier[] = [
  {
    tier: "tier_1",
    label: "High frequency",
    timeframes: ["1m", "5m"],
    cadenceHours: 6,
    cadenceWindowHours: [4, 6],
    target: "clickhouse"
  },
  {
    tier: "tier_2",
    label: "Medium frequency",
    timeframes: ["15m", "1h"],
    cadenceHours: 24,
    cadenceWindowHours: [24, 24],
    target: "clickhouse"
  },
  {
    tier: "tier_3",
    label: "Low frequency",
    timeframes: ["4h", "1d"],
    cadenceHours: 24 * 7,
    cadenceWindowHours: [24 * 7, 24 * 7],
    target: "clickhouse"
  }
];
