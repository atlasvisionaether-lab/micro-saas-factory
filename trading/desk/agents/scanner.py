"""Tarayıcı: is today unusual? Relative volume, range expansion, gap and the
opening-range break, each measured against the same time of day in the pool."""

import numpy as np

from .base import Agent


def scan_stats(b):
    m, k = b.market, b.market.entry_bar
    day = m.entry_day
    slots = [i for i in range(k + 1) if i in day]
    pool_v = np.array([sum(D[i]["v"] for i in range(k + 1)) for _, D in m.sessions], float)
    pool_rng = np.array([max(D[i]["h"] for i in range(k + 1)) / min(D[i]["l"] for i in range(k + 1)) - 1
                         for _, D in m.sessions])
    day_v = float(sum(day[i]["v"] for i in slots))
    day_rng = max(day[i]["h"] for i in slots) / min(day[i]["l"] for i in slots) - 1
    prev_close = m.sessions[-1][1][-1]["c"]
    n = b.plan["opening_range"]["minutes"] // 5
    or_bars = [day[i] for i in range(n) if i in day]
    oh = max(x["h"] for x in or_bars) if or_bars else None
    ol = min(x["l"] for x in or_bars) if or_bars else None
    sd = pool_v.std(ddof=1)
    return {
        "rvol": day_v / pool_v.mean() if pool_v.mean() > 0 else None,
        "rvol_z": (day_v - pool_v.mean()) / sd if sd > 0 else 0.0,
        "range_ratio": day_rng / pool_rng.mean() if pool_rng.mean() > 0 else None,
        "gap_pct": 100.0 * (day[0]["o"] / prev_close - 1) if 0 in day else None,
        "or_high": oh, "or_low": ol, "entry_close": day[k]["c"],
        "day_move_pct": 100.0 * (b.plan["entry"] / prev_close - 1),
        "prev_close": prev_close, "bars_seen": len(slots),
    }


class Scanner(Agent):
    name = "scanner"
    title = "Tarayıcı"

    def analyze(self, b):
        c = b.desk_cfg["scanner"]
        s = scan_stats(b)
        b.extras["scan"] = s
        ev = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items()}
        out = []
        rv = s["rvol"]
        if rv is None:
            out.append(self.claim("volume", "Hacim verisi yok; hacim teyidi yapılamadı.", severity="warn",
                                  stance="against", confidence=0.5, evidence=ev))
        elif rv >= c["rvol_high"]:
            out.append(self.claim("volume", "Giriş barına kadar hacim, aynı saat dilimi ortalamasının %.1f katı "
                                  "(z=%.1f): olağandışı ilgi." % (rv, s["rvol_z"]), stance="for",
                                  confidence=round(min(0.9, 0.5 + 0.1 * max(0.0, s["rvol_z"])), 3), evidence=ev))
        elif rv <= c["rvol_low"]:
            out.append(self.claim("volume", "Hacim ortalamanın %.1f katı: hareketin hacim teyidi yok." % rv,
                                  stance="against", severity="warn", confidence=0.6, evidence=ev))
        else:
            out.append(self.claim("volume", "Hacim olağan aralıkta (%.1f kat)." % rv, confidence=0.4, evidence=ev))

        rr = s["range_ratio"]
        if rr is not None and rr >= c["range_high"]:
            out.append(self.claim("range", "Gün içi aralık olağanın %.1f katı: volatilite genişlemesi. Yön "
                                  "söylemez; stop'lar daha sık tetiklenebilir." % rr, confidence=0.6, evidence=ev))
        g = s["gap_pct"]
        if g is not None and abs(g) >= c["gap_pct_high"]:
            out.append(self.claim("gap", "Açılış önceki kapanıştan %+.1f%% uzakta: gap dolumu riski." % g,
                                  severity="warn", confidence=0.5, evidence=ev))

        if s["or_high"] is not None:
            above = s["entry_close"] > s["or_high"] if b.long else s["entry_close"] < s["or_low"]
            edge = s["or_high"] if b.long else s["or_low"]
            out.append(self.claim(
                "breakout",
                ("Giriş barı açılış aralığının dışında kapandı (%.2f, sınır %.2f): kırılım teyitli." if above else
                 "Giriş barı açılış aralığının içinde kapandı (%.2f, sınır %.2f): kırılım teyitsiz.")
                % (s["entry_close"], edge),
                stance="for" if above else "against", severity="info" if above else "warn",
                confidence=0.5, evidence=ev))
        return out

    def respond(self, b, others):
        s = b.extras.get("scan") or {}
        rv, c = s.get("rvol"), b.desk_cfg["scanner"]
        out = []
        for m in others:
            if m.topic != "catalyst" or rv is None:
                continue
            if rv >= c["rvol_high"]:
                out.append(self.support(m, "Haber hacimle teyit ediliyor (%.1f kat hacim)." % rv, confidence=0.6))
            elif rv <= c["rvol_low"]:
                out.append(self.challenge(m, "Haber var ama hacim düşük (%.1f kat): piyasa haberi önemsemiyor "
                                          "ya da zaten fiyatlamış." % rv))
        return out

    def defend(self, b, claim, challenge):
        s = b.extras.get("scan") or {}
        if claim.topic == "volume" and claim.stance == "for" and s.get("rvol_z", 0) >= 3:
            return self.defend_keep(claim, challenge, "Hacim sapması z=%.1f; tesadüf olma ihtimali çok düşük. "
                                    "Yön konusundaki itiraz geçerli, anomalinin varlığı değil." % s["rvol_z"],
                                    {"rvol_z": round(s["rvol_z"], 2)})
        return super().defend(b, claim, challenge)
