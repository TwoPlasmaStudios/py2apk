#!/usr/bin/env python3
"""PyAPK fabrikası - GitHub Actions (ubuntu) üzerinde çalışır, son kullanıcı çalıştırmaz.

  python factory.py list                         -> kütüphane listesi (JSON, matrix için)
  python factory.py runtime --py 3.13.5          -> Android CPython + JNI çalıştırıcı + classes.dex
  python factory.py wheel light-01 --py 3.13     -> bir iş grubunun kütüphaneleri (+bağımlılıkların) Android wheel'leri
  python factory.py publish --repo OWNER/REPO    -> index.json üretir, GitHub Release'e yükler

Strateji (wheel): önce PyPI + Chaquopy dizininde hazır Android/saf-Python wheel aranır;
eksik bağımlılık çıkarsa sdist'ten cibuildwheel (--platform android) ile derlenir.
"""
from __future__ import annotations

import argparse, json, os, re, shutil, subprocess, sys, tarfile, tempfile, time, urllib.request, zipfile
from pathlib import Path

# Kategoriler -> PyPI adları. Her biri için Android (veya saf Python) wheel kapanışı çözülür.
CATEGORIES = {
    "Web / sunucu": ["flask", "django", "fastapi", "starlette", "uvicorn", "bottle", "quart", "tornado", "aiohttp",
                     "falcon", "cherrypy", "waitress", "werkzeug", "jinja2", "requests", "httpx", "websockets",
                     "python-socketio", "flask-socketio", "flask-cors", "flask-sqlalchemy", "flask-login",
                     "flask-wtf", "nicegui", "dash", "pywebio", "remi", "streamlit", "gradio", "websocket-client"],
    "GUI / oyun": ["pygame", "pygame-ce", "kivy", "kivymd", "pyglet", "arcade", "pysdl2", "pymunk", "pygame-gui",
                   "pgzero", "raylib", "moderngl", "pyopengl", "panda3d", "ursina", "flet"],
    "Minecraft / bot / sosyal": ["minecraft-launcher-lib", "mcstatus", "nbtlib", "mcrcon", "discord.py",
                                 "python-telegram-bot", "aiogram", "pytelegrambotapi", "slack-sdk", "tweepy", "praw"],
    "Ağ / donanım": ["paho-mqtt", "dnspython", "paramiko", "pysocks", "aiofiles", "httpcore", "pyserial", "scapy",
                     "zeroconf", "ping3"],
    "Veri / bilim / görüntü": ["numpy", "pandas", "scipy", "scikit-learn", "matplotlib", "seaborn", "plotly", "sympy",
                               "networkx", "statsmodels", "scikit-image", "bokeh", "openpyxl", "xlsxwriter", "xlrd",
                               "polars", "tabulate", "pillow", "opencv-python-headless", "imageio"],
    "Metin / ayrıştırma": ["beautifulsoup4", "lxml", "html5lib", "pyyaml", "tomlkit", "python-dotenv", "jsonschema",
                           "markdown", "mistune", "pygments", "docutils", "rich", "tqdm", "colorama", "click", "typer",
                           "loguru", "pyfiglet", "prompt-toolkit", "regex", "python-dateutil", "pytz", "tzdata",
                           "arrow", "babel", "unidecode", "emoji", "jmespath", "xmltodict", "feedparser",
                           "markdownify"],
    "Veritabanı": ["sqlalchemy", "alembic", "peewee", "tinydb", "pymongo", "redis", "aiosqlite", "sqlmodel"],
    "Güvenlik": ["cryptography", "pycryptodome", "bcrypt", "pynacl", "pyjwt", "passlib", "argon2-cffi", "pyotp",
                 "itsdangerous", "oauthlib", "authlib"],
    "Yardımcı": ["attrs", "pydantic", "marshmallow", "orjson", "ujson", "msgpack", "cachetools", "tenacity",
                 "more-itertools", "toolz", "schedule", "apscheduler", "psutil", "python-slugify", "shortuuid",
                 "qrcode", "faker", "humanize", "pint", "filelock", "platformdirs", "packaging", "six"],
    "Belge / medya": ["reportlab", "fpdf2", "pypdf", "python-docx", "python-pptx", "mutagen", "gtts"],
    "Yapay zeka": ["openai", "anthropic", "ollama", "huggingface-hub", "tokenizers", "google-generativeai"],
}
BASE = ["certifi"]  # her APK'ya girer (https sertifikaları)
ALL = list(dict.fromkeys([n for v in CATEGORIES.values() for n in v] + BASE))
# Kaynaktan ASLA derlenmeyenler: yalnızca hazır Android/saf-Python wheel varsa alınır (yoksa "başarısız" yazılır).
# Pencere/SDL gerektirenler, Rust/gRPC/Arrow gibi ağır zincirler, bu çalışma zamanında anlamsız ya da çok pahalı.
GUI_NATIVE = {"pygame", "pygame-ce", "kivy", "pysdl2", "panda3d", "ursina", "raylib", "moderngl", "arcade", "flet",
              "pymunk", "pyglet"}
NO_BUILD = GUI_NATIVE | {"polars", "tokenizers", "google-generativeai", "pymongo", "streamlit", "gradio",
                         "huggingface-hub", "pgzero", "pygame-gui", "kivymd"}
GUI_NOTE = "SDL2/pencere altyapısı henüz yok (beta). Android wheel bulunamadı: "
# Ağır (kaynaktan derleme ihtimali olan) kütüphaneler tek başına bir iş olur; kalanlar 10'arlı gruplanır.
HEAVY = {"numpy", "pandas", "scipy", "scikit-learn", "matplotlib", "pillow", "opencv-python-headless", "cryptography",
         "lxml", "pydantic", "psutil", "scikit-image", "statsmodels", "bcrypt", "pynacl", "pycryptodome", "orjson",
         "msgpack", "pyyaml", "seaborn", "bokeh"}


def norm(n):
    return re.sub(r"[-_.]+", "-", n).lower()


def batches():
    out = {f"heavy-{n}": [n] for n in ALL if n in HEAVY}
    light = [n for n in ALL if n not in HEAVY]
    for k in range(0, len(light), 10):
        out[f"light-{k // 10 + 1:02d}"] = light[k:k + 10]
    return out


ABIS = {"arm64-v8a": "aarch64-linux-android", "x86_64": "x86_64-linux-android"}
API = 24
BT, PLAT = "34.0.0", "android-34"
CHAQUOPY = os.environ.get("CHAQUOPY_INDEX", "https://chaquo.com/pypi-13.1/")


def log(m): print(f"[factory] {m}", flush=True)
def run(cmd, **kw):
    cmd = [str(c) for c in cmd]; log("$ " + " ".join(cmd)[:200])
    if subprocess.run(cmd, **kw).returncode:
        raise SystemExit(f"başarısız: {cmd[0]}")


def tags(py):  # "3.13" -> ("3.13", "313", "cp313")
    xy = ".".join(py.split(".")[:2]); n = xy.replace(".", "")
    return xy, n, f"cp{n}"


def sdk_root():
    return Path(os.environ.get("ANDROID_HOME") or os.environ["ANDROID_SDK_ROOT"])


# --------------------------------------------------------------------------- runtime
RUNNER_C = r'''#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <jni.h>
#include <pthread.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <android/log.h>

static JavaVM *vm; static jobject act; static jmethodID mid; static int pfd[2];

JNIEXPORT jint JNI_OnLoad(JavaVM *v, void *r) { vm = v; return JNI_VERSION_1_6; }

static void *pump(void *arg) {
    JNIEnv *env; char buf[4096]; ssize_t n;
    (*vm)->AttachCurrentThread(vm, &env, NULL);
    while ((n = read(pfd[0], buf, sizeof buf)) > 0) {
        __android_log_print(ANDROID_LOG_INFO, "pyapk", "%.*s", (int)n, buf);
        jbyteArray b = (*env)->NewByteArray(env, (jsize)n);
        (*env)->SetByteArrayRegion(env, b, 0, (jsize)n, (jbyte *)buf);
        (*env)->CallVoidMethod(env, act, mid, b);
        (*env)->DeleteLocalRef(env, b);
    }
    return NULL;
}

JNIEXPORT void JNICALL Java_pyapk_runtime_MainActivity_nativeRun(JNIEnv *env, jobject self, jstring jhome, jstring jcache) {
    const char *home = (*env)->GetStringUTFChars(env, jhome, 0);
    const char *cache = (*env)->GetStringUTFChars(env, jcache, 0);
    char app[2048];
    act = (*env)->NewGlobalRef(env, self);
    mid = (*env)->GetMethodID(env, (*env)->GetObjectClass(env, self), "onOutput", "([B)V");
    if (pipe(pfd) == 0) {
        pthread_t t; dup2(pfd[1], 1); dup2(pfd[1], 2);
        pthread_create(&t, 0, pump, 0); pthread_detach(t);
    }
    snprintf(app, sizeof app, "%s/app", home);
    setenv("HOME", home, 1); setenv("TMPDIR", cache, 1); setenv("PYTHONPATH", app, 1);
    PyConfig cfg; PyConfig_InitPythonConfig(&cfg);
    cfg.buffered_stdio = 0; cfg.install_signal_handlers = 0;
    PyStatus st = PyConfig_SetBytesString(&cfg, &cfg.home, home);
    if (!PyStatus_Exception(st)) st = Py_InitializeFromConfig(&cfg);
    PyConfig_Clear(&cfg);
    if (PyStatus_Exception(st)) { dprintf(2, "Python baslatilamadi: %s\n", st.err_msg ? st.err_msg : "?"); return; }
    PyRun_SimpleString("import _pyapk_boot");
}
'''

MAIN_JAVA = r'''package pyapk.runtime;

import android.app.Activity;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.*;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.util.zip.*;

public class MainActivity extends Activity {
    static { System.loadLibrary("@PYLIB@"); System.loadLibrary("pyrunner"); }
    static boolean started;
    TextView tv; ScrollView sv; WebView web;
    boolean webMode; int port = 5000;

    native void nativeRun(String home, String cache);

    public void onOutput(byte[] b) {
        final String s = new String(b, java.nio.charset.StandardCharsets.UTF_8);
        runOnUiThread(() -> { tv.append(s); sv.post(() -> sv.fullScroll(View.FOCUS_DOWN)); });
    }

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        try {
            ApplicationInfo ai = getPackageManager().getApplicationInfo(getPackageName(), PackageManager.GET_META_DATA);
            if (ai.metaData != null) {
                webMode = "webview".equals(String.valueOf(ai.metaData.get("py2apk.mode")));
                Object p = ai.metaData.get("py2apk.port");
                if (p != null) port = Integer.parseInt(String.valueOf(p));
            }
        } catch (Exception e) { }
        sv = new ScrollView(this); tv = new TextView(this);
        tv.setTypeface(Typeface.MONOSPACE); tv.setTextSize(13); tv.setPadding(24, 64, 24, 24);
        tv.setTextIsSelectable(true);
        sv.addView(tv);
        FrameLayout root = new FrameLayout(this);
        root.addView(sv, new FrameLayout.LayoutParams(-1, -1));
        if (webMode) {
            web = new WebView(this);
            web.setVisibility(View.GONE);
            WebSettings ws = web.getSettings();
            ws.setJavaScriptEnabled(true); ws.setDomStorageEnabled(true);
            web.setWebViewClient(new WebViewClient());
            web.setWebChromeClient(new WebChromeClient());
            root.addView(web, new FrameLayout.LayoutParams(-1, -1));
        }
        setContentView(root);
        if (!started) {
            started = true;
            new Thread(null, () -> {
                try {
                    File home = new File(getFilesDir(), "pyhome");
                    unpack(home);
                    nativeRun(home.getAbsolutePath(), getCacheDir().getAbsolutePath());
                } catch (Throwable t) {
                    onOutput(android.util.Log.getStackTraceString(t).getBytes());
                }
            }, "python", 32L << 20).start();
        }
        if (webMode) new Thread(this::waitForServer, "py2apk-wait").start();
    }

    // Python sunucusu portu açınca WebView'ı göster; açılmazsa günlük (hata) ekranda kalır.
    void waitForServer() {
        long end = System.currentTimeMillis() + 180000;
        while (System.currentTimeMillis() < end) {
            try (Socket s = new Socket()) {
                s.connect(new InetSocketAddress("127.0.0.1", port), 400);
                runOnUiThread(() -> {
                    sv.setVisibility(View.GONE); web.setVisibility(View.VISIBLE);
                    web.loadUrl("http://127.0.0.1:" + port + "/");
                });
                return;
            } catch (IOException e) {
                try { Thread.sleep(400); } catch (InterruptedException ie) { return; }
            }
        }
    }

    @Override public void onBackPressed() {
        if (web != null && web.getVisibility() == View.VISIBLE && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override protected void onDestroy() {
        super.onDestroy();
        if (isFinishing()) System.exit(0);
    }

    void unpack(File home) throws IOException {
        String stamp;
        try { stamp = String.valueOf(getPackageManager().getPackageInfo(getPackageName(), 0).lastUpdateTime); }
        catch (Exception e) { throw new IOException(e); }
        File stampFile = new File(home, ".stamp");
        if (stampFile.exists()) {
            try (BufferedReader r = new BufferedReader(new FileReader(stampFile))) {
                if (stamp.equals(r.readLine())) return;
            }
        }
        delete(home); home.mkdirs();
        InputStream in = null;
        for (String abi : Build.SUPPORTED_ABIS) {
            try { in = getAssets().open("pyhome-" + abi + ".zip"); break; } catch (IOException e) { }
        }
        if (in == null) throw new IOException("Bu cihazin ABI'si icin paket yok");
        String root = home.getCanonicalPath() + File.separator;
        try (ZipInputStream z = new ZipInputStream(new BufferedInputStream(in))) {
            ZipEntry e; byte[] buf = new byte[65536];
            while ((e = z.getNextEntry()) != null) {
                File f = new File(home, e.getName());
                if (!f.getCanonicalPath().startsWith(root)) continue;
                if (e.isDirectory()) { f.mkdirs(); continue; }
                f.getParentFile().mkdirs();
                try (FileOutputStream o = new FileOutputStream(f)) {
                    int n; while ((n = z.read(buf)) > 0) o.write(buf, 0, n);
                }
            }
        }
        try (FileWriter w = new FileWriter(stampFile)) { w.write(stamp); }
    }

    static void delete(File f) {
        File[] kids = f.listFiles();
        if (kids != null) for (File k : kids) delete(k);
        f.delete();
    }
}
'''


def zip_dir(src: Path, dest: Path):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(src).as_posix())


def cmd_runtime(a):
    full = a.py; xy, _, tag = tags(full)
    out = Path(a.out) / "runtime"; out.mkdir(parents=True, exist_ok=True)
    work = Path("work"); work.mkdir(exist_ok=True)
    tgz = work / f"Python-{full}.tgz"
    if not tgz.exists():
        urllib.request.urlretrieve(f"https://www.python.org/ftp/python/{full}/Python-{full}.tgz", tgz)
    src = work / f"Python-{full}"
    if not src.exists():
        with tarfile.open(tgz) as t:
            t.extractall(work)
    # CPython'un kendi Android betiği (NDK sürümünü kendisi belirler)
    ndk_ver = re.search(r"ndk_version=([\w.]+)", (src / "Android" / "android-env.sh").read_text()).group(1)
    sdk = sdk_root(); sm = sdk / "cmdline-tools" / "latest" / "bin" / "sdkmanager"
    run([sm, f"--sdk_root={sdk}", f"ndk;{ndk_ver}", f"build-tools;{BT}", f"platforms;{PLAT}"],
        input="y\n" * 50, text=True)
    os.environ["ANDROID_HOME"] = str(sdk)
    ndk = sdk / "ndk" / ndk_ver / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64"

    for abi, triple in ABIS.items():
        run([sys.executable, "Android/android.py", "build", triple], cwd=src)
        prefix = src / "cross-build" / triple / "prefix"
        stage = out / "stage" / abi; shutil.rmtree(stage, ignore_errors=True)
        libs, home = stage / "libs", stage / "home"; libs.mkdir(parents=True)
        for so in (prefix / "lib").glob("*.so"):          # libpython + openssl/sqlite/ffi... (hepsi *.so)
            shutil.copy(so.resolve(), libs / so.name)
        shutil.copytree(prefix / "lib" / f"python{xy}", home / "lib" / f"python{xy}", ignore=shutil.ignore_patterns(
            "test", "tests", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3", "__pycache__",
            "config-*", "*.a", "site-packages"))
        run([ndk / "bin" / f"{triple}{API}-clang", "-shared", "-fPIC", "-O2", "-o", libs / "libpyrunner.so",
             _write(stage / "pyrunner.c", RUNNER_C), f"-I{prefix}/include/python{xy}", f"-L{prefix}/lib",
             f"-lpython{xy}", "-llog", "-Wl,-z,max-page-size=16384"])
        for so in list(libs.glob("*.so")) + list((home / "lib" / f"python{xy}" / "lib-dynload").glob("*.so")):
            subprocess.run([str(ndk / "bin" / "llvm-strip"), "--strip-unneeded", str(so)])
        (stage / "pyrunner.c").unlink()
        zip_dir(stage, out / f"runtime-{tag}-{abi}.zip")

    # JNI'li Java etkinliği -> classes.dex (tüm ABI'ler için ortak)
    jdir = work / "java" / "pyapk" / "runtime"; jdir.mkdir(parents=True, exist_ok=True)
    (jdir / "MainActivity.java").write_text(MAIN_JAVA.replace("@PYLIB@", f"python{xy}"))
    classes = work / "classes"; shutil.rmtree(classes, ignore_errors=True); classes.mkdir()
    jar = sdk / "platforms" / PLAT / "android.jar"
    run(["javac", "--release", "8", "-classpath", jar, "-d", classes, jdir / "MainActivity.java"])
    dexdir = work / "dex"; shutil.rmtree(dexdir, ignore_errors=True); dexdir.mkdir()
    run([sdk / "build-tools" / BT / "d8", "--lib", jar, "--release", "--min-api", API, "--output", dexdir,
         *map(str, classes.rglob("*.class"))])
    shutil.copy(dexdir / "classes.dex", out / f"classes-{tag}.dex")
    (out / "meta.json").write_text(json.dumps({"py": xy, "tag": tag, "abis": list(ABIS)}))
    shutil.rmtree(out / "stage")


def _write(p: Path, text: str) -> Path:
    p.write_text(text); return p


# --------------------------------------------------------------------------- wheel'ler
def pip_cmd(name, abi, xy, dest, built):
    n = xy.replace(".", "")
    cmd = [sys.executable, "-m", "pip", "download", name, "-d", str(dest), "--only-binary=:all:",
           "--implementation", "cp", "--python-version", xy, "--abi", f"cp{n}", "--disable-pip-version-check",
           "--extra-index-url", CHAQUOPY, "--find-links", str(built)]
    for api in range(21, API + 1):
        cmd += ["--platform", f"android_{api}_{abi.replace('-', '_')}"]
    return cmd


def build_from_sdist(pkg, built, tag):
    log(f"sdist'ten derleniyor (cibuildwheel android): {pkg}")
    tmp = Path(tempfile.mkdtemp())
    run([sys.executable, "-m", "pip", "download", pkg, "--no-deps", "--no-binary", ":all:", "-d", tmp,
         "--disable-pip-version-check"])
    sd = next(p for p in tmp.iterdir())
    srcdir = tmp / "src"; srcdir.mkdir()
    if sd.suffix == ".zip":
        zipfile.ZipFile(sd).extractall(srcdir)
    else:
        with tarfile.open(sd) as t:
            t.extractall(srcdir)
    pkgdir = next(srcdir.iterdir())
    env = {**os.environ, "CIBW_BUILD": f"{tag}-*", "CIBW_ARCHS": "arm64_v8a x86_64"}
    run([sys.executable, "-m", "cibuildwheel", "--platform", "android", "--output-dir", built, pkgdir], env=env)


def resolve(name, abi, xy, dest, built, tag, tried, allow_build=True):
    for _ in range(10):
        p = subprocess.run(pip_cmd(name, abi, xy, dest, built), capture_output=True, text=True)
        if p.returncode == 0:
            return
        m = (re.search(r"No matching distribution found for ([A-Za-z0-9_.\-]+)", p.stderr)
             or re.search(r"satisfies the requirement ([A-Za-z0-9_.\-]+)", p.stderr))
        if not m or m.group(1).lower() in tried:
            raise RuntimeError(p.stderr.strip()[-500:])
        if not allow_build:
            raise RuntimeError(f"hazır Android wheel yok: {m.group(1)}")
        tried.add(m.group(1).lower())
        build_from_sdist(m.group(1), built, tag)
    raise RuntimeError("çözümleme döngüsü bitmedi")


def wheel_one(name, xy, tag, out):
    out = Path(out) / name; shutil.rmtree(out, ignore_errors=True)
    (out / "wheels").mkdir(parents=True)
    result = {"name": name}
    built = out / "built"; built.mkdir(); tried = set(); files = {}
    try:
        for abi in ABIS:
            dest = out / "dl" / abi; dest.mkdir(parents=True)
            resolve(name, abi, xy, dest, built, tag, tried, allow_build=name not in NO_BUILD)
            files[abi] = sorted(p.name for p in dest.glob("*.whl"))
            for w in dest.glob("*.whl"):
                shutil.copy(w, out / "wheels" / w.name)
        result["files"] = files
        result["native"] = any("android_" in f for fs in files.values() for f in fs)
    except (Exception, SystemExit) as e:  # run() SystemExit atar; yakalanmazsa iş kırmızı biter, index'e yazılmaz
        msg = str(e).replace("\n", " ")[:260]
        result["failed"] = (GUI_NOTE if name in GUI_NATIVE else "") + msg
        log(f"BAŞARISIZ {name}: {result['failed']}")
    (out / "result.json").write_text(json.dumps(result))
    for d in ("dl", "built"):
        shutil.rmtree(out / d, ignore_errors=True)


def cmd_wheel(a):
    xy, _, tag = tags(a.py)
    names = batches()[a.batch]
    log(f"grup {a.batch}: {names}")
    for name in names:
        wheel_one(name, xy, tag, Path(a.out) / a.batch)


# --------------------------------------------------------------------------- yayın
def cmd_publish(a):
    dist = Path(a.dist); rel = dist / "release"; rel.mkdir(exist_ok=True)
    meta = json.loads(next(dist.glob("**/meta.json")).read_text())
    libs, failed = {}, {}
    for rj in dist.glob("**/result.json"):
        r = json.loads(rj.read_text())
        if "failed" in r:
            failed[norm(r["name"])] = r["failed"]
        else:
            libs[norm(r["name"])] = {"native": r["native"], "files": r["files"]}
        for w in (rj.parent / "wheels").glob("*.whl"):
            shutil.copy(w, rel / w.name)
    for f in list(dist.glob("**/runtime-*.zip")) + list(dist.glob("**/classes-*.dex")):
        shutil.copy(f, rel / f.name)
    index = {**meta, "build": time.strftime("%Y%m%d%H%M%S"), "libs": libs, "failed": failed}
    (rel / "index.json").write_text(json.dumps(index, indent=1))
    tag = meta["tag"]
    subprocess.run(["gh", "release", "create", tag, "--repo", a.repo, "--title", f"PyAPK kütüphaneleri ({tag})",
                    "--notes", "factory.py tarafından otomatik üretildi"])  # varsa hata verir, sorun değil
    files = [str(p) for p in sorted(rel.iterdir())]
    if len(files) > 950:
        log(f"UYARI: {len(files)} dosya var; GitHub release başına 1000 varlık sınırı var")
    for i in range(0, len(files), 40):
        run(["gh", "release", "upload", tag, "--repo", a.repo, "--clobber", *files[i:i + 40]])
    log(f"yayınlandı: {len(libs)} kütüphane hazır, {len(failed)} başarısız -> {sorted(failed)}")


def main():
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("list")
    r = sp.add_parser("runtime"); r.add_argument("--py", default="3.13.5"); r.add_argument("--out", default="dist")
    w = sp.add_parser("wheel"); w.add_argument("batch"); w.add_argument("--py", default="3.13")
    w.add_argument("--out", default="dist")
    p = sp.add_parser("publish"); p.add_argument("--repo", required=True); p.add_argument("--dist", default="dist")
    a = ap.parse_args()
    if a.cmd == "list":
        print(json.dumps(list(batches())))
    else:
        {"runtime": cmd_runtime, "wheel": cmd_wheel, "publish": cmd_publish}[a.cmd](a)


if __name__ == "__main__":
    main()
