import hashlib
import io
import json
import os
import shutil
import urllib.request
import zipfile

import paths

ZIP_NAME = "PKLab-maj.zip"
MAX_ZIP = 150 * 1024 * 1024
ALLOWED_FILES = ("pklab.html", "mgba_gen3_bridge.lua", "mgba_gen2_bridge.lua", "favicon.png")
ALLOWED_DIRS = ("data/", "boxart/")


def allowed_path(rel):
    if not rel or rel.startswith(("/", "\\")) or "\\" in rel or ":" in rel:
        return False
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return False
    return rel in ALLOWED_FILES or (rel.startswith(ALLOWED_DIRS) and len(parts) >= 2)


def _download(url, digest):
    req = urllib.request.Request(url, headers={"User-Agent": "PKLab", "Accept": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read(MAX_ZIP + 1)
    if len(data) > MAX_ZIP:
        raise ValueError("Fichier de mise à jour trop gros")
    if digest and digest.startswith("sha256:"):
        if hashlib.sha256(data).hexdigest() != digest[7:].lower():
            raise ValueError("Fichier de mise à jour corrompu (empreinte différente)")
    return data


def apply_light_update(url, digest, expected_version):
    if not paths.UPDATABLE:
        return {"ok": False, "needExe": True, "error": "Mise à jour légère impossible avec cette installation"}
    try:
        data = _download(url, digest)
    except Exception as e:
        msg = str(e) if isinstance(e, ValueError) else "Téléchargement impossible"
        return {"ok": False, "error": msg}
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        man = json.loads(zf.read("manifest.json").decode("utf-8"))
    except Exception:
        return {"ok": False, "error": "Fichier de mise à jour illisible"}
    version = str(man.get("version") or "")
    min_exe = str(man.get("min_exe") or "")
    files = man.get("files") or {}
    if paths.ver_tuple(version) != paths.ver_tuple(expected_version) or not files:
        return {"ok": False, "error": "Fichier de mise à jour incohérent"}
    if paths.ver_tuple(min_exe) > paths.ver_tuple(paths.APP_VERSION):
        return {"ok": False, "needExe": True, "error": "Cette mise à jour demande le nouveau PKLab.exe"}
    names = set(zf.namelist())
    for rel, h in files.items():
        if not allowed_path(rel) or rel not in names:
            return {"ok": False, "error": "Fichier de mise à jour refusé : " + rel}
        if hashlib.sha256(zf.read(rel)).hexdigest() != str(h).lower():
            return {"ok": False, "error": "Fichier de mise à jour corrompu : " + rel}
    base = paths.BASE_DIR
    tmp = os.path.join(base, "_maj_tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        for rel in files:
            dst = os.path.join(tmp, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(zf.read(rel))
        old = {}
        if os.path.isfile(paths.MAJ_FILE):
            try:
                with open(paths.MAJ_FILE, encoding="utf-8") as f:
                    old = json.load(f)
            except (OSError, ValueError):
                old = {}
        for rel in old.get("files") or []:
            if rel not in files and allowed_path(rel):
                try:
                    os.remove(os.path.join(base, *rel.split("/")))
                except OSError:
                    pass
        for rel in files:
            dst = os.path.join(base, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(os.path.join(tmp, *rel.split("/")), dst)
        with open(paths.MAJ_FILE, "w", encoding="utf-8") as f:
            json.dump({"version": version, "min_exe": min_exe, "files": sorted(files)}, f, ensure_ascii=False, indent=1)
    except OSError:
        return {"ok": False, "error": "Écriture impossible dans le dossier de PKLab"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"ok": True, "version": version}


EXE_NAME = "PKLab.exe"
MIN_EXE_SIZE = 20 * 1024 * 1024
MAX_EXE_SIZE = 400 * 1024 * 1024


def apply_exe_update(url, digest):
    import sys
    if not paths.UPDATABLE:
        return {"ok": False, "needPage": True, "error": "Mise à jour automatique impossible avec cette installation"}
    if not (digest or "").startswith("sha256:"):
        return {"ok": False, "needPage": True, "error": "Empreinte du nouvel exe absente"}
    exe = sys.executable
    new, old = exe + ".new", exe + ".old"
    h = hashlib.sha256()
    size = 0
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PKLab", "Accept": "application/octet-stream"})
        with urllib.request.urlopen(req, timeout=60) as r, open(new, "wb") as f:
            first = b""
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                if not first:
                    first = chunk[:2]
                size += len(chunk)
                if size > MAX_EXE_SIZE:
                    raise ValueError("Fichier de mise à jour trop gros")
                h.update(chunk)
                f.write(chunk)
    except PermissionError:
        _rm(new)
        return {"ok": False, "needPage": True, "error": "Écriture impossible dans le dossier de PKLab"}
    except Exception as e:
        _rm(new)
        return {"ok": False, "error": str(e) if isinstance(e, ValueError) else "Téléchargement impossible"}
    if h.hexdigest() != digest[7:].lower() or first != b"MZ" or size < MIN_EXE_SIZE:
        _rm(new)
        return {"ok": False, "error": "Fichier de mise à jour corrompu (empreinte différente)"}
    _rm(old)
    try:
        os.replace(exe, old)
    except OSError:
        _rm(new)
        return {"ok": False, "needPage": True, "error": "Remplacement de PKLab.exe impossible"}
    try:
        os.replace(new, exe)
    except OSError:
        os.replace(old, exe)
        _rm(new)
        return {"ok": False, "needPage": True, "error": "Remplacement de PKLab.exe impossible"}
    return {"ok": True, "exe": True}


def _rm(p):
    try:
        os.remove(p)
    except OSError:
        pass


def cleanup_old_exe(wait_pid=None):
    import sys
    import time
    if wait_pid:
        import ctypes
        k = ctypes.windll.kernel32
        hp = k.OpenProcess(0x00100000, False, int(wait_pid))
        if hp:
            k.WaitForSingleObject(hp, 30000)
            k.CloseHandle(hp)
    if not paths.FROZEN:
        return
    old = sys.executable + ".old"
    for _ in range(20):
        if not os.path.exists(old):
            break
        _rm(old)
        time.sleep(0.25)
    _rm(sys.executable + ".new")


def restart_command():
    import sys
    env = {k: v for k, v in os.environ.items() if not k.startswith(("_PYI", "_MEIPASS")) and k != "PKLAB_BASE_DIR"}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return [sys.executable, "--wait-pid", str(os.getpid())], env
