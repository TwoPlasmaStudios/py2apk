#!/usr/bin/env python3
"""py2apk - GUI ile Python -> APK (Windows / macOS / Linux).

Kullanıcı tarafında DERLEME YOK: CPython runtime'ı ve kütüphane wheel'leri
GitHub Releases'e önceden derlenip konmuştur (bkz. factory.py). Bu araç yalnızca
eksik araçları (JDK, Android build-tools) indirir, hazır parçaları çeker ve APK'yı paketler.

    pip install py2apk   ->   py2apk
"""
from __future__ import annotations

import ast, json, os, platform, queue, re, shutil, struct, subprocess, sys, tarfile
import threading, traceback, urllib.parse, urllib.request, zipfile, zlib
from pathlib import Path
from xml.sax.saxutils import quoteattr

_old, _new = Path.home() / ".pyapk", Path.home() / ".py2apk"   # eski önbelleği (JDK/SDK) yeniden indirme
HOME = Path(os.environ.get("PY2APK_HOME") or (_old if _old.exists() and not _new.exists() else _new))
REPO = os.environ.get("PY2APK_REPO") or os.environ.get("PYAPK_REPO") or "TwoPlasmaStudios/pyapk"
PY_TAG = os.environ.get("PY2APK_PY", "cp313")              # release etiketi
ABIS = ("arm64-v8a", "x86_64")
BT_VER, PLATFORM, TARGET_SDK, MIN_SDK = "34.0.0", "android-34", 34, 24
CMDLINE = "https://dl.google.com/android/repository/commandlinetools-{os}-11076708_latest.zip"
SYS = platform.system()
WIN = SYS == "Windows"
ARCH = "aarch64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
EXE, BAT = (".exe", ".bat") if WIN else ("", "")

PIPMAP = {"PIL": "pillow", "cv2": "opencv-python-headless", "yaml": "pyyaml", "bs4": "beautifulsoup4",
          "sklearn": "scikit-learn", "dateutil": "python-dateutil", "dotenv": "python-dotenv",
          "OpenSSL": "pyopenssl", "Crypto": "pycryptodome", "serial": "pyserial", "jwt": "pyjwt",
          "attr": "attrs", "skimage": "scikit-image", "git": "gitpython", "magic": "python-magic"}
UNSUPPORTED = {"tkinter": "Android'de Tk yok (Web arayüzü türünü kullanın)",
               "pygame": "pygame için SDL altyapısı henüz yok", "kivy": "kivy için SDL altyapısı henüz yok"}
WEB_LIBS = {"flask", "fastapi", "bottle", "django", "quart", "starlette", "uvicorn", "waitress"}
MODES = [  # (anahtar, başlık, açıklama, destekleniyor)
    ("console", "Konsol", "print() çıktısı ekranda görünür. Betikler, botlar, hesaplamalar.", True),
    ("webview", "Web arayüzü", "Flask / FastAPI + HTML. Uygulama yerel sunucu açar, arayüz tam ekran WebView'da görünür.", True),
    ("pygame", "Pygame / Oyun", "SDL2 altyapısı gerekir. Henüz desteklenmiyor.", False),
    ("kivy", "Kivy", "SDL2 altyapısı gerekir. Henüz desteklenmiyor.", False),
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


# --------------------------------------------------------------------------- GUI
BG, HEAD, CARD, CARD2 = "#0b1220", "#0f1830", "#141c2f", "#18233b"
FIELD, LINE, FG, MUTED = "#0c1426", "#26334f", "#e6edf7", "#8b9ab3"
ACC, OK, WARN, BAD = "#5b8cff", "#34d399", "#fbbf24", "#f87171"
UI = {"Windows": "Segoe UI", "Darwin": "Helvetica Neue"}.get(SYS, "DejaVu Sans")
MONO = {"Windows": "Consolas", "Darwin": "Menlo"}.get(SYS, "DejaVu Sans Mono")


def open_folder(p):
    if WIN:
        os.startfile(p)  # noqa
    else:
        subprocess.run(["open" if SYS == "Darwin" else "xdg-open", str(p)])


def main(argv=None):
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError:
        sys.exit("tkinter bulunamadı. Linux'ta: sudo apt install python3-tk")
    if WIN:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # net yazı
        except Exception:
            pass
    argv = sys.argv[1:] if argv is None else argv

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("py2apk"); self.geometry("1100x790"); self.minsize(1000, 720); self.configure(bg=BG)
            self.q, self.idx, self.detected, self.photo = queue.Queue(), None, [], None
            self.script, self.name, self.pkg, self.icon = (tk.StringVar() for _ in range(4))
            self.version, self.extra, self.repo = tk.StringVar(value="1.0"), tk.StringVar(), tk.StringVar(value=REPO)
            self.port, self.mode, self.status = tk.StringVar(value="5000"), tk.StringVar(value="console"), \
                tk.StringVar(value="Hazır")
            self.abi = {a: tk.BooleanVar(value=(a == "arm64-v8a")) for a in ABIS}
            self.cards = {}
            self.style_setup(); self.build_ui(); self.set_mode("console")
            self.extra.trace_add("write", lambda *_: self.refresh())
            set_log(lambda m: self.q.put(("log", m)))
            self.after(100, self.pump)
            threading.Thread(target=self.load_index, daemon=True).start()
            if argv and Path(argv[0]).is_file():
                self.script.set(argv[0]); self.on_script()

        # ---- görünüm
        def style_setup(self):
            s = ttk.Style(self); s.theme_use("clam")
            s.configure(".", background=BG, foreground=FG, font=(UI, 10))
            s.configure("T.TEntry", fieldbackground=FIELD, foreground=FG, bordercolor=LINE, lightcolor=LINE,
                        darkcolor=LINE, insertcolor=FG, padding=7)
            s.map("T.TEntry", bordercolor=[("focus", ACC)], lightcolor=[("focus", ACC)], darkcolor=[("focus", ACC)])
            s.configure("T.TButton", background=LINE, foreground=FG, borderwidth=0, focusthickness=0, padding=(14, 7))
            s.map("T.TButton", background=[("active", "#2f3d5e")])
            s.configure("Accent.TButton", background=ACC, foreground="#ffffff", font=(UI, 12, "bold"),
                        padding=(18, 12), borderwidth=0, focusthickness=0)
            s.map("Accent.TButton", background=[("disabled", "#26324d"), ("active", "#7aa2ff")],
                  foreground=[("disabled", "#7c8aa5")])
            s.configure("T.Horizontal.TProgressbar", troughcolor=FIELD, background=ACC, bordercolor=BG,
                        lightcolor=ACC, darkcolor=ACC, thickness=8)
            s.configure("T.Treeview", background=FIELD, fieldbackground=FIELD, foreground=FG, rowheight=27,
                        borderwidth=0, font=(UI, 10))
            s.configure("T.Treeview.Heading", background=CARD2, foreground=MUTED, borderwidth=0, relief="flat",
                        font=(UI, 9, "bold"))
            s.map("T.Treeview", background=[("selected", "#22304f")])
            s.map("T.Treeview.Heading", background=[("active", CARD2)])
            s.configure("T.TCheckbutton", background=CARD, foreground=FG, font=(UI, 10), focusthickness=0)
            s.map("T.TCheckbutton", background=[("active", CARD)])
            s.configure("Vertical.TScrollbar", background=LINE, troughcolor=FIELD, bordercolor=FIELD,
                        arrowcolor=MUTED, relief="flat")

        def card(self, parent, step, title):
            outer = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=LINE)
            head = tk.Frame(outer, bg=CARD); head.pack(fill="x", padx=16, pady=(14, 8))
            tk.Label(head, text=str(step), bg=ACC, fg="#fff", font=(UI, 9, "bold"), width=2).pack(side="left")
            tk.Label(head, text=title, bg=CARD, fg=FG, font=(UI, 11, "bold")).pack(side="left", padx=10)
            body = tk.Frame(outer, bg=CARD); body.pack(fill="both", expand=True, padx=16, pady=(0, 14))
            return outer, body

        def label(self, parent, text, **kw):
            return tk.Label(parent, text=text, bg=kw.pop("bg", CARD), fg=kw.pop("fg", MUTED),
                            font=kw.pop("font", (UI, 9)), anchor="w", **kw)

        def field(self, body, row, text, var, browse=None, width=None):
            self.label(body, text).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
            ttk.Entry(body, textvariable=var, style="T.TEntry", width=width or 30).grid(row=row, column=1,
                                                                                         sticky="ew", pady=4)
            if browse:
                ttk.Button(body, text="Seç…", style="T.TButton", command=browse).grid(row=row, column=2,
                                                                                         padx=(8, 0))

        def build_ui(self):
            hd = tk.Frame(self, bg=HEAD); hd.pack(fill="x")
            inner = tk.Frame(hd, bg=HEAD); inner.pack(fill="x", padx=24, pady=16)
            tk.Label(inner, text="py2", bg=HEAD, fg=ACC, font=(UI, 22, "bold")).pack(side="left")
            tk.Label(inner, text="apk", bg=HEAD, fg=FG, font=(UI, 22, "bold")).pack(side="left")
            tk.Label(inner, text="Python'u Android uygulamasına çevir", bg=HEAD, fg=MUTED,
                     font=(UI, 11)).pack(side="left", padx=16, pady=(8, 0))
            tk.Frame(self, bg=LINE, height=1).pack(fill="x")

            foot = tk.Frame(self, bg=BG); foot.pack(side="bottom", fill="x", padx=20, pady=(6, 16))
            self.btn = ttk.Button(foot, text="APK OLUŞTUR", style="Accent.TButton", command=self.start)
            self.btn.pack(side="left")
            right = tk.Frame(foot, bg=BG); right.pack(side="left", fill="x", expand=True, padx=18)
            tk.Label(right, textvariable=self.status, bg=BG, fg=MUTED, font=(UI, 9), anchor="w").pack(fill="x")
            self.pb = ttk.Progressbar(right, mode="indeterminate", style="T.Horizontal.TProgressbar")
            self.pb.pack(fill="x", pady=(4, 0))

            body = tk.Frame(self, bg=BG); body.pack(fill="both", expand=True, padx=20, pady=16)
            body.columnconfigure(0, weight=11, uniform="c"); body.columnconfigure(1, weight=9, uniform="c")
            body.rowconfigure(0, weight=1)
            left = tk.Frame(body, bg=BG); left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
            rt = tk.Frame(body, bg=BG); rt.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

            # 1 kaynak
            c, b = self.card(left, 1, "Python dosyası"); c.pack(fill="x", pady=(0, 12)); b.columnconfigure(1, weight=1)
            self.field(b, 0, "Giriş dosyası", self.script, self.pick_script)

            # 2 uygulama bilgisi
            c, b = self.card(left, 2, "Uygulama"); c.pack(fill="x", pady=(0, 12)); b.columnconfigure(1, weight=1)
            self.field(b, 0, "Ad", self.name)
            self.field(b, 1, "Paket adı", self.pkg)
            self.field(b, 2, "Sürüm", self.version)
            self.field(b, 3, "Logo", self.icon, self.pick_icon)
            self.preview = tk.Label(b, text="logo", bg=FIELD, fg=MUTED, width=8, height=4, font=(UI, 8))
            self.preview.grid(row=0, column=3, rowspan=3, padx=(14, 0), sticky="ne")

            # 3 uygulama türü
            c, b = self.card(left, 3, "Uygulama türü"); c.pack(fill="both", expand=True)
            grid = tk.Frame(b, bg=CARD); grid.pack(fill="x")
            for i in range(2):
                grid.columnconfigure(i, weight=1, uniform="m")
            for n, (key, title, desc, ok) in enumerate(MODES):
                self.make_card(grid, key, title, desc, ok).grid(row=n // 2, column=n % 2, sticky="nsew",
                                                                 padx=4, pady=4)
            self.mode_box = tk.Frame(b, bg=CARD); self.mode_box.pack(fill="x", pady=(8, 0))
            self.mode_hint = tk.Label(self.mode_box, bg=CARD, fg=MUTED, font=(UI, 9), justify="left",
                                      anchor="w", wraplength=470)
            self.mode_hint.pack(fill="x")
            self.port_row = tk.Frame(self.mode_box, bg=CARD)
            self.label(self.port_row, "Sunucu portu").pack(side="left")
            ttk.Entry(self.port_row, textvariable=self.port, style="T.TEntry", width=7).pack(side="left", padx=8)
            self.code_hint = tk.Label(self.mode_box, bg=FIELD, fg="#b9c7e3", font=(MONO, 9), justify="left",
                                      anchor="w", padx=10, pady=8,
                                      text="import os\napp.run(host=\"127.0.0.1\",\n        port=int(os.environ.get(\"PORT\", 5000)),\n        debug=False)")

            # 4 kütüphaneler
            c, b = self.card(rt, 4, "Kütüphaneler"); c.pack(fill="x", pady=(0, 12))
            self.tree = ttk.Treeview(b, columns=("lib", "durum"), show="headings", height=5, style="T.Treeview")
            self.tree.heading("lib", text="Algılanan", anchor="w"); self.tree.heading("durum", text="Durum", anchor="w")
            self.tree.column("lib", width=150); self.tree.column("durum", width=260)
            for t, col in (("ok", OK), ("warn", WARN), ("bad", BAD)):
                self.tree.tag_configure(t, foreground=col)
            self.tree.pack(fill="x")
            r = tk.Frame(b, bg=CARD); r.pack(fill="x", pady=(10, 0)); r.columnconfigure(1, weight=1)
            self.field(r, 0, "Ek paketler", self.extra, width=20)
            ab = tk.Frame(b, bg=CARD); ab.pack(fill="x", pady=(8, 0))
            for a, v in self.abi.items():
                ttk.Checkbutton(ab, text=a + (" · telefon" if a == "arm64-v8a" else " · emülatör"), variable=v,
                                style="T.TCheckbutton").pack(side="left", padx=(0, 16))
            adv = tk.Label(b, text="Gelişmiş ▸", bg=CARD, fg=MUTED, font=(UI, 9), cursor="hand2")
            adv.pack(anchor="w", pady=(8, 0))
            self.adv_row = tk.Frame(b, bg=CARD); self.adv_row.columnconfigure(1, weight=1)
            self.field(self.adv_row, 0, "GitHub deposu", self.repo, width=20)
            adv.bind("<Button-1>", lambda e: (self.adv_row.pack_forget() if self.adv_row.winfo_ismapped()
                                              else self.adv_row.pack(fill="x")))

            # günlük
            c, b = self.card(rt, "›", "Günlük"); c.pack(fill="both", expand=True)
            wrap = tk.Frame(b, bg="#070c16"); wrap.pack(fill="both", expand=True)
            self.logw = tk.Text(wrap, height=8, state="disabled", bg="#070c16", fg="#c9d4e8", relief="flat",
                                font=(MONO, 9), wrap="word", padx=10, pady=8, insertbackground=FG,
                                highlightthickness=0)
            sb = ttk.Scrollbar(wrap, command=self.logw.yview)
            self.logw["yscrollcommand"] = sb.set
            sb.pack(side="right", fill="y"); self.logw.pack(side="left", fill="both", expand=True)
            self.logw.tag_configure("cmd", foreground="#6b7a99"); self.logw.tag_configure("warn", foreground=WARN)
            self.logw.tag_configure("good", foreground=OK, font=(MONO, 9, "bold"))
            self.logw.tag_configure("bad", foreground=BAD)

        def make_card(self, parent, key, title, desc, ok):
            fr = tk.Frame(parent, bg=CARD2, highlightthickness=2, highlightbackground=LINE,
                          cursor="hand2" if ok else "arrow")
            top = tk.Frame(fr, bg=CARD2); top.pack(fill="x", padx=10, pady=(10, 2))
            t = tk.Label(top, text=title, bg=CARD2, fg=FG if ok else MUTED, font=(UI, 11, "bold"), anchor="w")
            t.pack(side="left")
            if not ok:
                tk.Label(top, text="YAKINDA", bg=WARN, fg="#1a1300", font=(UI, 7, "bold"), padx=5).pack(side="right")
            d = tk.Label(fr, text=desc, bg=CARD2, fg=MUTED, font=(UI, 9), justify="left", anchor="nw",
                         wraplength=210, height=4)
            d.pack(fill="x", padx=10, pady=(0, 10))
            if ok:
                for w in (fr, top, t, d):
                    w.bind("<Button-1>", lambda e, k=key: self.set_mode(k))
            self.cards[key] = fr
            return fr

        def set_mode(self, key):
            self.mode.set(key)
            for k, fr in self.cards.items():
                fr.configure(highlightbackground=ACC if k == key else LINE)
            if key == "webview":
                self.mode_hint.configure(text="Kodunuz bir web sunucusu başlatmalı (debug kapalı). "
                                              "Hazır olunca arayüz uygulamada tam ekran açılır.")
                self.port_row.pack(anchor="w", pady=(8, 0)); self.code_hint.pack(fill="x", pady=(8, 0))
            else:
                self.mode_hint.configure(text="Çıktı ekranda metin olarak görünür. Etkileşimli girdi (input) yok.")
                self.port_row.pack_forget(); self.code_hint.pack_forget()

        # ---- olaylar
        def pick_script(self):
            p = filedialog.askopenfilename(title="Python dosyası", filetypes=[("Python", "*.py")])
            if p:
                self.script.set(p); self.on_script()

        def pick_icon(self):
            p = filedialog.askopenfilename(title="Logo", filetypes=[("Resim", "*.png *.jpg *.jpeg *.webp")])
            if not p:
                return
            self.icon.set(p)
            try:
                try:
                    from PIL import Image, ImageTk
                    self.photo = ImageTk.PhotoImage(Image.open(p).convert("RGBA").resize((64, 64)))
                except ImportError:
                    img = tk.PhotoImage(file=p)
                    self.photo = img.subsample(max(1, img.width() // 64), max(1, img.height() // 64))
                self.preview.configure(image=self.photo, text="", width=64, height=64)
            except Exception:
                self.preview.configure(image="", text="logo")

        def on_script(self):
            p = Path(self.script.get())
            stem = re.sub(r"[^a-z0-9_]", "_", p.stem.lower()) or "app"
            self.name.set(p.stem.replace("_", " ").title()); self.pkg.set(f"com.py2apk.{stem}")
            try:
                self.detected = detect_libs(collect(p))
            except Exception as e:
                self.detected = []; log(f"tarama hatası: {e}")
            if WEB_LIBS & set(self.detected):
                self.set_mode("webview")
                log("Web çatısı algılandı → uygulama türü 'Web arayüzü' seçildi")
            self.refresh()

        def load_index(self):
            try:
                self.idx = fetch_index(self.repo.get())
            except Fail as e:
                self.q.put(("log", f"UYARI: {e}"))
            self.q.put(("refresh", None))

        def libs(self):
            extra = [norm(x) for x in re.split(r"[,\s]+", self.extra.get()) if x]
            return list(dict.fromkeys([*self.detected, *extra]))

        def refresh(self):
            self.tree.delete(*self.tree.get_children())
            for lib in self.libs():
                st = lib_status(self.idx, lib)
                self.tree.insert("", "end", values=(lib, st),
                                 tags=("ok" if st.startswith("✓") else "bad" if st.startswith("✗") else "warn",))

        def start(self):
            abis = [a for a, v in self.abi.items() if v.get()]
            if not Path(self.script.get()).is_file():
                return messagebox.showerror("py2apk", "Önce bir .py dosyası seçin")
            if not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", self.pkg.get()):
                return messagebox.showerror("py2apk", "Geçersiz paket adı (örn. com.ben.uygulama)")
            if not abis:
                return messagebox.showerror("py2apk", "En az bir mimari seçin")
            if not self.port.get().isdigit() or not (1024 <= int(self.port.get()) <= 65535):
                return messagebox.showerror("py2apk", "Port 1024-65535 arasında olmalı")
            cfg = dict(script=self.script.get(), name=self.name.get() or "App", package=self.pkg.get(),
                       icon=self.icon.get() or None, version=self.version.get() or "1.0", vcode=1, abis=abis,
                       libs=self.libs(), repo=self.repo.get(), mode=self.mode.get(), port=int(self.port.get()))
            self.btn.state(["disabled"]); self.pb.start(12); self.status.set("Başladı…")

            def work():
                try:
                    self.q.put(("done", str(build_apk(cfg))))
                except Fail as e:
                    self.q.put(("err", str(e)))
                except Exception:
                    self.q.put(("err", traceback.format_exc()))
            threading.Thread(target=work, daemon=True).start()

        def pump(self):
            try:
                while True:
                    kind, val = self.q.get_nowait()
                    if kind == "log":
                        tag = ("cmd" if val.startswith("$ ") else "warn" if val.startswith("UYARI")
                               else "good" if val.startswith("HAZIR") else "")
                        self.logw.configure(state="normal"); self.logw.insert("end", val + "\n", tag)
                        self.logw.see("end"); self.logw.configure(state="disabled")
                        if val.strip():
                            self.status.set(val.strip()[:100])
                    elif kind == "refresh":
                        self.refresh()
                    else:
                        self.pb.stop(); self.btn.state(["!disabled"])
                        if kind == "err":
                            self.status.set("Hata"); messagebox.showerror("py2apk - hata", val[-1500:])
                        else:
                            self.status.set("Tamamlandı ✓")
                            if messagebox.askyesno("py2apk", f"APK hazır:\n{val}\n\nKlasörü açayım mı?"):
                                open_folder(Path(val).parent)
            except queue.Empty:
                pass
            self.after(100, self.pump)

    App().mainloop()


if __name__ == "__main__":
    main()
