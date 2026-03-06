from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = ROOT / "logs"
OUTPUT_PATH = LOGS_DIR / "platform_sync_status.json"


@dataclass(frozen=True)
class SyncConfig:
    github_token: str
    github_owner: str
    github_repo: str
    vercel_token: str
    vercel_project_id: str
    vercel_team_id: str
    public_base_url: str
    expected_markers: tuple[str, ...]
    timeout_sec: float
    retries: int


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")


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
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value


def load_env_files() -> None:
    load_dotenv(dotenv_path=ROOT / ".env", override=False)
    load_dotenv(dotenv_path=ROOT / "support" / ".env", override=False)


def parse_config() -> SyncConfig:
    timeout_sec = max(4.0, parse_float(os.getenv("PLATFORM_SYNC_TIMEOUT_SEC"), 12.0))
    retries = max(1, parse_int(os.getenv("PLATFORM_SYNC_RETRIES"), 2))
    marker_raw = str(
        os.getenv(
            "PLATFORM_SYNC_EXPECTED_MARKERS",
            "Quant Engine Dashboard|量化引擎儀表板|LEIMAI ORACLE",
        )
    )
    markers = tuple(token.strip() for token in marker_raw.split("|") if token.strip())
    public_base_url = str(os.getenv("SUPPORT_BASE_URL", "")).strip().rstrip("/")
    if not public_base_url:
        public_base_url = "https://leimai.io"
    return SyncConfig(
        github_token=str(os.getenv("GITHUB_TOKEN", "")).strip(),
        github_owner=str(os.getenv("GITHUB_OWNER", "Le1Ma1")).strip() or "Le1Ma1",
        github_repo=str(os.getenv("GITHUB_REPO", "leimai-oracle")).strip() or "leimai-oracle",
        vercel_token=str(os.getenv("VERCEL_TOKEN", "")).strip(),
        vercel_project_id=str(os.getenv("VERCEL_PROJECT_ID", "")).strip(),
        vercel_team_id=str(os.getenv("VERCEL_ORG_ID", os.getenv("VERCEL_TEAM_ID", ""))).strip(),
        public_base_url=public_base_url,
        expected_markers=markers,
        timeout_sec=timeout_sec,
        retries=retries,
    )


def run_git(*args: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(ROOT),
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        return False, str(exc)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "").strip()
    return True, (proc.stdout or "").strip()


def request_json(
    method: str,
    url: str,
    *,
    timeout_sec: float,
    retries: int,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> tuple[bool, int | None, Any, str | None]:
    last_error: str | None = None
    with requests.Session() as session:
        for attempt in range(1, retries + 1):
            try:
                resp = session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    timeout=(5.0, timeout_sec),
                )
                code = int(resp.status_code)
                if code in {429, 500, 502, 503, 504} and attempt < retries:
                    time.sleep(min(8.0, 2 ** (attempt - 1)))
                    continue
                if code < 200 or code >= 300:
                    return False, code, None, (resp.text or "")[:280]
                try:
                    payload = resp.json()
                except Exception:
                    payload = {}
                return True, code, payload, None
            except requests.RequestException as exc:
                last_error = str(exc)
                if attempt < retries:
                    time.sleep(min(8.0, 2 ** (attempt - 1)))
        return False, None, None, last_error or "request_failed"


def request_text(
    url: str,
    *,
    timeout_sec: float,
    retries: int,
) -> tuple[bool, int | None, str, str | None]:
    last_error: str | None = None
    with requests.Session() as session:
        for attempt in range(1, retries + 1):
            try:
                resp = session.get(url, timeout=(5.0, timeout_sec), allow_redirects=True)
                code = int(resp.status_code)
                if code in {429, 500, 502, 503, 504} and attempt < retries:
                    time.sleep(min(8.0, 2 ** (attempt - 1)))
                    continue
                if code < 200 or code >= 300:
                    return False, code, "", (resp.text or "")[:280]
                return True, code, resp.text or "", None
            except requests.RequestException as exc:
                last_error = str(exc)
                if attempt < retries:
                    time.sleep(min(8.0, 2 ** (attempt - 1)))
        return False, None, "", last_error or "request_failed"


def github_main_sha(cfg: SyncConfig) -> tuple[str | None, str | None]:
    if not cfg.github_token:
        return None, "missing_github_token"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {cfg.github_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"https://api.github.com/repos/{cfg.github_owner}/{cfg.github_repo}/commits/main"
    ok, _status, payload, err = request_json(
        "GET",
        url,
        headers=headers,
        timeout_sec=cfg.timeout_sec,
        retries=cfg.retries,
    )
    if not ok:
        return None, err or "github_request_failed"
    sha = str((payload or {}).get("sha", "")).strip()
    if not sha:
        return None, "github_sha_missing"
    return sha, None


def vercel_latest_production(cfg: SyncConfig) -> tuple[dict[str, Any], str | None]:
    if not cfg.vercel_token or not cfg.vercel_project_id:
        return {}, "missing_vercel_credentials"
    headers = {"Authorization": f"Bearer {cfg.vercel_token}"}
    params: dict[str, Any] = {"projectId": cfg.vercel_project_id, "target": "production", "limit": 1}
    if cfg.vercel_team_id:
        params["teamId"] = cfg.vercel_team_id
    ok, _status, payload, err = request_json(
        "GET",
        "https://api.vercel.com/v6/deployments",
        headers=headers,
        params=params,
        timeout_sec=cfg.timeout_sec,
        retries=cfg.retries,
    )
    if not ok:
        return {}, err or "vercel_request_failed"
    rows = (payload or {}).get("deployments", [])
    if not isinstance(rows, list) or not rows:
        return {}, "vercel_deployment_missing"
    latest = rows[0] or {}
    return {
        "id": str(latest.get("uid", "")),
        "url": str(latest.get("url", "")),
        "state": str(latest.get("readyState", "")),
        "target": str(latest.get("target", "")),
        "created_at": latest.get("createdAt"),
        "commit_sha": str((latest.get("meta") or {}).get("githubCommitSha", "")),
        "commit_ref": str((latest.get("meta") or {}).get("githubCommitRef", "")),
        "repo": str((latest.get("meta") or {}).get("githubRepo", "")),
        "org": str((latest.get("meta") or {}).get("githubOrg", "")),
    }, None


def public_surface(cfg: SyncConfig) -> tuple[dict[str, Any], str | None]:
    ok, code, text, err = request_text(
        cfg.public_base_url,
        timeout_sec=cfg.timeout_sec,
        retries=cfg.retries,
    )
    if not ok:
        return {
            "url": cfg.public_base_url,
            "status_code": code,
            "title": "",
            "marker_hit": False,
            "matched_marker": "",
        }, err or "public_request_failed"
    lower = text.lower()
    title = ""
    title_start = lower.find("<title")
    if title_start >= 0:
        gt = text.find(">", title_start)
        end = lower.find("</title>", gt + 1 if gt >= 0 else title_start)
        if gt >= 0 and end > gt:
            title = text[gt + 1 : end].strip()
    matched_marker = ""
    for marker in cfg.expected_markers:
        if marker and marker in text:
            matched_marker = marker
            break
    return {
        "url": cfg.public_base_url,
        "status_code": code,
        "title": title,
        "marker_hit": bool(matched_marker),
        "matched_marker": matched_marker,
    }, None


def collect_local_git_state() -> dict[str, Any]:
    head_ok, head = run_git("rev-parse", "HEAD")
    branch_ok, branch = run_git("branch", "--show-current")
    status_ok, status_text = run_git("status", "--porcelain")
    fetch_ok, fetch_err = run_git("fetch", "origin", "--prune")
    origin_ok, origin_sha = run_git("rev-parse", "origin/main")
    delta_ok, delta = run_git("rev-list", "--left-right", "--count", "HEAD...origin/main")
    ahead = 0
    behind = 0
    if delta_ok:
        parts = delta.split()
        if len(parts) >= 2:
            try:
                ahead = int(parts[0])
                behind = int(parts[1])
            except ValueError:
                ahead = 0
                behind = 0
    return {
        "head_sha": head if head_ok else "",
        "branch": branch if branch_ok else "",
        "dirty": bool(status_ok and status_text.strip()),
        "dirty_files": len(status_text.splitlines()) if status_ok and status_text.strip() else 0,
        "origin_main_sha": origin_sha if origin_ok else "",
        "ahead": ahead,
        "behind": behind,
        "fetch_ok": bool(fetch_ok),
        "fetch_error": "" if fetch_ok else fetch_err,
    }


def build_status(cfg: SyncConfig) -> dict[str, Any]:
    local = collect_local_git_state()
    gh_sha, gh_err = github_main_sha(cfg)
    vercel, vercel_err = vercel_latest_production(cfg)
    public, public_err = public_surface(cfg)

    deployed_sha = str(vercel.get("commit_sha", "")).strip()
    local_sha = str(local.get("head_sha", "")).strip()
    origin_sha = str(local.get("origin_main_sha", "")).strip()

    source_sha = gh_sha or origin_sha
    vercel_synced = bool(source_sha and deployed_sha and deployed_sha == source_sha)
    local_synced = bool(source_sha and local_sha and local_sha == source_sha and not bool(local.get("dirty", False)))
    marker_ok = bool(public.get("marker_hit", False))

    issues: list[dict[str, str]] = []
    if gh_err:
        issues.append({"code": "github_probe_failed", "severity": "major", "detail": gh_err})
    if vercel_err:
        issues.append({"code": "vercel_probe_failed", "severity": "major", "detail": vercel_err})
    if public_err:
        issues.append({"code": "public_probe_failed", "severity": "major", "detail": public_err})
    if source_sha and deployed_sha and deployed_sha != source_sha:
        issues.append(
            {
                "code": "deployment_sha_mismatch",
                "severity": "critical",
                "detail": f"deployed={deployed_sha[:12]} source={source_sha[:12]}",
            }
        )
    if not marker_ok:
        issues.append(
            {
                "code": "public_marker_mismatch",
                "severity": "major",
                "detail": "public site content does not contain expected dashboard markers",
            }
        )
    if bool(local.get("dirty", False)):
        issues.append(
            {
                "code": "local_uncommitted_changes",
                "severity": "minor",
                "detail": f"dirty_files={int(local.get('dirty_files', 0) or 0)}",
            }
        )
    if int(local.get("behind", 0) or 0) > 0:
        issues.append(
            {
                "code": "local_behind_origin",
                "severity": "minor",
                "detail": f"behind={int(local.get('behind', 0) or 0)}",
            }
        )

    severity_rank = {"critical": 3, "major": 2, "minor": 1}
    highest = "ok"
    for issue in issues:
        level = issue.get("severity", "minor")
        if highest == "ok" or severity_rank.get(level, 0) > severity_rank.get(highest, 0):
            highest = level

    pass_status = bool(vercel_synced and marker_ok and highest in {"ok", "minor"})
    recommendation = (
        "push_and_deploy"
        if bool(local.get("dirty", False)) or int(local.get("behind", 0) or 0) > 0
        else "monitor"
    )
    if not vercel_synced:
        recommendation = "repair_deployment_source"
    if not marker_ok:
        recommendation = "verify_frontend_entrypoint"

    return {
        "generated_at_utc": now_iso(),
        "source_of_truth": {
            "policy": "github_main",
            "github_main_sha": gh_sha or "",
            "origin_main_sha": origin_sha,
        },
        "local": local,
        "vercel": vercel,
        "public": public,
        "checks": {
            "local_synced_to_source": local_synced,
            "vercel_synced_to_source": vercel_synced,
            "public_marker_ok": marker_ok,
        },
        "issues": issues,
        "severity": highest,
        "pass": pass_status,
        "recommendation": recommendation,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe GitHub/Vercel/public sync status.")
    parser.add_argument("--output", type=str, default=str(OUTPUT_PATH))
    return parser.parse_args()


def main() -> int:
    load_env_files()
    args = parse_args()
    cfg = parse_config()
    payload = build_status(cfg)
    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(out_path), "severity": payload.get("severity")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
