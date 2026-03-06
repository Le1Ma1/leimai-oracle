# LeiMai Oracle Data Engine

## Setup

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -r engine/requirements.txt
```

## Configuration

Copy `engine/.env.example` to `.env`.

Default universe source is `ENGINE_UNIVERSE_SOURCE=coingecko_market_cap`:
- CoinGecko market-cap ranking
- Excludes stablecoins/wrapped/leveraged assets
- Keeps only assets with first 1m candle date on or before `2020-01-01`
- Optional explicit universe override: `ENGINE_UNIVERSE_SYMBOLS` (comma-separated `SYMBOLUSDT` list)

Iteration targets (Phase C gate):
- `ENGINE_OPTIMIZATION_MAX_ROUNDS`
- `ENGINE_OPT_TARGET_VALIDATION_PASS_RATE`
- `ENGINE_OPT_TARGET_ALL_WINDOW_ALPHA_FLOOR`
- `ENGINE_OPT_TARGET_DEPLOY_ALPHA_FLOOR`
- `ENGINE_OPT_TARGET_DEPLOY_SYMBOL_RATIO`

Gate and credibility thresholds (feature-native):
- `ENGINE_GATE_ORACLE_QUANTILE`
- `ENGINE_GATE_CONFIDENCE_QUANTILE`
- `ENGINE_CREDIBILITY_REJECT_THRESHOLD`
- `ENGINE_CREDIBLE_MAX_PENALTY`

Time-Bar Meta-Label Baseline v2 (binary only, no regression):
- `ENGINE_META_LABEL_ENABLED`
- `ENGINE_META_LABEL_MODEL=logreg` (phase-1 locked)
- `ENGINE_META_LABEL_OBJECTIVE=classification_binary` (regression forbidden)
- `ENGINE_META_LABEL_PENALTY` / `ENGINE_META_LABEL_C` / `ENGINE_META_LABEL_CLASS_WEIGHT`
- `ENGINE_META_LABEL_TP_MULT` / `ENGINE_META_LABEL_SL_MULT` / `ENGINE_META_LABEL_VERTICAL_HORIZON_BARS`
- `ENGINE_META_LABEL_PRECISION_FLOOR` / `ENGINE_META_LABEL_THRESHOLD_OBJECTIVE=f05`
- `ENGINE_META_LABEL_CPCV_*` (purge/embargo/splits)

## Run Once

```bash
python -m engine.src.main --mode once
```

Run once for a single symbol:

```bash
python -m engine.src.main --mode once --symbol BTCUSDT
```

Force optimization on/off for once mode:

```bash
python -m engine.src.main --mode once --optimize on
python -m engine.src.main --mode once --optimize off
```

## Alpha-First Aggressive Supervisor

Run explicit 15-symbol basket with aggressive alpha-first profile:

```bash
python scripts/alpha_supervisor.py --max-rounds 2
```

Skip ingestion and only run iterative optimization:

```bash
python scripts/alpha_supervisor.py --max-rounds 2 --skip-ingest
```

Dual-track BTC execution (legacy model + new nonlinear grid model):

```bash
python scripts/btc_phase_runner.py --profile dual_track_train --wait-existing
```

New-model only branch (still generates legacy progress report first):

```bash
python scripts/btc_phase_runner.py --profile nonlinear_grid_v1 --wait-existing
```

## Run Scheduler

```bash
python -m engine.src.main --mode scheduler
```

## Rebuild Validation Only

Rebuild `validation_report.json` and `deploy_pool.json` from the latest `summary.json` without rerunning optimization:

```bash
python -m engine.src.main --mode validate
```

Use an explicit summary path:

```bash
python -m engine.src.main --mode validate --summary-path /engine/artifacts/optimization/single/2026-02-25/summary.json
```

Optional runtime limiters for validation:

- `ENGINE_VALIDATION_LIGHT_MODE=true` (summary-driven fast validation, skips full signal rebuild)
- `ENGINE_VALIDATION_GATE_MODES=gated` (validate only one gate mode)
- `ENGINE_VALIDATION_MAX_RESULTS=90` (cap number of result rows validated)

## Optimization Artifacts

Single-indicator optimization output is written to:

- `engine/artifacts/optimization/single/<YYYY-MM-DD>/summary.json`
- `engine/artifacts/optimization/single/<YYYY-MM-DD>/symbol=<SYMBOL>/core=<CORE_ID>/gate=<MODE>/timeframe=<TF>.json`
- `engine/artifacts/optimization/single/<YYYY-MM-DD>/explainability.json`
- `engine/artifacts/optimization/single/<YYYY-MM-DD>/validation_report.json`
- `engine/artifacts/optimization/single/<YYYY-MM-DD>/deploy_pool.json`
- `engine/artifacts/optimization/single/iterations/<YYYY-MM-DD>/iteration_decision_log_*.json`

`summary.json` includes:
- `results_by_gate_mode` (gated + ungated)
- `delta_views` (gate delta by window + symbol-indicator gate delta + indicator delta)
- `health_dashboard` (gate-level health + target thresholds + top indicators)
- `rank_shift_gated_vs_ungated` (rank movement per symbol-indicator-window)
- `window_alpha_heatmap_payload` (window/symbol/indicator alpha matrix payload)
- `indicator_competition_overview` (indicator-level alpha/pass aggregate)

## Local-Only Execution Contract

This repository now runs as local-first only:

- optimization/validation execution stays on local machine
- monitor reads local status only (`engine/artifacts/monitor/live_status.json`)
- no cloud batch or remote manifest workflow is used
