from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
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
DETAIL_IMAGE = LOGS_DIR / ".detail_vibe_tmp.png"
DETAIL_FOLD_IMAGE = LOGS_DIR / ".detail_fold_vibe_tmp.png"
MERGED_IMAGE = LOGS_DIR / "current_vibe.png"
STATE_FILE = LOGS_DIR / "visual_state.json"
SNAPSHOT_DIR = ROOT / "support" / "web" / "generated" / "snapshots"


@dataclass(frozen=True)
class UiQaConfig:
    base_url: str
    timeout_sec: float
    gemini_api_key: str
    gemini_model: str
    force_fallback: bool


@dataclass(frozen=True)
class ReportConfig:
    supabase_url: str
    supabase_service_role_key: str
    timeout_sec: float
    limit: int
    locale: str
    slug: str
    output_dir: Path
    binance_base_url: str


@dataclass(frozen=True)
class SnapshotConfig:
    mode: str
    uiqa: UiQaConfig
    report: ReportConfig


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
    if text[-1] not in {"。", "!", "！", "?", "？", "."}:
        text = f"{text}."
    return text


def parse_args() -> SnapshotConfig:
    parser = argparse.ArgumentParser(description="Visual snapshot tool: uiqa memory + report snapshot generation.")
    parser.add_argument("--mode", choices=("uiqa", "report"), default=os.getenv("VISUAL_SNAPSHOT_MODE", "uiqa"))
    parser.add_argument("--base-url", default=os.getenv("SUPPORT_BASE_URL", "http://127.0.0.1:4310"))
    parser.add_argument("--timeout-sec", type=float, default=float(os.getenv("VISUAL_TIMEOUT_SEC", "25")))
    parser.add_argument("--gemini-model", default=os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))
    parser.add_argument("--limit", type=int, default=int(os.getenv("SNAPSHOT_REPORT_LIMIT", "40")))
    parser.add_argument("--locale", default=str(os.getenv("SNAPSHOT_REPORT_LOCALE", "")).strip().lower())
    parser.add_argument("--slug", default=str(os.getenv("SNAPSHOT_REPORT_SLUG", "")).strip().lower())
    parser.add_argument("--force-fallback", action="store_true")
    args = parser.parse_args()

    uiqa_cfg = UiQaConfig(
        base_url=normalize_base_url(args.base_url),
        timeout_sec=max(8.0, float(args.timeout_sec)),
        gemini_api_key=str(os.getenv("GEMINI_API_KEY", "")).strip(),
        gemini_model=str(args.gemini_model or "").strip() or "gemini-1.5-flash",
        force_fallback=bool(args.force_fallback),
    )
    report_cfg = ReportConfig(
        supabase_url=str(os.getenv("SUPABASE_URL", "")).strip().rstrip("/"),
        supabase_service_role_key=str(os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip(),
        timeout_sec=max(8.0, float(args.timeout_sec)),
        limit=max(1, min(500, int(args.limit))),
        locale=str(args.locale or "").strip().lower(),
        slug=str(args.slug or "").strip().lower(),
        output_dir=SNAPSHOT_DIR,
        binance_base_url=str(os.getenv("BINANCE_SPOT_BASE_URL", "https://api.binance.com")).strip().rstrip("/"),
    )
    return SnapshotConfig(mode=str(args.mode or "uiqa"), uiqa=uiqa_cfg, report=report_cfg)


def ensure_matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec
    from matplotlib.patches import Rectangle

    return plt, GridSpec, Rectangle


def parse_float(raw: Any, default: float = 0.0) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if math.isnan(value) or math.isinf(value):
        return default
    return value


def normalize_symbol(raw: str) -> str:
    token = re.sub(r"[^A-Za-z]", "", str(raw or "").upper())
    if not token:
        return "BTCUSDT"
    if token.endswith("USDT"):
        return token
    return f"{token}USDT"


def infer_symbol(row: dict[str, Any]) -> str:
    evidence = row.get("evidence_pack")
    if isinstance(evidence, dict):
        asset = evidence.get("asset")
        if isinstance(asset, dict):
            symbol = str(asset.get("symbol") or "").strip()
            if symbol:
                return normalize_symbol(symbol)

    title = str(row.get("title") or "").upper()
    match = re.search(r"\(([A-Z]{2,10})\)", title)
    if match:
        return normalize_symbol(match.group(1))
    match = re.search(r"\b([A-Z]{2,10})/USDT\b", title)
    if match:
        return normalize_symbol(match.group(1))
    return "BTCUSDT"


def infer_asset_display_name(row: dict[str, Any], symbol: str) -> str:
    evidence = row.get("evidence_pack")
    if isinstance(evidence, dict):
        asset = evidence.get("asset")
        if isinstance(asset, dict):
            name = str(asset.get("name") or "").strip()
            ticker = str(asset.get("ticker") or "").strip().upper()
            if name and ticker:
                return f"{name} ({ticker})"
    ticker = symbol.replace("USDT", "")
    return f"{ticker.title()} ({ticker})"


def hash_seed(value: str) -> int:
    digest = hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def build_synthetic_klines(symbol: str, interval: str, limit: int, seed_source: str) -> list[dict[str, float]]:
    seed = hash_seed(f"{symbol}:{interval}:{seed_source}")
    base_price = 80.0 + (seed % 9000) / 10.0
    amplitude = 0.008 if interval == "1m" else 0.022
    candles: list[dict[str, float]] = []
    for idx in range(limit):
        phase = (idx / max(1, limit - 1)) * math.pi * 4.0
        wave = math.sin(phase + (seed % 97) * 0.01) * amplitude
        drift = ((seed % 31) - 15) / 12000.0
        open_price = base_price * (1.0 + wave + drift * idx)
        close_price = open_price * (1.0 + math.sin(phase * 1.9) * amplitude * 0.6)
        high_price = max(open_price, close_price) * (1.0 + abs(math.cos(phase * 1.4)) * amplitude * 0.8 + 0.0008)
        low_price = min(open_price, close_price) * (1.0 - abs(math.sin(phase * 1.6)) * amplitude * 0.8 - 0.0008)
        candles.append({"open": open_price, "high": high_price, "low": low_price, "close": close_price})
    return candles


def fetch_binance_klines(cfg: ReportConfig, symbol: str, interval: str, limit: int, seed_source: str) -> list[dict[str, float]]:
    endpoint = f"{cfg.binance_base_url}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": str(limit)}
    try:
        resp = requests.get(endpoint, params=params, timeout=(5.0, cfg.timeout_sec))
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, list):
            raise ValueError("invalid_klines_payload")
        out: list[dict[str, float]] = []
        for row in payload:
            if not isinstance(row, list) or len(row) < 5:
                continue
            out.append(
                {
                    "open": parse_float(row[1], 0.0),
                    "high": parse_float(row[2], 0.0),
                    "low": parse_float(row[3], 0.0),
                    "close": parse_float(row[4], 0.0),
                }
            )
        if len(out) < max(12, limit // 3):
            raise ValueError("insufficient_klines")
        return out[-limit:]
    except Exception as exc:  # noqa: BLE001
        log_event("REPORT_SNAPSHOT_BINANCE_FALLBACK", symbol=symbol, interval=interval, error=str(exc))
        return build_synthetic_klines(symbol=symbol, interval=interval, limit=limit, seed_source=seed_source)


def supabase_headers(cfg: ReportConfig) -> dict[str, str]:
    return {
        "apikey": cfg.supabase_service_role_key,
        "Authorization": f"Bearer {cfg.supabase_service_role_key}",
        "Content-Type": "application/json",
    }


def fetch_reports_for_snapshots(cfg: ReportConfig) -> list[dict[str, Any]]:
    if not cfg.supabase_url or not cfg.supabase_service_role_key:
        log_event(
            "REPORT_SNAPSHOT_CONFIG_MISSING",
            has_url=bool(cfg.supabase_url),
            has_service_role_key=bool(cfg.supabase_service_role_key),
        )
        return []

    params: dict[str, str] = {
        "select": "report_id,event_id,slug,title,locale,evidence_pack,verdict_pack,snapshot_url,updated_at,created_at",
        "order": "updated_at.desc",
        "limit": str(cfg.limit),
    }
    if cfg.slug:
        params["slug"] = f"eq.{cfg.slug}"
    if cfg.locale:
        params["locale"] = f"eq.{cfg.locale}"

    try:
        resp = requests.get(
            f"{cfg.supabase_url}/rest/v1/oracle_reports",
            headers=supabase_headers(cfg),
            params=params,
            timeout=(5.0, cfg.timeout_sec),
        )
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, list):
            return []
        return [row for row in payload if isinstance(row, dict) and str(row.get("slug") or "").strip()]
    except Exception as exc:  # noqa: BLE001
        log_event("REPORT_SNAPSHOT_FETCH_FAILED", error=str(exc))
        return []


def update_snapshot_url(cfg: ReportConfig, report_id: Any, snapshot_url: str) -> bool:
    if not report_id:
        return False
    try:
        resp = requests.patch(
            f"{cfg.supabase_url}/rest/v1/oracle_reports",
            headers={**supabase_headers(cfg), "Prefer": "return=minimal"},
            params={"report_id": f"eq.{int(report_id)}"},
            json={"snapshot_url": snapshot_url},
            timeout=(5.0, cfg.timeout_sec),
        )
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        log_event("REPORT_SNAPSHOT_DB_UPDATE_FAILED", report_id=report_id, error=str(exc))
        return False


def draw_candles(ax: Any, candles: list[dict[str, float]], color: str, rectangle_cls: Any, *, down_fill: bool = True) -> None:
    width = 0.62
    for idx, candle in enumerate(candles):
        o = parse_float(candle.get("open"), 0.0)
        h = parse_float(candle.get("high"), o)
        l = parse_float(candle.get("low"), o)
        c = parse_float(candle.get("close"), o)
        ax.vlines(idx, min(l, o, c), max(h, o, c), color=color, linewidth=0.8, alpha=0.98)
        body_low = min(o, c)
        body_height = max(abs(c - o), 1e-7)
        is_up = c >= o
        face = "none" if is_up else (color if down_fill else "none")
        body = rectangle_cls((idx - width / 2.0, body_low), width, body_height, linewidth=0.8, edgecolor=color, facecolor=face, alpha=0.98)
        ax.add_patch(body)


def apply_axis_style(ax: Any, grid_color: str) -> None:
    ax.set_facecolor("#050505")
    ax.grid(color=grid_color, linestyle="-", linewidth=0.4, alpha=0.4)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color("#151515")
        spine.set_linewidth(0.9)


def render_report_snapshot(cfg: ReportConfig, row: dict[str, Any]) -> tuple[bool, str]:
    plt, GridSpec, Rectangle = ensure_matplotlib()
    slug = str(row.get("slug") or "").strip().lower()
    if not slug:
        return False, ""

    evidence = row.get("evidence_pack") if isinstance(row.get("evidence_pack"), dict) else {}
    verdict = row.get("verdict_pack") if isinstance(row.get("verdict_pack"), dict) else {}
    v1 = evidence.get("v1") if isinstance(evidence.get("v1"), dict) else {}

    symbol = infer_symbol(row)
    asset_name = infer_asset_display_name(row, symbol)
    event_hash = str(row.get("event_id") or "")
    confidence = max(0.0, min(100.0, parse_float(verdict.get("confidence_score"), 0.0)))
    verdict_raw = str(verdict.get("structural_verdict") or "REBALANCING_WATCH").upper()
    vol_z = parse_float(v1.get("vol_z_score"), 0.0)
    k_delta = parse_float(v1.get("k_line_delta"), 0.0)

    micro = fetch_binance_klines(cfg=cfg, symbol=symbol, interval="1m", limit=80, seed_source=f"{event_hash}:{slug}:1m")
    macro = fetch_binance_klines(cfg=cfg, symbol=symbol, interval="4h", limit=80, seed_source=f"{event_hash}:{slug}:4h")
    if not micro or not macro:
        return False, slug

    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = cfg.output_dir / f"{slug}.png"

    fig = plt.figure(figsize=(16, 9), facecolor="#000000")
    grid = GridSpec(1, 3, width_ratios=[2, 1, 2], figure=fig, wspace=0.04)
    ax_left = fig.add_subplot(grid[0, 0])
    ax_center = fig.add_subplot(grid[0, 1])
    ax_right = fig.add_subplot(grid[0, 2])

    # Left panel: micro 1m
    apply_axis_style(ax_left, grid_color="#0a0a0a")
    draw_candles(ax_left, micro, "#D4AF37", Rectangle, down_fill=True)
    micro_lows = [parse_float(c.get("low"), 0.0) for c in micro]
    micro_highs = [parse_float(c.get("high"), 0.0) for c in micro]
    anomaly_idx = len(micro) - 1
    anomaly_y = micro_lows[anomaly_idx] if anomaly_idx >= 0 else 0.0
    ax_left.scatter([anomaly_idx], [anomaly_y], s=460, color="#FF4500", alpha=0.5, zorder=6)
    ax_left.scatter([anomaly_idx], [anomaly_y], s=180, color="#FF4500", alpha=0.8, zorder=7)
    ax_left.axvline(anomaly_idx, color="#333333", linestyle="--", linewidth=0.8, alpha=0.85)
    ax_left.axhline(anomaly_y, color="#333333", linestyle="--", linewidth=0.8, alpha=0.85)
    ax_left.set_xlim(-1, len(micro))
    if micro_lows and micro_highs:
        pad = (max(micro_highs) - min(micro_lows)) * 0.08 or 1.0
        ax_left.set_ylim(min(micro_lows) - pad, max(micro_highs) + pad)
    ax_left.text(0.98, 0.96, "MICRO_VIEW : 1M", transform=ax_left.transAxes, ha="right", va="top", color="#D4AF37", fontsize=11, family="monospace")
    ax_left.text(0.98, 0.91, f"{symbol}_PERP", transform=ax_left.transAxes, ha="right", va="top", color="#D4AF37", fontsize=9, family="monospace")
    ax_left.text(0.02, 0.04, "ANOMALY DETECTED // T-MINUS 0:00", transform=ax_left.transAxes, ha="left", va="bottom", color="#FF4500", fontsize=8.5, family="monospace")

    # Right panel: macro 4h
    apply_axis_style(ax_right, grid_color="#101010")
    draw_candles(ax_right, macro, "#C0C0C0", Rectangle, down_fill=True)
    macro_lows = [parse_float(c.get("low"), 0.0) for c in macro]
    macro_highs = [parse_float(c.get("high"), 0.0) for c in macro]
    if macro_lows and macro_highs:
        recent = macro[-24:] if len(macro) >= 24 else macro
        recent_high = [parse_float(c.get("high"), 0.0) for c in recent]
        recent_low = [parse_float(c.get("low"), 0.0) for c in recent]
        top = max(recent_high)
        bottom = min(recent_low)
        span = (top - bottom) * 0.12
        ax_right.axhspan(top - span, top, facecolor="#141414", alpha=0.8)
        ax_right.axhspan(bottom, bottom + span, facecolor="#141414", alpha=0.8)
        ax_right.text(0.02, 0.89, "RESISTANCE_ZONE // R1", transform=ax_right.transAxes, color="#C0C0C0", fontsize=8, family="monospace")
        ax_right.text(0.02, 0.08, "SUPPORT_ZONE // S1", transform=ax_right.transAxes, color="#C0C0C0", fontsize=8, family="monospace")
        pad = (max(macro_highs) - min(macro_lows)) * 0.08 or 1.0
        ax_right.set_ylim(min(macro_lows) - pad, max(macro_highs) + pad)
    ax_right.set_xlim(-1, len(macro))
    ax_right.text(0.02, 0.96, "MACRO_VIEW : 4H", transform=ax_right.transAxes, ha="left", va="top", color="#C0C0C0", fontsize=11, family="monospace")
    ax_right.text(0.02, 0.91, "STRUCTURAL_TENSION", transform=ax_right.transAxes, ha="left", va="top", color="#C0C0C0", fontsize=9, family="monospace")

    # Center panel: oracle verdict pillar
    ax_center.set_facecolor("#000000")
    ax_center.set_xticks([])
    ax_center.set_yticks([])
    for spine in ax_center.spines.values():
        spine.set_visible(False)
    pillar = Rectangle((0.08, 0.08), 0.84, 0.84, transform=ax_center.transAxes, facecolor="#050505", edgecolor=(1, 1, 1, 0.10), linewidth=1.0)
    ax_center.add_patch(pillar)
    ax_center.plot([0.10, 0.90], [0.91, 0.91], transform=ax_center.transAxes, color="#D4AF37", linewidth=1.4, alpha=0.9)
    ax_center.plot([0.10, 0.90], [0.09, 0.09], transform=ax_center.transAxes, color="#D4AF37", linewidth=1.4, alpha=0.9)
    ax_center.text(0.5, 0.83, "CONFIDENCE METRIC", transform=ax_center.transAxes, ha="center", va="center", color="#666666", fontsize=9, family="monospace")
    ax_center.text(0.5, 0.57, f"{confidence:.0f}%", transform=ax_center.transAxes, ha="center", va="center", color="#D4AF37", fontsize=46, family="monospace", fontweight="bold")
    ax_center.text(0.5, 0.40, f"STRUCTURAL BIAS: {verdict_raw}", transform=ax_center.transAxes, ha="center", va="center", color="#FF4500", fontsize=10, family="monospace")
    ax_center.text(0.5, 0.26, f"{asset_name} | {symbol}", transform=ax_center.transAxes, ha="center", va="center", color="#C0C0C0", fontsize=8.8, family="monospace")
    ax_center.text(0.5, 0.13, "> SYSTEM PROTOCOL EXECUTED...\n> DEPLOY CAPITAL.", transform=ax_center.transAxes, ha="center", va="center", color="#555555", fontsize=8, family="monospace")

    # Global watermark
    fig.text(0.03, 0.96, "LEIMAI ORACLE", color="#E0E0E0", fontsize=16, family="serif", ha="left", va="top")
    fig.text(0.03, 0.925, "OMNISCIENT QUANTITATIVE ENGINE", color="#666666", fontsize=9, family="monospace", ha="left", va="top")
    fig.text(0.97, 0.06, "DIGITAL SIGNATURE STAMP", color="#666666", fontsize=8.5, family="monospace", ha="right", va="bottom")
    fig.text(0.97, 0.035, event_hash[-32:] if event_hash else slug, color="#444444", fontsize=8, family="monospace", ha="right", va="bottom")
    fig.text(0.03, 0.03, f"Vol_Z {vol_z:.2f} | Delta {k_delta:.2f} | {utc_now_iso()}", color="#666666", fontsize=8, family="monospace", ha="left", va="bottom")

    fig.savefig(output_path, dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig)
    try:
        img = Image.open(output_path).convert("RGB")
        if img.size != (1600, 900):
            img = img.resize((1600, 900), Image.Resampling.LANCZOS)
            img.save(output_path, format="PNG")
    except Exception as exc:  # noqa: BLE001
        log_event("REPORT_SNAPSHOT_POSTPROCESS_WARN", slug=slug, error=str(exc))
    return True, slug


def run_report_snapshot_mode(cfg: ReportConfig) -> int:
    log_event(
        "REPORT_SNAPSHOT_MODE_START",
        limit=cfg.limit,
        locale=cfg.locale or "all",
        slug=cfg.slug or "",
        output_dir=str(cfg.output_dir.relative_to(ROOT)).replace("\\", "/"),
    )
    reports = fetch_reports_for_snapshots(cfg)
    if not reports:
        log_event("REPORT_SNAPSHOT_NO_REPORTS")
        return 0

    generated = 0
    failed = 0
    db_updated = 0
    for row in reports:
        ok, slug = render_report_snapshot(cfg, row)
        if not ok or not slug:
            failed += 1
            continue
        generated += 1
        snapshot_url = f"/generated/snapshots/{slug}.png"
        if update_snapshot_url(cfg, row.get("report_id"), snapshot_url):
            db_updated += 1
        log_event("REPORT_SNAPSHOT_WRITTEN", report_id=row.get("report_id"), slug=slug, snapshot_url=snapshot_url)

    log_event(
        "REPORT_SNAPSHOT_MODE_DONE",
        total=len(reports),
        generated=generated,
        failed=failed,
        db_updated=db_updated,
    )
    return 0


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
          const fontPx = Number.parseFloat(bodyStyle.fontSize || '0') || 0;
          const viewportArea = Math.max(1, window.innerWidth * window.innerHeight);

          const unlockBtn = document.querySelector('.unlock-btn');
          let ctaAreaRatio = 0;
          if (unlockBtn) {
            const rect = unlockBtn.getBoundingClientRect();
            ctaAreaRatio = Math.max(0, (rect.width * rect.height) / viewportArea);
          }

          const overflowHotspots = [];
          const hotspotSelectors = ['.hero h1', '.card-mid', '.card-sub', '.report-entity', '.meta-hash', '.route-line', '.lock-message'];
          hotspotSelectors.forEach((selector) => {
            document.querySelectorAll(selector).forEach((el) => {
              const style = window.getComputedStyle(el);
              if (style.display === 'none' || style.visibility === 'hidden') return;
              const rect = el.getBoundingClientRect();
              if (rect.width < 2 || rect.height < 2) return;
              if (el.scrollWidth > el.clientWidth + 2) {
                overflowHotspots.push({
                  selector,
                  scrollWidth: el.scrollWidth,
                  clientWidth: el.clientWidth,
                });
              }
            });
          });

          const hasReportArticle = !!document.querySelector('.report-article, .article-body');
          const hasPaywallShell = !!document.querySelector('.paywall-shell');
          const path = String(window.location.pathname || '');
          const detailIsReal = path.startsWith('/analysis/') && !path.endsWith('/non-existent') && (hasReportArticle || hasPaywallShell);

          const readabilityScore = (() => {
            let score = 100;
            if (minContrast > 0 && minContrast < 4.5) score -= 28;
            if (fontPx < 14) score -= 18;
            if (Number.isFinite(lineHeightPx) && lineHeightPx > 0 && lineHeightPx < 20) score -= 14;
            if (overflowHotspots.length > 0) score -= Math.min(26, overflowHotspots.length * 6);
            return Math.max(0, Math.min(100, Math.round(score)));
          })();

          const ctaProminenceScore = (() => {
            let score = 38;
            if (isVisible('.unlock-btn')) score += 24;
            if (typeof samples.unlock_button === 'number') {
              score += Math.min(22, samples.unlock_button * 2.2);
            }
            score += Math.min(16, ctaAreaRatio * 4500);
            return Math.max(0, Math.min(100, Math.round(score)));
          })();

          return {
            url: window.location.href,
            pathname: path,
            title: document.title || '',
            low_gpu_mode: document.body.classList.contains('low-gpu'),
            matrix_canvas_visible: isVisible('#matrix-bg'),
            has_report_article: hasReportArticle,
            has_paywall_shell: hasPaywallShell,
            detail_is_real_report: detailIsReal,
            report_card_count: document.querySelectorAll('.report-card').length,
            analysis_links_count: document.querySelectorAll("a[href^='/analysis/']").length,
            paywall_lock_visible: isVisible('.paywall-locked-content'),
            paywall_unlock_visible: isVisible('.unlock-btn'),
            paywall_fog_visible: isVisible('.obsidian-fog'),
            has_horizontal_overflow: document.documentElement.scrollWidth > window.innerWidth + 2,
            overflow_hotspots: overflowHotspots,
            text_nodes: document.querySelectorAll('p, li').length,
            body_font_px: fontPx,
            body_line_height_px: Number.isFinite(lineHeightPx) ? lineHeightPx : 0,
            accent_css: String(rootStyle.getPropertyValue('--accent') || '').trim(),
            contrast_samples: samples,
            text_contrast_min: Number(minContrast.toFixed(2)),
            text_contrast_avg: Number(avgContrast.toFixed(2)),
            readability_score: readabilityScore,
            cta_prominence_score: ctaProminenceScore,
          };
        }
        """
    )


def aggregate_checks(page_checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pages = [page_checks.get(k, {}) for k in ("home", "detail")]
    min_values = [float(p.get("text_contrast_min", 0)) for p in pages if float(p.get("text_contrast_min", 0)) > 0]
    avg_values = [float(p.get("text_contrast_avg", 0)) for p in pages if float(p.get("text_contrast_avg", 0)) > 0]

    text_contrast_min = min(min_values) if min_values else 0.0
    text_contrast_avg = sum(avg_values) / len(avg_values) if avg_values else 0.0
    detail_page = page_checks.get("detail", {})
    index_page = page_checks.get("index", {})
    detail_is_real_report = bool(detail_page.get("detail_is_real_report", False))
    index_has_reports = int(index_page.get("report_card_count", 0) or 0) > 0
    paywall_lock_visible = bool(detail_page.get("paywall_lock_visible", False))
    paywall_unlock_visible = bool(detail_page.get("paywall_unlock_visible", False))
    paywall_fog_visible = bool(detail_page.get("paywall_fog_visible", False))
    matrix_canvas_visible = bool(page_checks.get("home", {}).get("matrix_canvas_visible", False))
    low_gpu_mode = bool(page_checks.get("home", {}).get("low_gpu_mode", False))
    has_horizontal_overflow = any(bool(p.get("has_horizontal_overflow", False)) for p in pages)
    overflow_hotspots = []
    for page_name, payload in page_checks.items():
        for spot in payload.get("overflow_hotspots", []) if isinstance(payload, dict) else []:
            if isinstance(spot, dict):
                overflow_hotspots.append({"page": page_name, **spot})

    readability_values = [float(p.get("readability_score", 0)) for p in pages]
    cta_values = [float(p.get("cta_prominence_score", 0)) for p in pages]

    issues: list[str] = []
    if text_contrast_min and text_contrast_min < 4.5:
        issues.append("text_contrast_below_wcag_aa")
    if index_has_reports and not detail_is_real_report:
        issues.append("detail_not_real_report")
    elif detail_is_real_report:
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
    if overflow_hotspots:
        issues.append("element_overflow_hotspots")

    return {
        "text_contrast_min": round(text_contrast_min, 2),
        "text_contrast_avg": round(text_contrast_avg, 2),
        "paywall_lock_visible": paywall_lock_visible,
        "paywall_unlock_visible": paywall_unlock_visible,
        "paywall_fog_visible": paywall_fog_visible,
        "index_has_reports": index_has_reports,
        "index_report_card_count": int(index_page.get("report_card_count", 0) or 0),
        "detail_is_real_report": detail_is_real_report,
        "matrix_canvas_visible": matrix_canvas_visible,
        "low_gpu_mode": low_gpu_mode,
        "has_horizontal_overflow": has_horizontal_overflow,
        "overflow_hotspots": overflow_hotspots,
        "cta_prominence_score": round(sum(cta_values) / max(1, len(cta_values)), 1),
        "readability_score": round(sum(readability_values) / max(1, len(readability_values)), 1),
        "issues": issues,
        "issue_count": len(issues),
        "pages": page_checks,
    }


def capture_images(cfg: UiQaConfig) -> tuple[dict[str, str], dict[str, Any]]:
    timeout_ms = int(cfg.timeout_sec * 1000)
    home_url = f"{cfg.base_url}/"
    index_url = f"{cfg.base_url}/analysis/"
    detail_url = f"{cfg.base_url}/analysis/non-existent"
    page_checks: dict[str, dict[str, Any]] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1536, "height": 960})

        page.goto(home_url, wait_until="networkidle", timeout=timeout_ms)
        page.screenshot(path=str(HOME_IMAGE), full_page=True)
        page_checks["home"] = collect_page_checks(page)

        page.goto(index_url, wait_until="networkidle", timeout=timeout_ms)
        page_checks["index"] = collect_page_checks(page)
        try:
            href = page.eval_on_selector_all(
                "a[href^='/analysis/']",
                """nodes => {
                  const hrefs = nodes
                    .map(n => (n && n.getAttribute ? n.getAttribute('href') : null))
                    .filter(Boolean)
                    .filter(h => h !== '/analysis/' && h !== '/analysis');
                  return hrefs.length ? hrefs[0] : null;
                }""",
            )
            if isinstance(href, str) and href.strip():
                detail_url = f"{cfg.base_url}{href.strip()}"
        except PlaywrightError:
            detail_url = f"{cfg.base_url}/analysis/non-existent"

        page.goto(detail_url, wait_until="networkidle", timeout=timeout_ms)
        page.screenshot(path=str(DETAIL_IMAGE), full_page=False)
        page_checks["detail"] = collect_page_checks(page)

        page.evaluate("window.scrollTo(0, Math.max(document.body.scrollHeight * 0.62, 720));")
        page.wait_for_timeout(450)
        page.screenshot(path=str(DETAIL_FOLD_IMAGE), full_page=False)

        browser.close()

    return (
        {
            "home_url": home_url,
            "index_url": index_url,
            "detail_url": detail_url,
        },
        aggregate_checks(page_checks),
    )


def build_collage() -> None:
    left = Image.open(HOME_IMAGE).convert("RGB")
    right = Image.open(DETAIL_IMAGE).convert("RGB")
    target_h = max(left.height, right.height)

    if left.height != target_h:
        left = left.resize((int(left.width * target_h / left.height), target_h))
    if right.height != target_h:
        right = right.resize((int(right.width * target_h / right.height), target_h))

    merged = Image.new("RGB", (left.width + right.width, target_h))
    merged.paste(left, (0, 0))
    merged.paste(right, (left.width, 0))
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
    detail_real = bool(quality.get("detail_is_real_report", False))
    cta_score = float(quality.get("cta_prominence_score", 0.0) or 0.0)
    readability = float(quality.get("readability_score", 0.0) or 0.0)
    return (
        f"當前為 {accent} 配色，最小對比度 {contrast:.2f}，"
        f"詳情頁{'已' if detail_real else '未'}對準真實報告，"
        f"可讀性分數 {readability:.0f}，解鎖按鈕顯著度 {cta_score:.0f}。"
    )


def describe_with_gemini(cfg: UiQaConfig, quality: dict[str, Any]) -> tuple[str, str]:
    if cfg.force_fallback or not cfg.gemini_api_key:
        return normalize_sentence(fallback_note(quality)), "fallback"

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.gemini_model}:generateContent"
    image_b64 = base64.b64encode(MERGED_IMAGE.read_bytes()).decode("utf-8")
    prompt = (
        "你是視覺審核助手。只輸出一句繁體中文，描述目前 UI 狀態。"
        "句子必須包含：配色（24K 金或白金銀）、詳情頁是否為真實報告、"
        "文字可讀性與解鎖按鈕顯著度。"
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
    cfg: UiQaConfig,
    page_urls: dict[str, str],
    quality: dict[str, Any],
    note: str,
    model_name: str,
) -> None:
    accent = estimate_accent_label()
    contrast_min = float(quality.get("text_contrast_min", 0.0) or 0.0)
    contrast_status = "high" if contrast_min >= 4.5 else "low"
    payload = {
        "ts_utc": utc_now_iso(),
        "base_url": cfg.base_url,
        "home_url": page_urls.get("home_url", ""),
        "index_url": page_urls.get("index_url", ""),
        "detail_url": page_urls.get("detail_url", ""),
        "pages_checked": [
            page_urls.get("home_url", ""),
            page_urls.get("detail_url", ""),
        ],
        "dominant_palette": accent,
        "contrast_status": contrast_status,
        "checks": quality,
        "model": model_name,
        "visual_note": normalize_sentence(note),
        "assets": {
            "merged_png": str(MERGED_IMAGE.relative_to(ROOT)).replace("\\", "/"),
        },
    }
    STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def cleanup_temp_files() -> None:
    for path in (HOME_IMAGE, DETAIL_IMAGE, DETAIL_FOLD_IMAGE):
        try:
            if path.exists():
                path.unlink()
        except Exception:
            continue


def run_uiqa_mode(cfg: UiQaConfig) -> int:
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
        pages_checked=2,
        issues=quality.get("issues", []),
        image=str(MERGED_IMAGE.relative_to(ROOT)).replace("\\", "/"),
        state=str(STATE_FILE.relative_to(ROOT)).replace("\\", "/"),
    )
    return 0


def main() -> int:
    cfg = parse_args()
    if cfg.mode == "report":
        return run_report_snapshot_mode(cfg.report)
    return run_uiqa_mode(cfg.uiqa)


if __name__ == "__main__":
    raise SystemExit(main())
