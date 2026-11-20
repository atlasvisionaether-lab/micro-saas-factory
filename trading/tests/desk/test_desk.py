"""Offline tests for trading/desk. Run from trading/:
    python3 -m unittest discover -s tests -t .
"""

import ast
import copy
import datetime
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from desk import config as deskcfg
from desk.__main__ import main
from desk.agents import DEFAULT_AGENTS, EntryExit, News, Scanner, Skeptic
from desk.bundle import Bundle, load_news
from desk.logs import write_run
from desk.protocol import run_desk
from desk.report import render
from desk.schema import Message
from sim import config as simcfg
from sim.data import load_market
from sim.run import run_sim
from sim.vendor_bridge import VENDOR, timemachine

TRADING = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIX = os.path.join(VENDOR, "tests", "fixtures")
CHART = os.path.join(FIX, "trader-timemachine", "TSLA-60d5m.json.gz")
RSS = os.path.join(FIX, "trader-news", "yahoo-TSLA.xml")
TRADER_CFG = os.path.join(VENDOR, "trader-budget", "config.example.json")
NOW = "2026-10-19 10:15"
PLAN = {"symbol": "TSLA", "side": "buy", "date": "2026-10-19", "entry": 364.18, "stop": 358.32,
        "target": 370.04, "entry_time": "10:15 AM", "setup": "orb"}

_CACHE = {}


def base_inputs():
    """Market + sim are the slow part: build once, hand out deep copies."""
    if not _CACHE:
        tm = timemachine()
        now = tm.parse_now(NOW)
        plan = tm.normalize_plan(dict(PLAN))
        market = load_market(tm.read_offline(CHART, "TSLA"), plan, now)
        cfg = simcfg.load(None, {"replays": 2000, "risk_usd": 50})
        with open(RSS, "rb") as fh:
            rss = fh.read()
        with open(TRADER_CFG, encoding="utf-8") as fh:
            trader = json.load(fh)
        _CACHE.update(now=now, plan=plan, market=market, sim=run_sim(market, plan, cfg, now), rss=rss,
                      trader=trader)
    return _CACHE


def bundle(**over):
    c = base_inputs()
    news, err = load_news("TSLA", c["now"], 12, rss_bytes=c["rss"])
    kw = dict(plan=copy.deepcopy(c["plan"]), market=c["market"], sim=copy.deepcopy(c["sim"]),
              trader_cfg=copy.deepcopy(c["trader"]), desk_cfg=deskcfg.load(None), now_utc=c["now"],
              news=news, news_error=err)
    kw.update(over)
    return Bundle(**kw)


def by_round(run, rnd):
    return [m for m in run["transcript"] if m.round == rnd]


class Schema(unittest.TestCase):
    def test_validation(self):
        Message(id="x", round="R1", agent="a", kind="claim", topic="t", text="ok")
        for bad in ({"round": "R9"}, {"kind": "vote"}, {"stance": "maybe"}, {"severity": "fatal"},
                    {"confidence": 1.5}, {"kind": "challenge"}):
            kw = dict(id="x", round="R1", agent="a", kind="claim", topic="t", text="ok")
            kw.update(bad)
            with self.assertRaises(ValueError, msg=bad):
                Message(**kw)

    def test_example_config_valid_and_unknown_keys_rejected(self):
        deskcfg.load(os.path.join(TRADING, "config", "desk.example.json"))
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"decision": {"typo": 1}}, fh)
        try:
            with self.assertRaises(deskcfg.DeskConfigError):
                deskcfg.load(fh.name)
        finally:
            os.unlink(fh.name)


class Golden(unittest.TestCase):
    """The TSLA reel trade, 10:15 AM, with that morning's headlines."""

    @classmethod
    def setUpClass(cls):
        cls.b = bundle()
        cls.desk = run_desk(cls.b)

    def test_decision_is_wait_with_named_failures(self):
        d = self.desk["decision"]
        self.assertEqual(d["decision"], "BEKLE")
        self.assertEqual(d["vetoes"], [])
        self.assertEqual(set(d["failed"]), {"edge_bar_bootstrap", "edge_block_bootstrap", "history_r", "stance"})

    def test_news_sees_the_morning_catalysts(self):
        claims = [m for m in by_round(self.desk, "R1") if m.agent == "news"]
        cat = next(m for m in claims if m.topic == "catalyst")
        self.assertEqual(cat.evidence["items"], 16)               # 18 in the feed, 2 after 10:15
        self.assertTrue({"deal", "earnings"} <= set(cat.evidence["tags"]))
        self.assertEqual(cat.stance, "for")                       # +2.7 % on the day, same side as the plan

    def test_rounds_in_order_and_ids_unique(self):
        rounds = [m.round for m in self.desk["transcript"]]
        self.assertEqual(rounds, sorted(rounds))
        ids = [m.id for m in self.desk["transcript"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(by_round(self.desk, "R4")), 1)

    def test_skeptic_challenges_every_for_claim(self):
        fors = {m.id for m in by_round(self.desk, "R1") if m.stance == "for" and m.agent != "skeptic"}
        hit = {m.replies_to for m in by_round(self.desk, "R2") if m.agent == "skeptic" and m.kind == "challenge"}
        self.assertTrue(fors)
        self.assertEqual(fors - hit, set())

    def test_every_serious_challenge_gets_one_answer(self):
        serious = [m for m in by_round(self.desk, "R2") if m.kind == "challenge" and m.severity != "info"]
        answers = by_round(self.desk, "R3")
        self.assertEqual(sorted(m.id for m in serious), sorted(a.replies_to for a in answers))
        self.assertEqual(len(self.desk["contradictions"]), len(serious))
        for c in self.desk["contradictions"]:
            reply = next(a for a in answers if a.id == c["reply"])
            self.assertEqual(c["status"], "resolved" if reply.kind == "concede" else "unresolved")

    def test_concession_lowers_final_confidence(self):
        for c in self.desk["contradictions"]:
            if c["status"] == "resolved":
                claim = next(m for m in self.desk["transcript"] if m.id == c["claim"])
                self.assertLess(self.desk["final_confidence"][c["claim"]], claim.confidence)

    def test_deterministic(self):
        again = run_desk(bundle())
        self.assertEqual([m.to_dict() for m in again["transcript"]],
                         [m.to_dict() for m in self.desk["transcript"]])

    def test_r1_is_independent_of_agent_order(self):
        rev = run_desk(bundle(), tuple(reversed(DEFAULT_AGENTS)))

        def r1(run):
            return sorted((m.agent, m.topic, m.text, m.confidence) for m in by_round(run, "R1"))
        self.assertEqual(r1(rev), r1(self.desk))

    def test_report_shows_decision_conditions_and_transcript(self):
        md = render(self.desk, self.b)
        for s in ("— **BEKLE**", "Sorumluluk sınırı", "## Karar koşulları", "## Çelişkiler",
                  "### R0 · Veri kapısı", "### R3 · Savunma", "### R4 · Karar"):
            self.assertIn(s, md)


class Vetoes(unittest.TestCase):
    def assertVeto(self, b, agent):
        run = run_desk(b)
        self.assertEqual(run["decision"]["decision"], "GEÇ")
        self.assertIn(agent, {v["agent"] for v in run["decision"]["vetoes"]})
        return run

    def test_reward_risk_below_limit(self):
        b = bundle()
        b.trader_cfg["min_reward_risk"] = 1.5
        self.assertVeto(b, "entry_exit")

    def test_entry_outside_window(self):
        b = bundle()
        b.trader_cfg["no_entries_before"] = "10:30"
        self.assertVeto(b, "entry_exit")

    def test_risk_per_share_above_max_loss(self):
        b = bundle()
        b.trader_cfg["max_loss_per_trade_usd"] = 5
        self.assertVeto(b, "skeptic")

    def test_stale_data_while_session_is_live(self):
        tm = timemachine()
        b = bundle(now_utc=tm.parse_now("2026-10-19 11:30"))   # data ends 10:40, the session is live
        run = self.assertVeto(b, "gate")
        self.assertIn("bayat", run["decision"]["summary"])

    def test_halt_headline(self):
        b = bundle()
        b.news = [dict(b.news[0], tags=["halt"])] + b.news[1:]
        self.assertVeto(b, "news")

    def test_every_model_negative(self):
        b = bundle()
        for s in b.sim["models"].values():
            s["expectancy_r"], s["expectancy_r_ci"] = -0.3, (-0.4, -0.2)
        self.assertVeto(b, "skeptic")


class Paths(unittest.TestCase):
    def _strong(self, b):
        for s in b.sim["models"].values():
            s["expectancy_r"], s["expectancy_r_ci"] = 0.25, (0.2, 0.3)
            s["p_win"], s["p_loss"], s["p_exit_target"], s["p_exit_stop"] = 0.6, 0.3, 0.5, 0.25
        b.sim["history"].update(triggered=40, target=24, stop=10, avg_R=0.3)
        return b

    def test_al_when_every_condition_holds(self):
        b = self._strong(bundle())
        b.desk_cfg["decision"]["min_stance_score"] = -99
        b.desk_cfg["decision"]["max_unresolved_warn"] = 99
        run = run_desk(b)
        self.assertEqual(run["decision"]["decision"], "AL", run["decision"]["failed"])
        self.assertIn("paper", run["decision"]["summary"])

    def test_strong_numbers_still_wait_on_negative_stance(self):
        b = self._strong(bundle())
        b.desk_cfg["decision"]["min_stance_score"] = 50
        run = run_desk(b)
        self.assertEqual(run["decision"]["decision"], "BEKLE")
        self.assertEqual(run["decision"]["failed"], ["stance"])

    def test_no_news_is_a_warning_not_a_veto(self):
        run = run_desk(bundle(news=None, news_error="offline"))
        gate = [m for m in by_round(run, "R0") if m.topic == "news_data"]
        self.assertEqual(gate[0].severity, "warn")
        self.assertNotEqual(run["decision"]["decision"], "GEÇ")

    def test_unexplained_volume_is_challenged_by_news(self):
        b = bundle(news=[])
        b.desk_cfg["scanner"]["rvol_high"] = 0.5          # make today's volume count as unusual
        run = run_desk(b)
        vol = next(m for m in by_round(run, "R1") if m.topic == "volume")
        self.assertEqual(vol.stance, "for")
        news_ch = [m for m in by_round(run, "R2") if m.agent == "news" and m.replies_to == vol.id]
        self.assertEqual(len(news_ch), 1)

    def test_agent_cannot_speak_out_of_turn(self):
        class Rogue(Scanner):
            name = "rogue"

            def analyze(self, b):
                return [self.msg("R2", "challenge", "x", "too early", replies_to="R1-x-1")]
        with self.assertRaises(ValueError):
            run_desk(bundle(), (Rogue, News, EntryExit, Skeptic))


class LogsAndCli(unittest.TestCase):
    ARGS = ["run", "--symbol", "TSLA", "--date", "2026-10-19", "--entry", "364.18", "--stop", "358.32",
            "--target", "370.04", "--entry-time", "10:15 AM", "--offline", CHART, "--news-offline", RSS,
            "--now", NOW, "--replays", "500", "--sim-config", "/nonexistent", "--desk-config", "/nonexistent",
            "--trader-config", TRADER_CFG]

    def _run(self, extra):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(self.ARGS + list(extra))
        return code, out.getvalue(), err.getvalue()

    def test_run_writes_artifacts_and_index(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, err = self._run(["--logs", d])
            self.assertEqual(code, 0, err)
            run_dir = os.path.join(d, "desk", "2026-10-19", "20261019T141500Z-TSLA")
            for f in ("transcript.jsonl", "decision.json", "sim.json", "sim.md", "report.md"):
                self.assertTrue(os.path.exists(os.path.join(run_dir, f)), f)
            with open(os.path.join(run_dir, "transcript.jsonl"), encoding="utf-8") as fh:
                lines = [json.loads(x) for x in fh]
            self.assertEqual(lines[-1]["kind"], "decision")
            with open(os.path.join(d, "desk", "index.jsonl"), encoding="utf-8") as fh:
                idx = [json.loads(x) for x in fh]
            with open(os.path.join(run_dir, "decision.json"), encoding="utf-8") as fh:
                self.assertEqual(idx[-1]["decision"], json.load(fh)["decision"]["decision"])
            self.assertIn("Masa kararı", out)

    def test_json_no_log(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, _ = self._run(["--logs", d, "--no-log", "--json"])
            self.assertEqual(os.listdir(d), [])
        self.assertEqual(code, 0)
        self.assertIn(json.loads(out)["decision"]["decision"], ("AL", "BEKLE", "GEÇ"))

    def test_bad_input_exit_2(self):
        code, _, err = self._run(["--entry-time", "10:17 AM"])
        self.assertEqual(code, 2)
        self.assertIn("5-minute grid", err)


class Safety(unittest.TestCase):
    def test_desk_has_no_network_or_broker_path(self):
        root = os.path.join(TRADING, "desk")
        for dirpath, _, files in os.walk(root):
            for name in files:
                if not name.endswith(".py"):
                    continue
                with open(os.path.join(dirpath, name), encoding="utf-8") as fh:
                    src = fh.read()
                tree = ast.parse(src)
                mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
                mods |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
                self.assertFalse({"urllib.request", "requests", "http.client", "socket", "subprocess"} & mods, name)
                for word in ("trader-broker", "ticket.py", "orders.json", "alpaca"):
                    self.assertNotIn(word, src.lower(), name)


if __name__ == "__main__":
    unittest.main()
