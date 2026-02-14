const {
  MODALITY,
  TIMEFRAMES,
  VARIANTS,
  WINDOWS,
} = require("./constants");

const PAYMENT_RAILS = ["USDT-TRON", "USDC-L2", "ERC20"];
const LOCALES = ["zh-Hant", "en", "zh-Hans"];
const CHANNELS = ["email", "telegram", "webhook"];

function parseVariant(rawValue) {
  if (rawValue === undefined || rawValue === null || rawValue === "") {
    return "long";
  }
  return VARIANTS.includes(rawValue) ? rawValue : null;
}

function parseTf(rawValue) {
  if (rawValue === undefined || rawValue === null || rawValue === "") {
    return "1h";
  }
  return TIMEFRAMES.includes(rawValue) ? rawValue : null;
}

function parseWindow(rawValue) {
  if (rawValue === undefined || rawValue === null || rawValue === "") {
    return "30D";
  }
  return WINDOWS.includes(rawValue) ? rawValue : null;
}

function parseModality(rawValue) {
  if (rawValue === undefined || rawValue === null || rawValue === "") {
    return MODALITY;
  }
  return rawValue === MODALITY ? rawValue : null;
}

function isValidPaymentRail(value) {
  return PAYMENT_RAILS.includes(value);
}

function normalizeLocale(rawValue) {
  if (rawValue === undefined || rawValue === null || rawValue === "") {
    return "zh-Hant";
  }
  return LOCALES.includes(rawValue) ? rawValue : null;
}

function detectLocaleFromPath(pathname) {
  if (pathname === "/en" || pathname.startsWith("/en/")) {
    return "en";
  }
  if (pathname === "/zh-hans" || pathname.startsWith("/zh-hans/")) {
    return "zh-Hans";
  }
  return "zh-Hant";
}

function isValidChannel(channel) {
  return CHANNELS.includes(channel);
}

module.exports = {
  CHANNELS,
  LOCALES,
  PAYMENT_RAILS,
  detectLocaleFromPath,
  isValidChannel,
  isValidPaymentRail,
  normalizeLocale,
  parseModality,
  parseTf,
  parseVariant,
  parseWindow,
};
