"""Turkish Markdown report of one desk run."""

from sim.report import DISCLAIMER, MODEL_TR, pct

ROUND_TR = {"R0": "R0 · Veri kapısı", "R1": "R1 · Bağımsız bulgular", "R2": "R2 · Çapraz sorgu",
            "R3": "R3 · Savunma", "R4": "R4 · Karar"}
KIND_TR = {"gate": "kontrol", "claim": "iddia", "challenge": "itiraz", "support": "destek",
           "defend": "savunma", "concede": "kabul", "decision": "karar"}
STANCE_TR = {"for": "lehte", "against": "aleyhte", "neutral": "nötr"}
SEV_ICON = {"info": "", "warn": "⚠️ ", "critical": "⛔ "}
AGENT_TR = {"gate": "Kapı", "scanner": "Tarayıcı", "news": "Haberci", "entry_exit": "Giriş-Çıkış",
            "skeptic": "Şüpheci", "decision": "Karar"}


def render(run, b):
    dec, p = run["decision"], b.plan
    L = ["# Masa kararı: %s %s — **%s**" % (p["symbol"], p["date"], dec["decision"]), "", DISCLAIMER, "",
         "> %s" % dec["summary"], ""]
    L += ["## Plan", "",
          "%s %s · giriş %.2f (%s) · stop %.2f · hedef %.2f · %.2f R" % (
              p["symbol"], "alış" if b.long else "açığa satış", p["entry"], p["entry_time"], p["stop"],
              p["target"], p["target_r"]), ""]
    L += ["## Karar koşulları", "", "| Koşul | Durum |", "|---|---|"]
    for c in dec["checks"]:
        L.append("| %s | %s |" % (c["text"], "✅" if c["ok"] else "❌"))
    if dec["vetoes"]:
        L += ["", "**Vetolar:**"] + ["- ⛔ %s (%s)" % (v["text"], AGENT_TR.get(v["agent"], v["agent"]))
                                      for v in dec["vetoes"]]
    L += ["", "Güven ağırlıklı görüş skoru: %+.2f · çözülmemiş çelişki: %d" % (
        dec["stance_score"], dec["unresolved_contradictions"]), ""]

    L += ["## Simülasyon özeti", "", "| Model | Kazanç | Başabaş | Kayıp | Expectancy (R) [GA] |", "|---|---|---|---|---|"]
    for m, s in b.sim["models"].items():
        L.append("| %s | %s | %s | %s | %+.3f [%+.3f, %+.3f] |" % (
            MODEL_TR.get(m, m), pct(s["p_win"]), pct(s["p_breakeven"]), pct(s["p_loss"]), s["expectancy_r"],
            s["expectancy_r_ci"][0], s["expectancy_r_ci"][1]))
    L.append("")

    L += ["## Çelişkiler", ""]
    if run["contradictions"]:
        L += ["| Konu | İddia | İtiraz | Yanıt | Durum |", "|---|---|---|---|---|"]
        for c in run["contradictions"]:
            L.append("| %s | %s | %s%s | %s | %s |" % (
                c["topic"], c["claim_text"], SEV_ICON[c["severity"]], c["challenge_text"], c["reply_text"],
                "çözüldü (kabul)" if c["status"] == "resolved" else "**açık**"))
    else:
        L.append("Uyarı düzeyinde itiraz yok.")
    L.append("")

    L += ["## Tartışma dökümü", ""]
    cur = None
    for m in run["transcript"]:
        if m.round != cur:
            cur = m.round
            L += ["", "### " + ROUND_TR[cur], ""]
        conf = run["final_confidence"].get(m.id)
        tail = ""
        if m.kind == "claim" and conf is not None and abs(conf - m.confidence) > 1e-9:
            tail = " (güven %.2f → %.2f)" % (m.confidence, conf)
        L.append("- `%s` **%s** · %s · %s · güven %.2f%s%s — %s%s" % (
            m.id, AGENT_TR.get(m.agent, m.agent), KIND_TR[m.kind], STANCE_TR[m.stance], m.confidence, tail,
            (" · ↳ `%s`" % m.replies_to) if m.replies_to else "", SEV_ICON[m.severity], m.text))
    L += ["", "## Notlar", "",
          "- Ajanlar kurallara dayalıdır; aynı girdi aynı tartışmayı ve kararı üretir.",
          "- AL yalnızca masanın kontrollerini geçen bir **paper** işlem anlamına gelir; emir gönderilmez.",
          "- Ayrıntılı simülasyon tabloları: aynı klasördeki `sim.md`.", ""]
    return "\n".join(L)
