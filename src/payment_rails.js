const ALLOWED_CHAINS = ["tron", "arbitrum", "ethereum"];
const ALLOWED_ASSETS = ["usdt", "usdc"];
const ALLOWED_PAIRS = new Set([
  "tron:usdt",
  "arbitrum:usdc",
  "ethereum:usdt",
  "ethereum:usdc",
]);

const DEFAULT_RECIPIENTS = {
  TRON_USDT_RECIPIENT: "TUmegztKiXNjhmifi7wJ8SdMkowY2s7Avw",
  ETH_L1_ERC20_RECIPIENT: "0xc8Fdb8A3D531C47d4d3C4C252c09A26176323809",
  L2_USDC_RECIPIENT: "0x1E90d2675915F4510eEEb6Bb9eecEECC2E320179",
};

function readEnv(name, fallbackValue) {
  const raw = process.env[name];
  if (raw === undefined || raw === null) {
    return fallbackValue;
  }
  const trimmed = String(raw).trim();
  return trimmed === "" ? fallbackValue : trimmed;
}

function normalizePaymentChain(value) {
  if (value === undefined || value === null || value === "") {
    return null;
  }
  const normalized = String(value).trim().toLowerCase();
  return ALLOWED_CHAINS.includes(normalized) ? normalized : null;
}

function normalizePaymentAsset(value) {
  if (value === undefined || value === null || value === "") {
    return null;
  }
  const normalized = String(value).trim().toLowerCase();
  return ALLOWED_ASSETS.includes(normalized) ? normalized : null;
}

function isAllowedChainAssetPair(chain, asset) {
  const normalizedChain = normalizePaymentChain(chain);
  const normalizedAsset = normalizePaymentAsset(asset);
  if (!normalizedChain || !normalizedAsset) {
    return false;
  }
  return ALLOWED_PAIRS.has(`${normalizedChain}:${normalizedAsset}`);
}

function getL2Network() {
  const raw = normalizePaymentChain(readEnv("L2_NETWORK", "arbitrum"));
  return raw === "arbitrum" ? raw : "arbitrum";
}

function getPaymentRailsMap() {
  const l2Network = getL2Network();
  const map = {
    "USDT-TRON": {
      rail_key: "USDT-TRON",
      chain: "tron",
      chain_kind: "TRON",
      chain_profile: "TRON",
      default_asset: "usdt",
      supported_assets: ["usdt"],
      recipient_address: readEnv(
        "TRON_USDT_RECIPIENT",
        DEFAULT_RECIPIENTS.TRON_USDT_RECIPIENT
      ),
    },
    "USDC-L2": {
      rail_key: "USDC-L2",
      chain: l2Network,
      chain_kind: "EVM",
      chain_profile: "L2",
      default_asset: "usdc",
      supported_assets: ["usdc"],
      recipient_address: readEnv(
        "L2_USDC_RECIPIENT",
        DEFAULT_RECIPIENTS.L2_USDC_RECIPIENT
      ),
    },
    ERC20: {
      rail_key: "ERC20",
      chain: "ethereum",
      chain_kind: "EVM",
      chain_profile: "ERC20",
      default_asset: "usdt",
      supported_assets: ["usdt", "usdc"],
      recipient_address: readEnv(
        "ETH_L1_ERC20_RECIPIENT",
        DEFAULT_RECIPIENTS.ETH_L1_ERC20_RECIPIENT
      ),
    },
  };

  for (const entry of Object.values(map)) {
    if (!isAllowedChainAssetPair(entry.chain, entry.default_asset)) {
      throw new Error(
        `Invalid payment rail default pair: ${entry.chain}:${entry.default_asset}`
      );
    }
  }

  return map;
}

function getPaymentRailKeys() {
  return Object.keys(getPaymentRailsMap());
}

function isValidPaymentRail(railKey) {
  const map = getPaymentRailsMap();
  return Object.prototype.hasOwnProperty.call(map, railKey);
}

function resolveOrderRail({ railKey, paymentAsset }) {
  const map = getPaymentRailsMap();
  const rail = map[railKey];
  if (!rail) {
    throw new Error(`Unsupported payment rail: ${railKey}`);
  }

  const normalizedAsset = normalizePaymentAsset(
    paymentAsset === undefined || paymentAsset === null || paymentAsset === ""
      ? rail.default_asset
      : paymentAsset
  );
  if (!normalizedAsset) {
    throw new Error(`Unsupported payment asset: ${paymentAsset}`);
  }
  if (!rail.supported_assets.includes(normalizedAsset)) {
    throw new Error(
      `Unsupported payment asset for rail ${railKey}: ${normalizedAsset}`
    );
  }
  if (!isAllowedChainAssetPair(rail.chain, normalizedAsset)) {
    throw new Error(`Unsupported chain/asset pair: ${rail.chain}/${normalizedAsset}`);
  }

  return {
    ...rail,
    payment_asset: normalizedAsset,
  };
}

function getPublicRails() {
  const map = getPaymentRailsMap();
  return Object.values(map).map((entry) => ({
    rail_key: entry.rail_key,
    chain: entry.chain,
    supported_assets: [...entry.supported_assets],
    recipient_address: entry.recipient_address,
  }));
}

module.exports = {
  ALLOWED_ASSETS,
  ALLOWED_CHAINS,
  getPaymentRailKeys,
  getPaymentRailsMap,
  getPublicRails,
  isAllowedChainAssetPair,
  isValidPaymentRail,
  normalizePaymentAsset,
  normalizePaymentChain,
  resolveOrderRail,
};
