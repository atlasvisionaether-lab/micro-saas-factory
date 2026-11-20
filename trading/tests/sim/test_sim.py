"""Offline tests for trading/sim. Run from trading/:
    python3 -m unittest discover -s tests -t .
"""

import ast
import io
import json
import math
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

import numpy as np

from sim import config as cfgmod
from sim.__main__ import main
from sim.data import SimError, load_market
from sim.engine import STOP, TARGET, TIME, run_paths
from sim.metrics import disagreement, sequence_risk, summarize, wilson
from sim.models import MODELS, block_bootstrap, gbm, generate, regime_shock
from sim.run import run_sim
from sim.vendor_bridge import VENDOR, timemachine

TRADING = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIX = os.path.join(VENDOR, "tests", "fixtures", "trader-timemachine", "TSLA-60d5m.json.gz")
NOW = "2026-10-19 10:50"
PLAN_RAW = {"symbol": "TSLA", "side": "buy", "date": "2026-10-19", "entry": 364.18, "stop": 358.32,
            "target": 370.04, "entry_time": "10:15 AM", "setup": "orb"}


def bars(*rows):
    """One path from (o,h,l,c) ratio rows."""
    return np.array([rows], dtype=float)


class Engine(unittest.TestCase):
    def test_target_stop_time_and_tie(self):
        rel = np.concatenate([
            bars((1, 1.005, 0.999, 1.004), (1, 1.012, 1.0, 1.01)),     # target on bar 2
            bars((1, 1.001, 0.985, 0.99), (1, 1, 1, 1)),               # stop on bar 1
            bars((1, 1.002, 0.998, 1.001), (1, 1.003, 0.999, 1.002)),  # neither
            bars((1, 1.02, 0.98, 1.0), (1, 1, 1, 1)),                  # both in one bar -> stop
        ])
        r = run_paths(rel, 100.0, 99.0, 101.0)
        self.assertEqual(r["outcome"].tolist(), [TARGET, STOP, TIME, STOP])
        np.testing.assert_allclose(r["r_net"][:2], [1.0, -1.0])
        self.assertAlmostEqual(r["r_net"][2], 100 * 1.001 * 1.002 - 100, places=9)
        self.assertEqual(r["exit_bar"].tolist(), [1, 0, 1, 0])

    def test_gap_through_stop_fills_at_open(self):
        r = run_paths(bars((0.97, 0.98, 0.96, 0.975)), 100.0, 99.0, 101.0)
        self.assertEqual(r["outcome"][0], STOP)
        self.assertAlmostEqual(r["exit_price"][0], 97.0)
        self.assertAlmostEqual(r["r_net"][0], -3.0)
        self.assertEqual(r["gap_stops"], 1)

    def test_short_side_mirrors(self):
        r = run_paths(bars((1, 1.001, 0.985, 0.99)), 100.0, 101.0, 99.0, side="sell")
        self.assertEqual(r["outcome"][0], TARGET)
        self.assertAlmostEqual(r["r_net"][0], 1.0)

    def test_costs_in_r(self):
        r = run_paths(bars((1, 1.012, 1.0, 1.01)), 100.0, 99.0, 101.0, slippage_bps=10, commission_per_share=0.01)
        # slippage (100 + 101) * 10bps = 0.201, commission 0.02 -> 0.221 / risk 1.0
        self.assertAlmostEqual(r["r_net"][0], 1.0 - 0.221, places=9)
        self.assertAlmostEqual(r["r_gross"][0], 1.0)

    def test_bad_plan_rejected(self):
        with self.assertRaises(ValueError):
            run_paths(bars((1, 1, 1, 1)), 100.0, 101.0, 102.0)


class Models(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        c = np.exp(rng.normal(0, 0.002, size=(40, 78)))
        o = np.ones_like(c)
        self.pool = np.stack([o, np.maximum(o, c) * 1.001, np.minimum(o, c) * 0.999, c], axis=-1)
        self.pool[:, 0, :] = np.nan

    def test_shapes_and_bar_consistency(self):
        for m in MODELS:
            rel = generate(m, self.pool, 9, 77, 500, 19, entry=100.0, risk=1.0)
            self.assertEqual(rel.shape, (500, 68, 4), m)
            self.assertTrue(np.all(rel[..., 1] >= np.maximum(rel[..., 0], rel[..., 3]) - 1e-12), m)
            self.assertTrue(np.all(rel[..., 2] <= np.minimum(rel[..., 0], rel[..., 3]) + 1e-12), m)

    def test_seed_reproducible_and_model_streams_independent(self):
        a = generate("bar_bootstrap", self.pool, 9, 77, 100, 19)
        b = generate("bar_bootstrap", self.pool, 9, 77, 100, 19)
        c = generate("bar_bootstrap", self.pool, 9, 77, 100, 20)
        np.testing.assert_array_equal(a, b)
        self.assertFalse(np.array_equal(a, c))

    def test_block_bootstrap_copies_contiguous_session_blocks(self):
        rel = generate("block_bootstrap", self.pool, 9, 77, 50, 3, block_size_bars=6)
        for path in rel[:5]:
            first = path[:6, 3]
            hits = [s for s in range(40) if np.array_equal(self.pool[s, 10:16, 3], first)]
            self.assertTrue(hits)

    def test_gbm_barrier_odds_match_theory(self):
        """Zero-drift Brownian motion: P(hit +a before -b) = b / (a + b). Target 2R, stop 1R -> 1/3.
        Checks the bridge max/min draws, not only the closes."""
        pool = np.ones((5, 400, 4))
        rel = gbm(pool, 0, 399, 40000, np.random.default_rng(7), sigma=0.003)
        r = run_paths(rel, 100.0, 100.0 * math.exp(-0.01), 100.0 * math.exp(0.02))
        hit = r["outcome"] != TIME
        self.assertGreater(hit.mean(), 0.97)
        p_up = (r["outcome"] == TARGET).sum() / hit.sum()
        self.assertAlmostEqual(p_up, 1 / 3, delta=0.012)

    def test_gbm_price_is_martingale(self):
        rel = gbm(np.ones((5, 100, 4)), 0, 99, 200000, np.random.default_rng(1), sigma=0.004)
        self.assertAlmostEqual(np.prod(rel[..., 3], axis=1).mean(), 1.0, delta=0.002)

    def test_regime_shock_gaps_are_adverse_and_drift_not_amplified(self):
        # same RNG for both: regime_shock draws its blocks first, then the gaps
        base = block_bootstrap(self.pool, 9, 77, 4000, np.random.default_rng(5))
        shock = regime_shock(self.pool, 9, 77, 4000, np.random.default_rng(5), vol_multiplier=1.0,
                             gap_prob=1.0, gap_size_r=2.0, entry=100.0, risk=1.0)
        ratio = shock[..., 3] / base[..., 3]
        self.assertTrue(np.allclose(ratio.prod(axis=1), 0.98))     # exactly one -2% gap per path
        big = generate("regime_shock", self.pool, 9, 77, 20000, 5, vol_multiplier=3.0, gap_prob=0.0)
        mu = np.log(self.pool[:, 10:78, 3]).mean()
        self.assertAlmostEqual(np.log(big[..., 3]).mean(), mu, delta=2e-4)


class Metrics(unittest.TestCase):
    def test_wilson_known_value(self):
        lo, hi = wilson(50, 100, 1.96)
        self.assertAlmostEqual(lo, 0.4038, places=4)
        self.assertAlmostEqual(hi, 0.5962, places=4)

    def test_classes_and_expectancy(self):
        r = np.array([1.0, 0.05, -0.05, -1.0, 2.0])
        s = summarize({"r_net": r, "r_gross": r, "outcome": np.array([1, 0, 0, 2, 1])}, band_r=0.1, risk_usd=50)
        self.assertEqual((s["p_win"], s["p_breakeven"], s["p_loss"]), (0.4, 0.4, 0.2))
        self.assertAlmostEqual(s["expectancy_r"], 0.4)
        self.assertAlmostEqual(s["expectancy_usd"], 20.0)
        self.assertAlmostEqual(s["profit_factor"], 3.05 / 1.05)
        self.assertAlmostEqual(s["p_win"] + s["p_breakeven"] + s["p_loss"], 1.0)

    def test_sequence_risk_bounds(self):
        rng = np.random.default_rng(0)
        q = sequence_risk(np.array([-1.0]), rng, n_trades=10, n_seq=200, risk_frac=0.01)
        self.assertAlmostEqual(q["final_return_median"], 0.99 ** 10 - 1)
        self.assertAlmostEqual(q["max_drawdown_median"], 1 - 0.99 ** 10)
        self.assertEqual(q["p_losing_sequence"], 1.0)

    def test_disagreement_flags(self):
        d = disagreement({"a": {"expectancy_r": 0.1, "expectancy_r_ci": (0.05, 0.15)},
                          "b": {"expectancy_r": -0.1, "expectancy_r_ci": (-0.15, -0.05)}})
        self.assertIn("models disagree on the sign of expectancy", d["flags"])
        self.assertEqual(d["min_model"], "b")


class Config(unittest.TestCase):
    def test_example_file_is_valid(self):
        cfg = cfgmod.load(os.path.join(TRADING, "config", "sim.example.json"))
        self.assertEqual(cfg["replays"], 10000)

    def test_rejects_bad_values(self):
        for bad in ({"replays": 5}, {"models": ["magic"]}, {"breakeven_band_r": -1},
                    {"confidence_level": 0.8}, {"nope": 1}, {"regime_shock": {"gap_prob": 2}}):
            with self.assertRaises(cfgmod.ConfigError, msg=bad):
                cfgmod.load(None, bad)


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tm = timemachine()
        cls.now = tm.parse_now(NOW)
        cls.plan = tm.normalize_plan(dict(PLAN_RAW))
        cls.market = load_market(tm.read_offline(FIX, "TSLA"), cls.plan, cls.now)
        cls.cfg = cfgmod.load(None, {"risk_usd": 50})
        cls.doc = run_sim(cls.market, cls.plan, cls.cfg, cls.now)

    def test_pool_matches_vendor(self):
        self.assertEqual(self.market.pool.shape, (59, 78, 4))
        self.assertEqual(self.market.entry_bar, 8)
        self.assertEqual(self.market.last_bar, 77)

    def test_bar_bootstrap_agrees_with_vendor_time_machine(self):
        """Vendor (Python random, seed 19): target 29.38 %, stop 25.48 %, neither 45.14 %.
        Same method, different RNG: must agree within sampling error (~1.4 pp at 3 sigma)."""
        m = self.doc["models"]["bar_bootstrap"]
        self.assertAlmostEqual(m["p_exit_target"], 0.2938, delta=0.014)
        self.assertAlmostEqual(m["p_exit_stop"], 0.2548, delta=0.014)
        self.assertAlmostEqual(m["p_exit_time"], 0.4514, delta=0.015)

    def test_history_replay_matches_vendor(self):
        h = self.doc["history"]
        self.assertEqual((h["sessions"], h["triggered"], h["target"], h["stop"], h["close"]), (59, 33, 13, 15, 5))

    def test_every_model_reported_with_classes_summing_to_one(self):
        self.assertEqual(set(self.doc["models"]), set(MODELS))
        for m, s in self.doc["models"].items():
            self.assertEqual(s["n"], 10000)
            self.assertAlmostEqual(s["p_win"] + s["p_breakeven"] + s["p_loss"], 1.0, msg=m)
            lo, hi = s["expectancy_r_ci"]
            self.assertLess(lo, s["expectancy_r"])
            self.assertLess(s["expectancy_r"], hi)

    def test_deterministic(self):
        again = run_sim(self.market, self.plan, self.cfg, self.now)
        self.assertEqual(json.dumps(again, default=list, sort_keys=True),
                         json.dumps(self.doc, default=list, sort_keys=True))

    def test_stress_has_heavier_tail(self):
        s, b = self.doc["models"]["regime_shock"], self.doc["models"]["block_bootstrap"]
        self.assertGreater(s["gap_stops"], b["gap_stops"])
        self.assertLess(s["avg_loss_r"], b["avg_loss_r"])

    def test_entry_not_in_data_is_an_error(self):
        tm = timemachine()
        p = tm.normalize_plan(dict(PLAN_RAW, entry_time="11:30 AM"))
        with self.assertRaises(SimError):
            load_market(tm.read_offline(FIX, "TSLA"), p, self.now)


class Cli(unittest.TestCase):
    ARGS = ["run", "--symbol", "TSLA", "--date", "2026-10-19", "--entry", "364.18", "--stop", "358.32",
            "--target", "370.04", "--entry-time", "10:15 AM", "--offline", FIX, "--now", NOW,
            "--replays", "500", "--config", "/nonexistent", "--trader-config", "/nonexistent"]

    def _run(self, extra=()):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(self.ARGS + list(extra))
        return code, out.getvalue(), err.getvalue()

    def test_markdown_report_has_tables_and_disclaimer(self):
        code, out, _ = self._run()
        self.assertEqual(code, 0)
        for s in ("Sorumluluk sınırı", "| Model | Kazanç | Başabaş | Kayıp | Expectancy (R)", "Varsayımlar",
                  "Veri kalitesi", "Tarihsel tekrar", "Seri riski"):
            self.assertIn(s, out)

    def test_json_and_write(self):
        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            os.chdir(d)
            try:
                code, out, err = self._run(["--json", "--write"])
                self.assertTrue(os.path.exists("trader/sim/TSLA-2026-10-19.md"))
                with open("trader/sim/TSLA-2026-10-19.json", encoding="utf-8") as fh:
                    self.assertEqual(json.load(fh)["plan"]["symbol"], "TSLA")
            finally:
                os.chdir(cwd)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["source"], "offline:TSLA-60d5m.json.gz")

    def test_bad_input_exit_code_2(self):
        code, _, err = self._run(["--models", "magic"])
        self.assertEqual(code, 2)
        self.assertIn("models", err)


class Safety(unittest.TestCase):
    def test_sim_never_touches_the_broker_or_writes_orders(self):
        sim_dir = os.path.join(TRADING, "sim")
        for name in os.listdir(sim_dir):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(sim_dir, name), encoding="utf-8") as fh:
                src = fh.read()
            tree = ast.parse(src)
            mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            mods |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            self.assertFalse({"urllib.request", "requests", "http.client", "socket", "subprocess"} & mods, name)
            for word in ("trader-broker", "ticket.py", "orders.json", "alpaca"):
                self.assertNotIn(word, src.lower(), name)


if __name__ == "__main__":
    unittest.main()
