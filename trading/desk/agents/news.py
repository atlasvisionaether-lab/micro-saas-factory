"""Haberci: what could move the price, and is it already priced in?
Headline tags come from the vendored news monitor; a headline is a lead, not a fact,
and it never says which way the price goes."""

from .base import Agent

RISK_TAGS = {"legal", "risk"}
EVENT_TAGS = {"earnings", "deal", "regulatory", "macro", "analyst", "capital", "people"}


class News(Agent):
    name = "news"
    title = "Haberci"

    def analyze(self, b):
        hours = b.desk_cfg["news_hours"]
        if b.news is None:
            return [self.claim("news_data", "Haber verisi okunamadı (%s): katalizör değerlendirmesi kör."
                               % (b.news_error or "bilinmiyor"), severity="warn", confidence=0.6)]
        items = b.news
        if not items:
            return [self.claim("catalyst", "Son %d saatte %s için başlık yok: hareket teknik görünüyor, "
                               "açıklaması olmayan bir hareket." % (hours, b.plan["symbol"]), confidence=0.4,
                               evidence={"items": 0})]
        tags = sorted({t for it in items for t in it["tags"]})
        newest = items[0]
        age = (b.now_aware - newest["time"]).total_seconds() / 60.0
        top = [{"time": it["time"].strftime("%Y-%m-%d %H:%MZ"), "title": it["title"], "tags": it["tags"]}
               for it in items[:5]]
        ev = {"items": len(items), "tags": tags, "newest_age_min": round(age, 1), "top": top}
        out = []
        if "halt" in tags:
            out.append(self.claim("halt", "Başlıklarda işlem durdurma geçiyor: veri ve dolum güvenilmez.",
                                  stance="against", severity="critical", confidence=0.8, evidence=ev))
        risky = sorted(RISK_TAGS & set(tags))
        if risky:
            out.append(self.claim("headline_risk", "Risk etiketli başlık var (%s): ani ters hareket ihtimali."
                                  % ", ".join(risky), stance="against", severity="warn", confidence=0.6, evidence=ev))
        events = sorted(EVENT_TAGS & set(tags))
        if events:
            prev_close = b.market.sessions[-1][1][-1]["c"]          # computed here: R1 must not read other agents
            move = 100.0 * (b.plan["entry"] / prev_close - 1)
            aligned = move is not None and ((move > 0) == b.long) and abs(move) >= 1.0
            text = "Katalizör başlıkları: %s (%d başlık, en yenisi %.0f dk önce)." % (", ".join(events), len(items), age)
            if aligned:
                text += " Fiyat günü planla aynı yönde %+.1f%% hareket etmiş." % move
            else:
                text += " Başlıklar yön söylemez."
            out.append(self.claim("catalyst", text, stance="for" if aligned else "neutral",
                                  confidence=0.45 if aligned else 0.4, evidence=dict(ev, day_move_pct=move)))
        if "earnings" in tags:
            out.append(self.claim("event_regime", "Kazanç gündemi var: bugünkü volatilite rejimi 60 günlük "
                                  "havuzdan farklı olabilir, simülasyon bunu görmez.", severity="warn",
                                  confidence=0.5, evidence={"tags": tags}))
        if not out:
            out.append(self.claim("catalyst", "%d başlık var, fiyatı oynatacak etiket yok." % len(items),
                                  confidence=0.3, evidence=ev))
        return out

    def respond(self, b, others):
        out = []
        unexplained = b.news is not None and not b.news
        for m in others:
            if m.topic == "volume" and m.stance == "for" and unexplained:
                out.append(self.challenge(m, "Olağandışı hacim var ama haber yok: nedeni bilinmeyen akış, "
                                          "bilgi asimetrisi riski taşır."))
        return out
