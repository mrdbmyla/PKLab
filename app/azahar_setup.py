import hashlib
import os
import shutil
import sys
import threading
import urllib.request
import zipfile

VERSION = "2126.2"
URL = f"https://github.com/azahar-emu/azahar/releases/download/{VERSION}/azahar-windows-mxe-{VERSION}.zip"
SHA256 = "dae9f107d9141ebc0e64ba251f9796393aab651cf3437ab9e083b45354624486"
SIZE = 69427557
if sys.platform != "win32":
    URL = f"https://github.com/azahar-emu/azahar/releases/download/{VERSION}/azahar.AppImage"
    SHA256 = "af037f8b775198f636b14bcfe63fb401b02246ebfefe1025bb905ce042556960"
    SIZE = 103684600
EXE = "azahar.exe" if sys.platform == "win32" else "azahar.AppImage"

_lock = threading.Lock()
STATUS = {"state": "idle", "done": 0, "total": SIZE, "error": None}


def installed(dest):
    return os.path.isfile(os.path.join(dest, EXE))


def status():
    with _lock:
        return dict(STATUS)


def _set(**kw):
    with _lock:
        STATUS.update(kw)


def start(dest):
    with _lock:
        if STATUS["state"] in ("downloading", "extracting"):
            return
        STATUS.update(state="downloading", done=0, total=SIZE, error=None)
    threading.Thread(target=_run, args=(dest,), daemon=True).start()


def _run(dest):
    part = dest.rstrip("\\/") + ("_telechargement.zip" if sys.platform == "win32" else "_telechargement.AppImage")
    tmp = dest.rstrip("\\/") + "_extraction"
    try:
        h = hashlib.sha256()
        req = urllib.request.Request(URL, headers={"User-Agent": "PKLab"})
        with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
            done = 0
            while True:
                block = r.read(1 << 16)
                if not block:
                    break
                f.write(block)
                h.update(block)
                done += len(block)
                _set(done=done)
        if h.hexdigest() != SHA256:
            raise ValueError("fichier téléchargé invalide (empreinte différente)")
        _set(state="extracting")
        if sys.platform != "win32":
            os.makedirs(os.path.join(dest, "user"), exist_ok=True)
            os.chmod(part, 0o755)
            os.replace(part, os.path.join(dest, EXE))
            _set(state="done")
            return
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(part) as z:
            for info in z.infolist():
                target = os.path.normpath(os.path.join(tmp, info.filename))
                if not target.startswith(os.path.normpath(tmp) + os.sep):
                    raise ValueError("archive invalide")
            z.extractall(tmp)
        roots = os.listdir(tmp)
        src = os.path.join(tmp, roots[0]) if len(roots) == 1 and os.path.isdir(os.path.join(tmp, roots[0])) else tmp
        if not os.path.isfile(os.path.join(src, "azahar.exe")):
            raise ValueError("azahar.exe absent de l'archive")
        os.makedirs(dest, exist_ok=True)
        for name in os.listdir(src):
            target = os.path.join(dest, name)
            if os.path.isdir(target):
                shutil.rmtree(target)
            elif os.path.exists(target):
                os.remove(target)
            shutil.move(os.path.join(src, name), target)
        os.makedirs(os.path.join(dest, "user"), exist_ok=True)
        _set(state="done")
    except Exception as e:
        _set(state="error", error=str(e))
    finally:
        for p in (part,):
            try:
                os.remove(p)
            except OSError:
                pass
        shutil.rmtree(tmp, ignore_errors=True)
