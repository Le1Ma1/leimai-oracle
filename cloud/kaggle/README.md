# Kaggle Runner

Use this folder to run matrix optimization on Kaggle CPU in batch mode.

## 1) Start notebook

- Open `cloud/kaggle/runner.ipynb` in Kaggle Notebook.
- Set `REPO_URL`, `GITHUB_TOKEN` (optional), `BRANCH`, `BATCH_INDEX`, `BATCH_TOTAL`.
- Token requirement (fine-grained PAT): grant repository `Le1Ma1/leimai-oracle` with `Contents: Read`.
- Set `GITHUB_USERNAME` to token owner (default `Le1Ma1`) for auth fallback mode.
- `SKIP_INGEST=True` no longer hard-fails on empty data: missing symbols are auto-ingested for safety.

## 2) Batch contract

- Batch split is symbol based.
- Runner auto-sets `ENGINE_TOP_N` to current batch size.
- If batch symbols have no local raw `1m` data, runner auto-ingests missing symbols before iterate.
- Keep `ENGINE_OPTIMIZATION_TIMEFRAMES=1m`.
- Recommended: run 3 batches (`1/3`, `2/3`, `3/3`) and then merge artifacts locally.

## 3) Manifest output

Notebook writes:

- `engine/artifacts/cloud/cloud_run_manifest.json`
- Includes `quality_snapshot` auto-derived from latest `summary.json`, `validation_report.json`, `deploy_pool.json`.

Monitor can read this path directly.

## 4) Pull back artifacts

After notebook run, upload produced artifacts to your Kaggle dataset and pull locally:

```bash
python scripts/cloud_data_sync.py pull --dataset <owner/dataset>
```
