"""Load vendored day-trader-skill modules so trading/ reuses their plan checks,
Yahoo bar parsing, news parsing and history replay instead of re-implementing them."""

import importlib.util
import os

VENDOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "vendor", "day-trader-skill")
_CACHE = {}


def load(folder, name):
    key = (folder, name)
    if key not in _CACHE:
        path = os.path.join(VENDOR, folder, name + ".py")
        spec = importlib.util.spec_from_file_location("vendor_" + name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _CACHE[key] = mod
    return _CACHE[key]


def timemachine():
    return load("trader-timemachine", "timemachine")


def news():
    return load("trader-news", "news")
