"""python3 -m runner {tick,health,status}   (run from trading/)

    python3 -m runner tick                 # what systemd's timer calls every 5 minutes
    python3 -m runner tick --dry-run       # show what is due, run nothing, write nothing
    python3 -m runner tick --now "2026-10-19 10:15"   # pin the clock (New York time)
    python3 -m runner health               # exit 1 and alert when ticks stop or jobs keep failing
    python3 -m runner status               # heartbeat, job state, last desk decisions

Config: trader/runner.json (see config/runner.example.json).
Exit codes: tick 0 (job failures are logged, not fatal), health 0 ok / 1 unhealthy, 2 bad config.
"""

import argparse
import json
import os
import sys

from sim.vendor_bridge import timemachine

from . import config as rcfg
from .core import health, status, tick
from .log import Log

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m runner")
    ap.add_argument("--config", default="trader/runner.json")
    ap.add_argument("--root", default=ROOT, help="the trading/ folder (jobs run here)")
    ap.add_argument("--now", help="pin the clock, New York time")
    ap.add_argument("--quiet", action="store_true", help="no stderr log lines")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tick")
    t.add_argument("--dry-run", action="store_true")
    hp = sub.add_parser("health")
    hp.add_argument("--no-alert", action="store_true")
    sp = sub.add_parser("status")
    sp.add_argument("-n", type=int, default=10)
    a = ap.parse_args(argv)

    cfg_path = a.config if os.path.isabs(a.config) else os.path.join(a.root, a.config)
    try:
        cfg = rcfg.load(cfg_path)
        now_utc = timemachine().parse_now(a.now)
    except (rcfg.RunnerConfigError, ValueError) as e:
        print("runner: %s" % e, file=sys.stderr)
        return 2
    if a.cmd == "status":
        print(json.dumps(status(cfg, a.root, a.n), indent=1, ensure_ascii=False, default=str))
        return 0
    log = Log(os.path.join(a.root, cfg["logs"]), cfg["log_max_bytes"], cfg["log_backups"], stderr=not a.quiet)
    try:
        if a.cmd == "tick":
            out = tick(cfg, a.root, log, now_utc, dry_run=a.dry_run)
            if a.dry_run:
                print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
            return 0
        res = health(cfg, a.root, log, now_utc, send_alert=not a.no_alert)
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return 0 if res["ok"] else 1
    finally:
        log.close()


if __name__ == "__main__":
    sys.exit(main())
