from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = ROOT / "logs"
STATE_FILE = LOGS_DIR / "visual_state.json"
TUNE_LOG_FILE = LOGS_DIR / "visual_tune.json"
CSS_FILE = ROOT / "support" / "web" / "ouroboros.css"


@dataclass(frozen=True)
class TuneProfile:
    name: str
    panel_alpha: float
    line_alpha: float
    line_strong_alpha: float
    neon_near_alpha: float
    neon_far_alpha: float
    glass_blur_px: int
    lock_bg_alpha: float
    lock_blur_px: int


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_event(event: str, **kwargs: Any) -> None:
    print(json.dumps({"ts_utc": utc_now_iso(), "event": event, **kwargs}, ensure_ascii=False))


def load_visual_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        raise FileNotFoundError(f"{STATE_FILE} not found. Run scripts/visual_snapshot.py first.")
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def choose_profile(state: dict[str, Any]) -> tuple[TuneProfile, list[str]]:
    checks = state.get("checks", {}) if isinstance(state.get("checks"), dict) else {}
    reasons: list[str] = []

    contrast_min = _safe_float(checks.get("text_contrast_min"), 0.0)
    readability = _safe_float(checks.get("readability_score"), 100.0)
    cta_score = _safe_float(checks.get("cta_prominence_score"), 100.0)
    detail_is_real = bool(checks.get("detail_is_real_report", False))

    if not detail_is_real:
        reasons.append("detail_not_real_report")
    if 0 < contrast_min < 4.5:
        reasons.append(f"contrast_low:{contrast_min:.2f}")
    if readability < 84:
        reasons.append(f"readability_low:{readability:.1f}")
    if cta_score < 58:
        reasons.append(f"cta_low:{cta_score:.1f}")

    if reasons:
        return TuneProfile("boost", 0.80, 0.25, 0.36, 0.52, 0.26, 11, 0.56, 16), reasons

    return TuneProfile("balanced", 0.76, 0.18, 0.28, 0.42, 0.18, 10, 0.45, 15), ["quality_stable"]


def replace_once(text: str, pattern: str, repl: str) -> tuple[str, bool]:
    new_text, count = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE)
    return new_text, count > 0


def set_css_var(text: str, var_name: str, var_value: str) -> tuple[str, bool]:
    pattern = rf"({re.escape(var_name)}\s*:\s*)([^;]+)(;)"
    replacement = rf"\g<1>{var_value}\g<3>"
    return replace_once(text, pattern, replacement)


def tune_css(profile: TuneProfile) -> bool:
    original = CSS_FILE.read_text(encoding="utf-8")
    text = original
    changed = False

    css_vars = {
        "--panel": f"rgba(8, 10, 12, {profile.panel_alpha:.2f})",
        "--line": f"rgba(255, 255, 255, {profile.line_alpha:.2f})",
        "--line-strong": f"rgba(255, 255, 255, {profile.line_strong_alpha:.2f})",
        "--neon-near-alpha": f"{profile.neon_near_alpha:.2f}",
        "--neon-far-alpha": f"{profile.neon_far_alpha:.2f}",
        "--glass-blur-px": str(profile.glass_blur_px),
        "--lock-bg-alpha": f"{profile.lock_bg_alpha:.2f}",
        "--lock-blur-px": str(profile.lock_blur_px),
    }

    for var_name, var_value in css_vars.items():
        text, did = set_css_var(text, var_name, var_value)
        changed = changed or did

    if changed and text != original:
        CSS_FILE.write_text(text, encoding="utf-8")
        return True
    return False


def write_tune_log(state: dict[str, Any], profile: TuneProfile, reasons: list[str], changed_files: list[str]) -> None:
    payload = {
        "ts_utc": utc_now_iso(),
        "source_state_ts_utc": state.get("ts_utc"),
        "visual_note": state.get("visual_note", ""),
        "checks": state.get("checks", {}),
        "profile": profile.name,
        "reasons": reasons,
        "changed_files": changed_files,
    }
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    TUNE_LOG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    try:
        state = load_visual_state()
    except FileNotFoundError as exc:
        log_event("VISUAL_AUTOTUNE_BLOCKED", reason=str(exc))
        return 2

    profile, reasons = choose_profile(state)
    changed_files: list[str] = []

    if tune_css(profile):
        changed_files.append("support/web/ouroboros.css")

    write_tune_log(state, profile, reasons, changed_files)
    if changed_files:
        log_event("VISUAL_AUTOTUNE_DONE", profile=profile.name, reasons=reasons, changed_files=changed_files)
    else:
        log_event("VISUAL_AUTOTUNE_NO_CHANGE", profile=profile.name, reasons=reasons)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
