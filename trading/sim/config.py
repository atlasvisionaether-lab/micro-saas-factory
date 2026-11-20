"""Simulation settings: defaults, merge with trader/sim.json, validate."""

import copy
import json
import os

from .models import MODELS

DEFAULTS = {
    "replays": 10000, "seed": 19, "models": list(MODELS), "window": 2, "block_size_bars": 6,
    "breakeven_band_r": 0.1, "commission_per_share_usd": 0.0, "slippage_bps": 5.0,
    "confidence_level": 0.95, "risk_usd": None,
    "regime_shock": {"vol_multiplier": 2.0, "gap_prob": 0.05, "gap_size_r": 1.5},
    "sequence": {"n_trades": 50, "n_sequences": 5000, "risk_frac": 0.01, "dd_threshold": 0.10},
}


class ConfigError(ValueError):
    pass


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if k not in base:
            raise ConfigError("unknown setting %r" % k)
        out[k] = _merge(base[k], v) if isinstance(base[k], dict) and isinstance(v, dict) else v
    return out


def _rng(cfg, path, lo, hi, kind=float):
    obj = cfg
    for p in path[:-1]:
        obj = obj[p]
    v = obj[path[-1]]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (kind is int and int(v) != v) or not lo <= v <= hi:
        raise ConfigError("%s must be %s in [%s, %s], got %r" % (".".join(path), kind.__name__, lo, hi, v))


def validate(cfg):
    _rng(cfg, ["replays"], 100, 1_000_000, int)
    _rng(cfg, ["seed"], 0, 2**32 - 1, int)
    _rng(cfg, ["window"], 0, 10, int)
    _rng(cfg, ["block_size_bars"], 1, 78, int)
    _rng(cfg, ["breakeven_band_r"], 0.0, 1.0)
    _rng(cfg, ["commission_per_share_usd"], 0.0, 1.0)
    _rng(cfg, ["slippage_bps"], 0.0, 200.0)
    if cfg["confidence_level"] not in (0.90, 0.95, 0.99):
        raise ConfigError("confidence_level must be 0.90, 0.95 or 0.99")
    if cfg["risk_usd"] is not None:
        _rng(cfg, ["risk_usd"], 0.01, 1e9)
    _rng(cfg, ["regime_shock", "vol_multiplier"], 0.1, 10.0)
    _rng(cfg, ["regime_shock", "gap_prob"], 0.0, 1.0)
    _rng(cfg, ["regime_shock", "gap_size_r"], 0.0, 20.0)
    _rng(cfg, ["sequence", "n_trades"], 1, 10_000, int)
    _rng(cfg, ["sequence", "n_sequences"], 100, 100_000, int)
    _rng(cfg, ["sequence", "risk_frac"], 0.0001, 0.25)
    _rng(cfg, ["sequence", "dd_threshold"], 0.01, 0.99)
    models = cfg["models"]
    if not isinstance(models, list) or not models or any(m not in MODELS for m in models):
        raise ConfigError("models must be a non-empty list from %s" % ", ".join(MODELS))
    if len(set(models)) != len(models):
        raise ConfigError("models has duplicates")
    return cfg


def load(path=None, overrides=None):
    cfg = DEFAULTS
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            try:
                raw = json.load(fh)
            except ValueError as e:
                raise ConfigError("%s is not valid JSON: %s" % (path, e))
        if not isinstance(raw, dict):
            raise ConfigError("%s must hold a JSON object" % path)
        cfg = _merge(cfg, raw)
    cfg = _merge(cfg, {k: v for k, v in (overrides or {}).items() if v is not None})
    return validate(cfg)
