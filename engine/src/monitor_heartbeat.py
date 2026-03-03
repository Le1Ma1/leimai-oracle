from __future__ import annotations

import hashlib
import json
import os
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


@dataclass(frozen=True)
class HeartbeatConfig:
    supabase_url: str
    supabase_service_role_key: str
    max_age_hours: float
    event_type: str
    github_token: str
    github_owner: str
    github_repo: str
    dispatch_workflow: str
    dispatch_ref: str
    dispatch_enabled: bool
    timeout_sec: float
    retries: int


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_bool(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    val = str(raw).strip().lower()
    if val in {"1", "true", "yes", "y", "on"}:
        return True
    if val in {"0", "false", "no", "n", "off"}:
        return False
    return default


def parse_float(raw: Any, default: float) -> float:
    try:
        out = float(raw)
    except (TypeError, ValueError):
        return default
    return out if out == out else default


def parse_int(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def log_event(event: str, **kwargs: Any) -> None:
    payload = {"ts_utc": iso_utc(utc_now()), "event": event, **kwargs}
    print(json.dumps(payload, ensure_ascii=False))


def load_config() -> HeartbeatConfig:
    load_dotenv()
    return HeartbeatConfig(
        supabase_url=str(os.getenv("SUPABASE_URL", "")).strip(),
        supabase_service_role_key=str(os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip(),
        max_age_hours=max(0.1, parse_float(os.getenv("HEARTBEAT_MAX_AGE_HOURS"), 5.0)),
        event_type=str(os.getenv("HEARTBEAT_EVENT_TYPE", "oracle_report_pipeline_stale")).strip() or "oracle_report_pipeline_stale",
        github_token=str(os.getenv("GITHUB_TOKEN", "")).strip(),
        github_owner=str(os.getenv("GITHUB_OWNER", "Le1Ma1")).strip() or "Le1Ma1",
        github_repo=str(os.getenv("GITHUB_REPO", "leimai-oracle")).strip() or "leimai-oracle",
        dispatch_workflow=str(os.getenv("HEARTBEAT_DISPATCH_WORKFLOW", "ingest_4h.yml")).strip() or "ingest_4h.yml",
        dispatch_ref=str(os.getenv("HEARTBEAT_DISPATCH_REF", "main")).strip() or "main",
        dispatch_enabled=parse_bool(os.getenv("HEARTBEAT_ENABLE_DISPATCH"), True),
        timeout_sec=max(3.0, parse_float(os.getenv("HEARTBEAT_HTTP_TIMEOUT_SEC"), 12.0)),
        retries=max(1, parse_int(os.getenv("HEARTBEAT_HTTP_RETRIES"), 3)),
    )


def init_supabase(cfg: HeartbeatConfig) -> Client | None:
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


def parse_utc_ts(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def fetch_latest_report_ts(client: Client) -> datetime | None:
    try:
        response = (
            client.table("oracle_reports")
            .select("updated_at,created_at,report_id")
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        log_event("HEARTBEAT_REPORT_QUERY_FAILED", error=str(exc))
        return None
    rows = response.data if isinstance(response.data, list) else []
    if not rows:
        return None
    row = rows[0] if isinstance(rows[0], dict) else {}
    ts = parse_utc_ts(row.get("updated_at")) or parse_utc_ts(row.get("created_at"))
    return ts


def build_event_id(event_type: str, now_dt: datetime) -> str:
    bucket = now_dt.astimezone(timezone.utc).strftime("%Y%m%d%H")
    raw = f"{event_type}|{bucket}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def upsert_critical_event(
    client: Client,
    cfg: HeartbeatConfig,
    *,
    lag_hours: float | None,
    latest_report_ts: datetime | None,
    note: str | None,
) -> bool:
    now_dt = utc_now()
    event_id = build_event_id(cfg.event_type, now_dt)
    payload = {
        "latest_report_ts_utc": iso_utc(latest_report_ts) if latest_report_ts else None,
        "lag_hours": None if lag_hours is None else round(lag_hours, 6),
        "threshold_hours": cfg.max_age_hours,
        "note": note or "",
    }
    row = {
        "event_id": event_id,
        "ts_utc": iso_utc(now_dt),
        "event_type": cfg.event_type,
        "severity": "critical",
        "payload": payload,
        "status": "new",
    }
    try:
        client.table("anomaly_events").upsert([row], on_conflict="event_id").execute()
        log_event("HEARTBEAT_CRITICAL_EVENT_UPSERTED", event_id=event_id, payload=payload)
        return True
    except Exception as exc:  # noqa: BLE001
        log_event("HEARTBEAT_CRITICAL_EVENT_FAILED", event_id=event_id, error=str(exc))
        return False


def request_with_retry(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any] | None,
    timeout_sec: float,
    retries: int,
) -> tuple[bool, int | None, str | None]:
    session = requests.Session()
    last_error: str | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.request(method=method, url=url, headers=headers, json=json_body, timeout=(5.0, timeout_sec))
            status = resp.status_code
            if status in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(min(8.0, 2 ** (attempt - 1)))
                continue
            if 200 <= status < 300:
                return True, status, None
            last_error = f"http_{status}:{resp.text[:300]}"
            return False, status, last_error
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt < retries:
                time.sleep(min(8.0, 2 ** (attempt - 1)))
    return False, None, last_error or "request_failed"


def dispatch_recovery_workflow(cfg: HeartbeatConfig, *, lag_hours: float | None, latest_report_ts: datetime | None) -> bool:
    if not cfg.dispatch_enabled:
        log_event("HEARTBEAT_DISPATCH_SKIPPED", reason="disabled")
        return False
    if not cfg.github_token:
        log_event("HEARTBEAT_DISPATCH_SKIPPED", reason="missing_github_token")
        return False

    url = f"https://api.github.com/repos/{cfg.github_owner}/{cfg.github_repo}/actions/workflows/{cfg.dispatch_workflow}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {cfg.github_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = {
        "ref": cfg.dispatch_ref,
        "inputs": {
            "reason": "heartbeat_recovery",
            "detected_lag_hours": "unknown" if lag_hours is None else f"{lag_hours:.6f}",
            "latest_report_ts_utc": iso_utc(latest_report_ts) if latest_report_ts else "missing",
        },
    }
    ok, status, error = request_with_retry(
        "POST",
        url,
        headers=headers,
        json_body=body,
        timeout_sec=cfg.timeout_sec,
        retries=cfg.retries,
    )
    if ok:
        log_event("HEARTBEAT_DISPATCH_TRIGGERED", workflow=cfg.dispatch_workflow, ref=cfg.dispatch_ref)
        return True
    log_event("HEARTBEAT_DISPATCH_FAILED", workflow=cfg.dispatch_workflow, status=status, error=error)
    return False


def run_monitor() -> int:
    cfg = load_config()
    log_event(
        "HEARTBEAT_START",
        max_age_hours=cfg.max_age_hours,
        dispatch_enabled=cfg.dispatch_enabled,
        workflow=cfg.dispatch_workflow,
    )
    client = init_supabase(cfg)
    if client is None:
        log_event("HEARTBEAT_STOPPED", reason="supabase_client_unavailable")
        return 0

    latest_ts = fetch_latest_report_ts(client)
    now_dt = utc_now()
    if latest_ts is None:
        log_event("HEARTBEAT_STALE", reason="no_reports_found")
        upsert_critical_event(client, cfg, lag_hours=None, latest_report_ts=None, note="no_reports_found")
        dispatch_recovery_workflow(cfg, lag_hours=None, latest_report_ts=None)
        return 0

    lag_hours = max(0.0, (now_dt - latest_ts).total_seconds() / 3600.0)
    if lag_hours <= cfg.max_age_hours:
        log_event("HEARTBEAT_OK", latest_report_ts_utc=iso_utc(latest_ts), lag_hours=round(lag_hours, 6))
        return 0

    log_event(
        "HEARTBEAT_STALE",
        latest_report_ts_utc=iso_utc(latest_ts),
        lag_hours=round(lag_hours, 6),
        threshold_hours=cfg.max_age_hours,
    )
    upsert_critical_event(client, cfg, lag_hours=lag_hours, latest_report_ts=latest_ts, note="stale_report_feed")
    dispatch_recovery_workflow(cfg, lag_hours=lag_hours, latest_report_ts=latest_ts)
    return 0


def main() -> int:
    try:
        return run_monitor()
    except Exception as exc:  # noqa: BLE001
        log_event("HEARTBEAT_FATAL", error=str(exc))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
