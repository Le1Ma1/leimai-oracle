# Review Dashboard (Decision Mode)

Static local review UI for single-indicator 1m optimization artifacts.

## Run

From repo root:

```bash
python -m http.server 8787
```

Open:

`http://localhost:8787/review/`

## Required Data

The page auto-loads latest date under:

- `/engine/artifacts/optimization/single/<YYYY-MM-DD>/summary.json`
- `/engine/artifacts/optimization/single/<YYYY-MM-DD>/explainability.json`
- `/engine/artifacts/optimization/single/<YYYY-MM-DD>/validation_report.json` (optional)
- `/engine/artifacts/optimization/single/<YYYY-MM-DD>/deploy_pool.json` (optional)

Fallback (legacy): `/engine/artifacts/optimization/rsi/...`

## What This Dashboard Shows

- Executive snapshot (window pass rate, avg strategy return, avg spot return, grade distribution)
- Health dashboard (validation pass rate, all-window alpha, deploy alpha, gate-level alpha proxy)
- Pyramid gate-diff summary (`gated` vs `ungated`) by window
- Rank shift board (`gated` vs `ungated`) for direct rank movement comparison
- Plain-language quick guide (4-step reading order for non-technical review)
- Validation health (validation pass rate, median final score, deploy coverage)
- Hypermatrix slice view (`symbol x indicator`) with:
  - direct mode (current gate mode)
  - delta mode (`gated - ungated`)
  - metric switch (`alpha/return/score/pass`)
- Feature convergence panel:
  - family contribution ranking by current window (`trend / oscillation / risk_volatility / flow_liquidity / timing_execution`)
  - top-importance features (Top 15)
  - prune-candidate features (Top 15)
  - plain-language weakness/improvement/advantage summary
  - high-dimensional two-bar feature family classification (for fast audit)
- Deploy pool table (symbol-level launch candidates)
- Window-first matrix (`all/360d/90d/30d`) with indicator filter
- Per-symbol explainability:
  - performance decomposition
  - validation verdict (pass/fail + failed reasons)
  - rule competition and rejection reasons
  - feature weight contribution shares
  - signal frequency distribution (weekday/weekend + UTC sessions)
  - sampled event K-line review (best/median/worst trade)
  - no-lookahead audit result

## Interpretation Notes

- Negative strategy return can still be acceptable when alpha vs spot is positive.
- `C*` means insufficient statistical significance for that window.
- `A/B/C` is decision-oriented quality grading, not forecasting certainty.
- Validation `PASS` means the candidate passed institutional validation thresholds in `validation_report.json`.
- The page performs run-id consistency checks; if validation/deploy is from a different run, it will be ignored and marked.
- `gated`: entry signal must pass fusion filter; `ungated`: indicator signal enters directly without fusion filter.
