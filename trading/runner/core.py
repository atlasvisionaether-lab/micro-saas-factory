"""tick / health / status."""

import datetime
import os
import subprocess

from . import jobs as J
from .store import Locked, TickLock, read_json, write_json


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def paths(cfg, root):
    logs = os.path.join(root, cfg["logs"])
    r = os.path.join(logs, "runner")
    return {"logs": logs, "lock": os.path.join(r, "runner.lock"), "state": os.path.join(r, "state.json"),
            "heartbeat": os.path.join(r, "heartbeat.json")}


def alert(cfg, root, log, message):
    argv = cfg["health"]["alert_argv"]
    log.warn("alert", message=message, sent=bool(argv))
    if not argv:
        return
    try:
        subprocess.run(list(argv) + [message], cwd=root, timeout=30, capture_output=True,
                       stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        log.error("alert_failed", error=str(e))


def tick(cfg, root, log, now_utc, dry_run=False, execute=J.execute):
    p = paths(cfg, root)
    try:
        with TickLock(p["lock"]):
            return _tick(cfg, root, log, now_utc, dry_run, execute, p)
    except Locked:
        log.warn("tick_skipped", reason="previous tick still running")
        return {"skipped": "locked"}


def _tick(cfg, root, log, now_utc, dry_run, execute, p):
    st = J.market(now_utc)
    today = st["local"].date().isoformat()
    state = read_json(p["state"], {}) or {}
    summary = {"ts_utc": _iso(now_utc) + "Z", "now_new_york": st["now_new_york"], "market_open": st["open"],
               "market_reason": st["reason"], "calendar_known": st["calendar_known"], "ran": [], "not_due": {}}
    if not st["calendar_known"]:
        log.warn("calendar_unknown", year=st["local"].year,
                 note="the vendored NYSE holiday list does not cover this year; holidays are treated as trading days")
    threshold = cfg["health"]["max_consecutive_failures"]
    for job in cfg["jobs"]:
        js = state.setdefault(job["name"], {})
        ok_due, why = J.due(job, st, js, now_utc)
        if not ok_due:
            summary["not_due"][job["name"]] = why
            continue
        cmds, skipped = J.commands(job, root, today, cfg["logs"])
        for s in skipped:
            log.info("plan_skipped", job=job["name"], reason="plan date is not today", **s)
        if dry_run:
            summary["ran"].append({"job": job["name"], "dry_run": True, "commands": [c[1] for c in cmds]})
            continue
        js["last_attempt_utc"] = _iso(now_utc)
        if js.get("attempts_date") != today:
            js["attempts_date"], js["attempts_today"] = today, 0
        js["attempts_today"] += 1
        if not cmds:
            log.info("job_idle", job=job["name"], reason="no plan for today")
            summary["ran"].append({"job": job["name"], "commands": 0})
            js["last_success_date"] = today
            continue
        all_ok = True
        for label, argv in cmds:
            res = execute(argv, root, int(job["timeout_s"]), int(job["retries"]))
            all_ok &= res["ok"]
            fields = {"job": job["name"], "label": label, "exit": res["exit"], "attempts": len(res["attempts"]),
                      "seconds": sum(a["seconds"] for a in res["attempts"])}
            if res["ok"]:
                log.info("job_ok", **fields)
            else:
                last = res["attempts"][-1]
                log.error("job_failed", timeout=bool(last.get("timeout")), error=last.get("error"),
                          stderr_tail=last.get("stderr_tail", "")[-500:], **fields)
            summary["ran"].append({"job": job["name"], "label": label, "ok": res["ok"], "exit": res["exit"]})
        if all_ok:
            js["consecutive_failures"] = 0
            js["last_success_utc"] = _iso(now_utc)
            js["last_success_date"] = today
        else:
            js["consecutive_failures"] = js.get("consecutive_failures", 0) + 1
            if js["consecutive_failures"] == threshold:
                alert(cfg, root, log, "trading runner: job %s failed %d times in a row" % (job["name"], threshold))
    if not dry_run:
        write_json(p["state"], state)
        write_json(p["heartbeat"], summary)
    log.info("tick", ran=len(summary["ran"]), market_open=st["open"], dry_run=dry_run)
    return summary


def health(cfg, root, log, now_utc, send_alert=True):
    p = paths(cfg, root)
    h = cfg["health"]
    problems, notes = [], []
    hb = read_json(p["heartbeat"])
    if not hb:
        problems.append("no heartbeat yet: the timer has not run a tick")
    else:
        ts = datetime.datetime.fromisoformat(hb["ts_utc"].rstrip("Z"))
        age = (now_utc - ts).total_seconds() / 60.0
        if age > h["max_heartbeat_age_min"]:
            problems.append("last tick %.0f min ago (limit %d): is the timer running?" % (
                age, h["max_heartbeat_age_min"]))
        else:
            notes.append("last tick %.0f min ago" % age)
        if not hb.get("calendar_known", True):
            problems.append("NYSE calendar unknown for this year: update the vendored holiday list")
    state = read_json(p["state"], {}) or {}
    for name, js in sorted(state.items()):
        f = js.get("consecutive_failures", 0)
        if f >= h["max_consecutive_failures"]:
            problems.append("job %s failed %d times in a row" % (name, f))
        elif f:
            notes.append("job %s: %d recent failure(s)" % (name, f))
    ok = not problems
    log.info("health", ok=ok, problems=problems)
    if not ok and send_alert:
        alert(cfg, root, log, "trading runner unhealthy: " + "; ".join(problems))
    return {"ok": ok, "problems": problems, "notes": notes}


def status(cfg, root, n=10):
    p = paths(cfg, root)
    idx = os.path.join(p["logs"], "desk", "index.jsonl")
    runs = []
    if os.path.exists(idx):
        import json
        with open(idx, encoding="utf-8") as fh:
            lines = fh.readlines()[-n:]
        runs = [json.loads(x) for x in lines if x.strip()]
    return {"heartbeat": read_json(p["heartbeat"]), "state": read_json(p["state"], {}), "desk_runs": runs}
