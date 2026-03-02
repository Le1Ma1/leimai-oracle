from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from engine.src.aggregate import aggregate_timeframes
from engine.src.features import apply_winsor_bounds, build_feature_set, fit_winsor_bounds
from engine.src.optimization import build_fusion_components
from engine.src.validation import _purged_cv_stats, _walk_forward_stats


def _make_ohlcv(n: int = 5000) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC")
    rng = np.random.default_rng(7)
    drift = rng.normal(0.0, 0.0006, size=n).astype("float64")
    close = 100.0 * np.exp(np.cumsum(drift))
    open_ = np.concatenate(([close[0]], close[:-1]))
    spread = np.abs(rng.normal(0.0, 0.0015, size=n))
    high = np.maximum(open_, close) * (1.0 + spread)
    low = np.minimum(open_, close) * (1.0 - spread)
    volume = rng.lognormal(mean=4.0, sigma=0.6, size=n).astype("float64")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    ).astype("float64")


class CausalContractTests(unittest.TestCase):
    def test_no_future_features(self) -> None:
        df = _make_ohlcv(6000)
        htf = aggregate_timeframes(df, ("5m", "15m", "1h", "4h", "1d", "1w"))
        full = build_feature_set(df, htf, warmup_bars=720)

        cut = int(df.shape[0] * 0.7)
        df_cut = df.iloc[:cut].copy()
        htf_cut = aggregate_timeframes(df_cut, ("5m", "15m", "1h", "4h", "1d", "1w"))
        part = build_feature_set(df_cut, htf_cut, warmup_bars=720)

        overlap_idx = full.index.intersection(part.index)
        self.assertGreater(len(overlap_idx), 1000)
        left = full.reindex(overlap_idx)
        right = part.reindex(overlap_idx)
        pd.testing.assert_frame_equal(left, right, check_exact=False, rtol=1e-10, atol=1e-10)

    def test_fold_safe_winsor_bounds(self) -> None:
        idx = pd.date_range("2024-01-01", periods=2000, freq="1min", tz="UTC")
        train = pd.DataFrame({"x": np.linspace(-1.0, 1.0, 1500)}, index=idx[:1500], dtype="float64")
        test = pd.DataFrame({"x": np.linspace(-50.0, 50.0, 500)}, index=idx[1500:], dtype="float64")
        all_df = pd.concat([train, test])

        bounds = fit_winsor_bounds(train)
        transformed = apply_winsor_bounds(all_df, bounds)
        lo, hi = bounds["x"]
        self.assertAlmostEqual(float(transformed["x"].iloc[-1]), hi, places=8)
        self.assertAlmostEqual(float(transformed["x"].iloc[-2]), hi, places=8)
        self.assertGreater(float(all_df["x"].iloc[-1]), hi)
        self.assertLess(float(all_df["x"].iloc[-500]), lo)

    def test_causal_fusion_no_future_leak(self) -> None:
        df = _make_ohlcv(7000)
        htf = aggregate_timeframes(df, ("5m", "15m", "1h", "4h", "1d", "1w"))
        feat_full = build_feature_set(df, htf, warmup_bars=720)
        fusion_full = build_fusion_components(feat_full, timeframe="1m")

        cut = int(df.shape[0] * 0.8)
        df_cut = df.iloc[:cut].copy()
        htf_cut = aggregate_timeframes(df_cut, ("5m", "15m", "1h", "4h", "1d", "1w"))
        feat_cut = build_feature_set(df_cut, htf_cut, warmup_bars=720)
        fusion_cut = build_fusion_components(feat_cut, timeframe="1m")

        overlap_idx = fusion_full.index.intersection(fusion_cut.index)
        self.assertGreater(len(overlap_idx), 1200)
        cols = ["fusion_score", "oracle_score", "confidence"]
        pd.testing.assert_frame_equal(
            fusion_full.reindex(overlap_idx)[cols],
            fusion_cut.reindex(overlap_idx)[cols],
            check_exact=False,
            rtol=1e-10,
            atol=1e-10,
        )

    def test_purged_cv_embargo_effect(self) -> None:
        df = _make_ohlcv(3000)
        close = df["close"].astype("float64")
        entry = pd.Series(False, index=close.index)
        exit_ = pd.Series(False, index=close.index)
        entry.iloc[::30] = True
        exit_.iloc[15::30] = True

        wf_pass, _, wf_segments, _ = _walk_forward_stats(close, entry, exit_, splits=4, friction_bps=10)
        cv_pass_0, _, cv_segments_0, _ = _purged_cv_stats(close, entry, exit_, folds=4, friction_bps=10, purge_bars=0)
        cv_pass_120, _, cv_segments_120, _ = _purged_cv_stats(close, entry, exit_, folds=4, friction_bps=10, purge_bars=120)

        self.assertGreaterEqual(wf_segments, cv_segments_120)
        self.assertGreaterEqual(cv_segments_0, cv_segments_120)
        self.assertGreaterEqual(wf_pass, 0.0)
        self.assertGreaterEqual(cv_pass_0, 0.0)
        self.assertGreaterEqual(cv_pass_120, 0.0)


if __name__ == "__main__":
    unittest.main()
