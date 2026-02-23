-- LeiMai Oracle i18n schema for ClickHouse.

CREATE TABLE IF NOT EXISTS candles_raw (
  symbol LowCardinality(String),
  timeframe LowCardinality(String),
  ts DateTime64(3, 'UTC'),
  open Float64,
  high Float64,
  low Float64,
  close Float64,
  volume Float64,
  source LowCardinality(String),
  ingested_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (symbol, timeframe, ts);

CREATE TABLE IF NOT EXISTS backtest_runs (
  run_id UUID,
  symbol LowCardinality(String),
  timeframe LowCardinality(String),
  lookback_window LowCardinality(String),
  regime LowCardinality(String),
  indicator_set_slug String,
  params_json String,
  cagr Float64,
  max_drawdown Float64,
  turnover_penalty Float64,
  score Float64,
  fee_model_bps UInt32,
  slippage_bps UInt32,
  funding_bps UInt32,
  asof_ts DateTime64(3, 'UTC'),
  config_version LowCardinality(String),
  created_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (symbol, timeframe, lookback_window, regime, indicator_set_slug, created_at);

CREATE TABLE IF NOT EXISTS best_params_snapshot (
  snapshot_id UUID,
  symbol LowCardinality(String),
  timeframe LowCardinality(String),
  lookback_window LowCardinality(String),
  regime LowCardinality(String),
  indicator_set_slug String,
  best_run_id UUID,
  headline_return_is Float64,
  headline_return_after_friction Float64,
  max_drawdown Float64,
  trade_count UInt32,
  proof_id String,
  asof_ts DateTime64(3, 'UTC'),
  rank_bucket LowCardinality(String),
  updated_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(asof_ts)
ORDER BY (symbol, timeframe, lookback_window, regime, indicator_set_slug);

CREATE TABLE IF NOT EXISTS content_keys (
  content_key String,
  content_type LowCardinality(String),
  version UInt32,
  updated_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY content_key;

CREATE TABLE IF NOT EXISTS content_i18n (
  content_key String,
  locale LowCardinality(String),
  title String,
  summary_md String,
  analysis_md String,
  faq_json String,
  schema_json String,
  updated_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (content_key, locale);

CREATE TABLE IF NOT EXISTS seo_pages (
  page_id UUID,
  locale LowCardinality(String),
  url_path String,
  content_key String,
  canonical_url String,
  hreflang_json String,
  index_priority Float64,
  updated_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (locale, url_path);
