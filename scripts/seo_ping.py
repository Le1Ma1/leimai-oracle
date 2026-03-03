from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_event(event: str, **kwargs: Any) -> None:
    print(json.dumps({"ts_utc": utc_now_iso(), "event": event, **kwargs}, ensure_ascii=False))


@dataclass(frozen=True)
class SeoPingConfig:
    site_url: str
    sitemap_url: str
    service_account_json: str
    dry_run: bool


def normalize_site_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.endswith("/"):
        text += "/"
    return text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit sitemap to Google Search Console.")
    parser.add_argument("--site-url", default="")
    parser.add_argument("--sitemap-url", default="")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_config(args: argparse.Namespace) -> SeoPingConfig:
    load_dotenv()
    site_url = normalize_site_url(args.site_url or os.getenv("GSC_SITE_URL", ""))
    base_url = str(os.getenv("SUPPORT_BASE_URL", "")).strip().rstrip("/")
    sitemap_url = str(args.sitemap_url or os.getenv("SEO_SITEMAP_URL", "")).strip()
    if not sitemap_url and base_url:
        sitemap_url = f"{base_url}/sitemap.xml"
    service_account_json = str(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")).strip()
    return SeoPingConfig(
        site_url=site_url,
        sitemap_url=sitemap_url,
        service_account_json=service_account_json,
        dry_run=bool(args.dry_run),
    )


def parse_service_account(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        return json.loads(text)
    with open(text, "r", encoding="utf-8") as fp:
        return json.load(fp)


def submit_sitemap(cfg: SeoPingConfig) -> None:
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("missing_google_search_console_dependencies") from exc

    info = parse_service_account(cfg.service_account_json)
    credentials = Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/webmasters"],
    )
    service = build("searchconsole", "v1", credentials=credentials, cache_discovery=False)
    service.sitemaps().submit(siteUrl=cfg.site_url, feedpath=cfg.sitemap_url).execute()


def run() -> int:
    args = parse_args()
    cfg = load_config(args)
    missing: list[str] = []
    if not cfg.site_url:
        missing.append("GSC_SITE_URL")
    if not cfg.sitemap_url:
        missing.append("SUPPORT_BASE_URL or SEO_SITEMAP_URL")
    if not cfg.service_account_json and not cfg.dry_run:
        missing.append("GOOGLE_SERVICE_ACCOUNT_JSON")
    if missing:
        log_event("SEO_SUBMIT_CONFIG_MISSING", missing=",".join(missing))
        return 1

    log_event("SEO_SUBMIT_START", site_url=cfg.site_url, sitemap_url=cfg.sitemap_url, dry_run=cfg.dry_run)
    if cfg.dry_run:
        log_event("SEO_SUBMIT_DRY_RUN_OK", site_url=cfg.site_url, sitemap_url=cfg.sitemap_url)
        return 0

    try:
        submit_sitemap(cfg)
    except Exception as exc:  # noqa: BLE001
        log_event("SEO_SUBMIT_FAILED", error=str(exc))
        return 1

    log_event("SEO_SUBMIT_OK", site_url=cfg.site_url, sitemap_url=cfg.sitemap_url)
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
