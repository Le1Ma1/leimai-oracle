# Colab Runner (Fallback)

Use `cloud/colab/runner.ipynb` when Kaggle resources are unavailable.

## Notes

- Keep the same batch contract as Kaggle (`BATCH_INDEX`, `BATCH_TOTAL`).
- Keep `ENGINE_OPTIMIZATION_TIMEFRAMES=1m`.
- Batch runner auto-sets `ENGINE_TOP_N` to current batch size (e.g. `5` for 3-way split).
- If batch symbols have no local raw `1m` data, runner auto-ingests missing symbols before iterate.
- Default auth source is Colab Secrets via `google.colab.userdata.get()`.
- Add Secret `GITHUB_TOKEN` (required) and optional `GITHUB_USERNAME`.
- Manual fallback is still available via `MANUAL_GITHUB_TOKEN` / `MANUAL_GITHUB_USERNAME` in notebook cell 1.
- Token requirement (fine-grained PAT): grant repository `Le1Ma1/leimai-oracle` with `Contents: Read`.
- Set `GITHUB_USERNAME` to token owner (default `Le1Ma1`) if clone auth fallback is needed.
- `SKIP_INGEST=True` no longer hard-fails on empty data: missing symbols are auto-ingested for safety.
- You can stage variables from `cloud/colab/env.template`.
- Output manifest path:
  - `engine/artifacts/cloud/cloud_run_manifest.json`
  - manifest is generated with `--auto-quality` and includes run quality snapshot.
