const REQUIRED_CONFIRMATIONS = {
  TRON: 20,
  L2: 12,
  ERC20: 12,
};

function getRequiredConfirmations(chainProfile) {
  return REQUIRED_CONFIRMATIONS[chainProfile] ?? null;
}

function isConfirmationSufficient(chainProfile, currentConfirmations) {
  const required = getRequiredConfirmations(chainProfile);
  if (required === null) {
    return false;
  }
  return Number(currentConfirmations) >= required;
}

module.exports = {
  REQUIRED_CONFIRMATIONS,
  getRequiredConfirmations,
  isConfirmationSufficient,
};
