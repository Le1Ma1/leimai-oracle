# Cloud Execution Layout

- `cloud/kaggle/`: primary free CPU batch runner.
- `cloud/colab/`: fallback runner when Kaggle is unavailable.

Use helper scripts:

- `scripts/cloud_dispatch.py` for batch slicing + manifest writing.
- `scripts/cloud_data_sync.py` for Kaggle dataset push/pull.
