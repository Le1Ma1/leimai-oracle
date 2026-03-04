from __future__ import annotations

import html
import json
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from dotenv import load_dotenv

try:
    from .features import calc_v1_hard_metrics
except Exception:  # noqa: BLE001
    from engine.src.features import calc_v1_hard_metrics

try:
    from supabase import Client, create_client
except Exception:  # noqa: BLE001
    Client = Any  # type: ignore[assignment]
    create_client = None


UNIQUE_ENTITY_DEFAULT = "LeiMai Liquidity Friction"
LOCALES: tuple[str, ...] = ("en", "zh-tw")
FORBIDDEN_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b[a-f0-9]{24,}\b", re.IGNORECASE),
    re.compile(r"/analysis/[a-z0-9_-]+", re.IGNORECASE),
    re.compile(r"\b(?:event[_\s-]?id|uuid|hash)\b", re.IGNORECASE),
    re.compile(r"\b(?:payload|權限策略|參考識別|authority record)\b", re.IGNORECASE),
    re.compile(r"\bConclusion Event\b", re.IGNORECASE),
)
ZH_ALLOWED_TERMS: tuple[str, ...] = (
    UNIQUE_ENTITY_DEFAULT,
    "USDT",
    "BTC",
    "ETH",
    "SOL",
    "XRP",
    "BNB",
    "ADA",
    "TRX",
    "LTC",
    "RSI",
    "MACD",
)


@dataclass(frozen=True)
class ReportsConfig:
    supabase_url: str
    supabase_service_role_key: str
    gemini_api_key: str
    gemini_model: str
    unique_entity: str
    per_event_locales: tuple[str, ...]
    http_timeout_sec: float
    retries: int
    use_mock_llm: bool


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_event(event: str, **kwargs: Any) -> None:
    payload = {"ts_utc": iso_utc(utc_now()), "event": event, **kwargs}
    print(json.dumps(payload, ensure_ascii=False))


def parse_float(raw: Any, default: float) -> float:
    try:
        out = float(raw)
    except (TypeError, ValueError):
        return default
    if out != out:
        return default
    return out


def parse_int(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def parse_bool(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return default


def parse_locales(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return LOCALES
    parsed = tuple(token.strip().lower() for token in str(raw).split(",") if token.strip())
    if not parsed:
        return LOCALES
    supported = tuple(locale for locale in parsed if locale in LOCALES)
    return supported or LOCALES


def load_config() -> ReportsConfig:
    load_dotenv()
    return ReportsConfig(
        supabase_url=str(os.getenv("SUPABASE_URL", "")).strip(),
        supabase_service_role_key=str(os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip(),
        gemini_api_key=str(os.getenv("GEMINI_API_KEY", "")).strip(),
        gemini_model=str(os.getenv("GEMINI_MODEL", "gemini-1.5-flash")).strip(),
        unique_entity=str(os.getenv("ORACLE_UNIQUE_ENTITY", UNIQUE_ENTITY_DEFAULT)).strip() or UNIQUE_ENTITY_DEFAULT,
        per_event_locales=parse_locales(os.getenv("REPORT_LOCALES")),
        http_timeout_sec=max(3.0, parse_float(os.getenv("REPORT_HTTP_TIMEOUT_SEC"), 20.0)),
        retries=max(1, parse_int(os.getenv("REPORT_HTTP_RETRIES"), 3)),
        use_mock_llm=parse_bool(os.getenv("REPORT_USE_MOCK_LLM"), default=False),
    )


def init_supabase(cfg: ReportsConfig) -> Client | None:
    if create_client is None:
        log_event("SUPABASE_SDK_MISSING", package="supabase")
        return None
    if not cfg.supabase_url or not cfg.supabase_service_role_key:
        log_event(
            "SUPABASE_CONFIG_MISSING",
            has_url=bool(cfg.supabase_url),
            has_service_role_key=bool(cfg.supabase_service_role_key),
        )
        return None
    try:
        return create_client(cfg.supabase_url, cfg.supabase_service_role_key)
    except Exception as exc:  # noqa: BLE001
        log_event("SUPABASE_INIT_FAILED", error=str(exc))
        return None


def fetch_new_events(client: Client, limit: int = 20) -> list[dict[str, Any]]:
    try:
        response = (
            client.table("anomaly_events")
            .select("event_id, ts_utc, event_type, severity, payload, status")
            .eq("status", "new")
            .neq("severity", "low")
            .order("ts_utc", desc=False)
            .limit(limit)
            .execute()
        )
        rows = response.data if isinstance(response.data, list) else []
        return [row for row in rows if isinstance(row, dict) and row.get("event_id")]
    except Exception as exc:  # noqa: BLE001
        log_event("FETCH_EVENTS_FAILED", error=str(exc))
        return []


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered)
    return cleaned.strip("-")[:120] or "report"


def build_slug(event_id: str, locale: str) -> str:
    short = re.sub(r"[^a-z0-9]", "", event_id.lower())[:12]
    return slugify(f"oracle-{locale}-{short}")


def humanize_event_type(event_type: str, locale: str) -> str:
    raw = str(event_type or "").strip().lower()
    en_map = {
        "liquidation_spike": "Forced Liquidation Shock",
        "open_interest_crash": "Open Interest Compression",
        "open_interest_spike": "Open Interest Expansion",
        "oracle_report_pipeline_stale": "Signal Freshness Deviation",
        "oracle_report_generation_error": "Signal Synthesis Deviation",
    }
    zh_map = {
        "liquidation_spike": "強制平倉衝擊",
        "open_interest_crash": "未平倉量壓縮",
        "open_interest_spike": "未平倉量擴張",
        "oracle_report_pipeline_stale": "訊號新鮮度偏移",
        "oracle_report_generation_error": "訊號合成偏移",
    }
    if locale == "zh-tw":
        return zh_map.get(raw, "主權市場結構事件")
    return en_map.get(raw, "Sovereign Market Structure Event")


def _clamp(value: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, value)))


def build_metric_context(event: dict[str, Any], unique_entity: str) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = event.get("payload")
    event_type = str(event.get("event_type", ""))
    severity = str(event.get("severity", "medium")).lower()
    v1 = calc_v1_hard_metrics(payload if isinstance(payload, dict) else {}, event_type=event_type, severity=severity)
    vol_z = float(v1.get("vol_z_score", 0.0))
    k_delta = float(v1.get("k_line_delta", 0.0))
    oi_stress = float(v1.get("oi_stress_score", 0.0))
    bias = float(v1.get("sovereign_bias_mapped", 0.0))

    orderflow_proxy = _clamp((oi_stress * 28.0) + abs(k_delta) * 2.4 + vol_z * 8.5, 0.0, 100.0)
    depth_imbalance_proxy = _clamp(50.0 + math.tanh((k_delta * 0.75) + (oi_stress * 0.55)) * 34.0, 0.0, 100.0)
    regime_pressure = _clamp((vol_z * 18.0) + (oi_stress * 14.0), 0.0, 100.0)

    confidence_score = _clamp((bias * 0.56) + (regime_pressure * 0.28) + (orderflow_proxy * 0.16), 5.0, 99.0)
    if confidence_score >= 74.0:
        structural_verdict = "structural_stress_expansion"
        alpha_posture = "defensive"
    elif confidence_score >= 52.0:
        structural_verdict = "liquidity_friction_persistent"
        alpha_posture = "defensive_to_balanced"
    else:
        structural_verdict = "rebalancing_watch"
        alpha_posture = "balanced"

    evidence_pack = {
        "entity": unique_entity,
        "event_type": event_type,
        "severity": severity,
        "v1": {
            "vol_z_score": round(vol_z, 4),
            "k_line_delta": round(k_delta, 4),
            "open_interest_stress": round(oi_stress, 4),
            "sovereign_bias_mapped": round(bias, 2),
            "pulse_label": str(v1.get("pulse_label", "contained")),
            "range_pct_4h": round(float(v1.get("range_pct_4h", 0.0)), 4),
            "open_interest_drop_pct": round(float(v1.get("open_interest_drop_pct", 0.0)), 4),
        },
        "v2": {
            "orderflow_proxy": round(orderflow_proxy, 2),
            "depth_imbalance_proxy": round(depth_imbalance_proxy, 2),
            "regime_pressure": round(regime_pressure, 2),
            "calibration_state": "calibrating",
        },
        "window_contract": {"micro": "1m", "macro": "4h", "source_mode": "hybrid_v1_v2"},
    }

    verdict_pack = {
        "structural_verdict": structural_verdict,
        "confidence_score": round(confidence_score, 2),
        "alpha_posture": alpha_posture,
        "restriction": "locked_for_unsigned_users",
    }
    return evidence_pack, verdict_pack


def _series_point(i: int, total: int, seed: float, amplitude: float, tilt: float, base: float) -> float:
    phase = (i / max(total - 1, 1)) * math.pi * 2.0
    wave = math.sin(phase + seed) * amplitude
    harmonic = math.sin(phase * 2.4 + seed * 0.7) * (amplitude * 0.34)
    trend = ((i / max(total - 1, 1)) - 0.5) * tilt
    return base + wave + harmonic + trend


def build_snapshot_svg(
    title: str,
    event: dict[str, Any],
    evidence_pack: dict[str, Any],
    verdict_pack: dict[str, Any],
    locale: str,
) -> str:
    v1 = evidence_pack.get("v1", {}) if isinstance(evidence_pack.get("v1"), dict) else {}
    v2 = evidence_pack.get("v2", {}) if isinstance(evidence_pack.get("v2"), dict) else {}
    vol_z = float(v1.get("vol_z_score", 0.0))
    k_delta = float(v1.get("k_line_delta", 0.0))
    bias = float(v1.get("sovereign_bias_mapped", 0.0))
    regime_pressure = float(v2.get("regime_pressure", 0.0))
    confidence = float(verdict_pack.get("confidence_score", 0.0))
    severity = str(event.get("severity", "medium")).upper()

    macro_points: list[str] = []
    micro_points: list[str] = []
    macro_total = 64
    micro_total = 64
    macro_amp = _clamp(14.0 + vol_z * 3.5, 8.0, 42.0)
    micro_amp = _clamp(8.0 + abs(k_delta) * 4.8 + (regime_pressure / 20.0), 6.0, 38.0)
    macro_tilt = _clamp((bias - 50.0) / 2.4, -26.0, 26.0)
    micro_tilt = _clamp((confidence - 50.0) / 3.1, -22.0, 22.0)

    for i in range(macro_total):
        x = 64 + (i * (528 / max(macro_total - 1, 1)))
        y = 206 - _series_point(i, macro_total, seed=vol_z * 0.25 + 1.4, amplitude=macro_amp, tilt=macro_tilt, base=0.0)
        macro_points.append(f"{x:.2f},{y:.2f}")

    for i in range(micro_total):
        x = 640 + (i * (528 / max(micro_total - 1, 1)))
        y = 206 - _series_point(i, micro_total, seed=abs(k_delta) * 0.31 + 2.2, amplitude=micro_amp, tilt=micro_tilt, base=0.0)
        micro_points.append(f"{x:.2f},{y:.2f}")

    label_macro = "宏觀結構 4h" if locale == "zh-tw" else "Macro Structure 4h"
    label_micro = "微觀脈衝 1m" if locale == "zh-tw" else "Micro Pulse 1m"
    label_verdict = "結構裁決" if locale == "zh-tw" else "Structural Verdict"
    label_conf = "信心值" if locale == "zh-tw" else "Confidence"
    observed = str(event.get("ts_utc", ""))

    return (
        "<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='630' viewBox='0 0 1200 630' role='img'>"
        "<defs>"
        "<linearGradient id='bg' x1='0' y1='0' x2='1' y2='1'>"
        "<stop offset='0%' stop-color='#030405'/>"
        "<stop offset='100%' stop-color='#090c10'/>"
        "</linearGradient>"
        "<linearGradient id='gold' x1='0' y1='0' x2='1' y2='0'>"
        "<stop offset='0%' stop-color='#8d6a13'/>"
        "<stop offset='52%' stop-color='#D4AF37'/>"
        "<stop offset='100%' stop-color='#f0da8a'/>"
        "</linearGradient>"
        "</defs>"
        "<rect width='1200' height='630' fill='url(#bg)'/>"
        "<rect x='34' y='34' width='1132' height='562' fill='none' stroke='#D4AF37' stroke-opacity='0.38'/>"
        "<rect x='56' y='84' width='544' height='248' fill='none' stroke='#C0C0C0' stroke-opacity='0.28'/>"
        "<rect x='632' y='84' width='544' height='248' fill='none' stroke='#C0C0C0' stroke-opacity='0.28'/>"
        f"<polyline fill='none' stroke='url(#gold)' stroke-width='2.2' points='{' '.join(macro_points)}'/>"
        f"<polyline fill='none' stroke='url(#gold)' stroke-width='2.2' points='{' '.join(micro_points)}'/>"
        f"<text x='62' y='72' fill='#f2f5f7' font-size='14' font-family='JetBrains Mono, monospace'>{html.escape(label_macro)}</text>"
        f"<text x='638' y='72' fill='#f2f5f7' font-size='14' font-family='JetBrains Mono, monospace'>{html.escape(label_micro)}</text>"
        f"<text x='62' y='390' fill='#D4AF37' font-size='22' font-family='JetBrains Mono, monospace'>{html.escape(title)}</text>"
        f"<text x='62' y='422' fill='#d9e0e8' font-size='13' font-family='JetBrains Mono, monospace'>Vol_Z {vol_z:.2f} | Delta {k_delta:.2f} | Bias {bias:.1f}</text>"
        f"<text x='62' y='446' fill='#d9e0e8' font-size='13' font-family='JetBrains Mono, monospace'>{html.escape(label_conf)} {confidence:.1f} | Severity {html.escape(severity)}</text>"
        f"<text x='62' y='474' fill='#f0da8a' font-size='13' font-family='JetBrains Mono, monospace'>{html.escape(label_verdict)} {html.escape(str(verdict_pack.get('structural_verdict', '')))}</text>"
        f"<text x='62' y='505' fill='#9da9b6' font-size='12' font-family='JetBrains Mono, monospace'>{html.escape(observed)}</text>"
        "<text x='62' y='560' fill='#D4AF37' font-size='12' font-family='JetBrains Mono, monospace'>LeiMai Oracle Snapshot / Hybrid V1+V2</text>"
        "</svg>"
    )


def build_prompt(
    event: dict[str, Any],
    locale: str,
    unique_entity: str,
    evidence_pack: dict[str, Any],
    verdict_pack: dict[str, Any],
) -> str:
    payload_text = json.dumps(event.get("payload", {}), ensure_ascii=False, sort_keys=True)
    context_macro = json.dumps(
        {
            "range_pct_4h": evidence_pack.get("v1", {}).get("range_pct_4h"),
            "open_interest_drop_pct": evidence_pack.get("v1", {}).get("open_interest_drop_pct"),
            "regime_pressure": evidence_pack.get("v2", {}).get("regime_pressure"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    context_micro = json.dumps(
        {
            "vol_z_score": evidence_pack.get("v1", {}).get("vol_z_score"),
            "k_line_delta": evidence_pack.get("v1", {}).get("k_line_delta"),
            "orderflow_proxy": evidence_pack.get("v2", {}).get("orderflow_proxy"),
            "depth_imbalance_proxy": evidence_pack.get("v2", {}).get("depth_imbalance_proxy"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    context_verdict = json.dumps(verdict_pack, ensure_ascii=False, sort_keys=True)
    event_label = humanize_event_type(str(event.get("event_type", "")), locale)
    if locale == "zh-tw":
        style_line = (
            "請使用繁體中文（zh-TW）。語氣需冷靜、精準、具機構紀律，"
            "結構固定為：結論 -> 證據 -> 風險邊界。"
        )
        language_guard = (
            "Language Isolation: 全文必須為繁體中文。除了幣種代號與專有實體名稱外，不可混入英文句子。"
        )
    else:
        style_line = (
            "Write in English with institutional financial tone: cold, precise, evidence-first, "
            "and structured as Conclusion -> Evidence -> Risk Boundary."
        )
        language_guard = "Language Isolation: Output in English only."

    return (
        "You are LeiMai Oracle. Produce a market-structure brief around 300 words.\n"
        f"{style_line}\n"
        f"{language_guard}\n"
        "Do not use hype. Do not provide investment advice.\n"
        "NEVER output internal event IDs, UUIDs, hashes, route paths, or system labels.\n"
        "NEVER output system meta text such as 'Conclusion Event is rated' or any access-policy sentence.\n"
        f"Mandatory entity phrase (exact match): {unique_entity}\n"
        "Return strict JSON only with keys: title, body_md, jsonld.\n"
        f"event_class={event_label}\n"
        f"severity={event.get('severity')}\n"
        f"event_ts_utc={event.get('ts_utc')}\n"
        f"context_macro_4h={context_macro}\n"
        f"context_micro_1m={context_micro}\n"
        f"context_verdict={context_verdict}\n"
        f"payload={payload_text}\n"
    )


def extract_text_from_gemini(data: dict[str, Any]) -> str:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    content = candidates[0].get("content", {})
    parts = content.get("parts", [])
    if not isinstance(parts, list):
        return ""
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks).strip()


def parse_report_json(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        obj = json.loads(text)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    if not isinstance(obj.get("title"), str) or not isinstance(obj.get("body_md"), str):
        return None
    jsonld = obj.get("jsonld")
    if not isinstance(jsonld, dict):
        jsonld = {}
    return {"title": obj["title"].strip(), "body_md": obj["body_md"].strip(), "jsonld": jsonld}


def strip_forbidden_text(text: str) -> str:
    cleaned = str(text or "")
    for pattern in FORBIDDEN_TEXT_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def is_locale_isolated(text: str, locale: str, unique_entity: str) -> bool:
    if locale != "zh-tw":
        return True
    sample = str(text or "")
    allow_terms = {unique_entity, *ZH_ALLOWED_TERMS}
    for token in allow_terms:
        if token:
            sample = sample.replace(token, " ")
    latin_words = re.findall(r"[A-Za-z]{3,}", sample)
    return len(latin_words) == 0


def call_gemini(prompt: str, cfg: ReportsConfig) -> dict[str, Any] | None:
    if not cfg.gemini_api_key:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.gemini_model}:generateContent"
    params = {"key": cfg.gemini_api_key}
    req_body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "topP": 0.9, "maxOutputTokens": 2048},
    }
    last_error: str | None = None
    for attempt in range(1, cfg.retries + 1):
        try:
            response = requests.post(url, params=params, json=req_body, timeout=(5.0, cfg.http_timeout_sec))
            if response.status_code >= 500 or response.status_code == 429:
                last_error = f"http_{response.status_code}"
                if attempt < cfg.retries:
                    time.sleep(min(5.0, 1.0 * attempt))
                    continue
                return None
            if response.status_code >= 400:
                last_error = response.text[:280]
                return None
            payload = response.json()
            raw_text = extract_text_from_gemini(payload)
            if not raw_text:
                last_error = "empty_text"
                return None
            return parse_report_json(raw_text)
        except (requests.RequestException, ValueError) as exc:
            last_error = str(exc)
            if attempt < cfg.retries:
                time.sleep(min(5.0, 1.0 * attempt))
    log_event("GEMINI_CALL_FAILED", error=last_error or "unknown")
    return None


def build_jsonld(
    event: dict[str, Any],
    locale: str,
    title: str,
    body_md: str,
    unique_entity: str,
    snapshot_url: str,
) -> dict[str, Any]:
    event_id = str(event.get("event_id", ""))
    summary = body_md.replace("\n", " ").strip()[:460]
    canonical = f"https://leimai.io/analysis/{build_slug(event_id, locale)}"
    image_url = f"https://leimai.io{snapshot_url}" if snapshot_url.startswith("/") else canonical
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "NewsArticle",
                "headline": title,
                "description": summary,
                "inLanguage": locale,
                "identifier": event_id,
                "mainEntityOfPage": canonical,
                "image": image_url,
                "author": {"@type": "Organization", "name": "LeiMai Oracle"},
                "about": {"@type": "Thing", "name": unique_entity, "sameAs": "https://leimai.io/"},
                "isAccessibleForFree": False,
                "hasPart": [
                    {
                        "@type": "WebPageElement",
                        "isAccessibleForFree": False,
                        "cssSelector": ".paywall-locked-content",
                    }
                ],
            },
            {
                "@type": "Dataset",
                "name": f"{unique_entity} Signal Dataset",
                "description": summary,
                "creator": {"@type": "Organization", "name": "LeiMai Oracle"},
                "url": canonical,
                "image": image_url,
                "isAccessibleForFree": False,
            },
            {
                "@type": "DefinedTerm",
                "name": unique_entity,
                "description": "Proprietary liquidity-friction entity of LeiMai Oracle.",
                "inDefinedTermSet": "https://leimai.io/analysis/",
            },
        ],
    }


def build_mock_report(
    event: dict[str, Any],
    locale: str,
    unique_entity: str,
    evidence_pack: dict[str, Any],
    verdict_pack: dict[str, Any],
    snapshot_url: str,
) -> dict[str, Any]:
    event_type = str(event.get("event_type", "unknown"))
    event_label = humanize_event_type(event_type, locale)
    severity = str(event.get("severity", "medium")).lower()
    observed_at = str(event.get("ts_utc", ""))
    v1 = evidence_pack.get("v1", {}) if isinstance(evidence_pack.get("v1"), dict) else {}
    v2 = evidence_pack.get("v2", {}) if isinstance(evidence_pack.get("v2"), dict) else {}
    vol_z = float(v1.get("vol_z_score", 0.0))
    k_delta = float(v1.get("k_line_delta", 0.0))
    oi_drop = float(v1.get("open_interest_drop_pct", 0.0))
    regime_pressure = float(v2.get("regime_pressure", 0.0))
    orderflow_proxy = float(v2.get("orderflow_proxy", 0.0))
    confidence = float(verdict_pack.get("confidence_score", 0.0))
    verdict_label = str(verdict_pack.get("structural_verdict", "rebalancing_watch"))

    if locale == "zh-tw":
        title = f"主權結構簡報｜{event_label}｜Vol_Z {vol_z:.2f}"
        body_md = (
            "### 市場證據\n"
            f"- 結構分類：{event_label}\n"
            f"- 觀測時間：{observed_at}\n"
            f"- 4h 波動偏離：`{vol_z:.2f}`\n"
            f"- K 線差分強度：`{k_delta:.2f}`\n"
            f"- 未平倉壓力：`{oi_drop:.2f}%`\n"
            f"- 流動性代理壓力：`{orderflow_proxy:.1f}` / 體制壓力：`{regime_pressure:.1f}`\n\n"
            "### 結構裁決\n"
            f"裁決狀態：**{verdict_label}**，信心值 **{confidence:.1f}**。核心實體為 **{unique_entity}**。\n\n"
            "### 風險邊界\n"
            "本報告僅提供結構判讀，不構成投資建議。若量能擴張且波動收斂，市場可能轉入再平衡；若槓桿與波動同向擴大，結構壓力將延續。"
        )
    else:
        title = f"Sovereign Structure Brief | {event_label} | Vol_Z {vol_z:.2f}"
        body_md = (
            "### Market Evidence\n"
            f"- Structure class: {event_label}\n"
            f"- Observed at: {observed_at}\n"
            f"- 4h volatility displacement: `{vol_z:.2f}`\n"
            f"- K-line delta intensity: `{k_delta:.2f}`\n"
            f"- Open-interest stress: `{oi_drop:.2f}%`\n"
            f"- Orderflow proxy: `{orderflow_proxy:.1f}` / regime pressure: `{regime_pressure:.1f}`\n\n"
            "### Structural Verdict\n"
            f"Verdict is **{verdict_label}** with confidence **{confidence:.1f}**. Core entity anchor: **{unique_entity}**.\n\n"
            "### Risk Boundary\n"
            "This brief is a structure assessment, not investment advice. If volume expands while volatility compresses, "
            "conditions may rotate to rebalancing. If leverage and volatility expand together, repricing pressure likely persists."
        )

    jsonld = build_jsonld(
        event=event,
        locale=locale,
        title=title,
        body_md=body_md,
        unique_entity=unique_entity,
        snapshot_url=snapshot_url,
    )
    return {"title": title, "body_md": body_md, "jsonld": jsonld}


def generate_report_for_locale(event: dict[str, Any], locale: str, cfg: ReportsConfig) -> dict[str, Any]:
    slug = build_slug(str(event.get("event_id", "")), locale)
    snapshot_url = f"/analysis/{slug}/snapshot.svg"
    evidence_pack, verdict_pack = build_metric_context(event=event, unique_entity=cfg.unique_entity)
    generated: dict[str, Any] | None = None
    if not cfg.use_mock_llm and cfg.gemini_api_key:
        prompt = build_prompt(
            event=event,
            locale=locale,
            unique_entity=cfg.unique_entity,
            evidence_pack=evidence_pack,
            verdict_pack=verdict_pack,
        )
        for attempt in range(1, cfg.retries + 1):
            candidate = call_gemini(prompt=prompt, cfg=cfg)
            if not candidate:
                continue
            candidate["title"] = strip_forbidden_text(str(candidate.get("title", "")))
            candidate["body_md"] = strip_forbidden_text(str(candidate.get("body_md", "")))
            if not is_locale_isolated(
                f"{candidate['title']}\n{candidate['body_md']}",
                locale=locale,
                unique_entity=cfg.unique_entity,
            ):
                log_event(
                    "REPORT_LANGUAGE_RETRY",
                    locale=locale,
                    event_type=str(event.get("event_type", "")),
                    attempt=attempt,
                )
                continue
            generated = candidate
            generated["jsonld"] = build_jsonld(
                event=event,
                locale=locale,
                title=generated["title"],
                body_md=generated["body_md"],
                unique_entity=cfg.unique_entity,
                snapshot_url=snapshot_url,
            )
            break
    if not generated:
        generated = build_mock_report(
            event=event,
            locale=locale,
            unique_entity=cfg.unique_entity,
            evidence_pack=evidence_pack,
            verdict_pack=verdict_pack,
            snapshot_url=snapshot_url,
        )

    title = strip_forbidden_text(str(generated.get("title", "")))
    body_md = strip_forbidden_text(str(generated.get("body_md", "")))
    if not is_locale_isolated(f"{title}\n{body_md}", locale=locale, unique_entity=cfg.unique_entity):
        generated = build_mock_report(
            event=event,
            locale=locale,
            unique_entity=cfg.unique_entity,
            evidence_pack=evidence_pack,
            verdict_pack=verdict_pack,
            snapshot_url=snapshot_url,
        )
        title = strip_forbidden_text(str(generated.get("title", "")))
        body_md = strip_forbidden_text(str(generated.get("body_md", "")))

    if cfg.unique_entity not in body_md:
        tail = f"核心實體：**{cfg.unique_entity}**" if locale == "zh-tw" else f"Core entity: **{cfg.unique_entity}**"
        body_md = f"{body_md}\n\n{tail}"

    jsonld = generated.get("jsonld")
    if not isinstance(jsonld, dict):
        jsonld = build_jsonld(
            event=event,
            locale=locale,
            title=title,
            body_md=body_md,
            unique_entity=cfg.unique_entity,
            snapshot_url=snapshot_url,
        )

    snapshot_svg = build_snapshot_svg(
        title=title,
        event=event,
        evidence_pack=evidence_pack,
        verdict_pack=verdict_pack,
        locale=locale,
    )

    return {
        "event_id": str(event.get("event_id", "")),
        "locale": locale,
        "title": title,
        "slug": slug,
        "body_md": body_md,
        "jsonld": jsonld,
        "unique_entity": cfg.unique_entity,
        "evidence_pack": evidence_pack,
        "verdict_pack": verdict_pack,
        "snapshot_svg": snapshot_svg,
        "snapshot_url": snapshot_url,
    }


def upsert_reports(client: Client, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    try:
        client.table("oracle_reports").upsert(rows, on_conflict="event_id,locale").execute()
        return len(rows)
    except Exception as exc:  # noqa: BLE001
        log_event("UPSERT_REPORTS_FAILED", rows=len(rows), error=str(exc))
        return 0


def mark_event_processed(client: Client, event_id: str) -> bool:
    try:
        client.table("anomaly_events").update({"status": "processed"}).eq("event_id", event_id).execute()
        return True
    except Exception as exc:  # noqa: BLE001
        log_event("MARK_EVENT_PROCESSED_FAILED", event_id=event_id, error=str(exc))
        return False


def run_generate_reports() -> int:
    cfg = load_config()
    log_event(
        "REPORTS_START",
        model=cfg.gemini_model,
        locales=",".join(cfg.per_event_locales),
        unique_entity=cfg.unique_entity,
    )
    client = init_supabase(cfg)
    if client is None:
        log_event("REPORTS_STOPPED", reason="supabase_client_unavailable")
        return 0

    events = fetch_new_events(client, limit=20)
    if not events:
        log_event("REPORTS_NO_EVENTS")
        return 0

    events_processed = 0
    reports_upserted = 0
    for event in events:
        event_id = str(event.get("event_id", "")).strip()
        if not event_id:
            continue

        rows: list[dict[str, Any]] = []
        for locale in cfg.per_event_locales:
            try:
                row = generate_report_for_locale(event=event, locale=locale, cfg=cfg)
                rows.append(row)
            except Exception as exc:  # noqa: BLE001
                log_event("GENERATE_REPORT_LOCALE_FAILED", event_id=event_id, locale=locale, error=str(exc))

        if len(rows) < len(cfg.per_event_locales):
            log_event("GENERATE_REPORT_INCOMPLETE", event_id=event_id, generated_locales=len(rows))
            continue

        inserted = upsert_reports(client, rows)
        if inserted != len(rows):
            log_event("REPORT_UPSERT_PARTIAL", event_id=event_id, inserted=inserted, expected=len(rows))
            continue

        if mark_event_processed(client, event_id):
            events_processed += 1
            reports_upserted += inserted
            log_event("EVENT_PROCESSED", event_id=event_id, reports=inserted)

    log_event(
        "REPORTS_DONE",
        events_total=len(events),
        events_processed=events_processed,
        reports_upserted=reports_upserted,
    )
    return 0


def main() -> int:
    try:
        return run_generate_reports()
    except Exception as exc:  # noqa: BLE001
        log_event("REPORTS_FATAL", error=str(exc))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
