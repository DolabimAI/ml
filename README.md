# DolabımAI · ml

Görüntü işleme ve öneri motoru için ortak Python deposu.
E1 modülü, onaylanmış kıyafetlerden hava ve etkinliğe uygun kombin adayları üretir.
E2 modülü, bu adaylar arasından sabit renk kurallarıyla Kural Kartı seçer.

## İş bölümü

| Bileşen | Görev |
|---|---|
| Görüntü analizi | FashionCLIP ile alt tür tahmini; piksel analiziyle renk, ton ve desen |
| Öneri motoru | Onaylanmış kıyafet etiketlerinden aday üretimi, kural kartı ve öğrenen kart |
| C# API | Veritabanı işlemleri, hava ve karar geçmişini Python'a iletme |

E1 fotoğraf veya FashionCLIP çıktısını doğrudan işlemez. C#'tan gelecek onaylanmış
kıyafet verilerini kullanır; mevcut test dolabı bu verileri temsil eder.

## Kurulum

Python 3.12 kullanılır. E1 ve E2 yalnız standart kütüphaneye ihtiyaç duyar;
bu modülleri çalıştırmak için FastAPI, pandas veya scikit-learn kurulması gerekmez.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m unittest discover -s tests -v
python -m recommendation.demo
```

Windows'ta etkinleştirme: `.venv\Scripts\activate`.
Komutlar depo kökünde çalıştırılır. Etkinleştirmeden de
`.venv/bin/python -m unittest discover -s tests -v` kullanılabilir.
`.venv` Git tarafından yok sayılır; başka bilgisayara kopyalanmaz.

## Deneme

```bash
python -m recommendation.demo --temperature 10 --weather yagmurlu --style gunluk
python -m recommendation.demo --temperature 28 --weather gunesli --style is
python -m recommendation.demo --temperature 6 --weather karli --style gunluk
python -m recommendation.demo --method rule
python -m recommendation.demo --method rule --temperature 28 --weather gunesli --style is
```

Demo varsayılan olarak ilk beş adayı, aday sayısını ve kullanılan yedek kuralları
gösterir. `--method rule` ayrıca seçilen Kural Kartını, puanını ve eşit puanlı aday
sayısını gösterir. `--seed 42` aynı girdilerle aynı aday sırasını ve kart seçimini
yeniden üretir.

## Veri kaynağı ve kapsam

- Kodlar ve alt tür başlangıç değerleri:
  [api PR #1](https://github.com/DolabimAI/api/pull/1),
  commit `419213967d5c35a7ad264a5d31b9ee067068a435`, `002` ve `003` SQL dosyaları.
- `recommendation/catalog.json` bu kaynağın yerel kopyasıdır. Canlı Supabase
  verisi çekilmez.
- `tests/sample_wardrobe.json` 35 sentetik parça içerir: 8 üst, 8 alt, 7 ayakkabı,
  5 dış giyim, 5 tek parça ve 2 aksesuar. İki dolap şablonunun asgari sayılarını karşılar.
- Dış giyim kategori kodu `dis`; desen alanı `is_patterned` boolean'dır.
  Hava alanları `avoid_when_wet`, `preferred_when_wet`, `preferred_when_hot` olarak korunur.
- JSON biçimi **yerel test sözleşmesidir**; C# API sözleşmesi olarak kullanılmamalıdır.
  C# kıyafetin güncel özelliklerini ve alt türün hava
  işaretlerini birleştirir. Varsayılan tarzlar kullanıcının güncel tarzının yerine geçmez.
- E1'de aksesuarlar adaylara veya tekrar anahtarlarına katılmaz.
  E1, dolabın uygulamadaki başlangıç sayısı şartını uygulamaz;
  verilen uygun parçalarla aday üretir. Dolap hazır olma kontrolü C#'ın sorumluluğudur.

## E1 davranışı

1. Yalnız `onayli` ana parçalar değerlendirilir.
2. Hissedilen sıcaklık aralığına (iki sınır dahil) ve güncel etkinlik tarzına göre süzülür.
3. Islak havada kaçınılan ayakkabılar çıkarılır; dış giyim ıslakta tercih edilenlerle sınırlanır.
4. Islak olmayan, güneşli ve en az 25 °C havada ayakkabılar sıcakta tercih edilenlerle sınırlanır.
5. Üst + alt + ayakkabı ve tek parça + ayakkabı üretilir. Uygun dış giyim varsa her adaya
   bir dış giyim eklenir. Parça düzeyindeki filtreler, gereksiz kombin üretmemek için
   kartezyen çarpımdan önce uygulanır.
6. Oturumda reddedilen kombinler çıkarılır. Tekrar anahtarı sıralanmış parça id'leridir;
   dış giyim dahildir. Geçmiş oturumların redlerini bu listeye C# eklememelidir.

Islak/sıcak hava adımı bir konumda sıfır parça bırakırsa yalnız o konumda o hava adımı
gevşetilir. Sıcaklık, etkinlik ve tekrar engeli korunur. Bu nedenle yalnız sandaletin
kaldığı yağmurlu bir durumda yedek kural sandaletli aday üretebilir.

Sıcaklık ve etkinlik filtrelerini geçmeyen dış giyim tekrar eklenmez.
Uygun dış giyim hiç yoksa dış giyimsiz aday gelir. Bu yorumun gerekçesi ve teyit durumu
[E1 rapor notunda](docs/E1-notes.md#belgelerdeki-belirsizlik-için-seçilen-yorum) açıklanır.

`recommendation/settings.json`: sıcak gün eşiği 25 °C, aday sınırı 500.
500 bir proje şartı değil, E1 için seçilmiş başlangıç ayarıdır. Kombin uzayında
rastgele başlangıç ve aralarında asal adımla gezinilir; bütün kombin listesi oluşturulmaz.
Bu yöntem eşit olasılıklı alt küme örneklemesi değildir. İki yöntem aynı üretilmiş
havuzu kullanmalı; iki kart için E1 ayrı ayrı çalıştırılmamalıdır.

`candidate_space_size`, tekrar engelinden önceki kombin sayısıdır.
`limit_reached`, dönen aday sayısının sınıra ulaştığını belirtir; dışarıda mutlaka
başka geçerli aday kaldığı anlamına gelmez. Aday yoksa boş tuple döner.

## E2 davranışı

`select_rule_outfit(pool.candidates)` E1'in ürettiği havuzdan bir kart seçer.
Dış giyim dahil bütün ana parça çiftleri puanlanır; aksesuarlar değerlendirilmez.
Nötr, aynı veya komşu renk çiftleri 3; tanımlı karşıt çiftler 2; diğer çiftler 1
puan alır. Çift puanlarının ortalamasından, ikiden fazla her farklı canlı renk için
0,5 puan düşülür. Sonuç sıfırın altına inmez.

En yüksek puanlı adaylar arasındaki eşitlik rastgele çözülür. Boş havuzda `None`
döner. Sonuç, `outfit`, `score` ve `tied_best_count` alanlarını içerir; puan
dökümünde ortalama, farklı canlı renk sayısı, ceza ve toplam bulunur.

Renk grupları ve puanlar [rule_settings.json](recommendation/rule_settings.json)
dosyasındadır. Ton ve desen için ek ağırlık uygulanmaz. Bu kurallar kullanıcı
geçmişinden öğrenilmez; renk uyum bilgisi öğrenen yönteme özellik olarak verilmez.

## Dokümantasyon

Geliştirme durumu, test sonuçları, uygulama kararları ve bekleyen işler
[E1 rapor notunda](docs/E1-notes.md) ve [E2 rapor notunda](docs/E2-notes.md) tutulur.
