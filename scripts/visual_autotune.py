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
    "\u6b64\u9810\u8a00\u53d7 LeiMai \u6b0a\u9650\u5354\u8b70\u4fdd\u8b77\uff0c"
    "\u8acb\u9023\u63a5\u51b7\u9322\u5305\u7c3d\u7f72\u300e\u929c\u5c3e\u86c7\u5951\u7d04\u300f"
    "\u4ee5\u89e3\u9396 Alpha \u5168\u6587\u3002"
)


@dataclass(frozen=True)
class TuneProfile:
    name: str
    panel_alpha: float
    line_alpha: float
    line_strong_alpha: float
    neon_near_alpha: float
    neon_far_alpha: float
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


def choose_profile(note: str) -> TuneProfile:
    text = str(note or "")
    lowered = text.lower()
    low_keywords = (
        "contrast low",
        "dim",
        "blur",
        "hazy",
        "\u5c0d\u6bd4\u4e0d\u8db3",
        "\u504f\u6697",
        "\u6a21\u7cca",
        "\u767c\u9727",
        "\u4e0d\u6e05\u6670",
    )
    high_keywords = (
        "too bright",
        "harsh",
        "overexposed",
        "too strong",
        "\u904e\u4eae",
        "\u523a\u773c",
        "\u904e\u66dd",
        "\u592a\u5f37",
        "\u904e\u5ea6",
    )
    if any(k in lowered or k in text for k in low_keywords):
        return TuneProfile("boost", 0.80, 0.24, 0.34, 0.52, 0.28, 0.56, 16)
    if any(k in lowered or k in text for k in high_keywords):
        return TuneProfile("soft", 0.72, 0.16, 0.24, 0.32, 0.14, 0.38, 14)
    return TuneProfile("balanced", 0.76, 0.18, 0.28, 0.42, 0.18, 0.45, 15)


def replace_once(text: str, pattern: str, repl: str) -> tuple[str, bool]:
    new_text, count = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE)
    return new_text, count > 0


def tune_css(profile: TuneProfile) -> bool:
    original = CSS_FILE.read_text(encoding="utf-8")
    text = original
    changed = False

    replacements = [
        (
            r"--panel:\s*rgba\(8,\s*10,\s*12,\s*[0-9.]+\);",
            f"--panel: rgba(8, 10, 12, {profile.panel_alpha:.2f});",
        ),
        (
            r"--line:\s*rgba\(255,\s*255,\s*255,\s*[0-9.]+\);",
            f"--line: rgba(255, 255, 255, {profile.line_alpha:.2f});",
        ),
        (
            r"--line-strong:\s*rgba\(255,\s*255,\s*255,\s*[0-9.]+\);",
            f"--line-strong: rgba(255, 255, 255, {profile.line_strong_alpha:.2f});",
        ),
        (
            r"text-shadow:\s*0 0 22px rgba\(var\(--accent-rgb\),\s*[0-9.]+\),\s*0 0 38px rgba\(var\(--accent-rgb\),\s*[0-9.]+\);",
            (
                "text-shadow: "
                f"0 0 22px rgba(var(--accent-rgb), {profile.neon_near_alpha:.2f}), "
                f"0 0 38px rgba(var(--accent-rgb), {profile.neon_far_alpha:.2f});"
            ),
        ),
        (
            r"\.lock-message\s*\{[^}]*?background:\s*rgba\(4,\s*8,\s*12,\s*[0-9.]+\);",
            (
                ".lock-message {\n"
                "  border: 1px solid rgba(var(--accent-rgb), 0.45);\n"
                f"  background: rgba(4, 8, 12, {profile.lock_bg_alpha:.2f});"
            ),
        ),
        (
            r"backdrop-filter:\s*blur\([0-9.]+px\);",
            f"backdrop-filter: blur({profile.lock_blur_px}px);",
        ),
    ]

    for pattern, repl in replacements:
        text, did = replace_once(text, pattern, repl)
        changed = changed or did

    if changed and text != original:
        CSS_FILE.write_text(text, encoding="utf-8")
        return True
    return False


def tune_server_template() -> bool:
    original = SERVER_FILE.read_text(encoding="utf-8")
    pattern = r'const PAYWALL_NOTICE = ".*";'
    replacement = f'const PAYWALL_NOTICE = "{PAYWALL_NOTICE}";'
    updated, count = re.subn(pattern, replacement, original, count=1)
    if count > 0 and updated != original:
        SERVER_FILE.write_text(updated, encoding="utf-8")
        return True
    return False


def write_tune_log(state: dict[str, Any], profile: TuneProfile, changed_files: list[str]) -> None:
    payload = {
        "ts_utc": utc_now_iso(),
        "source_state_ts_utc": state.get("ts_utc"),
        "visual_note": state.get("visual_note", ""),
        "profile": profile.name,
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
    profile = choose_profile(note)
    changed_files: list[str] = []

    if tune_css(profile):
        changed_files.append("support/web/ouroboros.css")
    if tune_server_template():
        changed_files.append("support/server.mjs")

    write_tune_log(state, profile, changed_files)
    if changed_files:
        log_event("VISUAL_AUTOTUNE_DONE", profile=profile.name, changed_files=changed_files)
    else:
        log_event("VISUAL_AUTOTUNE_NO_CHANGE", profile=profile.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
