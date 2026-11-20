"""One plan, every configured model, one document."""

import datetime

import numpy as np

from . import __version__
from .engine import run_paths
from .metrics import disagreement, sequence_risk, summarize
from .models import generate
from .vendor_bridge import timemachine


def run_sim(market, plan, cfg, now_utc=None):
    entry, stop, target, side = plan["entry"], plan["stop"], plan["target"], plan["side"]
    risk = abs(entry - stop)
    k, last = market.entry_bar, market.last_bar
    risk_usd = cfg["risk_usd"]
    by_model = {}
    for model in cfg["models"]:
        params = {"window": cfg["window"], "block_size_bars": cfg["block_size_bars"]}
        if model == "regime_shock":
            params.update(cfg["regime_shock"], entry=entry, risk=risk, side=side)
        rel = generate(model, market.pool, k, last, cfg["replays"], cfg["seed"], **params)
        res = run_paths(rel, entry, stop, target, side, cfg["slippage_bps"], cfg["commission_per_share_usd"])
        s = summarize(res, cfg["breakeven_band_r"], cfg["confidence_level"], risk_usd)
        sq = cfg["sequence"]
        s["sequence"] = sequence_risk(res["r_net"], np.random.default_rng([cfg["seed"], 1000]),
                                      sq["n_trades"], sq["n_sequences"], sq["risk_frac"], sq["dd_threshold"])
        by_model[model] = s

    history = None
    tm = timemachine()
    rule = tm.resolve_rule(plan, market.entry_day)
    if rule:
        h = tm.history_replay(market.sessions, rule, last, side)
        history = {key: h[key] for key in ("sessions", "triggered", "target", "stop", "close", "green", "avg_R")}
        history["rule"] = rule

    now = now_utc or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return {
        "created_by": "trading/sim", "version": __version__,
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plan": {key: plan[key] for key in ("symbol", "side", "date", "setup", "entry", "entry_time",
                                             "stop", "target", "risk_per_share", "target_r")},
        "until": market.until, "bars_left": last - k,
        "data": market.quality, "warnings": list(market.warnings),
        "settings": cfg, "models": by_model, "disagreement": disagreement(by_model),
        "history": history,
    }

