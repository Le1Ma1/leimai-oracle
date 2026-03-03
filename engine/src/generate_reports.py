from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from dotenv import load_dotenv

try:
    from supabase import Client, create_client
except Exception:  # noqa: BLE001
    Client = Any  # type: ignore[assignment]
    create_client = None


UNIQUE_ENTITY_DEFAULT = "LeiMai Liquidity Friction"
LOCALES: tuple[str, ...] = ("en", "zh-tw")


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


def build_prompt(event: dict[str, Any], locale: str, unique_entity: str) -> str:
    payload_text = json.dumps(event.get("payload", {}), ensure_ascii=False, sort_keys=True)
    if locale == "zh-tw":
        style_line = (
            "請使用繁體中文（zh-TW）。語氣需冷靜、精準、具機構紀律，"
            "結構固定為：結論 -> 證據 -> 風險邊界。"
        )
    else:
        style_line = (
            "Write in English with institutional financial tone: cold, precise, evidence-first, "
            "and structured as Conclusion -> Evidence -> Risk Boundary."
        )

    return (
        "You are LeiMai Oracle. Produce a market-structure brief around 300 words.\n"
        f"{style_line}\n"
        "Do not use hype. Do not provide investment advice.\n"
        f"Mandatory entity phrase (exact match): {unique_entity}\n"
        "Return strict JSON only with keys: title, body_md, jsonld.\n"
        f"event_id={event.get('event_id')}\n"
        f"event_type={event.get('event_type')}\n"
        f"severity={event.get('severity')}\n"
        f"event_ts_utc={event.get('ts_utc')}\n"
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
) -> dict[str, Any]:
    event_id = str(event.get("event_id", ""))
    summary = body_md.replace("\n", " ").strip()[:460]
    canonical = f"https://leimai.io/analysis/{build_slug(event_id, locale)}"
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


def build_mock_report(event: dict[str, Any], locale: str, unique_entity: str) -> dict[str, Any]:
    event_id = str(event.get("event_id", ""))
    event_type = str(event.get("event_type", "unknown"))
    severity = str(event.get("severity", "medium")).lower()
    observed_at = str(event.get("ts_utc", ""))

    if locale == "zh-tw":
        title = f"主權結構簡報｜{event_type}｜{severity.upper()}"
        body_md = (
            "### 結論\n"
            f"事件 `{event_id}` 目前評級為 **{severity}**，市場摩擦仍在累積，主要監測實體為 **{unique_entity}**。\n\n"
            "### 證據\n"
            f"- 事件類型：`{event_type}`\n"
            f"- 觀測時間：`{observed_at}`\n"
            "- 波動壓力尚未與倉位穩定同步，代表短期再定價風險仍在。\n\n"
            "### 風險邊界\n"
            "本報告僅提供結構判讀，不構成投資建議。若量能擴張且波動收斂，市場可能轉入再平衡；"
            "若槓桿與波動同向擴大，結構壓力將持續上升。"
        )
    else:
        title = f"Sovereign Structure Brief | {event_type} | {severity.upper()}"
        body_md = (
            "### Conclusion\n"
            f"Event `{event_id}` is rated **{severity}**, with persistent liquidity friction across the observed structure. "
            f"Primary entity anchor: **{unique_entity}**.\n\n"
            "### Evidence\n"
            f"- Event type: `{event_type}`\n"
            f"- Observed at: `{observed_at}`\n"
            "- Volatility pressure remains elevated relative to positioning stabilization.\n\n"
            "### Risk Boundary\n"
            "This brief is a structure assessment, not investment advice. If volume expands while volatility compresses, "
            "conditions may rotate to rebalancing. If leverage and volatility expand together, repricing pressure likely persists."
        )

    jsonld = build_jsonld(event=event, locale=locale, title=title, body_md=body_md, unique_entity=unique_entity)
    return {"title": title, "body_md": body_md, "jsonld": jsonld}


def generate_report_for_locale(event: dict[str, Any], locale: str, cfg: ReportsConfig) -> dict[str, Any]:
    generated: dict[str, Any] | None = None
    if not cfg.use_mock_llm and cfg.gemini_api_key:
        prompt = build_prompt(event=event, locale=locale, unique_entity=cfg.unique_entity)
        generated = call_gemini(prompt=prompt, cfg=cfg)
        if generated:
            generated["jsonld"] = build_jsonld(
                event=event,
                locale=locale,
                title=generated["title"],
                body_md=generated["body_md"],
                unique_entity=cfg.unique_entity,
            )
    if not generated:
        generated = build_mock_report(event=event, locale=locale, unique_entity=cfg.unique_entity)

    title = str(generated.get("title", "")).strip()
    body_md = str(generated.get("body_md", "")).strip()
    if cfg.unique_entity not in body_md:
        body_md = f"{body_md}\n\nEntity Anchor: **{cfg.unique_entity}**"

    jsonld = generated.get("jsonld")
    if not isinstance(jsonld, dict):
        jsonld = build_jsonld(event=event, locale=locale, title=title, body_md=body_md, unique_entity=cfg.unique_entity)

    slug = build_slug(str(event.get("event_id", "")), locale)
    return {
        "event_id": str(event.get("event_id", "")),
        "locale": locale,
        "title": title,
        "slug": slug,
        "body_md": body_md,
        "jsonld": jsonld,
        "unique_entity": cfg.unique_entity,
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
