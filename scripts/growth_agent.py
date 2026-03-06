from __future__ import annotations

import argparse
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = ROOT / "logs"
OVERRIDES_PATH = ROOT / "support" / "web" / "generated" / "growth_overrides.json"
SCOREBOARD_PATH = LOGS_DIR / "growth_scoreboard.json"
ACTIONS_PATH = LOGS_DIR / "agent_actions.jsonl"
HISTORY_PATH = LOGS_DIR / "growth_history.jsonl"
ROLLBACK_PATH = LOGS_DIR / "rollback_journal.jsonl"
STABLE_OVERRIDES_PATH = LOGS_DIR / "growth_stable_overrides.json"

REQUIRED_HREFLANGS = {"x-default", "en", "zh-hant", "es", "ja"}
ENTITY_ANCHOR = "LeiMai Liquidity Friction"


@dataclass(frozen=True)
class AgentConfig:
    mode: str
    base_url: str
    timeout_sec: float
    min_total: float
    min_conversion: float
    min_reliability: float
    max_drawdown_pct: float
    supabase_url: str
    supabase_service_role_key: str
    lookback_days: int


VARIANTS: list[dict[str, Any]] = [
    {
        "id": "control_v1",
        "copy_overrides": {
            "en": {},
            "zh-tw": {},
            "es": {},
            "ja": {},
        },
    },
    {
        "id": "conversion_focus_v1",
        "copy_overrides": {
            "en": {
                "homeLead": "Institution-grade intelligence built for high-intent operators. Validate signal fast, then unlock sovereign execution.",
                "homeOpenIndex": "Open Signals and Unlock Conversion",
                "vaultLead": "Sovereign model calibrated for execution. Sign once to activate commercial intelligence access.",
            },
            "zh-tw": {
                "homeLead": "為高意向操作者打造的機構級情報流。先快速驗證訊號，再解鎖主權執行層。",
                "homeOpenIndex": "開啟訊號並進入轉化",
                "vaultLead": "主權模型已進入可執行狀態，簽署一次即可啟用商業情報通道。",
            },
            "es": {
                "homeLead": "Inteligencia institucional para operadores de alta intencion. Valida la senal y desbloquea ejecucion soberana.",
                "homeOpenIndex": "Abrir Senales y Desbloquear Conversion",
                "vaultLead": "Modelo soberano listo para ejecucion. Firma una vez para activar acceso comercial.",
            },
            "ja": {
                "homeLead": "高意図オペレーター向け機関級インテリジェンス。シグナル検証後に主権実行レイヤーを解放。",
                "homeOpenIndex": "シグナルを開き転換を開始",
                "vaultLead": "主権モデルは実行可能状態。1 回の署名で商用インテリジェンスアクセスを有効化。",
            },
        },
    },
    {
        "id": "geo_snippet_v1",
        "copy_overrides": {
            "en": {
                "analysisLead": "AI-citable multilingual intelligence pages with explicit Evidence and Risk Boundary sections.",
                "homeLatestLead": "Citation-ready snapshots with canonical traceability.",
            },
            "zh-tw": {
                "analysisLead": "可被 AI 引用的多語情報頁，含明確證據與風險邊界段落。",
                "homeLatestLead": "具 canonical 可追溯性的可引用快照。",
            },
            "es": {
                "analysisLead": "Paginas multilingues citables por IA con secciones claras de Evidencia y Frontera de Riesgo.",
                "homeLatestLead": "Snapshots listos para citacion con trazabilidad canonical.",
            },
            "ja": {
                "analysisLead": "Evidence と Risk Boundary を明示した AI 引用可能な多言語ページ。",
                "homeLatestLead": "canonical 追跡可能な引用準備済みスナップショット。",
            },
        },
    },
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_event(event: str, **kwargs: Any) -> None:
    print(json.dumps({"ts_utc": utc_now_iso(), "event": event, **kwargs}, ensure_ascii=False))


def normalize_base_url(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return "http://127.0.0.1:4310"
    if text.endswith("/"):
        return text[:-1]
    return text


def parse_args() -> AgentConfig:
    parser = argparse.ArgumentParser(
        description="Growth agent: SEO/GEO/conversion scoring + autonomous variant iteration."
    )
    parser.add_argument("--mode", choices=("observe", "iterate"), default=os.getenv("GROWTH_AGENT_MODE", "iterate"))
    parser.add_argument("--base-url", default=os.getenv("SUPPORT_BASE_URL", "http://127.0.0.1:4310"))
    parser.add_argument("--timeout-sec", type=float, default=float(os.getenv("GROWTH_AGENT_TIMEOUT_SEC", "12")))
    parser.add_argument("--min-total", type=float, default=float(os.getenv("GROWTH_AGENT_MIN_TOTAL", "88")))
    parser.add_argument("--min-conversion", type=float, default=float(os.getenv("GROWTH_AGENT_MIN_CONVERSION", "80")))
    parser.add_argument("--min-reliability", type=float, default=float(os.getenv("GROWTH_AGENT_MIN_RELIABILITY", "95")))
    parser.add_argument("--max-drawdown-pct", type=float, default=float(os.getenv("GROWTH_AGENT_MAX_DRAWDOWN_PCT", "12")))
    parser.add_argument("--lookback-days", type=int, default=int(os.getenv("GROWTH_AGENT_LOOKBACK_DAYS", "7")))
    args = parser.parse_args()

    load_dotenv()
    return AgentConfig(
        mode=str(args.mode or "iterate").strip().lower(),
        base_url=normalize_base_url(args.base_url),
        timeout_sec=max(4.0, float(args.timeout_sec)),
        min_total=float(args.min_total),
        min_conversion=float(args.min_conversion),
        min_reliability=float(args.min_reliability),
        max_drawdown_pct=max(1.0, float(args.max_drawdown_pct)),
        supabase_url=str(os.getenv("SUPABASE_URL", "")).strip().rstrip("/"),
        supabase_service_role_key=str(os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip(),
        lookback_days=max(3, min(30, int(args.lookback_days))),
    )


def _safe_float(raw: Any, default: float = 0.0) -> float:
    try:
        value = float(raw)
    except Exception:
        return default
    if math.isnan(value) or math.isinf(value):
        return default
    return value


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False))
        fp.write("\n")


def _http_get_text(url: str, timeout_sec: float) -> tuple[int, str, float]:
    started = datetime.now(timezone.utc)
    try:
        resp = requests.get(url, timeout=timeout_sec)
        latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000.0
        return int(resp.status_code), str(resp.text or ""), latency_ms
    except Exception:
        latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000.0
        return 0, "", latency_ms


def _http_get_json(url: str, timeout_sec: float) -> tuple[int, dict[str, Any]]:
    code, text, _ = _http_get_text(url, timeout_sec)
    if code < 200 or code >= 400:
        return code, {}
    try:
        payload = json.loads(text)
        return code, payload if isinstance(payload, dict) else {}
    except Exception:
        return code, {}


def _contains_jsonld(html: str) -> bool:
    return bool(re.search(r"<script[^>]+application/ld\+json", html, flags=re.IGNORECASE))


def _has_canonical(html: str) -> bool:
    return bool(re.search(r'<link[^>]+rel=["\']canonical["\']', html, flags=re.IGNORECASE))


def _hreflangs(html: str) -> set[str]:
    out: set[str] = set()
    for match in re.finditer(r'hreflang=["\']([^"\']+)["\']', html, flags=re.IGNORECASE):
        out.add(str(match.group(1) or "").strip().lower())
    return out


def _score_surface(base_url: str, timeout_sec: float) -> tuple[dict[str, Any], dict[str, Any]]:
    core_pages = ["/", "/analysis/", "/vault"]
    aux_pages = [
        "/robots.txt",
        "/sitemap-index.xml",
        "/sitemap-static.xml",
        "/sitemap-analysis.xml",
        "/llms.txt",
        "/.well-known/ai-citation-feed.json",
    ]

    page_checks: list[dict[str, Any]] = []
    latencies: list[float] = []

    for route in [*core_pages, *aux_pages]:
        code, body, latency = _http_get_text(f"{base_url}{route}", timeout_sec)
        latencies.append(latency)
        row = {
            "route": route,
            "status": code,
            "latency_ms": round(latency, 2),
            "ok": 200 <= code < 400,
            "has_canonical": _has_canonical(body) if route in core_pages else None,
            "has_jsonld": _contains_jsonld(body) if route in core_pages else None,
            "hreflangs": sorted(_hreflangs(body)) if route in core_pages else [],
        }
        page_checks.append(row)

    core_rows = [row for row in page_checks if row["route"] in core_pages]
    aux_rows = [row for row in page_checks if row["route"] in aux_pages]
    core_ok = sum(1 for row in core_rows if bool(row["ok"]))
    aux_ok = sum(1 for row in aux_rows if bool(row["ok"]))
    canonical_ok = sum(1 for row in core_rows if bool(row.get("has_canonical")))
    jsonld_ok = sum(1 for row in core_rows if bool(row.get("has_jsonld")))
    hreflang_ok = sum(
        1 for row in core_rows if REQUIRED_HREFLANGS.issubset(set(row.get("hreflangs") or []))
    )
    uptime_ratio = 100.0 * (core_ok + aux_ok) / max(1, len(page_checks))
    sorted_lat = sorted(latencies)
    p95_latency = sorted_lat[int(len(sorted_lat) * 0.95)] if sorted_lat else 0.0
    latency_score = _clamp(100.0 - max(0.0, p95_latency - 800.0) / 14.0)
    reliability = round((uptime_ratio * 0.72) + (latency_score * 0.28), 2)

    seo_score = round(
        (100.0 * core_ok / max(1, len(core_rows)) * 0.30)
        + (100.0 * canonical_ok / max(1, len(core_rows)) * 0.20)
        + (100.0 * jsonld_ok / max(1, len(core_rows)) * 0.20)
        + (100.0 * hreflang_ok / max(1, len(core_rows)) * 0.15)
        + (100.0 * aux_ok / max(1, len(aux_rows)) * 0.15),
        2,
    )

    diagnostics = {
        "checks": page_checks,
        "uptime_ratio": round(uptime_ratio, 2),
        "latency_p95_ms": round(p95_latency, 2),
        "latency_score": round(latency_score, 2),
        "core_ok_count": core_ok,
        "aux_ok_count": aux_ok,
        "canonical_ok_count": canonical_ok,
        "jsonld_ok_count": jsonld_ok,
        "hreflang_ok_count": hreflang_ok,
    }
    return {"seo_score": seo_score, "reliability_score": reliability}, diagnostics


def _score_geo(base_url: str, timeout_sec: float) -> tuple[float, dict[str, Any]]:
    llms_code, llms_text, _ = _http_get_text(f"{base_url}/llms.txt", timeout_sec)
    feed_code, feed_json = _http_get_json(f"{base_url}/.well-known/ai-citation-feed.json", timeout_sec)
    feed = feed_json if bool(feed_json.get("ok")) else feed_json
    items = feed.get("items", []) if isinstance(feed, dict) else []
    if not isinstance(items, list):
        items = []

    llms_ok = llms_code >= 200 and llms_code < 400
    llms_sections = [
        "Canonical policy" in llms_text,
        "Citation feed" in llms_text,
        "Entry pages" in llms_text,
    ]
    llms_depth_score = 100.0 * sum(1 for ok in llms_sections if ok) / len(llms_sections)

    snippet_ok = 0
    risk_ok = 0
    entity_ok = 0
    locales: set[str] = set()
    for row in items:
        if not isinstance(row, dict):
            continue
        locales.add(str(row.get("locale") or "").strip().lower())
        snippets = row.get("snippets") if isinstance(row.get("snippets"), dict) else {}
        if snippets.get("words_40") and snippets.get("words_80") and snippets.get("words_160"):
            snippet_ok += 1
        if str(row.get("risk_boundary") or "").strip():
            risk_ok += 1
        if str(row.get("unique_entity") or "").strip() == ENTITY_ANCHOR:
            entity_ok += 1

    item_count = len(items)
    feed_availability_score = 100.0 if (200 <= feed_code < 400 and item_count > 0) else (60.0 if 200 <= feed_code < 400 else 0.0)
    snippet_score = 100.0 * snippet_ok / max(1, item_count)
    risk_score = 100.0 * risk_ok / max(1, item_count)
    entity_score = 100.0 * entity_ok / max(1, item_count)
    locale_score = _clamp((len(locales) / 4.0) * 100.0)

    geo_score = round(
        (feed_availability_score * 0.30)
        + (llms_depth_score * 0.20)
        + (snippet_score * 0.20)
        + (risk_score * 0.15)
        + (entity_score * 0.10)
        + (locale_score * 0.05),
        2,
    )
    diagnostics = {
        "llms_status": llms_code,
        "llms_depth_score": round(llms_depth_score, 2),
        "feed_status": feed_code,
        "feed_item_count": item_count,
        "snippet_ok_count": snippet_ok,
        "risk_ok_count": risk_ok,
        "entity_ok_count": entity_ok,
        "locales_found": sorted([loc for loc in locales if loc]),
    }
    return geo_score, diagnostics


def _supabase_headers(cfg: AgentConfig) -> dict[str, str]:
    return {
        "apikey": cfg.supabase_service_role_key,
        "Authorization": f"Bearer {cfg.supabase_service_role_key}",
        "Content-Type": "application/json",
    }


def _fetch_conversion_metrics(cfg: AgentConfig) -> tuple[float, dict[str, Any]]:
    if not cfg.supabase_url or not cfg.supabase_service_role_key:
        return 70.0, {"data_source": "none", "reason": "supabase_config_missing", "initiated": 0, "paid": 0}

    window_start = (datetime.now(timezone.utc) - timedelta(days=cfg.lookback_days)).isoformat()
    params = {
        "select": "status,created_at",
        "created_at": f"gte.{window_start}",
        "order": "created_at.desc",
        "limit": "5000",
    }
    try:
        resp = requests.get(
            f"{cfg.supabase_url}/rest/v1/payment_invoices",
            headers=_supabase_headers(cfg),
            params=params,
            timeout=(5.0, cfg.timeout_sec),
        )
        if resp.status_code < 200 or resp.status_code >= 300:
            return 70.0, {
                "data_source": "supabase",
                "reason": f"http_{resp.status_code}",
                "initiated": 0,
                "paid": 0,
            }
        payload = resp.json()
        if not isinstance(payload, list):
            return 70.0, {"data_source": "supabase", "reason": "invalid_payload", "initiated": 0, "paid": 0}
        initiated = len(payload)
        paid = sum(1 for row in payload if str((row or {}).get("status") or "").strip().lower() == "paid")
        if initiated <= 0:
            return 70.0, {"data_source": "supabase", "reason": "empty_window", "initiated": 0, "paid": 0}

        success_rate = (paid / initiated) * 100.0
        # reward stable volume slightly, but north-star remains payment success rate
        volume_confidence = min(10.0, math.log2(max(1.0, initiated)) * 2.0)
        score = _clamp(success_rate * 0.92 + volume_confidence)
        return round(score, 2), {
            "data_source": "supabase",
            "initiated": initiated,
            "paid": paid,
            "payment_success_rate": round(success_rate, 2),
            "volume_confidence_bonus": round(volume_confidence, 2),
        }
    except Exception as exc:  # noqa: BLE001
        return 70.0, {"data_source": "supabase", "reason": str(exc), "initiated": 0, "paid": 0}


def _fetch_content_quality(cfg: AgentConfig) -> tuple[float, dict[str, Any]]:
    if not cfg.supabase_url or not cfg.supabase_service_role_key:
        return 72.0, {"data_source": "none", "reason": "supabase_config_missing", "rows": 0}
    params = {
        "select": "slug,locale,title,unique_entity,body_md,updated_at",
        "order": "updated_at.desc",
        "limit": "120",
    }
    try:
        resp = requests.get(
            f"{cfg.supabase_url}/rest/v1/oracle_reports",
            headers=_supabase_headers(cfg),
            params=params,
            timeout=(5.0, cfg.timeout_sec),
        )
        if resp.status_code < 200 or resp.status_code >= 300:
            return 72.0, {"data_source": "supabase", "reason": f"http_{resp.status_code}", "rows": 0}
        payload = resp.json()
        if not isinstance(payload, list):
            return 72.0, {"data_source": "supabase", "reason": "invalid_payload", "rows": 0}

        rows = [row for row in payload if isinstance(row, dict)]
        if not rows:
            return 72.0, {"data_source": "supabase", "reason": "empty_payload", "rows": 0}

        entity_ok = 0
        evidence_ok = 0
        risk_ok = 0
        locale_map: dict[str, int] = {}
        for row in rows:
            locale = str(row.get("locale") or "").strip().lower()
            locale_map[locale] = locale_map.get(locale, 0) + 1
            if str(row.get("unique_entity") or "").strip() == ENTITY_ANCHOR:
                entity_ok += 1
            body = str(row.get("body_md") or "")
            if re.search(r"(?:^|\n)#{1,6}\s*(Evidence|證據)\s*\n", body, flags=re.IGNORECASE):
                evidence_ok += 1
            if re.search(r"(?:^|\n)#{1,6}\s*(Risk Boundary|風險邊界)\s*\n", body, flags=re.IGNORECASE):
                risk_ok += 1

        count = len(rows)
        entity_score = 100.0 * entity_ok / count
        evidence_score = 100.0 * evidence_ok / count
        risk_score = 100.0 * risk_ok / count
        locale_score = _clamp((len([k for k, v in locale_map.items() if v > 0]) / 4.0) * 100.0)
        quality = round(
            (entity_score * 0.35) + (evidence_score * 0.30) + (risk_score * 0.25) + (locale_score * 0.10),
            2,
        )
        return quality, {
            "data_source": "supabase",
            "rows": count,
            "entity_ok": entity_ok,
            "evidence_ok": evidence_ok,
            "risk_boundary_ok": risk_ok,
            "locales": locale_map,
        }
    except Exception as exc:  # noqa: BLE001
        return 72.0, {"data_source": "supabase", "reason": str(exc), "rows": 0}


def _median(values: list[float]) -> float:
    clean = sorted([_safe_float(v, math.nan) for v in values if not math.isnan(_safe_float(v, math.nan))])
    if not clean:
        return 0.0
    mid = len(clean) // 2
    if len(clean) % 2 == 1:
        return clean[mid]
    return (clean[mid - 1] + clean[mid]) / 2.0


def _read_history(limit: int = 60) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    except Exception:
        return []
    return rows[-max(1, limit) :]


def _variant_payload(variant_id: str) -> dict[str, Any]:
    for row in VARIANTS:
        if str(row.get("id")) == variant_id:
            return row
    return VARIANTS[0]


def _read_active_variant_id() -> str:
    payload = _read_json(OVERRIDES_PATH, {})
    return str(payload.get("variant_id") or "control_v1")


def _write_variant(variant_id: str, reason: str) -> dict[str, Any]:
    variant = _variant_payload(variant_id)
    payload = {
        "version": 1,
        "updated_at": utc_now_iso(),
        "variant_id": variant["id"],
        "copy_overrides": variant["copy_overrides"],
        "meta": {
            "owner": "growth-agent",
            "reason": reason,
        },
    }
    _write_json(OVERRIDES_PATH, payload)
    return payload


def _choose_next_variant(active_variant_id: str, seo_score: float, geo_score: float, conversion_score: float) -> str:
    if conversion_score < 80.0:
        return "conversion_focus_v1"
    if geo_score < 85.0 or seo_score < 85.0:
        return "geo_snippet_v1"
    return active_variant_id


def build_scoreboard(cfg: AgentConfig) -> dict[str, Any]:
    surface_scores, surface_diag = _score_surface(cfg.base_url, cfg.timeout_sec)
    geo_score, geo_diag = _score_geo(cfg.base_url, cfg.timeout_sec)
    conversion_score, conversion_diag = _fetch_conversion_metrics(cfg)
    content_score, content_diag = _fetch_content_quality(cfg)

    seo_score = _safe_float(surface_scores.get("seo_score"), 0.0)
    reliability_score = _safe_float(surface_scores.get("reliability_score"), 0.0)

    total_score = round(
        (seo_score * 0.35)
        + (geo_score * 0.25)
        + (conversion_score * 0.25)
        + (content_score * 0.10)
        + (reliability_score * 0.05),
        2,
    )
    return {
        "ts_utc": utc_now_iso(),
        "base_url": cfg.base_url,
        "weights": {
            "seo": 0.35,
            "geo": 0.25,
            "conversion": 0.25,
            "content_quality": 0.10,
            "reliability": 0.05,
        },
        "score": {
            "seo": round(seo_score, 2),
            "geo": round(geo_score, 2),
            "conversion": round(conversion_score, 2),
            "content_quality": round(content_score, 2),
            "reliability": round(reliability_score, 2),
            "total": total_score,
        },
        "thresholds": {
            "min_total": cfg.min_total,
            "min_conversion": cfg.min_conversion,
            "min_reliability": cfg.min_reliability,
            "max_drawdown_pct": cfg.max_drawdown_pct,
        },
        "diagnostics": {
            "surface": surface_diag,
            "geo": geo_diag,
            "conversion": conversion_diag,
            "content_quality": content_diag,
        },
    }


def apply_iteration(cfg: AgentConfig, scoreboard: dict[str, Any]) -> dict[str, Any]:
    history = _read_history(limit=120)
    score = scoreboard.get("score", {}) if isinstance(scoreboard.get("score"), dict) else {}
    total = _safe_float(score.get("total"), 0.0)
    conversion = _safe_float(score.get("conversion"), 0.0)
    reliability = _safe_float(score.get("reliability"), 0.0)
    seo = _safe_float(score.get("seo"), 0.0)
    geo = _safe_float(score.get("geo"), 0.0)
    active_variant_id = _read_active_variant_id()

    recent = history[-max(1, cfg.lookback_days) :]
    med_total = _median([_safe_float((row.get("score") or {}).get("total"), 0.0) for row in recent if isinstance(row, dict)])
    med_conversion = _median(
        [_safe_float((row.get("score") or {}).get("conversion"), 0.0) for row in recent if isinstance(row, dict)]
    )
    drawdown_total_pct = 0.0 if med_total <= 0 else max(0.0, (med_total - total) / med_total * 100.0)
    drawdown_conversion_pct = (
        0.0 if med_conversion <= 0 else max(0.0, (med_conversion - conversion) / med_conversion * 100.0)
    )

    hard_pass = total >= cfg.min_total and conversion >= cfg.min_conversion and reliability >= cfg.min_reliability
    rollback_recommended = (
        drawdown_total_pct >= cfg.max_drawdown_pct
        or drawdown_conversion_pct >= cfg.max_drawdown_pct
        or not hard_pass
    )

    action = "observe_only" if cfg.mode == "observe" else "hold"
    action_reason = "mode_observe"
    stable_restored = False
    variant_changed = False

    if cfg.mode == "iterate":
        if rollback_recommended and STABLE_OVERRIDES_PATH.exists():
            stable_payload = _read_json(STABLE_OVERRIDES_PATH, {})
            if isinstance(stable_payload, dict) and stable_payload.get("variant_id"):
                _write_json(OVERRIDES_PATH, stable_payload)
                stable_restored = True
                action = "rollback_to_stable"
                action_reason = "guardrail_triggered"
                _append_jsonl(
                    ROLLBACK_PATH,
                    {
                        "ts_utc": utc_now_iso(),
                        "reason": "guardrail_triggered",
                        "drawdown_total_pct": round(drawdown_total_pct, 2),
                        "drawdown_conversion_pct": round(drawdown_conversion_pct, 2),
                        "restored_variant_id": str(stable_payload.get("variant_id")),
                    },
                )
        elif rollback_recommended:
            action = "guardrail_block_no_stable"
            action_reason = "guardrail_triggered_no_stable"
        else:
            next_variant_id = _choose_next_variant(active_variant_id, seo, geo, conversion)
            if next_variant_id != active_variant_id:
                _write_variant(next_variant_id, "score_policy_rotation")
                variant_changed = True
                action = "rotate_variant"
                action_reason = f"{active_variant_id}_to_{next_variant_id}"
                active_variant_id = next_variant_id
            else:
                action = "keep_variant"
                action_reason = "score_stable"

            if hard_pass:
                current_payload = _read_json(OVERRIDES_PATH, {})
                if isinstance(current_payload, dict):
                    stable_payload = {
                        **current_payload,
                        "meta": {
                            **(current_payload.get("meta") if isinstance(current_payload.get("meta"), dict) else {}),
                            "saved_as_stable_at": utc_now_iso(),
                            "stable_score_total": total,
                        },
                    }
                    _write_json(STABLE_OVERRIDES_PATH, stable_payload)

    guardrail = {
        "pass": bool(hard_pass),
        "rollback_recommended": bool(rollback_recommended),
        "drawdown_total_pct": round(drawdown_total_pct, 2),
        "drawdown_conversion_pct": round(drawdown_conversion_pct, 2),
        "recent_median_total": round(med_total, 2),
        "recent_median_conversion": round(med_conversion, 2),
    }
    scoreboard["guardrail"] = guardrail
    scoreboard["active_variant_id"] = active_variant_id

    action_payload = {
        "ts_utc": utc_now_iso(),
        "mode": cfg.mode,
        "action": action,
        "reason": action_reason,
        "active_variant_id": active_variant_id,
        "variant_changed": variant_changed,
        "stable_restored": stable_restored,
        "score_total": total,
        "score_conversion": conversion,
        "score_reliability": reliability,
        "guardrail": guardrail,
    }
    return action_payload


def main() -> int:
    cfg = parse_args()
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if not OVERRIDES_PATH.exists():
        _write_variant("control_v1", "bootstrap")

    scoreboard = build_scoreboard(cfg)
    action_payload = apply_iteration(cfg, scoreboard)

    _write_json(SCOREBOARD_PATH, scoreboard)
    _append_jsonl(ACTIONS_PATH, action_payload)
    _append_jsonl(HISTORY_PATH, scoreboard)

    log_event(
        "GROWTH_AGENT_DONE",
        mode=cfg.mode,
        action=action_payload.get("action"),
        total=(scoreboard.get("score") or {}).get("total"),
        conversion=(scoreboard.get("score") or {}).get("conversion"),
        reliability=(scoreboard.get("score") or {}).get("reliability"),
        variant=action_payload.get("active_variant_id"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
