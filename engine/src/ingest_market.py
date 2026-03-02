from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from dotenv import load_dotenv

try:
    from supabase import Client, create_client
except Exception:  # noqa: BLE001
    Client = Any  # type: ignore[assignment]
    create_client = None


DEFAULT_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


@dataclass(frozen=True)
class IngestConfig:
    supabase_url: str
    supabase_service_role_key: str
    binance_base_url: str
    symbols: tuple[str, ...]
    range_threshold_pct: float
    oi_drop_threshold_pct: float
    timeout_sec: float
    retries: int


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_event(event: str, **kwargs: Any) -> None:
    payload = {"ts_utc": iso_utc(utc_now()), "event": event, **kwargs}
    print(json.dumps(payload, ensure_ascii=False))


def parse_symbols(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return DEFAULT_SYMBOLS
    parsed = tuple(token.strip().upper() for token in str(raw).split(",") if token.strip())
    return parsed or DEFAULT_SYMBOLS


def parse_float(raw: Any, default: float = 0.0) -> float:
    try:
        out = float(raw)
    except (TypeError, ValueError):
        return default
    if out != out:  # NaN
        return default
    return out


def parse_int(raw: Any, default: int = 0) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def load_config() -> IngestConfig:
    load_dotenv()
    return IngestConfig(
        supabase_url=str(os.getenv("SUPABASE_URL", "")).strip(),
        supabase_service_role_key=str(os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip(),
        binance_base_url=str(os.getenv("BINANCE_FAPI_BASE_URL", "https://fapi.binance.com")).strip().rstrip("/"),
        symbols=parse_symbols(os.getenv("INGEST_SYMBOLS")),
        range_threshold_pct=parse_float(os.getenv("ANOMALY_RANGE_THRESHOLD_PCT"), default=5.0),
        oi_drop_threshold_pct=parse_float(os.getenv("ANOMALY_OI_DROP_THRESHOLD_PCT"), default=3.0),
        timeout_sec=max(3.0, parse_float(os.getenv("BINANCE_HTTP_TIMEOUT_SEC"), default=12.0)),
        retries=max(1, parse_int(os.getenv("BINANCE_HTTP_RETRIES"), default=3)),
    )


def severity_by_ratio(value: float, threshold: float) -> str:
    if threshold <= 0:
        return "medium"
    ratio = value / threshold
    if ratio >= 2.0:
        return "critical"
    if ratio >= 1.6:
        return "high"
    if ratio >= 1.0:
        return "medium"
    return "low"


def hash_text(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def floor_to_4h(dt: datetime) -> datetime:
    base = dt.astimezone(timezone.utc)
    floored_hour = (base.hour // 4) * 4
    return base.replace(hour=floored_hour, minute=0, second=0, microsecond=0)


def request_json(
    session: requests.Session,
    url: str,
    params: dict[str, Any] | None,
    timeout_sec: float,
    retries: int,
) -> tuple[int | None, Any, str | None]:
    last_error: str | None = None
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, params=params, timeout=(3.0, timeout_sec))
            status = response.status_code
            body = response.text
            if status >= 500 or status == 429:
                last_error = f"http_{status}"
                if attempt < retries:
                    time.sleep(min(4.0, 0.8 * attempt))
                    continue
                return status, None, last_error
            if status >= 400:
                trimmed = body[:300] if body else ""
                return status, None, trimmed or f"http_{status}"
            try:
                return status, response.json(), None
            except ValueError:
                return status, None, "json_decode_error"
        except requests.Timeout:
            last_error = "timeout"
        except requests.RequestException as exc:
            last_error = f"request_error:{exc}"
        if attempt < retries:
            time.sleep(min(4.0, 0.8 * attempt))
    return None, None, last_error or "request_failed"


def fetch_klines_4h(
    session: requests.Session,
    cfg: IngestConfig,
    symbol: str,
) -> tuple[list[list[Any]], str | None]:
    url = f"{cfg.binance_base_url}/fapi/v1/klines"
    _, data, err = request_json(
        session=session,
        url=url,
        params={"symbol": symbol, "interval": "4h", "limit": 3},
        timeout_sec=cfg.timeout_sec,
        retries=cfg.retries,
    )
    if err:
        return [], err
    if not isinstance(data, list):
        return [], "invalid_klines_payload"
    out = [row for row in data if isinstance(row, list) and len(row) >= 5]
    return out, None


def compute_range_pct(klines: list[list[Any]]) -> float:
    if not klines:
        return 0.0
    # Prefer the last closed bar (penultimate), fallback to latest.
    row = klines[-2] if len(klines) >= 2 else klines[-1]
    open_px = parse_float(row[1], 0.0)
    high_px = parse_float(row[2], 0.0)
    low_px = parse_float(row[3], 0.0)
    if open_px <= 0:
        return 0.0
    return max(0.0, (high_px - low_px) / open_px * 100.0)


def fetch_open_interest_hist(
    session: requests.Session,
    cfg: IngestConfig,
    symbol: str,
) -> tuple[list[dict[str, Any]], str | None]:
    url = f"{cfg.binance_base_url}/futures/data/openInterestHist"
    _, data, err = request_json(
        session=session,
        url=url,
        params={"symbol": symbol, "period": "5m", "limit": 24},
        timeout_sec=cfg.timeout_sec,
        retries=cfg.retries,
    )
    if err:
        return [], err
    if not isinstance(data, list):
        return [], "invalid_open_interest_payload"
    out = [row for row in data if isinstance(row, dict)]
    return out, None


def compute_open_interest_drop_pct(rows: list[dict[str, Any]]) -> tuple[float, float]:
    values: list[float] = []
    for row in rows:
        raw = row.get("sumOpenInterestValue")
        val = parse_float(raw, 0.0)
        if val <= 0:
            val = parse_float(row.get("sumOpenInterest"), 0.0)
        if val > 0:
            values.append(val)
    if len(values) < 2:
        return 0.0, 0.0
    prev, last = values[-2], values[-1]
    step_drop = ((prev - last) / prev * 100.0) if prev > 0 and last < prev else 0.0
    max_recent = max(values)
    drop_from_peak = ((max_recent - last) / max_recent * 100.0) if max_recent > 0 and last < max_recent else 0.0
    return max(0.0, step_drop), max(0.0, drop_from_peak)


def fetch_force_orders(
    session: requests.Session,
    cfg: IngestConfig,
    symbol: str,
) -> tuple[list[dict[str, Any]], str | None]:
    # Binance may reject this endpoint in some regions / runtimes (401/403).
    url = f"{cfg.binance_base_url}/fapi/v1/forceOrders"
    status, data, err = request_json(
        session=session,
        url=url,
        params={"symbol": symbol, "limit": 50},
        timeout_sec=cfg.timeout_sec,
        retries=cfg.retries,
    )
    if err:
        if status in {401, 403}:
            return [], f"force_orders_unavailable_http_{status}"
        return [], err
    if not isinstance(data, list):
        return [], "invalid_force_orders_payload"
    out = [row for row in data if isinstance(row, dict)]
    return out, None


def parse_force_side(raw: Any) -> str:
    side = str(raw or "").strip().upper()
    if side in {"BUY", "SELL", "LONG", "SHORT"}:
        return side
    return "UNKNOWN"


def build_liquidation_rows(symbol: str, force_orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in force_orders:
        ts_ms = parse_int(item.get("T") or item.get("time"), 0)
        ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc) if ts_ms > 0 else utc_now()
        side = parse_force_side(item.get("S") or item.get("side"))
        qty = parse_float(item.get("q") or item.get("origQty") or item.get("executedQty"), 0.0)
        price = parse_float(item.get("ap") or item.get("p") or item.get("avgPrice") or item.get("price"), 0.0)
        usd_value = abs(qty * price)
        if usd_value <= 0:
            continue
        source_ref = str(item.get("o") or item.get("orderId") or item.get("id") or "")
        hash_id = hash_text(f"{symbol}|{iso_utc(ts)}|{side}|{usd_value:.6f}|{source_ref}")
        rows.append(
            {
                "ts_utc": iso_utc(ts),
                "symbol": symbol,
                "side": side,
                "usd_value": round(usd_value, 6),
                "hash_id": hash_id,
                "source": "binance_force_orders",
                "payload": item,
            }
        )
    return rows


def build_anomaly_row(
    symbol: str,
    event_type: str,
    severity: str,
    payload: dict[str, Any],
    ts: datetime,
) -> dict[str, Any]:
    bucket_4h = iso_utc(floor_to_4h(ts))
    event_id = hash_text(f"{symbol}|{event_type}|{severity}|{bucket_4h}")
    return {
        "event_id": event_id,
        "ts_utc": iso_utc(ts),
        "event_type": event_type,
        "severity": severity,
        "payload": payload,
        "status": "new",
    }


def init_supabase(cfg: IngestConfig) -> Client | None:
    if create_client is None:
        log_event("SUPABASE_SDK_MISSING", package="supabase")
        return None
    if not cfg.supabase_url or not cfg.supabase_service_role_key:
        log_event("SUPABASE_CONFIG_MISSING", has_url=bool(cfg.supabase_url), has_service_role_key=bool(cfg.supabase_service_role_key))
        return None
    try:
        return create_client(cfg.supabase_url, cfg.supabase_service_role_key)
    except Exception as exc:  # noqa: BLE001
        log_event("SUPABASE_INIT_FAILED", error=str(exc))
        return None


def upsert_rows(client: Client, table: str, rows: list[dict[str, Any]], conflict_column: str) -> int:
    if not rows:
        return 0
    try:
        client.table(table).upsert(rows, on_conflict=conflict_column).execute()
        return len(rows)
    except Exception as exc:  # noqa: BLE001
        log_event("SUPABASE_UPSERT_FAILED", table=table, rows=len(rows), error=str(exc))
        return 0


def run_ingest() -> int:
    cfg = load_config()
    log_event(
        "INGEST_START",
        symbols=",".join(cfg.symbols),
        range_threshold_pct=cfg.range_threshold_pct,
        oi_drop_threshold_pct=cfg.oi_drop_threshold_pct,
        base_url=cfg.binance_base_url,
    )

    anomaly_rows: list[dict[str, Any]] = []
    liquidation_rows: list[dict[str, Any]] = []

    session = requests.Session()
    for symbol in cfg.symbols:
        symbol_ts = utc_now()
        try:
            klines, klines_err = fetch_klines_4h(session, cfg, symbol)
            range_pct = compute_range_pct(klines)
            if klines_err:
                log_event("KLINES_FETCH_ERROR", symbol=symbol, error=klines_err)

            oi_rows, oi_err = fetch_open_interest_hist(session, cfg, symbol)
            step_drop_pct, drop_from_peak_pct = compute_open_interest_drop_pct(oi_rows)
            if oi_err:
                log_event("OPEN_INTEREST_FETCH_ERROR", symbol=symbol, error=oi_err)

            if range_pct >= cfg.range_threshold_pct:
                severity = severity_by_ratio(range_pct, cfg.range_threshold_pct)
                anomaly_rows.append(
                    build_anomaly_row(
                        symbol=symbol,
                        event_type="price_range_spike_4h",
                        severity=severity,
                        payload={
                            "symbol": symbol,
                            "range_pct": round(range_pct, 6),
                            "threshold_pct": cfg.range_threshold_pct,
                            "kline_points": len(klines),
                        },
                        ts=symbol_ts,
                    )
                )

            oi_signal = max(step_drop_pct, drop_from_peak_pct)
            if oi_signal >= cfg.oi_drop_threshold_pct:
                severity = severity_by_ratio(oi_signal, cfg.oi_drop_threshold_pct)
                anomaly_rows.append(
                    build_anomaly_row(
                        symbol=symbol,
                        event_type="open_interest_drop",
                        severity=severity,
                        payload={
                            "symbol": symbol,
                            "step_drop_pct": round(step_drop_pct, 6),
                            "drop_from_peak_pct": round(drop_from_peak_pct, 6),
                            "threshold_pct": cfg.oi_drop_threshold_pct,
                            "samples": len(oi_rows),
                        },
                        ts=symbol_ts,
                    )
                )

            force_orders, force_err = fetch_force_orders(session, cfg, symbol)
            if force_err:
                log_event("FORCE_ORDERS_FETCH_NOTE", symbol=symbol, note=force_err)
                anomaly_rows.append(
                    build_anomaly_row(
                        symbol=symbol,
                        event_type="liquidation_feed_unavailable",
                        severity="low",
                        payload={"symbol": symbol, "note": force_err},
                        ts=symbol_ts,
                    )
                )
            liquidation_rows.extend(build_liquidation_rows(symbol, force_orders))

            log_event(
                "SYMBOL_DONE",
                symbol=symbol,
                range_pct=round(range_pct, 6),
                oi_step_drop_pct=round(step_drop_pct, 6),
                oi_drop_from_peak_pct=round(drop_from_peak_pct, 6),
                force_orders=len(force_orders),
            )
        except Exception as exc:  # noqa: BLE001
            log_event("SYMBOL_UNHANDLED_ERROR", symbol=symbol, error=str(exc))

    client = init_supabase(cfg)
    inserted_liq = 0
    inserted_anom = 0
    if client is not None:
        inserted_liq = upsert_rows(client, "market_liquidations", liquidation_rows, "hash_id")
        inserted_anom = upsert_rows(client, "anomaly_events", anomaly_rows, "event_id")
    else:
        log_event("SUPABASE_WRITE_SKIPPED", reason="client_not_available")

    log_event(
        "INGEST_DONE",
        symbols=len(cfg.symbols),
        liquidation_rows=len(liquidation_rows),
        anomaly_rows=len(anomaly_rows),
        liquidations_upserted=inserted_liq,
        anomalies_upserted=inserted_anom,
    )
    return 0


def main() -> int:
    try:
        return run_ingest()
    except Exception as exc:  # noqa: BLE001
        log_event("INGEST_FATAL", error=str(exc))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
