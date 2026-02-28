# Monitor Cloud Source Mode

`monitor/index.html` now supports two data sources:

- `本地 Monitor`: `/engine/artifacts/monitor/live_status.json`
- `雲端 Manifest`: `/engine/artifacts/cloud/cloud_run_manifest.json`

## Usage

1. Start static server:

```bash
python -m http.server 8787
```

2. Open:

`http://localhost:8787/monitor/`

3. In the toolbar, switch `資料來源`:

- choose `本地 Monitor` for active local run
- choose `雲端 Manifest` after pulling cloud batch output

4. If needed, override path directly in the path input.
