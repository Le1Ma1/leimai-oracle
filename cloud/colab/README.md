# Colab Runner (Fallback)

Use `cloud/colab/runner.ipynb` when Kaggle resources are unavailable.

## Notes

- Keep the same batch contract as Kaggle (`BATCH_INDEX`, `BATCH_TOTAL`).
- Keep `ENGINE_OPTIMIZATION_TIMEFRAMES=1m`.
- Output manifest path:
  - `engine/artifacts/cloud/cloud_run_manifest.json`
