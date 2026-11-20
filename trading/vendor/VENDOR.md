# Vendored: day-trader-skill

| | |
|---|---|
| Kaynak | https://github.com/Jakeschincariol/day-trader-skill |
| Commit | `3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd` (2026-10-20) |
| Lisans | MIT (`day-trader-skill/LICENSE`) |
| Bütünlük | `day-trader-skill.MANIFEST.sha256` |

Değiştirilmeden kopyalandı (`.git` hariç). Doğrulama:

```bash
cd trading/vendor/day-trader-skill && sha256sum -c --quiet ../day-trader-skill.MANIFEST.sha256
```

Upstream testleri (offline, fixture tabanlı, 315 test):

```bash
cd trading/vendor/day-trader-skill && python3 -I -m unittest discover -s tests
```

## Güvenlik incelemesi (statik, kopyalamadan önce)

- Bağımlılık: yalnızca Python standart kütüphanesi.
- Ağ: yalnızca okuma (Yahoo Finance, Stooq, SEC EDGAR, House Clerk, Nasdaq Trader).
- `subprocess`: yalnızca `trader-pelosi/ptr.py` içinde `pdftotext` çağrısı.
- Emir: `trader-broker/ticket.py` hiçbir brokera bağlanmaz; fiş ve log üretir.
  Gerçek emir harici bir broker MCP sunucusu gerektirir. **Bu kurulumda broker
  MCP yapılandırılmaz**; `claude_desktop_config.example.json` kullanılmaz.

Güncelleme: yeni commit'i ayrı bir dalda kopyala, manifest'i yeniden üret,
diff'i incele, testleri çalıştır.
