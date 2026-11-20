"""Desk thresholds. Every number that can flip a decision lives here, not in code."""

import copy
import json
import os

DEFAULTS = {
    "news_hours": 12,
    "scanner": {"rvol_high": 1.5, "rvol_low": 0.7, "range_high": 1.5, "gap_pct_high": 2.0},
    "entry_exit": {"min_stop_atr": 1.0, "max_chase_r": 0.5},
    "data_gate": {"max_bar_age_min": 30, "min_pool_sessions": 30},
    "decision": {
        "base_models": ["bar_bootstrap", "block_bootstrap"],
        "min_edge_r": 0.0,
        "stress_floor_r": -0.15,
        "min_history_trades": 20,
        "max_unresolved_warn": 1,
        "min_stance_score": 0.0,
    },
}


class DeskConfigError(ValueError):
    pass


def _merge(base, over, path=""):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if k not in base:
            raise DeskConfigError("unknown desk setting %r" % (path + k))
        out[k] = _merge(base[k], v, path + k + ".") if isinstance(base[k], dict) else v
    return out


def load(path=None):
    cfg = DEFAULTS
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            try:
                raw = json.load(fh)
            except ValueError as e:
                raise DeskConfigError("%s is not valid JSON: %s" % (path, e))
        cfg = _merge(cfg, raw)
    d = cfg["decision"]
    if not d["base_models"]:
        raise DeskConfigError("decision.base_models must not be empty")
    if cfg["news_hours"] <= 0 or cfg["news_hours"] > 168:
        raise DeskConfigError("news_hours must be in (0, 168]")
    return cfg
