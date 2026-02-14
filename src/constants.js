const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];
const WINDOWS = ["7D", "30D", "180D", "All"];
const VARIANTS = ["long", "short", "long_short"];

const VARIANT_TIEBREAK_PRIORITY = {
  long: 3,
  long_short: 2,
  short: 1,
};

const MODALITY = "technical_indicators_plus_price_volume";
const METHOD_VERSION = "v0.1";
const FEE_ASSUMPTION = "mdp_v0_fee_assumption";
const SLIPPAGE_ASSUMPTION = "mdp_v0_slippage_assumption";
const PAYMENT_MATCH_WINDOW_MS = 30 * 60 * 1000;

const UNIVERSE = [
  "ASSET_01",
  "ASSET_02",
  "ASSET_03",
  "ASSET_04",
  "ASSET_05",
  "ASSET_06",
  "ASSET_07",
  "ASSET_08",
  "ASSET_09",
  "ASSET_10",
  "ASSET_11",
  "ASSET_12",
  "ASSET_13",
  "ASSET_14",
  "ASSET_15",
  "ASSET_16",
  "ASSET_17",
  "ASSET_18",
  "ASSET_19",
  "ASSET_20",
  "ASSET_21",
  "ASSET_22",
  "ASSET_23",
  "ASSET_24",
];

module.exports = {
  FEE_ASSUMPTION,
  METHOD_VERSION,
  MODALITY,
  PAYMENT_MATCH_WINDOW_MS,
  SLIPPAGE_ASSUMPTION,
  TIMEFRAMES,
  UNIVERSE,
  VARIANTS,
  VARIANT_TIEBREAK_PRIORITY,
  WINDOWS,
};
