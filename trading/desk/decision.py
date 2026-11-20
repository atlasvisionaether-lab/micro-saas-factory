"""Karar modülü: rules, not a vote and not a model.

GEÇ (pass)   any critical message anywhere in R0-R3 (data gate, risk limit, all
             models negative, halt) - a veto cannot be outweighed.
AL  (take)   every condition below holds:
             - each base model's expectancy CI lower bound > min_edge_r
             - stress model expectancy >= stress_floor_r
             - history replay has >= min_history_trades triggers and avg R > 0
               (when the setup has a history replay)
             - unresolved warn/critical contradictions <= max_unresolved_warn
             - confidence-weighted stance score > min_stance_score
BEKLE (wait) everything else. The report lists exactly which AL conditions failed,
             so "what would change my mind" is explicit.

AL means "the plan passes the desk's checks for a paper trade". It never places an order.
"""


def stance_score(claims, final_conf):
    s = 0.0
    for cid, c in claims.items():
        sign = {"for": 1.0, "against": -1.0}.get(c.stance, 0.0)
        s += sign * final_conf[cid]
    return round(s, 4)


def decide(b, transcript, claims, final_conf, contradictions):
    d = b.desk_cfg["decision"]
    models = b.sim["models"]
    vetoes = [{"id": m.id, "agent": m.agent, "text": m.text} for m in transcript
              if m.severity == "critical" and m.kind in ("gate", "claim", "challenge")]

    checks = []

    def check(name, ok, text):
        checks.append({"name": name, "ok": bool(ok), "text": text})

    base = [m for m in d["base_models"] if m in models]
    for m in base:
        lo = models[m]["expectancy_r_ci"][0]
        check("edge_" + m, lo > d["min_edge_r"],
              "%s expectancy alt sınırı > %+.3f R (şu an %+.3f)" % (m, d["min_edge_r"], lo))
    if not base:
        check("edge", False, "temel modellerin hiçbiri çalıştırılmadı")
    if "regime_shock" in models:
        e = models["regime_shock"]["expectancy_r"]
        check("stress", e >= d["stress_floor_r"], "stres expectancy ≥ %+.2f R (şu an %+.3f)" % (d["stress_floor_r"], e))
    h = b.sim.get("history")
    if h:
        check("history_n", h["triggered"] >= d["min_history_trades"],
              "tarihsel tetik sayısı ≥ %d (şu an %d)" % (d["min_history_trades"], h["triggered"]))
        check("history_r", h["avg_R"] is not None and h["avg_R"] > 0,
              "tarihsel ortalama R > 0 (şu an %s)" % ("—" if h["avg_R"] is None else "%+.3f" % h["avg_R"]))
    unresolved = [c for c in contradictions if c["status"] == "unresolved"]
    check("contradictions", len(unresolved) <= d["max_unresolved_warn"],
          "çözülmemiş çelişki ≤ %d (şu an %d)" % (d["max_unresolved_warn"], len(unresolved)))
    score = stance_score(claims, final_conf)
    check("stance", score > d["min_stance_score"], "güven ağırlıklı görüş skoru > %+.2f (şu an %+.2f)" % (
        d["min_stance_score"], score))

    failed = [c for c in checks if not c["ok"]]
    if vetoes:
        decision = "GEÇ"
        summary = "GEÇ: %d veto var. İlk veto: %s" % (len(vetoes), vetoes[0]["text"])
    elif not failed:
        decision = "AL"
        summary = ("AL (yalnızca paper): bütün koşullar sağlandı. Bu bir emir değildir; boyutlandırma ve risk "
                   "kontrolü ayrıca yapılmalı.")
    else:
        decision = "BEKLE"
        summary = "BEKLE: %d/%d koşul sağlanmadı: %s." % (len(failed), len(checks),
                                                           "; ".join(c["text"] for c in failed[:3]))
    return {"decision": decision, "summary": summary, "vetoes": vetoes, "checks": checks,
            "failed": [c["name"] for c in failed], "stance_score": score,
            "unresolved_contradictions": len(unresolved)}
