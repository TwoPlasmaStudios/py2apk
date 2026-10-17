# py2apk

[English](README.md)

Python dosyanı bir Android APK'sına çevir. Docker yok, WSL yok, bilgisayarında derleme yok. Windows, macOS ve Linux'ta tek pencereden çalışır.

```
pip install py2apk
py2apk
```

> **Durum: alpha.** Konsol uygulaması gerçek telefonda denendi. Web arayüzü türü yeni, Pygame/Kivy henüz yok ve bazı ağır kütüphaneler (scipy, scikit-learn, opencv) henüz derlenemedi.

## Nasıl çalışır?

İki parça var, bu yüzden senin bilgisayarında hiçbir şey derlenmez:

1. **Fabrika** (`factory.py` + GitHub Actions) CPython'u ve popüler kütüphaneleri Android için bir kez derler, GitHub Release'e koyar.
2. **Araç** (`py2apk`) hazır parçaları indirir, importlarını tarar, kodunu ve gereken kütüphaneleri gömer, manifesti yazar, APK'yı paketleyip imzalar.

Bilgisayarına yalnızca JDK 17 ve Android build-tools inebilir (yoksa), `~/.py2apk` içinde tutulur.

## Kurulum

```
pip install py2apk
# ya da doğrudan GitHub'dan
pip install git+https://github.com/TwoPlasmaStudios/py2apk.git
```

Gereken: tkinter'lı Python 3.10+. Linux'ta: `sudo apt install python3-tk`. İsteğe bağlı: `pip install "py2apk[icon]"` (JPG/WebP logo ve net önizleme).

**`py2apk` komutu bulunamıyor mu?** Windows'ta `pip install` başlatıcıyı çoğu zaman PATH'te olmayan bir `Scripts` klasörüne koyar. Bunun yerine `python -m py2apk` (ya da `py -m py2apk`) çalıştır. Pencere ilk açıldığında py2apk bu klasörü PATH'e eklemeyi kendisi de önerir. Elle yapmak için bir kez `python -m py2apk --add-to-path` çalıştırıp yeni bir terminal aç.

## Kullanım

1. `py2apk` komutuyla pencereyi aç.
2. **Python dosyası**nı seç. Ad, paket adı ve kütüphaneler otomatik algılanır.
3. İstersen logo seç, **uygulama türünü** seç.
4. **APK OLUŞTUR**'a bas. İlk seferde araçlar iner (birkaç yüz MB), sonrası hızlıdır. APK dosyanın yanında oluşur.
5. Telefona `adb install uygulama.apk` ile ya da dosyayı kopyalayıp açarak kur (bilinmeyen kaynaklara izin ver).

Giriş dosyasının yanındaki `.py` dosyaları ve paketler APK'ya otomatik girer; her uygulamayı kendi klasöründe tut.

## Uygulama türleri

| Tür | Durum | Ne yapar |
|---|---|---|
| **Konsol** | çalışıyor | `print()` çıktısı ekranda görünür. `input()` yok. |
| **Web arayüzü** | çalışıyor | Flask/FastAPI sunucusu telefonda açılır, arayüz tam ekran WebView'da görünür. |
| **Pygame / Oyun** | beta (geliştiriliyor) | SDL2 altyapısı gerekir, henüz seçilemez. |
| **Kivy** | beta (geliştiriliyor) | SDL2 altyapısı gerekir, henüz seçilemez. |

Android'de tkinter yoktur. Grafik arayüz için **Web arayüzü** türünü kullan.

```python
import os
from flask import Flask

app = Flask(__name__)

@app.get("/")
def index():
    return "<h1>Merhaba Android!</h1>"

app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
```

`debug=False` olmalı (reloader ikinci süreç açar, Android izin vermez). Port arayüzden verilir ve kodna `PORT` olarak geçer. Sunucu açılamazsa boş sayfa yerine Python hata çıktısı görünür.

## Kütüphaneler

Fabrika, `factory.py` içindeki `LIBS` listesi ve bağımlılıkları için Android wheel'leri üretir. Saf Python paketler olduğu gibi çalışır, C eklentileri yalnızca Android sürümü varsa çalışır. Hangilerinin hazır olduğunu arayüzdeki durum sütunundan ya da Release'teki `index.json`'dan görürsün. Listede olmayanlar `pip` ile aranır, bulunamazsa günlükte uyarı çıkar.

## Kendi fabrikanı çalıştır

Depoyu fork'la, Actions'ı aç, **Settings → Actions → General → Workflow permissions → Read and write** yap, sonra **Actions → factory → Run workflow**. Bitince `cp313` etiketli bir release oluşur. Aracı ona yönelt:

```
$env:PY2APK_REPO = "kullanici/depo"     # PowerShell
export PY2APK_REPO=kullanici/depo       # macOS / Linux
```

Ya da arayüzde *Gelişmiş → GitHub deposu* alanına yaz. Diğer değişkenler: `PY2APK_HOME` (önbellek klasörü), `PY2APK_PY` (release etiketi).

## Sorun giderme

- **"Kütüphane dizini alınamadı":** depo public olmalı ve fabrika en az bir kez bitmiş olmalı.
- **`py2apk` komutu tanınmıyor:** `python -m py2apk` çalıştır (yukarıdaki nota bak).
- **Uygulama çöküyor:** açarken `adb logcat -s pyapk` çalıştır.
- **Native kütüphane import hatası:** o paketin henüz Android sürümü yok, arayüzde durumuna bak.

## Sınırlar

Python 3.13 runtime, yalnızca arm64-v8a ve x86_64, en düşük Android 7.0 (API 24). Pygame ve Kivy hâlâ beta geliştirme aşamasında ve henüz kullanılamaz; tkinter Android'de yoktur. APK herkese açık debug anahtarıyla imzalanır: test için uygun, Google Play için değil.

## Lisans

MIT. Release'teki kütüphaneler kendi lisanslarıyla dağıtılır, CPython PSF lisansındadır.
