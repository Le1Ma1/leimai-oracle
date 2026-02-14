const { createHash } = require("node:crypto");

const REQUIRED_FIELDS = [
  "domain",
  "uri",
  "version",
  "chain_id",
  "nonce",
  "issued_at",
  "expiration_time",
];

function canonicalMessage(message) {
  return REQUIRED_FIELDS.map((field) => `${field}:${String(message[field])}`).join(
    "\n"
  );
}

function signSiweMessage(message, signerId) {
  return createHash("sha256")
    .update(`${canonicalMessage(message)}|${signerId}`, "utf8")
    .digest("hex");
}

class NonceLedger {
  constructor() {
    this.used = new Set();
  }

  consume(nonce) {
    if (this.used.has(nonce)) {
      return false;
    }
    this.used.add(nonce);
    return true;
  }
}

function validateRequiredFields(message) {
  for (const field of REQUIRED_FIELDS) {
    if (!(field in message) || message[field] === undefined || message[field] === null || message[field] === "") {
      return { ok: false, code: "MISSING_FIELD", field };
    }
  }
  return { ok: true };
}

function verifySiweSubmission({
  message,
  signature,
  expectedDomain,
  expectedUri,
  signerId,
  nonceLedger,
  now,
}) {
  const required = validateRequiredFields(message);
  if (!required.ok) {
    return { ok: false, code: "MISSING_FIELD", field: required.field };
  }

  if (message.domain !== expectedDomain || message.uri !== expectedUri) {
    return { ok: false, code: "DOMAIN_URI_MISMATCH" };
  }

  const issuedAt = Date.parse(message.issued_at);
  const expiration = Date.parse(message.expiration_time);
  if (Number.isNaN(issuedAt) || Number.isNaN(expiration)) {
    return { ok: false, code: "INVALID_TIMESTAMP" };
  }
  if (now.getTime() > expiration) {
    return { ok: false, code: "EXPIRED" };
  }

  const expectedSignature = signSiweMessage(message, signerId);
  if (signature !== expectedSignature) {
    return { ok: false, code: "SIGNATURE_MISMATCH" };
  }

  if (!nonceLedger.consume(String(message.nonce))) {
    return { ok: false, code: "NONCE_REPLAY" };
  }

  return { ok: true };
}

module.exports = {
  NonceLedger,
  REQUIRED_FIELDS,
  signSiweMessage,
  verifySiweSubmission,
};
