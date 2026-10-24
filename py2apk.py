#!/usr/bin/env python3
"""py2apk - Terminal arayüzü (TUI) ile Python -> APK (Windows / macOS / Linux).

Kullanıcı tarafında DERLEME YOK: CPython runtime'ı ve kütüphane wheel'leri
GitHub Releases'e önceden derlenip konmuştur (bkz. factory.py). Bu araç yalnızca
eksik araçları (JDK, Android build-tools) indirir, hazır parçaları çeker ve APK'yı paketler.

    pip install py2apk
    py2apk                      # TUI
    py2apk build main.py ...    # arayüzsüz (CI/otomasyon)
"""
from __future__ import annotations

import ast, json, os, platform, re, shutil, struct, subprocess, sys, tarfile
import threading, traceback, urllib.parse, urllib.request, zipfile, zlib
from pathlib import Path
from xml.sax.saxutils import quoteattr

_old, _new = Path.home() / ".pyapk", Path.home() / ".py2apk"   # eski önbelleği (JDK/SDK) yeniden indirme
HOME = Path(os.environ.get("PY2APK_HOME") or (_old if _old.exists() and not _new.exists() else _new))
REPO = os.environ.get("PY2APK_REPO") or os.environ.get("PYAPK_REPO") or "TwoPlasmaStudios/py2apk"
PY_TAG = os.environ.get("PY2APK_PY", "cp313")              # release etiketi
ABIS = ("arm64-v8a", "x86_64")
BT_VER, PLATFORM, TARGET_SDK, MIN_SDK = "34.0.0", "android-34", 34, 24
CMDLINE = "https://dl.google.com/android/repository/commandlinetools-{os}-11076708_latest.zip"
SYS = platform.system()
WIN = SYS == "Windows"
ARCH = "aarch64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
EXE, BAT = (".exe", ".bat") if WIN else ("", "")

PIPMAP = {  # import adı -> PyPI adı (yalnızca farklı olanlar; '_' ve '-' farkı otomatik çözülür)
    "PIL": "pillow", "cv2": "opencv-python-headless", "yaml": "pyyaml", "bs4": "beautifulsoup4",
    "sklearn": "scikit-learn", "dateutil": "python-dateutil", "dotenv": "python-dotenv",
    "OpenSSL": "pyopenssl", "Crypto": "pycryptodome", "Cryptodome": "pycryptodomex", "serial": "pyserial",
    "jwt": "pyjwt", "attr": "attrs", "skimage": "scikit-image", "git": "gitpython", "magic": "python-magic",
    "socks": "pysocks", "telegram": "python-telegram-bot", "discord": "discord.py", "docx": "python-docx",
    "pptx": "python-pptx", "nacl": "pynacl", "argon2": "argon2-cffi", "slugify": "python-slugify",
    "socketio": "python-socketio", "paho": "paho-mqtt", "websocket": "websocket-client",
    "telebot": "pytelegrambotapi", "sdl2": "pysdl2", "OpenGL": "pyopengl", "fitz": "pymupdf",
    "jose": "python-jose", "zmq": "pyzmq", "yarl": "yarl", "markdown2": "markdown2", "ollama": "ollama"}
UNSUPPORTED = {
    "tkinter": "Android'de Tk yok (Web arayüzü türünü kullanın)",
    "customtkinter": "Android'de Tk yok (Web arayüzü türünü kullanın)",
    "PyQt5": "Qt bu çalışma zamanıyla Android'de çalışmaz", "PyQt6": "Qt bu çalışma zamanıyla Android'de çalışmaz",
    "PySide2": "Qt bu çalışma zamanıyla Android'de çalışmaz", "PySide6": "Qt bu çalışma zamanıyla Android'de çalışmaz",
    "wx": "wxPython Android'de çalışmaz",
    "pygame": "pygame için SDL altyapısı beta aşamasında, henüz yok",
    "kivy": "kivy için SDL altyapısı beta aşamasında, henüz yok",
    "pyglet": "pyglet için pencere/OpenGL altyapısı henüz yok", "arcade": "arcade için pencere altyapısı henüz yok",
    "sdl2": "SDL2 altyapısı henüz yok", "panda3d": "panda3d için pencere altyapısı henüz yok"}
WEB_LIBS = {"flask", "fastapi", "bottle", "django", "quart", "starlette", "uvicorn", "waitress", "tornado",
            "falcon", "cherrypy", "nicegui", "dash", "pywebio", "remi", "streamlit", "gradio", "sanic"}
MODES = [  # (anahtar, başlık, açıklama, destekleniyor)
    ("console", "Konsol", "print() çıktısı ekranda görünür. Betikler, botlar, hesaplamalar.", True),
    ("webview", "Web arayüzü", "Flask / FastAPI / NiceGUI + HTML. Uygulama yerel sunucu açar, arayüz WebView'da görünür.", True),
    ("pygame", "Pygame / Oyun", "SDL2 altyapısı beta aşamasında, henüz seçilemez.", False),
    ("kivy", "Kivy", "SDL2 altyapısı beta aşamasında, henüz seçilemez.", False),
]


# --------------------------------------------------------------------------- günlük / hata
class Fail(Exception):
    pass


_log = print
def set_log(fn): global _log; _log = fn
def log(m): _log(m)
def die(m): raise Fail(m)
def norm(n): return re.sub(r"[-_.]+", "-", n).lower()


def run(cmd, input=None, **kw):
    cmd = [str(c) for c in cmd]
    log("$ " + " ".join(cmd)[:200])
    if WIN:
        kw["creationflags"] = 0x08000000  # konsol penceresi açma
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE if input else None, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, errors="replace", **kw)
    if input:
        p.stdin.write(input); p.stdin.close()
    for line in p.stdout:
        log(line.rstrip())
    if p.wait():
        die(f"komut başarısız ({p.returncode}): {Path(cmd[0]).name}")


def download(url, dest):
    dest = Path(dest)
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"indiriliyor: {url}")
    tmp = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "py2apk"}), timeout=60) as r, \
                open(tmp, "wb") as f:
            total, got, mark = int(r.headers.get("Content-Length") or 0), 0, 0
            while chunk := r.read(1 << 20):
                f.write(chunk); got += len(chunk)
                if total and got - mark >= (16 << 20):
                    mark = got; log(f"  {got >> 20}/{total >> 20} MB")
    except Exception as e:
        tmp.unlink(missing_ok=True); die(f"indirilemedi: {url} ({e})")
    tmp.rename(dest)
    return dest


def extract(archive, dest):
    dest = Path(dest); dest.mkdir(parents=True, exist_ok=True)
    if str(archive).endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for i in z.infolist():
                z.extract(i, dest)
                mode = (i.external_attr >> 16) & 0o7777
                if mode and not WIN:
                    os.chmod(dest / i.filename, mode)
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest, filter="tar") if hasattr(tarfile, "data_filter") else t.extractall(dest)


def jenv(jdk):
    e = dict(os.environ)
    e["JAVA_HOME"] = str(jdk)
    e["PATH"] = str(Path(jdk) / "bin") + os.pathsep + e.get("PATH", "")
    return e


# --------------------------------------------------------------------------- araç kurulumu (yalnızca eksikse)
def ensure_jdk() -> Path:
    def major(javac):
        try:
            p = subprocess.run([str(javac), "-version"], capture_output=True, text=True)
            return int(re.search(r"(\d+)", p.stdout + p.stderr).group(1))
        except Exception:
            return 0
    cands = []
    if os.environ.get("JAVA_HOME"):
        cands.append(Path(os.environ["JAVA_HOME"]) / "bin" / f"javac{EXE}")
    if shutil.which("javac"):
        cands.append(Path(shutil.which("javac")).resolve())
    for c in cands:
        if c.exists() and major(c) >= 17:
            return c.parent.parent
    d = HOME / "jdk"
    found = list(d.glob(f"**/bin/javac{EXE}"))
    if not found:
        osn = {"Windows": "windows", "Darwin": "mac"}.get(SYS, "linux")
        a = "aarch64" if ARCH == "aarch64" else "x64"
        ext = "zip" if WIN else "tar.gz"
        f = download(f"https://api.adoptium.net/v3/binary/latest/17/ga/{osn}/{a}/jdk/hotspot/normal/eclipse",
                     HOME / "dl" / f"jdk17-{osn}-{a}.{ext}")
        extract(f, d)
        found = list(d.glob(f"**/bin/javac{EXE}"))
    return found[0].parent.parent


def ensure_sdk(jdk) -> Path:
    sdk = HOME / "sdk"
    sm = sdk / "cmdline-tools" / "latest" / "bin" / f"sdkmanager{BAT}"
    if not sm.exists():
        osn = {"Windows": "win", "Darwin": "mac"}.get(SYS, "linux")
        z = download(CMDLINE.format(os=osn), HOME / "dl" / f"cmdline-tools-{osn}.zip")
        tmp = HOME / "tmp_cmd"; shutil.rmtree(tmp, ignore_errors=True); extract(z, tmp)
        (sdk / "cmdline-tools").mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp / "cmdline-tools"), str(sm.parent.parent))
    want = []
    if not (sdk / "build-tools" / BT_VER / f"aapt2{EXE}").exists(): want.append(f"build-tools;{BT_VER}")
    if not (sdk / "platforms" / PLATFORM / "android.jar").exists(): want.append(f"platforms;{PLATFORM}")
    if want:
        log("Android SDK lisansları otomatik kabul ediliyor: https://developer.android.com/studio/terms")
        run([sm, f"--sdk_root={sdk}", *want], input="y\n" * 60, env=jenv(jdk))
    return sdk


# --------------------------------------------------------------------------- hazır parçalar (GitHub Releases)
def asset_url(repo, tag, name):
    return f"https://github.com/{repo}/releases/download/{tag}/{urllib.parse.quote(name)}"


def fetch_index(repo):
    try:
        with urllib.request.urlopen(asset_url(repo, PY_TAG, "index.json"), timeout=30) as r:
            return json.load(r)
    except Exception as e:
        die(f"Kütüphane dizini alınamadı ({repo}, etiket {PY_TAG}): {e}\n"
            "GitHub deposunda 'factory' iş akışının çalışıp release oluşturduğundan emin olun.")


def lib_status(idx, lib):
    if idx is None:
        return "…"
    e = idx["libs"].get(lib)
    if e:
        return "✓ hazır (derlenmiş)" if e["native"] else "✓ hazır (saf Python)"
    if lib in idx.get("failed", {}):
        return "✗ " + idx["failed"][lib][:60]
    return "dizinde yok → pip denenecek"


# --------------------------------------------------------------------------- uygulama içeriği
def collect(main: Path, extra=()):
    items = []
    for p in sorted(main.parent.iterdir()):
        if p.name.startswith((".", "_pyapk")):
            continue
        if p.is_file() and p.suffix == ".py":
            items.append(p)
        elif p.is_dir() and (p / "__init__.py").exists() and p.name not in {"venv", "env", "build", "dist"}:
            items.append(p)
    return items + [Path(e).resolve() for e in extra]


def detect_libs(items):
    local = {p.stem if p.is_file() else p.name for p in items}
    found = set()
    for p in items:
        for f in ([p] if p.is_file() else p.rglob("*.py")):
            try:
                tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, OSError):
                continue
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    found |= {a.name.split(".")[0] for a in n.names}
                elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                    found.add(n.module.split(".")[0])
    for m, why in UNSUPPORTED.items():
        if m in found:
            log(f"UYARI: '{m}' kullanılıyor ama {why}")
    return sorted({norm(PIPMAP.get(m, m)) for m in found - set(sys.stdlib_module_names) - local})


def pip_fallback(libs, site, abi, py):
    cmd = [sys.executable, "-m", "pip", "install", "--target", site, "--only-binary=:all:", "--no-compile",
           "--disable-pip-version-check", "--implementation", "cp", "--python-version", py,
           "--abi", "cp" + py.replace(".", "")]
    api_tag = abi.replace("-", "_")
    for api in range(21, MIN_SDK + 1):
        cmd += ["--platform", f"android_{api}_{api_tag}"]
    for lib in libs:  # tek tek: biri olmazsa diğerleri yine gelsin
        try:
            run(cmd + [lib])
        except Fail:
            log(f"UYARI: '{lib}' için Android/saf-Python wheel bulunamadı, atlandı")


def make_icon(icon, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if icon:
        try:
            from PIL import Image
            Image.open(icon).convert("RGBA").resize((192, 192)).save(dest); return
        except ImportError:
            if Path(icon).suffix.lower() != ".png":
                die("PNG olmayan logo için Pillow gerekir: pip install pillow")
            shutil.copy(icon, dest); return
    n = 192
    raw = (b"\x00" + bytes([0x30, 0x6E, 0xB8, 255]) * n) * n
    ch = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    dest.write_bytes(b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0))
                     + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b""))


def manifest_xml(pkg, name, vname, vcode, mode="console", port=5000):
    return f'''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package={quoteattr(pkg)}
    android:versionCode="{vcode}" android:versionName={quoteattr(vname)}>
  <uses-permission android:name="android.permission.INTERNET"/>
  <application android:label={quoteattr(name)} android:icon="@mipmap/ic_launcher" android:allowBackup="false"
      android:extractNativeLibs="true" android:usesCleartextTraffic="true"
      android:theme="@android:style/Theme.Material.Light.NoActionBar">
    <meta-data android:name="py2apk.mode" android:value={quoteattr(mode)}/>
    <meta-data android:name="py2apk.port" android:value={quoteattr(str(port))}/>
    <activity android:name="pyapk.runtime.MainActivity" android:exported="true"
        android:configChanges="orientation|screenSize|keyboardHidden|screenLayout|smallestScreenSize|uiMode">
      <intent-filter>
        <action android:name="android.intent.action.MAIN"/>
        <category android:name="android.intent.category.LAUNCHER"/>
      </intent-filter>
    </activity>
  </application>
</manifest>
'''


BOOT_PY = r'''import sys, os, runpy, traceback
sys.stdout = open(1, "w", buffering=1, encoding="utf-8", errors="replace", closefd=False)
sys.stderr = open(2, "w", buffering=1, encoding="utf-8", errors="replace", closefd=False)
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except Exception:
    pass
os.environ["PORT"] = "@PORT@"
_main = os.path.join(os.path.dirname(os.path.abspath(__file__)), @MAIN@)
sys.argv = [_main]
try:
    runpy.run_path(_main, run_name="__main__")
except SystemExit:
    pass
except BaseException:
    traceback.print_exc()
print("\n[program sona erdi]")
'''


# --------------------------------------------------------------------------- APK üretimi
def build_apk(c) -> Path:
    """c: script, name, package, icon, version, vcode, abis, libs(list), repo, add(list)"""
    if c.get("mode", "console") not in ("console", "webview"):
        die("Bu uygulama türü henüz desteklenmiyor")
    idx = fetch_index(c["repo"])
    py, tag, bid = idx["py"], idx["tag"], idx["build"]
    for abi in c["abis"]:
        if abi not in idx["abis"]:
            die(f"Release'te {abi} runtime'ı yok")
    src = Path(c["script"]).resolve()
    items = collect(src, c.get("add", []))
    libs = list(dict.fromkeys([*c["libs"], "certifi"]))
    log(f"uygulama: {c['name']} ({c['package']})  ABI: {c['abis']}  kütüphaneler: {libs}")

    jdk = ensure_jdk(); sdk = ensure_sdk(jdk); je = jenv(jdk)
    bt, android_jar = sdk / "build-tools" / BT_VER, sdk / "platforms" / PLATFORM / "android.jar"
    work = HOME / "work" / c["package"]; shutil.rmtree(work, ignore_errors=True); work.mkdir(parents=True)

    make_icon(c.get("icon"), work / "res" / "mipmap-xxxhdpi" / "ic_launcher.png")
    (work / "AndroidManifest.xml").write_text(manifest_xml(c["package"], c["name"], c["version"], c["vcode"],
                                                          c.get("mode", "console"), c.get("port", 5000)),
                                              encoding="utf-8")
    run([bt / f"aapt2{EXE}", "compile", "--dir", work / "res", "-o", work / "res.zip"])
    base = work / "base.apk"
    run([bt / f"aapt2{EXE}", "link", "-o", base, "-I", android_jar, "--manifest", work / "AndroidManifest.xml",
         "--min-sdk-version", MIN_SDK, "--target-sdk-version", TARGET_SDK, "--version-code", c["vcode"],
         "--version-name", c["version"], work / "res.zip"])

    dl = HOME / "dl" / bid
    dex = download(asset_url(c["repo"], tag, f"classes-{tag}.dex"), dl / "classes.dex")
    parts = {}
    for abi in c["abis"]:
        rt = HOME / "runtime" / bid / abi
        if not rt.exists():
            extract(download(asset_url(c["repo"], tag, f"runtime-{tag}-{abi}.zip"), dl / f"runtime-{abi}.zip"), rt)
        root = work / f"home-{abi}"
        shutil.copytree(rt / "home", root)
        site = root / "lib" / f"python{py}" / "site-packages"; site.mkdir(parents=True, exist_ok=True)
        missing, done = [], set()
        for lib in libs:
            ent = idx["libs"].get(lib)
            if not ent or abi not in ent["files"]:
                missing.append(lib); continue
            for fn in ent["files"][abi]:
                if fn not in done:
                    done.add(fn)
                    with zipfile.ZipFile(download(asset_url(c["repo"], tag, fn), dl / fn)) as z:
                        z.extractall(site)
        if missing:
            log(f"dizinde olmayanlar pip ile deneniyor: {missing}")
            pip_fallback(missing, site, abi, py)
        app = root / "app"; app.mkdir()
        for it in items:
            if it.is_dir():
                shutil.copytree(it, app / it.name, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(it, app / it.name)
        boot = BOOT_PY.replace("@MAIN@", repr(src.name)).replace("@PORT@", str(c.get("port", 5000)))
        (app / "_pyapk_boot.py").write_text(boot, encoding="utf-8")
        z = work / f"pyhome-{abi}.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    zf.write(p, p.relative_to(root).as_posix())
        parts[abi] = (sorted((rt / "libs").glob("*.so")), z)

    with zipfile.ZipFile(base, "a") as z:
        z.write(dex, "classes.dex", zipfile.ZIP_DEFLATED)
        for abi, (sos, home_zip) in parts.items():
            for so in sos:
                z.write(so, f"lib/{abi}/{so.name}", zipfile.ZIP_STORED)
            z.write(home_zip, f"assets/pyhome-{abi}.zip", zipfile.ZIP_STORED)

    ks = HOME / "debug.keystore"
    if not ks.exists():
        run([jdk / "bin" / f"keytool{EXE}", "-genkeypair", "-keystore", ks, "-storepass", "android",
             "-keypass", "android", "-alias", "pyapk", "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
             "-dname", "CN=py2apk"])
    aligned = work / "aligned.apk"
    run([bt / f"zipalign{EXE}", "-f", "-p", "4", base, aligned])
    out = Path(c.get("out") or src.parent / f"{re.sub(r'[^A-Za-z0-9_-]', '_', c['name'])}-{c['version']}.apk")
    run([bt / f"apksigner{BAT}", "sign", "--ks", ks, "--ks-pass", "pass:android", "--key-pass", "pass:android",
         "--out", out, aligned], env=je)
    log(f"HAZIR: {out}  ({out.stat().st_size >> 20} MB)")
    return out



# --------------------------------------------------------------------------- komut PATH'te değilse otomatik düzelt
def scripts_dir():
    """pip'in py2apk başlatıcısını koyduğu klasör (yoksa None)."""
    try:
        from importlib import metadata
        for f in metadata.distribution("py2apk").files or []:
            if f.name in ("py2apk.exe", "py2apk"):
                p = Path(f.locate()).resolve().parent
                if p.exists():
                    return p
    except Exception:
        pass
    return None


def add_to_path(d):
    """Kullanıcı PATH'ine ekler. Dönüş: (başarılı_mı, mesaj). Yalnızca Windows'ta kayıt defterini değiştirir."""
    d = str(d)
    if not WIN:
        return False, f'Şu satırı kabuk ayar dosyana (~/.profile veya ~/.zshrc) ekle:\n  export PATH="{d}:$PATH"'
    try:
        import ctypes, winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as k:
            try:
                cur, typ = winreg.QueryValueEx(k, "Path")
            except FileNotFoundError:
                cur, typ = "", winreg.REG_EXPAND_SZ
            parts = [p for p in cur.split(";") if p]
            if d.lower().rstrip("\\") not in [p.lower().rstrip("\\") for p in parts]:
                parts.append(d)
                winreg.SetValueEx(k, "Path", 0, typ, ";".join(parts))
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 2, 5000, None)
        return True, f"Eklendi: {d}\nYeni bir terminal açınca 'py2apk' komutu çalışır."
    except Exception as e:
        return False, f"PATH güncellenemedi: {e}"

# --------------------------------------------------------------------------- arayüzsüz (CLI) derleme
def open_folder(p):
    if WIN:
        os.startfile(p)  # noqa
    else:
        subprocess.run(["open" if SYS == "Darwin" else "xdg-open", str(p)])


def build_cli(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="py2apk build", description="Arayüzsüz APK derleme (CI / otomasyon).")
    ap.add_argument("script", help="giriş .py dosyası")
    ap.add_argument("--name"); ap.add_argument("--package"); ap.add_argument("--icon")
    ap.add_argument("--version", default="1.0")
    ap.add_argument("--abi", default="arm64-v8a", help="virgüllü: arm64-v8a,x86_64")
    ap.add_argument("--mode", choices=["console", "webview"], help="verilmezse web çatısı algılanırsa webview")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--pip", action="append", default=[], help="ek paket (tekrarlanabilir)")
    ap.add_argument("--repo", default=REPO); ap.add_argument("--out")
    a = ap.parse_args(argv)
    set_log(print)
    src = Path(a.script).resolve()
    if not src.is_file():
        sys.exit(f"dosya yok: {src}")
    detected = detect_libs(collect(src))
    stem = re.sub(r"[^a-z0-9_]", "_", src.stem.lower()) or "app"
    cfg = dict(script=str(src), name=a.name or src.stem.replace("_", " ").title(),
               package=a.package or f"com.py2apk.{stem}", icon=a.icon, version=a.version, vcode=1,
               abis=[x.strip() for x in a.abi.split(",")], libs=list(dict.fromkeys([*detected, *map(norm, a.pip)])),
               repo=a.repo, mode=a.mode or ("webview" if WEB_LIBS & set(detected) else "console"),
               port=a.port, out=a.out)
    if not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", cfg["package"]):
        sys.exit("Geçersiz paket adı (örn. com.ben.uygulama)")
    try:
        print(build_apk(cfg))
    except Fail as e:
        sys.exit(f"HATA: {e}")


# --------------------------------------------------------------------------- TUI (Textual) - her terminalde çalışır
WEB_HINT = ('import os\napp.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)\n'
            '# NiceGUI: ui.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), show=False, reload=False)')

TUI_CSS = """
#body { height: 1fr; }
#left { width: 1fr; padding: 0 1; }
#right { width: 1fr; padding: 0 1; }
.card { border: round $primary; padding: 0 1; margin-bottom: 1; height: auto; }
.row { height: auto; }
.row Label { width: 14; height: 3; content-align: left middle; }
.row Input { width: 1fr; }
.row Button { width: 12; }
#libs { height: 11; margin-bottom: 1; }
#log { height: 1fr; border: round $primary; }
#webhint { color: $text-muted; padding: 0 1; }
#bar { height: 5; padding: 1 1 0 1; }
#build { width: 22; }
#pb { width: 28; padding-top: 1; }
#status { width: 1fr; padding: 1 2; }
PickFile, Confirm { align: center middle; }
#picker { width: 85%; height: 85%; border: thick $primary; background: $surface; padding: 1; }
#dialog { width: 64; height: auto; border: thick $primary; background: $surface; padding: 1 2; }
#dlgbtn { height: auto; margin-top: 1; }
#dlgbtn Button { margin-right: 2; }
"""


def run_tui(argv):
    try:
        from rich.text import Text
        from textual import on
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical, VerticalScroll
        from textual.screen import ModalScreen
        from textual.widgets import (Button, Checkbox, DataTable, DirectoryTree, Footer, Header, Input, Label,
                                     ProgressBar, RadioButton, RadioSet, RichLog, Static)
    except ImportError:
        sys.exit("Textual gerekli: pip install textual   (veya: pip install --upgrade py2apk)")

    class FilteredTree(DirectoryTree):
        exts = ()

        def filter_paths(self, paths):
            return [p for p in paths if not p.name.startswith(".") and (p.is_dir() or p.suffix.lower() in self.exts)]

    class PickFile(ModalScreen):
        BINDINGS = [("escape", "cancel", "İptal")]

        def __init__(self, text, exts, start):
            super().__init__()
            self.msg, self.exts, self.start_dir = text, exts, start

        def compose(self) -> ComposeResult:
            with Vertical(id="picker"):
                yield Label(f"{self.msg}  (ok tuşları + Enter, Esc: iptal)")
                tree = FilteredTree(str(self.start_dir), id="tree")
                tree.exts = self.exts
                yield tree

        def on_directory_tree_file_selected(self, event):
            event.stop(); self.dismiss(str(event.path))

        def action_cancel(self):
            self.dismiss(None)

    class Confirm(ModalScreen):
        def __init__(self, text):
            super().__init__()
            self.msg = text

        def compose(self) -> ComposeResult:
            with Vertical(id="dialog"):
                yield Label(Text(self.msg))
                with Horizontal(id="dlgbtn"):
                    yield Button("Evet", id="yes", variant="success")
                    yield Button("Hayır", id="no")

        def on_button_pressed(self, event):
            self.dismiss(event.button.id == "yes")

    class Py2Apk(App):
        TITLE = "py2apk"
        SUB_TITLE = "Python → Android APK"
        CSS = TUI_CSS
        BINDINGS = [("ctrl+q", "quit", "Çıkış"), ("ctrl+b", "build", "APK oluştur"), ("ctrl+o", "open_out", "Klasörü aç")]

        def __init__(self, preset=None):
            super().__init__()
            self.preset, self.idx, self.detected = preset, None, []
            self.last_script, self.out_path, self.building = "", None, False

        # ---- düzen
        def compose(self) -> ComposeResult:
            yield Header()
            with Horizontal(id="body"):
                with VerticalScroll(id="left"):
                    with Vertical(classes="card", id="c1"):
                        with Horizontal(classes="row"):
                            yield Label("Dosya")
                            yield Input(placeholder="main.py yolu (ya da Gözat)", id="script")
                            yield Button("Gözat", id="pick_script")
                    with Vertical(classes="card", id="c2"):
                        for lab, id_, val in (("Ad", "name", ""), ("Paket adı", "pkg", ""), ("Sürüm", "version", "1.0")):
                            with Horizontal(classes="row"):
                                yield Label(lab)
                                yield Input(value=val, id=id_)
                        with Horizontal(classes="row"):
                            yield Label("Logo")
                            yield Input(placeholder="logo.png (isteğe bağlı)", id="icon")
                            yield Button("Gözat", id="pick_icon")
                    with Vertical(classes="card", id="c3"):
                        with RadioSet(id="mode"):
                            yield RadioButton("Konsol: print() çıktısı ekranda", value=True, id="m_console")
                            yield RadioButton("Web arayüzü: Flask / FastAPI / NiceGUI + HTML (WebView)", id="m_web")
                            yield RadioButton("Pygame / Oyun: BETA, henüz kullanılamaz", id="m_pygame", disabled=True)
                            yield RadioButton("Kivy: BETA, henüz kullanılamaz", id="m_kivy", disabled=True)
                        with Horizontal(classes="row", id="portrow"):
                            yield Label("Sunucu portu")
                            yield Input(value="5000", id="port")
                        yield Static(Text(WEB_HINT), id="webhint")
                with Vertical(id="right"):
                    with Vertical(classes="card", id="c4"):
                        yield DataTable(id="libs", zebra_stripes=True, cursor_type="none")
                        with Horizontal(classes="row"):
                            yield Label("Ek paketler")
                            yield Input(placeholder="requests, numpy, ...", id="extra")
                        with Horizontal(classes="row"):
                            yield Checkbox("arm64-v8a (telefon)", True, id="abi_arm")
                            yield Checkbox("x86_64 (emülatör)", False, id="abi_x86")
                    yield RichLog(id="log", wrap=True, markup=False, highlight=False)
            with Horizontal(id="bar"):
                yield Button("APK OLUŞTUR", id="build", variant="primary")
                yield ProgressBar(id="pb", total=None, show_eta=False)
                yield Static("Hazır", id="status")
            yield Footer()

        def on_mount(self):
            for cid, title in (("c1", "1 · Python dosyası"), ("c2", "2 · Uygulama"), ("c3", "3 · Uygulama türü"),
                               ("c4", "4 · Kütüphaneler")):
                self.query_one("#" + cid).border_title = title
            self.query_one("#log").border_title = "Günlük"
            self.query_one("#libs", DataTable).add_columns("Kütüphane", "Durum")
            self.query_one("#pb").display = False
            self.apply_mode("m_console")
            set_log(self.safe_log)
            self.run_worker(self.load_index, thread=True)
            self.set_timer(1.0, self.check_path)
            if self.preset and Path(self.preset).is_file():
                self.query_one("#script", Input).value = str(Path(self.preset).resolve())

        # ---- günlük / durum (her iş parçacığından güvenli)
        def safe_log(self, m):
            if threading.current_thread() is threading.main_thread():
                self.on_log(m)
            else:
                self.call_from_thread(self.on_log, m)

        def on_log(self, m):
            style = ("dim" if m.startswith("$ ") else "yellow" if m.startswith("UYARI")
                     else "bold green" if m.startswith("HAZIR") else "")
            self.query_one("#log", RichLog).write(Text(m, style=style))
            if m.strip():
                self.query_one("#status", Static).update(Text(m.strip()[:90]))

        # ---- dizin ve kütüphane tablosu
        def load_index(self):
            try:
                self.idx = fetch_index(REPO)
            except Fail as e:
                self.safe_log(f"UYARI: {e}")
            self.call_from_thread(self.refresh_libs)

        def libs(self):
            extra = [norm(x) for x in re.split(r"[,\s]+", self.query_one("#extra", Input).value) if x]
            return list(dict.fromkeys([*self.detected, *extra]))

        def refresh_libs(self):
            tbl = self.query_one("#libs", DataTable)
            tbl.clear()
            for lib in self.libs():
                st = lib_status(self.idx, lib)
                tbl.add_row(lib, Text(st, style="green" if st.startswith("✓") else "red" if st.startswith("✗")
                                      else "yellow"))

        # ---- tür seçimi
        def apply_mode(self, rid):
            web = rid == "m_web"
            self.query_one("#portrow").display = web
            self.query_one("#webhint").display = web

        def get_mode(self):
            return "webview" if self.query_one("#mode", RadioSet).pressed_button.id == "m_web" else "console"

        @on(RadioSet.Changed, "#mode")
        def _mode_changed(self, event):
            self.apply_mode(event.pressed.id)

        # ---- dosya seçimi / girişler
        @on(Input.Changed, "#script")
        def _script_changed(self, event):
            p = Path(event.value.strip().strip('"'))
            if p.suffix == ".py" and p.is_file() and str(p) != self.last_script:
                self.last_script = str(p)
                self.on_script(p)

        @on(Input.Changed, "#extra")
        def _extra_changed(self, event):
            self.refresh_libs()

        def on_script(self, p):
            stem = re.sub(r"[^a-z0-9_]", "_", p.stem.lower()) or "app"
            self.query_one("#name", Input).value = p.stem.replace("_", " ").title()
            self.query_one("#pkg", Input).value = f"com.py2apk.{stem}"
            try:
                self.detected = detect_libs(collect(p))
            except Exception as e:
                self.detected = []; self.safe_log(f"tarama hatası: {e}")
            if WEB_LIBS & set(self.detected):
                self.query_one("#m_web", RadioButton).value = True
                self.safe_log("Web çatısı algılandı → uygulama türü 'Web arayüzü' seçildi")
            self.refresh_libs()

        def _start_dir(self):
            p = Path(self.query_one("#script", Input).value.strip().strip('"'))
            return p.parent if p.parent.exists() and str(p) else Path.home()

        @on(Button.Pressed, "#pick_script")
        def _pick_script(self, event):
            def done(path):
                if path:
                    self.query_one("#script", Input).value = path
            self.push_screen(PickFile("Python dosyası seç", (".py",), self._start_dir()), done)

        @on(Button.Pressed, "#pick_icon")
        def _pick_icon(self, event):
            def done(path):
                if path:
                    self.query_one("#icon", Input).value = path
            self.push_screen(PickFile("Logo seç", (".png", ".jpg", ".jpeg", ".webp"), self._start_dir()), done)

        @on(Button.Pressed, "#build")
        def _build_pressed(self, event):
            self.action_build()

        # ---- PATH önerisi (yalnızca bir kez)
        def check_path(self):
            flag, d = HOME / "path_asked", scripts_dir()
            if shutil.which("py2apk") or flag.exists() or not d:
                return
            flag.parent.mkdir(parents=True, exist_ok=True); flag.write_text("1")
            if WIN:
                def answer(yes):
                    if yes:
                        ok, msg = add_to_path(d)
                        self.notify(msg, severity="information" if ok else "warning", timeout=12)
                self.push_screen(Confirm("Terminalde 'py2apk' komutu bulunamıyor (Python'un Scripts klasörü PATH'te "
                                         f"değil).\n\nBu klasör PATH'e eklensin mi?\n{d}"), answer)
            else:
                self.safe_log(add_to_path(d)[1])

        # ---- derleme
        def action_build(self):
            if self.building:
                return
            q = lambda i: self.query_one(i, Input).value.strip()
            script = q("#script").strip('"')
            abis = [a for a, w in (("arm64-v8a", "#abi_arm"), ("x86_64", "#abi_x86"))
                    if self.query_one(w, Checkbox).value]
            err = None
            if not Path(script).is_file():
                err = "Önce bir .py dosyası seçin"
            elif not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", q("#pkg")):
                err = "Geçersiz paket adı (örn. com.ben.uygulama)"
            elif not abis:
                err = "En az bir mimari seçin"
            elif not q("#port").isdigit() or not 1024 <= int(q("#port")) <= 65535:
                err = "Port 1024-65535 arasında olmalı"
            if err:
                return self.notify(err, severity="error")
            cfg = dict(script=script, name=q("#name") or "App", package=q("#pkg"), icon=q("#icon") or None,
                       version=q("#version") or "1.0", vcode=1, abis=abis, libs=self.libs(), repo=REPO,
                       mode=self.get_mode(), port=int(q("#port")))
            self.building = True
            self.query_one("#build", Button).disabled = True
            self.query_one("#pb").display = True
            self.run_worker(lambda: self.do_build(cfg), thread=True)

        def do_build(self, cfg):
            try:
                out, err = str(build_apk(cfg)), None
            except Fail as e:
                out, err = None, str(e)
            except Exception:
                out, err = None, traceback.format_exc()
            self.call_from_thread(self.build_done, out, err)

        def build_done(self, out, err):
            self.building = False
            self.query_one("#build", Button).disabled = False
            self.query_one("#pb").display = False
            if err:
                self.on_log("HATA: " + err[-1500:])
                self.query_one("#status", Static).update(Text("Hata, günlüğe bakın", style="red"))
                self.notify("Derleme başarısız, günlüğe bakın", severity="error", timeout=10)
            else:
                self.out_path = out
                self.query_one("#status", Static).update(Text(f"Tamamlandı: {out}", style="green"))
                self.notify(f"APK hazır: {out}\nKlasörü açmak için Ctrl+O", timeout=15)

        def action_open_out(self):
            if self.out_path:
                open_folder(Path(self.out_path).parent)

    preset = next((a for a in argv if a.lower().endswith(".py")), None)
    Py2Apk(preset).run()


USAGE = """py2apk - Python'u Android APK'sına çevirir

  py2apk [dosya.py]            terminal arayüzünü (TUI) açar
  py2apk build dosya.py ...    arayüzsüz derleme (py2apk build -h)
  py2apk --add-to-path         'py2apk' komutunu PATH'e ekler
"""


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--add-to-path":
        d = scripts_dir()
        print(add_to_path(d)[1] if d else "py2apk başlatıcısı bulunamadı (pip ile kurulu mu?)")
    elif argv and argv[0] == "build":
        build_cli(argv[1:])
    elif argv and argv[0] in ("-h", "--help"):
        print(USAGE)
    else:
        run_tui(argv)


if __name__ == "__main__":
    main()
