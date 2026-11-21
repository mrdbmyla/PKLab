import os
import sys

FROZEN = getattr(sys, "frozen", False)
_APP_RES = (os.environ.get("PKLAB_RES_DIR") or "").replace("\\", "/")
BUNDLED = FROZEN or bool(_APP_RES)
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")


def _base_dir():
    if not BUNDLED:
        return "C:/pkmn" if sys.platform == "win32" else _SRC_DIR
    exe_dir = os.path.dirname(sys.executable) if FROZEN else _APP_RES
    if FROZEN and os.path.isfile(os.path.join(exe_dir, "pklab.html")):
        return exe_dir
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        root = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    d = os.path.join(root, "PKLab")
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except OSError:
        return exe_dir


BASE_DIR = _base_dir().replace("\\", "/")
RES_DIR = _APP_RES or (os.path.join(sys._MEIPASS, "pklab_res").replace("\\", "/") if FROZEN else BASE_DIR)
os.environ["PKLAB_BASE_DIR"] = BASE_DIR


def res(*parts):
    p = os.path.join(BASE_DIR, *parts)
    if os.path.exists(p):
        return p
    return os.path.join(RES_DIR, *parts)

APP_VERSION = "1.2.0"
EXE_DIR = os.path.dirname(sys.executable).replace("\\", "/") if FROZEN else ""
UPDATABLE = FROZEN and sys.platform == "win32" and os.path.normcase(BASE_DIR) != os.path.normcase(EXE_DIR)
MAJ_FILE = os.path.join(BASE_DIR, "maj_installee.json")


def ver_tuple(v):
    import re
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3])


def _drop_light_update():
    import shutil
    for name in ("pklab.html", "mgba_gen3_bridge.lua", "mgba_gen2_bridge.lua", "favicon.png", "maj_installee.json"):
        try:
            os.remove(os.path.join(BASE_DIR, name))
        except OSError:
            pass
    for d in ("data", "boxart"):
        shutil.rmtree(os.path.join(BASE_DIR, d), ignore_errors=True)


def _light_version():
    if not UPDATABLE:
        return APP_VERSION
    if not os.path.isfile(MAJ_FILE):
        if os.path.isfile(os.path.join(BASE_DIR, "pklab.html")) or os.path.isdir(os.path.join(BASE_DIR, "data")):
            _drop_light_update()
        return APP_VERSION
    import json
    try:
        with open(MAJ_FILE, encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        _drop_light_update()
        return APP_VERSION
    if ver_tuple(info.get("version")) <= ver_tuple(APP_VERSION) or ver_tuple(info.get("min_exe")) > ver_tuple(APP_VERSION):
        _drop_light_update()
        return APP_VERSION
    return info.get("version") or APP_VERSION


CURRENT_VERSION = _light_version()
