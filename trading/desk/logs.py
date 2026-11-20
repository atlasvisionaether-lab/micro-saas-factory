"""Run artifacts. One folder per run, plus an append-only index for monitoring.

logs/desk/<plan date>/<run id>/
    transcript.jsonl   every message, one per line, in protocol order
    decision.json      decision, checks, vetoes, contradictions, final confidences
    sim.json, sim.md   the simulation document behind the debate
    report.md          the human-readable desk report
logs/desk/index.jsonl  one line per run: id, time, symbol, decision, path
"""

import json
import os

import numpy as np


def _default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, tuple):
        return list(o)
    if hasattr(o, "isoformat"):
        return o.isoformat()
    raise TypeError("not JSON serializable: %r" % type(o))


def dumps(o, **kw):
    return json.dumps(o, default=_default, ensure_ascii=False, **kw)


def run_id(b):
    return "%s-%s" % (b.now_utc.strftime("%Y%m%dT%H%M%SZ"), b.plan["symbol"])


def write_run(root, b, run, report_md, sim_md):
    rid = run_id(b)
    d = os.path.join(root, "desk", b.plan["date"], rid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "transcript.jsonl"), "w", encoding="utf-8") as fh:
        for m in run["transcript"]:
            fh.write(dumps(m.to_dict()) + "\n")
    with open(os.path.join(d, "decision.json"), "w", encoding="utf-8") as fh:
        fh.write(dumps({"run_id": rid, "plan": b.sim["plan"], "decision": run["decision"],
                        "contradictions": run["contradictions"], "final_confidence": run["final_confidence"],
                        "agents": run["agents"], "news_error": b.news_error}, indent=1))
    with open(os.path.join(d, "sim.json"), "w", encoding="utf-8") as fh:
        fh.write(dumps(b.sim, indent=1))
    for name, text in (("sim.md", sim_md), ("report.md", report_md)):
        with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    with open(os.path.join(root, "desk", "index.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(dumps({"run_id": rid, "at": b.now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "symbol": b.plan["symbol"], "date": b.plan["date"],
                        "decision": run["decision"]["decision"], "path": os.path.relpath(d, root)}) + "\n")
    return d
