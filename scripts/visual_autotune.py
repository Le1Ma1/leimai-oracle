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
SERVER_FILE = ROOT / "support" / "server.mjs"
PAYWALL_NOTICE = (
    "此預言受 LeiMai 權限協議保護，"
    "請連接冷錢包簽署『銜尾蛇契約』"
    "以解鎖 Alpha 全文。"
)


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


def choose_profile(note: str, state: dict[str, Any]) -> tuple[TuneProfile, list[str]]:
    text = str(note or "")
    lowered = text.lower()
    checks = state.get("checks", {}) if isinstance(state.get("checks"), dict) else {}
    reasons: list[str] = []

    contrast_min = _safe_float(checks.get("text_contrast_min"), 0.0)
    detail_has_analysis = bool(checks.get("detail_has_analysis", False))
    lock_visible = bool(checks.get("paywall_lock_visible", True))
    unlock_visible = bool(checks.get("paywall_unlock_visible", True))
    fog_visible = bool(checks.get("paywall_fog_visible", True))

    if 0 < contrast_min < 4.5:
        reasons.append(f"contrast_low:{contrast_min:.2f}")
    if detail_has_analysis:
        if not lock_visible:
            reasons.append("paywall_lock_hidden")
        if not unlock_visible:
            reasons.append("unlock_btn_hidden")
        if not fog_visible:
            reasons.append("paywall_fog_hidden")

    low_keywords = (
        "contrast low",
        "dim",
        "blur",
        "hazy",
        "對比不足",
        "偏暗",
        "模糊",
        "發霧",
        "不清晰",
    )
    high_keywords = (
        "too bright",
        "harsh",
        "overexposed",
        "too strong",
        "過亮",
        "刺眼",
        "過曝",
        "太強",
        "過度",
    )

    if reasons or any(k in lowered or k in text for k in low_keywords):
        if not reasons:
            reasons.append("note_low_quality")
        return TuneProfile("boost", 0.80, 0.24, 0.34, 0.52, 0.28, 11, 0.56, 16), reasons

    if any(k in lowered or k in text for k in high_keywords):
        return TuneProfile("soft", 0.72, 0.16, 0.24, 0.32, 0.14, 9, 0.38, 14), ["note_overbright"]

    return TuneProfile("balanced", 0.76, 0.18, 0.28, 0.42, 0.18, 10, 0.45, 15), ["quality_stable"]


def replace_once(text: str, pattern: str, repl: str) -> tuple[str, bool]:
    new_text, count = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE)
    return new_text, count > 0


def set_css_var(text: str, var_name: str, var_value: str) -> tuple[str, bool]:
    pattern = rf"({re.escape(var_name)}\\s*:\\s*)([^;]+)(;)"
    replacement = rf"\\g<1>{var_value}\\g<3>"
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


def tune_server_template() -> bool:
    original = SERVER_FILE.read_text(encoding="utf-8")
    pattern = r'const PAYWALL_NOTICE = ".*";'
    replacement = f'const PAYWALL_NOTICE = "{PAYWALL_NOTICE}";'
    updated, count = re.subn(pattern, lambda _m: replacement, original, count=1)
    if count > 0 and updated != original:
        SERVER_FILE.write_text(updated, encoding="utf-8")
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

    note = str(state.get("visual_note", "")).strip()
    profile, reasons = choose_profile(note, state)
    changed_files: list[str] = []

    if tune_css(profile):
        changed_files.append("support/web/ouroboros.css")
    if tune_server_template():
        changed_files.append("support/server.mjs")

    write_tune_log(state, profile, reasons, changed_files)
    if changed_files:
        log_event("VISUAL_AUTOTUNE_DONE", profile=profile.name, reasons=reasons, changed_files=changed_files)
    else:
        log_event("VISUAL_AUTOTUNE_NO_CHANGE", profile=profile.name, reasons=reasons)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
