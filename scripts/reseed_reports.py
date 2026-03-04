from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

try:
    from supabase import Client, create_client
except Exception:  # noqa: BLE001
    Client = Any  # type: ignore[assignment]
    create_client = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_event(event: str, **kwargs: Any) -> None:
    print(json.dumps({"ts_utc": utc_now_iso(), "event": event, **kwargs}, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Archive + reset oracle reports, then reopen anomaly events for regeneration."
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--skip-archive", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def init_client() -> Client | None:
    load_dotenv()
    if create_client is None:
        log_event("SUPABASE_SDK_MISSING")
        return None
    url = str(os.getenv("SUPABASE_URL", "")).strip()
    key = str(os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    if not url or not key:
        log_event("SUPABASE_CONFIG_MISSING", has_url=bool(url), has_service_role_key=bool(key))
        return None
    try:
        return create_client(url, key)
    except Exception as exc:  # noqa: BLE001
        log_event("SUPABASE_INIT_FAILED", error=str(exc))
        return None


def fetch_reports(client: Client, batch_size: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = 0
    while True:
        resp = (
            client.table("oracle_reports")
            .select("report_id,event_id,locale,title,slug,body_md,jsonld,unique_entity,created_at,updated_at")
            .gt("report_id", cursor)
            .order("report_id", desc=False)
            .limit(batch_size)
            .execute()
        )
        data = resp.data if isinstance(resp.data, list) else []
        if not data:
            break
        rows.extend([row for row in data if isinstance(row, dict)])
        cursor = int(data[-1].get("report_id") or cursor)
    return rows


def archive_reports(client: Client, rows: list[dict[str, Any]]) -> tuple[bool, int]:
    if not rows:
        return True, 0
    payload = []
    for row in rows:
        payload.append(
            {
                "report_id": row.get("report_id"),
                "event_id": row.get("event_id"),
                "locale": row.get("locale"),
                "title": row.get("title"),
                "slug": row.get("slug"),
                "body_md": row.get("body_md"),
                "jsonld": row.get("jsonld") if isinstance(row.get("jsonld"), dict) else {},
                "unique_entity": row.get("unique_entity"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            }
        )
    try:
        client.table("oracle_reports_archive").upsert(payload, on_conflict="report_id").execute()
        return True, len(payload)
    except Exception as exc:  # noqa: BLE001
        log_event("ARCHIVE_UPSERT_FAILED", error=str(exc))
        return False, 0


def delete_reports(client: Client) -> int:
    try:
        resp = client.table("oracle_reports").delete().gt("report_id", 0).execute()
    except Exception as exc:  # noqa: BLE001
        log_event("DELETE_REPORTS_FAILED", error=str(exc))
        return 0
    data = resp.data if isinstance(resp.data, list) else []
    return len(data)


def reopen_events(client: Client) -> int:
    try:
        resp = (
            client.table("anomaly_events")
            .update({"status": "new"})
            .in_("status", ["processed", "error"])
            .neq("severity", "low")
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        log_event("REOPEN_EVENTS_FAILED", error=str(exc))
        return 0
    data = resp.data if isinstance(resp.data, list) else []
    return len(data)


def run() -> int:
    args = parse_args()
    client = init_client()
    if client is None:
        return 1

    batch_size = max(50, int(args.batch_size))
    reports = fetch_reports(client, batch_size=batch_size)
    log_event("REPORTS_LOADED", count=len(reports), dry_run=bool(args.dry_run))
    if args.dry_run:
        return 0

    archived = 0
    if not args.skip_archive:
        ok, archived = archive_reports(client, reports)
        if not ok:
            log_event("RESEED_ABORTED", reason="archive_failed")
            return 1

    deleted = delete_reports(client)
    reopened = reopen_events(client)
    log_event(
        "RESEED_DONE",
        archived=archived,
        deleted=deleted,
        reopened_events=reopened,
        skip_archive=bool(args.skip_archive),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

