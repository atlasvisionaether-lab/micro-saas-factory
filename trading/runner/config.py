"""Runner settings and job definitions (trader/runner.json)."""

import copy
import json
import os
import re

WINDOWS = ("session", "trading_day_at", "daily_at")
KINDS = ("desk", "command")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

JOB_DEFAULTS = {"enabled": True, "timeout_s": 120, "retries": 1, "every_min": 15, "start": "09:45",
                "end": "15:30", "at": None, "argv": None, "plans": ["trader/plan.json", "trader/plans/*.json"],
                "max_attempts_per_day": 3}
DEFAULTS = {
    "logs": "logs",
    "log_max_bytes": 5_000_000,
    "log_backups": 5,
    "jobs": [],
    "health": {"max_heartbeat_age_min": 15, "max_consecutive_failures": 3, "alert_argv": None},
}


class RunnerConfigError(ValueError):
    pass


def _job(raw):
    unknown = set(raw) - set(JOB_DEFAULTS) - {"name", "kind", "window"}
    if unknown:
        raise RunnerConfigError("job %r: unknown keys %s" % (raw.get("name"), sorted(unknown)))
    j = dict(copy.deepcopy(JOB_DEFAULTS), **raw)
    name = j.get("name")
    if not name or not re.match(r"^[a-z0-9][a-z0-9_-]{0,40}$", str(name)):
        raise RunnerConfigError("job name must be lowercase letters, digits, - or _: %r" % name)
    if j.get("kind") not in KINDS:
        raise RunnerConfigError("job %s: kind must be one of %s" % (name, KINDS))
    if j.get("window") not in WINDOWS:
        raise RunnerConfigError("job %s: window must be one of %s" % (name, WINDOWS))
    if j["window"] == "session":
        for k in ("start", "end"):
            if not _HHMM.match(str(j[k])):
                raise RunnerConfigError("job %s: %s must be HH:MM" % (name, k))
        if not 1 <= int(j["every_min"]) <= 390:
            raise RunnerConfigError("job %s: every_min must be 1..390" % name)
    elif not j["at"] or not _HHMM.match(str(j["at"])):
        raise RunnerConfigError("job %s: window %s needs at: HH:MM (New York time)" % (name, j["window"]))
    if j["kind"] == "command":
        if not isinstance(j["argv"], list) or not j["argv"] or not all(isinstance(x, str) for x in j["argv"]):
            raise RunnerConfigError("job %s: argv must be a non-empty list of strings (no shell)" % name)
    if not 1 <= int(j["timeout_s"]) <= 3600:
        raise RunnerConfigError("job %s: timeout_s must be 1..3600" % name)
    if not 0 <= int(j["retries"]) <= 5:
        raise RunnerConfigError("job %s: retries must be 0..5" % name)
    return j


def load(path):
    cfg = copy.deepcopy(DEFAULTS)
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            try:
                raw = json.load(fh)
            except ValueError as e:
                raise RunnerConfigError("%s is not valid JSON: %s" % (path, e))
        unknown = set(raw) - set(DEFAULTS)
        if unknown:
            raise RunnerConfigError("unknown runner settings %s" % sorted(unknown))
        for k, v in raw.items():
            cfg[k] = dict(cfg[k], **v) if isinstance(cfg[k], dict) else v
    cfg["jobs"] = [_job(j) for j in cfg["jobs"]]
    names = [j["name"] for j in cfg["jobs"]]
    if len(names) != len(set(names)):
        raise RunnerConfigError("job names must be unique")
    alert = cfg["health"]["alert_argv"]
    if alert is not None and (not isinstance(alert, list) or not all(isinstance(x, str) for x in alert)):
        raise RunnerConfigError("health.alert_argv must be a list of strings or null")
    return cfg
