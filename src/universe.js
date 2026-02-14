const { UNIVERSE } = require("./constants");

function getUniverse() {
  return [...UNIVERSE];
}

function isUniverseValid(universeList) {
  if (!Array.isArray(universeList)) {
    return false;
  }
  if (universeList.length < 20 || universeList.length > 30) {
    return false;
  }
  const uniq = new Set(universeList);
  return uniq.size === universeList.length;
}

module.exports = {
  getUniverse,
  isUniverseValid,
};
