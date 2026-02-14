function stripLockedData(value) {
  if (Array.isArray(value)) {
    return value.map(stripLockedData);
  }

  if (value !== null && typeof value === "object") {
    const out = {};
    for (const [key, nested] of Object.entries(value)) {
      if (key === "locked_data") {
        continue;
      }
      out[key] = stripLockedData(nested);
    }
    return out;
  }

  return value;
}

function hasLockedData(value) {
  if (Array.isArray(value)) {
    return value.some(hasLockedData);
  }

  if (value !== null && typeof value === "object") {
    for (const [key, nested] of Object.entries(value)) {
      if (key === "locked_data") {
        return true;
      }
      if (hasLockedData(nested)) {
        return true;
      }
    }
  }

  return false;
}

module.exports = {
  hasLockedData,
  stripLockedData,
};
