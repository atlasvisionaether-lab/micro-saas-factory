"""Markdown report (Turkish). Every number is labelled as a model output."""

MODEL_TR = {
    "bar_bootstrap": "Bar bootstrap",
    "block_bootstrap": "Blok bootstrap",
    "gbm": "GBM (sıfır drift, kenar yok)",
    "regime_shock": "Rejim şoku (stres)",
}
FLAG_TR = {
    "models disagree on the sign of expectancy": "Modeller expectancy'nin işaretinde anlaşamıyor.",
    "every model's expectancy CI is below zero": "Tüm modellerde expectancy güven aralığı sıfırın altında.",
    "at least one model's expectancy CI is above zero": "En az bir modelde expectancy güven aralığı sıfırın üstünde.",
    "no model shows expectancy distinguishable from zero": "Hiçbir modelde expectancy sıfırdan ayırt edilemiyor.",
}
DISCLAIMER = ("> **Sorumluluk sınırı:** Bu rapor geçmiş 5 dakikalık barların yeniden örneklenmesi ve açıkça "
              "yazılmış model varsayımlarıyla üretilmiş istatistiksel bir simülasyondur. Tahmin veya yatırım "
              "tavsiyesi değildir. Kazanç, haber, işlem durdurma ve gap gibi olaylar geçmiş pencerede "
              "görülmemiş olabilir. Bu sistem emir göndermez.")


def pct(x):
    return "%.1f %%" % (100 * x)


def ci_pct(ci):
    return "%.1f–%.1f" % (100 * ci[0], 100 * ci[1])


def r(x, nd=3):
    return "—" if x is None else ("%+.*f" % (nd, x))


def render(doc):
    p, d, st = doc["plan"], doc["data"], doc["settings"]
    lvl = int(round(100 * st["confidence_level"]))
    band = st["breakeven_band_r"]
    L = []
    L.append("# Simülasyon raporu: %s %s" % (p["symbol"], p["date"]))
    L.append("")
    L.append(DISCLAIMER)
    L.append("")
    L.append("## Plan")
    L.append("")
    L.append("| Yön | Giriş | Stop | Hedef | Risk/hisse | Hedef (R) | Giriş zamanı | Bitiş |")
    L.append("|---|---|---|---|---|---|---|---|")
    L.append("| %s | %.2f | %.2f | %.2f | %.2f | %.2f | %s | %s ET (%d bar) |" % (
        "Alış" if p["side"] == "buy" else "Açığa satış", p["entry"], p["stop"], p["target"],
        p["risk_per_share"], p["target_r"], p["entry_time"], doc["until"], doc["bars_left"]))
    L.append("")
    L.append("## Sonuç dağılımı (%s senaryo / model, seed %d)" % ("{:,}".format(st["replays"]), st["seed"]))
    L.append("")
    L.append("Sınıflar maliyet sonrası R üzerinden: **Kazanç** R > +%g, **Başabaş** |R| ≤ %g, "
             "**Kayıp** R < −%g. Köşeli parantez: %%%d güven aralığı (Wilson)." % (band, band, band, lvl))
    L.append("")
    usd = st["risk_usd"] is not None
    head = "| Model | Kazanç | Başabaş | Kayıp | Expectancy (R) [%%%d GA] |" % lvl
    sep = "|---|---|---|---|---|"
    if usd:
        head += " Expectancy ($) |"
        sep += "---|"
    L += [head, sep]
    for m, s in doc["models"].items():
        row = "| %s | %s [%s] | %s [%s] | %s [%s] | %s [%s, %s] |" % (
            MODEL_TR.get(m, m), pct(s["p_win"]), ci_pct(s["p_win_ci"]),
            pct(s["p_breakeven"]), ci_pct(s["p_breakeven_ci"]), pct(s["p_loss"]), ci_pct(s["p_loss_ci"]),
            r(s["expectancy_r"]), r(s["expectancy_r_ci"][0]), r(s["expectancy_r_ci"][1]))
        if usd:
            row += " %+.2f |" % s["expectancy_usd"]
        L.append(row)
    L.append("")
    L.append("### Çıkış şekli ve R dağılımı")
    L.append("")
    L.append("| Model | Hedef önce | Stop önce | Süre sonu | Ort. kazanç R | Ort. kayıp R | Kâr faktörü | "
             "R p5 / p50 / p95 | Gap'li stop |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for m, s in doc["models"].items():
        q = s["r_percentiles"]
        pf = "—" if s["profit_factor"] is None else "%.2f" % s["profit_factor"]
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s / %s / %s | %d |" % (
            MODEL_TR.get(m, m), pct(s["p_exit_target"]), pct(s["p_exit_stop"]), pct(s["p_exit_time"]),
            r(s["avg_win_r"], 2), r(s["avg_loss_r"], 2), pf, r(q["5"], 2), r(q["50"], 2), r(q["95"], 2),
            s["gap_stops"]))
    L.append("")
    sq0 = next(iter(doc["models"].values()))["sequence"]
    L.append("### Seri riski (%d işlem, işlem başına sermayenin %%%g'i riskte, %s seri)" % (
        sq0["n_trades"], 100 * sq0["risk_frac"], "{:,}".format(sq0["n_sequences"])))
    L.append("")
    L.append("| Model | Seri sonu getiri p5 / medyan / p95 | Zararla biten seri | Maks. düşüş medyan / p95 | "
             "Düşüş > %%%g |" % (100 * sq0["dd_threshold"]))
    L.append("|---|---|---|---|---|")
    for m, s in doc["models"].items():
        q = s["sequence"]
        L.append("| %s | %s / %s / %s | %s | %s / %s | %s |" % (
            MODEL_TR.get(m, m), pct(q["final_return_p5"]), pct(q["final_return_median"]),
            pct(q["final_return_p95"]), pct(q["p_losing_sequence"]), pct(q["max_drawdown_median"]),
            pct(q["max_drawdown_p95"]), pct(q["p_drawdown_over_threshold"])))
    L.append("")
    L.append("## Modeller arası tutarlılık")
    L.append("")
    dis = doc["disagreement"]
    L.append("- Expectancy aralığı (en iyi − en kötü model): %.3f R; en kötü: %s." % (
        dis["expectancy_spread_r"], MODEL_TR.get(dis["min_model"], dis["min_model"])))
    for f in dis["flags"]:
        L.append("- " + FLAG_TR.get(f, f))
    L.append("")
    h = doc.get("history")
    L.append("## Tarihsel tekrar (aynı kural, geçmiş seanslar)")
    L.append("")
    if h:
        L.append("%d seansta kural %d kez tetiklendi: hedef %d, stop %d, süre sonu %d; ortalama R %s "
                 "(maliyet öncesi, stop'ta tam −1R varsayımı). Örnek küçük: güven aralığı geniştir." % (
                     h["sessions"], h["triggered"], h["target"], h["stop"], h["close"],
                     "—" if h["avg_R"] is None else "%+.3f" % h["avg_R"]))
    else:
        L.append("Yalnızca opening-range breakout (orb) kurulumu için yapılabiliyor; bu plan için atlandı.")
    L.append("")
    L.append("## Veri kalitesi")
    L.append("")
    L.append("- Havuz: %d tam seans, %s → %s. Son bar: %s." % (
        d["pool_sessions"], d["pool_from"], d["pool_to"], d["last_bar"]))
    L.append("- Dışarıda bırakılan kısa seans: %d. Atılan bar: %s." % (
        len(d["short_sessions_left_out"]), ", ".join("%s %d" % kv for kv in d["dropped_bars"].items())))
    for w in doc["warnings"]:
        L.append("- ⚠️ " + w)
    L.append("")
    L.append("## Varsayımlar")
    L.append("")
    rs = st["regime_shock"]
    L += [
        "- Giriş plan fiyatından dolar; slippage %g bps (giriş ve çıkış), komisyon %g $/hisse (her iki yön)." % (
            st["slippage_bps"], st["commission_per_share_usd"]),
        "- Stop ve hedef aynı 5 dakikalık barda: stop sayılır (muhafazakâr).",
        "- Bar stop'un ötesinde açılırsa (gap) dolum açılış fiyatıdır; hedef limit emirdir, daha iyi dolmaz.",
        "- Bitişe kadar ikisi de olmazsa son barın kapanışından çıkılır.",
        "- Bar bootstrap: aynı saat dilimi ±%d bar; blok bootstrap: %d barlık bloklar." % (
            st["window"], st["block_size_bars"]),
        "- GBM: sıfır drift (fiyat martingale), saat dilimine göre volatilite, bar içi uç değerler Brownian köprü.",
        "- Rejim şoku: volatilite ×%g, seri başına %%%g olasılıkla %g R'lik ters yönde gap." % (
            rs["vol_multiplier"], 100 * rs["gap_prob"], rs["gap_size_r"]),
        "- Seriler: sonuçlar bağımsız varsayılır; gerçekte kayıplar kümelenebilir.",
        "- Rejim şoku expectancy'den çok kuyruk riskini ölçer (ort. kayıp, gap'li stop, seri düşüşü): "
        "simetrik bir planda volatilite artışı tek başına expectancy'yi düşürmez.",
        "- Bootstrap modelleri havuz dönemindeki trendi (drift) taşır; GBM bu trendi sıfırlayan kıyas modelidir.",
    ]
    L.append("")
    return "\n".join(L)
