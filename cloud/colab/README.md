# Colab Runner (Fallback)

Use `cloud/colab/runner.ipynb` when Kaggle resources are unavailable.

## Notes

- Keep the same batch contract as Kaggle (`BATCH_INDEX`, `BATCH_TOTAL`).
- Keep `ENGINE_OPTIMIZATION_TIMEFRAMES=1m`.
- Set `GITHUB_TOKEN` when repo clone needs auth.
- Optional: `SKIP_INGEST=True` to run optimization only.
- You can stage variables from `cloud/colab/env.template`.
- Output manifest path:
  - `engine/artifacts/cloud/cloud_run_manifest.json`
  - manifest is generated with `--auto-quality` and includes run quality snapshot.
