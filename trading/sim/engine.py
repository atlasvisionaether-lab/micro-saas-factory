"""Walk generated bars against the plan's stop and target. Vectorized over paths.

Fill rules (all conservative, all reported in the assumptions block):
- Entry fills at the plan's entry price, plus slippage.
- Stop and target both inside one bar: the stop counts (order unknown at 5 min).
- Stop: if a bar opens beyond the stop (a gap), the fill is that open, not the stop.
- Target: a limit order fills at the target, never better.
- Neither by `until`: exit at that bar's close.
- Costs: slippage in basis points on entry and exit notional, commission per
  share on both sides; converted to R and subtracted.
"""

import numpy as np

TIME, TARGET, STOP = 0, 1, 2
OUTCOME_NAMES = {TIME: "time", TARGET: "target", STOP: "stop"}


def run_paths(rel, entry, stop, target, side="buy", slippage_bps=0.0, commission_per_share=0.0):
    long = side == "buy"
    if long and not stop < entry < target:
        raise ValueError("a buy needs stop < entry < target")
    if not long and not target < entry < stop:
        raise ValueError("a sell needs target < entry < stop")
    n, T, _ = rel.shape
    closes = entry * np.cumprod(rel[..., 3], axis=1)
    prev = np.concatenate([np.full((n, 1), entry), closes[:, :-1]], axis=1)
    o = prev * rel[..., 0]
    h = prev * rel[..., 1]
    lo = prev * rel[..., 2]

    if long:
        s_hit, t_hit = lo <= stop, h >= target
    else:
        s_hit, t_hit = h >= stop, lo <= target
    first_s = np.where(s_hit.any(axis=1), s_hit.argmax(axis=1), T)
    first_t = np.where(t_hit.any(axis=1), t_hit.argmax(axis=1), T)

    outcome = np.full(n, TIME, dtype=np.int8)
    is_stop = (first_s < T) & (first_s <= first_t)
    is_tgt = (first_t < T) & ~is_stop
    outcome[is_stop] = STOP
    outcome[is_tgt] = TARGET

    rows = np.arange(n)
    exit_bar = np.where(is_stop, first_s, np.where(is_tgt, first_t, T - 1))
    exit_px = closes[:, -1].copy()
    stop_open = o[rows, np.minimum(first_s, T - 1)]
    gap_fill = np.minimum(stop, stop_open) if long else np.maximum(stop, stop_open)
    exit_px[is_stop] = gap_fill[is_stop]
    exit_px[is_tgt] = target

    d = 1.0 if long else -1.0
    risk = (entry - stop) * d
    r_gross = d * (exit_px - entry) / risk
    cost = (entry + exit_px) * slippage_bps / 1e4 + 2.0 * commission_per_share
    r_net = r_gross - cost / risk
    return {
        "outcome": outcome, "exit_price": exit_px, "exit_bar": exit_bar,
        "r_gross": r_gross, "r_net": r_net, "close": closes[:, -1],
        "gap_stops": int((is_stop & (gap_fill != stop)).sum()),
    }
