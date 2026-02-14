const { VARIANTS } = require("./constants");
const { parseVariant } = require("./validators");
const { chooseBestVariant } = require("./variant");

const TABS = ["risk_adjusted", "roi"];

function parseTab(rawTab) {
  if (!rawTab || rawTab === "") {
    return "risk_adjusted";
  }
  return TABS.includes(rawTab) ? rawTab : "risk_adjusted";
}

function getTabState(rawTab) {
  const activeTab = parseTab(rawTab);
  return {
    active_tab: activeTab,
    secondary_tabs: TABS.filter((tab) => tab !== activeTab),
    available_tabs: [...TABS],
  };
}

function getRankingsUiState({ rawTab, variant, variantSet }) {
  const selected = parseVariant(variant) || "long";
  const bestVariant = chooseBestVariant(variantSet);
  return {
    ...getTabState(rawTab),
    selected_variant: selected,
    default_variant: "long",
    switchable_variants: [...VARIANTS],
    best_variant_badge: bestVariant,
  };
}

module.exports = {
  TABS,
  getRankingsUiState,
  getTabState,
  parseTab,
};
