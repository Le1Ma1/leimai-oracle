from __future__ import annotations

import argparse
import base64
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from PIL import Image
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = ROOT / "logs"
HOME_IMAGE = LOGS_DIR / ".home_vibe_tmp.png"
DETAIL_IMAGE = LOGS_DIR / ".detail_vibe_tmp.png"
MERGED_IMAGE = LOGS_DIR / "current_vibe.png"
STATE_FILE = LOGS_DIR / "visual_state.json"


@dataclass(frozen=True)
class SnapshotConfig:
    base_url: str
    timeout_sec: float
    gemini_api_key: str
    gemini_model: str
    force_fallback: bool


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_event(event: str, **kwargs: Any) -> None:
    print(json.dumps({"ts_utc": utc_now_iso(), "event": event, **kwargs}, ensure_ascii=False))


def normalize_base_url(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return "http://127.0.0.1:4310"
    return text.rstrip("/")


def normalize_sentence(raw: str) -> str:
    text = re.sub(r"\s+", " ", str(raw or "").strip())
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    for marker in ("\u3002", ".", "!", "\uff01", "?", "\uff1f"):
        idx = text.find(marker)
        if idx > 0:
            text = text[: idx + 1]
            break
    if text and text[-1] not in {"\u3002", "!", "\uff01", "?", "\uff1f", "."}:
        text = f"{text}."
    return text


def parse_args() -> SnapshotConfig:
    parser = argparse.ArgumentParser(description="Capture visual snapshot and persist compact visual memory.")
    parser.add_argument("--base-url", default=os.getenv("SUPPORT_BASE_URL", "http://127.0.0.1:4310"))
    parser.add_argument("--timeout-sec", type=float, default=float(os.getenv("VISUAL_TIMEOUT_SEC", "25")))
    parser.add_argument("--gemini-model", default=os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))
    parser.add_argument("--force-fallback", action="store_true")
    args = parser.parse_args()

    return SnapshotConfig(
        base_url=normalize_base_url(args.base_url),
        timeout_sec=max(8.0, float(args.timeout_sec)),
        gemini_api_key=str(os.getenv("GEMINI_API_KEY", "")).strip(),
        gemini_model=str(args.gemini_model or "").strip() or "gemini-1.5-flash",
        force_fallback=bool(args.force_fallback),
    )


def capture_images(cfg: SnapshotConfig) -> tuple[str, str]:
    timeout_ms = int(cfg.timeout_sec * 1000)
    home_url = f"{cfg.base_url}/"
    detail_url = f"{cfg.base_url}/analysis/non-existent"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1536, "height": 960})

        page.goto(home_url, wait_until="networkidle", timeout=timeout_ms)
        page.screenshot(path=str(HOME_IMAGE), full_page=True)

        analysis_url = f"{cfg.base_url}/analysis/"
        page.goto(analysis_url, wait_until="networkidle", timeout=timeout_ms)
        try:
            href = page.eval_on_selector_all(
                "a[href^='/analysis/']",
                """nodes => {
                  const hrefs = nodes
                    .map(n => (n && n.getAttribute ? n.getAttribute('href') : null))
                    .filter(Boolean);
                  return hrefs.find(h => h !== '/analysis/' && h !== '/analysis') || null;
                }""",
            )
            if isinstance(href, str) and href.strip():
                detail_url = f"{cfg.base_url}{href.strip()}"
        except PlaywrightError:
            detail_url = f"{cfg.base_url}/analysis/non-existent"

        page.goto(detail_url, wait_until="networkidle", timeout=timeout_ms)
        page.screenshot(path=str(DETAIL_IMAGE), full_page=True)
        browser.close()

    return home_url, detail_url


def build_collage() -> None:
    home = Image.open(HOME_IMAGE).convert("RGB")
    detail = Image.open(DETAIL_IMAGE).convert("RGB")

    if home.width != detail.width:
        target_width = max(home.width, detail.width)
        home = home.resize((target_width, int(home.height * target_width / home.width)))
        detail = detail.resize((target_width, int(detail.height * target_width / detail.width)))

    merged = Image.new("RGB", (home.width, home.height + detail.height))
    merged.paste(home, (0, 0))
    merged.paste(detail, (0, home.height))
    merged.save(MERGED_IMAGE, format="PNG")


def estimate_accent_label() -> str:
    try:
        image = Image.open(HOME_IMAGE).convert("RGB").resize((320, 180))
        px = image.load()
        rs: list[int] = []
        gs: list[int] = []
        bs: list[int] = []
        for y in range(0, image.height, 4):
            for x in range(0, image.width, 4):
                r, g, b = px[x, y]
                if max(r, g, b) < 90:
                    continue
                rs.append(r)
                gs.append(g)
                bs.append(b)
        if not rs:
            return "Platinum Silver"
        r_avg = sum(rs) / len(rs)
        g_avg = sum(gs) / len(gs)
        b_avg = sum(bs) / len(bs)
        if r_avg > g_avg + 10 and g_avg > b_avg + 8:
            return "24K Gold"
        return "Platinum Silver"
    except Exception:
        return "Platinum Silver"


def fallback_note() -> str:
    accent = estimate_accent_label()
    return (
        f"Current palette leans {accent}, obsidian background remains stable, "
        "and the paywall zone keeps clear high contrast."
    )


def describe_with_gemini(cfg: SnapshotConfig) -> tuple[str, str]:
    if cfg.force_fallback or not cfg.gemini_api_key:
        return normalize_sentence(fallback_note()), "fallback"

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.gemini_model}:generateContent"
    image_b64 = base64.b64encode(MERGED_IMAGE.read_bytes()).decode("utf-8")
    prompt = (
        "You are a visual QA assistant. Output exactly one sentence in Traditional Chinese "
        "describing this UI state. The sentence must include: palette (24K Gold or Platinum Silver), "
        "obsidian background status, and paywall contrast quality. No bullets and no second sentence."
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/png", "data": image_b64}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 100},
    }

    try:
        resp = requests.post(
            endpoint,
            params={"key": cfg.gemini_api_key},
            json=payload,
            timeout=(8.0, cfg.timeout_sec),
        )
        resp.raise_for_status()
        data = resp.json()
        text = ""
        for candidate in data.get("candidates", []):
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    text = part["text"]
                    break
            if text:
                break
        note = normalize_sentence(text)
        if not note:
            raise RuntimeError("empty_vision_response")
        return note, cfg.gemini_model
    except Exception as exc:
        log_event("VISUAL_NOTE_FALLBACK", reason=str(exc))
        return normalize_sentence(fallback_note()), "fallback"


def write_state(cfg: SnapshotConfig, home_url: str, detail_url: str, note: str, model_name: str) -> None:
    payload = {
        "ts_utc": utc_now_iso(),
        "base_url": cfg.base_url,
        "home_url": home_url,
        "detail_url": detail_url,
        "model": model_name,
        "visual_note": normalize_sentence(note),
        "assets": {
            "merged_png": str(MERGED_IMAGE.relative_to(ROOT)).replace("\\", "/"),
        },
    }
    STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def cleanup_temp_files() -> None:
    for path in (HOME_IMAGE, DETAIL_IMAGE):
        try:
            if path.exists():
                path.unlink()
        except Exception:
            continue


def main() -> int:
    cfg = parse_args()
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_event("VISUAL_SNAPSHOT_START", base_url=cfg.base_url)

    try:
        home_url, detail_url = capture_images(cfg)
        build_collage()
    except Exception as exc:
        log_event("VISUAL_SNAPSHOT_FAILED", error=str(exc))
        cleanup_temp_files()
        return 1

    note, model_name = describe_with_gemini(cfg)
    write_state(cfg, home_url, detail_url, note, model_name)
    cleanup_temp_files()
    log_event(
        "VISUAL_SNAPSHOT_DONE",
        model=model_name,
        note=note,
        image=str(MERGED_IMAGE.relative_to(ROOT)).replace("\\", "/"),
        state=str(STATE_FILE.relative_to(ROOT)).replace("\\", "/"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
