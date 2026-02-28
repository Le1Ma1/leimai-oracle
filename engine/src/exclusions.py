from __future__ import annotations


STABLECOIN_BASE_ASSETS = {
    "USDT",
    "USDC",
    "BUSD",
    "FDUSD",
    "DAI",
    "TUSD",
    "USDP",
    "USDD",
    "GUSD",
    "EURS",
    "PYUSD",
    "SUSD",
    "LUSD",
    "FRAX",
}

MANUAL_EXCLUDED_BASE_ASSETS = {
    "WBTC",
    "WETH",
    "WBNB",
    "STETH",
    "WSTETH",
    "RENBTC",
    "HBTC",
}

STRICT_STABLE_SYMBOL_PATTERNS = (
    "USD",
    "USDT",
    "USDC",
    "USDE",
    "DAI",
    "FDUSD",
    "TUSD",
    "USDP",
    "PYUSD",
    "FRAX",
    "LUSD",
)

STRICT_STABLE_NAME_PATTERNS = (
    "stable",
    "usd",
    "dollar",
)


def _contains_wrapped_pattern(base_asset: str) -> bool:
    token = base_asset.upper()
    if token.startswith("W") and token not in {"WAVES", "WOO", "WIN"}:
        return True
    return token.startswith("WRAP") or token.endswith("WRAP")


def _contains_leveraged_pattern(base_asset: str) -> bool:
    token = base_asset.upper()
    return token.endswith(("UP", "DOWN", "BULL", "BEAR"))


def _contains_strict_stable_pattern(base_asset: str, coin_name: str | None = None) -> bool:
    token = base_asset.upper()
    if any(pattern in token for pattern in STRICT_STABLE_SYMBOL_PATTERNS):
        return True
    name_token = (coin_name or "").strip().lower()
    if not name_token:
        return False
    return any(pattern in name_token for pattern in STRICT_STABLE_NAME_PATTERNS)


def is_excluded_asset(base_asset: str) -> bool:
    token = base_asset.upper()
    return (
        token in STABLECOIN_BASE_ASSETS
        or token in MANUAL_EXCLUDED_BASE_ASSETS
        or _contains_wrapped_pattern(token)
        or _contains_leveraged_pattern(token)
    )


def is_strict_stable_or_wrapped_asset(base_asset: str, coin_name: str | None = None) -> bool:
    token = base_asset.upper()
    return (
        token in STABLECOIN_BASE_ASSETS
        or token in MANUAL_EXCLUDED_BASE_ASSETS
        or _contains_wrapped_pattern(token)
        or _contains_strict_stable_pattern(token, coin_name=coin_name)
    )
