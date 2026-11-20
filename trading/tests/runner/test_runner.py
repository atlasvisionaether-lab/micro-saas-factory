"""Offline tests for trading/runner. Run from trading/:
    python3 -m unittest discover -s tests -t .
"""

import ast
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from runner import config as rcfg
from runner import jobs as J
from runner.__main__ import main
from runner.core import health, status, tick
from runner.log import Log
from runner.store import TickLock, read_json
from sim.vendor_bridge import VENDOR, timemachine

TRADING = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIX = os.path.join(VENDOR, "tests", "fixtures")


def now(s):
    return timemachine().parse_now(s)


def job(**kw):
    base = {"name": "j", "kind": "command", "window": "session", "argv": ["true"]}
    base.update(kw)
    return rcfg._job(base)


class FakeExec:
    def __init__(self, results=None):
        self.calls, self.results = [], list(results or [])

    def __call__(self, argv, cwd, timeout_s, retries):
        self.calls.append(argv)
        ok = self.results.pop(0) if self.results else True
        return {"ok": ok, "exit": 0 if ok else 1, "attempts": [{"exit": 0 if ok else 1, "seconds": 0.1}]}


class Tmp(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = self.td.name
        self.log = Log(os.path.join(self.root, "logs"), stderr=False)

    def tearDown(self):
        self.log.close()
        self.td.cleanup()

    def cfg(self, jobs, **health_over):
        c = {"logs": "logs", "jobs": jobs, "health": dict(rcfg.DEFAULTS["health"], **health_over)}
        path = os.path.join(self.root, "runner.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(c, fh)
        return rcfg.load(path)

    def write_plan(self, rel, date):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"symbol": "TSLA", "date": date}, fh)


class Config(unittest.TestCase):
    def test_example_is_valid(self):
        c = rcfg.load(os.path.join(TRADING, "config", "runner.example.json"))
        self.assertEqual([j["name"] for j in c["jobs"]], ["desk", "news", "pelosi"])

    def test_rejects(self):
        bad = [
            {"argv": "python3 x.py && rm -rf /"},          # shell string, not argv
            {"window": "hourly"}, {"kind": "shell"}, {"name": "Bad Name"},
            {"window": "daily_at"},                        # needs at
            {"window": "daily_at", "at": "25:00"}, {"start": "9:45"}, {"timeout_s": 0},
            {"retries": 9}, {"surprise": 1},
        ]
        for b in bad:
            with self.assertRaises(rcfg.RunnerConfigError, msg=b):
                job(**b)

    def test_duplicate_names_and_bad_alert(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.json")
            for raw in ({"jobs": [{"name": "a", "kind": "command", "window": "session", "argv": ["x"]}] * 2},
                        {"health": {"alert_argv": "notify-send"}}, {"nope": 1}):
                with open(p, "w") as fh:
                    json.dump(raw, fh)
                with self.assertRaises(rcfg.RunnerConfigError, msg=raw):
                    rcfg.load(p)


class Due(unittest.TestCase):
    def check(self, j, when, js=None):
        n = now(when)
        return J.due(j, J.market(n), js or {}, n)

    def test_session_window(self):
        j = job(start="09:45", end="15:30", every_min=15)
        self.assertTrue(self.check(j, "2026-10-19 10:15")[0])
        self.assertFalse(self.check(j, "2026-10-19 09:40")[0])
        self.assertFalse(self.check(j, "2026-10-19 15:30")[0])
        self.assertIn("weekend", self.check(j, "2026-10-18 10:15")[1])
        self.assertIn("Thanksgiving", self.check(j, "2026-11-26 10:15")[1])

    def test_early_close_clamps_end(self):
        j = job(start="09:45", end="15:30")
        self.assertTrue(self.check(j, "2026-11-27 12:50")[0])
        self.assertFalse(self.check(j, "2026-11-27 13:05")[0])     # NYSE closes 13:00 that day

    def test_every_min_with_timer_slack(self):
        j = job(every_min=15)
        last = {"last_attempt_utc": "2026-10-19T14:00:00"}             # 10:00 ET
        self.assertFalse(self.check(j, "2026-10-19 10:10", last)[0])
        self.assertTrue(self.check(j, "2026-10-19 10:14", last)[0])    # 14 min >= 15 - 1 slack

    def test_once_a_day_and_give_up(self):
        j = job(window="daily_at", at="18:30", max_attempts_per_day=2)
        self.assertFalse(self.check(j, "2026-10-18 18:00")[0])
        self.assertTrue(self.check(j, "2026-10-18 18:35")[0])          # daily_at runs on weekends too
        self.assertFalse(self.check(j, "2026-10-18 19:00", {"last_success_date": "2026-10-18"})[0])
        gave = self.check(j, "2026-10-18 19:00", {"attempts_date": "2026-10-18", "attempts_today": 2})
        self.assertEqual(gave, (False, "gave up today after 2 attempts"))
        self.assertFalse(self.check(job(window="trading_day_at", at="18:30"), "2026-10-18 19:00")[0])

    def test_disabled(self):
        self.assertEqual(self.check(job(enabled=False), "2026-10-19 10:15"), (False, "disabled"))


class Execute(unittest.TestCase):
    def test_ok_bad_input_retry_and_timeout(self):
        slept = []
        ok = J.execute([sys.executable, "-c", "print(1)"], TRADING, 10, 2, sleep=slept.append)
        self.assertTrue(ok["ok"])
        self.assertEqual(len(ok["attempts"]), 1)
        bad = J.execute([sys.executable, "-c", "import sys; sys.exit(2)"], TRADING, 10, 2, sleep=slept.append)
        self.assertEqual((bad["ok"], bad["exit"], len(bad["attempts"])), (False, 2, 1))   # not retried
        flaky = J.execute([sys.executable, "-c", "import sys; print('boom', file=sys.stderr); sys.exit(1)"],
                          TRADING, 10, 2, sleep=slept.append)
        self.assertEqual(len(flaky["attempts"]), 3)
        self.assertEqual(slept, [2, 4])
        self.assertIn("boom", flaky["attempts"][-1]["stderr_tail"])
        slow = J.execute([sys.executable, "-c", "import time; time.sleep(5)"], TRADING, 1, 0)
        self.assertTrue(slow["attempts"][0]["timeout"])
        missing = J.execute(["/nonexistent/binary"], TRADING, 5, 0)
        self.assertIn("error", missing["attempts"][0])


class Tick(Tmp):
    def test_desk_job_runs_only_todays_plans(self):
        self.write_plan("trader/plan.json", "2026-10-19")
        self.write_plan("trader/plans/old.json", "2026-10-16")
        self.write_plan("trader/plans/aapl.json", "2026-10-19")
        cfg = self.cfg([{"name": "desk", "kind": "desk", "window": "session"}])
        fx = FakeExec()
        out = tick(cfg, self.root, self.log, now("2026-10-19 10:15"), execute=fx)
        plans = sorted(c[c.index("--plan") + 1] for c in fx.calls)
        self.assertEqual(plans, ["trader/plan.json", "trader/plans/aapl.json"])
        self.assertTrue(all(c[1:4] == ["-m", "desk", "run"] for c in fx.calls))
        self.assertEqual(len(out["ran"]), 2)
        self.assertEqual(read_json(os.path.join(self.root, "logs/runner/heartbeat.json"))["market_open"], True)
        with open(os.path.join(self.root, "logs/runner/runner.jsonl"), encoding="utf-8") as fh:
            lines = [json.loads(x) for x in fh]
        self.assertIn("plan_skipped", [x["event"] for x in lines])

    def test_spacing_between_ticks(self):
        cfg = self.cfg([{"name": "a", "kind": "command", "window": "session", "argv": ["x"], "every_min": 15}])
        fx = FakeExec()
        for t in ("10:00", "10:05", "10:10", "10:15"):
            tick(cfg, self.root, self.log, now("2026-10-19 " + t), execute=fx)
        self.assertEqual(len(fx.calls), 2)        # 10:00 and 10:15

    def test_failures_count_and_alert_once_at_threshold(self):
        flag = os.path.join(self.root, "alert.txt")
        writer = "import sys; open(%r, 'a').write(sys.argv[1] + '\\n')" % flag
        cfg = self.cfg([{"name": "a", "kind": "command", "window": "session", "argv": ["x"], "every_min": 5}],
                       max_consecutive_failures=2, alert_argv=[sys.executable, "-c", writer])
        fx = FakeExec([False, False, False, True])
        for t in ("10:00", "10:05", "10:10"):
            tick(cfg, self.root, self.log, now("2026-10-19 " + t), execute=fx)
        st = read_json(os.path.join(self.root, "logs/runner/state.json"))
        self.assertEqual(st["a"]["consecutive_failures"], 3)
        with open(flag) as fh:
            self.assertEqual(len(fh.readlines()), 1)                 # alert at 2, not again at 3
        tick(cfg, self.root, self.log, now("2026-10-19 10:15"), execute=fx)
        st = read_json(os.path.join(self.root, "logs/runner/state.json"))
        self.assertEqual(st["a"]["consecutive_failures"], 0)

    def test_overlapping_tick_is_skipped(self):
        cfg = self.cfg([{"name": "a", "kind": "command", "window": "session", "argv": ["x"]}])
        fx = FakeExec()
        with TickLock(os.path.join(self.root, "logs/runner/runner.lock")):
            out = tick(cfg, self.root, self.log, now("2026-10-19 10:15"), execute=fx)
        self.assertEqual(out, {"skipped": "locked"})
        self.assertEqual(fx.calls, [])

    def test_dry_run_writes_no_state(self):
        cfg = self.cfg([{"name": "a", "kind": "command", "window": "session", "argv": ["{python}", "{today}"]}])
        fx = FakeExec()
        out = tick(cfg, self.root, self.log, now("2026-10-19 10:15"), dry_run=True, execute=fx)
        self.assertEqual(out["ran"][0]["commands"], [[sys.executable, "2026-10-19"]])
        self.assertEqual(fx.calls, [])
        self.assertIsNone(read_json(os.path.join(self.root, "logs/runner/state.json")))


class Health(Tmp):
    def test_no_heartbeat_fresh_stale_and_failures(self):
        cfg = self.cfg([{"name": "a", "kind": "command", "window": "session", "argv": ["x"]}],
                       max_consecutive_failures=2)
        self.assertFalse(health(cfg, self.root, self.log, now("2026-10-19 10:15"), send_alert=False)["ok"])
        tick(cfg, self.root, self.log, now("2026-10-19 10:15"), execute=FakeExec())
        self.assertTrue(health(cfg, self.root, self.log, now("2026-10-19 10:20"), send_alert=False)["ok"])
        stale = health(cfg, self.root, self.log, now("2026-10-19 11:00"), send_alert=False)
        self.assertFalse(stale["ok"])
        self.assertIn("timer", stale["problems"][0])
        fx = FakeExec([False, False])
        for t in ("11:00", "11:20"):
            tick(cfg, self.root, self.log, now("2026-10-19 " + t), execute=fx)
        bad = health(cfg, self.root, self.log, now("2026-10-19 11:21"), send_alert=False)
        self.assertIn("job a failed 2 times in a row", bad["problems"])

    def test_unknown_calendar_year_is_a_problem(self):
        cfg = self.cfg([])
        tick(cfg, self.root, self.log, now("2028-03-01 10:15"), execute=FakeExec())
        res = health(cfg, self.root, self.log, now("2028-03-01 10:16"), send_alert=False)
        self.assertTrue(any("calendar" in p for p in res["problems"]))


class Cli(unittest.TestCase):
    def _main(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def test_tick_runs_real_desk_subprocess_then_health_and_status(self):
        """Integration: the runner launches the desk as a child process (offline fixtures)."""
        with tempfile.TemporaryDirectory() as d:
            logs = os.path.join(d, "logs")
            desk = ["{python}", "-m", "desk", "run", "--offline",
                    os.path.join(FIX, "trader-timemachine", "TSLA-60d5m.json.gz"),
                    "--news-offline", os.path.join(FIX, "trader-news", "yahoo-TSLA.xml"),
                    "--symbol", "TSLA", "--date", "2026-10-19", "--entry", "364.18", "--stop", "358.32",
                    "--target", "370.04", "--entry-time", "10:15 AM", "--now", "2026-10-19 10:15",
                    "--replays", "500", "--sim-config", "/nonexistent", "--desk-config", "/nonexistent",
                    "--trader-config", os.path.join(VENDOR, "trader-budget", "config.example.json"),
                    "--logs", logs]
            cfgp = os.path.join(d, "runner.json")
            with open(cfgp, "w") as fh:
                json.dump({"logs": logs, "jobs": [{"name": "desk-fixture", "kind": "command",
                                                   "window": "session", "argv": desk, "timeout_s": 120}]}, fh)
            base = ["--config", cfgp, "--root", TRADING, "--quiet", "--now", "2026-10-19 10:15"]
            code, _, err = self._main(base + ["tick"])
            self.assertEqual(code, 0, err)
            st = read_json(os.path.join(logs, "runner", "state.json"))
            self.assertEqual(st["desk-fixture"]["consecutive_failures"], 0)
            with open(os.path.join(logs, "desk", "index.jsonl"), encoding="utf-8") as fh:
                self.assertEqual(json.loads(fh.readline())["decision"], "BEKLE")
            code, out, _ = self._main(base[:-1] + ["2026-10-19 10:16", "health", "--no-alert"])
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(out)["ok"])
            code, out, _ = self._main(base + ["status"])
            self.assertEqual(json.loads(out)["desk_runs"][0]["symbol"], "TSLA")

    def test_bad_config_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.json")
            with open(p, "w") as fh:
                fh.write("{not json")
            code, _, err = self._main(["--config", p, "--root", d, "tick"])
        self.assertEqual(code, 2)
        self.assertIn("not valid JSON", err)


class Safety(unittest.TestCase):
    def test_runner_never_uses_a_shell_or_broker(self):
        root = os.path.join(TRADING, "runner")
        for dirpath, _, files in os.walk(root):
            for name in files:
                if not name.endswith(".py"):
                    continue
                with open(os.path.join(dirpath, name), encoding="utf-8") as fh:
                    src = fh.read()
                tree = ast.parse(src)
                for node in ast.walk(tree):
                    if isinstance(node, ast.keyword) and node.arg == "shell":
                        self.fail("%s passes shell=" % name)
                self.assertNotIn("os.system", src, name)
                for word in ("trader-broker", "ticket.py", "orders.json", "alpaca"):
                    self.assertNotIn(word, src.lower(), name)


if __name__ == "__main__":
    unittest.main()
