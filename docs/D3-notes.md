# D3 notları: gerçek modelle ilk kontrol

**Durum: henüz yapılmadı.** Bu dosya, kontrol yapıldığında doldurulacak şablondur. Boş bırakılan yerlere tahmin yazılmaz.

Araç: `python -m vision.check --photos <klasör> --labels labels.csv --out sonuc.csv` (bkz. README, "Görüntü modülü").
Fotoğraflar ve `labels.csv` (A5: 20 fotoğraf, `dosya,alt_tur,renk`) depoya yüklenmez.

## Ortam

| Alan | Değer |
|---|---|
| Bilgisayar / işletim sistemi | |
| Python sürümü | |
| `transformers` / `torch` sürümleri | |
| Tarih | |

## Sonuçlar

| Ölçü | Değer |
|---|---|
| Fotoğraf sayısı | |
| Alt tür doğru (en yüksek tahmin) | / |
| Alt tür doğru (0,40 eşiği sonrası) | / |
| Renk doğru | / |
| Fotoğraf başına ortalama süre (sn) | |
| Servis boşta bellek (MB) | |
| `/analyze` sonrası bellek (MB) | |

## Yanlışlar ve gözlemler

| Dosya | Beklenen | Tahmin | Not |
|---|---|---|---|
| | | | |

## Ayar değişikliği önerileri

Eşik ve etiket ifadeleri `vision/*_settings.json` içindedir; 7 Aralık'ta dondurulur. Değişiklik yapılırsa nedeni ve önce/sonra sonucu buraya yazılır.
