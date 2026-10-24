# py2apk

[English](README.md)

Python dosyanı terminal arayüzünden imzalı bir Android APK'sına çevir. Windows, macOS ve Linux'ta çalışır. Docker yok, bilgisayarında derleme yok, tkinter yok.

```
pip install py2apk
py2apk
```

> **Durum: alpha.** Konsol uygulaması gerçek telefonda denendi. Web arayüzü türü yeni. Pygame ve Kivy hâlâ beta geliştirme aşamasında, henüz kullanılamaz.

## Nasıl çalışır?

1. **Fabrika** (`factory.py` + GitHub Actions) CPython'u ve geniş bir kütüphane kümesini Android için bir kez derler, GitHub Release'e koyar.
2. **Araç** (`py2apk`) hazır parçaları indirir, importlarını tarar, kodunu, logonu ve kütüphaneleri gömer, manifesti yazar, APK'yı paketleyip imzalar.

Bilgisayarına yalnızca JDK 17 ve Android build-tools inebilir (yoksa), `~/.py2apk` içinde tutulur.

## Kurulum ve çalıştırma

```
pip install py2apk
py2apk                 # terminal arayüzü
py2apk main.py         # dosya seçili açılır
py2apk build main.py --name "Uygulamam" --package com.ben.uyg --mode webview   # arayüzsüz (CI, betik)
```

**`py2apk` komutu bulunamıyor mu?** Windows'ta `pip install` başlatıcıyı çoğu zaman PATH'te olmayan bir `Scripts` klasörüne koyar. Bunun yerine `python -m py2apk` (ya da `py -m py2apk`) çalıştır. py2apk ilk açılışta bu klasörü PATH'e eklemeyi kendisi de önerir. Elle yapmak için bir kez `python -m py2apk --add-to-path` çalıştırıp yeni bir terminal aç.

Arayüz bir terminal uygulamasıdır ([Textual](https://textual.textualize.io/) ile), bu yüzden Windows Terminal, PowerShell, cmd, macOS Terminal, SSH ve her Linux terminalinde çalışır. İsteğe bağlı: `pip install "py2apk[icon]"` (JPG/WebP logoları küçültür).

## Uygulama türleri

| Tür | Durum | Ne yapar |
|---|---|---|
| **Konsol** | çalışıyor | `print()` çıktısı ekranda görünür. `input()` yok. |
| **Web arayüzü** (Flask / FastAPI / NiceGUI + HTML) | destekleniyor, yeni | Telefonda yerel sunucu açılır, arayüz tam ekran WebView'da görünür. |
| **Pygame / Oyun** | beta (geliştiriliyor) | SDL2 altyapısı gerekir, henüz seçilemez. |
| **Kivy** | beta (geliştiriliyor) | SDL2 altyapısı gerekir, henüz seçilemez. |

Tkinter, Qt (PyQt/PySide) ve wxPython bu çalışma zamanıyla Android'de çalışmaz. Grafik arayüz için **Web arayüzü** türünü kullan.

```python
import os
from flask import Flask

app = Flask(__name__)

@app.get("/")
def index():
    return "<h1>Merhaba Android!</h1>"

app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
```

`debug=False` olmalı (reloader ikinci süreç açar, Android izin vermez). Port arayüzden seçilir ve kodna `PORT` olarak geçer. Sunucu açılamazsa boş sayfa yerine Python hata günlüğü görünür.

## Kütüphaneler

Fabrika **174 kütüphaneyi** (ve bağımlılıklarını) hedefler. Her biri hazır Android veya saf Python wheel'lerden (PyPI, Chaquopy dizini) çözülür, mümkünse cibuildwheel ile kaynaktan derlenir. Gerçekte hangilerinin hazır olduğu arayüzde her importun yanında (`hazır` / `başarısız` / `pip denenecek`) ve Release'teki `index.json` dosyasında görünür.

| Kategori | Adet | Kütüphaneler |
|---|---|---|
| Web / sunucu | 30 | flask, django, fastapi, starlette, uvicorn, bottle, quart, tornado, aiohttp, falcon, cherrypy, waitress, werkzeug, jinja2, requests, httpx, websockets, python-socketio, flask-socketio, flask-cors, flask-sqlalchemy, flask-login, flask-wtf, nicegui, dash, pywebio, remi, streamlit, gradio, websocket-client |
| GUI / oyun | 16 | pygame, pygame-ce, kivy, kivymd, pyglet, arcade, pysdl2, pymunk, pygame-gui, pgzero, raylib, moderngl, pyopengl, panda3d, ursina, flet |
| Minecraft / bot / sosyal | 11 | minecraft-launcher-lib, mcstatus, nbtlib, mcrcon, discord.py, python-telegram-bot, aiogram, pytelegrambotapi, slack-sdk, tweepy, praw |
| Ağ / donanım | 10 | paho-mqtt, dnspython, paramiko, pysocks, aiofiles, httpcore, pyserial, scapy, zeroconf, ping3 |
| Veri / bilim / görüntü | 20 | numpy, pandas, scipy, scikit-learn, matplotlib, seaborn, plotly, sympy, networkx, statsmodels, scikit-image, bokeh, openpyxl, xlsxwriter, xlrd, polars, tabulate, pillow, opencv-python-headless, imageio |
| Metin / ayrıştırma | 31 | beautifulsoup4, lxml, html5lib, pyyaml, tomlkit, python-dotenv, jsonschema, markdown, mistune, pygments, docutils, rich, tqdm, colorama, click, typer, loguru, pyfiglet, prompt-toolkit, regex, python-dateutil, pytz, tzdata, arrow, babel, unidecode, emoji, jmespath, xmltodict, feedparser, markdownify |
| Veritabanı | 8 | sqlalchemy, alembic, peewee, tinydb, pymongo, redis, aiosqlite, sqlmodel |
| Güvenlik | 11 | cryptography, pycryptodome, bcrypt, pynacl, pyjwt, passlib, argon2-cffi, pyotp, itsdangerous, oauthlib, authlib |
| Yardımcı | 23 | attrs, pydantic, marshmallow, orjson, ujson, msgpack, cachetools, tenacity, more-itertools, toolz, schedule, apscheduler, psutil, python-slugify, shortuuid, qrcode, faker, humanize, pint, filelock, platformdirs, packaging, six |
| Belge / medya | 7 | reportlab, fpdf2, pypdf, python-docx, python-pptx, mutagen, gtts |
| Yapay zeka | 6 | openai, anthropic, ollama, huggingface-hub, tokenizers, google-generativeai |

Pencere sistemi ya da ağır yerel zincir gerektirenler (pygame, kivy, pyglet, arcade, raylib, panda3d, polars, streamlit, gradio, ...) yalnızca hazır bir Android wheel varsa alınır. Yoksa nedeniyle birlikte "başarısız" yazılır. Listede olmayan paketler `pip` ile denenir (saf Python paketler çalışır, C eklentileri için Android wheel gerekir).

## Sınırlar

- Python 3.13 runtime, `arm64-v8a` (telefon) ve `x86_64` (emülatör), Android 7.0+ (API 24).
- `input()` yok, SDL pencere desteği henüz yok (pygame, kivy).
- APK herkese açık bir debug anahtarıyla imzalanır: test için uygun, Google Play için değil.

## Kendi fabrikanı çalıştır

Depoyu fork'la, **Settings → Actions → General → Workflow permissions → Read and write** yap, sonra **Actions → factory → Run workflow**. Bitince `cp313` etiketli bir release oluşur. Aracı ona yönelt:

```
export PY2APK_REPO=kullanici/depo      # PowerShell: $env:PY2APK_REPO = "kullanici/depo"
```

Diğer değişkenler: `PY2APK_HOME` (önbellek klasörü, varsayılan `~/.py2apk`), `PY2APK_PY` (release etiketi). Bir release en fazla 1000 dosya tutar; sınıra yaklaşınca fabrika uyarır.

## Sorun giderme

- **"Kütüphane dizini alınamadı":** depo public olmalı ve fabrika en az bir kez bitmiş olmalı.
- **Uygulama açılışta çöküyor:** açarken `adb logcat -s pyapk` çalıştır.
- **Native import hatası:** o paketin henüz Android sürümü yok, arayüzde durumuna bak.

## PyPI'a yayın (bakımcılar)

`.github/workflows/publish.yml`, `v` ile başlayan bir etiket gönderince Trusted Publishing ile (token'sız) yayınlar; fabrikanın `cp313` release'i bunu tetiklemez. Publisher'ı pypi.org'da bir kez kaydet (owner `TwoPlasmaStudios`, repository `py2apk`, workflow `publish.yml`, environment `pypi`), `pyproject.toml`'da `version`'ı artır, sonra `git tag v0.4.0 && git push origin v0.4.0`.

## Lisans

`LICENSE` dosyasına bak. Release'teki kütüphaneler kendi lisanslarıyla dağıtılır, CPython PSF lisansındadır.
