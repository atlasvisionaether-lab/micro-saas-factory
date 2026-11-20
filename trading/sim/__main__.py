"""python3 -m sim run [...]   (run from trading/)

    python3 -m sim run                                   # trader/plan.json, trader/sim.json, live Yahoo bars
    python3 -m sim run --offline FILE.json.gz            # saved chart, no network
    python3 -m sim run --symbol TSLA --date 2026-10-19 --entry 364.18 --stop 358.32 \
        --target 370.04 --entry-time "10:15 AM" --offline FILE --now "2026-10-19 10:50"
    python3 -m sim run --json | --write                  # JSON to stdout | save trader/sim/<sym>-<date>.{json,md}

Exit codes: 0 ok, 2 bad input or data.
"""

import argparse
import json
import os
import sys

from . import config as cfgmod
from .data import SimError, load_market
from .report import render
from .run import run_sim
from .vendor_bridge import timemachine


def _jsonable(o):
    if isinstance(o, tuple):
        return list(o)
    raise TypeError(type(o))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m sim")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="simulate one plan under every configured model")
    r.add_argument("--plan", default="trader/plan.json")
    r.add_argument("--config", default="trader/sim.json")
    r.add_argument("--trader-config", default="trader/config.json",
                   help="risk_usd falls back to its max_loss_per_trade_usd")
    r.add_argument("--offline", help="saved Yahoo chart JSON (.json/.json.gz) or a folder of them")
    r.add_argument("--now", help='pin the clock, New York time, e.g. "2026-10-19 10:50"')
    r.add_argument("--until", help="end each replay at this HH:MM ET (default: the close)")
    r.add_argument("--replays", type=int)
    r.add_argument("--seed", type=int)
    r.add_argument("--models", help="comma list")
    for f in ("symbol", "date", "entry_time", "setup", "stop_rule"):
        r.add_argument("--" + f.replace("_", "-"), dest=f)
    for f in ("entry", "stop", "target"):
        r.add_argument("--" + f, type=float)
    r.add_argument("--side", default="buy", choices=("buy", "sell"))
    r.add_argument("--or-minutes", type=int, default=15)
    r.add_argument("--json", action="store_true")
    r.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)

    tm = timemachine()
    try:
        now_utc = tm.parse_now(a.now)
        if a.setup is None:
            a.setup = "orb"
        if a.stop_rule is None:
            a.stop_rule = "auto"
        plan = tm.load_plan(a, now_utc)
        overrides = {"replays": a.replays, "seed": a.seed,
                     "models": a.models.split(",") if a.models else None}
        cfg = cfgmod.load(a.config, overrides)
        if cfg["risk_usd"] is None and os.path.exists(a.trader_config):
            with open(a.trader_config, encoding="utf-8") as fh:
                cfg["risk_usd"] = json.load(fh).get("max_loss_per_trade_usd")
            cfgmod.validate(cfg)
        if a.offline:
            text, source = tm.read_offline(a.offline, plan["symbol"]), "offline:" + os.path.basename(a.offline)
        else:
            text, source = tm.fetch_chart(plan["symbol"]), "yahoo"
        market = load_market(text, plan, now_utc, a.until)
        doc = run_sim(market, plan, cfg, now_utc)
        doc["source"] = source
    except (tm.TMError, SimError, cfgmod.ConfigError, ValueError, OSError) as e:
        print("sim: %s" % e, file=sys.stderr)
        return 2

    md = render(doc)
    if a.write:
        os.makedirs(os.path.join("trader", "sim"), exist_ok=True)
        base = os.path.join("trader", "sim", "%s-%s" % (plan["symbol"], plan["date"]))
        with open(base + ".json", "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, default=_jsonable)
        with open(base + ".md", "w", encoding="utf-8") as fh:
            fh.write(md + "\n")
        print("wrote %s.json and %s.md" % (base, base), file=sys.stderr)
    print(json.dumps(doc, indent=1, default=_jsonable) if a.json else md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
