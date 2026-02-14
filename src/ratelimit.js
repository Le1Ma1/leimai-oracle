class MinuteRateLimiter {
  constructor(limitPerMinute = 10) {
    this.limitPerMinute = limitPerMinute;
    this.state = new Map();
  }

  check(memberId, nowMs) {
    const id = memberId || "anon";
    const bucket = Math.floor(nowMs / 60000);
    const current = this.state.get(id);

    if (!current || current.bucket !== bucket) {
      this.state.set(id, { bucket, count: 1 });
      return {
        allowed: true,
        limit: this.limitPerMinute,
        count: 1,
        bucket,
      };
    }

    if (current.count >= this.limitPerMinute) {
      return {
        allowed: false,
        limit: this.limitPerMinute,
        count: current.count,
        bucket,
      };
    }

    current.count += 1;
    return {
      allowed: true,
      limit: this.limitPerMinute,
      count: current.count,
      bucket,
    };
  }
}

module.exports = {
  MinuteRateLimiter,
};
