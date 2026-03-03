from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from dotenv import load_dotenv


DEFAULT_ZONE_NAME = "leimai.io"
DEFAULT_TARGET = "cname.vercel-dns.com"
DEFAULT_RECORDS = ("@", "www", "support")


@dataclass(frozen=True)
class CloudflareConfig:
    api_token: str
    zone_name: str
    zone_id: str | None
    target: str
    records: tuple[str, ...]
    proxied: bool
    ttl: int
    retries: int
    timeout_sec: float
    dry_run: bool


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_event(event: str, **kwargs: Any) -> None:
    print(json.dumps({"ts_utc": utc_now_iso(), "event": event, **kwargs}, ensure_ascii=False))


def parse_bool(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    val = str(raw).strip().lower()
    if val in {"1", "true", "yes", "y", "on"}:
        return True
    if val in {"0", "false", "no", "n", "off"}:
        return False
    return default


def parse_records(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return DEFAULT_RECORDS
    out = tuple(token.strip().lower() for token in str(raw).split(",") if token.strip())
    return out or DEFAULT_RECORDS


def fqdn(record: str, zone_name: str) -> str:
    r = str(record or "").strip().lower()
    z = str(zone_name or "").strip().lower()
    if not r or r == "@":
        return z
    if r.endswith(f".{z}") or r == z:
        return r
    return f"{r}.{z}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upsert Cloudflare DNS records for Vercel custom domains.")
    parser.add_argument("--zone-name", default=os.getenv("CLOUDFLARE_ZONE_NAME", DEFAULT_ZONE_NAME))
    parser.add_argument("--zone-id", default=os.getenv("CLOUDFLARE_ZONE_ID", ""))
    parser.add_argument("--target", default=os.getenv("CF_TARGET", DEFAULT_TARGET))
    parser.add_argument("--records", default=os.getenv("CF_RECORDS", ",".join(DEFAULT_RECORDS)))
    parser.add_argument("--proxied", default=os.getenv("CF_PROXY", "false"))
    parser.add_argument("--ttl", type=int, default=int(os.getenv("CF_TTL", "1")))
    parser.add_argument("--retry", type=int, default=3)
    parser.add_argument("--timeout-sec", type=float, default=15.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_config(args: argparse.Namespace) -> CloudflareConfig:
    load_dotenv()
    return CloudflareConfig(
        api_token=str(os.getenv("CLOUDFLARE_API_TOKEN", "")).strip(),
        zone_name=str(args.zone_name or DEFAULT_ZONE_NAME).strip().lower(),
        zone_id=str(args.zone_id or "").strip() or None,
        target=str(args.target or DEFAULT_TARGET).strip().lower(),
        records=parse_records(args.records),
        proxied=parse_bool(args.proxied, default=False),
        ttl=max(1, int(args.ttl)),
        retries=max(1, int(args.retry)),
        timeout_sec=max(3.0, float(args.timeout_sec)),
        dry_run=bool(args.dry_run),
    )


def cf_headers(cfg: CloudflareConfig) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {cfg.api_token}",
        "Content-Type": "application/json",
    }


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    cfg: CloudflareConfig,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> tuple[bool, int | None, Any, str | None]:
    last_error: str | None = None
    headers = cf_headers(cfg)
    for attempt in range(1, cfg.retries + 1):
        try:
            resp = session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=(5.0, cfg.timeout_sec),
            )
            status = resp.status_code
            data: Any
            try:
                data = resp.json()
            except ValueError:
                data = resp.text

            if status in {429, 500, 502, 503, 504} and attempt < cfg.retries:
                last_error = f"http_{status}"
                time.sleep(min(8.0, 2 ** (attempt - 1)))
                continue

            if 200 <= status < 300:
                return True, status, data, None

            detail = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)[:500]
            return False, status, data, detail or f"http_{status}"
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt < cfg.retries:
                time.sleep(min(8.0, 2 ** (attempt - 1)))
                continue
    return False, None, None, last_error or "request_failed"


def resolve_zone_id(session: requests.Session, cfg: CloudflareConfig) -> str | None:
    if cfg.zone_id:
        return cfg.zone_id
    url = "https://api.cloudflare.com/client/v4/zones"
    ok, status, data, error = request_with_retry(
        session,
        "GET",
        url,
        cfg=cfg,
        params={"name": cfg.zone_name, "status": "active", "page": 1, "per_page": 5},
    )
    if not ok:
        log_event("CF_ZONE_LOOKUP_FAILED", zone_name=cfg.zone_name, status=status, error=error)
        return None
    rows = data.get("result") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        log_event("CF_ZONE_NOT_FOUND", zone_name=cfg.zone_name)
        return None
    row = rows[0] if isinstance(rows[0], dict) else {}
    zone_id = str(row.get("id", "")).strip()
    if not zone_id:
        log_event("CF_ZONE_ID_MISSING", zone_name=cfg.zone_name)
        return None
    return zone_id


def find_cname_record(session: requests.Session, cfg: CloudflareConfig, zone_id: str, fqdn_name: str) -> dict[str, Any] | None:
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    ok, status, data, error = request_with_retry(
        session,
        "GET",
        url,
        cfg=cfg,
        params={"type": "CNAME", "name": fqdn_name, "page": 1, "per_page": 5},
    )
    if not ok:
        log_event("CF_RECORD_LOOKUP_FAILED", name=fqdn_name, status=status, error=error)
        return None
    rows = data.get("result") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    first = rows[0]
    return first if isinstance(first, dict) else None


def upsert_cname_record(session: requests.Session, cfg: CloudflareConfig, zone_id: str, record_name: str) -> str:
    name = fqdn(record_name, cfg.zone_name)
    existing = find_cname_record(session, cfg, zone_id, name)
    payload = {
        "type": "CNAME",
        "name": name,
        "content": cfg.target,
        "proxied": cfg.proxied,
        "ttl": cfg.ttl,
    }

    if existing is None:
        if cfg.dry_run:
            log_event("CF_DRY_RUN_CREATE", name=name, target=cfg.target)
            return "created"
        url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
        ok, status, _data, error = request_with_retry(session, "POST", url, cfg=cfg, json_body=payload)
        if not ok:
            log_event("CF_CREATE_FAILED", name=name, status=status, error=error)
            return "failed"
        log_event("CF_CREATED", name=name, target=cfg.target)
        return "created"

    existing_content = str(existing.get("content", "")).strip().lower()
    existing_proxied = bool(existing.get("proxied", False))
    existing_ttl = int(existing.get("ttl", 1) or 1)
    if existing_content == cfg.target and existing_proxied == cfg.proxied and existing_ttl == cfg.ttl:
        log_event("CF_UNCHANGED", name=name, target=cfg.target)
        return "unchanged"

    record_id = str(existing.get("id", "")).strip()
    if not record_id:
        log_event("CF_RECORD_ID_MISSING", name=name)
        return "failed"
    if cfg.dry_run:
        log_event("CF_DRY_RUN_UPDATE", name=name, target=cfg.target)
        return "updated"

    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}"
    ok, status, _data, error = request_with_retry(session, "PUT", url, cfg=cfg, json_body=payload)
    if not ok:
        log_event("CF_UPDATE_FAILED", name=name, status=status, error=error)
        return "failed"
    log_event("CF_UPDATED", name=name, target=cfg.target)
    return "updated"


def run() -> int:
    args = parse_args()
    cfg = load_config(args)
    if not cfg.api_token:
        log_event("CF_CONFIG_MISSING", missing="CLOUDFLARE_API_TOKEN")
        return 1

    session = requests.Session()
    zone_id = resolve_zone_id(session, cfg)
    if not zone_id:
        return 1

    stats = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
    for record in cfg.records:
        result = upsert_cname_record(session, cfg, zone_id, record)
        if result in stats:
            stats[result] += 1

    log_event(
        "CF_SYNC_DONE",
        zone_name=cfg.zone_name,
        zone_id=zone_id,
        records=",".join(cfg.records),
        target=cfg.target,
        dry_run=cfg.dry_run,
        **stats,
    )
    return 0 if stats["failed"] == 0 else 2


def main() -> int:
    try:
        return run()
    except Exception as exc:  # noqa: BLE001
        log_event("CF_SYNC_FATAL", error=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

