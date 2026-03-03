from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from supabase import Client, create_client


TIER_LABELS = ("Plankton", "Fish", "Dolphin", "Whale", "Kraken")


@dataclass(frozen=True)
class ProfileResult:
    wallet_address: str
    whale_tier: str
    profile_payload: dict[str, Any]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def _json_log(event: str, **kwargs: Any) -> None:
    payload: dict[str, Any] = {"ts_utc": now_iso(), "event": event}
    payload.update(kwargs)
    print(json.dumps(payload, ensure_ascii=False))


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except Exception:
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def _canonical_wallet(address: str) -> str:
    return str(address or "").strip()


def _http_get_json(url: str, *, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None, timeout: float = 12.0) -> Any:
    resp = requests.get(url, headers=headers, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _http_post_json(url: str, payload: dict[str, Any], *, headers: dict[str, str] | None = None, timeout: float = 12.0) -> Any:
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _tier_from_usd(portfolio_usd: float | None, native_balance: float | None) -> str:
    if portfolio_usd is not None:
        if portfolio_usd >= 1_000_000:
            return "Kraken"
        if portfolio_usd >= 100_000:
            return "Whale"
        if portfolio_usd >= 10_000:
            return "Dolphin"
        if portfolio_usd >= 1_000:
            return "Fish"
        return "Plankton"

    if native_balance is not None:
        if native_balance >= 500:
            return "Kraken"
        if native_balance >= 50:
            return "Whale"
        if native_balance >= 5:
            return "Dolphin"
        if native_balance >= 0.5:
            return "Fish"
    return "Plankton"


def _extract_top_assets(raw_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in raw_assets:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or item.get("optimized_symbol") or item.get("name") or "").strip()
        amount = _safe_float(item.get("amount"), 0.0) or 0.0
        usd_value = _safe_float(item.get("usd_value"), None)
        if usd_value is None:
            price = _safe_float(item.get("price"), None)
            if price is not None:
                usd_value = amount * price
        normalized.append(
            {
                "symbol": symbol[:24] if symbol else "UNKNOWN",
                "amount": float(amount),
                "usd_value": float(usd_value) if usd_value is not None else None,
            }
        )
    normalized.sort(key=lambda x: float(x.get("usd_value") or 0.0), reverse=True)
    return normalized[:5]


def _profile_from_debank(address: str, api_key: str, timeout_sec: float) -> dict[str, Any] | None:
    if not api_key:
        return None
    headers = {"AccessKey": api_key}
    balance_url = "https://pro-openapi.debank.com/v1/user/total_balance"
    tokens_url = "https://pro-openapi.debank.com/v1/user/token_list"
    balance_payload = _http_get_json(balance_url, headers=headers, params={"id": address}, timeout=timeout_sec)
    tokens_payload = _http_get_json(tokens_url, headers=headers, params={"id": address, "is_all": "false"}, timeout=timeout_sec)

    total_usd = _safe_float(
        (balance_payload or {}).get("total_usd_value")
        or (balance_payload or {}).get("total_usd")
        or (balance_payload or {}).get("usd_value"),
        None,
    )
    top_assets = _extract_top_assets(tokens_payload if isinstance(tokens_payload, list) else [])
    return {
        "data_source": "debank",
        "native_balance": None,
        "portfolio_est_usd": total_usd,
        "portfolio_top_assets": top_assets,
    }


def _profile_from_etherscan(address: str, api_key: str, timeout_sec: float, eth_usd_fallback: float) -> dict[str, Any] | None:
    if not api_key:
        return None
    payload = _http_get_json(
        "https://api.etherscan.io/v2/api",
        params={
            "chainid": 1,
            "module": "account",
            "action": "balance",
            "address": address,
            "tag": "latest",
            "apikey": api_key,
        },
        timeout=timeout_sec,
    )
    wei_raw = str((payload or {}).get("result") or "0")
    native_balance = int(wei_raw) / 1e18
    portfolio_est_usd = native_balance * eth_usd_fallback if eth_usd_fallback > 0 else None
    return {
        "data_source": "etherscan",
        "native_balance": native_balance,
        "portfolio_est_usd": portfolio_est_usd,
        "portfolio_top_assets": [],
    }


def _profile_from_rpc(address: str, rpc_url: str, timeout_sec: float, eth_usd_fallback: float) -> dict[str, Any] | None:
    if not rpc_url:
        return None
    payload = _http_post_json(
        rpc_url,
        {
            "jsonrpc": "2.0",
            "method": "eth_getBalance",
            "params": [address, "latest"],
            "id": 1,
        },
        headers={"Content-Type": "application/json"},
        timeout=timeout_sec,
    )
    hex_wei = str((payload or {}).get("result") or "0x0")
    native_balance = int(hex_wei, 16) / 1e18
    portfolio_est_usd = native_balance * eth_usd_fallback if eth_usd_fallback > 0 else None
    return {
        "data_source": "rpc",
        "native_balance": native_balance,
        "portfolio_est_usd": portfolio_est_usd,
        "portfolio_top_assets": [],
    }


def build_profile_for_address(
    address: str,
    *,
    debank_api_key: str,
    etherscan_api_key: str,
    rpc_url: str,
    timeout_sec: float,
    eth_usd_fallback: float,
) -> ProfileResult:
    errors: list[str] = []
    base: dict[str, Any] = {
        "wallet_address": address,
        "profiled_at_utc": now_iso(),
        "profile_version": "phase4.1-v1",
    }

    profile: dict[str, Any] | None = None
    for provider_name, fn in (
        ("debank", lambda: _profile_from_debank(address, debank_api_key, timeout_sec)),
        ("etherscan", lambda: _profile_from_etherscan(address, etherscan_api_key, timeout_sec, eth_usd_fallback)),
        ("rpc", lambda: _profile_from_rpc(address, rpc_url, timeout_sec, eth_usd_fallback)),
    ):
        try:
            candidate = fn()
            if candidate is not None:
                profile = candidate
                break
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{provider_name}:{exc}")

    if profile is None:
        profile = {
            "data_source": "unavailable",
            "native_balance": None,
            "portfolio_est_usd": None,
            "portfolio_top_assets": [],
        }

    native_balance = _safe_float(profile.get("native_balance"), None)
    portfolio_est_usd = _safe_float(profile.get("portfolio_est_usd"), None)
    whale_tier = _tier_from_usd(portfolio_est_usd, native_balance)
    if whale_tier not in TIER_LABELS:
        whale_tier = "Plankton"

    base.update(profile)
    if errors:
        base["provider_errors"] = errors[:8]

    return ProfileResult(wallet_address=address, whale_tier=whale_tier, profile_payload=base)


def _is_unprofiled(meta: Any, force_refresh: bool) -> bool:
    if force_refresh:
        return True
    if not isinstance(meta, dict):
        return True
    entity_profile = meta.get("entity_profile")
    if not isinstance(entity_profile, dict):
        return True
    profiled_at = str(entity_profile.get("profiled_at_utc") or "").strip()
    return not profiled_at


def create_sb_client() -> Client | None:
    url = str(os.getenv("SUPABASE_URL") or "").strip()
    key = str(os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        return None
    return create_client(url, key)


def fetch_candidate_rows(client: Client, *, limit: int, lookback_hours: int, address: str | None) -> list[dict[str, Any]]:
    query = client.table("user_access_logs").select("id,wallet_address,meta,whale_tier,created_at").order("created_at", desc=True).limit(limit)
    if address:
        query = query.eq("wallet_address", address)
    else:
        since = (now_utc() - timedelta(hours=max(1, lookback_hours))).isoformat()
        query = query.gte("created_at", since)
    resp = query.execute()
    data = getattr(resp, "data", None)
    return data if isinstance(data, list) else []


def update_address_profile(client: Client, wallet_address: str, whale_tier: str, profile_payload: dict[str, Any], dry_run: bool = False) -> bool:
    existing_meta: dict[str, Any] = {}
    read_resp = client.table("user_access_logs").select("meta").eq("wallet_address", wallet_address).order("created_at", desc=True).limit(1).execute()
    rows = getattr(read_resp, "data", None)
    if isinstance(rows, list) and rows and isinstance(rows[0], dict) and isinstance(rows[0].get("meta"), dict):
        existing_meta = dict(rows[0]["meta"])

    merged_meta = dict(existing_meta)
    merged_meta["entity_profile"] = profile_payload
    merged_meta["profiled_at_utc"] = now_iso()

    if dry_run:
        return True

    resp = (
        client.table("user_access_logs")
        .update({"meta": merged_meta, "whale_tier": whale_tier})
        .eq("wallet_address", wallet_address)
        .execute()
    )
    err = getattr(resp, "error", None)
    return err is None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile wallet entities from user_access_logs and assign whale tiers.")
    parser.add_argument("--limit", type=int, default=200, help="Max logs to scan.")
    parser.add_argument("--lookback-hours", type=int, default=72, help="Lookback window if --address is not set.")
    parser.add_argument("--address", type=str, default="", help="Single address override.")
    parser.add_argument("--dry-run", action="store_true", help="Do not persist updates.")
    parser.add_argument("--force-refresh", action="store_true", help="Refresh profiles even if meta already exists.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = create_sb_client()
    if client is None:
        _json_log("ENTITY_PROFILER_SKIPPED", reason="supabase_service_role_missing")
        return 0

    debank_api_key = str(os.getenv("DEBANK_API_KEY") or "").strip()
    etherscan_api_key = str(os.getenv("ETHERSCAN_API_KEY") or "").strip()
    rpc_url = str(os.getenv("RPC_URL_ETH") or "https://cloudflare-eth.com").strip()
    timeout_sec = float(os.getenv("ENTITY_PROFILER_TIMEOUT_SEC") or "12")
    eth_usd_fallback = float(os.getenv("ENTITY_ETH_USD_FALLBACK") or "3000")

    address_override = _canonical_wallet(args.address)
    try:
        rows = fetch_candidate_rows(
            client,
            limit=max(1, args.limit),
            lookback_hours=max(1, args.lookback_hours),
            address=address_override or None,
        )
    except Exception as exc:  # noqa: BLE001
        _json_log("ENTITY_PROFILER_FAILED", error=str(exc))
        return 0

    unique_candidates: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        wallet = _canonical_wallet(row.get("wallet_address") or "")
        if not wallet:
            continue
        if wallet not in unique_candidates:
            unique_candidates[wallet] = row

    profiled = 0
    skipped = 0
    failed = 0
    for wallet, row in unique_candidates.items():
        if not _is_unprofiled(row.get("meta"), args.force_refresh):
            skipped += 1
            continue
        try:
            result = build_profile_for_address(
                wallet,
                debank_api_key=debank_api_key,
                etherscan_api_key=etherscan_api_key,
                rpc_url=rpc_url,
                timeout_sec=timeout_sec,
                eth_usd_fallback=eth_usd_fallback,
            )
            ok = update_address_profile(
                client,
                wallet_address=result.wallet_address,
                whale_tier=result.whale_tier,
                profile_payload=result.profile_payload,
                dry_run=args.dry_run,
            )
            if ok:
                profiled += 1
                _json_log(
                    "ENTITY_PROFILED",
                    wallet_address=result.wallet_address,
                    whale_tier=result.whale_tier,
                    source=result.profile_payload.get("data_source"),
                    portfolio_est_usd=result.profile_payload.get("portfolio_est_usd"),
                    dry_run=bool(args.dry_run),
                )
            else:
                failed += 1
                _json_log("ENTITY_PROFILE_UPDATE_FAILED", wallet_address=wallet)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            _json_log("ENTITY_PROFILE_EXCEPTION", wallet_address=wallet, error=str(exc))
        time.sleep(0.08)

    _json_log(
        "ENTITY_PROFILER_DONE",
        scanned=len(rows),
        unique_addresses=len(unique_candidates),
        profiled=profiled,
        skipped=skipped,
        failed=failed,
        dry_run=bool(args.dry_run),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
