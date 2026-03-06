from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from engine.src.meta_labeling import (
    MetaLabelConfig,
    _build_triple_barrier_events,
    _scan_thresholds,
    run_meta_label_veto,
)


class MetaLabelingTests(unittest.TestCase):
    def test_vertical_barrier_labels_are_retained_binary(self) -> None:
        index = pd.date_range("2026-01-01", periods=24, freq="15min", tz="UTC")
        close = pd.Series(
            np.array(
                [
                    100.0,
                    100.0,
                    100.0,
                    100.0,
                    100.0,
                    100.0,
                    100.2,
                    100.4,
                    100.5,
                    100.6,
                    100.6,
                    100.6,
                    100.6,
                    100.6,
                    100.6,
                    100.6,
                    100.5,
                    100.4,
                    100.3,
                    100.2,
                    100.2,
                    100.2,
                    100.2,
                    100.2,
                ],
                dtype="float64",
            ),
            index=index,
        )
        high = close * 1.0001
        low = close * 0.9999
        entry = pd.Series(False, index=index, dtype=bool)
        entry.iloc[5] = True
        entry.iloc[15] = True

        events = _build_triple_barrier_events(
            close=close,
            high=high,
            low=low,
            entry=entry,
            friction_bps=10,
            tp_mult=50.0,
            sl_mult=50.0,
            vertical_horizon_bars=4,
            vol_window=3,
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(int(events[0]["label"]), 1)
        self.assertEqual(str(events[0]["provenance"]), "vertical_pos")
        self.assertEqual(int(events[1]["label"]), 0)
        self.assertEqual(str(events[1]["provenance"]), "vertical_nonpos")

    def test_threshold_scan_respects_precision_floor(self) -> None:
        y_true = np.asarray([0, 0, 0, 1], dtype=int)
        y_prob = np.asarray([0.9, 0.8, 0.7, 0.6], dtype="float64")
        best, valid_count = _scan_thresholds(
            y_true=y_true,
            y_prob=y_prob,
            precision_floor=0.60,
            threshold_min=0.50,
            threshold_max=0.95,
            threshold_step=0.05,
            objective="f05",
        )
        self.assertIsNone(best)
        self.assertEqual(valid_count, 0)

    def test_failsafe_veto_all_when_precision_floor_unmet(self) -> None:
        bars = 420
        index = pd.date_range("2024-01-01", periods=bars, freq="15min", tz="UTC")
        base = np.linspace(100.0, 92.0, bars, dtype="float64")
        close = pd.Series(base, index=index, dtype="float64")
        high = close * 1.0001
        low = close * 0.9999
        entry = pd.Series(False, index=index, dtype=bool)
        entry.iloc[::8] = True
        features = pd.DataFrame(
            {
                "trend__logret__15m": close.pct_change().fillna(0.0),
                "risk_volatility__realized_vol_60__1m": close.pct_change().rolling(12).std().fillna(0.0),
                "flow_liquidity__shock_density__1m": close.diff().abs().rolling(6).mean().fillna(0.0),
            },
            index=index,
            dtype="float64",
        )

        cfg = MetaLabelConfig(
            enabled=True,
            model="logreg",
            objective="classification_binary",
            penalty="l1",
            c=0.25,
            max_iter=1200,
            class_weight="balanced",
            tp_mult=1.5,
            sl_mult=1.0,
            vertical_horizon_bars=8,
            vol_window=10,
            min_events=20,
            threshold_min=0.50,
            threshold_max=0.95,
            threshold_step=0.05,
            precision_floor=0.95,
            threshold_objective="f05",
            prob_threshold_fallback=0.55,
            feature_cap=3,
            feature_allowlist=(
                "trend__logret__15m",
                "risk_volatility__realized_vol_60__1m",
                "flow_liquidity__shock_density__1m",
            ),
            cpcv_splits=5,
            cpcv_test_groups=1,
            cpcv_purge_bars=4,
            cpcv_embargo_bars=4,
            cpcv_max_combinations=12,
        )

        output = run_meta_label_veto(
            close=close,
            high=high,
            low=low,
            entry=entry,
            feature_df=features,
            friction_bps=10,
            cfg=cfg,
        )
        self.assertTrue(bool(output["threshold"]["failsafe_veto_all"]))
        self.assertEqual(int(output["entry_meta"].sum()), 0)
        self.assertEqual(str(output.get("reason")), "precision_floor_unmet_global")


if __name__ == "__main__":
    unittest.main()
