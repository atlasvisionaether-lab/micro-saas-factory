# trading/ — analiz, backtest ve simülasyon katmanı

Next.js uygulamasından izole, saf Python. Canlı emir yok. Önce `DISCLAIMER.md`.

## Yapı

```
trading/
├── DISCLAIMER.md
├── requirements.txt          numpy (yalnızca sim/ için)
├── config/
│   ├── trader.config.example.json   risk + bütçe sınırları (upstream formatı)
│   └── sim.example.json             iterasyon, seed, başabaş bandı, maliyetler, modeller
├── sim/                     çoklu model Monte Carlo motoru (numpy)
├── tests/sim/               sim testleri (offline)
├── vendor/
│   ├── VENDOR.md                    kaynak, commit, güvenlik notları
│   ├── day-trader-skill/            11 modül, değiştirilmemiş
│   └── day-trader-skill.MANIFEST.sha256
└── trader/                          (çalışma zamanı durumu, git'e girmez)
```

## Kurulum

```bash
cd trading
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
mkdir -p trader && cp config/trader.config.example.json trader/config.json
cp config/sim.example.json trader/sim.json
```

Araçlar `trader/` klasörünü çalıştırıldıkları dizine göre okur; komutları
`trading/` içinden çalıştırın.

## Modüller ve akış

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker (yalnızca fiş)
alerts: stop / hedef / gün sonu kapanış      analyst, pelosi: zamanlanmış
```

| Modül | Görev |
|---|---|
| scanner | Setup tarama (opening-range breakout, flag, oversold) |
| news | Haber ve 8-K katalizörleri |
| entry | Giriş tetikleme zamanlaması |
| exit | Stop, hedef, R/R, gün sonu çıkış |
| timemachine | 10.000 bootstrap senaryo + geçmiş tekrar |
| budget | Pozisyon büyüklüğü |
| risk | Sınır kontrolü, PASS/BLOCK |
| broker | Emir fişi ve paper log (bağlantısız) |
| alerts | Fiyat alarmları |
| analyst | SEC XBRL bilanço özeti |
| pelosi | Kongre işlem bildirimleri (PTR) |

## Simülasyon motoru (`sim/`)

Bir planı (giriş, stop, hedef, giriş zamanı) dört modelle 10.000'er kez oynatır
ve Kazanç / Başabaş / Kayıp %, expectancy (R ve $), güven aralıkları, çıkış
şekli, R dağılımı, 50 işlemlik seri riski ve modeller arası tutarlılık üretir.

| Model | Ne sorar |
|---|---|
| `bar_bootstrap` | Her bar geçmiş seansların aynı saat dilimindeki barından (upstream Time Machine ile aynı yöntem) |
| `block_bootstrap` | 6 barlık bitişik bloklar: kısa vadeli momentum ve volatilite kümelenmesi korunur |
| `gbm` | Sıfır drift, kenar yok kıyası: plan sadece bootstrap'ta iyi görünüyorsa kenar havuzun trendinden gelir |
| `regime_shock` | Volatilite ×2 + ters yönde gap: kuyruk riski stres testi |

```bash
python3 -m sim run                                  # trader/plan.json + trader/sim.json, canlı Yahoo verisi
python3 -m sim run --offline vendor/day-trader-skill/tests/fixtures/trader-timemachine/TSLA-60d5m.json.gz \
    --symbol TSLA --date 2026-10-19 --entry 364.18 --stop 358.32 --target 370.04 \
    --entry-time "10:15 AM" --now "2026-10-19 10:50"
python3 -m sim run --json          # makine okunur çıktı
python3 -m sim run --write         # trader/sim/<SYM>-<tarih>.{json,md}
```

`risk_usd` boşsa `trader/config.json` içindeki `max_loss_per_trade_usd` kullanılır.
Aynı plan + aynı veri + aynı seed = aynı sayılar.

## Test

```bash
python3 -m unittest discover -s tests -t .                                  # sim (28 test)
cd vendor/day-trader-skill && python3 -I -m unittest discover -s tests      # upstream (315 test)
```

## Yol haritası

1. ✅ İskelet, config, sorumluluk sınırı
2. ✅ Upstream vendor + offline testler (315/315)
3. ✅ `sim/` motoru: 4 model, Kazanç/Başabaş/Kayıp %, expectancy, güven aralıkları, seri riski
4. ⏳ `desk/` çoklu ajan masası (Tarayıcı, Haberci, Giriş-Çıkış, Şüpheci, Karar)
5. ⏳ `runner/` zamanlayıcı (systemd timer), loglar, sağlık kontrolü
6. ⏳ `.claude/skills/`, `.claude/agents/` ve izin kısıtları
