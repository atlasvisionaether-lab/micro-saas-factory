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

## Test

```bash
cd vendor/day-trader-skill && python3 -I -m unittest discover -s tests
```

## Yol haritası

1. ✅ İskelet, config, sorumluluk sınırı
2. ✅ Upstream vendor + offline testler (315/315)
3. ⏳ `sim/` motoru: çoklu model, Kazanç/Başabaş/Kayıp %, expectancy, güven aralıkları
4. ⏳ `.claude/skills/` ve izin kısıtları
5. ⏳ Uçtan uca örnek
