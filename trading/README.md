# trading/ — analiz, backtest ve simülasyon katmanı

Next.js uygulamasından izole, saf Python. Canlı emir yok. Önce `DISCLAIMER.md`.

## Yapı

```
trading/
├── DISCLAIMER.md
├── requirements.txt          numpy (yalnızca sim/ için)
├── config/
│   ├── trader.config.example.json   risk + bütçe sınırları (upstream formatı)
│   ├── desk.example.json            masa eşikleri (karar koşulları, tarayıcı, veri kapısı)
│   └── sim.example.json             iterasyon, seed, başabaş bandı, maliyetler, modeller
├── sim/                     çoklu model Monte Carlo motoru (numpy)
├── desk/                    çoklu ajan masası: tartışma protokolü + AL/BEKLE/GEÇ
│   └── agents/              scanner, news, entry_exit, skeptic
├── tests/sim/, tests/desk/  offline testler
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
cp config/desk.example.json trader/desk.json
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

## Çoklu ajan masası (`desk/`)

Bir plan, beş rolün sabit turlarda tartıştığı bir masadan geçer. Ajanlar kurala
dayalıdır: aynı girdi aynı tartışmayı ve kararı üretir.

| Rol | Bakar | Örnek iddia |
|---|---|---|
| Tarayıcı | Aynı saat dilimine göre göreli hacim, aralık genişlemesi, gap, açılış aralığı kırılımı | "Hacim ortalamanın 2.3 katı (z=3.1)" |
| Haberci | Son N saatin başlıkları (vendor etiketleri), tazelik, risk/durdurma etiketleri | "Katalizör var, fiyat aynı yönde +2.7%" |
| Giriş-Çıkış | Ödül/risk, stop'un bar gürültüsüne oranı, hedefin kalan seansta erişilebilirliği, kovalama, giriş penceresi | "Hedef medyan hareketin ötesinde" |
| Risk & Şüpheci | Simülasyon güven aralıkları, trend etkisi, stres kuyruğu, tarihsel örneklem, veri uyarıları, pozisyon büyüklüğü | "Pozitif kenar kanıtı yok" |
| Karar | Kurallar; oylama değil | AL / BEKLE / GEÇ |

**Turlar:** R0 veri kapısı → R1 bağımsız bulgular (ajanlar birbirini görmez) →
R2 çapraz sorgu (Şüpheci her lehte iddiaya sayıyla itiraz etmek zorunda) →
R3 savunma (uyarı/kritik itirazlar sahibine döner: savun ya da kabul et) → R4 karar.

**Karar kuralları** (`config/desk.example.json`):
- **GEÇ**: herhangi bir kritik mesaj (bayat veri, risk limiti, tüm modeller negatif, işlem durdurma).
- **AL** (yalnızca paper): temel modellerde expectancy alt sınırı > 0, stres tabanı sağlanıyor,
  tarihsel tetik ≥ 20 ve ort. R > 0, açık çelişki ≤ 1, güven ağırlıklı görüş skoru > 0.
- **BEKLE**: diğer her durum; raporda hangi koşulun sağlanmadığı yazılır.

```bash
python3 -m desk run                         # trader/plan.json, canlı veri + başlıklar
python3 -m desk run --offline vendor/day-trader-skill/tests/fixtures/trader-timemachine/TSLA-60d5m.json.gz \
    --news-offline vendor/day-trader-skill/tests/fixtures/trader-news/yahoo-TSLA.xml \
    --symbol TSLA --date 2026-10-19 --entry 364.18 --stop 358.32 --target 370.04 \
    --entry-time "10:15 AM" --now "2026-10-19 10:15"
```

Her çalıştırma `logs/desk/<tarih>/<run id>/` altına `transcript.jsonl`, `decision.json`,
`sim.json`, `sim.md`, `report.md` yazar ve `logs/desk/index.jsonl`'a bir satır ekler.
Çıkış kodu: 0 masa çalıştı (karar ne olursa), 2 girdi/veri hatası.

## Test

```bash
python3 -m unittest discover -s tests -t .                                  # sim + desk (54 test)
cd vendor/day-trader-skill && python3 -I -m unittest discover -s tests      # upstream (315 test)
```

## Yol haritası

1. ✅ İskelet, config, sorumluluk sınırı
2. ✅ Upstream vendor + offline testler (315/315)
3. ✅ `sim/` motoru: 4 model, Kazanç/Başabaş/Kayıp %, expectancy, güven aralıkları, seri riski
4. ✅ `desk/` çoklu ajan masası (Tarayıcı, Haberci, Giriş-Çıkış, Şüpheci, Karar)
5. ⏳ `runner/` zamanlayıcı (systemd timer), uygulama logu, sağlık kontrolü, isteğe bağlı Claude anlatım katmanı
6. ⏳ `.claude/skills/`, `.claude/agents/` ve izin kısıtları
