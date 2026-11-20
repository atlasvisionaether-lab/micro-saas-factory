"""Giriş-Çıkış: is the plan's geometry sound? Reward/risk, stop vs. bar noise,
target vs. what the rest of the session usually offers, chasing, entry window."""

import numpy as np

from .base import Agent


def _minutes(hhmm):
    h, m = str(hhmm).split(":")[:2]
    return int(h) * 60 + int(m[:2])


def _entry_minutes(entry_time):
    """'10:15 AM' -> minutes after midnight."""
    t, ap = entry_time.split()
    h, m = (int(x) for x in t.split(":"))
    return (h % 12 + (12 if ap.upper() == "PM" else 0)) * 60 + m


def geometry(b):
    m, k, last, p = b.market, b.market.entry_bar, b.market.last_bar, b.plan
    pool = m.pool
    entry, risk = p["entry"], p["risk_per_share"]
    atr = float(np.nanmean(pool[:, k + 1:last + 1, 1] - pool[:, k + 1:last + 1, 2])) * entry
    closes_k = np.array([D[k]["c"] for _, D in m.sessions])
    if b.long:
        exc = np.array([max(x["h"] for x in D[k + 1:last + 1]) for _, D in m.sessions]) / closes_k - 1
    else:
        exc = 1 - np.array([min(x["l"] for x in D[k + 1:last + 1]) for _, D in m.sessions]) / closes_k
    target_dist = abs(p["target"] - entry)
    return {"atr5": atr, "stop_atr": risk / atr if atr > 0 else None,
            "median_excursion": float(np.median(exc)) * entry,
            "p_reach_hist": float((exc * entry >= target_dist).mean()),
            "target_dist": target_dist}


class EntryExit(Agent):
    name = "entry_exit"
    title = "Giriş-Çıkış"

    def analyze(self, b):
        p, cfg, tc = b.plan, b.desk_cfg["entry_exit"], b.trader_cfg
        g = geometry(b)
        b.extras["geometry"] = g
        ev = {k: round(v, 4) if isinstance(v, float) else v for k, v in g.items()}
        out = []
        min_rr = tc.get("min_reward_risk")
        if min_rr is not None and p["target_r"] < min_rr:
            out.append(self.claim("reward_risk", "Ödül/risk %.2f, limitin (%.2f) altında: risk kuralı bu emri "
                                  "durdurur." % (p["target_r"], min_rr), stance="against", severity="critical",
                                  confidence=0.95, evidence={"target_r": p["target_r"], "min": min_rr}))
        else:
            out.append(self.claim("reward_risk", "Ödül/risk %.2f R; tek başına kenar değildir, hedefe ulaşma "
                                  "olasılığıyla birlikte okunmalı." % p["target_r"], stance="neutral",
                                  confidence=0.4, evidence={"target_r": p["target_r"]}))

        sa = g["stop_atr"]
        if sa is not None and sa < cfg["min_stop_atr"]:
            out.append(self.claim("stop_noise", "Stop mesafesi ortalama 5 dk bar aralığının yalnızca %.2f katı: "
                                  "stop gürültü bandında." % sa, stance="against", severity="warn",
                                  confidence=0.6, evidence=ev))
        elif sa is not None:
            out.append(self.claim("stop_noise", "Stop mesafesi ortalama 5 dk bar aralığının %.1f katı: gürültünün "
                                  "dışında." % sa, stance="for", confidence=0.45, evidence=ev))

        if g["target_dist"] > g["median_excursion"]:
            out.append(self.claim("target_reach", "Hedef (%.2f uzakta), bu saatten kapanışa medyan lehte hareketin "
                                  "(%.2f) ötesinde; geçmiş seanslarda ulaşma oranı %%%.0f." % (
                                      g["target_dist"], g["median_excursion"], 100 * g["p_reach_hist"]),
                                  stance="against", severity="warn", confidence=0.55, evidence=ev))
        else:
            out.append(self.claim("target_reach", "Hedef, kalan seansın medyan lehte hareketi içinde; geçmiş "
                                  "seanslarda ulaşma oranı %%%.0f." % (100 * g["p_reach_hist"]),
                                  stance="for", confidence=0.5, evidence=ev))

        scan_or = b.plan.get("opening_range") or {}
        day = b.market.entry_day
        n = scan_or.get("minutes", 15) // 5
        if all(i in day for i in range(n)):
            edge = max(day[i]["h"] for i in range(n)) if b.long else min(day[i]["l"] for i in range(n))
            chase = ((p["entry"] - edge) if b.long else (edge - p["entry"])) / p["risk_per_share"]
            if chase > cfg["max_chase_r"]:
                out.append(self.claim("chase", "Giriş, kırılım seviyesinin %.2f R ötesinde: kovalama; geri "
                                      "çekilmede stop'a mesafe kısa." % chase, stance="against", severity="warn",
                                      confidence=0.55, evidence={"chase_r": round(chase, 3)}))

        lo, hi = tc.get("no_entries_before"), tc.get("no_entries_after")
        em = _entry_minutes(p["entry_time"])
        if (lo and em < _minutes(lo)) or (hi and em > _minutes(hi)):
            out.append(self.claim("entry_window", "Giriş saati %s, izin verilen pencerenin (%s–%s) dışında." % (
                p["entry_time"], lo, hi), stance="against", severity="critical", confidence=0.95))
        if p["side"] == "sell" and not tc.get("allow_short", False):
            out.append(self.claim("short", "Plan açığa satış ama config açığa satışa izin vermiyor.",
                                  stance="against", severity="critical", confidence=0.95))
        return out
