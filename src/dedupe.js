const { isValidChannel } = require("./validators");

function minuteBucket(nowMs) {
  return Math.floor(nowMs / 60000);
}

function buildDedupeKey(fields) {
  return [
    fields.member_id,
    fields.channel,
    fields.proof_id,
    fields.variant,
    fields.tf,
    fields.window,
    fields.signal_type,
    fields.minute_bucket,
  ].join("|");
}

class NotificationDedupeLedger {
  constructor() {
    this.keys = new Set();
    this.records = [];
  }

  record(input, nowMs) {
    if (!isValidChannel(input.channel)) {
      throw new Error(`Invalid channel: ${input.channel}`);
    }

    const complete = {
      ...input,
      minute_bucket:
        input.minute_bucket !== undefined
          ? input.minute_bucket
          : minuteBucket(nowMs),
    };

    const key = buildDedupeKey(complete);
    if (this.keys.has(key)) {
      return {
        deduped: true,
        key,
      };
    }

    this.keys.add(key);
    this.records.push({ key, ...complete });
    return {
      deduped: false,
      key,
    };
  }

  getRecords() {
    return [...this.records];
  }
}

module.exports = {
  NotificationDedupeLedger,
  buildDedupeKey,
  minuteBucket,
};
