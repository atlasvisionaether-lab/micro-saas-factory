"""Outcome statistics with uncertainty. All R values are net of costs.

Win / breakeven / loss classes use a symmetric band around zero R:
    win        R >  band
    breakeven  |R| <= band
    loss       R < -band
"""

import math

import numpy as np

from .engine import STOP, TARGET, TIME

_Z = {0.90: 1.6449, 0.95: 1.9600, 0.99: 2.5758}


def z_for(level):
    if level not in _Z:
        raise ValueError("confidence_level must be one of %s" % sorted(_Z))
    return _Z[level]


def wilson(k, n, z):
    """Wilson score interval for a proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, mid - half), min(1.0, mid + half))


def summarize(res, band_r=0.1, level=0.95, risk_usd=None):
    r = res["r_net"]
    n = r.size
    z = z_for(level)
    win, loss = r > band_r, r < -band_r
    be = ~win & ~loss
    out = {"n": int(n)}
    for name, mask in (("win", win), ("breakeven", be), ("loss", loss)):
        k = int(mask.sum())
        out["p_" + name] = k / n
        out["p_%s_ci" % name] = wilson(k, n, z)
    for name, code in (("target", TARGET), ("stop", STOP), ("time", TIME)):
        out["p_exit_" + name] = float((res["outcome"] == code).mean())
    mean = float(r.mean())
    sd = float(r.std(ddof=1)) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n else 0.0
    out.update({
        "expectancy_r": mean, "expectancy_r_ci": (mean - z * se, mean + z * se),
        "sd_r": sd, "expectancy_gross_r": float(res["r_gross"].mean()),
        "avg_win_r": float(r[win].mean()) if win.any() else None,
        "avg_loss_r": float(r[loss].mean()) if loss.any() else None,
        "profit_factor": float(r[r > 0].sum() / -r[r < 0].sum()) if (r < 0).any() else None,
        "r_percentiles": {str(q): float(np.percentile(r, q)) for q in (5, 25, 50, 75, 95)},
        "gap_stops": res.get("gap_stops", 0),
        "confidence_level": level, "breakeven_band_r": band_r,
    })
    if risk_usd:
        out["risk_usd"] = risk_usd
        out["expectancy_usd"] = mean * risk_usd
        out["expectancy_usd_ci"] = tuple(x * risk_usd for x in out["expectancy_r_ci"])
    return out


def sequence_risk(r, rng, n_trades=50, n_seq=5000, risk_frac=0.01, dd_threshold=0.10):
    """Resample n_trades outcomes per sequence, compounding risk_frac of equity per trade.
    Answers: what does a string of these trades do to an account, including bad luck?"""
    draws = rng.choice(r, size=(n_seq, n_trades), replace=True)
    growth = np.maximum(1.0 + risk_frac * draws, 0.0)
    eq = np.cumprod(growth, axis=1)
    peak = np.maximum.accumulate(np.concatenate([np.ones((n_seq, 1)), eq], axis=1), axis=1)[:, 1:]
    dd = 1.0 - eq / peak
    max_dd = dd.max(axis=1)
    final = eq[:, -1] - 1.0
    return {
        "n_trades": n_trades, "n_sequences": n_seq, "risk_frac": risk_frac,
        "final_return_p5": float(np.percentile(final, 5)),
        "final_return_median": float(np.median(final)),
        "final_return_p95": float(np.percentile(final, 95)),
        "p_losing_sequence": float((final < 0).mean()),
        "max_drawdown_median": float(np.median(max_dd)),
        "max_drawdown_p95": float(np.percentile(max_dd, 95)),
        "dd_threshold": dd_threshold,
        "p_drawdown_over_threshold": float((max_dd > dd_threshold).mean()),
    }


def disagreement(by_model):
    """Flags for the skeptic: do the models even agree on the sign of the edge?"""
    exps = {m: s["expectancy_r"] for m, s in by_model.items()}
    lows = {m: s["expectancy_r_ci"][0] for m, s in by_model.items()}
    highs = {m: s["expectancy_r_ci"][1] for m, s in by_model.items()}
    flags = []
    if any(v > 0 for v in exps.values()) and any(v < 0 for v in exps.values()):
        flags.append("models disagree on the sign of expectancy")
    if all(h < 0 for h in highs.values()):
        flags.append("every model's expectancy CI is below zero")
    elif any(l > 0 for l in lows.values()):
        flags.append("at least one model's expectancy CI is above zero")
    else:
        flags.append("no model shows expectancy distinguishable from zero")
    spread = max(exps.values()) - min(exps.values()) if exps else 0.0
    return {"expectancy_spread_r": spread, "min_model": min(exps, key=exps.get) if exps else None,
            "flags": flags}
