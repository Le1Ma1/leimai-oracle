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
from playwright.sync_api import Page
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = ROOT / "logs"
HOME_IMAGE = LOGS_DIR / ".home_vibe_tmp.png"
VAULT_IMAGE = LOGS_DIR / ".vault_vibe_tmp.png"
INDEX_IMAGE = LOGS_DIR / ".index_vibe_tmp.png"
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


def collect_page_checks(page: Page) -> dict[str, Any]:
    return page.evaluate(
        r"""
        () => {
          const parseRgb = (raw) => {
            const value = String(raw || '').trim();
            const match = value.match(/rgba?\(([^)]+)\)/i);
            if (!match) return null;
            const parts = match[1].split(',').map(x => Number(String(x).trim()));
            if (parts.length < 3 || parts.some(v => Number.isNaN(v))) return null;
            return [parts[0], parts[1], parts[2]];
          };

          const luminance = (rgb) => {
            if (!rgb) return 0;
            const norm = rgb.map(v => {
              const n = Math.max(0, Math.min(255, v)) / 255;
              return n <= 0.03928 ? n / 12.92 : Math.pow((n + 0.055) / 1.055, 2.4);
            });
            return 0.2126 * norm[0] + 0.7152 * norm[1] + 0.0722 * norm[2];
          };

          const contrast = (fg, bg) => {
            if (!fg || !bg) return null;
            const l1 = luminance(fg);
            const l2 = luminance(bg);
            const hi = Math.max(l1, l2);
            const lo = Math.min(l1, l2);
            return Number(((hi + 0.05) / (lo + 0.05)).toFixed(2));
          };

          const isVisible = (selector) => {
            const el = document.querySelector(selector);
            if (!el) return false;
            const st = window.getComputedStyle(el);
            if (st.display === 'none' || st.visibility === 'hidden') return false;
            if (Number(st.opacity || '1') <= 0.01) return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 1 && rect.height > 1;
          };

          const contrastSample = (fgSelector, bgSelector) => {
            const fgEl = document.querySelector(fgSelector);
            if (!fgEl) return null;
            const bgEl = document.querySelector(bgSelector) || fgEl.parentElement || document.body;
            const fgColor = parseRgb(window.getComputedStyle(fgEl).color);
            let bgColorRaw = window.getComputedStyle(bgEl).backgroundColor;
            if (!bgColorRaw || bgColorRaw.includes('rgba(0, 0, 0, 0)') || bgColorRaw === 'transparent') {
              bgColorRaw = window.getComputedStyle(document.body).backgroundColor;
            }
            const bgColor = parseRgb(bgColorRaw);
            return contrast(fgColor, bgColor);
          };

          const bodyStyle = window.getComputedStyle(document.body);
          const rootStyle = window.getComputedStyle(document.documentElement);
          const samples = {
            hero_title: contrastSample('.hero h1, .hero .neon-text, h1', '.hero, .glass-panel, body'),
            panel_text: contrastSample('.panel p, .panel .muted, p', '.panel, .glass-panel, body'),
            paywall_message: contrastSample('.lock-message', '.paywall-locked-content, .lock-message, body'),
            unlock_button: contrastSample('.unlock-btn', '.paywall-locked-content, .unlock-btn, body'),
            article_text: contrastSample('.article-body p, .report-article p', '.obsidian-container, .report-article, body'),
          };

          const values = Object.values(samples).filter(v => typeof v === 'number');
          const minContrast = values.length ? Math.min(...values) : 0;
          const avgContrast = values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;

          const lineHeightRaw = String(bodyStyle.lineHeight || '');
          const lineHeightPx = Number.parseFloat(lineHeightRaw);

          return {
            url: window.location.href,
            title: document.title || '',
            low_gpu_mode: document.body.classList.contains('low-gpu'),
            matrix_canvas_visible: isVisible('#matrix-bg'),
            has_report_article: !!document.querySelector('.report-article, .article-body'),
            has_paywall_shell: !!document.querySelector('.paywall-shell'),
            paywall_lock_visible: isVisible('.paywall-locked-content'),
            paywall_unlock_visible: isVisible('.unlock-btn'),
            paywall_fog_visible: isVisible('.obsidian-fog'),
            has_horizontal_overflow: document.documentElement.scrollWidth > window.innerWidth + 2,
            text_nodes: document.querySelectorAll('p, li').length,
            body_font_px: Number.parseFloat(bodyStyle.fontSize || '0') || 0,
            body_line_height_px: Number.isFinite(lineHeightPx) ? lineHeightPx : 0,
            accent_css: String(rootStyle.getPropertyValue('--accent') || '').trim(),
            contrast_samples: samples,
            text_contrast_min: Number(minContrast.toFixed(2)),
            text_contrast_avg: Number(avgContrast.toFixed(2)),
          };
        }
        """
    )


def aggregate_checks(page_checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pages = [page_checks.get(k, {}) for k in ("home", "vault", "index", "detail")]
    min_values = [float(p.get("text_contrast_min", 0)) for p in pages if float(p.get("text_contrast_min", 0)) > 0]
    avg_values = [float(p.get("text_contrast_avg", 0)) for p in pages if float(p.get("text_contrast_avg", 0)) > 0]

    text_contrast_min = min(min_values) if min_values else 0.0
    text_contrast_avg = sum(avg_values) / len(avg_values) if avg_values else 0.0
    detail_page = page_checks.get("detail", {})
    detail_has_analysis = bool(detail_page.get("has_report_article", False) or detail_page.get("has_paywall_shell", False))
    paywall_lock_visible = bool(detail_page.get("paywall_lock_visible", False))
    paywall_unlock_visible = bool(detail_page.get("paywall_unlock_visible", False))
    paywall_fog_visible = bool(detail_page.get("paywall_fog_visible", False))
    matrix_canvas_visible = bool(page_checks.get("home", {}).get("matrix_canvas_visible", False))
    low_gpu_mode = bool(page_checks.get("home", {}).get("low_gpu_mode", False))
    has_horizontal_overflow = any(bool(p.get("has_horizontal_overflow", False)) for p in pages)

    issues: list[str] = []
    if text_contrast_min and text_contrast_min < 4.5:
        issues.append("text_contrast_below_wcag_aa")
    if detail_has_analysis:
        if not paywall_lock_visible:
            issues.append("paywall_lock_not_visible")
        if not paywall_unlock_visible:
            issues.append("unlock_button_not_visible")
        if not paywall_fog_visible:
            issues.append("paywall_fog_not_visible")
    if not matrix_canvas_visible and not low_gpu_mode:
        issues.append("matrix_background_not_visible")
    if has_horizontal_overflow:
        issues.append("horizontal_overflow_detected")

    return {
        "text_contrast_min": round(text_contrast_min, 2),
        "text_contrast_avg": round(text_contrast_avg, 2),
        "paywall_lock_visible": paywall_lock_visible,
        "paywall_unlock_visible": paywall_unlock_visible,
        "paywall_fog_visible": paywall_fog_visible,
        "detail_has_analysis": detail_has_analysis,
        "matrix_canvas_visible": matrix_canvas_visible,
        "low_gpu_mode": low_gpu_mode,
        "has_horizontal_overflow": has_horizontal_overflow,
        "issues": issues,
        "issue_count": len(issues),
        "pages": page_checks,
    }


def capture_images(cfg: SnapshotConfig) -> tuple[dict[str, str], dict[str, Any]]:
    timeout_ms = int(cfg.timeout_sec * 1000)
    home_url = f"{cfg.base_url}/"
    vault_url = f"{cfg.base_url}/vault"
    index_url = f"{cfg.base_url}/analysis/"
    detail_url = f"{cfg.base_url}/analysis/non-existent"
    page_checks: dict[str, dict[str, Any]] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1536, "height": 960})

        page.goto(home_url, wait_until="networkidle", timeout=timeout_ms)
        page.screenshot(path=str(HOME_IMAGE), full_page=True)
        page_checks["home"] = collect_page_checks(page)

        page.goto(vault_url, wait_until="networkidle", timeout=timeout_ms)
        page.screenshot(path=str(VAULT_IMAGE), full_page=True)
        page_checks["vault"] = collect_page_checks(page)

        page.goto(index_url, wait_until="networkidle", timeout=timeout_ms)
        page.screenshot(path=str(INDEX_IMAGE), full_page=True)
        page_checks["index"] = collect_page_checks(page)
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
        page_checks["detail"] = collect_page_checks(page)
        browser.close()

    return (
        {
            "home_url": home_url,
            "vault_url": vault_url,
            "index_url": index_url,
            "detail_url": detail_url,
        },
        aggregate_checks(page_checks),
    )


def build_collage() -> None:
    tiles = [
        Image.open(HOME_IMAGE).convert("RGB"),
        Image.open(VAULT_IMAGE).convert("RGB"),
        Image.open(INDEX_IMAGE).convert("RGB"),
        Image.open(DETAIL_IMAGE).convert("RGB"),
    ]
    target_w = max(img.width for img in tiles)
    resized: list[Image.Image] = []
    for img in tiles:
        if img.width == target_w:
            resized.append(img)
            continue
        new_h = int(img.height * target_w / img.width)
        resized.append(img.resize((target_w, new_h)))

    row1_h = max(resized[0].height, resized[1].height)
    row2_h = max(resized[2].height, resized[3].height)
    canvas_w = target_w * 2
    canvas_h = row1_h + row2_h
    merged = Image.new("RGB", (canvas_w, canvas_h))
    merged.paste(resized[0], (0, 0))
    merged.paste(resized[1], (target_w, 0))
    merged.paste(resized[2], (0, row1_h))
    merged.paste(resized[3], (target_w, row1_h))
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


def fallback_note(quality: dict[str, Any]) -> str:
    accent = estimate_accent_label()
    contrast = float(quality.get("text_contrast_min", 0.0) or 0.0)
    detail_has_analysis = bool(quality.get("detail_has_analysis", False))
    lock_visible = bool(quality.get("paywall_lock_visible", False))
    matrix_ok = bool(quality.get("matrix_canvas_visible", False)) or bool(quality.get("low_gpu_mode", False))
    paywall_state = "clear" if lock_visible else ("not_applicable" if not detail_has_analysis else "degraded")
    return (
        f"Current palette leans {accent}, minimum text contrast is {contrast:.2f}, "
        f"obsidian background status is {'stable' if matrix_ok else 'degraded'}, "
        f"and paywall visibility is {paywall_state}."
    )


def describe_with_gemini(cfg: SnapshotConfig, quality: dict[str, Any]) -> tuple[str, str]:
    if cfg.force_fallback or not cfg.gemini_api_key:
        return normalize_sentence(fallback_note(quality)), "fallback"

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
        return normalize_sentence(fallback_note(quality)), "fallback"


def write_state(
    cfg: SnapshotConfig,
    page_urls: dict[str, str],
    quality: dict[str, Any],
    note: str,
    model_name: str,
) -> None:
    accent = estimate_accent_label()
    contrast_min = float(quality.get("text_contrast_min", 0.0) or 0.0)
    contrast_status = "high" if contrast_min >= 4.5 else "low"
    detail_has_analysis = bool(quality.get("detail_has_analysis", False))
    if not detail_has_analysis:
        paywall_status = "not_applicable"
    else:
        paywall_status = "clear" if bool(quality.get("paywall_lock_visible", False)) else "degraded"
    payload = {
        "ts_utc": utc_now_iso(),
        "base_url": cfg.base_url,
        "home_url": page_urls.get("home_url", ""),
        "vault_url": page_urls.get("vault_url", ""),
        "index_url": page_urls.get("index_url", ""),
        "detail_url": page_urls.get("detail_url", ""),
        "pages_checked": [
            page_urls.get("home_url", ""),
            page_urls.get("vault_url", ""),
            page_urls.get("index_url", ""),
            page_urls.get("detail_url", ""),
        ],
        "dominant_palette": accent,
        "contrast_status": contrast_status,
        "paywall_visibility_status": paywall_status,
        "checks": quality,
        "model": model_name,
        "visual_note": normalize_sentence(note),
        "assets": {
            "merged_png": str(MERGED_IMAGE.relative_to(ROOT)).replace("\\", "/"),
        },
    }
    STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def cleanup_temp_files() -> None:
    for path in (HOME_IMAGE, VAULT_IMAGE, INDEX_IMAGE, DETAIL_IMAGE):
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
        page_urls, quality = capture_images(cfg)
        build_collage()
    except Exception as exc:
        log_event("VISUAL_SNAPSHOT_FAILED", error=str(exc))
        cleanup_temp_files()
        return 1

    note, model_name = describe_with_gemini(cfg, quality)
    write_state(cfg, page_urls, quality, note, model_name)
    cleanup_temp_files()
    log_event(
        "VISUAL_SNAPSHOT_DONE",
        model=model_name,
        note=note,
        pages_checked=4,
        issues=quality.get("issues", []),
        image=str(MERGED_IMAGE.relative_to(ROOT)).replace("\\", "/"),
        state=str(STATE_FILE.relative_to(ROOT)).replace("\\", "/"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
