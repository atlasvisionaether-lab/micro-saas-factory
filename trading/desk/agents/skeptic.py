"""Risk & Şüpheci: argues against the trade by construction.

R1: its own case from the simulation, the history replay, data quality and the
    risk / budget limits.
R2: must challenge every 'for' claim by another agent; a challenge cites a
    number, never just doubt. Where it has nothing concrete, it says so (info).
"""

import math

from .base import Agent


def sizing(b):
    tc, p = b.trader_cfg, b.plan
    max_loss = tc.get("max_loss_per_trade_usd")
    shares = math.floor(max_loss / p["risk_per_share"]) if max_loss else None
    out = {"max_loss_usd": max_loss, "shares_by_risk": shares}
    if shares:
        notional = shares * p["entry"]
        out["notional_usd"] = round(notional, 2)
        cap = tc.get("max_order_usd")
        if cap and notional > cap:
            out["shares_by_order_cap"] = math.floor(cap / p["entry"])
        budget, pos = tc.get("budget"), tc.get("max_position_pct")
        if budget and pos:
            out["position_pct"] = round(100.0 * notional / budget, 1)
            out["max_position_pct"] = pos
    return out


class Skeptic(Agent):
    name = "skeptic"
    title = "Risk & Şüpheci"

    def analyze(self, b):
        d = b.desk_cfg["decision"]
        models = b.sim["models"]
        out = []
        base = [m for m in d["base_models"] if m in models]
        lows = {m: models[m]["expectancy_r_ci"][0] for m in base}
        if base and all(models[m]["expectancy_r_ci"][1] < 0 for m in models):
            out.append(self.claim("edge", "Bütün modellerde expectancy güven aralığı tamamen sıfırın altında: "
                                  "bu plan maliyetler sonrası para kaybettiriyor.", stance="against",
                                  severity="critical", confidence=0.9,
                                  evidence={m: models[m]["expectancy_r_ci"] for m in models}))
        elif base and not all(v > d["min_edge_r"] for v in lows.values()):
            out.append(self.claim("edge", "Temel modellerde (%s) expectancy alt sınırı %s; pozitif kenar kanıtı "
                                  "yok." % (", ".join(base), ", ".join("%+.3f R" % lows[m] for m in base)),
                                  stance="against", severity="warn", confidence=0.7, evidence={"ci_low": lows}))

        if "gbm" in models and base:
            boot = max(models[m]["expectancy_r"] for m in base)
            g = models["gbm"]["expectancy_r"]
            if boot > 0 and (g <= 0 or boot - g > 0.05):
                out.append(self.claim("drift", "Bootstrap %+.3f R, kenarsız GBM %+.3f R: görünen kenarın bir kısmı "
                                      "havuz dönemindeki trendden geliyor ve tekrar etmeyebilir." % (boot, g),
                                      stance="against", severity="warn", confidence=0.55,
                                      evidence={"bootstrap_best": boot, "gbm": g}))
            elif boot <= 0:
                out.append(self.claim("drift", "Havuz dönemindeki trend dahil edildiğinde bile expectancy %+.3f R; "
                                      "trend olmadan (GBM) %+.3f R. Kenar yok." % (boot, g),
                                      stance="against", severity="info", confidence=0.55,
                                      evidence={"bootstrap_best": boot, "gbm": g}))

        if "regime_shock" in models:
            s = models["regime_shock"]
            if s["expectancy_r"] < d["stress_floor_r"]:
                out.append(self.claim("stress", "Stres senaryosunda expectancy %.3f R, taban %.2f R'nin altında." % (
                    s["expectancy_r"], d["stress_floor_r"]), stance="against", severity="warn", confidence=0.6))
            q = s["sequence"]
            out.append(self.claim("tail", "Stres altında ortalama kayıp %.2f R, %d gap'li stop; %d işlemlik "
                                  "serilerde düşüşün %%%.0f sınırını aşma oranı %%%.0f." % (
                                      s["avg_loss_r"] or 0, s["gap_stops"], q["n_trades"],
                                      100 * q["dd_threshold"], 100 * q["p_drawdown_over_threshold"]),
                                  stance="against", severity="info", confidence=0.5,
                                  evidence={"avg_loss_r": s["avg_loss_r"], "gap_stops": s["gap_stops"],
                                            "p_dd": q["p_drawdown_over_threshold"]}))

        h = b.sim.get("history")
        if h:
            if h["triggered"] < d["min_history_trades"]:
                out.append(self.claim("history", "Aynı kural geçmişte yalnızca %d kez tetiklendi (asgari %d): "
                                      "tarihsel kanıt istatistiksel olarak zayıf." % (h["triggered"],
                                                                                    d["min_history_trades"]),
                                      stance="against", severity="warn", confidence=0.6, evidence=h))
            elif h["avg_R"] is not None and h["avg_R"] <= 0:
                out.append(self.claim("history", "Kural %d tetikte ortalama %+.3f R getirdi (maliyet öncesi)." % (
                    h["triggered"], h["avg_R"]), stance="against", severity="warn", confidence=0.6, evidence=h))

        for w in b.sim.get("warnings", []):
            out.append(self.claim("data_quality", "Veri uyarısı: " + w, stance="against", severity="warn",
                                  confidence=0.5))

        sz = sizing(b)
        b.extras["sizing"] = sz
        if sz["shares_by_risk"] == 0:
            out.append(self.claim("sizing", "Hisse başı risk (%.2f) işlem başı azami kaybı (%s $) aşıyor: tek "
                                  "hisse bile limit dışı." % (b.plan["risk_per_share"], sz["max_loss_usd"]),
                                  stance="against", severity="critical", confidence=0.95, evidence=sz))
        elif sz.get("position_pct") and sz["position_pct"] > sz["max_position_pct"]:
            out.append(self.claim("sizing", "Risk bazlı pozisyon bütçenin %%%.0f kadarı, sınır %%%.0f: "
                                  "pozisyon küçültülmeli." % (sz["position_pct"], sz["max_position_pct"]),
                                  stance="against", severity="warn", confidence=0.7, evidence=sz))
        return out

    def respond(self, b, others):
        models, h = b.sim["models"], b.sim.get("history")
        base = [m for m in b.desk_cfg["decision"]["base_models"] if m in models]
        bb = models[base[0]] if base else None
        out = []
        for m in others:
            if m.stance != "for" or m.kind != "claim":
                continue
            if m.topic == "volume":
                out.append(self.challenge(m, "Hacim anomalisi yön söylemez: aynı plan simülasyonda %%%.1f kazanç, "
                                          "%%%.1f kayıp veriyor." % (100 * bb["p_win"], 100 * bb["p_loss"]),
                                          severity="warn" if bb["expectancy_r_ci"][0] <= 0 else "info",
                                          evidence={"p_win": bb["p_win"], "p_loss": bb["p_loss"]}))
            elif m.topic == "breakout":
                txt = ("Kırılım kuralı geçmişte %d tetikte %d hedef, %d stop verdi." % (
                    h["triggered"], h["target"], h["stop"]) if h else "Bu kurulum için tarihsel tekrar yok.")
                bad = (not h) or h["target"] <= h["stop"]
                out.append(self.challenge(m, txt + (" Kırılım tek başına kenar değil." if bad else ""),
                                          severity="warn" if bad else "info", evidence=h or {}))
            elif m.topic == "catalyst":
                move = (m.evidence or {}).get("day_move_pct")
                out.append(self.challenge(m, "Haber giriş anında %+.1f%%'lik hareketle zaten fiyatlanmış olabilir; "
                                          "haberin geri kalan seansa etkisi ölçülmüyor." % (move or 0.0),
                                          severity="warn"))
            elif m.topic == "target_reach":
                out.append(self.challenge(m, "Geçmişte hedefe ulaşmak, stop'tan önce ulaşmak demek değil: "
                                          "simülasyonda hedef önce %%%.1f, stop önce %%%.1f." % (
                                              100 * bb["p_exit_target"], 100 * bb["p_exit_stop"]),
                                          severity="warn" if bb["p_exit_target"] <= bb["p_exit_stop"] else "info"))
            elif m.topic == "stop_noise":
                out.append(self.challenge(m, "Stop gürültünün dışında olsa da gap'te kayabilir: stres modelinde "
                                          "%d gap'li stop." % models.get("regime_shock", {}).get("gap_stops", 0),
                                          severity="info"))
            else:
                out.append(self.challenge(m, "Bu iddiaya karşı somut bir sayım yok; simülasyon sonucuna "
                                          "bağlanmadıkça kanıt sayılmaz.", severity="info"))
        return out
