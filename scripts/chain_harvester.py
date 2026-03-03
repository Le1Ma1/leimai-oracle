from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from supabase import Client, create_client
from dotenv import load_dotenv


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def jlog(event: str, **kwargs: Any) -> None:
    payload: dict[str, Any] = {"ts_utc": now_iso(), "event": event}
    payload.update(kwargs)
    print(json.dumps(payload, ensure_ascii=False))


def to_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw <= 0:
            return None
        # Unix seconds or milliseconds
        ts = raw / 1000.0 if raw > 1e12 else raw
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def as_iso(value: Any) -> str | None:
    dt = to_dt(value)
    return dt.isoformat() if dt else None


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if out.is_nan() or out.is_infinite():
        return None
    return out


def merge_meta(existing: Any, patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(existing) if isinstance(existing, dict) else {}
    out.update(patch)
    return out


@dataclass(frozen=True)
class Config:
    supabase_url: str
    supabase_service_role_key: str
    support_trc20_address: str
    tronscan_base: str
    trongrid_base: str
    trongrid_api_key: str
    fetch_limit: int
    timeout_sec: float
    retries: int
    lookback_min: int
    amount_tolerance: Decimal
    dry_run: bool
    min_confirmations: int
    alchemy_api_key: str
    eth_l1_erc20_recipient: str
    l2_network: str
    l2_usdc_recipient: str


def build_config(args: argparse.Namespace) -> Config:
    load_dotenv()
    return Config(
        supabase_url=str(os.getenv("SUPABASE_URL") or "").strip(),
        supabase_service_role_key=str(os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip(),
        support_trc20_address=str(
            os.getenv("SUPPORT_TRC20_ADDRESS") or "TUmegztKiXNjhmifi7wJ8SdMkowY2s7Avw"
        ).strip(),
        tronscan_base=str(
            os.getenv("SUPPORT_TRONSCAN_API_BASE") or "https://apilist.tronscanapi.com"
        ).strip().rstrip("/"),
        trongrid_base=str(
            os.getenv("SUPPORT_TRONGRID_API_BASE") or "https://api.trongrid.io"
        ).strip().rstrip("/"),
        trongrid_api_key=str(os.getenv("SUPPORT_TRONGRID_API_KEY") or "").strip(),
        fetch_limit=max(50, int(os.getenv("SUPPORT_FETCH_LIMIT") or "200")),
        timeout_sec=max(3.0, float(os.getenv("CHAIN_HARVEST_TIMEOUT_SEC") or "12")),
        retries=max(1, int(os.getenv("CHAIN_HARVEST_RETRIES") or "3")),
        lookback_min=max(5, int(args.lookback_min)),
        amount_tolerance=to_decimal(os.getenv("CHAIN_HARVEST_AMOUNT_TOL") or "0.000001") or Decimal("0.000001"),
        dry_run=bool(args.dry_run),
        min_confirmations=max(0, int(os.getenv("SUPPORT_MIN_CONFIRMATIONS") or "15")),
        alchemy_api_key=str(os.getenv("ALCHEMY_API_KEY") or "").strip(),
        eth_l1_erc20_recipient=str(
            os.getenv("ETH_L1_ERC20_RECIPIENT") or "0xc8Fdb8A3D531C47d4d3C4C252c09A26176323809"
        ).strip(),
        l2_network=str(os.getenv("L2_NETWORK") or "arbitrum").strip().lower(),
        l2_usdc_recipient=str(
            os.getenv("L2_USDC_RECIPIENT") or "0x1E90d2675915F4510eEEb6Bb9eecEECC2E320179"
        ).strip(),
    )


def fetch_json(
    url: str,
    *,
    headers: dict[str, str] | None,
    timeout_sec: float,
    retries: int,
    params: dict[str, Any] | None = None,
) -> Any:
    last_err: Exception | None = None
    for i in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=timeout_sec)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if i < retries:
                time.sleep(min(2.0, 0.35 * i))
            continue
    raise RuntimeError(str(last_err or "unknown_fetch_error"))


def fetch_json_post(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None,
    timeout_sec: float,
    retries: int,
) -> Any:
    last_err: Exception | None = None
    for i in range(1, retries + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout_sec)
            resp.raise_for_status()
            body = resp.json()
            if isinstance(body, dict) and body.get("error"):
                raise RuntimeError(str(body.get("error")))
            return body
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if i < retries:
                time.sleep(min(2.0, 0.35 * i))
            continue
    raise RuntimeError(str(last_err or "unknown_fetch_error"))


def normalize_addr(addr: Any) -> str:
    return str(addr or "").strip()


def is_evm_address(addr: str) -> bool:
    text = normalize_addr(addr)
    return text.startswith("0x") and len(text) == 42


def address_matches(a: Any, b: Any) -> bool:
    aa = normalize_addr(a)
    bb = normalize_addr(b)
    if not aa or not bb:
        return False
    if is_evm_address(aa) or is_evm_address(bb):
        return aa.lower() == bb.lower()
    return aa == bb


def normalize_tronscan_row(row: dict[str, Any], support_address: str) -> dict[str, Any] | None:
    token = str(
        row.get("tokenAbbr")
        or row.get("tokenName")
        or row.get("tokenSymbol")
        or row.get("symbol")
        or ""
    ).upper()
    if token != "USDT":
        return None
    tx_hash = str(row.get("transaction_id") or row.get("hash") or row.get("txID") or "").lower().strip()
    to_addr = str(row.get("to_address") or row.get("to") or row.get("toAddress") or "").strip()
    from_addr = str(row.get("from_address") or row.get("from") or row.get("ownerAddress") or "").strip()
    if not tx_hash or not to_addr or to_addr != support_address:
        return None

    decimals = int(row.get("tokenDecimal") or row.get("decimals") or 6)
    raw_amt = to_decimal(row.get("quant") or row.get("amount_str") or row.get("amount"))
    if raw_amt is None:
        return None
    amount = raw_amt / (Decimal(10) ** decimals)
    if amount <= 0:
        return None

    confirmed = row.get("confirmed")
    confirmations = int(row.get("confirmations") or (20 if confirmed is not False else 0))
    return {
        "tx_hash": tx_hash,
        "to_addr": to_addr,
        "from_addr": from_addr,
        "amount": amount,
        "confirmed_at_utc": as_iso(row.get("block_ts") or row.get("timestamp") or row.get("block_timestamp")),
        "confirmations": confirmations,
        "status": "verified" if confirmed is not False else "pending",
        "source": "tronscan",
    }


def normalize_trongrid_row(row: dict[str, Any], support_address: str) -> dict[str, Any] | None:
    token = str(
        (row.get("token_info") or {}).get("symbol")
        or (row.get("token_info") or {}).get("name")
        or row.get("tokenName")
        or row.get("token_symbol")
        or ""
    ).upper()
    if token != "USDT":
        return None
    tx_hash = str(row.get("transaction_id") or row.get("txID") or row.get("hash") or "").lower().strip()
    to_addr = str(row.get("to") or row.get("to_address") or "").strip()
    from_addr = str(row.get("from") or row.get("from_address") or "").strip()
    if not tx_hash or not to_addr or to_addr != support_address:
        return None

    decimals = int((row.get("token_info") or {}).get("decimals") or row.get("decimals") or 6)
    raw_amt = to_decimal(row.get("value") or row.get("amount"))
    if raw_amt is None:
        return None
    amount = raw_amt / (Decimal(10) ** decimals)
    if amount <= 0:
        return None

    confirmed = row.get("confirmed")
    confirmations = int(row.get("confirmations") or (20 if confirmed is not False else 0))
    return {
        "tx_hash": tx_hash,
        "to_addr": to_addr,
        "from_addr": from_addr,
        "amount": amount,
        "confirmed_at_utc": as_iso(row.get("block_timestamp") or row.get("timestamp")),
        "confirmations": confirmations,
        "status": "verified" if confirmed is not False else "pending",
        "source": "trongrid",
    }


def alchemy_endpoint(network: str, api_key: str) -> str | None:
    net = string_or_empty(network).lower()
    if not api_key:
        return None
    mapping = {
        "eth": "eth-mainnet",
        "ethereum": "eth-mainnet",
        "mainnet": "eth-mainnet",
        "arbitrum": "arb-mainnet",
        "arb": "arb-mainnet",
    }
    target = mapping.get(net)
    if not target:
        return None
    return f"https://{target}.g.alchemy.com/v2/{api_key}"


def string_or_empty(value: Any) -> str:
    return str(value or "").strip()


def normalize_alchemy_transfer(
    row: dict[str, Any],
    *,
    recipient: str,
    source: str,
) -> dict[str, Any] | None:
    tx_hash = string_or_empty(row.get("hash")).lower()
    to_addr = string_or_empty(row.get("to"))
    from_addr = string_or_empty(row.get("from"))
    if not tx_hash or not to_addr or not address_matches(to_addr, recipient):
        return None
    amount = to_decimal(row.get("value"))
    if amount is None or amount <= 0:
        return None
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    ts = as_iso(metadata.get("blockTimestamp") or row.get("blockTimestamp"))
    if not ts:
        return None
    return {
        "tx_hash": tx_hash,
        "to_addr": to_addr,
        "from_addr": from_addr,
        "amount": amount,
        "confirmed_at_utc": ts,
        "confirmations": 32,
        "status": "verified",
        "source": source,
    }


def fetch_alchemy_transfers(
    *,
    network: str,
    recipient: str,
    contract_address: str,
    source: str,
    cfg: Config,
) -> list[dict[str, Any]]:
    endpoint = alchemy_endpoint(network, cfg.alchemy_api_key)
    if not endpoint or not recipient:
        return []
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "alchemy_getAssetTransfers",
        "params": [
            {
                "fromBlock": "0x0",
                "toAddress": recipient,
                "category": ["erc20"],
                "contractAddresses": [contract_address],
                "excludeZeroValue": True,
                "withMetadata": True,
                "maxCount": "0x3e8",
                "order": "desc",
            }
        ],
    }
    body = fetch_json_post(
        endpoint,
        payload,
        headers={"Content-Type": "application/json"},
        timeout_sec=cfg.timeout_sec,
        retries=cfg.retries,
    )
    result = body.get("result") if isinstance(body, dict) else {}
    rows = result.get("transfers") if isinstance(result, dict) else []
    if not isinstance(rows, list):
        rows = []
    return [
        normalized
        for normalized in (
            normalize_alchemy_transfer(row, recipient=recipient, source=source)
            for row in rows
            if isinstance(row, dict)
        )
        if normalized is not None
    ]


def merge_transfers(a_rows: list[dict[str, Any]], b_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in [*a_rows, *b_rows]:
        tx_hash = str(row.get("tx_hash") or "").strip().lower()
        if not tx_hash:
            continue
        prev = merged.get(tx_hash)
        if prev is None:
            merged[tx_hash] = row
            continue
        merged[tx_hash] = {
            **prev,
            "confirmations": max(int(prev.get("confirmations") or 0), int(row.get("confirmations") or 0)),
            "confirmed_at_utc": prev.get("confirmed_at_utc") or row.get("confirmed_at_utc"),
            "amount": prev.get("amount") if to_decimal(prev.get("amount")) and to_decimal(prev.get("amount")) > 0 else row.get("amount"),
            "source": prev.get("source") if prev.get("source") == row.get("source") else "dual",
            "status": "verified" if prev.get("status") == "verified" or row.get("status") == "verified" else "pending",
        }
    return list(merged.values())


def fetch_recent_transfers(cfg: Config) -> list[dict[str, Any]]:
    tronscan: list[dict[str, Any]] = []
    trongrid: list[dict[str, Any]] = []
    eth_l1_rows: list[dict[str, Any]] = []
    l2_rows: list[dict[str, Any]] = []

    try:
        payload = fetch_json(
            f"{cfg.tronscan_base}/api/token_trc20/transfers",
            headers=None,
            timeout_sec=cfg.timeout_sec,
            retries=cfg.retries,
            params={
                "toAddress": cfg.support_trc20_address,
                "limit": cfg.fetch_limit,
                "start": 0,
                "sort": "-timestamp",
            },
        )
        rows = []
        if isinstance(payload, dict):
            rows.extend(payload.get("token_transfers") or [])
            rows.extend(payload.get("data") or [])
            rows.extend(payload.get("trc20_transfers") or [])
        tronscan = [
            normalized
            for normalized in (
                normalize_tronscan_row(row, cfg.support_trc20_address)
                for row in rows
                if isinstance(row, dict)
            )
            if normalized is not None
        ]
        jlog("HARVEST_FETCH_OK", source="tronscan", count=len(tronscan))
    except Exception as exc:  # noqa: BLE001
        jlog("HARVEST_FETCH_ERROR", source="tronscan", error=str(exc))

    try:
        headers: dict[str, str] = {}
        if cfg.trongrid_api_key:
            headers["TRON-PRO-API-KEY"] = cfg.trongrid_api_key
        payload = fetch_json(
            f"{cfg.trongrid_base}/v1/accounts/{cfg.support_trc20_address}/transactions/trc20",
            headers=headers,
            timeout_sec=cfg.timeout_sec,
            retries=cfg.retries,
            params={
                "limit": cfg.fetch_limit,
                "only_confirmed": "true",
                "order_by": "block_timestamp,desc",
            },
        )
        rows = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            rows = []
        trongrid = [
            normalized
            for normalized in (
                normalize_trongrid_row(row, cfg.support_trc20_address)
                for row in rows
                if isinstance(row, dict)
            )
            if normalized is not None
        ]
        jlog("HARVEST_FETCH_OK", source="trongrid", count=len(trongrid))
    except Exception as exc:  # noqa: BLE001
        jlog("HARVEST_FETCH_ERROR", source="trongrid", error=str(exc))

    if cfg.alchemy_api_key and cfg.eth_l1_erc20_recipient:
        try:
            eth_l1_rows = fetch_alchemy_transfers(
                network="ethereum",
                recipient=cfg.eth_l1_erc20_recipient,
                contract_address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
                source="alchemy_eth_usdt",
                cfg=cfg,
            )
            jlog("HARVEST_FETCH_OK", source="alchemy_eth_usdt", count=len(eth_l1_rows))
        except Exception as exc:  # noqa: BLE001
            jlog("HARVEST_FETCH_ERROR", source="alchemy_eth_usdt", error=str(exc))

    if cfg.alchemy_api_key and cfg.l2_usdc_recipient:
        try:
            l2_rows = fetch_alchemy_transfers(
                network=cfg.l2_network or "arbitrum",
                recipient=cfg.l2_usdc_recipient,
                contract_address="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
                source=f"alchemy_{cfg.l2_network}_usdc",
                cfg=cfg,
            )
            jlog("HARVEST_FETCH_OK", source=f"alchemy_{cfg.l2_network}_usdc", count=len(l2_rows))
        except Exception as exc:  # noqa: BLE001
            jlog("HARVEST_FETCH_ERROR", source=f"alchemy_{cfg.l2_network}_usdc", error=str(exc))

    merged = merge_transfers(merge_transfers(tronscan, trongrid), merge_transfers(eth_l1_rows, l2_rows))
    cutoff = now_utc() - timedelta(minutes=cfg.lookback_min)
    filtered: list[dict[str, Any]] = []
    for row in merged:
        if int(row.get("confirmations") or 0) < cfg.min_confirmations:
            continue
        ts = to_dt(row.get("confirmed_at_utc"))
        if not ts:
            continue
        if ts < cutoff:
            continue
        amt = to_decimal(row.get("amount"))
        if amt is None or amt <= 0:
            continue
        row["amount"] = amt
        filtered.append(row)

    filtered.sort(key=lambda x: to_dt(x.get("confirmed_at_utc")) or now_utc())
    jlog("HARVEST_RECENT_WINDOW", lookback_min=cfg.lookback_min, recent_transfers=len(filtered))
    return filtered


def create_supabase_client(cfg: Config) -> Client | None:
    if not cfg.supabase_url or not cfg.supabase_service_role_key:
        return None
    return create_client(cfg.supabase_url, cfg.supabase_service_role_key)


def fetch_pending_invoices(client: Client) -> list[dict[str, Any]]:
    resp = (
        client.table("payment_invoices")
        .select(
            "invoice_id,wallet_address,slug,plan_code,amount_usdt,pay_to_address,status,expires_at_utc,created_at,updated_at,meta"
        )
        .eq("status", "pending")
        .order("created_at", desc=False)
        .limit(1000)
        .execute()
    )
    data = getattr(resp, "data", None)
    return data if isinstance(data, list) else []


def fetch_paid_tx_hashes(client: Client) -> set[str]:
    resp = (
        client.table("payment_invoices")
        .select("invoice_id,meta,updated_at")
        .eq("status", "paid")
        .order("updated_at", desc=True)
        .limit(5000)
        .execute()
    )
    data = getattr(resp, "data", None)
    if not isinstance(data, list):
        return set()
    hashes: set[str] = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        meta = row.get("meta")
        if isinstance(meta, dict):
            tx_hash = str(meta.get("paid_tx_hash") or "").strip().lower()
            if tx_hash:
                hashes.add(tx_hash)
    return hashes


def mark_invoice_expired(client: Client, invoice: dict[str, Any], *, dry_run: bool) -> bool:
    invoice_id = str(invoice.get("invoice_id") or "").strip()
    if not invoice_id:
        return False
    expires_at = as_iso(invoice.get("expires_at_utc"))
    meta = merge_meta(
        invoice.get("meta"),
        {
            "expired_by": "chain_harvester",
            "expired_marked_at_utc": now_iso(),
            "expired_at_utc": expires_at,
        },
    )
    if dry_run:
        jlog("HARVEST_EXPIRED_DRYRUN", invoice_id=invoice_id, expires_at_utc=expires_at)
        return True
    resp = (
        client.table("payment_invoices")
        .update({"status": "expired", "meta": meta})
        .eq("invoice_id", invoice_id)
        .eq("status", "pending")
        .execute()
    )
    err = getattr(resp, "error", None)
    if err:
        jlog("HARVEST_EXPIRED_ERROR", invoice_id=invoice_id, error=str(err))
        return False
    jlog("HARVEST_EXPIRED", invoice_id=invoice_id)
    return True


def promote_wallet_premium(
    client: Client,
    *,
    wallet_address: str,
    invoice: dict[str, Any],
    paid_at_utc: str,
    dry_run: bool,
) -> None:
    wallet = str(wallet_address or "").strip()
    if not wallet:
        return
    patch = {
        "access_label": "Premium_Entity",
        "premium_source": "invoice_paid",
        "premium_invoice_id": str(invoice.get("invoice_id") or ""),
        "premium_paid_at_utc": paid_at_utc,
        "premium_plan_code": str(invoice.get("plan_code") or ""),
    }
    resp = (
        client.table("user_access_logs")
        .select("id,meta")
        .eq("wallet_address", wallet)
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )
    rows = getattr(resp, "data", None)
    if not isinstance(rows, list):
        rows = []

    if not rows:
        if dry_run:
            jlog("PREMIUM_LOG_INSERT_DRYRUN", wallet_address=wallet)
            return
        ins = (
            client.table("user_access_logs")
            .insert(
                {
                    "wallet_address": wallet,
                    "slug": str(invoice.get("slug") or "vault"),
                    "signed_at_utc": now_iso(),
                    "source": "payment_settlement",
                    "meta": patch,
                }
            )
            .execute()
        )
        if getattr(ins, "error", None):
            jlog("PREMIUM_LOG_INSERT_ERROR", wallet_address=wallet, error=str(getattr(ins, "error", None)))
        else:
            jlog("PREMIUM_LOG_INSERTED", wallet_address=wallet)
        return

    for row in rows:
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        if rid is None:
            continue
        merged = merge_meta(row.get("meta"), patch)
        if dry_run:
            jlog("PREMIUM_LOG_UPDATE_DRYRUN", wallet_address=wallet, row_id=rid)
            continue
        upd = (
            client.table("user_access_logs")
            .update({"meta": merged})
            .eq("id", rid)
            .execute()
        )
        if getattr(upd, "error", None):
            jlog("PREMIUM_LOG_UPDATE_ERROR", wallet_address=wallet, row_id=rid, error=str(getattr(upd, "error", None)))


def mark_invoice_paid(
    client: Client,
    *,
    invoice: dict[str, Any],
    transfer: dict[str, Any],
    dry_run: bool,
) -> bool:
    invoice_id = str(invoice.get("invoice_id") or "").strip()
    tx_hash = str(transfer.get("tx_hash") or "").strip().lower()
    paid_at_utc = as_iso(transfer.get("confirmed_at_utc")) or now_iso()
    paid_amount = str(transfer.get("amount") or "0")
    meta = merge_meta(
        invoice.get("meta"),
        {
            "paid_tx_hash": tx_hash,
            "paid_at_utc": paid_at_utc,
            "paid_amount_usdt": paid_amount,
            "paid_source": str(transfer.get("source") or "trongrid"),
            "harvested_at_utc": now_iso(),
            "harvested_by": "chain_harvester",
        },
    )
    if dry_run:
        jlog("HARVEST_MATCH_DRYRUN", invoice_id=invoice_id, tx_hash=tx_hash, amount_usdt=paid_amount)
        return True

    resp = (
        client.table("payment_invoices")
        .update({"status": "paid", "meta": meta})
        .eq("invoice_id", invoice_id)
        .eq("status", "pending")
        .execute()
    )
    err = getattr(resp, "error", None)
    if err:
        jlog("HARVEST_MATCH_ERROR", invoice_id=invoice_id, tx_hash=tx_hash, error=str(err))
        return False

    wallet_address = str(invoice.get("wallet_address") or "").strip()
    if wallet_address:
        promote_wallet_premium(
            client,
            wallet_address=wallet_address,
            invoice=invoice,
            paid_at_utc=paid_at_utc,
            dry_run=dry_run,
        )

    jlog(
        "HARVEST_MATCHED",
        invoice_id=invoice_id,
        tx_hash=tx_hash,
        wallet_address=wallet_address,
        amount_usdt=paid_amount,
        paid_at_utc=paid_at_utc,
    )
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 4.2 Sovereign chain payment harvester")
    parser.add_argument("--lookback-min", type=int, default=int(os.getenv("CHAIN_HARVEST_LOOKBACK_MIN") or "20"))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def match_and_settle(
    *,
    cfg: Config,
    client: Client,
    transfers: list[dict[str, Any]],
    pending_invoices: list[dict[str, Any]],
) -> tuple[int, int]:
    paid_count = 0
    expired_count = 0
    now = now_utc()
    paid_tx_hashes = fetch_paid_tx_hashes(client)

    active_invoices: list[dict[str, Any]] = []
    for invoice in pending_invoices:
        if not isinstance(invoice, dict):
            continue
        expires_at = to_dt(invoice.get("expires_at_utc"))
        if expires_at and now > expires_at:
            if mark_invoice_expired(client, invoice, dry_run=cfg.dry_run):
                expired_count += 1
            continue
        active_invoices.append(invoice)

    # FIFO per matching transfer to avoid double-consuming one tx
    for transfer in transfers:
        tx_hash = str(transfer.get("tx_hash") or "").strip().lower()
        if not tx_hash or tx_hash in paid_tx_hashes:
            continue
        transfer_to = str(transfer.get("to_addr") or "").strip()
        transfer_amt = to_decimal(transfer.get("amount"))
        transfer_ts = to_dt(transfer.get("confirmed_at_utc"))
        if transfer_amt is None or transfer_ts is None:
            continue

        best_idx = -1
        best_created: datetime | None = None
        for idx, invoice in enumerate(active_invoices):
            pay_to = str(invoice.get("pay_to_address") or "").strip()
            if not address_matches(pay_to, transfer_to):
                continue
            inv_amt = to_decimal(invoice.get("amount_usdt"))
            if inv_amt is None:
                continue
            if abs(transfer_amt - inv_amt) > cfg.amount_tolerance:
                continue
            created_at = to_dt(invoice.get("created_at"))
            expires_at = to_dt(invoice.get("expires_at_utc"))
            if created_at and transfer_ts < created_at:
                continue
            if expires_at and transfer_ts > expires_at:
                continue
            if best_idx < 0 or (created_at and (best_created is None or created_at < best_created)):
                best_idx = idx
                best_created = created_at

        if best_idx < 0:
            continue
        invoice = active_invoices.pop(best_idx)
        ok = mark_invoice_paid(client, invoice=invoice, transfer=transfer, dry_run=cfg.dry_run)
        if ok:
            paid_count += 1
            paid_tx_hashes.add(tx_hash)

    return paid_count, expired_count


def main() -> int:
    args = parse_args()
    cfg = build_config(args)
    jlog(
        "HARVEST_START",
        lookback_min=cfg.lookback_min,
        dry_run=cfg.dry_run,
        support_trc20_address=cfg.support_trc20_address,
    )
    if not cfg.supabase_url or not cfg.supabase_service_role_key:
        jlog("HARVEST_SKIPPED", reason="supabase_service_role_missing")
        return 0

    client = create_supabase_client(cfg)
    if client is None:
        jlog("HARVEST_SKIPPED", reason="supabase_client_init_failed")
        return 0

    try:
        transfers = fetch_recent_transfers(cfg)
        pending = fetch_pending_invoices(client)
        paid_count, expired_count = match_and_settle(
            cfg=cfg,
            client=client,
            transfers=transfers,
            pending_invoices=pending,
        )
        jlog(
            "HARVEST_DONE",
            pending_invoices=len(pending),
            recent_transfers=len(transfers),
            paid_count=paid_count,
            expired_count=expired_count,
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        jlog("HARVEST_FATAL", error=str(exc))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
