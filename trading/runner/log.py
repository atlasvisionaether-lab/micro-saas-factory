"""JSON-lines application log with size rotation, plus one readable line on
stderr (journald keeps those when the runner runs under systemd)."""

import datetime
import json
import logging
import logging.handlers
import os
import sys


class JsonFormatter(logging.Formatter):
    def format(self, rec):
        out = {"ts": datetime.datetime.fromtimestamp(rec.created, datetime.timezone.utc)
               .strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "level": rec.levelname, "event": rec.getMessage()}
        out.update(getattr(rec, "fields", {}) or {})
        return json.dumps(out, ensure_ascii=False, default=str)


class Log:
    def __init__(self, logs_dir, max_bytes=5_000_000, backups=5, stderr=True):
        self.logger = logging.getLogger("runner.%s" % os.path.abspath(logs_dir))
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        for h in list(self.logger.handlers):
            self.logger.removeHandler(h)
            h.close()
        os.makedirs(os.path.join(logs_dir, "runner"), exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(os.path.join(logs_dir, "runner", "runner.jsonl"),
                                                  maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
        fh.setFormatter(JsonFormatter())
        self.logger.addHandler(fh)
        if stderr:
            sh = logging.StreamHandler(sys.stderr)
            sh.setFormatter(logging.Formatter("runner %(levelname)s %(message)s"))
            self.logger.addHandler(sh)

    def _emit(self, level, event, fields):
        self.logger.log(level, event, extra={"fields": fields})

    def info(self, event, **f):
        self._emit(logging.INFO, event, f)

    def warn(self, event, **f):
        self._emit(logging.WARNING, event, f)

    def error(self, event, **f):
        self._emit(logging.ERROR, event, f)

    def close(self):
        for h in list(self.logger.handlers):
            self.logger.removeHandler(h)
            h.close()
