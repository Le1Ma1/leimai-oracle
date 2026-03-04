from __future__ import annotations

import argparse
import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import psycopg
from dotenv import load_dotenv


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_event(event: str, **kwargs: object) -> None:
    print(json.dumps({"ts_utc": utc_now_iso(), "event": event, **kwargs}, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply SQL file via SUPABASE_DB_URL.")
    parser.add_argument("--sql-file", required=True, help="Path to SQL file")
    parser.add_argument("--dry-run", action="store_true", help="Validate config and SQL readability only")
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()
    sql_path = Path(args.sql_file).resolve()
    if not sql_path.exists():
        log_event("APPLY_SQL_FAILED", reason="sql_file_not_found", sql_file=str(sql_path))
        return 1

    sql_text = sql_path.read_text(encoding="utf-8")
    db_url = str(os.getenv("SUPABASE_DB_URL", "")).strip()
    if not db_url:
        log_event("APPLY_SQL_FAILED", reason="missing_SUPABASE_DB_URL")
        return 1
    db_url = normalize_db_url(db_url)
    try:
        conn_kwargs = to_conn_kwargs(db_url)
    except Exception as exc:  # noqa: BLE001
        log_event("APPLY_SQL_FAILED", reason="invalid_SUPABASE_DB_URL", error=str(exc))
        return 1

    if args.dry_run:
        log_event("APPLY_SQL_DRY_RUN_OK", sql_file=str(sql_path), bytes=len(sql_text))
        return 0

    try:
        with connect_with_fallback(conn_kwargs) as conn:
            with conn.cursor() as cur:
                cur.execute(sql_text)
            conn.commit()
        log_event("APPLY_SQL_OK", sql_file=str(sql_path), bytes=len(sql_text))
        return 0
    except Exception as exc:  # noqa: BLE001
        log_event("APPLY_SQL_FAILED", reason="execution_error", error=str(exc))
        return 1


def normalize_db_url(raw: str) -> str:
    text = str(raw or "").strip()
    marker = "://"
    if marker not in text:
        return text

    scheme, rest = text.split(marker, 1)
    if "@" not in rest:
        return text

    userinfo, tail = rest.rsplit("@", 1)
    if ":" not in userinfo:
        return text
    user, password = userinfo.split(":", 1)
    if not password:
        return text
    if password.startswith("[") and password.endswith("]") and len(password) >= 2:
        password = password[1:-1]

    encoded_password = quote(password, safe="")
    return f"{scheme}{marker}{user}:{encoded_password}@{tail}"


def to_conn_kwargs(raw: str) -> dict[str, object]:
    text = str(raw or "").strip()
    parsed = urlsplit(text)
    host = parsed.hostname or ""
    if not host:
        raise ValueError("SUPABASE_DB_URL missing host")
    try:
        ipv4 = socket.gethostbyname(host)
    except Exception as exc:
        raise ValueError(f"unable to resolve host '{host}'") from exc

    port = parsed.port or 5432
    user = parsed.username or ""
    password = unquote(parsed.password or "")
    dbname = (parsed.path or "/postgres").lstrip("/") or "postgres"
    return {
        "host": host,
        "hostaddr": ipv4,
        "port": port,
        "user": user,
        "password": password,
        "dbname": dbname,
        "sslmode": "require",
        "connect_timeout": 12,
    }


def connect_with_fallback(conn_kwargs: dict[str, object]):
    ref = ""
    supabase_url = str(os.getenv("SUPABASE_URL", "")).strip()
    if supabase_url:
        try:
            ref_host = urlsplit(supabase_url).hostname or ""
            ref = ref_host.split(".")[0]
        except Exception:
            ref = ""

    primary_user = str(conn_kwargs.get("user") or "").strip() or "postgres"
    candidates = [primary_user]
    if ref:
        candidates.append(f"postgres.{ref}")
    candidates.append("postgres")
    deduped = []
    for item in candidates:
        if item not in deduped:
            deduped.append(item)

    last_exc: Exception | None = None
    for user in deduped:
        trial = dict(conn_kwargs)
        trial["user"] = user
        try:
            conn = psycopg.connect(**trial)
            log_event("APPLY_SQL_CONNECT_OK", user=user)
            return conn
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log_event("APPLY_SQL_CONNECT_RETRY", user=user, error=str(exc).split("\n")[0])
            continue

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("unable_to_connect")


if __name__ == "__main__":
    raise SystemExit(main())
