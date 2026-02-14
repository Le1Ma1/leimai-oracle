const PUSH_CHANNELS = ["webpush", "email", "telegram"];

class PushDispatcher {
  constructor({ dedupeLedger }) {
    this.dedupeLedger = dedupeLedger;
    this.deliveryLog = [];
  }

  send(input, nowMs) {
    if (!PUSH_CHANNELS.includes(input.channel)) {
      return {
        sent: false,
        reason: "UNSUPPORTED_CHANNEL",
      };
    }

    const dedupeResult = this.dedupeLedger.record(
      {
        member_id: input.member_id,
        // Keep compatibility with dedupe key enum while preserving channel semantics.
        channel: input.channel === "webpush" ? "webhook" : input.channel,
        proof_id: input.proof_id,
        variant: input.variant,
        tf: input.tf,
        window: input.window,
        signal_type: input.signal_type,
      },
      nowMs
    );

    if (dedupeResult.deduped) {
      return {
        sent: false,
        deduped: true,
        key: dedupeResult.key,
      };
    }

    const record = {
      channel: input.channel,
      member_id: input.member_id,
      proof_id: input.proof_id,
      variant: input.variant,
      tf: input.tf,
      window: input.window,
      signal_type: input.signal_type,
      at_ms: nowMs,
      key: dedupeResult.key,
    };
    this.deliveryLog.push(record);
    return {
      sent: true,
      deduped: false,
      key: dedupeResult.key,
      record,
    };
  }

  getDeliveryLog() {
    return [...this.deliveryLog];
  }
}

module.exports = {
  PUSH_CHANNELS,
  PushDispatcher,
};
