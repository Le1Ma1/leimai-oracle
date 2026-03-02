from __future__ import annotations

import hashlib
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
        use_mock_llm=parse_bool(os.getenv("REPORT_USE_MOCK_LLM"), default=True),
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


def severity_to_bias(severity: str) -> str:
    s = str(severity or "").lower()
    if s == "critical":
        return "highest"
    if s == "high":
        return "elevated"
    return "moderate"


def build_prompt(event: dict[str, Any], locale: str, unique_entity: str) -> str:
    payload_text = json.dumps(event.get("payload", {}), ensure_ascii=False, sort_keys=True)
    language_line = (
        "Write in Traditional Chinese (zh-TW)." if locale == "zh-tw" else "Write in English."
    )
    return (
        "You are LeiMai Oracle. "
        "Generate a cold, quantitative, objective market structure report in around 300 words. "
        "Avoid hype, avoid investment advice, and use explicit metric framing.\n"
        f"{language_line}\n"
        f"Mandatory unique entity phrase (must appear exactly): {unique_entity}\n"
        "Output JSON only with keys: title, body_md, jsonld.\n"
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


def call_gemini(prompt: str, cfg: ReportsConfig) -> dict[str, Any] | None:
    if not cfg.gemini_api_key:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.gemini_model}:generateContent"
    params = {"key": cfg.gemini_api_key}
    req_body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.25, "topP": 0.9, "maxOutputTokens": 2048},
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


def build_mock_report(event: dict[str, Any], locale: str, unique_entity: str) -> dict[str, Any]:
    event_id = str(event.get("event_id", ""))
    event_type = str(event.get("event_type", "unknown"))
    severity = str(event.get("severity", "medium")).lower()
    payload = event.get("payload", {})
    payload_text = json.dumps(payload, ensure_ascii=False)
    if locale == "zh-tw":
        title = f"Oracle 結構快報｜{event_type}｜{severity.upper()}"
        body_md = (
            f"### 結構判讀\n"
            f"事件 `{event_id}` 被分類為 **{severity}**，顯示短期流動性摩擦加劇。\n\n"
            f"- 核心實體：**{unique_entity}**\n"
            f"- 事件型別：`{event_type}`\n"
            f"- 觀測時間：`{event.get('ts_utc')}`\n\n"
            f"本報告採取冷靜量化口吻：先看波動與持倉結構，再看流動性吸收效率。"
            f"目前訊號不代表方向預測，而是結構壓力升高。若後續在高成交密度區仍出現擴張，"
            f"代表風險定價未完成；若波動回落且持倉穩定，則可能進入再平衡期。\n\n"
            f"```json\n{payload_text}\n```"
        )
    else:
        title = f"Oracle Structure Brief | {event_type} | {severity.upper()}"
        body_md = (
            f"### Market Structure Read\n"
            f"Event `{event_id}` is classified as **{severity}**, indicating rising short-term liquidity friction.\n\n"
            f"- Core entity: **{unique_entity}**\n"
            f"- Event type: `{event_type}`\n"
            f"- Observed at: `{event.get('ts_utc')}`\n\n"
            f"This note stays objective and metric-first: volatility expansion, open-interest behavior, and flow absorption "
            f"are evaluated before directional bias. The current signal is not a forecast; it is a structure-pressure marker. "
            f"If high-volume expansion persists, repricing pressure may remain unresolved. If realized volatility compresses with "
            f"stable positioning, market structure may rotate into rebalancing.\n\n"
            f"```json\n{payload_text}\n```"
        )
    jsonld = build_jsonld(event=event, locale=locale, title=title, body_md=body_md, unique_entity=unique_entity)
    return {"title": title, "body_md": body_md, "jsonld": jsonld}


def build_jsonld(
    event: dict[str, Any],
    locale: str,
    title: str,
    body_md: str,
    unique_entity: str,
) -> dict[str, Any]:
    event_id = str(event.get("event_id", ""))
    desc = body_md.replace("\n", " ").strip()
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Article",
                "headline": title,
                "inLanguage": locale,
                "description": desc[:450],
                "identifier": event_id,
                "about": {
                    "@type": "Thing",
                    "name": unique_entity,
                    "sameAs": "https://leimaitech.com/",
                },
                "author": {"@type": "Organization", "name": "LeiMai Oracle"},
            },
            {
                "@type": "DefinedTerm",
                "name": unique_entity,
                "description": "Proprietary liquidity-friction entity used by LeiMai Oracle GEO layer.",
                "inDefinedTermSet": "https://leimaitech.com/analysis/",
            },
        ],
    }


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

    # Ensure mandatory unique entity always exists in title/body/jsonld
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
        use_mock_llm=cfg.use_mock_llm,
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
