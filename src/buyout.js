const BUYOUT_STATES = {
  OPEN: "OPEN",
  BUYOUT_PENDING: "BUYOUT_PENDING",
  BUYOUT_EFFECTIVE: "BUYOUT_EFFECTIVE",
  BUYOUT_EARLY_EFFECTIVE: "BUYOUT_EARLY_EFFECTIVE",
};

function createBuyoutState({ cap_total, cap_active }) {
  return {
    status: BUYOUT_STATES.OPEN,
    cap_total,
    cap_active,
    cap_total_future: cap_total,
    effective_date_epoch: null,
    tender_threshold: 0.8,
    seats: [],
  };
}

function canSellNewSeats(state) {
  return (
    state.status === BUYOUT_STATES.OPEN ||
    state.status === BUYOUT_STATES.BUYOUT_PENDING
  );
}

function addSeat(state, seat) {
  if (!canSellNewSeats(state)) {
    return { ok: false, code: "SEAT_SALE_BLOCKED_AFTER_EFFECTIVE" };
  }
  state.seats.push({
    seat_id: seat.seat_id,
    sold_epoch: seat.sold_epoch,
    end_epoch: seat.end_epoch,
  });
  state.cap_active += 1;
  return { ok: true };
}

function startBuyout(state, effectiveDateEpoch) {
  if (state.status !== BUYOUT_STATES.OPEN) {
    return { ok: false, code: "INVALID_TRANSITION" };
  }
  state.status = BUYOUT_STATES.BUYOUT_PENDING;
  state.effective_date_epoch = effectiveDateEpoch;
  return { ok: true };
}

function applyEffective(state, nowEpoch) {
  if (state.status !== BUYOUT_STATES.BUYOUT_PENDING) {
    return { ok: false, code: "INVALID_TRANSITION" };
  }
  if (nowEpoch < state.effective_date_epoch) {
    return { ok: false, code: "NOT_EFFECTIVE_YET" };
  }
  state.status = BUYOUT_STATES.BUYOUT_EFFECTIVE;
  state.cap_total_future = 0;
  return { ok: true };
}

function applyTenderOffer(state, participationRatio) {
  if (state.status !== BUYOUT_STATES.BUYOUT_PENDING) {
    return { ok: false, code: "INVALID_TRANSITION" };
  }
  if (participationRatio < state.tender_threshold) {
    return { ok: false, code: "THRESHOLD_NOT_MET" };
  }
  state.status = BUYOUT_STATES.BUYOUT_EARLY_EFFECTIVE;
  state.cap_total_future = 0;
  return { ok: true };
}

function isGrandfatheredSeatActive(state, seatId, nowEpoch) {
  const seat = state.seats.find((item) => item.seat_id === seatId);
  if (!seat) {
    return false;
  }

  if (!state.effective_date_epoch) {
    return nowEpoch <= seat.end_epoch;
  }

  if (seat.sold_epoch < state.effective_date_epoch) {
    return nowEpoch <= seat.end_epoch;
  }

  return false;
}

module.exports = {
  BUYOUT_STATES,
  addSeat,
  applyEffective,
  applyTenderOffer,
  canSellNewSeats,
  createBuyoutState,
  isGrandfatheredSeatActive,
  startBuyout,
};
