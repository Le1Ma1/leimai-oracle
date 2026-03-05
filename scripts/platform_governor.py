from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = ROOT / "logs"
REPORT_PATH = LOGS_DIR / "platform_governor_report.json"
ACTIONS_PATH = LOGS_DIR / "platform_governor_actions.jsonl"

WATCH_WORKFLOWS: tuple[str, ...] = (
    "autonomic_evolution.yml",
    "ingest_4h.yml",
    "heartbeat_1h.yml",
    "harvest_payments_5m.yml",
    "growth_agent_daily.yml",
    "vercel_env_sync.yml",
)

CRITICAL_WORKFLOWS = {
    "autonomic_evolution.yml",
    "ingest_4h.yml",
    "heartbeat_1h.yml",
    "harvest_payments_5m.yml",
}


@dataclass(frozen=True)
class GovernorConfig:
    github_token: str
    github_owner: str
    github_repo: str
    vercel_token: str
    vercel_project_id: str
    vercel_team_id: str
    supabase_url: str
    supabase_service_role_key: str
    support_base_url: str
    stale_report_hours: float
    max_actions: int
    timeout_sec: float
    retries: int
    auto_heal: bool
    dry_run: bool
    fail_on_critical: bool


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def now_iso() -> str:
    return iso_utc(utc_now())


def parse_bool(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return default


def parse_float(raw: Any, default: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value != value:
        return default
    return value


def parse_int(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def normalize_url(raw: str, fallback: str) -> str:
    text = str(raw or "").strip()
    if not text:
        text = fallback
    return text.rstrip("/")


def parse_utc_ts(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def load_env_files() -> None:
    load_dotenv(dotenv_path=ROOT / ".env", override=False)
    load_dotenv(dotenv_path=ROOT / "support" / ".env", override=False)


def parse_args() -> GovernorConfig:
    parser = argparse.ArgumentParser(
        description="Global platform governor for GitHub, Vercel, Supabase, and crypto-support health.",
    )
    parser.add_argument("--stale-report-hours", type=float, default=parse_float(os.getenv("PLATFORM_GOVERNOR_STALE_REPORT_HOURS"), 6.0))
    parser.add_argument("--max-actions", type=int, default=parse_int(os.getenv("PLATFORM_GOVERNOR_MAX_ACTIONS"), 4))
    parser.add_argument("--timeout-sec", type=float, default=parse_float(os.getenv("PLATFORM_GOVERNOR_TIMEOUT_SEC"), 12.0))
    parser.add_argument("--retries", type=int, default=parse_int(os.getenv("PLATFORM_GOVERNOR_RETRIES"), 3))
    parser.add_argument("--auto-heal", dest="auto_heal", action=argparse.BooleanOptionalAction, default=parse_bool(os.getenv("PLATFORM_GOVERNOR_AUTO_HEAL"), True))
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--fail-on-critical", dest="fail_on_critical", action=argparse.BooleanOptionalAction, default=parse_bool(os.getenv("PLATFORM_GOVERNOR_FAIL_ON_CRITICAL"), True))
    args = parser.parse_args()

    load_env_files()

    return GovernorConfig(
        github_token=str(os.getenv("GITHUB_TOKEN", "")).strip(),
        github_owner=str(os.getenv("GITHUB_OWNER", "Le1Ma1")).strip() or "Le1Ma1",
        github_repo=str(os.getenv("GITHUB_REPO", "leimai-oracle")).strip() or "leimai-oracle",
        vercel_token=str(os.getenv("VERCEL_TOKEN", "")).strip(),
        vercel_project_id=str(os.getenv("VERCEL_PROJECT_ID", "")).strip(),
        vercel_team_id=str(os.getenv("VERCEL_TEAM_ID", "")).strip(),
        supabase_url=normalize_url(os.getenv("SUPABASE_URL", ""), ""),
        supabase_service_role_key=str(os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip(),
        support_base_url=normalize_url(
            os.getenv("SUPPORT_BASE_URL", ""),
            "https://support.leimai.io",
        ),
        stale_report_hours=max(1.0, float(args.stale_report_hours)),
        max_actions=max(0, int(args.max_actions)),
        timeout_sec=max(4.0, float(args.timeout_sec)),
        retries=max(1, int(args.retries)),
        auto_heal=bool(args.auto_heal),
        dry_run=bool(args.dry_run),
        fail_on_critical=bool(args.fail_on_critical),
    )


def log_event(event: str, **kwargs: Any) -> None:
    payload = {"ts_utc": now_iso(), "event": event, **kwargs}
    print(json.dumps(payload, ensure_ascii=False))


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False))
        fp.write("\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout_sec: float,
    retries: int,
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
            status = int(resp.status_code)
            if status in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(min(8.0, 2 ** (attempt - 1)))
                continue
            if status < 200 or status >= 300:
                text = (resp.text or "")[:400]
                return False, status, None, f"http_{status}:{text}"
            data: Any
            try:
                data = resp.json()
            except ValueError:
                data = resp.text or ""
            return True, status, data, None
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt < retries:
                time.sleep(min(8.0, 2 ** (attempt - 1)))
    return False, None, None, last_error or "request_failed"


def github_headers(cfg: GovernorConfig) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {cfg.github_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def vercel_headers(cfg: GovernorConfig) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {cfg.vercel_token}",
        "Content-Type": "application/json",
    }


def supabase_headers(cfg: GovernorConfig) -> dict[str, str]:
    return {
        "apikey": cfg.supabase_service_role_key,
        "Authorization": f"Bearer {cfg.supabase_service_role_key}",
        "Content-Type": "application/json",
    }


def build_issue(code: str, severity: str, message: str, **context: Any) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "context": context,
    }


def build_action(action: str, target: str, ok: bool, detail: str = "", **context: Any) -> dict[str, Any]:
    return {
        "ts_utc": now_iso(),
        "action": action,
        "target": target,
        "ok": bool(ok),
        "detail": detail,
        "context": context,
    }


def gh_dispatch_workflow(
    session: requests.Session,
    cfg: GovernorConfig,
    workflow_file: str,
    *,
    inputs: dict[str, str] | None = None,
    dry_run: bool,
) -> tuple[bool, str]:
    if dry_run:
        return True, "dry_run"
    url = (
        f"https://api.github.com/repos/{cfg.github_owner}/{cfg.github_repo}"
        f"/actions/workflows/{workflow_file}/dispatches"
    )
    body = {"ref": "main"}
    if inputs:
        body["inputs"] = inputs
    ok, status, _data, error = request_with_retry(
        session,
        "POST",
        url,
        headers=github_headers(cfg),
        json_body=body,
        timeout_sec=cfg.timeout_sec,
        retries=cfg.retries,
    )
    if ok:
        return True, f"http_{status}"
    return False, error or "dispatch_failed"


def gh_rerun_failed_jobs(
    session: requests.Session,
    cfg: GovernorConfig,
    run_id: str,
    *,
    dry_run: bool,
) -> tuple[bool, str]:
    if dry_run:
        return True, "dry_run"
    url = (
        f"https://api.github.com/repos/{cfg.github_owner}/{cfg.github_repo}"
        f"/actions/runs/{run_id}/rerun-failed-jobs"
    )
    ok, status, _data, error = request_with_retry(
        session,
        "POST",
        url,
        headers=github_headers(cfg),
        timeout_sec=cfg.timeout_sec,
        retries=cfg.retries,
    )
    if ok:
        return True, f"http_{status}"
    return False, error or "rerun_failed"


def gh_latest_run_for_workflow(
    session: requests.Session,
    cfg: GovernorConfig,
    workflow_file: str,
) -> tuple[dict[str, Any] | None, str | None]:
    url = (
        f"https://api.github.com/repos/{cfg.github_owner}/{cfg.github_repo}"
        f"/actions/workflows/{workflow_file}/runs"
    )
    ok, _status, data, error = request_with_retry(
        session,
        "GET",
        url,
        headers=github_headers(cfg),
        params={"per_page": 1},
        timeout_sec=cfg.timeout_sec,
        retries=cfg.retries,
    )
    if not ok:
        if (error or "").startswith("http_404"):
            return None, "workflow_not_found"
        return None, error
    runs = data.get("workflow_runs") if isinstance(data, dict) else None
    if not isinstance(runs, list) or not runs:
        return None, "no_runs"
    row = runs[0]
    return row if isinstance(row, dict) else None, None


def check_github_workflows(
    session: requests.Session,
    cfg: GovernorConfig,
    *,
    action_budget: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    issues: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    used = 0
    if not cfg.github_token:
        issues.append(build_issue("github_token_missing", "critical", "GITHUB_TOKEN missing"))
        return issues, actions, used

    for workflow in WATCH_WORKFLOWS:
        run, err = gh_latest_run_for_workflow(session, cfg, workflow)
        if not run:
            if err == "workflow_not_found":
                continue
            issues.append(build_issue("github_run_missing", "major", "Unable to fetch workflow run", workflow=workflow, error=err or "unknown"))
            continue

        run_id = str(run.get("id") or "")
        status = str(run.get("status") or "")
        conclusion = str(run.get("conclusion") or "")
        created_at = str(run.get("created_at") or "")
        check = {
            "workflow": workflow,
            "run_id": run_id,
            "status": status,
            "conclusion": conclusion,
            "created_at_utc": created_at,
            "html_url": str(run.get("html_url") or ""),
        }
        if status == "completed" and conclusion == "failure":
            severity = "critical" if workflow in CRITICAL_WORKFLOWS else "major"
            issues.append(build_issue("github_workflow_failed", severity, "Latest workflow run failed", **check))
            can_heal = cfg.auto_heal and used < action_budget and run_id
            if can_heal:
                ok, detail = gh_rerun_failed_jobs(session, cfg, run_id, dry_run=cfg.dry_run)
                actions.append(build_action("rerun_failed_jobs", workflow, ok, detail, run_id=run_id))
                used += 1
        elif status != "completed":
            issues.append(build_issue("github_workflow_not_completed", "minor", "Latest workflow run still in progress", **check))

    return issues, actions, used


def check_supabase_freshness(
    session: requests.Session,
    cfg: GovernorConfig,
    *,
    action_budget: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], int]:
    check: dict[str, Any] = {"ok": False}
    issues: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    used = 0

    if not cfg.supabase_url or not cfg.supabase_service_role_key:
        issues.append(build_issue("supabase_config_missing", "critical", "Supabase URL or service key missing"))
        return check, issues, actions, used

    url = f"{cfg.supabase_url}/rest/v1/oracle_reports"
    ok, _status, data, error = request_with_retry(
        session,
        "GET",
        url,
        headers=supabase_headers(cfg),
        params={"select": "updated_at,created_at,report_id", "order": "updated_at.desc", "limit": "1"},
        timeout_sec=cfg.timeout_sec,
        retries=cfg.retries,
    )
    if not ok:
        issues.append(build_issue("supabase_report_query_failed", "critical", "oracle_reports query failed", error=error or "unknown"))
        return check, issues, actions, used

    rows = data if isinstance(data, list) else []
    if not rows or not isinstance(rows[0], dict):
        issues.append(build_issue("supabase_report_empty", "critical", "No oracle_reports rows found"))
        return check, issues, actions, used

    row = rows[0]
    latest_ts = parse_utc_ts(row.get("updated_at")) or parse_utc_ts(row.get("created_at"))
    if latest_ts is None:
        issues.append(build_issue("supabase_report_ts_invalid", "major", "Latest report timestamp invalid"))
        return check, issues, actions, used

    age_hours = max(0.0, (utc_now() - latest_ts).total_seconds() / 3600.0)
    check = {
        "ok": True,
        "latest_report_ts_utc": iso_utc(latest_ts),
        "report_age_hours": round(age_hours, 3),
        "stale_threshold_hours": cfg.stale_report_hours,
    }

    if age_hours > cfg.stale_report_hours:
        issues.append(
            build_issue(
                "supabase_reports_stale",
                "critical",
                "Report feed is stale",
                latest_report_ts_utc=iso_utc(latest_ts),
                age_hours=round(age_hours, 3),
                threshold_hours=cfg.stale_report_hours,
            )
        )
        can_heal = cfg.auto_heal and used < action_budget
        if can_heal:
            ok_dispatch, detail = gh_dispatch_workflow(
                session,
                cfg,
                "ingest_4h.yml",
                inputs={
                    "reason": "platform_governor_stale_reports",
                    "detected_lag_hours": f"{age_hours:.6f}",
                    "latest_report_ts_utc": iso_utc(latest_ts),
                },
                dry_run=cfg.dry_run,
            )
            actions.append(build_action("dispatch_workflow", "ingest_4h.yml", ok_dispatch, detail))
            used += 1

    return check, issues, actions, used


def check_vercel_deployment(
    session: requests.Session,
    cfg: GovernorConfig,
    *,
    action_budget: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], int]:
    check: dict[str, Any] = {"ok": False}
    issues: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    used = 0

    if not cfg.vercel_token or not cfg.vercel_project_id:
        issues.append(build_issue("vercel_config_missing", "major", "Vercel token or project id missing"))
        return check, issues, actions, used

    params: dict[str, Any] = {"projectId": cfg.vercel_project_id, "limit": 3}
    if cfg.vercel_team_id:
        params["teamId"] = cfg.vercel_team_id
    url = "https://api.vercel.com/v6/deployments"
    ok, _status, data, error = request_with_retry(
        session,
        "GET",
        url,
        headers=vercel_headers(cfg),
        params=params,
        timeout_sec=cfg.timeout_sec,
        retries=cfg.retries,
    )
    if not ok:
        issues.append(build_issue("vercel_deploy_query_failed", "major", "Failed to query Vercel deployments", error=error or "unknown"))
        return check, issues, actions, used

    rows = data.get("deployments") if isinstance(data, dict) else []
    if not isinstance(rows, list) or not rows:
        issues.append(build_issue("vercel_deploy_empty", "major", "No deployments returned from Vercel"))
        return check, issues, actions, used

    latest = rows[0] if isinstance(rows[0], dict) else {}
    state = str(latest.get("state") or "").upper()
    deployment_id = str(latest.get("uid") or latest.get("id") or "")
    url_target = str(latest.get("url") or "")
    created_ms = float(latest.get("created") or 0.0)
    created_ts = (
        datetime.fromtimestamp(created_ms / 1000.0, tz=timezone.utc)
        if created_ms > 0
        else None
    )
    check = {
        "ok": True,
        "latest_state": state,
        "latest_id": deployment_id,
        "latest_url": url_target,
        "latest_created_at_utc": iso_utc(created_ts) if created_ts else "",
    }

    if state not in {"READY", "CANCELED"}:
        severity = "critical" if state == "ERROR" else "major"
        issues.append(build_issue("vercel_deploy_unhealthy", severity, "Latest Vercel deployment not healthy", state=state, deployment_id=deployment_id))
        can_heal = cfg.auto_heal and used < action_budget
        if can_heal:
            ok_dispatch, detail = gh_dispatch_workflow(
                session,
                cfg,
                "vercel_env_sync.yml",
                inputs=None,
                dry_run=cfg.dry_run,
            )
            actions.append(build_action("dispatch_workflow", "vercel_env_sync.yml", ok_dispatch, detail))
            used += 1

    return check, issues, actions, used


def check_crypto_surface(
    session: requests.Session,
    cfg: GovernorConfig,
    *,
    action_budget: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], int]:
    check: dict[str, Any] = {"ok": False}
    issues: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    used = 0

    url = f"{cfg.support_base_url}/api/v1/health"
    ok, status, data, error = request_with_retry(
        session,
        "GET",
        url,
        timeout_sec=cfg.timeout_sec,
        retries=cfg.retries,
    )
    if not ok:
        issues.append(build_issue("crypto_health_unreachable", "major", "Support health endpoint unreachable", status=status or 0, error=error or "unknown"))
        return check, issues, actions, used
    if not isinstance(data, dict):
        issues.append(build_issue("crypto_health_invalid", "major", "Support health payload invalid"))
        return check, issues, actions, used

    source_status = data.get("source_status") if isinstance(data.get("source_status"), dict) else {}
    tronscan_ok = bool((source_status.get("tronscan") or {}).get("ok", False)) if isinstance(source_status.get("tronscan"), dict) else False
    trongrid_ok = bool((source_status.get("trongrid") or {}).get("ok", False)) if isinstance(source_status.get("trongrid"), dict) else False

    counts = data.get("counts") if isinstance(data.get("counts"), dict) else {}
    check = {
        "ok": True,
        "status_code": status,
        "tronscan_ok": tronscan_ok,
        "trongrid_ok": trongrid_ok,
        "counts": counts,
    }
    if not tronscan_ok or not trongrid_ok:
        issues.append(build_issue("crypto_source_degraded", "critical", "One or more chain sources are degraded", tronscan_ok=tronscan_ok, trongrid_ok=trongrid_ok))
        can_heal = cfg.auto_heal and used < action_budget
        if can_heal:
            ok_dispatch, detail = gh_dispatch_workflow(
                session,
                cfg,
                "harvest_payments_5m.yml",
                inputs={"reason": "platform_governor_crypto_source_degraded"},
                dry_run=cfg.dry_run,
            )
            actions.append(build_action("dispatch_workflow", "harvest_payments_5m.yml", ok_dispatch, detail))
            used += 1

    return check, issues, actions, used


def compute_score(issues: list[dict[str, Any]]) -> tuple[float, dict[str, int]]:
    severity_weight = {"critical": 22.0, "major": 12.0, "minor": 5.0}
    severity_count = {"critical": 0, "major": 0, "minor": 0}
    penalty = 0.0
    for issue in issues:
        severity = str(issue.get("severity") or "minor").lower()
        if severity not in severity_count:
            severity = "minor"
        severity_count[severity] += 1
        penalty += severity_weight.get(severity, 5.0)
    score = clamp(100.0 - penalty, 0.0, 100.0)
    return round(score, 2), severity_count


def run_governor(cfg: GovernorConfig) -> tuple[int, dict[str, Any]]:
    session = requests.Session()
    issues: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    action_budget = max(0, cfg.max_actions)

    gh_issues, gh_actions, gh_used = check_github_workflows(session, cfg, action_budget=action_budget)
    issues.extend(gh_issues)
    actions.extend(gh_actions)
    action_budget = max(0, action_budget - gh_used)

    supabase_check, sp_issues, sp_actions, sp_used = check_supabase_freshness(session, cfg, action_budget=action_budget)
    issues.extend(sp_issues)
    actions.extend(sp_actions)
    action_budget = max(0, action_budget - sp_used)

    vercel_check, ve_issues, ve_actions, ve_used = check_vercel_deployment(session, cfg, action_budget=action_budget)
    issues.extend(ve_issues)
    actions.extend(ve_actions)
    action_budget = max(0, action_budget - ve_used)

    crypto_check, cr_issues, cr_actions, cr_used = check_crypto_surface(session, cfg, action_budget=action_budget)
    issues.extend(cr_issues)
    actions.extend(cr_actions)
    action_budget = max(0, action_budget - cr_used)

    score, severity_count = compute_score(issues)
    pass_state = severity_count["critical"] == 0 and score >= 85.0
    payload = {
        "ts_utc": now_iso(),
        "mode": {
            "auto_heal": cfg.auto_heal,
            "dry_run": cfg.dry_run,
            "max_actions": cfg.max_actions,
        },
        "checks": {
            "supabase": supabase_check,
            "vercel": vercel_check,
            "crypto_surface": crypto_check,
        },
        "issues": issues,
        "issue_count": len(issues),
        "actions": actions,
        "action_count": len(actions),
        "score": score,
        "severity_count": severity_count,
        "pass": pass_state,
    }
    return (0 if pass_state or not cfg.fail_on_critical else 1), payload


def main() -> int:
    cfg = parse_args()
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    code, payload = run_governor(cfg)
    write_json(REPORT_PATH, payload)
    for action in payload.get("actions", []) if isinstance(payload.get("actions"), list) else []:
        if isinstance(action, dict):
            append_jsonl(ACTIONS_PATH, action)

    log_event(
        "PLATFORM_GOVERNOR_DONE",
        pass_state=payload.get("pass"),
        score=payload.get("score"),
        issue_count=payload.get("issue_count"),
        action_count=payload.get("action_count"),
        critical=(payload.get("severity_count") or {}).get("critical", 0),
    )
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
