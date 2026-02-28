from __future__ import annotations

from dataclasses import asdict
from datetime import date
import json
from pathlib import Path

import requests

from .binance_api import fetch_earliest_1m_candle_date
from .config import EngineConfig
from .exclusions import is_excluded_asset, is_strict_stable_or_wrapped_asset
from .types import UniverseAsset

REQUEST_TIMEOUT_SECONDS = 30
COINGECKO_PAGE_SIZE = 250


def _fetch_binance_exchange_info(binance_api_base_url: str, quote_asset: str) -> dict[str, str]:
    url = f"{binance_api_base_url.rstrip('/')}/exchangeInfo"
    response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()
    symbols = payload.get("symbols")
    if not isinstance(symbols, list):
        raise RuntimeError("Binance exchangeInfo malformed.")

    base_to_symbol: dict[str, str] = {}
    for item in symbols:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "TRADING":
            continue
        if not item.get("isSpotTradingAllowed", False):
            continue
        if item.get("quoteAsset") != quote_asset:
            continue
        base_asset = str(item.get("baseAsset", "")).upper()
        symbol = str(item.get("symbol", "")).upper()
        if base_asset and symbol:
            base_to_symbol[base_asset] = symbol
    return base_to_symbol


def _fetch_exchange_info_symbol_map(binance_api_base_url: str, quote_asset: str) -> dict[str, str]:
    url = f"{binance_api_base_url.rstrip('/')}/exchangeInfo"
    response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()
    symbols = payload.get("symbols")
    if not isinstance(symbols, list):
        raise RuntimeError("Binance exchangeInfo malformed.")

    out: dict[str, str] = {}
    for item in symbols:
        if not isinstance(item, dict):
            continue
        if item.get("quoteAsset") != quote_asset:
            continue
        symbol = str(item.get("symbol", "")).upper()
        base_asset = str(item.get("baseAsset", "")).upper()
        if symbol and base_asset:
            out[symbol] = base_asset
    return out


def _fetch_binance_quote_volume(binance_api_base_url: str) -> dict[str, float]:
    url = f"{binance_api_base_url.rstrip('/')}/ticker/24hr"
    response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("Binance ticker/24hr malformed.")

    out: dict[str, float] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).upper()
        quote_volume = row.get("quoteVolume")
        if not symbol:
            continue
        try:
            out[symbol] = float(quote_volume)
        except (TypeError, ValueError):
            continue
    return out


def _fetch_coingecko_market_cap_page(coingecko_api_base_url: str, page: int) -> list[dict[str, object]]:
    url = f"{coingecko_api_base_url.rstrip('/')}/coins/markets"
    response = requests.get(
        url,
        params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": COINGECKO_PAGE_SIZE,
            "page": page,
            "sparkline": "false",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("CoinGecko markets payload malformed.")
    return [row for row in payload if isinstance(row, dict)]


def _resolve_first_seen_date(
    binance_api_base_url: str,
    symbol: str,
    cutoff: date,
) -> date | None:
    first_seen_ts = fetch_earliest_1m_candle_date(
        binance_api_base_url=binance_api_base_url,
        symbol=symbol,
    )
    if first_seen_ts is None:
        return None
    first_seen_date = first_seen_ts.date()
    if first_seen_date > cutoff:
        return None
    return first_seen_date


def _select_by_binance_volume(config: EngineConfig) -> list[UniverseAsset]:
    tradable = _fetch_binance_exchange_info(
        binance_api_base_url=config.binance_api_base_url,
        quote_asset=config.quote_asset,
    )
    quote_volume_by_symbol = _fetch_binance_quote_volume(config.binance_api_base_url)
    cutoff = date(2020, 1, 1)

    ranked_candidates = sorted(
        (
            (base_asset, symbol, quote_volume_by_symbol.get(symbol, 0.0))
            for base_asset, symbol in tradable.items()
        ),
        key=lambda item: item[2],
        reverse=True,
    )

    selected: list[UniverseAsset] = []
    rank_counter = 0
    for base_asset, symbol, quote_volume in ranked_candidates:
        rank_counter += 1
        if len(selected) >= config.top_n:
            break
        if quote_volume <= 0:
            continue
        if is_excluded_asset(base_asset):
            continue

        first_seen_date = _resolve_first_seen_date(
            binance_api_base_url=config.binance_api_base_url,
            symbol=symbol,
            cutoff=cutoff,
        )
        if first_seen_date is None:
            continue

        selected.append(
            UniverseAsset(
                symbol=symbol,
                base_asset=base_asset,
                quote_asset=config.quote_asset,
                rank=rank_counter,
                market_cap=float(quote_volume),
                first_seen_date=first_seen_date,
                source_rank=rank_counter,
                source_market_cap_usd=float(quote_volume),
                eligibility_flags=("spot_trading", "history_before_2020"),
            )
        )

    return selected


def _select_by_coingecko_market_cap(config: EngineConfig) -> list[UniverseAsset]:
    tradable = _fetch_binance_exchange_info(
        binance_api_base_url=config.binance_api_base_url,
        quote_asset=config.quote_asset,
    )
    cutoff = date(2020, 1, 1)
    selected: list[UniverseAsset] = []
    seen_bases: set[str] = set()

    page = 1
    while len(selected) < config.top_n and page <= 8:
        market_rows = _fetch_coingecko_market_cap_page(config.coingecko_api_base_url, page=page)
        if not market_rows:
            break
        for row in market_rows:
            base_asset = str(row.get("symbol", "")).upper().strip()
            coin_name = str(row.get("name", "")).strip()
            if not base_asset or base_asset in seen_bases:
                continue

            if config.universe_strict_stable_filter:
                if is_strict_stable_or_wrapped_asset(base_asset, coin_name=coin_name):
                    continue
            elif is_excluded_asset(base_asset):
                continue

            symbol = tradable.get(base_asset)
            if not symbol:
                continue

            market_cap = row.get("market_cap")
            try:
                market_cap_f = float(market_cap)
            except (TypeError, ValueError):
                continue
            if market_cap_f <= 0:
                continue

            first_seen_date = _resolve_first_seen_date(
                binance_api_base_url=config.binance_api_base_url,
                symbol=symbol,
                cutoff=cutoff,
            )
            if first_seen_date is None:
                continue

            source_rank_raw = row.get("market_cap_rank")
            try:
                source_rank = int(source_rank_raw) if source_rank_raw is not None else None
            except (TypeError, ValueError):
                source_rank = None

            selected.append(
                UniverseAsset(
                    symbol=symbol,
                    base_asset=base_asset,
                    quote_asset=config.quote_asset,
                    rank=len(selected) + 1,
                    market_cap=market_cap_f,
                    first_seen_date=first_seen_date,
                    source_rank=source_rank,
                    source_market_cap_usd=market_cap_f,
                    eligibility_flags=("spot_trading", "history_before_2020", "strict_stable_filtered"),
                )
            )
            seen_bases.add(base_asset)
            if len(selected) >= config.top_n:
                break
        page += 1

    return selected


def _select_by_explicit_symbols(config: EngineConfig) -> list[UniverseAsset]:
    explicit = tuple(symbol.upper() for symbol in config.universe_symbols if symbol.strip())
    if not explicit:
        raise RuntimeError("Explicit symbol selection requested but ENGINE_UNIVERSE_SYMBOLS is empty.")

    symbol_to_base = _fetch_exchange_info_symbol_map(
        binance_api_base_url=config.binance_api_base_url,
        quote_asset=config.quote_asset,
    )
    quote_volume_by_symbol = _fetch_binance_quote_volume(config.binance_api_base_url)
    cutoff = date(2020, 1, 1)
    out: list[UniverseAsset] = []
    seen: set[str] = set()
    for rank, symbol in enumerate(explicit, start=1):
        if symbol in seen:
            continue
        seen.add(symbol)
        base_asset = symbol_to_base.get(symbol)
        if not base_asset and symbol.endswith(config.quote_asset):
            base_asset = symbol[: -len(config.quote_asset)]
        if not base_asset:
            raise RuntimeError(f"Explicit symbol is invalid for quote {config.quote_asset}: {symbol}")

        first_seen_date = _resolve_first_seen_date(
            binance_api_base_url=config.binance_api_base_url,
            symbol=symbol,
            cutoff=cutoff,
        )
        if first_seen_date is None:
            first_seen_date = cutoff

        out.append(
            UniverseAsset(
                symbol=symbol,
                base_asset=base_asset,
                quote_asset=config.quote_asset,
                rank=rank,
                market_cap=float(quote_volume_by_symbol.get(symbol, 0.0)),
                first_seen_date=first_seen_date,
                source_rank=rank,
                source_market_cap_usd=float(quote_volume_by_symbol.get(symbol, 0.0)),
                eligibility_flags=(
                    "explicit_universe_override",
                    "history_before_2020",
                ),
            )
        )
    if len(out) < config.top_n:
        raise RuntimeError(
            f"Explicit universe count ({len(out)}) is smaller than ENGINE_TOP_N ({config.top_n})."
        )
    return out


def select_top15_universe(config: EngineConfig) -> list[UniverseAsset]:
    if config.universe_symbols:
        selected = _select_by_explicit_symbols(config)
        return selected[: config.top_n]
    if config.universe_source.lower() == "binance_volume":
        selected = _select_by_binance_volume(config)
    elif config.universe_source.lower() == "coingecko_market_cap":
        selected = _select_by_coingecko_market_cap(config)
    else:
        raise RuntimeError(f"Unsupported universe source: {config.universe_source}")

    if len(selected) < config.top_n:
        raise RuntimeError(f"Unable to select top {config.top_n} assets after filtering. Got {len(selected)}.")
    return selected


def write_universe_snapshot(assets: list[UniverseAsset], output_dir: Path, asof_date: date) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"top15_{asof_date.isoformat()}.json"
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump([asdict(asset) for asset in assets], fh, ensure_ascii=False, indent=2, default=str)
    return output_path
