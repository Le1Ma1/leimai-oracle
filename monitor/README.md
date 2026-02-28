# 即時訓練監控台（Monitor）

這個頁面用來白話監看訓練進度，不需要讀 log 就能看懂：
- 目前進度與預估剩餘時間
- 幣種完成熱圖
- 週期目標燈號（達標 / 未達）

## 1) 啟動自治監督器（訓練 + 自動監控）

```powershell
python scripts/alpha_supervisor.py --max-rounds 1 --cycles 2 --skip-ingest
```

預設會自動啟動 `progress_monitor.py`，你不需要手動開第二個終端。

## 2)（選用）獨立啟動監控資料寫入器

若你只想看監控、不跑 supervisor，可單獨啟動：

```powershell
python scripts/progress_monitor.py --interval 2
```

會持續更新：
- `engine/artifacts/monitor/live_status.json`
- `engine/artifacts/monitor/live_history.json`

## 3) 開本地靜態伺服器

```powershell
python -m http.server 8787
```

打開：
- `http://localhost:8787/monitor/`

預設資料路徑：
- `/engine/artifacts/monitor/live_status.json`

補充：
- `alpha_supervisor` 可用 `--no-with-monitor` 關閉自動監控程序。
- 若畫面顯示「監控資料延遲/中斷」，先確認 `progress_monitor` 是否仍在執行。
