"""Chart JSON + plan -> a numpy pool of past sessions and a data-quality record."""

from dataclasses import dataclass, field

import numpy as np

from .vendor_bridge import timemachine


class SimError(Exception):
    pass


@dataclass
class Market:
    symbol: str
    pool: np.ndarray            # (S, 78, 4) o,h,l,c as ratios to the previous bar's close; [:, 0] is NaN
    sessions: list              # vendor format [(date, [bar dicts])], oldest first
    entry_bar: int              # k: the bar whose close is the entry
    last_bar: int               # last bar replayed (inclusive)
    until: str                  # HH:MM ET
    quality: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    entry_day: dict = field(default_factory=dict)  # {slot: bar} for the plan's own date


def build_pool(sessions):
    arr = np.array([[[b["o"], b["h"], b["l"], b["c"]] for b in D] for _, D in sessions], dtype=float)
    pool = np.full_like(arr, np.nan)
    pool[:, 1:, :] = arr[:, 1:, :] / arr[:, :-1, 3:4]
    return pool


def load_market(text, plan, now_utc, until=None, min_sessions=None):
    """Mirror of the vendor's time_machine() preamble, returning numpy data."""
    tm = timemachine()
    sym = plan["symbol"]
    try:
        result = tm.chart_result(text, sym)
        meta, bars, dropped = tm.parse_bars(result, now_utc)
    except tm.TMError as e:
        raise SimError(str(e))
    msym = str(meta.get("symbol") or "").upper()
    if msym and msym != sym.replace(".", "-"):
        raise SimError("the data is for %s but the plan is for %s" % (msym, sym))
    if meta.get("dataGranularity") not in (None, "5m"):
        raise SimError("5-minute bars required, got %s" % meta.get("dataGranularity"))
    if not bars:
        raise SimError("no complete 5-minute bars for %s" % sym)
    k = plan["entry_bar"]
    early = plan["date"] in tm.NYSE_EARLY_CLOSE
    end_min = tm.EARLY_MIN if early else tm.CLOSE_MIN
    until_min = end_min if until is None else tm.parse_clock(until, "until")
    if (until_min - tm.OPEN_MIN) % 5 or until_min > end_min:
        raise SimError("until must be on the 5-minute grid and no later than %s" % tm.clock12(end_min))
    last = (until_min - tm.OPEN_MIN) // 5 - 1
    if last <= k:
        raise SimError("until %s leaves nothing to replay after the %s entry" % (tm.clock12(until_min),
                                                                             plan["entry_time"]))
    days = tm.split_sessions(bars)
    entry_day = days.get(plan["date"], {})
    if k not in entry_day:
        raise SimError("no complete entry bar (closing %s) on %s for %s" % (plan["entry_time"], plan["date"], sym))
    warnings = []
    eb = entry_day[k]
    if not eb["l"] - 0.01 <= plan["entry"] <= eb["h"] + 0.01:
        warnings.append("plan entry %.2f is outside the entry bar's range %.2f-%.2f" % (plan["entry"], eb["l"], eb["h"]))
    sessions, short = tm.full_sessions(days, plan["date"])
    need = tm.MIN_SESSIONS if min_sessions is None else min_sessions
    if len(sessions) < need:
        raise SimError("only %d full sessions before %s; need at least %d" % (len(sessions), plan["date"], need))
    pool = build_pool(sessions)
    if not np.all(np.isfinite(pool[:, 1:, :])) or np.any(pool[:, 1:, :] <= 0):
        raise SimError("bad prices in the pool (non-finite or non-positive)")
    # data-quality signals the skeptic / decision layer can read
    lr = np.log(pool[:, 1:, 3])
    ext = np.abs(lr) > 0.10
    if ext.any():
        warnings.append("%d bar(s) moved more than 10%% in five minutes in the pool (splits or bad ticks?)" % int(ext.sum()))
    if len(sessions) < 40:
        warnings.append("only %d sessions in the pool: tail estimates are noisy" % len(sessions))
    last_bar = bars[-1]
    quality = {
        "pool_sessions": len(sessions), "pool_from": sessions[0][0], "pool_to": sessions[-1][0],
        "short_sessions_left_out": short, "dropped_bars": dropped,
        "last_bar": "%s %s ET" % (last_bar["date"], last_bar["start"]),
        "extreme_bars": int(ext.sum()),
    }
    return Market(sym, pool, sessions, k, last, tm.clock24(until_min), quality, warnings, entry_day)
