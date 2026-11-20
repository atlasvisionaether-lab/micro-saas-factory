"""python3 -m desk run [...]   (run from trading/)

    python3 -m desk run                               # trader/plan.json, live bars + headlines
    python3 -m desk run --offline CHART.json.gz --news-offline yahoo-TSLA.xml \
        --symbol TSLA --date 2026-10-19 --entry 364.18 --stop 358.32 --target 370.04 \
        --entry-time "10:15 AM" --now "2026-10-19 10:15"
    python3 -m desk run ... --json        # decision document to stdout
    python3 -m desk run ... --no-log      # do not write logs/desk/...

Exit codes: 0 the desk ran (any decision), 2 bad input or unusable data.
"""

import argparse
import json
import os
import sys

from sim import config as simcfg
from sim.data import SimError, load_market
from sim.report import render as render_sim
from sim.run import run_sim
from sim.vendor_bridge import timemachine

from . import config as deskcfg
from .bundle import Bundle, load_news
from .logs import dumps, write_run
from .protocol import run_desk
from .report import render


def build_parser():
    ap = argparse.ArgumentParser(prog="python3 -m desk")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="debate one plan and decide AL / BEKLE / GEÇ")
    r.add_argument("--plan", default="trader/plan.json")
    r.add_argument("--trader-config", default="trader/config.json")
    r.add_argument("--sim-config", default="trader/sim.json")
    r.add_argument("--desk-config", default="trader/desk.json")
    r.add_argument("--offline", help="saved Yahoo chart JSON (.json/.json.gz) or a folder of them")
    r.add_argument("--news-offline", help="saved Yahoo headline RSS file")
    r.add_argument("--no-news", action="store_true", help="skip headlines (the desk notes it is blind)")
    r.add_argument("--now", help='pin the clock, New York time, e.g. "2026-10-19 10:15"')
    r.add_argument("--until")
    r.add_argument("--replays", type=int)
    r.add_argument("--seed", type=int)
    for f in ("symbol", "date", "entry_time", "setup", "stop_rule"):
        r.add_argument("--" + f.replace("_", "-"), dest=f)
    for f in ("entry", "stop", "target"):
        r.add_argument("--" + f, type=float)
    r.add_argument("--side", default="buy", choices=("buy", "sell"))
    r.add_argument("--or-minutes", type=int, default=15)
    r.add_argument("--logs", default="logs")
    r.add_argument("--no-log", action="store_true")
    r.add_argument("--json", action="store_true")
    return ap


def _read_json(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def main(argv=None):
    a = build_parser().parse_args(argv)
    tm = timemachine()
    try:
        now_utc = tm.parse_now(a.now)
        a.setup = a.setup or "orb"
        a.stop_rule = a.stop_rule or "auto"
        plan = tm.load_plan(a, now_utc)
        trader_cfg = _read_json(a.trader_config)
        dcfg = deskcfg.load(a.desk_config)
        cfg = simcfg.load(a.sim_config, {"replays": a.replays, "seed": a.seed})
        if cfg["risk_usd"] is None and trader_cfg.get("max_loss_per_trade_usd"):
            cfg["risk_usd"] = trader_cfg["max_loss_per_trade_usd"]
            simcfg.validate(cfg)
        text = tm.read_offline(a.offline, plan["symbol"]) if a.offline else tm.fetch_chart(plan["symbol"])
        market = load_market(text, plan, now_utc, a.until)
        sim_doc = run_sim(market, plan, cfg, now_utc)
        if a.no_news:
            news, err = None, "--no-news"
        elif a.news_offline:
            with open(a.news_offline, "rb") as fh:
                news, err = load_news(plan["symbol"], now_utc, dcfg["news_hours"], rss_bytes=fh.read())
        else:
            news, err = load_news(plan["symbol"], now_utc, dcfg["news_hours"], fetch=True)
    except (tm.TMError, SimError, simcfg.ConfigError, deskcfg.DeskConfigError, ValueError, OSError) as e:
        print("desk: %s" % e, file=sys.stderr)
        return 2

    b = Bundle(plan=plan, market=market, sim=sim_doc, trader_cfg=trader_cfg, desk_cfg=dcfg,
               now_utc=now_utc, news=news, news_error=err)
    run = run_desk(b)
    report = render(run, b)
    if not a.no_log:
        path = write_run(a.logs, b, run, report, render_sim(sim_doc))
        print("desk: logged to %s" % path, file=sys.stderr)
    if a.json:
        print(dumps({"decision": run["decision"], "contradictions": run["contradictions"],
                     "transcript": [m.to_dict() for m in run["transcript"]]}, indent=1))
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
