# İçerik Üretim + Instagram Yayın Pipeline'ı (Python, çoklu proje destekli)

RSS → LLM (metin) → Pillow (görsel) → GitHub Actions (zamanlama + barındırma) →
Instagram Graph API (yayın). Maliyet hedefi: içerik başına **~$0**.

Mimari **çoklu proje** için tasarlandı: `projects/` altında her klasör ayrı bir
RSS kaynağı seti + ayrı bir Instagram hesabı besleyen bağımsız bir "proje"dir.
Şu an tek proje var (`ankara` — 6saniyedeankara), ama yarın `izmir`, `bursa`
gibi başka hesaplar için `projects/` altına yeni bir klasör eklemek yeterli —
kod tarafında hiçbir şey değiştirmeniz gerekmiyor.

## ⚡ Önemli keşif: Instagram API erişimi büyük ihtimalle ZATEN HAZIR

`instagramankara` klasörünüzdeki `instagram_api_config.json` dosyasında zaten
çalışan bir Instagram Graph API kurulumu buldum:

- Business Account ID: `17841446264757964` (6saniyedeankara)
- Meta App: `ankaraposter` (app id `1803628844096044`)
- `instagram_business_basic` ve `instagram_business_content_publish` izinleri
  bu uygulama üzerinde tanımlı görünüyor.
- Uzun ömürlü (long-lived) access token, **2026-08-30'da üretilmiş, ~60 gün
  geçerli → yaklaşık 2026-10-29'da yenilenmesi gerekecek** (bkz. aşağıda
  "Token yenileme").

Bu doğruysa önceki raporumda bahsettiğim "Meta App Review için 2-4 hafta
bekleme" adımına muhtemelen GEREK YOK — bu zaten yapılmış. Ben kendi ortamımdan
(ağ erişimi kısıtlı) bu token'ı canlı test edemedim; ilk gerçek deneme
aşağıdaki "Kurulumu doğrulama" adımında olacak. Token çalışmazsa (süresi
dolmuş/izinler yetersizse) Meta Geliştirici Panelinden aynı uygulama üzerinden
yeni bir token üretmeniz yeterli olur, yeniden App Review gerekmez.

## Klasör yapısı

```
core/               # paylaşılan mantık (tüm projeler ortak kullanır)
  rss_fetch.py        RSS kaynaklarını çekip normalize eder
  filters.py           mekanik ön-filtre (görselsiz/eski/kullanılmış eleme)
  llm.py                aday seçimi + metin üretimi (Gemini/Groq/Claude)
  image_gen.py           Pillow ile 1080x1920 görsel üretimi
  publish_ig.py           Instagram Graph API yayın
  hosting.py               GitHub raw URL hesaplama
  state.py                  CSV tabanlı "daha önce paylaşıldı" takibi
  pipeline.py                hepsini birbirine bağlayan orkestrasyon
projects/
  _template/          yeni proje eklerken kopyalanacak şablon
  ankara/               mevcut proje (6saniyedeankara)
    config.yaml           RSS kaynakları, filtre kuralları, görsel stili
    state.csv              paylaşılmış içerik geçmişi (eski CSV'den taşındı)
public/<proje>/       üretilen görseller buraya yazılır (GitHub'a push edilince
                        herkese açık URL kazanırlar)
scripts/run.py        komut satırı: generate / publish / dry-run
.github/workflows/pipeline.yml   zamanlanmış (her 30dk) GitHub Actions job'u
```

## Kurulum

### 1) GitHub reposu oluşturun

Bu klasörün tamamını yeni bir GitHub reposuna push edin (private repo önerilir
— erişim token'ları yine de repo içine yazılmaz, GitHub Secrets'ta kalır, ama
public repo'da RSS içerik geçmişiniz herkese görünür olur). Public repo
seçerseniz Actions dakikaları tamamen sınırsız/ücretsiz olur; private repoda
da ayda ~2000 dakika ücretsiz kota var ve bu iş için fazlasıyla yeterli.

```bash
cd ig-content-pipeline
git init
git add .
git commit -m "İlk kurulum: çoklu proje içerik pipeline'ı"
git branch -M main
git remote add origin https://github.com/<kullanici-adi>/<repo-adi>.git
git push -u origin main
```

### 2) GitHub Secrets ekleyin

Repo → Settings → Secrets and variables → Actions → "New repository secret":

| Secret adı | Değer |
|---|---|
| `GEMINI_API_KEY` | (önerilen — ücretsiz) [Google AI Studio](https://aistudio.google.com/apikey)'dan alın |
| `GROQ_API_KEY` | (alternatif — ücretsiz) [console.groq.com](https://console.groq.com/keys)'tan alın — `config.yaml`'da `llm.provider: groq` yaparsanız |
| `IG_ACCESS_TOKEN_ANKARA` | `instagram_api_config.json` içindeki `access_token` değeri |
| `IG_BUSINESS_ID_ANKARA` | `17841446264757964` |

Sadece Gemini VEYA Groq'tan birini doldurmanız yeterli (config.yaml'daki
`llm.provider` hangisiyse o okunur).

### 3) Kurulumu doğrulama (manuel tetikleme)

Repo → Actions sekmesi → "İçerik üretim ve Instagram yayın pipeline'ı" →
"Run workflow" ile elle bir kere çalıştırın. Loglardan hangi adımda
kaldığını görebilirsiniz (RSS'te aday bulunamadı / LLM uygun aday seçmedi /
görsel üretildi / Instagram'a yayınlandı). İlk çalıştırmada bir hata
alırsanız (özellikle 3. adımda, Instagram yayınlarken) en olası sebep
token'ın süresinin dolmuş olması — "Token yenileme" bölümüne bakın.

Otomatik zamanlama zaten workflow'da tanımlı (`*/30 * * * *` — her 30
dakikada bir dener, uygun taze haber yoksa hiçbir şey yapmadan sessizce
biter, maliyet çıkmaz).

## Yerel test (isteğe bağlı, gerçek yayın yapmadan)

```bash
cd ig-content-pipeline
# video üretimi için ffmpeg gerekiyor (bir kere kurulması yeterli):
#   Ubuntu/Debian: sudo apt install ffmpeg
#   macOS:         brew install ffmpeg
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # sonra .env içine en azından GEMINI_API_KEY'i doldurun
python scripts/run.py dry-run --project ankara
```

Bu, gerçek RSS'ten çekip gerçek LLM çağrısı yapar, görseli üretip
`public/ankara/` altına kaydeder ama **Instagram'a yayınlamaz**. Görseli açıp
kalite/tasarımı kontrol edebilirsiniz.

## Yeni bir proje ekleme (örn. "izmir")

1. `projects/_template/` klasörünü `projects/izmir/` olarak kopyalayın.
2. `projects/izmir/config.yaml` içini doldurun (RSS kaynakları, hashtag, görsel renkleri).
3. Boş bir `projects/izmir/state.csv` bırakın.
4. GitHub Secrets'a `IG_ACCESS_TOKEN_IZMIR` ve `IG_BUSINESS_ID_IZMIR` ekleyin
   (İzmir hesabı için Instagram Business hesabı + Meta App kurulumu Ankara
   projesindeki gibi gerekiyor — bkz. aşağıda "Yeni bir Instagram hesabı bağlama").
5. Başka bir şey yapmanıza gerek yok — `.github/workflows/pipeline.yml`
   `projects/` klasörünü otomatik tarar (`discover` job'u), yeni projeyi
   kendiliğinden bulup zamanlanmış çalıştırmaya dahil eder.

## Yeni bir Instagram hesabı bağlama (Ankara dışında bir hesap için)

Ankara hesabında bu adımlar zaten tamamlanmış görünüyor; yeni bir hesap
eklerken aynısını tekrarlamanız gerekecek:

1. Instagram hesabını **Business** hesaba çevirin ve bir Facebook Sayfası'na bağlayın.
2. [Meta for Developers](https://developers.facebook.com/apps) üzerinde yeni
   bir uygulama oluşturun, Instagram ürününü ekleyin.
3. Kendi hesabınızı uygulamaya "Instagram Tester/Admin" olarak ekleyin —
   uygulama Geliştirme (Development) modundayken KENDİ hesabınız için App
   Review beklemeden `instagram_business_content_publish` iznini
   kullanabilirsiniz (App Review sadece BAŞKA kullanıcıların hesaplarını
   bağlamak isterseniz gerekir).
4. Graph API Explorer üzerinden kısa ömürlü bir token alıp
   `scripts/refresh_ig_token.py` mantığıyla (fb_exchange_token) uzun ömürlü
   token'a çevirin.

## Token yenileme

Uzun ömürlü token'lar ~60 günde bir sona erer.

```bash
export META_APP_ID=1803628844096044
export META_APP_SECRET=...   # Meta App > Ayarlar > Temel bilgiler'den
export CURRENT_ACCESS_TOKEN=...   # şu anki token
python scripts/refresh_ig_token.py
```

Çıkan yeni token'ı ilgili GitHub Secret'a (`IG_ACCESS_TOKEN_ANKARA`) yapıştırın.
İsterseniz bu adımı da ayrı bir zamanlanmış GitHub Actions job'u ile
otomatikleştirebiliriz (60 günde bir hatırlatma) — şimdilik manuel.

## Görsel/video şablonu hakkında

Marka "6 Saniyede Ankara" olduğu için nihai tasarım **6 saniyelik animasyonlu
video** (Reels) — `projects/ankara/config.yaml` içinde `output_type: video`.
Animasyon: fotoğrafta yavaş bir yakınlaşma (Ken Burns), rozet ("Gündem" vb.)
sürekli hafif parlayıp sönüyor, başlık ve ortalanmış açıklama paneli açılışta
fade+slide ile geliyor. Kareler Pillow ile tek tek üretilip (`core/image_gen.py`
> `compose_layers()`) ffmpeg ile MP4'e kodlanıyor (`core/video_gen.py`) —
MoviePy gibi ek bir kütüphaneye gerek yok, sadece sistemde `ffmpeg` kurulu
olmalı (GitHub Actions runner'ında workflow bunu otomatik kuruyor; yerel
testte `apt install ffmpeg` / `brew install ffmpeg` gerekir).

Video yerine daha basit/hızlı statik görsel isteyen bir proje için
`config.yaml`'da `output_type: image` yapmak yeterli — sistem otomatik olarak
Instagram'a feed post olarak yayınlar (Reels yerine), video üretim/işleme
adımlarını tamamen atlar. Bu esneklik gelecekte eklenecek farklı hesaplar
için proje bazında seçilebilir.

Görsel/video stili `projects/<proje>/config.yaml` içindeki `image:`
bölümünden (renkler, oranlar, panel opaklığı) özelleştirilebilir. Animasyon
zamanlaması (fade süreleri, yakınlaşma miktarı, rozet parlama periyodu,
kelime kelime yazma hızı) `core/video_gen.py` başındaki sabitlerden
ayarlanabilir. Özet metni "klavyede yazılır gibi" kelime kelime beliriyor ve
video süresi buna göre (min 6, config'te ayarlanabilen bir tavana kadar)
otomatik uzuyor.

### Arka plan sesi

`projects/<proje>/sounds/` klasörüne .mp3 dosyaları koyarsanız, her video
üretiminde bunlardan RASTGELE biri arka plan sesi olarak eklenir (ardışık
haberlerin sesi birbirinin aynısı olmaz). Ses klip videodan kısaysa otomatik
döner, uzunsa videonun süresinde kesilip son yarım saniyede yumuşak biter.
Klasör boşsa video sessiz üretilir, hata vermez — bu yüzden sesler her
zaman opsiyonel.

## Bilinen sınırlamalar / sonraki adımlar

- LLM'in aday seçimi (gerçek haber mi / Ankara ile alakalı mı / tekrar mı)
  insan denetimi kadar kusursuz olmayabilir — ilk birkaç hafta çıktıları
  gözden geçirip `config.yaml > filters.extra_rules` üzerinden ince ayar
  yapmak faydalı olur.
- Görsel şablon şu an sade; Canva'daki animasyon/rozet arka plan görseli gibi
  ince detaylar birebir kopyalanmadı — `core/image_gen.py` içinde kolayca
  geliştirilebilir.
- Token yenileme şu an manuel — otomatikleştirmek istenirse ayrı bir
  zamanlanmış workflow eklenebilir.
