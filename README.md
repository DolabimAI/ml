# DolabımAI · ml

Görüntü işleme ve öneri motoru için ortak Python deposu.
E1 modülü, onaylanmış kıyafetlerden hava ve etkinliğe uygun kombin adayları üretir.
E2 modülü, bu adaylar arasından sabit renk kurallarıyla Kural Kartı seçer.
E3 modülü, kombin ve bağlamı öğrenen yöntemin kullanacağı sayısal özelliklere dönüştürür.
E4 modülü, kullanıcının geçmiş kararlarından öğrenerek aynı aday havuzundan Öğrenen Kartı seçer.
E6 modülü, iki karta birlikte eklenecek aksesuarları ortak ve sabit bir kuralla seçer.
E7, bunları C#'ın çağırdığı `POST /recommend` ucunda birleştirir.
E10 modülü, sentetik bir kullanıcı profiliyle iki kartı karşılaştırıp öğrenme grafiği üretir.

## İş bölümü

| Bileşen | Görev |
|---|---|
| Görüntü analizi | FashionCLIP ile alt tür tahmini; piksel analiziyle renk, ton ve desen |
| Öneri motoru | Onaylanmış kıyafet etiketlerinden aday üretimi, kural kartı ve öğrenen kart |
| C# API | Veritabanı işlemleri, hava ve karar geçmişini Python'a iletme |

E1 fotoğraf veya FashionCLIP çıktısını doğrudan işlemez. C#'tan gelecek onaylanmış
kıyafet verilerini kullanır; mevcut test dolabı bu verileri temsil eder.

## Kurulum

Python 3.12 kullanılır. E1, E2 ve E3 yalnız standart kütüphaneye ihtiyaç duyar;
E4 için sürümü sabitlenmiş scikit-learn, E10 grafiği için matplotlib, servis ve
E7 `/recommend` ucu için FastAPI ve bunların bağımlılıkları kurulur. pandas gerekmez.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
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
python -m recommendation.demo --method features
python -m recommendation.demo --method learned
python -m recommendation.demo --method learned --history tests/sample_history.json --user-id demo
python -m recommendation.demo --method learned --history tests/sample_history.json --user-id demo --seed 31
python -m recommendation.demo --method accessories --temperature 5 --weather kapali
python -m recommendation.demo --method accessories --temperature 28 --weather gunesli
python -m recommendation.demo --method accessories --temperature 28 --weather gunesli --night
python -m recommendation.synthetic --profile notr_koyu
```

Demo varsayılan olarak ilk beş adayı, aday sayısını ve kullanılan yedek kuralları
gösterir. `--method rule` ayrıca seçilen Kural Kartını, puanını ve eşit puanlı aday
sayısını gösterir. `--method features` özellik şemasını, vektör boyutunu ve ilk
adayın sıfırdan farklı özelliklerini gösterir. `--seed 42` aynı girdilerle aynı
aday sırasını ve kart seçimini yeniden üretir. Özellik dönüşümü rastgelelik içermez.
`--method learned` geçmiş verilmezse soğuk başlangıcı gösterir. Örnek geçmişle
varsayılan tohum model seçimini, `--seed 31` keşfi gösterir. Demo mod, sayaçlar ve
örnek sayılarını; model seçiminde ayrıca tahmini olasılığı yazar.
`--method accessories` aynı havuzdan iki kartı seçip E6 aksesuarlarını, ortalama çift
puanını ve eşit puanlı aday sayısını yazar. Varsayılan istek gündüzdür ve aksesuar
istenmiştir; `--night` akşam/gece isteğini, `--no-accessories` aksesuar istenmemesini gösterir.

## Servis (D1)

Görüntü (`vision/`) ve öneri (`recommendation/`) modülleri tek FastAPI servisinde çalışır.

```bash
cp .env.example .env          # Windows: copy .env.example .env
python -m uvicorn service.main:app --reload
curl http://127.0.0.1:8000/health
```

- `GET /health` servis durumunu, bağlanan modülleri ve ortak kod sayılarını döner.
- Bir modül, `<modül>/router.py` içinde `router` adlı bir `APIRouter` tanımladığı anda servis onu
  kendiliğinden bağlar; `service/main.py`'ye dokunmak gerekmez. Ömer için: `recommendation/router.py`.
- Ortak kodlar (35 alt tür, 13 renk, 3 ton) tek kaynak olan `shared/codes.json` dosyasındadır ve
  `service/codes.py` ile okunur. Kodlar C# ve öneri modülüyle harfi harfine aynı kalmalıdır.
- Ayarlar `.env` dosyasından okunur (`service/config.py`). Gerçek `.env` depoya girmez.
- Python veritabanına bağlanmaz; görüntü modülü yalnızca görsel deposuna yazar.

## Görüntü modülü (D2–D6)

| Dosya | Görev |
|---|---|
| `vision/background.py`, `image_settings.json` | Arka plan temizleme (rembg u2net), WebP küçültme (300 KB hedefi), kıyafet maskesi |
| `vision/storage.py` | Temiz görseli Supabase deposuna yazar, gerekirse siler; yol `<kullanıcı-id>/<rastgele-ad>.webp` (bucket içinde) |
| `vision/router.py` | D7: `POST /analyze` (görsel işleme + alt tür + renk, ton, desen tek istekte) |
| `vision/subtype.py`, `subtype_settings.json` | FashionCLIP alt tür tahmini; 35 etiket ifadesi, güven eşiği 0,40 |
| `vision/color.py`, `color_settings.json` | k-means, HSV, nötr renk tablosu, ton ve desen |
| `vision/check.py` | D3: 20 fotoğrafta kontrol (`python -m vision.check --photos ... --labels ...`) |
| `shared/subtypes.json` | D5: `subtypes` tablosunun 35 satırı (Zehra yükler) |

Eşikler ve etiket ifadeleri kodda değil ayar dosyalarındadır; 7 Aralık'ta dondurulur.
Arka plan modeli testi isteğe bağlıdır: `ML_RUN_MODEL_TESTS=1 python -m unittest tests.test_background`
(u2net ağırlıklarını ~176 MB indirir). FashionCLIP için ek bağımlılıklar `requirements-fashionclip.txt`
içindedir; bu kurulum ve gerçek modelle tahmin henüz denenmedi.

## Görüntü servisini sıfırdan kurma (D8)

Bu bölüm yeni bir bilgisayarda (Mac veya Windows) `/analyze` ucunu çalıştırmak içindir.
Öneri motoru için yukarıdaki "Kurulum" yeterlidir; burada ek olarak görüntü modelleri kurulur.

**Gerekenler:** Python 3.12 (`.python-version` dosyası 3.12'dir), Git, yaklaşık 3 GB boş disk, ilk indirme için internet.

| Adım | Mac / Linux | Windows (cmd) |
|---|---|---|
| Sanal ortam | `python3.12 -m venv .venv` | `py -3.12 -m venv .venv` |
| Etkinleştirme | `source .venv/bin/activate` | `.venv\Scripts\activate` |
| Temel paketler | `python -m pip install -r requirements.txt` | aynı |
| FashionCLIP paketleri | `python -m pip install -r requirements-fashionclip.txt` | aynı |
| Ayar dosyası | `cp .env.example .env` | `copy .env.example .env` |

1. `.env` içine `SUPABASE_URL` ve `SUPABASE_SERVICE_KEY` değerlerini yazın. Anahtarı Zehra ayrıca verir; **sohbete, commit'e veya PR'a yazılmaz**. `.env` Git tarafından yok sayılır.
2. C# tarafında `appsettings.json > Python:BaseUrl`, `.env` içindeki `ML_HOST` ve `ML_PORT` ile aynı adres olmalıdır (geliştirmede `http://localhost:8000`).
3. Modeller ilk çalıştırmada kendiliğinden iner ve yerel önbelleğe yazılır:
   - arka plan modeli u2net (rembg), yaklaşık 176 MB, `~/.u2net` klasörüne;
   - FashionCLIP (`patrickjohncyh/fashion-clip`), yaklaşık 600 MB, Hugging Face önbelleğine (`~/.cache/huggingface`).

   İlk açılış bu yüzden dakikalar sürebilir; sonraki açılışlar önbellekten yüklenir. Önceden indirmek için servisi bir kez açıp `GET /health` cevabını beklemek yeterlidir.
4. Servisi başlatın (depo kökünde): `python -m uvicorn service.main:app --host 127.0.0.1 --port 8000`.
5. Denemek için: `curl http://127.0.0.1:8000/health`, ardından aşağıdaki `/analyze` örneği.

**Bellek ölçümü.** Servis açık ve boştayken ve bir `/analyze` isteğinden sonra süreç belleğine bakın.
Mac/Linux: `ps -o rss= -p <PID>` (KB cinsinden). Windows: Görev Yöneticisi'nde `python.exe` satırının "Bellek" değeri.
Ölçülen değerleri `docs/D3-notes.md` dosyasına, hangi bilgisayarda ölçüldüğüyle birlikte yazın; başka bilgisayardaki değer buradan tahmin edilmez.

**Sık sorunlar**

| Belirti | Neden / çözüm |
|---|---|
| `ModuleNotFoundError: multipart` | `requirements.txt` kurulmamış; `python -m pip install -r requirements.txt` |
| Açılışta `model yüklenemedi` log'u | FashionCLIP paketleri kurulmamış ya da indirme başarısız; internet ve `requirements-fashionclip.txt` kontrol edilir. Servis açılır, model ilk istekte yeniden denenir. |
| `500 internal_error` | `.env` içinde `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` boş olabilir ya da bucket (`gorseller`) yoktur; ayrıntı servis log'unda |
| C# `502 analysis_failed` | Python kapalı, adres farklı ya da istek 30 sn'yi aştı; önce `/health` |
| `.venv` etkinleşmiyor (Windows PowerShell) | `cmd` kullanın ya da `Set-ExecutionPolicy -Scope Process RemoteSigned` |

## POST /analyze (D7)

Sözleşme: [`DolabimAI/api` → `contracts/python-api.md`](https://github.com/DolabimAI/api/blob/main/contracts/python-api.md), bölüm 5 ve 8.

```bash
curl -F image=@foto.jpg -F userId=178eaf32-7cf1-4399-8957-6532e4c7fc91 http://127.0.0.1:8000/analyze
```

- Cevap `200`: `imagePath`, `subtype`, `subtypeConfidence` (3 ondalık), `color`, `tone`, `isPatterned`, `rawColor` (camelCase).
- Python güven ne olursa olsun en olası alt türü döner; 0,40 eşiğini C# uygular.
- Hatalar `{"code","message"}` biçimindedir: `422 image_unreadable`, `422 invalid_request`, `500 internal_error`.
- Görsel depoya yazıldıktan sonra bir adım başarısız olursa yazılan görsel silinir.
- Modeller (rembg, FashionCLIP) servis açılırken bir kez yüklenir; her istek süresi log'a yazılır.
- Gerçek bir istek `SUPABASE_URL` ve `SUPABASE_SERVICE_KEY` ister (`.env`); testler depoyu ve modelleri taklit eder
  (`tests/test_analyze.py`), gerçek modelle ve gerçek depoyla deneme henüz yapılmadı.

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

## E3 davranışı

`encode_outfit(outfit, weather, style)` bir kombin için sayısal tuple döndürür.
`encode_outfits(candidates, weather, style)` adayların sırasını koruyarak hepsini
kodlar; boş havuzda boş tuple verir. `feature_names()` sütun adlarını aynı sırada
döndürür. Bu fonksiyonlar [features.py](recommendation/features.py) modülündedir.

`e3_v1` şeması mevcut katalogda 126 sütundur. Üst, alt, tek parça, dış giyim ve
ayakkabının varlığı, alt türü, rengi, tonu ve deseni ayrı alanlarda kodlanır.
Etkinlik, hissedilen sıcaklık ve farklı canlı renk sayısı eklenir. Bulunmayan
konumun alanları sıfırdır; aksesuarlar özelliklere dahil edilmez.

E3, E2'nin puanlarını veya renk ilişkilerini kullanmaz; eğitim ya da kart seçimi
yapmaz. Aynı şema geçmiş eğitim örnekleri ve yeni adaylar için kullanılır.
Sütun düzeni, örnek dönüşüm ve E4'e bağlantı [E3 rapor notunda](docs/E3-notes.md)
açıklanır.

## E4 davranışı

`select_learned_outfit(candidates, weather, style, history, user_id=...)` aynı E1
havuzundan bir `LearnedSelection` seçer; boş havuzda `None` döndürür. Başka kullanıcıya
ait geçmiş kabul edilmez. `history` karar anındaki kombin etiketlerini ve bağlamı
taşır; güncel dolaptan veya mevcut havadan geçmiş veri türetilmez.

Geçerli son karar sayısı 10'dan azsa rastgele `soguk_baslangic` seçimi yapılır.
En az 10 karar ve hem pozitif hem negatif eğitim örneği varsa model her çağrıda
yeniden eğitilir. Sonra %10 olasılıkla rastgele `kesif`, diğer durumda en yüksek
`P(y=1)` puanıyla `model` seçimi yapılır. Yalnız bir sınıf varsa mod yine
`soguk_baslangic`, neden `tek_sinif` olur. Rastgele seçimlerde olasılık verilmez.

Kural kararları için ayrı öğrenme sınırı vardır: ilk 10 tamamlanmış kural kararının
örnekleri eğitimde kalır; sınırdan sonraki kararlarda yeni kural kaynaklı örnekler
alınmaz. Bir karşılaştırma birden çok örnek üretse de karar sayacı bir artar.
Tam karar tablosu ve seçilen yorumlar [E4 rapor notunda](docs/E4-notes.md) açıklanır.

E4, E3'ün 126 sütununu kullanır; yalnız sıcaklık ve canlı renk sayısı geçmiş eğitim
verisine göre ölçeklenir. E2 puanları kullanılmaz. Model kullanıcılar arasında
paylaşılmaz ve diske kaydedilmez. [Öğrenen ayarları](recommendation/learned_settings.json)
eşikleri, keşif oranını ve model parametrelerini içerir.

`tests/sample_history.json`, `demo` kullanıcısı için 12 sentetik son kararın tam
etiket kopyalarını içerir. Bu JSON yerel test sözleşmesidir; C# API sözleşmesi değildir.

## E5 davranışı

`POST /swap`, A3 sözleşmesinin 7. bölümüne göre seçilen kombinde tek bir parçayı ya da
aksesuarı değiştirir ve tek bir yeni parça önerir: `{"status": "ok", "newItemId": 6}`.
Uygun parça kalmadıysa `{"status": "no_alternative"}` döner; bu bir hata değildir.

- `kural`: hedef yere gelebilecek her parça, kombinin kalan parçalarıyla E2'ye göre
  puanlanır; en yüksek puanlı seçilir.
- `ogrenen`: E4 modeli `history` ile bu istekte eğitilir; o yer için en yüksek olasılıklı
  parça seçilir. Değiştirmede keşif yoktur; soğuk başlangıçta aday rastgele seçilir.
- `ortak_kural`: hedef aksesuarla aynı alt türden, E6'nın aday adımlarından geçen
  aksesuarlar kombinin o anki hâline göre sıralanır; ilk sıradaki önerilir.

E1'in ortak ön filtresi ([filter.py](recommendation/filter.py) `filter_slots`) geçerlidir.
`excludedItemIds` ve şu anki parça filtreden sonra çıkarılır; ıslak/sıcak yedeğini
tetiklemez. Akış FastAPI'den bağımsız olarak [swap.py](recommendation/swap.py) içindedir.
Hata biçimi `/recommend` ile aynıdır.

```bash
python -m uvicorn service.main:app --reload
curl -X POST http://127.0.0.1:8000/swap -H 'Content-Type: application/json' \
  --data-binary @tests/contracts/swap-request.json
```

Ayrıntılar ve seçilen yorumlar [E5 rapor notunda](docs/E5-notes.md).

## E6 davranışı

`select_accessories(cards, wardrobe, weather, style, is_daytime=..., wants_accessories=...)`
bir ya da iki kart için **tek** aksesuar listesi döndürür; aynı aksesuarlar iki karta
eklenir. Aksesuar istenmediyse liste boştur. Hissedilen sıcaklık 10 °C'nin altındaysa
atkı, bere ve eldiven; gündüz, güneşli ve 20 °C'nin üstündeyse şapka ve güneş gözlüğü
aday olur. Etkinlik izin tablosunun izin vermediği ve dolapta onaylı olmayan aksesuar çıkar.

Aynı türden birden fazla aday varsa her aday, kartların referans parçasıyla E2 çift
puanına göre puanlanır ve iki kartın ortalaması en yüksek olan seçilir; tek kartta yalnız
o kart kullanılır. Referans parça dış giyimdir, yoksa üst giyim, tek parça şablonunda tek
parçadır. Eşit puanlılar dışarıdan verilen `rng` ile seçilir. E5 aksesuar değiştirmede
(`ortak_kural`) aynı `accessory_candidates` ve `rank_accessories` fonksiyonlarını seçilen
kombinin o anki hâliyle kullanır.

Eşikler ve izin tablosu [aksesuar ayarlarında](recommendation/accessory_settings.json)
durur. Parçanın `styles` alanı aksesuarda kullanılmaz. Aksesuar seçimi öğrenmeye girmez.
Kural gerekçeleri ve seçilen yorumlar [E6 rapor notunda](docs/E6-notes.md) açıklanır.

## E7 davranışı

`POST /recommend`, A3 sözleşmesinin 6. bölümüne göre bir karşılaştırmanın iki kartını
birlikte üretir. E1 bir kez çalışır; E2 Kural Kartını ve E4 Öğrenen Kartı aynı havuzdan
seçer; E6 iki karta aynı aksesuarları ekler. İki yöntem aynı ana parça kümesini seçtiyse
`isSameOutfit: true` döner ve aksesuar tek karta göre seçilir. Uygun kombin yoksa
`{"status": "no_candidates"}` döner; bu bir hata değildir.

```bash
python -m uvicorn service.main:app --reload
curl -X POST http://127.0.0.1:8000/recommend -H 'Content-Type: application/json' \
  --data @tests/contracts/recommend-request.json
```

İstek camelCase gelir; [schemas.py](recommendation/schemas.py) bunu mevcut `ClothingItem`,
`Weather` ve `ComparisonDecision` modellerine çevirir. Akış FastAPI'den bağımsız olarak
[recommend.py](recommendation/recommend.py) içindedir. Bilinmeyen alan, yanlış tür,
bilinmeyen kod ya da geçmişte `KT, KD, KR, OT, OD, OR, HB` dışındaki bir sonuç
`422 {"code": "invalid_request", ...}`, beklenmeyen hata `500 {"code": "internal_error", ...}`
döner. FastAPI'nin `{"detail": [...]}` cevabı dönmez. Model saklanmaz; her istekte geçmişten
yeniden eğitilir.

[tests/contracts/](tests/contracts/) api deposundaki sözleşme örneklerinin kopyasıdır
(`contracts/examples/`, A3 PR #6). Sözleşme değişirse bu kopyalar da güncellenir.
Ayrıntılar [E7 rapor notunda](docs/E7-notes.md).

## E10 davranışı

**Sonuçlar sentetiktir; gerçek kullanıcı verisi değildir.**
`python -m recommendation.synthetic --profile <profil>` her karşılaştırmada bağlam
(sıcaklık, hava, etkinlik) çeker, E1'i bir kez çalıştırır ve aynı havuzdan E2 Kural
Kartını ve E4 Öğrenen Kartını seçer. Profil iki kartı kendi zevk kuralıyla karşılaştırır;
sonuç (KT, OT, HB, AT, AR) `ComparisonDecision` olarak geçmişe eklenir ve bir sonraki
öğrenen seçimine verilir. Profil parça değiştirmez ve tepkisiz kalmaz.

Profiller [synthetic_profiles.json](recommendation/synthetic_profiles.json), tekrar
sayısı, karar sayısı, pencere ve bağlam dağılımı
[synthetic_settings.json](recommendation/synthetic_settings.json) dosyasındadır.
Komut `docs/figures/E10-<profil>.png` grafiğini ve sıra sıra değerleri içeren CSV'yi
yazar. `--runs`, `--decisions`, `--output-dir`, `--wardrobe` ve `--no-plot` seçenekleri
vardır. İlk profil `notr_koyu`; kalan dört profil persona kartları kesinleşince eklenir.

## Dokümantasyon

Geliştirme durumu, test sonuçları, uygulama kararları ve bekleyen işler
[E1 rapor notunda](docs/E1-notes.md), [E2 rapor notunda](docs/E2-notes.md),
[E3 rapor notunda](docs/E3-notes.md), [E4 rapor notunda](docs/E4-notes.md),
[E5 rapor notunda](docs/E5-notes.md), [E6 rapor notunda](docs/E6-notes.md), [E7 rapor notunda](docs/E7-notes.md) ve
[E10 rapor notunda](docs/E10-notes.md) tutulur.
