import type { TruthFlag } from "@/lib/types";

export const TRUTH_FLAGS: TruthFlag[] = [
  "THEORETICAL",
  "IN_SAMPLE",
  "SNAPSHOT",
  "NOT_OOS",
  "NOT_EXECUTABLE",
  "NOT_ADVICE"
];

export const IS_SAMPLE_SCOPE = "in-sample" as const;
export const DATA_SOURCE = "binance_api" as const;

