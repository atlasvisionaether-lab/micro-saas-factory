"""Load the vendored trader-timemachine module so sim/ reuses its plan checks,
Yahoo bar parsing and history replay instead of re-implementing them."""

import importlib.util
import os

VENDOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "vendor", "day-trader-skill")
_TM = None


def timemachine():
    global _TM
    if _TM is None:
        path = os.path.join(VENDOR, "trader-timemachine", "timemachine.py")
        spec = importlib.util.spec_from_file_location("vendor_timemachine", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _TM = mod
    return _TM
