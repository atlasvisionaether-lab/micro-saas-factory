"""The desk's fixed conversation.

R0 data gate        the protocol itself checks data freshness, pool size, news availability.
R1 independent      each agent writes claims from the bundle alone, in a fixed order, and
                    cannot see the others' claims (against anchoring).
R2 cross-exam       each agent answers the other agents' R1 claims (challenge / support).
R3 defense          every warn/critical challenge goes back to the claim's owner, who
                    defends (keeps confidence) or concedes (confidence cut by severity).
R4 decision         rule-based synthesis, see decision.py.

Contradictions: every warn/critical challenge, marked resolved when conceded and
unresolved when defended. Both are visible in the report.
"""

import datetime

from sim.vendor_bridge import timemachine

from .agents import DEFAULT_AGENTS
from .decision import decide
from .schema import Message


def _assign(msgs, rnd, counters):
    for m in msgs:
        if m.round != rnd:
            raise ValueError("%s produced a %s message in %s" % (m.agent, m.round, rnd))
        counters[(rnd, m.agent)] = counters.get((rnd, m.agent), 0) + 1
        m.id = "%s-%s-%d" % (rnd, m.agent, counters[(rnd, m.agent)])
    return msgs


def data_gate(b):
    cfg = b.desk_cfg["data_gate"]
    out = []
    q = b.market.quality
    if q["pool_sessions"] < cfg["min_pool_sessions"]:
        out.append(("pool", "Havuzda %d seans var (önerilen ≥%d): kuyruk tahminleri gürültülü." % (
            q["pool_sessions"], cfg["min_pool_sessions"]), "warn"))
    # freshness only matters while the plan's own session is live
    date_s, time_s = q["last_bar"].split()[:2]
    last_end = datetime.datetime.fromisoformat("%s %s" % (date_s, time_s)) + datetime.timedelta(minutes=5)
    now_et = timemachine().to_eastern(b.now_utc)
    in_session = now_et.date().isoformat() == b.plan["date"] and now_et.hour * 60 + now_et.minute < 16 * 60
    age = (now_et - last_end).total_seconds() / 60.0
    if in_session and age > cfg["max_bar_age_min"]:
        out.append(("freshness", "Son tam bar %.0f dk önce bitmiş (sınır %d dk): veri bayat, canlı karar "
                    "verilemez." % (age, cfg["max_bar_age_min"]), "critical"))
    else:
        out.append(("freshness", "Son tam bar: %s (seans içi yaş %.0f dk)." % (q["last_bar"], max(age, 0.0)), "info"))
    if b.news is None:
        out.append(("news_data", "Haber verisi yok (%s)." % (b.news_error or "?"), "warn"))
    return [Message(id="", round="R0", agent="gate", kind="gate", topic=t, text=x, severity=s,
                    stance="against" if s != "info" else "neutral", confidence=0.9 if s == "critical" else 0.5)
            for t, x, s in out]


def run_desk(b, agent_classes=DEFAULT_AGENTS):
    agents = [cls() for cls in agent_classes]
    by_name = {a.name: a for a in agents}
    if len(by_name) != len(agents):
        raise ValueError("agent names must be unique")
    counters = {}
    transcript = _assign(data_gate(b), "R0", counters)

    r1 = []
    for a in agents:
        r1 += _assign(a.analyze(b), "R1", counters)
    transcript += r1

    r2 = []
    for a in agents:
        others = [m for m in r1 if m.agent != a.name]
        r2 += _assign(a.respond(b, others), "R2", counters)
    known = {m.id for m in r1}
    for m in r2:
        if m.replies_to not in known:
            raise ValueError("%s replies to unknown claim %s" % (m.id, m.replies_to))
    transcript += r2

    claims = {m.id: m for m in r1}
    r3, contradictions = [], []
    for ch in r2:
        if ch.kind != "challenge" or ch.severity == "info":
            continue
        target = claims[ch.replies_to]
        reply = _assign([by_name[target.agent].defend(b, target, ch)], "R3", counters)[0]
        if reply.replies_to != ch.id or reply.kind not in ("defend", "concede"):
            raise ValueError("%s must defend or concede %s" % (target.agent, ch.id))
        r3.append(reply)
        contradictions.append({
            "claim": target.id, "challenge": ch.id, "reply": reply.id, "topic": target.topic,
            "severity": ch.severity, "status": "resolved" if reply.kind == "concede" else "unresolved",
            "claim_text": target.text, "challenge_text": ch.text, "reply_text": reply.text,
        })
    transcript += r3

    final_conf = {cid: c.confidence for cid, c in claims.items()}
    for rep in r3:
        cid = next(c["claim"] for c in contradictions if c["reply"] == rep.id)
        final_conf[cid] = min(final_conf[cid], rep.confidence)

    decision = decide(b, transcript, claims, final_conf, contradictions)
    dmsg = _assign([Message(id="", round="R4", agent="decision", kind="decision", topic="decision",
                            text=decision["summary"], stance={"AL": "for", "GEÇ": "against"}.get(
                                decision["decision"], "neutral"),
                            severity="info", confidence=1.0, evidence={"decision": decision["decision"]})],
                   "R4", counters)
    transcript += dmsg
    return {"transcript": transcript, "contradictions": contradictions, "final_confidence": final_conf,
            "decision": decision, "agents": [{"name": a.name, "title": a.title} for a in agents]}
