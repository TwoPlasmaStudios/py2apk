#!/usr/bin/env python3
"""PyAPK - GUI ile Python -> APK (Windows / macOS / Linux).

Kullanıcı tarafında DERLEME YOK: CPython runtime'ı ve kütüphane wheel'leri
GitHub Releases'e önceden derlenip konmuştur (bkz. factory.py). Bu araç yalnızca
eksik araçları (JDK, Android build-tools) indirir, hazır parçaları çeker ve APK'yı paketler.

    pip install .   ->   pyapk
"""
from __future__ import annotations

import ast, json, os, platform, queue, re, shutil, struct, subprocess, sys, tarfile
import threading, traceback, urllib.parse, urllib.request, zipfile, zlib
from pathlib import Path
from xml.sax.saxutils import quoteattr

HOME = Path(os.environ.get("PYAPK_HOME", Path.home() / ".pyapk"))
REPO = os.environ.get("PYAPK_REPO", "OWNER/pyapk")        # <-- kendi GitHub deponuzu yazın
PY_TAG = os.environ.get("PYAPK_PY", "cp313")               # release etiketi
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
UNSUPPORTED = {"tkinter": "Tk yok", "pygame": "pygame için SDL altyapısı henüz yok"}


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
        stdin = p.stdin
        if stdin is None:
            die("stdin is not available")
        stdin.write(input)
        stdin.close()
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
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "pyapk"}), timeout=60) as r, \
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


def manifest_xml(pkg, name, vname, vcode):
    return f'''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package={quoteattr(pkg)}
    android:versionCode="{vcode}" android:versionName={quoteattr(vname)}>
  <uses-permission android:name="android.permission.INTERNET"/>
  <application android:label={quoteattr(name)} android:icon="@mipmap/ic_launcher" android:allowBackup="false"
      android:extractNativeLibs="true" android:theme="@android:style/Theme.Material.Light.NoActionBar">
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
    (work / "AndroidManifest.xml").write_text(manifest_xml(c["package"], c["name"], c["version"], c["vcode"]),
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
        (app / "_pyapk_boot.py").write_text(BOOT_PY.replace("@MAIN@", repr(src.name)), encoding="utf-8")
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
             "-dname", "CN=PyAPK"])
    aligned = work / "aligned.apk"
    run([bt / f"zipalign{EXE}", "-f", "-p", "4", base, aligned])
    out = Path(c.get("out") or src.parent / f"{re.sub(r'[^A-Za-z0-9_-]', '_', c['name'])}-{c['version']}.apk")
    run([bt / f"apksigner{BAT}", "sign", "--ks", ks, "--ks-pass", "pass:android", "--key-pass", "pass:android",
         "--out", out, aligned], env=je)
    log(f"HAZIR: {out}  ({out.stat().st_size >> 20} MB)")
    return out


# --------------------------------------------------------------------------- GUI
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
    argv = sys.argv[1:] if argv is None else argv

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("PyAPK - Python'dan APK"); self.geometry("860x760"); self.minsize(760, 640)
            self.q, self.idx, self.detected, self.icon_img = queue.Queue(), None, [], None
            sv = tk.StringVar
            self.script, self.name, self.pkg, self.icon = sv(), sv(), sv(), sv()
            self.version, self.extra, self.repo = sv(value="1.0"), sv(), sv(value=REPO)
            self.abi = {a: tk.BooleanVar(value=(a == "arm64-v8a")) for a in ABIS}
            f = ttk.Frame(self, padding=12); f.pack(fill="both", expand=True); f.columnconfigure(1, weight=1)

            def row(r, label, var, browse=None):
                ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=3)
                ttk.Entry(f, textvariable=var).grid(row=r, column=1, sticky="ew", padx=6)
                if browse:
                    ttk.Button(f, text="Seç…", command=browse).grid(row=r, column=2)
            row(0, "Python dosyası", self.script, self.pick_script)
            row(1, "Uygulama adı", self.name)
            row(2, "Paket adı", self.pkg)
            row(3, "Logo (PNG)", self.icon, self.pick_icon)
            self.preview = ttk.Label(f); self.preview.grid(row=3, column=3, padx=6)
            row(4, "Sürüm", self.version)
            ttk.Label(f, text="Mimariler").grid(row=5, column=0, sticky="w")
            fr = ttk.Frame(f); fr.grid(row=5, column=1, sticky="w", padx=6)
            for a, v in self.abi.items():
                ttk.Checkbutton(fr, text=a + (" (telefon)" if a == "arm64-v8a" else " (emülatör)"),
                                variable=v).pack(side="left", padx=(0, 12))
            row(6, "Ek kütüphaneler", self.extra)
            row(7, "GitHub deposu", self.repo)
            self.tree = ttk.Treeview(f, columns=("lib", "durum"), show="headings", height=6)
            self.tree.heading("lib", text="Algılanan kütüphane"); self.tree.heading("durum", text="Durum")
            self.tree.column("lib", width=220); self.tree.column("durum", width=420)
            self.tree.grid(row=8, column=0, columnspan=4, sticky="ew", pady=8)
            self.btn = ttk.Button(f, text="APK OLUŞTUR", command=self.start)
            self.btn.grid(row=9, column=0, columnspan=2, sticky="ew", pady=4)
            self.pb = ttk.Progressbar(f, mode="indeterminate"); self.pb.grid(row=9, column=2, columnspan=2, sticky="ew")
            f.rowconfigure(10, weight=1)
            self.logw = tk.Text(f, height=14, state="disabled", font=("Courier", 9), wrap="none")
            self.logw.grid(row=10, column=0, columnspan=4, sticky="nsew")
            sb = ttk.Scrollbar(f, command=self.logw.yview); sb.grid(row=10, column=4, sticky="ns")
            self.logw["yscrollcommand"] = sb.set
            self.extra.trace_add("write", lambda *_: self.refresh())
            set_log(lambda m: self.q.put(("log", m)))
            self.after(100, self.pump)
            threading.Thread(target=self.load_index, daemon=True).start()
            if argv and Path(argv[0]).is_file():
                self.script.set(argv[0]); self.on_script()

        # ---- olaylar
        def pick_script(self):
            p = filedialog.askopenfilename(title="Python dosyası", filetypes=[("Python", "*.py")])
            if p:
                self.script.set(p); self.on_script()

        def pick_icon(self):
            p = filedialog.askopenfilename(title="Logo", filetypes=[("Resim", "*.png *.jpg *.jpeg *.webp")])
            if p:
                self.icon.set(p)
                try:
                    img = tk.PhotoImage(file=p)
                    self.icon_img = img.subsample(max(1, img.width() // 48), max(1, img.height() // 48))
                    self.preview.configure(image=self.icon_img)
                except Exception:
                    self.preview.configure(image="")

        def on_script(self):
            p = Path(self.script.get())
            stem = re.sub(r"[^a-z0-9_]", "_", p.stem.lower()) or "app"
            self.name.set(p.stem.replace("_", " ").title()); self.pkg.set(f"com.pyapk.{stem}")
            try:
                self.detected = detect_libs(collect(p))
            except Exception as e:
                self.detected = []; log(f"tarama hatası: {e}")
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
                self.tree.insert("", "end", values=(lib, lib_status(self.idx, lib)))

        def start(self):
            abis = [a for a, v in self.abi.items() if v.get()]
            if not Path(self.script.get()).is_file():
                return messagebox.showerror("PyAPK", "Önce bir .py dosyası seçin")
            if not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", self.pkg.get()):
                return messagebox.showerror("PyAPK", "Geçersiz paket adı (örn. com.ben.uygulama)")
            if not abis:
                return messagebox.showerror("PyAPK", "En az bir mimari seçin")
            cfg = dict(script=self.script.get(), name=self.name.get() or "App", package=self.pkg.get(),
                       icon=self.icon.get() or None, version=self.version.get() or "1.0", vcode=1, abis=abis,
                       libs=self.libs(), repo=self.repo.get())
            self.btn.state(["disabled"]); self.pb.start(12)

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
                        self.logw.configure(state="normal"); self.logw.insert("end", val + "\n")
                        self.logw.see("end"); self.logw.configure(state="disabled")
                    elif kind == "refresh":
                        self.refresh()
                    else:
                        self.pb.stop(); self.btn.state(["!disabled"])
                        if kind == "err":
                            messagebox.showerror("PyAPK - hata", val[-1500:])
                        elif messagebox.askyesno("PyAPK", f"APK hazır:\n{val}\n\nKlasörü açayım mı?"):
                            open_folder(Path(val).parent)
            except queue.Empty:
                pass
            self.after(100, self.pump)

    App().mainloop()


if __name__ == "__main__":
    main()
