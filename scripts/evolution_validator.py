from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = ROOT / "logs"
VISUAL_STATE_PATH = LOGS_DIR / "visual_state.json"
OUTPUT_PATH = LOGS_DIR / "evolution_validation.json"
SERVER_FILE = ROOT / "support" / "server.mjs"
GEN_REPORTS_FILE = ROOT / "engine" / "src" / "generate_reports.py"
HARVESTER_FILE = ROOT / "scripts" / "chain_harvester.py"

FORBIDDEN_TERMS = ("GEO", "API", "MOCK", "PYTHON", "PIPELINE")


@dataclass(frozen=True)
class ValidatorConfig:
    base_url: str
    timeout_sec: float
    min_total_score: float


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_event(event: str, **kwargs: Any) -> None:
    print(json.dumps({"ts_utc": utc_now_iso(), "event": event, **kwargs}, ensure_ascii=False))


def parse_args() -> ValidatorConfig:
    parser = argparse.ArgumentParser(description="Validate visual/business/seo evolution integrity.")
    parser.add_argument("--base-url", default=os.getenv("SUPPORT_BASE_URL", "http://127.0.0.1:4310"))
    parser.add_argument("--timeout-sec", type=float, default=float(os.getenv("EVOLUTION_TIMEOUT_SEC", "12")))
    parser.add_argument("--min-total-score", type=float, default=float(os.getenv("EVOLUTION_MIN_SCORE", "95")))
    args = parser.parse_args()
    base_url = str(args.base_url or "").strip().rstrip("/") or "http://127.0.0.1:4310"
    return ValidatorConfig(base_url=base_url, timeout_sec=max(4.0, float(args.timeout_sec)), min_total_score=float(args.min_total_score))


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def strip_html_to_text(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_html(url: str, timeout_sec: float) -> tuple[str, int]:
    try:
        resp = requests.get(url, timeout=timeout_sec)
        return resp.text or "", int(resp.status_code)
    except Exception:
        return "", 0


def check_visual_state(state: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    checks = state.get("checks", {}) if isinstance(state.get("checks"), dict) else {}
    issues: list[str] = []

    contrast_min = float(checks.get("text_contrast_min", 0.0) or 0.0)
    readability = float(checks.get("readability_score", 0.0) or 0.0)
    cta = float(checks.get("cta_prominence_score", 0.0) or 0.0)
    detail_real = bool(checks.get("detail_is_real_report", False))
    index_has_reports = bool(checks.get("index_has_reports", False))
    overflow = checks.get("overflow_hotspots", []) if isinstance(checks.get("overflow_hotspots"), list) else []

    if contrast_min < 4.5:
        issues.append("visual_contrast_low")
    if readability < 80:
        issues.append("visual_readability_low")
    if cta < 55:
        issues.append("visual_cta_low")
    if index_has_reports and not detail_real:
        issues.append("detail_not_real_report")
    if overflow:
        issues.append("visual_overflow_hotspots")

    result = {
        "contrast_min": contrast_min,
        "readability_score": readability,
        "cta_prominence_score": cta,
        "index_has_reports": index_has_reports,
        "detail_is_real_report": detail_real,
        "overflow_hotspots_count": len(overflow),
    }
    return result, issues


def check_copy_density(
    base_url: str,
    timeout_sec: float,
    detail_url: str,
    index_has_reports: bool,
) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    pages = {
        "home": f"{base_url}/",
        "analysis": f"{base_url}/analysis/",
        "vault": f"{base_url}/vault",
        "detail": detail_url or f"{base_url}/analysis/",
    }

    forbidden_hits: dict[str, list[str]] = {}
    jsonld_present: dict[str, bool] = {}
    for key, url in pages.items():
        html, status = fetch_html(url, timeout_sec)
        if status < 200 or status >= 400:
            if key == "detail" and not index_has_reports:
                continue
            issues.append(f"page_unreachable:{key}:{status}")
            continue

        jsonld_present[key] = bool(re.search(r"<script[^>]+application/ld\+json", html, flags=re.IGNORECASE))
        text = strip_html_to_text(html)
        hits = [term for term in FORBIDDEN_TERMS if re.search(rf"\b{re.escape(term)}\b", text, flags=re.IGNORECASE)]
        if hits:
            forbidden_hits[key] = hits
            issues.append(f"forbidden_terms:{key}:{','.join(hits)}")

    if not jsonld_present.get("analysis", False):
        issues.append("jsonld_missing:analysis")
    if index_has_reports and not jsonld_present.get("detail", False):
        issues.append("jsonld_missing:detail")

    return {
        "forbidden_hits": forbidden_hits,
        "jsonld_present": jsonld_present,
    }, issues


def check_business_integrity() -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    server_src = read_text(SERVER_FILE)
    harvester_src = read_text(HARVESTER_FILE)

    required_server_tokens = [
        '"/api/v1/payment/create"',
        '"/api/v1/payment/status"',
        '.from("payment_invoices")',
        '.from("user_access_logs")',
    ]
    missing_server = [token for token in required_server_tokens if token not in server_src]
    if missing_server:
        issues.append("missing_payment_contract")

    required_harvester_tokens = [
        "Premium_Entity",
        "status\": \"paid\"",
        'table("payment_invoices")',
        'table("user_access_logs")',
    ]
    missing_harvester = [token for token in required_harvester_tokens if token not in harvester_src]
    if missing_harvester:
        issues.append("missing_harvester_contract")

    return {
        "missing_server_tokens": missing_server,
        "missing_harvester_tokens": missing_harvester,
    }, issues


def check_prompt_density() -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    src = read_text(GEN_REPORTS_FILE)

    has_zh_style = "結論 -> 證據 -> 風險邊界" in src
    has_en_style = "Conclusion -> Evidence -> Risk Boundary" in src
    has_unique_entity = "Mandatory entity phrase" in src and "unique_entity" in src
    has_no_internal_code_guard = "Do not reveal internal code names" in src

    if not has_zh_style:
        issues.append("zh_prompt_density_missing")
    if not has_en_style:
        issues.append("en_prompt_density_missing")
    if not has_unique_entity:
        issues.append("unique_entity_guard_missing")
    if not has_no_internal_code_guard:
        issues.append("internal_code_guard_missing")

    return {
        "has_zh_style": has_zh_style,
        "has_en_style": has_en_style,
        "has_unique_entity_guard": has_unique_entity,
        "has_internal_code_guard": has_no_internal_code_guard,
    }, issues


def score_matrix(issues: list[str], visual: dict[str, Any], copy_scan: dict[str, Any]) -> dict[str, Any]:
    quality_density = 100.0
    if any(item.startswith("forbidden_terms") for item in issues):
        quality_density = 0.0
    elif any(item.startswith("jsonld_missing") for item in issues):
        quality_density = 72.0

    brand = 100.0
    if visual.get("contrast_min", 0.0) < 4.5:
        brand -= 35.0
    if visual.get("readability_score", 0.0) < 80:
        brand -= 25.0
    if visual.get("overflow_hotspots_count", 0) > 0:
        brand -= 20.0
    brand = max(0.0, brand)

    business = 100.0
    if any(item.startswith("missing_payment_contract") for item in issues):
        business = 20.0
    elif any(item.startswith("missing_harvester_contract") for item in issues):
        business = 40.0

    seo = 100.0
    jsonld_present = copy_scan.get("jsonld_present", {}) if isinstance(copy_scan, dict) else {}
    if not jsonld_present.get("analysis", False) or not jsonld_present.get("detail", False):
        seo = 0.0

    weighted = (quality_density * 0.40) + (brand * 0.30) + (business * 0.20) + (seo * 0.10)
    return {
        "quality_density": round(quality_density, 2),
        "brand_authority": round(brand, 2),
        "business_harvest": round(business, 2),
        "sovereign_seo": round(seo, 2),
        "total": round(weighted, 2),
    }


def main() -> int:
    cfg = parse_args()
    state = load_json(VISUAL_STATE_PATH)
    if not state:
        log_event("EVOLUTION_VALIDATION_FAILED", reason="visual_state_missing")
        return 2

    detail_url = str(state.get("detail_url") or f"{cfg.base_url}/analysis/")
    state_checks = state.get("checks", {}) if isinstance(state.get("checks"), dict) else {}
    index_has_reports = bool(state_checks.get("index_has_reports", False))

    visual_result, visual_issues = check_visual_state(state)
    copy_result, copy_issues = check_copy_density(cfg.base_url, cfg.timeout_sec, detail_url, index_has_reports)
    business_result, business_issues = check_business_integrity()
    prompt_result, prompt_issues = check_prompt_density()

    issues = [*visual_issues, *copy_issues, *business_issues, *prompt_issues]
    scores = score_matrix(issues, visual_result, copy_result)

    payload = {
        "ts_utc": utc_now_iso(),
        "base_url": cfg.base_url,
        "visual": visual_result,
        "copy": copy_result,
        "business": business_result,
        "prompt": prompt_result,
        "issues": issues,
        "issue_count": len(issues),
        "score": scores,
        "pass": scores["total"] >= cfg.min_total_score and len([i for i in issues if i.startswith("forbidden_terms")]) == 0,
        "threshold": cfg.min_total_score,
    }

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if payload["pass"]:
        log_event("EVOLUTION_VALIDATION_PASS", score=scores["total"], issues=len(issues))
        return 0

    log_event("EVOLUTION_VALIDATION_FAIL", score=scores["total"], issues=issues)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
