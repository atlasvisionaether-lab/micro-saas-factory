"""When is a job due, and how is it run.

Windows (all New York time, from the vendored NYSE calendar, whatever the
machine's own time zone):
  session         trading days, start <= now < min(end, close), every `every_min`
                  minutes since the last attempt (one minute of slack for timer jitter)
  trading_day_at  trading days, once after `at`
  daily_at        every day, once after `at`
Once-a-day jobs stop after `max_attempts_per_day` failed attempts, so a broken
job does not run on every tick all day.

Every job runs as its own process (no shell), in trading/, with a timeout.
Exit 0 ok, exit 2 bad input (not retried), anything else or a timeout is
retried `retries` times with 2 s, 4 s ... backoff.
"""

import datetime
import glob
import os
import subprocess
import sys
import time

from sim.vendor_bridge import load as vendor_load

SLACK = datetime.timedelta(minutes=1)
TAIL = 2000


def alerts():
    return vendor_load("trader-alerts", "alerts")


def market(now_utc):
    """Vendor market status plus the parsed close time and the local clock."""
    a = alerts()
    st = a.market_status(now_utc)
    local = a.to_eastern(now_utc)
    st["local"] = local
    s = a.session(local.date())
    st["trading_day"] = s is not None
    st["close_time"] = s[1] if s else None
    return st


def _hm(s):
    return datetime.time(int(s[:2]), int(s[3:5]))


def due(job, st, js, now_utc):
    """(is_due, reason). `js` is the job's saved state."""
    if not job["enabled"]:
        return False, "disabled"
    local = st["local"]
    today = local.date().isoformat()
    w = job["window"]
    if w in ("session", "trading_day_at") and not st["trading_day"]:
        return False, "not a trading day (%s)" % (st.get("reason") or "closed")
    if w == "session":
        end = min(_hm(job["end"]), st["close_time"])
        if not _hm(job["start"]) <= local.time() < end:
            return False, "outside %s-%s" % (job["start"], end.strftime("%H:%M"))
        last = js.get("last_attempt_utc")
        if last:
            last_dt = datetime.datetime.fromisoformat(last)
            if now_utc - last_dt < datetime.timedelta(minutes=int(job["every_min"])) - SLACK:
                return False, "ran at %s" % last
        return True, "session"
    if local.time() < _hm(job["at"]):
        return False, "before %s" % job["at"]
    if js.get("last_success_date") == today:
        return False, "done today"
    if js.get("attempts_date") == today and js.get("attempts_today", 0) >= int(job["max_attempts_per_day"]):
        return False, "gave up today after %d attempts" % js["attempts_today"]
    return True, w


def expand(argv, today):
    return [x.replace("{python}", sys.executable).replace("{today}", today) for x in argv]


def plan_files(job, root, today):
    """Desk plans for today: every matching file whose plan date is today."""
    from runner.store import read_json
    seen, out, skipped = set(), [], []
    for pattern in job["plans"]:
        for path in sorted(glob.glob(os.path.join(root, pattern))):
            if path in seen:
                continue
            seen.add(path)
            plan = read_json(path, {}) or {}
            if plan.get("date") == today:
                out.append(path)
            else:
                skipped.append({"plan": os.path.relpath(path, root), "date": plan.get("date")})
    return out, skipped


def commands(job, root, today, logs):
    """[(label, argv)] the job runs this tick, plus notes on what it skipped."""
    if job["kind"] == "command":
        return [(job["name"], expand(job["argv"], today))], []
    plans, skipped = plan_files(job, root, today)
    return [("%s:%s" % (job["name"], os.path.relpath(p, root)),
             [sys.executable, "-m", "desk", "run", "--plan", os.path.relpath(p, root), "--logs", logs])
            for p in plans], skipped


def execute(argv, cwd, timeout_s, retries, sleep=time.sleep):
    """Run one command with retries. Returns a result dict (never raises for the job's own failure)."""
    attempts = []
    for n in range(retries + 1):
        if n:
            sleep(2 ** n)
        t0 = time.monotonic()
        try:
            p = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=timeout_s, stdin=subprocess.DEVNULL)
            rec = {"exit": p.returncode, "seconds": round(time.monotonic() - t0, 2),
                   "stderr_tail": p.stderr.decode("utf-8", "replace")[-TAIL:]}
        except subprocess.TimeoutExpired:
            rec = {"exit": None, "timeout": True, "seconds": timeout_s}
        except OSError as e:
            rec = {"exit": None, "error": str(e), "seconds": round(time.monotonic() - t0, 2)}
        attempts.append(rec)
        if rec["exit"] in (0, 2):
            break
    last = attempts[-1]
    return {"ok": last["exit"] == 0, "attempts": attempts, "exit": last["exit"]}
