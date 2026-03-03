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


DEFAULT_GITHUB_OWNER = "Le1Ma1"
DEFAULT_GITHUB_REPO = "leimai-oracle"
DEFAULT_SUPPORT_PREFIX = "SUPPORT_"
DEFAULT_TARGETS = ("production", "preview", "development")
DEFAULT_PRIMARY_DOMAIN = "leimai.io"
DEFAULT_SUPPORT_DOMAIN = "support.leimai.io"
DEFAULT_WWW_DOMAIN = "www.leimai.io"
DEFAULT_REDIRECT_SOURCES = (
    "leimaitech.com",
    "www.leimaitech.com",
    "support.leimaitech.com",
)


@dataclass(frozen=True)
class SyncConfig:
    github_token: str
    github_owner: str
    github_repo: str
    vercel_token: str
    vercel_project_id: str
    vercel_team_id: str | None
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    support_prefix: str
    targets: tuple[str, ...]
    retries: int
    timeout_sec: float
    trigger_deploy: bool
    deploy_ref: str
    dry_run: bool
    enable_domain_sync: bool
    primary_domain: str
    support_domain: str
    www_domain: str
    redirect_source_domains: tuple[str, ...]
    redirect_status_code: int


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


def parse_targets(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return DEFAULT_TARGETS
    parsed = tuple(token.strip().lower() for token in raw.split(",") if token.strip())
    allowed = tuple(t for t in parsed if t in {"production", "preview", "development"})
    return allowed or DEFAULT_TARGETS


def parse_domain_csv(raw: str | None, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if raw is None:
        return fallback
    out = tuple(token.strip().lower() for token in str(raw).split(",") if token.strip())
    return out or fallback


def normalize_domain(raw: str | None, fallback: str) -> str:
    text = str(raw or fallback).strip().lower()
    if not text:
        return fallback
    if text.startswith("https://"):
        text = text[8:]
    if text.startswith("http://"):
        text = text[7:]
    return text.strip("/") or fallback


def load_config(args: argparse.Namespace) -> SyncConfig:
    load_dotenv()
    trigger_deploy_env = parse_bool(os.getenv("VERCEL_TRIGGER_DEPLOY"), True)
    dry_run = bool(args.dry_run)
    no_deploy = bool(args.no_deploy)
    return SyncConfig(
        github_token=str(os.getenv("GITHUB_TOKEN", "")).strip(),
        github_owner=str(os.getenv("GITHUB_OWNER", DEFAULT_GITHUB_OWNER)).strip() or DEFAULT_GITHUB_OWNER,
        github_repo=str(os.getenv("GITHUB_REPO", DEFAULT_GITHUB_REPO)).strip() or DEFAULT_GITHUB_REPO,
        vercel_token=str(os.getenv("VERCEL_TOKEN", "")).strip(),
        vercel_project_id=str(os.getenv("VERCEL_PROJECT_ID", "")).strip(),
        vercel_team_id=str(os.getenv("VERCEL_TEAM_ID", "")).strip() or None,
        supabase_url=str(os.getenv("SUPABASE_URL", "")).strip(),
        supabase_anon_key=str(os.getenv("SUPABASE_ANON_KEY", "")).strip(),
        supabase_service_role_key=str(os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip(),
        support_prefix=str(args.support_prefix or os.getenv("VERCEL_SUPPORT_PREFIX", DEFAULT_SUPPORT_PREFIX)).strip() or DEFAULT_SUPPORT_PREFIX,
        targets=parse_targets(os.getenv("VERCEL_TARGETS")),
        retries=max(1, int(args.retry)),
        timeout_sec=max(3.0, float(args.timeout_sec)),
        trigger_deploy=(trigger_deploy_env and not no_deploy),
        deploy_ref=str(os.getenv("VERCEL_DEPLOY_REF", "main")).strip() or "main",
        dry_run=dry_run,
        enable_domain_sync=parse_bool(os.getenv("VERCEL_ENABLE_DOMAIN_SYNC"), False),
        primary_domain=normalize_domain(os.getenv("VERCEL_PRIMARY_DOMAIN"), DEFAULT_PRIMARY_DOMAIN),
        support_domain=normalize_domain(os.getenv("VERCEL_SUPPORT_DOMAIN"), DEFAULT_SUPPORT_DOMAIN),
        www_domain=normalize_domain(os.getenv("VERCEL_WWW_DOMAIN"), DEFAULT_WWW_DOMAIN),
        redirect_source_domains=parse_domain_csv(os.getenv("VERCEL_REDIRECT_SOURCE_DOMAINS"), DEFAULT_REDIRECT_SOURCES),
        redirect_status_code=max(301, int(os.getenv("VERCEL_REDIRECT_STATUS", "301"))),
    )


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    retries: int,
    timeout_sec: float,
) -> tuple[bool, int | None, Any, str | None]:
    last_error: str | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=(5.0, timeout_sec),
            )
            status = resp.status_code
            if status in {429, 500, 502, 503, 504}:
                last_error = f"http_{status}"
                if attempt < retries:
                    time.sleep(min(8.0, 2 ** (attempt - 1)))
                    continue
            data: Any
            try:
                data = resp.json()
            except ValueError:
                data = resp.text
            if 200 <= status < 300:
                return True, status, data, None
            detail = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)[:500]
            return False, status, data, detail or f"http_{status}"
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt < retries:
                time.sleep(min(8.0, 2 ** (attempt - 1)))
    return False, None, None, last_error or "request_failed"


def build_github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def build_vercel_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def gh_get_variable_value(
    session: requests.Session,
    cfg: SyncConfig,
    name: str,
    headers: dict[str, str],
) -> str | None:
    url = f"https://api.github.com/repos/{cfg.github_owner}/{cfg.github_repo}/actions/variables/{name}"
    ok, status, data, error = request_with_retry(
        session,
        "GET",
        url,
        headers=headers,
        retries=cfg.retries,
        timeout_sec=cfg.timeout_sec,
    )
    if not ok:
        log_event("GITHUB_VARIABLE_GET_FAILED", name=name, status=status, error=error)
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("value")
    if value is None:
        return None
    return str(value)


def gh_list_support_variables(session: requests.Session, cfg: SyncConfig) -> dict[str, str]:
    headers = build_github_headers(cfg.github_token)
    out: dict[str, str] = {}
    page = 1
    while True:
        url = f"https://api.github.com/repos/{cfg.github_owner}/{cfg.github_repo}/actions/variables"
        ok, status, data, error = request_with_retry(
            session,
            "GET",
            url,
            headers=headers,
            params={"per_page": 100, "page": page},
            retries=cfg.retries,
            timeout_sec=cfg.timeout_sec,
        )
        if not ok:
            log_event("GITHUB_VARIABLE_LIST_FAILED", page=page, status=status, error=error)
            break

        variables = data.get("variables") if isinstance(data, dict) else None
        if not isinstance(variables, list) or not variables:
            break

        for item in variables:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name.startswith(cfg.support_prefix):
                continue
            value_raw = item.get("value")
            value = str(value_raw) if value_raw is not None else gh_get_variable_value(session, cfg, name, headers)
            if value is None:
                log_event("GITHUB_VARIABLE_VALUE_MISSING", name=name)
                continue
            out[name] = value

        if len(variables) < 100:
            break
        page += 1
    return out


def env_list_support_variables(prefix: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in os.environ.items():
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        val = str(value or "").strip()
        if not val:
            continue
        out[key] = val
    return out


def vercel_params(cfg: SyncConfig) -> dict[str, Any]:
    if cfg.vercel_team_id:
        return {"teamId": cfg.vercel_team_id}
    return {}


def vercel_list_envs(session: requests.Session, cfg: SyncConfig, target: str) -> dict[str, dict[str, Any]]:
    headers = build_vercel_headers(cfg.vercel_token)
    url = f"https://api.vercel.com/v10/projects/{cfg.vercel_project_id}/env"
    params = {**vercel_params(cfg), "target": target, "decrypt": "true", "limit": 100}
    ok, status, data, error = request_with_retry(
        session,
        "GET",
        url,
        headers=headers,
        params=params,
        retries=cfg.retries,
        timeout_sec=cfg.timeout_sec,
    )
    if not ok:
        log_event("VERCEL_LIST_ENVS_FAILED", target=target, status=status, error=error)
        return {}
    envs = data.get("envs") if isinstance(data, dict) else None
    if not isinstance(envs, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in envs:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key", "")).strip()
        if not key:
            continue
        out[key] = row
    return out


def vercel_create_env(
    session: requests.Session,
    cfg: SyncConfig,
    *,
    key: str,
    value: str,
    target: str,
) -> bool:
    headers = build_vercel_headers(cfg.vercel_token)
    url = f"https://api.vercel.com/v10/projects/{cfg.vercel_project_id}/env"
    payload = {
        "key": key,
        "value": value,
        "type": "encrypted",
        "target": [target],
    }
    ok, status, _data, error = request_with_retry(
        session,
        "POST",
        url,
        headers=headers,
        params=vercel_params(cfg),
        json_body=payload,
        retries=cfg.retries,
        timeout_sec=cfg.timeout_sec,
    )
    if not ok:
        log_event("VERCEL_CREATE_ENV_FAILED", key=key, target=target, status=status, error=error)
    return ok


def vercel_delete_env(session: requests.Session, cfg: SyncConfig, env_id: str) -> bool:
    headers = build_vercel_headers(cfg.vercel_token)
    url = f"https://api.vercel.com/v10/projects/{cfg.vercel_project_id}/env/{env_id}"
    ok, status, _data, error = request_with_retry(
        session,
        "DELETE",
        url,
        headers=headers,
        params=vercel_params(cfg),
        retries=cfg.retries,
        timeout_sec=cfg.timeout_sec,
    )
    if not ok:
        log_event("VERCEL_DELETE_ENV_FAILED", env_id=env_id, status=status, error=error)
    return ok


def vercel_update_env(
    session: requests.Session,
    cfg: SyncConfig,
    *,
    env_id: str,
    key: str,
    value: str,
    target: str,
) -> bool:
    headers = build_vercel_headers(cfg.vercel_token)
    url = f"https://api.vercel.com/v10/projects/{cfg.vercel_project_id}/env/{env_id}"
    payload = {"value": value, "target": [target], "key": key, "type": "encrypted"}
    ok, status, _data, error = request_with_retry(
        session,
        "PATCH",
        url,
        headers=headers,
        params=vercel_params(cfg),
        json_body=payload,
        retries=cfg.retries,
        timeout_sec=cfg.timeout_sec,
    )
    if ok:
        return True

    log_event("VERCEL_PATCH_ENV_FAILED", key=key, target=target, status=status, error=error)
    deleted = vercel_delete_env(session, cfg, env_id)
    if not deleted:
        return False
    return vercel_create_env(session, cfg, key=key, value=value, target=target)


def sync_target(
    session: requests.Session,
    cfg: SyncConfig,
    target: str,
    desired: dict[str, str],
) -> dict[str, int]:
    stats = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
    existing = vercel_list_envs(session, cfg, target)
    for key, value in desired.items():
        current = existing.get(key)
        current_val = None if current is None else current.get("value")

        if current is None:
            if cfg.dry_run:
                log_event("SYNC_DRY_RUN_CREATE", target=target, key=key)
                stats["created"] += 1
                continue
            ok = vercel_create_env(session, cfg, key=key, value=value, target=target)
            stats["created" if ok else "failed"] += 1
            continue

        if current_val is not None and str(current_val) == value:
            log_event("SYNC_UNCHANGED", target=target, key=key)
            stats["unchanged"] += 1
            continue

        env_id = str(current.get("id", "")).strip()
        if not env_id:
            log_event("SYNC_ENV_ID_MISSING", target=target, key=key)
            stats["failed"] += 1
            continue
        if cfg.dry_run:
            log_event("SYNC_DRY_RUN_UPDATE", target=target, key=key)
            stats["updated"] += 1
            continue
        ok = vercel_update_env(session, cfg, env_id=env_id, key=key, value=value, target=target)
        stats["updated" if ok else "failed"] += 1
    return stats


def vercel_get_project(session: requests.Session, cfg: SyncConfig) -> dict[str, Any] | None:
    headers = build_vercel_headers(cfg.vercel_token)
    url = f"https://api.vercel.com/v9/projects/{cfg.vercel_project_id}"
    ok, status, data, error = request_with_retry(
        session,
        "GET",
        url,
        headers=headers,
        params=vercel_params(cfg),
        retries=cfg.retries,
        timeout_sec=cfg.timeout_sec,
    )
    if not ok:
        log_event("VERCEL_PROJECT_GET_FAILED", status=status, error=error)
        return None
    return data if isinstance(data, dict) else None


def vercel_list_domains(session: requests.Session, cfg: SyncConfig) -> dict[str, dict[str, Any]]:
    headers = build_vercel_headers(cfg.vercel_token)
    url = f"https://api.vercel.com/v9/projects/{cfg.vercel_project_id}/domains"
    ok, status, data, error = request_with_retry(
        session,
        "GET",
        url,
        headers=headers,
        params=vercel_params(cfg),
        retries=cfg.retries,
        timeout_sec=cfg.timeout_sec,
    )
    if not ok:
        log_event("VERCEL_LIST_DOMAINS_FAILED", status=status, error=error)
        return {}
    rows = data.get("domains") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = normalize_domain(row.get("name"), "")
        if name:
            out[name] = row
    return out


def vercel_add_domain(session: requests.Session, cfg: SyncConfig, domain: str) -> bool:
    headers = build_vercel_headers(cfg.vercel_token)
    url = f"https://api.vercel.com/v10/projects/{cfg.vercel_project_id}/domains"
    payload = {"name": domain}
    ok, status, data, error = request_with_retry(
        session,
        "POST",
        url,
        headers=headers,
        params=vercel_params(cfg),
        json_body=payload,
        retries=cfg.retries,
        timeout_sec=cfg.timeout_sec,
    )
    if ok:
        return True

    # Already exists / conflict in Vercel returns 409 for some tenants.
    if status == 409:
        message = ""
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                message = str(err.get("message", "")).strip()
        lowered = message.lower()
        if "already" in lowered and "project" in lowered:
            log_event("VERCEL_DOMAIN_EXISTS", domain=domain, message=message)
            return True
        log_event("VERCEL_ADD_DOMAIN_CONFLICT", domain=domain, message=message or error)
        return False

    detail = error
    if isinstance(data, dict):
        msg = data.get("error", {}) if isinstance(data.get("error"), dict) else {}
        detail = str(msg.get("message") or error)
    log_event("VERCEL_ADD_DOMAIN_FAILED", domain=domain, status=status, error=detail)
    return False


def vercel_patch_domain(session: requests.Session, cfg: SyncConfig, domain: str, payload: dict[str, Any]) -> bool:
    headers = build_vercel_headers(cfg.vercel_token)
    url = f"https://api.vercel.com/v9/projects/{cfg.vercel_project_id}/domains/{domain}"
    ok, status, _data, error = request_with_retry(
        session,
        "PATCH",
        url,
        headers=headers,
        params=vercel_params(cfg),
        json_body=payload,
        retries=cfg.retries,
        timeout_sec=cfg.timeout_sec,
    )
    if not ok:
        log_event("VERCEL_PATCH_DOMAIN_FAILED", domain=domain, status=status, error=error, payload=payload)
    return ok


def vercel_set_primary_domain(session: requests.Session, cfg: SyncConfig, domain: str) -> bool:
    headers = build_vercel_headers(cfg.vercel_token)
    url = f"https://api.vercel.com/v9/projects/{cfg.vercel_project_id}"
    payload = {"primaryDomain": domain}
    ok, status, _data, error = request_with_retry(
        session,
        "PATCH",
        url,
        headers=headers,
        params=vercel_params(cfg),
        json_body=payload,
        retries=cfg.retries,
        timeout_sec=cfg.timeout_sec,
    )
    if not ok:
        err_text = str(error or "")
        if "additional property `primaryDomain`" in err_text:
            log_event("VERCEL_SET_PRIMARY_UNSUPPORTED", domain=domain)
            return True
        log_event("VERCEL_SET_PRIMARY_FAILED", domain=domain, status=status, error=error)
        return False
    return True


def redirect_target_for_domain(source_domain: str, cfg: SyncConfig) -> str:
    if source_domain.startswith("support."):
        return cfg.support_domain
    return cfg.primary_domain


def sync_domains(session: requests.Session, cfg: SyncConfig) -> dict[str, int]:
    stats = {
        "ensured": 0,
        "redirect_updated": 0,
        "primary_set": 0,
        "failed": 0,
    }

    desired = tuple(
        dict.fromkeys(
            [
                cfg.primary_domain,
                cfg.www_domain,
                cfg.support_domain,
                *cfg.redirect_source_domains,
            ]
        )
    )
    existing = vercel_list_domains(session, cfg)

    for domain in desired:
        if not domain:
            continue
        if domain in existing:
            stats["ensured"] += 1
            continue
        if cfg.dry_run:
            log_event("DOMAIN_DRY_RUN_ENSURE", domain=domain)
            stats["ensured"] += 1
            continue
        ok = vercel_add_domain(session, cfg, domain)
        if ok:
            stats["ensured"] += 1
        else:
            stats["failed"] += 1

    if cfg.dry_run:
        log_event("DOMAIN_DRY_RUN_PRIMARY", domain=cfg.primary_domain)
        stats["primary_set"] += 1
    else:
        ok = vercel_set_primary_domain(session, cfg, cfg.primary_domain)
        if ok:
            stats["primary_set"] += 1
        else:
            stats["failed"] += 1

    # Allow Vercel domain state to settle, then refresh.
    if not cfg.dry_run:
        time.sleep(1.0)
    existing = vercel_list_domains(session, cfg)

    # Keep io domains non-redirecting.
    for domain in (cfg.primary_domain, cfg.www_domain, cfg.support_domain):
        if not domain:
            continue
        payload = {"redirect": None}
        if cfg.dry_run:
            log_event("DOMAIN_DRY_RUN_PATCH", domain=domain, payload=payload)
            continue
        _ = vercel_patch_domain(session, cfg, domain, payload)

    for source in cfg.redirect_source_domains:
        if not source:
            continue
        target = redirect_target_for_domain(source, cfg)
        if target not in existing and not cfg.dry_run:
            if not vercel_add_domain(session, cfg, target):
                stats["failed"] += 1
                continue
        payload = {
            "redirect": target,
            "redirectStatusCode": cfg.redirect_status_code,
        }
        if cfg.dry_run:
            log_event("DOMAIN_DRY_RUN_REDIRECT", source=source, target=payload["redirect"], status=cfg.redirect_status_code)
            stats["redirect_updated"] += 1
            continue
        ok = vercel_patch_domain(session, cfg, source, payload)
        if not ok:
            # Some Vercel API edges require target domain to be present before redirect patch.
            _ = vercel_add_domain(session, cfg, target)
            ok = vercel_patch_domain(session, cfg, source, payload)
        if ok:
            stats["redirect_updated"] += 1
        else:
            stats["failed"] += 1

    return stats


def trigger_vercel_deploy(session: requests.Session, cfg: SyncConfig) -> bool:
    project = vercel_get_project(session, cfg)
    if not project:
        return False
    project_name = str(project.get("name", "")).strip()
    link = project.get("link") if isinstance(project.get("link"), dict) else {}
    repo_id = link.get("repoId")
    repo_type = str(link.get("type", "")).strip()
    if not project_name or not repo_id or repo_type != "github":
        log_event(
            "VERCEL_DEPLOY_SKIPPED",
            reason="missing_project_link_info",
            project_name=project_name,
            repo_type=repo_type,
        )
        return False

    headers = build_vercel_headers(cfg.vercel_token)
    url = "https://api.vercel.com/v13/deployments"
    payload = {
        "name": project_name,
        "project": cfg.vercel_project_id,
        "target": "production",
        "gitSource": {
            "type": "github",
            "repoId": str(repo_id),
            "ref": cfg.deploy_ref,
        },
        "meta": {"trigger": "vercel_ops_sync"},
    }
    ok, status, data, error = request_with_retry(
        session,
        "POST",
        url,
        headers=headers,
        params=vercel_params(cfg),
        json_body=payload,
        retries=cfg.retries,
        timeout_sec=cfg.timeout_sec,
    )
    if not ok:
        log_event("VERCEL_DEPLOY_TRIGGER_FAILED", status=status, error=error)
        return False
    deployment_id = data.get("id") if isinstance(data, dict) else None
    deployment_url = data.get("url") if isinstance(data, dict) else None
    log_event("VERCEL_DEPLOY_TRIGGERED", deployment_id=deployment_id, deployment_url=deployment_url)
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync GitHub variables to Vercel env vars with admin overwrite.")
    parser.add_argument("--dry-run", action="store_true", help="Show planned actions without changing Vercel.")
    parser.add_argument("--no-deploy", action="store_true", help="Skip trigger deployment even if enabled by env.")
    parser.add_argument("--support-prefix", default=DEFAULT_SUPPORT_PREFIX, help="Prefix to sync from GitHub variables.")
    parser.add_argument("--retry", type=int, default=3, help="HTTP retry count for transient failures.")
    parser.add_argument("--timeout-sec", type=float, default=15.0, help="HTTP timeout in seconds.")
    return parser.parse_args()


def run_sync() -> int:
    args = parse_args()
    cfg = load_config(args)

    missing = []
    if not cfg.github_token:
        missing.append("GITHUB_TOKEN")
    if not cfg.vercel_token:
        missing.append("VERCEL_TOKEN")
    if not cfg.vercel_project_id:
        missing.append("VERCEL_PROJECT_ID")
    if not cfg.supabase_url:
        missing.append("SUPABASE_URL")
    if not cfg.supabase_anon_key:
        missing.append("SUPABASE_ANON_KEY")
    if missing:
        log_event("CONFIG_MISSING", missing=",".join(missing))
        return 1

    session = requests.Session()
    gh_support_vars = gh_list_support_variables(session, cfg)
    env_support_vars = env_list_support_variables(cfg.support_prefix)
    support_vars = {**env_support_vars, **gh_support_vars}
    desired = {
        "SUPABASE_URL": cfg.supabase_url,
        "SUPABASE_ANON_KEY": cfg.supabase_anon_key,
        **support_vars,
    }
    if cfg.supabase_service_role_key:
        desired["SUPABASE_SERVICE_ROLE_KEY"] = cfg.supabase_service_role_key

    log_event(
        "SYNC_PLAN",
        dry_run=cfg.dry_run,
        targets=",".join(cfg.targets),
        keys_total=len(desired),
        support_keys=len(support_vars),
        support_keys_env=len(env_support_vars),
        support_keys_github=len(gh_support_vars),
        domain_sync=cfg.enable_domain_sync,
    )
    if cfg.dry_run:
        for key in sorted(desired):
            log_event("SYNC_DRY_KEY", key=key)

    total = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
    for target in cfg.targets:
        stats = sync_target(session, cfg, target, desired)
        for k in total:
            total[k] += stats[k]
        log_event("SYNC_TARGET_DONE", target=target, **stats)

    domain_stats = {"ensured": 0, "redirect_updated": 0, "primary_set": 0, "failed": 0}
    if cfg.enable_domain_sync:
        domain_stats = sync_domains(session, cfg)
        log_event("DOMAIN_SYNC_DONE", **domain_stats)

    deploy_triggered = False
    if cfg.trigger_deploy and not cfg.dry_run:
        deploy_triggered = trigger_vercel_deploy(session, cfg)
    elif cfg.trigger_deploy and cfg.dry_run:
        log_event("SYNC_DRY_RUN_DEPLOY", enabled=True)

    log_event("SYNC_DONE", deploy_triggered=deploy_triggered, **total, domain_failed=domain_stats["failed"])
    if total["failed"] > 0 or domain_stats["failed"] > 0:
        return 2
    return 0


def main() -> int:
    try:
        return run_sync()
    except Exception as exc:  # noqa: BLE001
        log_event("SYNC_FATAL", error=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
