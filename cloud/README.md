# Cloud Execution Layout

- `cloud/kaggle/`: primary free CPU batch runner.
- `cloud/colab/`: fallback runner when Kaggle is unavailable.

Use helper scripts:

- `scripts/cloud_dispatch.py` for batch slicing + manifest writing.
- `scripts/cloud_data_sync.py` for Kaggle dataset push/pull.

## One-pass operator flow

1. Prepare batch split command locally:

```bash
python scripts/cloud_dispatch.py prepare --target kaggle --batch-index 1 --batch-total 3 --max-rounds 1 --skip-ingest
```

2. Run `cloud/kaggle/runner.ipynb` (or `cloud/colab/runner.ipynb` fallback).
3. Notebook will write:
   - `engine/artifacts/cloud/cloud_run_manifest.json`
   - with `--auto-quality` so monitor fields are real (not zero placeholders).
4. Pull artifacts back:

```bash
python scripts/cloud_data_sync.py pull --dataset <owner/dataset>
```
