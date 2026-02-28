# Colab Runner (Fallback)

Use `cloud/colab/runner.ipynb` when Kaggle resources are unavailable.

## Notes

- Keep the same batch contract as Kaggle (`BATCH_INDEX`, `BATCH_TOTAL`).
- Keep `ENGINE_OPTIMIZATION_TIMEFRAMES=1m`.
- Set `GITHUB_TOKEN` when repo clone needs auth.
- Token requirement (fine-grained PAT): grant repository `Le1Ma1/leimai-oracle` with `Contents: Read`.
- Set `GITHUB_USERNAME` to token owner (default `Le1Ma1`) if clone auth fallback is needed.
- Optional: `SKIP_INGEST=True` to run optimization only.
- You can stage variables from `cloud/colab/env.template`.
- Output manifest path:
  - `engine/artifacts/cloud/cloud_run_manifest.json`
  - manifest is generated with `--auto-quality` and includes run quality snapshot.
