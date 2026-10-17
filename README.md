# py2apk

[Türkçe](README.tr.md)

Turn a Python script into an Android APK, from a simple desktop GUI.
No Docker, no WSL, no compiler on your machine, and it runs on Windows, macOS and Linux.

```
pip install py2apk
py2apk
```

Pick your `.py` file, choose an app type, press **Build APK**. That's it.

## How it works

py2apk is split in two parts so that you never have to compile anything:

1. **The factory** (`factory.py` + a GitHub Actions workflow) runs once on GitHub.
   It cross-compiles CPython for Android (arm64-v8a and x86_64), builds the Android
   wheels for a set of popular libraries (Flask, NumPy, pandas, Pillow, ...), and
   publishes everything as a GitHub Release.
2. **The tool** (`py2apk.py`, the GUI you run) downloads those ready-made pieces,
   scans your imports, bundles your code and the libraries it needs, writes the
   Android manifest, and packages and signs the APK.

The only things downloaded on your machine are a JDK 17 and the Android build-tools
(if you don't already have them), kept in `~/.py2apk`.

## Install

From PyPI (once published):

```
pip install py2apk
```

Straight from GitHub (works today):

```
pip install git+https://github.com/TwoPlasmaStudios/py2apk.git
```

Requirements: Python 3.10+ with tkinter. The Windows and macOS installers from
python.org include tkinter. On Debian/Ubuntu: `sudo apt install python3-tk`.
Optional: `pip install py2apk[icon]` (Pillow) to use JPG/WebP logos and get a sharp preview.

**`py2apk` is not recognized?** On Windows, `pip install` often puts the launcher in a `Scripts`
folder that is not on your PATH. Run it with `python -m py2apk` (or `py -m py2apk`) instead.
py2apk also offers to add that folder to your PATH the first time the window opens, or you can run
`python -m py2apk --add-to-path` once and open a new terminal.

## Use it

```
py2apk                 # opens the GUI
py2apk path/to/app.py  # opens the GUI with a file preselected
```

1. **Python file**: your entry script. Other `.py` files and packages next to it are
   included automatically, so keep the project in its own folder.
2. **App**: name, package name (e.g. `com.me.myapp`), version and an optional logo.
3. **App type**: see below.
4. **Libraries**: detected from your imports. Each one shows whether a ready-made
   Android build exists. Add extra packages in the *Extra packages* field.
5. Press **Build APK**. The first build downloads the JDK and Android tools (several
   hundred MB); later builds are fast. The APK is written next to your script.

Install it with `adb install MyApp-1.0.apk` or copy it to the phone and open it
(allow installs from unknown sources). The APK is signed with a debug key, which is
fine for testing and sideloading but not for Google Play.

### App types

| Type | Status | What you get |
|---|---|---|
| **Console** | works | `print()` output is shown on screen. For scripts, bots, calculations. No `input()`. |
| **Web UI** | works | Run Flask/FastAPI/etc. in your script. The app opens it full screen in a WebView. |
| **Pygame / Games** | beta (in development) | Needs an SDL2 runtime. Not selectable yet. |
| **Kivy** | beta (in development) | Needs an SDL2 runtime. Not selectable yet. |

Tkinter does not exist on Android. Use the **Web UI** type for graphical apps.

#### Web UI example

```python
import os
from flask import Flask

app = Flask(__name__)

@app.get("/")
def index():
    return "<h1>Hello from Android!</h1>"

app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
```

Keep `debug=False` (the reloader starts a second process, which Android won't allow) and
listen on `127.0.0.1`. The port is set in the GUI and passed to your code as `PORT`.
If the server fails to start, the app shows the Python traceback instead of a blank page.

## Libraries

The factory builds Android wheels for a fixed list of popular packages
(see `LIBS` in `factory.py`), plus all of their dependencies. Pure-Python packages
work as they are. Packages with C extensions only work if an Android build exists.

* Packages in the Release are used first.
* Anything else is tried from PyPI (pure-Python or Android wheels) with `pip`.
* If nothing is found you get a warning in the log and the package is skipped.

Which libraries are available changes as the factory improves: open the
`index.json` asset of the Release (or look at the status column in the GUI).
Some heavy packages (SciPy, scikit-learn, OpenCV, anything needing Rust or Fortran
toolchains) are the hardest to cross-compile and may be marked as failed.

## Run your own factory

Fork the repository, enable Actions, give the workflow write access
(*Settings -> Actions -> General -> Workflow permissions -> Read and write*), then run
**Actions -> factory -> Run workflow**. When it finishes, a release tagged `cp313` appears.
Point the tool at your fork:

```
# Windows (PowerShell)
$env:PY2APK_REPO = "you/your-fork"
# macOS / Linux
export PY2APK_REPO=you/your-fork
```

Or use *Advanced -> GitHub repository* inside the GUI.

## Environment variables

| Variable | Meaning |
|---|---|
| `PY2APK_REPO` | GitHub `owner/repo` that hosts the Release (default `TwoPlasmaStudios/py2apk`) |
| `PY2APK_HOME` | Cache folder (default `~/.py2apk`) |
| `PY2APK_PY` | Release tag, i.e. the Python version (default `cp313`) |

## Troubleshooting

* **"Library index could not be fetched"**: the repository must be public and the factory
  must have finished at least once.
* **App crashes or shows a traceback**: run `adb logcat -s pyapk` while opening it.
* **Import error for a native library**: that package has no Android build yet. Check its
  status in the GUI.
* **Build fails while downloading tools**: check your connection; downloads resume from the cache.

## Limitations

* Python 3.13 runtime, arm64-v8a and x86_64 only, minimum Android 7.0 (API 24).
* Pygame and Kivy are still in beta development and cannot be used yet; tkinter does not exist on Android.
* Console apps have no interactive input.
* Debug-signed APKs only.

## Publishing to PyPI (maintainers)

Releases are published by `.github/workflows/publish.yml` with PyPI Trusted Publishing
(no API token needed). It only runs for tags that start with `v`, so the `cp313` release
created by the factory never triggers it.

One-time setup:

1. Check that the name is free: https://pypi.org/project/py2apk/ should return 404.
2. On pypi.org: *Your projects -> Publishing -> Add a new pending publisher* with
   project `py2apk`, owner `TwoPlasmaStudios`, repository `py2apk`,
   workflow `publish.yml`, environment `pypi`.
3. On GitHub: *Settings -> Environments -> New environment* named `pypi`.

Each release: bump `version` in `pyproject.toml`, then

```
git tag v0.3.0
git push origin v0.3.0
```

Manual alternative: `pip install build twine`, `python -m build`, `twine upload dist/*`
(use an API token, username `__token__`).

## License

MIT. Libraries in the Release keep their own licenses; CPython is under the PSF license.
