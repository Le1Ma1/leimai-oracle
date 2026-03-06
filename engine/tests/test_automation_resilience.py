from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[2]
VISUAL_SNAPSHOT_PATH = REPO_ROOT / "scripts" / "visual_snapshot.py"
ML_AUTOTUNE_PATH = REPO_ROOT / "scripts" / "ml_autotune.py"
TMP_ROOT = REPO_ROOT / "logs" / ".tmp_tests"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module spec: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _run_python(args: list[str], cwd: Path) -> None:
    proc = subprocess.run(args, cwd=str(cwd), check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(args)}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")


@contextmanager
def _sandbox_temp_dir() -> Any:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    tmp_path = TMP_ROOT / f"case_{uuid4().hex}"
    tmp_path.mkdir(parents=True, exist_ok=False)
    try:
        yield tmp_path
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
        try:
            TMP_ROOT.rmdir()
        except OSError:
            pass


class VisualSnapshotReportModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module("visual_snapshot_test_mod", VISUAL_SNAPSHOT_PATH)
        self.diag_path = Path(self.mod.REPORT_DIAGNOSTICS_FILE)
        if self.diag_path.exists():
            self.diag_path.unlink()

    def tearDown(self) -> None:
        if self.diag_path.exists():
            self.diag_path.unlink()

    def _build_cfg(self) -> Any:
        return self.mod.ReportConfig(
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="dummy-key",
            timeout_sec=10.0,
            limit=5,
            locale="",
            slug="",
            output_dir=Path(self.mod.SNAPSHOT_DIR),
            binance_base_url="https://api.binance.com",
        )

    def test_report_mode_does_not_call_playwright(self) -> None:
        cfg = self._build_cfg()

        def _fail_playwright() -> Any:
            raise RuntimeError("playwright should not be used in report mode")

        self.mod.ensure_playwright = _fail_playwright
        self.mod.fetch_reports_for_snapshots = lambda _: []
        code = self.mod.run_report_snapshot_mode(cfg)
        self.assertEqual(code, 0)
        self.assertTrue(self.diag_path.exists())
        payload = json.loads(self.diag_path.read_text(encoding="utf-8"))
        self.assertEqual(payload.get("status"), "ok")

    def test_report_mode_returns_retry_code_for_transient_fetch(self) -> None:
        cfg = self._build_cfg()

        def _raise_transient(_: Any) -> Any:
            raise self.mod.ReportSnapshotError("report_fetch_failed_transient", "temporary", transient=True)

        self.mod.fetch_reports_for_snapshots = _raise_transient
        code = self.mod.run_report_snapshot_mode(cfg)
        self.assertEqual(code, 2)
        payload = json.loads(self.diag_path.read_text(encoding="utf-8"))
        self.assertEqual(payload.get("fatal_reason_code"), "report_fetch_failed_transient")
        self.assertTrue(payload.get("transient"))


class MlAutotuneBehaviorTests(unittest.TestCase):
    def _sample_report(self, *, objective: float, delta: float, stability: int) -> dict[str, Any]:
        return {
            "ts_utc": "2026-03-05T10:00:00Z",
            "final_run_id": "iter_test",
            "final_objective_balance_score": objective,
            "stability_streak": stability,
            "best_round_score": {
                "validation_pass_rate": 0.25,
                "all_window_avg_alpha_vs_spot": -1.8,
                "deploy_avg_alpha_vs_spot": 0.01,
                "objective_balance_score": objective,
            },
            "round_reports": [
                {
                    "delta_vs_prev_round": {"objective_balance_score": delta},
                    "validation_metrics": {
                        "validation_pass_rate": 0.25,
                        "all_window_avg_alpha_vs_spot": -1.8,
                        "deploy_avg_alpha_vs_spot": 0.01,
                        "deploy_total_symbols": 1,
                        "deploy_total_rules": 2,
                    },
                }
            ],
        }

    def test_update_tightens_targets_with_stable_positive_delta(self) -> None:
        with _sandbox_temp_dir() as tmp_path:
            state_path = tmp_path / "ml_tune_state.json"
            decision_path = tmp_path / "decision.json"
            report_path = tmp_path / "iteration.json"
            report_path.write_text(json.dumps(self._sample_report(objective=0.62, delta=0.03, stability=3)), encoding="utf-8")

            _run_python(
                [
                    "python",
                    str(ML_AUTOTUNE_PATH),
                    "--mode",
                    "prepare",
                    "--state-path",
                    str(state_path),
                    "--decision-path",
                    str(decision_path),
                ],
                cwd=REPO_ROOT,
            )
            _run_python(
                [
                    "python",
                    str(ML_AUTOTUNE_PATH),
                    "--mode",
                    "update",
                    "--state-path",
                    str(state_path),
                    "--decision-path",
                    str(decision_path),
                    "--report-path",
                    str(report_path),
                    "--max-delta-pct",
                    "5",
                    "--min-stability-streak",
                    "2",
                ],
                cwd=REPO_ROOT,
            )

            state = json.loads(state_path.read_text(encoding="utf-8"))
            decision = json.loads(decision_path.read_text(encoding="utf-8"))
            self.assertEqual(decision.get("action"), "tighten_targets")
            pass_rate = float(state.get("current_targets", {}).get("target_pass_rate", 0.0))
            self.assertGreater(pass_rate, 0.20)
            self.assertLessEqual(pass_rate, 0.21 + 1e-9)

    def test_update_rolls_back_after_degrade_streak_limit(self) -> None:
        with _sandbox_temp_dir() as tmp_path:
            state_path = tmp_path / "ml_tune_state.json"
            decision_path = tmp_path / "decision.json"
            report_path = tmp_path / "iteration.json"
            report_path.write_text(json.dumps(self._sample_report(objective=0.40, delta=-0.02, stability=0)), encoding="utf-8")

            seeded_state = {
                "version": 1,
                "updated_at": "2026-03-05T09:00:00Z",
                "current_targets": {
                    "target_pass_rate": 0.30,
                    "target_all_alpha": -1.0,
                    "target_deploy_alpha": 0.05,
                    "target_deploy_symbols": 1,
                    "target_deploy_rules": 2,
                    "stable_rounds": 1,
                    "cycles": 2,
                    "max_rounds": 2,
                },
                "last_good_targets": {
                    "target_pass_rate": 0.20,
                    "target_all_alpha": -2.0,
                    "target_deploy_alpha": 0.0,
                    "target_deploy_symbols": 1,
                    "target_deploy_rules": 2,
                    "stable_rounds": 1,
                    "cycles": 2,
                    "max_rounds": 2,
                },
                "last_metrics": {"objective_balance_score": 0.50},
                "last_good_metrics": {"objective_balance_score": 0.50},
                "degrade_streak": 1,
            }
            state_path.write_text(json.dumps(seeded_state), encoding="utf-8")

            _run_python(
                [
                    "python",
                    str(ML_AUTOTUNE_PATH),
                    "--mode",
                    "update",
                    "--state-path",
                    str(state_path),
                    "--decision-path",
                    str(decision_path),
                    "--report-path",
                    str(report_path),
                    "--rollback-on-degrade-streak",
                    "2",
                ],
                cwd=REPO_ROOT,
            )

            state = json.loads(state_path.read_text(encoding="utf-8"))
            decision = json.loads(decision_path.read_text(encoding="utf-8"))
            self.assertEqual(decision.get("action"), "rollback_to_last_good")
            self.assertAlmostEqual(float(state.get("current_targets", {}).get("target_pass_rate", 0.0)), 0.20, places=9)


if __name__ == "__main__":
    unittest.main()
