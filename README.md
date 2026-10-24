# py2apk

[Türkçe](README.tr.md)

Turn a Python script into a signed Android APK from a terminal UI. Windows, macOS and Linux, no Docker, no compiling on your machine, no tkinter.

```
pip install py2apk
py2apk
```

> **Status: alpha.** Console apps are verified on a real phone. The Web UI app type is new. Pygame and Kivy are still in beta development and cannot be used yet.

## How it works

1. **Factory** (`factory.py` + GitHub Actions) builds CPython and a large library set for Android once and publishes them as GitHub Release assets.
2. **Tool** (`py2apk`) downloads those prebuilt parts, scans your imports, embeds your code, icon and libraries, writes the manifest, then packages and signs the APK.

Only a JDK 17 and the Android build-tools are downloaded on your machine (if missing), into `~/.py2apk`.

## Install and run

```
pip install py2apk
py2apk                 # terminal UI
py2apk main.py         # terminal UI with a file preselected
py2apk build main.py --name "My App" --package com.me.app --mode webview   # no UI (CI, scripts)
```

**`py2apk` is not recognized?** On Windows, `pip install` often puts the launcher in a `Scripts` folder that is not on your PATH. Run `python -m py2apk` (or `py -m py2apk`) instead. py2apk also offers to add that folder to your PATH the first time it starts, or run `python -m py2apk --add-to-path` once and open a new terminal.

The UI is a terminal app (built with [Textual](https://textual.textualize.io/)), so it works in Windows Terminal, PowerShell, cmd, macOS Terminal, over SSH and in any Linux terminal. Optional: `pip install "py2apk[icon]"` resizes JPG/WebP logos.

## App types

| Type | Status | What it does |
|---|---|---|
| **Console** | working | `print()` output is shown on screen. No `input()`. |
| **Web UI** (Flask / FastAPI / NiceGUI + HTML) | supported, new | A local server runs on the phone and the UI is shown full screen in a WebView. |
| **Pygame / games** | beta (in development) | Needs an SDL2 runtime. Not selectable yet. |
| **Kivy** | beta (in development) | Needs an SDL2 runtime. Not selectable yet. |

Tkinter, Qt (PyQt/PySide) and wxPython do not run on Android with this runtime. Use the Web UI type for a graphical interface.

```python
import os
from flask import Flask

app = Flask(__name__)

@app.get("/")
def index():
    return "<h1>Hello, Android!</h1>"

app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
```

Keep `debug=False` (the reloader starts a second process, which Android does not allow). The port is chosen in the UI and passed to your code as `PORT`. If the server never starts, the app shows the Python error log instead of a blank page.

## Libraries

The factory targets **174 libraries** (plus their dependencies). Each is resolved from existing Android or pure-Python wheels (PyPI, Chaquopy index) and, where possible, built from source with cibuildwheel. What is actually available shows up next to each import in the UI (`ready` / `failed` / `will try pip`), and in `index.json` of the Release.

| Category | Count | Libraries |
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

Libraries that need a window system or heavy native chains (pygame, kivy, pyglet, arcade, raylib, panda3d, polars, streamlit, gradio, ...) are only picked up if a ready Android wheel exists. Otherwise they are listed as failed with the reason. Anything not in the list is tried with `pip` (pure-Python packages work; C extensions need an Android wheel).

## Limits

- Python 3.13 runtime, `arm64-v8a` (phones) and `x86_64` (emulator), Android 7.0+ (API 24).
- No `input()`, no SDL windowing yet (pygame, kivy).
- APKs are signed with a public debug key: fine for testing, not for Google Play.

## Run your own factory

Fork the repo, then **Settings -> Actions -> General -> Workflow permissions -> Read and write**, then **Actions -> factory -> Run workflow**. A release tagged `cp313` appears when it finishes. Point the tool at it:

```
export PY2APK_REPO=user/repo          # PowerShell: $env:PY2APK_REPO = "user/repo"
```

Other variables: `PY2APK_HOME` (cache folder, default `~/.py2apk`), `PY2APK_PY` (release tag). A Release can hold at most 1000 assets; the factory warns when it gets close.

## Troubleshooting

- **"Could not fetch library index":** the repo must be public and the factory must have finished once.
- **App crashes on start:** run `adb logcat -s pyapk` while opening it.
- **Native import error:** that package has no Android build yet; check its status in the UI.

## Publishing to PyPI (maintainers)

`.github/workflows/publish.yml` publishes with Trusted Publishing (no token) when you push a tag starting with `v`; the factory's `cp313` release does not trigger it. Register the publisher once on pypi.org (owner `TwoPlasmaStudios`, repository `py2apk`, workflow `publish.yml`, environment `pypi`), bump `version` in `pyproject.toml`, then `git tag v0.4.0 && git push origin v0.4.0`.

## License

See the `LICENSE` file. Libraries in the Release keep their own licenses; CPython is under the PSF license.
