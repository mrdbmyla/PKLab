import atexit
import ctypes
import ctypes.wintypes as wintypes
import http.server
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from pycaw.pycaw import AudioUtilities
    _PYCAW_AVAILABLE = True
except Exception:
    _PYCAW_AVAILABLE = False

import paths
from nds_mem import NdsMemory, NdsEmulatorNotFound
from games import GAMES
import engine
import gen3_engine
from nds_reader import NdsReader
import gen3_maps
import gen2_maps
import gen4_maps
import gen5_maps
import randomizer
import randomizer_gen6
import randomizer_gen7
import save_editor
import shiny_patch
import updater
import i18n
import rom_finder
import azahar_reader
import azahar_setup
import ctr_maps

from paths import BASE_DIR, res
HACKMODE_OVERRIDE_PATH = os.path.join(BASE_DIR, "hackmode_override.txt")
DETECTION_LOG_PATH = os.path.join(BASE_DIR, "detection.log")
PORT = 8731

GEN3_RAW_PATH = os.path.join(BASE_DIR, "gen3_raw.json")
GEN3_RAW_FRESH_SECONDS = 2.0
GEN3_CODE_PREFIX_TO_KEY = {
    "BPE": "EMERALD", "BPR": "FIRERED", "BPG": "LEAFGREEN",
    "AXV": "RUBY", "AXP": "SAPPHIRE",
}

POLL_INTERVAL = 0.15
HEARTBEAT_INTERVAL = 0.5
NDS_LOCATE_INTERVAL = 0.5
NDS_LOST_GRACE_S = 3.0
PLAYER_EMPTY_STREAK_TO_CLEAR = 4


_GEN3_LAST_RAW = None


def read_gen3_raw():
    global _GEN3_LAST_RAW
    try:
        st = os.stat(GEN3_RAW_PATH)
    except OSError:
        return None
    if time.time() - st.st_mtime > GEN3_RAW_FRESH_SECONDS:
        return None
    key = (st.st_mtime_ns, st.st_size)
    if _GEN3_LAST_RAW is not None and _GEN3_LAST_RAW[0] == key:
        return _GEN3_LAST_RAW[1]
    for _ in range(3):
        try:
            with open(GEN3_RAW_PATH, "r", encoding="utf-8") as f:
                _GEN3_LAST_RAW = (key, json.load(f))
            return _GEN3_LAST_RAW[1]
        except Exception:
            time.sleep(0.01)
    return _GEN3_LAST_RAW[1] if _GEN3_LAST_RAW else None


def gen3_game_key_from_code(code):
    if not code:
        return None
    if code.startswith("GEN2:"):
        return code[5:] or None
    code = code.replace("AGB-", "")
    return GEN3_CODE_PREFIX_TO_KEY.get(code[:3])


GBC_EXTS = (".gbc", ".gb")
MGBA_SCRIPT_PATH = res("mgba_gen3_bridge.lua")
MGBA_GEN2_SCRIPT_PATH = res("mgba_gen2_bridge.lua")
GEN2_ROM_PATH = None


def gbc_game_key(path):
    found = rom_finder.identify(path) if path and path.lower().endswith(GBC_EXTS) else None
    return found[1] if found else None


def gen2_rom_for(game_key):
    if GEN2_ROM_PATH and os.path.isfile(GEN2_ROM_PATH) and gbc_game_key(GEN2_ROM_PATH) == game_key:
        return GEN2_ROM_PATH
    return next((r["path"] for r in ROM_INDEX.roms("mgba") if r["game"] == game_key and os.path.isfile(r["path"])), None)
ROM_SCAN_DIRS = [os.path.join(os.path.expanduser("~"), d) for d in ("Downloads", "Desktop", "Documents")]
ROM_INDEX = rom_finder.RomIndex(os.path.join(BASE_DIR, "rom_index.json"), ROM_SCAN_DIRS)


def rom_scan_dirs():
    return ROM_INDEX.dirs()

EMULATOR_BUNDLES = {
    "melonds": {
        "label": "melonDS",
        "bundle_dir": "melonds_bundle",
        "exe_name": "melonDS.exe",
        "extra_files": [],
        "rom_ext": ".nds",
        "needs_script": False,
    },
    "mgba": {
        "label": "mGBA",
        "bundle_dir": "mgba_bundle",
        "exe_name": "mGBA.exe",
        "extra_files": [],
        "rom_ext": ".gba",
        "rom_exts": [".gba", ".gbc", ".gb"],
        "needs_script": True,
    },
    "azahar": {
        "label": "Azahar",
        "bundle_dir": None,
        "exe_name": "azahar.exe",
        "extra_files": [],
        "rom_ext": ".3ds",
        "rom_exts": [".3ds", ".cci", ".cxi"],
        "needs_script": False,
    },
}
AZAHAR_DIR = os.path.join(BASE_DIR, "azahar")
AZAHAR_SAVE_DIR = ("user", "sdmc", "Nintendo 3DS", "0" * 32, "0" * 32, "title", "00040000")


def _prepare_azahar_config():
    os.makedirs(os.path.join(AZAHAR_DIR, "user", "config"), exist_ok=True)
    ini = os.path.join(AZAHAR_DIR, "user", "config", "qt-config.ini")
    _ini_set(ini, "[Debugging]", {"enable_rpc_server\\default": "false", "enable_rpc_server": "true"})
    _ini_set(ini, "[Renderer]", {"frame_limit\\default": "true", "frame_limit": "100"})
    sc = "Shortcuts\\Main%20Window\\Quick%20"
    _ini_set(ini, "[UI]", {"confirmClose\\default": "false", "confirmClose": "false",
                           sc + "Save\\KeySeq\\default": "false", sc + "Save\\KeySeq": "Shift+F1",
                           sc + "Load\\KeySeq\\default": "false", sc + "Load\\KeySeq": "F1"})
    _azahar_any_controller(ini)


def _azahar_any_controller(ini):
    try:
        with open(ini, encoding="utf-8") as f:
            lines = f.read().split("\n")
    except OSError:
        return
    cur, changed = "", False
    for i, line in enumerate(lines):
        t = line.strip()
        if t.startswith("[") and t.endswith("]"):
            cur = t
            continue
        if cur != "[Controls]" or "=" not in t:
            continue
        k, v = t.split("=", 1)
        if k.endswith("input_maptype\\default"):
            nv = "false"
        elif k.endswith("input_maptype"):
            nv = "0"
        elif "engine:sdl" in v or "engine$0sdl" in v:
            nv = re.sub(r"maptype(:|\$0)guid(\+port)?", r"maptype\1all", v)
        else:
            continue
        if nv != v:
            lines[i] = f"{k}={nv}"
            changed = True
    if changed:
        tmp = ini + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(lines))
        os.replace(tmp, ini)


def _ctr_title_id(rom_path):
    try:
        with open(rom_path, "rb") as f:
            h = f.read(0x120)
    except OSError:
        return None
    return int.from_bytes(h[0x108:0x110] if h[0x100:0x104] == b"NCSD" else h[0x118:0x120], "little")


def azahar_has_save(rom_path):
    tid = _ctr_title_id(rom_path)
    if not tid:
        return False
    return os.path.isfile(os.path.join(AZAHAR_DIR, *AZAHAR_SAVE_DIR, f"{tid & 0xFFFFFFFF:08x}", "data", "00000001", "main"))


def _ini_set(path, section, values):
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
    except OSError:
        lines = []
    todo = dict(values)
    cur, insert_at, changed = "", None, False
    for i, line in enumerate(lines):
        t = line.strip()
        if t.startswith("[") and t.endswith("]"):
            if cur == section and insert_at is None:
                insert_at = i
            cur = t
            continue
        if cur == section and "=" in t:
            k = t.split("=", 1)[0].strip()
            if k in todo:
                if t != f"{k}={todo[k]}":
                    lines[i] = f"{k}={todo[k]}"
                    changed = True
                del todo[k]
    if todo:
        add = [f"{k}={v}" for k, v in todo.items()]
        if cur == section and insert_at is None:
            while lines and not lines[-1].strip():
                lines.pop()
            lines += add + [""]
        elif insert_at is not None:
            lines[insert_at:insert_at] = add
        else:
            while lines and not lines[-1].strip():
                lines.pop()
            lines += ["", section] + add + [""]
        changed = True
    if changed:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except OSError:
            pass


def _prepare_mgba_config():
    base = os.path.join(os.environ.get("APPDATA") or "", "mGBA")
    if not os.path.isdir(base):
        return
    _ini_set(os.path.join(base, "config.ini"), "[ports.qt]", {"mute": "0"})


def _bridge_script(rom_path=""):
    script = MGBA_GEN2_SCRIPT_PATH if (rom_path or "").lower().endswith(GBC_EXTS) else MGBA_SCRIPT_PATH
    if BASE_DIR.rstrip("/").lower() == "c:/pkmn":
        return script
    try:
        with open(script, encoding="utf-8") as f:
            src = f.read()
        out = os.path.join(BASE_DIR, os.path.splitext(os.path.basename(script))[0] + "_run.lua")
        with open(out, "w", encoding="utf-8") as f:
            f.write(src.replace("C:/pkmn/", BASE_DIR.rstrip("/") + "/"))
        return out
    except OSError:
        return script


def _resource_path(relative_path):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)


def _ensure_file_extracted(stable_dir, exe_name, bundle_dir, extra_files=()):
    stable_exe = os.path.join(stable_dir, exe_name)
    if os.path.exists(stable_exe):
        return stable_exe
    bundled_exe = _resource_path(os.path.join(bundle_dir, exe_name))
    if not os.path.exists(bundled_exe):
        return None
    os.makedirs(stable_dir, exist_ok=True)
    shutil.copy2(bundled_exe, stable_exe)
    for extra in extra_files:
        src = _resource_path(os.path.join(bundle_dir, extra))
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(stable_dir, extra))
    return stable_exe


def _ensure_bundled_extracted(engine_key):
    cfg = EMULATOR_BUNDLES[engine_key]
    return _ensure_file_extracted(os.path.join(BASE_DIR, engine_key), cfg["exe_name"], cfg["bundle_dir"], cfg["extra_files"])


def scan_roms(engine_key):
    if engine_key not in EMULATOR_BUNDLES:
        return []
    return [r["path"] for r in ROM_INDEX.roms(engine_key)]


def rando_rom_entry(path):
    if not path or not os.path.isfile(path):
        return None
    low = path.lower()
    if low.endswith(".nds"):
        key = gen4_maps._rom_title(path)
        if key in gen5_maps.GAMES or key in randomizer.R4.PATHS4:
            return {"path": path, "game": key, "name": os.path.basename(path), "engine": "melonds"}
    elif low.endswith(".gba"):
        key = randomizer.R3.gba_title(path)
        if key in GBA_RANDO_KEYS and not re.search(r"\((Aleatoire|Aleatorio|Random) \d", os.path.basename(path)) \
                and not os.path.isfile(shiny_patch.side_path(os.path.splitext(path)[0])):
            return {"path": path, "game": GBA_RANDO_KEYS[key], "name": os.path.basename(path), "engine": "mgba"}
    elif low.endswith(GBC_EXTS):
        key = gbc_game_key(path)
        if key and not re.search(r"\((Aleatoire|Aleatorio|Random) \d", os.path.basename(path)) \
                and not os.path.isfile(shiny_patch.side_path(os.path.splitext(path)[0])):
            return {"path": path, "game": key, "name": os.path.basename(path), "engine": "mgba"}
    elif low.endswith(tuple(rom_finder.CTR_EXTS)):
        hit = rom_finder.identify(path)
        tid = _ctr_title_id(path)
        if hit and (hit[1] in randomizer_gen6.FAMILY or hit[1] in randomizer_gen7.FAMILY) and tid and rom_finder.base_tid(tid) == tid:
            return {"path": path, "game": hit[1], "name": os.path.basename(path), "engine": "azahar"}
    return None


RANDO_PICKED = []


def rando_roms():
    out, seen = [], set()
    for path in scan_roms("melonds") + scan_roms("mgba") + scan_roms("azahar") + RANDO_PICKED:
        e = rando_rom_entry(path)
        if e and os.path.normcase(path) not in seen:
            seen.add(os.path.normcase(path))
            out.append(e)
    return out


def rando_pick_rom():
    path = pick_rom_dialog()
    if not path:
        return {"ok": False, "cancelled": True}
    e = rando_rom_entry(path)
    if not e:
        return {"ok": False, "error": "Cette ROM n'est pas prise en charge (Pokémon 2G à 7G d'origine)"}
    if path not in RANDO_PICKED:
        RANDO_PICKED.append(path)
    return {"ok": True, "rom": e}


def rando_out_path(src, name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(name or "")).strip().rstrip(".")
    if not name:
        return None, None
    if len(name) > 100:
        return None, "Nom trop long (100 caractères maximum)"
    out = os.path.join(os.path.dirname(src), name + os.path.splitext(src)[1])
    if os.path.normcase(os.path.abspath(out)) == os.path.normcase(os.path.abspath(src)):
        return None, "Ce nom est celui de la ROM d'origine : choisis-en un autre"
    if os.path.exists(out):
        return None, "Une ROM porte déjà ce nom dans ce dossier : choisis-en un autre"
    return out, None


GBA_RANDO_KEYS = {"POKEMON EMER": "EMERALD", "POKEMON FIRE": "FIRERED", "POKEMON LEAF": "LEAFGREEN",
                  "POKEMON RUBY": "RUBY", "POKEMON SAPP": "SAPPHIRE"}


def run_randomizer(data):
    path = data.get("path") or ""
    roms = {r["path"]: r for r in rando_roms()}
    if path not in roms:
        return {"ok": False, "error": "ROM introuvable ou non prise en charge"}
    options = dict(data.get("options") or {})
    try:
        options["seed"] = int(options["seed"]) if str(options.get("seed") or "").strip() else None
        for k in ("wildLevels", "trainerLevels"):
            options[k] = int(options.get(k) or 0)
    except ValueError:
        return {"ok": False, "error": "La graine et les pourcentages doivent être des nombres"}
    vg = {"POKEMON B2": 14, "POKEMON W2": 14, "POKEMON D": 8, "POKEMON P": 8, "POKEMON PL": 9,
          "POKEMON HG": 10, "POKEMON SS": 10, "RUBY": 5, "SAPPHIRE": 5, "EMERALD": 6, "FIRERED": 7,
          "LEAFGREEN": 7, "GOLD": 3, "SILVER": 3, "CRYSTAL": 4, "POKEMON X": 15, "POKEMON Y": 15, "POKEMON OR": 16,
          "POKEMON AS": 16, "POKEMON S": 17, "POKEMON M": 17, "POKEMON US": 18, "POKEMON UM": 18}.get(roms[path]["game"], 11)
    base = None
    try:
        with open(res("data", "fiche", f"vg_{vg}.json"), encoding="utf-8") as f:
            base = json.load(f)
    except Exception:
        pass
    out_path, err = rando_out_path(path, data.get("name"))
    if err:
        return {"ok": False, "error": err}
    if roms[path]["engine"] == "azahar":
        return _run_randomizer_ctr(path, roms[path], options, out_path, base, data.get("copySave"))
    try:
        out, report, summary = randomizer.randomize(path, options, out_path=out_path, fiche_base=base,
                                                    sprite_dir=res("data", "sprites"))
    except Exception as e:
        return {"ok": False, "error": str(e)}
    save_copied = False
    if data.get("copySave"):
        src_sav = os.path.splitext(path)[0] + ".sav"
        dst_sav = os.path.splitext(out)[0] + ".sav"
        if os.path.isfile(src_sav) and not os.path.exists(dst_sav):
            shutil.copy2(src_sav, dst_sav)
            save_copied = True
    summary = dict(summary, game=roms[path]["game"])
    remember_created(out)
    return {"ok": True, "out": out, "report": report, "saveCopied": save_copied, "engine": roms[path]["engine"], **summary}


def _copy_ctr_save(src_rom, out_rom):
    src = os.path.join(randomizer_gen6.save_dir(AZAHAR_DIR, _ctr_title_id(src_rom)), "data")
    dst = os.path.join(randomizer_gen6.save_dir(AZAHAR_DIR, _ctr_title_id(out_rom)), "data")
    if os.path.isfile(os.path.join(src, "00000001", "main")) and not os.path.exists(dst):
        shutil.copytree(src, dst)
        return True
    return False


def _ctr_used_tids(*paths):
    files = set(scan_roms("azahar"))
    dirs = set(_created_dirs()) | {os.path.dirname(os.path.abspath(p)) for p in paths if p}
    for d in dirs:
        try:
            for n in os.listdir(d):
                if os.path.splitext(n)[1].lower() in rom_finder.CTR_EXTS:
                    files.add(os.path.join(d, n))
        except OSError:
            pass
    used = set()
    for r in files:
        try:
            used.add(_ctr_title_id(r))
        except Exception:
            pass
    return used


def _run_randomizer_ctr(path, rom, options, out_path, base, copy_save):
    used = _ctr_used_tids(path, out_path)
    try:
        mod = randomizer_gen7 if rom["game"] in randomizer_gen7.FAMILY else randomizer_gen6
        out, report, summary = mod.randomize(path, options, out_path, base, AZAHAR_DIR, used)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    save_copied = _copy_ctr_save(path, out) if copy_save else False
    summary = dict(summary, game=rom["game"])
    summary.pop("tid", None)
    remember_created(out)
    return {"ok": True, "out": out, "report": report, "saveCopied": save_copied, "engine": "azahar", **summary}


SHINY_PICKED = []


def shiny_rom_entry(path):
    if not path or not os.path.isfile(path):
        return None
    low = path.lower()
    if low.endswith(".nds"):
        key = gen4_maps._rom_title(path)
        if key in gen5_maps.GAMES or key in randomizer.R4.PATHS4:
            game, eng = key, "melonds"
        else:
            return None
    elif low.endswith(".gba"):
        key = randomizer.R3.gba_title(path)
        if key not in GBA_RANDO_KEYS:
            return None
        game, eng = GBA_RANDO_KEYS[key], "mgba"
    elif low.endswith(GBC_EXTS):
        game, eng = gbc_game_key(path), "mgba"
        if not game:
            return None
    elif low.endswith(tuple(rom_finder.CTR_EXTS)):
        hit = rom_finder.identify(path)
        if not hit or hit[1] not in rom_finder.CTR_TITLES.values():
            return None
        game, eng = hit[1], "azahar"
        t = shiny_patch.side_threshold(path)
        return {"path": path, "game": game, "name": os.path.basename(path), "engine": eng,
                "odds": "1 / 4096" if t == 8 else ("100 %" if t >= 0x10000 else f"1 / {round(65536 / t)}")}
    else:
        return None
    t = shiny_patch.side_threshold(path)
    return {"path": path, "game": game, "name": os.path.basename(path), "engine": eng,
            "odds": "1 / 8192" if t == 8 else ("100 %" if t >= 0x10000 else f"1 / {round(65536 / t)}")}


def shiny_roms():
    out, seen = [], set()
    for path in scan_roms("melonds") + scan_roms("mgba") + scan_roms("azahar") + SHINY_PICKED:
        e = shiny_rom_entry(path)
        if e and os.path.normcase(path) not in seen:
            seen.add(os.path.normcase(path))
            out.append(e)
    return out


def shiny_pick_rom():
    path = pick_rom_dialog()
    if not path:
        return {"ok": False, "cancelled": True}
    e = shiny_rom_entry(path)
    if not e:
        return {"ok": False, "error": "Cette ROM n'est pas prise en charge (Pokémon 2G à 7G)"}
    if path not in SHINY_PICKED:
        SHINY_PICKED.append(path)
    return {"ok": True, "rom": e}


def run_shiny_tool(data):
    path = data.get("path") or ""
    roms = {r["path"]: r for r in shiny_roms()}
    if path not in roms:
        return {"ok": False, "error": "ROM introuvable ou non prise en charge"}
    value = str(data.get("value") or "").strip()
    ctr = roms[path]["engine"] == "azahar"
    try:
        label = (shiny_patch.ctr_resolve(value) if ctr else shiny_patch.resolve(value, ds=path.lower().endswith(".nds")))["label"]
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    out, err = rando_out_path(path, data.get("name"))
    if err:
        return {"ok": False, "error": err}
    if out is None:
        root, ext = os.path.splitext(path)
        out = f"{root} (Shiny {label.replace(' / ', '-').replace(' %', 'pc')}){ext}"
        if os.path.exists(out):
            return {"ok": False, "error": "Une ROM porte déjà ce nom dans ce dossier : donne-lui un nom"}
    used = _ctr_used_tids(path, out) if ctr else set()
    try:
        line = shiny_patch.make_shiny_rom(path, out, value, AZAHAR_DIR, used)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    save_copied = False
    if data.get("copySave") and ctr:
        save_copied = _copy_ctr_save(path, out)
    elif data.get("copySave"):
        src_sav, dst_sav = os.path.splitext(path)[0] + ".sav", os.path.splitext(out)[0] + ".sav"
        if os.path.isfile(src_sav) and not os.path.exists(dst_sav):
            shutil.copy2(src_sav, dst_sav)
            save_copied = True
    remember_created(out)
    return {"ok": True, "out": out, "change": line, "saveCopied": save_copied,
            "engine": roms[path]["engine"], "game": roms[path]["game"]}


CREATED_DIRS_PATH = os.path.join(BASE_DIR, "created_roms_dirs.json")


def _created_dirs():
    try:
        with open(CREATED_DIRS_PATH, encoding="utf-8") as f:
            return [d for d in json.load(f) if isinstance(d, str)]
    except Exception:
        return []


def remember_created(out_path):
    d = os.path.dirname(os.path.abspath(out_path))
    dirs = _created_dirs()
    if os.path.normcase(d) not in {os.path.normcase(x) for x in dirs}:
        dirs.append(d)
        try:
            with open(CREATED_DIRS_PATH, "w", encoding="utf-8") as f:
                json.dump(dirs, f, ensure_ascii=False)
        except Exception:
            pass


def created_rom_entry(path):
    stem = os.path.splitext(path)[0]
    rando, shiny = os.path.isfile(shiny_patch.side_path(stem)), os.path.isfile(stem + ".shiny.json")
    if not (rando or shiny):
        return None
    e = shiny_rom_entry(path)
    if not e:
        return None
    seed, report = None, stem + ".txt"
    if rando and os.path.isfile(report):
        try:
            with open(report, encoding="utf-8") as f:
                for line in [next(f, "") for _ in range(4)]:
                    m = re.match(r"\s*[^\s:]+\s*:\s*(\d+)\b", line)
                    if m:
                        seed = int(m.group(1))
                        break
        except Exception:
            pass
    return {"path": path, "name": os.path.splitext(os.path.basename(path))[0], "game": e["game"], "engine": e["engine"],
            "kind": "rando" if rando else "shiny", "odds": e["odds"], "seed": seed,
            "report": report if rando and os.path.isfile(report) else None,
            "date": int(os.path.getmtime(path) * 1000)}


def created_roms():
    cands = scan_roms("melonds") + scan_roms("mgba") + scan_roms("azahar") + RANDO_PICKED + SHINY_PICKED
    for d in _created_dirs():
        try:
            cands += [os.path.join(d, n) for n in os.listdir(d)
                      if n.lower().endswith((".nds", ".gba") + GBC_EXTS + tuple(rom_finder.CTR_EXTS))]
        except Exception:
            continue
    out, seen = [], set()
    for path in cands:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        try:
            e = created_rom_entry(path)
        except Exception:
            e = None
        if e:
            out.append(e)
    out.sort(key=lambda e: -e["date"])
    return out


def _created_by_path(path):
    return next((e for e in created_roms() if path and e["path"] == path), None)


def _to_recycle_bin(paths):
    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", ctypes.c_uint), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    op = SHFILEOPSTRUCTW()
    op.wFunc = 3
    op.pFrom = "\0".join(paths) + "\0\0"
    op.fFlags = 0x0040 | 0x0010 | 0x0400 | 0x0004
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not op.fAnyOperationsAborted


def created_rom_delete(data):
    e = _created_by_path(data.get("path"))
    if not e:
        return {"ok": False, "error": "ROM introuvable"}
    stem = os.path.splitext(e["path"])[0]
    files = [e["path"]] + [f for f in (shiny_patch.side_path(stem), stem + ".shiny.json", stem + ".txt") if os.path.isfile(f)]
    if os.path.isdir(e["path"] + ".exefsdir"):
        files.append(e["path"] + ".exefsdir")
    if not _to_recycle_bin([os.path.abspath(f) for f in files]):
        return {"ok": False, "error": "Impossible de la mettre à la corbeille (ROM ouverte ?)"}
    return {"ok": True}


def created_rom_action(data):
    e = _created_by_path(data.get("path"))
    if not e:
        return {"ok": False}
    if data.get("what") == "folder":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(e["path"])])
    elif data.get("what") == "report" and e["report"]:
        os.startfile(e["report"])
    else:
        return {"ok": False}
    return {"ok": True}


APP_VERSION = paths.CURRENT_VERSION
ABOUT_LINKS = {
    "author": "https://github.com/mrdbmyla",
    "mgba": "https://mgba.io",
    "melonds": "https://melonds.kuribo64.net",
    "melonds-src": "https://github.com/melonDS-emu/melonDS",
    "azahar": "https://azahar-emu.org",
    "azahar-src": "https://github.com/azahar-emu/azahar",
    "pokeapi": "https://pokeapi.co",
    "font": "https://fonts.google.com/specimen/Barlow+Condensed",
}
UPDATE_REPO = "mrdbmyla/PKLab"
UPDATE_INFO = {}


def check_update():
    if not UPDATE_REPO:
        return {"ok": True, "version": APP_VERSION, "configured": False}
    import urllib.request
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
                                     headers={"User-Agent": "PKLab", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            rel = json.load(r)
    except Exception as e:
        if getattr(e, "code", None) == 404:
            return {"ok": True, "version": APP_VERSION, "configured": True, "latest": "", "newer": False, "notes": []}
        return {"ok": False, "version": APP_VERSION, "configured": True, "error": "Pas de connexion au serveur de mises à jour"}
    latest = str(rel.get("tag_name") or "").lstrip("vV.")
    notes = [ln.strip()[2:].strip() for ln in str(rel.get("body") or "").splitlines() if ln.strip().startswith(("- ", "* "))][:6]
    url = str(rel.get("html_url") or "")
    UPDATE_INFO["url"] = url if url.startswith(f"https://github.com/{UPDATE_REPO}/") else ""
    UPDATE_INFO["zip"] = UPDATE_INFO["exe"] = None
    for a in rel.get("assets") or []:
        dl = str(a.get("browser_download_url") or "")
        if not dl.startswith(f"https://github.com/{UPDATE_REPO}/releases/download/"):
            continue
        info = {"url": dl, "digest": str(a.get("digest") or ""), "version": latest}
        if a.get("name") == updater.ZIP_NAME:
            UPDATE_INFO["zip"] = info
        elif a.get("name") == updater.EXE_NAME and info["digest"].startswith("sha256:"):
            UPDATE_INFO["exe"] = info
    auto = paths.UPDATABLE and bool(UPDATE_INFO["zip"] or UPDATE_INFO["exe"])
    return {"ok": True, "version": APP_VERSION, "configured": True, "latest": latest,
            "newer": paths.ver_tuple(latest) > paths.ver_tuple(APP_VERSION), "notes": notes, "light": auto}


def apply_update():
    z, e = UPDATE_INFO.get("zip"), UPDATE_INFO.get("exe")
    r = {"ok": False, "needExe": True, "error": "Aucune mise à jour automatique disponible"}
    if z:
        r = updater.apply_light_update(z["url"], z["digest"], z["version"])
    if not r.get("ok") and r.get("needExe") and e:
        r = updater.apply_exe_update(e["url"], e["digest"])
        if r.get("needPage"):
            r["needExe"] = True
    if r.get("ok"):
        if STATE:
            STATE.log(f"Mise à jour installée : {z['version'] if z else e['version']}")
        r["restart"] = True
        threading.Thread(target=_restart_after_update, daemon=True).start()
    return r


def _restart_after_update():
    time.sleep(1.0)
    choice = ask_save_state_choice()
    if choice == "cancel":
        return
    if choice == "save":
        send_save_state_hotkey()
        time.sleep(1.5)
    cmd, env = updater.restart_command()
    try:
        subprocess.Popen(cmd, env=env, close_fds=True,
                         creationflags=0x00000008 | 0x00000200)
    except OSError:
        return
    stop_emulator()
    os._exit(0)


ROM_SIDE_PATH = None


def load_rom_side_data(rom_path):
    global ROM_SIDE_PATH
    ROM_SIDE_PATH = None
    engine.TYPE_OVERRIDE = {}
    engine.SHINY_THRESHOLD = shiny_patch.side_threshold(rom_path)
    side = shiny_patch.side_path(os.path.splitext(rom_path)[0])
    if not os.path.isfile(side):
        return
    try:
        with open(side, encoding="utf-8") as f:
            data = json.load(f)
        engine.TYPE_OVERRIDE = {int(k): (v[0], v[1]) for k, v in data.get("engineTypes", {}).items()}
        ROM_SIDE_PATH = side
    except Exception as e:
        print("[rando] fichier de données illisible :", side, e)


SAVE_PICKED = []


SAVE6_TITLES = {"POKEMON X", "POKEMON Y", "POKEMON OR", "POKEMON AS", "POKEMON S", "POKEMON M", "POKEMON US", "POKEMON UM"}


def _azahar_save_path(tid):
    return os.path.join(AZAHAR_DIR, *AZAHAR_SAVE_DIR, f"{tid & 0xFFFFFFFF:08x}", "data", "00000001", "main")


def _ctr_saves():
    out = {}
    for rom in scan_roms("azahar"):
        tid = _ctr_title_id(rom)
        key = rom_finder.CTR_TITLES.get(rom_finder.base_tid(tid)) if tid else None
        if key in SAVE6_TITLES:
            out.setdefault(os.path.normcase(_azahar_save_path(tid)), (rom, key))
    return out


def _save_rom(sav):
    hit = _ctr_saves().get(os.path.normcase(sav)) if os.path.basename(sav) == "main" else None
    if hit:
        return hit[0], hit[1], hit[1]
    stem = os.path.splitext(sav)[0]
    if os.path.isfile(stem + ".nds"):
        key = gen4_maps._rom_title(stem + ".nds")
        return stem + ".nds", key, key
    if os.path.isfile(stem + ".gba"):
        return stem + ".gba", GBA_RANDO_KEYS.get(randomizer.R3.gba_title(stem + ".gba")), None
    for ext in GBC_EXTS:
        if os.path.isfile(stem + ext):
            key = gbc_game_key(stem + ext)
            return stem + ext, key, key
    return None, None, None


def save_files():
    out, seen = [], set()
    roms = scan_roms("melonds") + scan_roms("mgba")
    for path in [os.path.splitext(r)[0] + ".sav" for r in roms] + SAVE_PICKED:
        if os.path.isfile(path) and os.path.normcase(path) not in seen:
            seen.add(os.path.normcase(path))
            _, game, _ = _save_rom(path)
            out.append({"path": path, "name": os.path.basename(path), "game": game})
    for path, (rom, key) in _ctr_saves().items():
        if os.path.isfile(path) and path not in seen:
            seen.add(path)
            out.append({"path": os.path.normpath(_azahar_save_path(_ctr_title_id(rom))),
                        "name": "Azahar", "game": key})
    return out


def _allowed_save(path):
    return any(os.path.normcase(s["path"]) == os.path.normcase(path or "") for s in save_files())


def _mon_json(m, warn=None):
    if not m:
        return None
    keys = ("species", "nickname", "level", "item", "moves", "pp", "ivs", "evs", "friendship", "nature", "shiny", "egg",
            "bad", "ot", "tid", "exp", "hp", "hp_max", "ability", "ability_slot", "dv", "hp_dv", "pp_ups", "stats")
    out = {k: m[k] for k in keys if k in m}
    if warn:
        out["warnings"] = warn(m)
    return out


_SAVE_TABLES = {}


def _save_table(path, gen):
    rom = _save_rom(path)[0]
    if rom:
        key = (os.path.normcase(rom), os.path.getmtime(rom))
        if key not in _SAVE_TABLES:
            try:
                _SAVE_TABLES[key] = save_editor.species_table(rom)
            except Exception as e:
                print(f"Éditeur : stats de base illisibles dans {os.path.basename(rom)} ({e}), données d'origine utilisées")
                _SAVE_TABLES[key] = None
        if _SAVE_TABLES[key]:
            return _SAVE_TABLES[key]
    return save_editor.base_table(gen)


_SAVE_POCKETS = {}


def _save_pockets(path, sv):
    rom = _save_rom(path)[0]
    if rom:
        key = (os.path.normcase(rom), os.path.getmtime(rom))
        if key not in _SAVE_POCKETS:
            try:
                _SAVE_POCKETS[key] = save_editor.item_pockets(rom)
            except Exception as e:
                print(f"Éditeur : objets illisibles dans {os.path.basename(rom)} ({e}), données d'origine utilisées")
                _SAVE_POCKETS[key] = None
        if _SAVE_POCKETS[key]:
            return _SAVE_POCKETS[key]
    return save_editor.item_pockets_default(save_editor.save_family(sv))


def save_load(data):
    path = data.get("path") or ""
    if not _allowed_save(path):
        return {"ok": False, "error": "Sauvegarde introuvable"}
    try:
        _, game, title = _save_rom(path)
        sv = save_editor.open_save(path, title)
        boxes, names = sv.pc()
        table = _save_table(path, sv.gen)
        for b in boxes:
            for m in b:
                if m and not m.get("bad") and m.get("species") in table:
                    m["level"] = save_editor.level_for_exp(table[m["species"]][6], m["exp"])
        pockets = _save_pockets(path, sv)
        bag = save_editor.bag(sv)
        for pk in bag:
            pk["allowed"] = sorted({i for i, c in pockets.items() if pk["code"] is None or c == pk["code"]} |
                                   {it for it, _ in pk["items"]})
        warn = lambda m: save_editor.check_mon(sv.gen, m, table, pockets, sv.family)
        return {"ok": True, "gen": sv.gen, "game": game, "family": sv.family, "problems": sv.problems,
                "bag": bag, "dex": save_editor.dex(sv), "ext": save_editor.MON_EXT[sv.gen],
                "baseStats": {k: v[:6] for k, v in table.items()},
                "trainer": sv.trainer(), "party": [_mon_json(m, warn) for m in sv.party()],
                "boxes": [[_mon_json(m, warn) for m in b] for b in boxes], "boxNames": names,
                "backup": _save_backup_info(path)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _save_backup_info(path):
    bak = path + ".bak"
    if not os.path.isfile(bak):
        return {"exists": False}
    return {"exists": True, "date": int(os.path.getmtime(bak) * 1000)}


def save_restore(data):
    path = data.get("path") or ""
    if not _allowed_save(path):
        return {"ok": False, "error": "Sauvegarde introuvable"}
    bak = path + ".bak"
    if not os.path.isfile(bak):
        return {"ok": False, "error": "Pas de copie d'origine pour cette sauvegarde"}
    try:
        shutil.copyfile(path, path + ".avant_restauration")
        shutil.copyfile(bak, path)
        return {"ok": True, "kept": os.path.basename(path) + ".avant_restauration"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def save_write(data):
    path = data.get("path") or ""
    if not _allowed_save(path):
        return {"ok": False, "error": "Sauvegarde introuvable"}
    try:
        _, _, title = _save_rom(path)
        sv = save_editor.open_save(path, title)
        if data.get("money") is not None:
            save_editor.set_money(sv, int(data["money"]))
        allowed = {"species", "item", "moves", "ivs", "evs", "friendship", "level", "nature"}
        table = _save_table(path, sv.gen)
        if data.get("bag"):
            pockets = _save_pockets(path, sv)
            for pk in save_editor.bag(sv):
                had = {it for it, _ in pk["items"]}
                for it, _ in data["bag"].get(pk["key"], []):
                    if pk["code"] is not None and pockets.get(int(it)) != pk["code"] and int(it) not in had:
                        return {"ok": False, "error": f"objet {it} : pas dans la poche {pk['label']}"}
            save_editor.set_bag(sv, data["bag"])
        if data.get("dex"):
            save_editor.set_dex(sv, data["dex"].get("seen", []), data["dex"].get("caught", []), table)
        for e in data.get("edits") or []:
            changes = {k: v for k, v in (e.get("changes") or {}).items() if k in allowed}
            where = tuple(e.get("where") or ())
            if changes and where:
                save_editor.edit_mon(sv, where, changes, table)
        save_editor.write_save(sv, path)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


EXPORT_DIR = os.path.join(BASE_DIR, "pokemon_exportes")


def _file_dialog(kind, ext, name=None):
    try:
        import webview
        if not webview.windows:
            return None
        types = (f"Pokémon (*{ext})", i18n.tr("Tous les fichiers (*.*)"))
        if kind == "save":
            r = webview.windows[0].create_file_dialog(webview.FileDialog.SAVE, directory=EXPORT_DIR, save_filename=name,
                                                      file_types=types)
        else:
            r = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN, directory=EXPORT_DIR, file_types=types)
        if not r:
            return None
        return r if isinstance(r, str) else r[0]
    except Exception:
        return None


def _where(data):
    w = data.get("where") or []
    return ("party", int(w[1])) if w and w[0] == "party" else ("box", int(w[1]), int(w[2]))


def save_export_mon(data):
    path = data.get("path") or ""
    if not _allowed_save(path):
        return {"ok": False, "error": "Sauvegarde introuvable"}
    try:
        sv = save_editor.open_save(path, _save_rom(path)[2])
        raw = save_editor.export_mon(sv, _where(data))
        if raw is None:
            return {"ok": False, "error": "place vide"}
        ext = save_editor.MON_EXT[sv.gen]
        base = "".join(c for c in (data.get("name") or "pokemon") if c.isalnum() or c in " -_") or "pokemon"
        os.makedirs(EXPORT_DIR, exist_ok=True)
        dest = _file_dialog("save", ext, base + ext)
        if not dest:
            if _has_window():
                return {"ok": False, "error": "annulé"}
            dest, k = os.path.join(EXPORT_DIR, base + ext), 2
            while os.path.exists(dest):
                dest, k = os.path.join(EXPORT_DIR, f"{base} ({k}){ext}"), k + 1
        with open(dest, "wb") as f:
            f.write(raw)
        return {"ok": True, "file": dest}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _has_window():
    try:
        import webview
        return bool(webview.windows)
    except Exception:
        return False


def save_import_mon(data):
    path = data.get("path") or ""
    if not _allowed_save(path):
        return {"ok": False, "error": "Sauvegarde introuvable"}
    try:
        _, _, title = _save_rom(path)
        sv = save_editor.open_save(path, title)
        ext = save_editor.MON_EXT[sv.gen]
        src = data.get("file") or _file_dialog("open", ext)
        if not src:
            return {"ok": False, "error": "annulé"}
        if not src.lower().endswith((".pk2", ".pk3", ".pk4", ".pk5", ".pk6")):
            return {"ok": False, "error": "choisis un fichier .pk2, .pk3, .pk4, .pk5 ou .pk6"}
        if not src.lower().endswith(ext):
            return {"ok": False, "error": f"cette sauvegarde prend les fichiers {ext} (Pokémon de la même génération)"}
        with open(src, "rb") as f:
            raw = f.read(400)
        save_editor.import_mon(sv, _where(data), raw, _save_table(path, sv.gen))
        save_editor.write_save(sv, path)
        return {"ok": True, "file": src}
    except Exception as e:
        return {"ok": False, "error": str(e)}


_SAVE_NAMES = {}


def _save_names(path):
    rom = _save_rom(path)[0]
    if not rom:
        return None
    key = (os.path.normcase(rom), os.path.getmtime(rom))
    if key not in _SAVE_NAMES:
        try:
            _SAVE_NAMES[key] = save_editor.species_names_raw(rom)
        except Exception as e:
            print(f"Éditeur : noms des Pokémon illisibles dans {os.path.basename(rom)} ({e}), noms français utilisés")
            _SAVE_NAMES[key] = None
    return _SAVE_NAMES[key]


def rom_has_save(rom_path):
    if rom_path.lower().endswith(tuple(rom_finder.CTR_EXTS)):
        return azahar_has_save(rom_path)
    sav = os.path.splitext(rom_path)[0] + ".sav"
    if not os.path.isfile(sav):
        return False
    try:
        with open(sav, "rb") as f:
            raw = f.read()
        if not raw or raw.count(raw[0]) == len(raw):
            return False
        if rom_path.lower().endswith(GBC_EXTS):
            sv = save_editor.open_save(sav, gbc_game_key(rom_path))
            return any(m and not m.get("bad") for m in sv.party())
        title = None if rom_path.lower().endswith(".gba") else gen4_maps._rom_title(rom_path)
        sv = save_editor.open_save(sav, title)
        buf, o = save_editor._party_count_at(sv)
        n = struct.unpack_from("<I", buf, o)[0]
        return 1 <= n <= 6 and any(m and not m.get("bad") for m in sv.party()[:n])
    except Exception as e:
        print(f"Detection : sauvegarde {os.path.basename(sav)} illisible ({e}), consideree comme une partie en cours")
        return True


def save_create_mon(data):
    path = data.get("path") or ""
    if not _allowed_save(path):
        return {"ok": False, "error": "Sauvegarde introuvable"}
    try:
        sv = save_editor.open_save(path, _save_rom(path)[2])
        save_editor.create_mon(sv, _where(data), int(data["species"]), int(data.get("level") or 5),
                               int(data.get("nature") or 0), bool(data.get("shiny")), data.get("moves") or [],
                               _save_table(path, sv.gen), names=_save_names(path))
        save_editor.write_save(sv, path)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def save_remove_mon(data):
    path = data.get("path") or ""
    if not _allowed_save(path):
        return {"ok": False, "error": "Sauvegarde introuvable"}
    try:
        sv = save_editor.open_save(path, _save_rom(path)[2])
        save_editor.remove_mon(sv, _where(data))
        save_editor.write_save(sv, path)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def pick_save_dialog():
    try:
        import webview
        if not webview.windows:
            return None
        result = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN,
                                                       file_types=(i18n.tr("Sauvegarde (*.sav)"), i18n.tr("Tous les fichiers (*.*)")))
        return result[0] if result else None
    except Exception:
        return None


def pick_rom_dialog():
    try:
        import webview
        if not webview.windows:
            return None
        exts = sorted({e for cfg in EMULATOR_BUNDLES.values() for e in cfg.get("rom_exts", [cfg["rom_ext"]])})
        pattern = ";".join(f"*{ext}" for ext in exts)
        result = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN,
            file_types=(f"ROM ({pattern})", i18n.tr("Tous les fichiers (*.*)")),
        )
        if not result:
            return None
        return result[0]
    except Exception:
        return None


def _hide_window_by_title(pid, title, timeout=6.0, poll_interval=0.2):
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def find_once():
        found = []

        def callback(hwnd, _lparam):
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value == title:
                win_pid = ctypes.c_uint32()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
                if win_pid.value == pid:
                    found.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(callback), None)
        return found[0] if found else None

    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = find_once()
        if hwnd:
            user32.ShowWindow(hwnd, 0)
            return True
        time.sleep(poll_interval)
    return False


def _find_window_containing(pid, title_contains, timeout=8.0, poll_interval=0.2, include_hidden=False):
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def find_once():
        found = []

        def callback(hwnd, _lparam):
            if not include_hidden and not user32.IsWindowVisible(hwnd):
                return True
            if pid is not None:
                win_pid = ctypes.c_uint32()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
                if win_pid.value != pid:
                    return True
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if title_contains in buf.value:
                found.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(callback), None)
        return found[0] if found else None

    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = find_once()
        if hwnd:
            return hwnd
        time.sleep(poll_interval)
    return None


EMBED_TITLE_HINTS = {"melonds": "melonDS", "mgba": "mGBA -", "azahar": "Azahar "}
GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
SW_HIDE = 0
SW_SHOW = 5
TOPBAR_HEIGHT_PX = 48
SIDEBAR_EXPANDED_PX = 320
SIDEBAR_COLLAPSED_PX = 28

CURRENT_CANVAS_HWND = None
CURRENT_EMBEDDED_HMENU = None
_LAST_RESIZE_PARAMS = None
OWN_HWND = None
EMBED_DESIRED_VISIBLE = True
CURRENT_SIDEBAR_PX = SIDEBAR_EXPANDED_PX


def _to_signed32(val):
    val &= 0xFFFFFFFF
    return val - 0x100000000 if val >= 0x80000000 else val


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


_U32 = None


def _user32():
    global _U32
    if _U32 is not None:
        return _U32
    user32 = ctypes.windll.user32
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
    user32.SetParent.restype = ctypes.c_void_p
    user32.SetParent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RECT)]
    user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RECT)]
    user32.GetMenu.restype = ctypes.c_void_p
    user32.GetMenu.argtypes = [ctypes.c_void_p]
    user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetMenuItemCount.argtypes = [ctypes.c_void_p]
    user32.GetMenuItemInfoW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_bool, ctypes.POINTER(_MENUITEMINFOW)]
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    user32.ClientToScreen.argtypes = [ctypes.c_void_p, ctypes.POINTER(_POINT)]
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    user32.SetFocus.argtypes = [ctypes.c_void_p]
    user32.MessageBoxW.restype = ctypes.c_int
    user32.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetWindowThreadProcessId.restype = ctypes.c_uint
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.AttachThreadInput.restype = ctypes.c_int
    user32.AttachThreadInput.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_int]
    user32.WindowFromPoint.restype = ctypes.c_void_p
    user32.WindowFromPoint.argtypes = [_POINT]
    user32.IsChild.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    _U32 = user32
    return user32


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MENUITEMINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint), ("fMask", ctypes.c_uint), ("fType", ctypes.c_uint),
        ("fState", ctypes.c_uint), ("wID", ctypes.c_uint), ("hSubMenu", ctypes.c_void_p),
        ("hbmpChecked", ctypes.c_void_p), ("hbmpUnchecked", ctypes.c_void_p),
        ("dwItemData", ctypes.c_void_p), ("dwTypeData", ctypes.c_wchar_p),
        ("cch", ctypes.c_uint), ("hbmpItem", ctypes.c_void_p),
    ]


MIIM_STATE = 0x1
MIIM_ID = 0x2
MIIM_SUBMENU = 0x4
MIIM_FTYPE = 0x100
MIIM_STRING = 0x40
MFT_SEPARATOR = 0x800
MFS_DISABLED = 0x3
WM_COMMAND = 0x0111


def _menu_tree(user32, hmenu, depth=0):
    if not hmenu or depth > 5:
        return []
    items = []
    for i in range(user32.GetMenuItemCount(hmenu)):
        info = _MENUITEMINFOW()
        info.cbSize = ctypes.sizeof(_MENUITEMINFOW)
        buf = ctypes.create_unicode_buffer(256)
        info.fMask = MIIM_STRING | MIIM_FTYPE | MIIM_SUBMENU | MIIM_STATE | MIIM_ID
        info.dwTypeData = ctypes.cast(buf, ctypes.c_wchar_p)
        info.cch = 256
        if not user32.GetMenuItemInfoW(hmenu, i, True, ctypes.byref(info)):
            continue
        if info.fType & MFT_SEPARATOR:
            items.append({"separator": True})
            continue
        label = buf.value.replace("&", "")
        if not label:
            continue
        if info.hSubMenu:
            items.append({"label": label, "items": _menu_tree(user32, info.hSubMenu, depth + 1)})
        else:
            items.append({
                "label": label,
                "id": info.wID,
                "disabled": bool(info.fState & MFS_DISABLED),
            })
    return items


def get_embedded_menu():
    if not CURRENT_CANVAS_HWND or not CURRENT_EMBEDDED_HMENU:
        return []
    user32 = _user32()
    if not user32.IsWindow(CURRENT_CANVAS_HWND):
        return []
    return _menu_tree(user32, CURRENT_EMBEDDED_HMENU)


def send_embedded_menu_command(item_id):
    if not CURRENT_CANVAS_HWND or not item_id:
        return False
    user32 = _user32()
    if not user32.IsWindow(CURRENT_CANVAS_HWND):
        return False
    user32.PostMessageW(CURRENT_CANVAS_HWND, WM_COMMAND, item_id, 0)
    return True


VK_SHIFT = 0x10
VK_F1 = 0x70
KEYEVENTF_KEYUP = 0x0002
WM_ACTIVATE = 0x0006
WM_SETFOCUS = 0x0007
WM_NCACTIVATE = 0x0086
WA_ACTIVE = 1


def _pump_sleep(seconds):
    user32 = ctypes.windll.user32
    msg = wintypes.MSG()
    PM_REMOVE = 1
    end = time.time() + seconds
    while True:
        remaining = end - time.time()
        if remaining <= 0:
            break
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(min(0.01, remaining))


def _find_save_state_slot1_id(user32, hmenu, label="Save State"):
    tree = _menu_tree(user32, hmenu)
    for top in tree:
        if top.get("label") != "File":
            continue
        for item in top.get("items", []):
            if item.get("label") == label and item.get("items"):
                return item["items"][0].get("id")
    return None


def send_save_state_hotkey(load=False):
    if not CURRENT_CANVAS_HWND or CURRENT_EMULATOR_PROC is None or CURRENT_EMULATOR_PROC.poll() is not None:
        return False
    user32 = _user32()
    if not user32.IsWindow(CURRENT_CANVAS_HWND):
        return False

    hmenu = user32.GetMenu(CURRENT_CANVAS_HWND)
    if hmenu:
        item_id = _find_save_state_slot1_id(user32, hmenu, "Load State" if load else "Save State")
        if item_id:
            user32.PostMessageW(CURRENT_CANVAS_HWND, WM_COMMAND, item_id, 0)
            time.sleep(0.5)
            return True

    if not OWN_HWND:
        return False
    azahar_before = _azahar_quicksaves() if CURRENT_ENGINE_KEY == "azahar" and not load else None
    kernel32 = ctypes.windll.kernel32
    current_thread_id = kernel32.GetCurrentThreadId()
    foreground_hwnd = user32.GetForegroundWindow()
    foreground_thread_id = user32.GetWindowThreadProcessId(foreground_hwnd, None) if foreground_hwnd else 0
    attached = False
    if foreground_thread_id and foreground_thread_id != current_thread_id:
        attached = bool(user32.AttachThreadInput(current_thread_id, foreground_thread_id, True))
    try:
        user32.SetForegroundWindow(OWN_HWND)
        user32.SetFocus(CURRENT_CANVAS_HWND)
    finally:
        if attached:
            user32.AttachThreadInput(current_thread_id, foreground_thread_id, False)
    _pump_sleep(0.25)
    user32.PostMessageW(CURRENT_CANVAS_HWND, WM_NCACTIVATE, 1, 0)
    user32.PostMessageW(CURRENT_CANVAS_HWND, WM_ACTIVATE, WA_ACTIVE, 0)
    user32.SetFocus(CURRENT_CANVAS_HWND)
    user32.PostMessageW(CURRENT_CANVAS_HWND, WM_SETFOCUS, 0, 0)
    _pump_sleep(1.0)
    if not load:
        user32.keybd_event(VK_SHIFT, 0, 0, 0)
        _pump_sleep(0.05)
    user32.keybd_event(VK_F1, 0, 0, 0)
    _pump_sleep(0.05)
    user32.keybd_event(VK_F1, 0, KEYEVENTF_KEYUP, 0)
    _pump_sleep(0.05)
    if not load:
        user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
    _pump_sleep(0.3)
    if azahar_before is not None:
        end = time.time() + 10
        while time.time() < end:
            now = _azahar_quicksaves()
            if any(azahar_before.get(f) != t for f, t in now.items()):
                _pump_sleep(0.5)
                break
            _pump_sleep(0.2)
    return True


STATE1_EXT = {"melonds": ".ml1", "mgba": ".ss1"}


def _azahar_quicksaves():
    d = os.path.join(AZAHAR_DIR, "user", "states")
    try:
        return {f: os.path.getmtime(os.path.join(d, f)) for f in os.listdir(d) if f.endswith(".00.cst")}
    except OSError:
        return {}


def state1_path(engine_key, rom_path):
    if engine_key == "azahar":
        tid = _ctr_title_id(rom_path) if rom_path else None
        return os.path.join(AZAHAR_DIR, "user", "states", f"{tid:016X}.00.cst") if tid else None
    ext = STATE1_EXT.get(engine_key)
    return os.path.splitext(rom_path)[0] + ext if ext and rom_path else None


def _load_state1_when_ready(proc):
    end = time.time() + 40
    while time.time() < end and proc.poll() is None:
        if CURRENT_EMULATOR_PROC is proc and CURRENT_CANVAS_HWND:
            break
        time.sleep(0.3)
    else:
        return
    time.sleep(4.0)
    if CURRENT_EMULATOR_PROC is not proc or proc.poll() is not None:
        return
    user32 = _user32()
    hidden = not user32.IsWindowVisible(CURRENT_CANVAS_HWND)
    if hidden:
        user32.ShowWindow(CURRENT_CANVAS_HWND, SW_SHOW)
    send_save_state_hotkey(load=True)
    if hidden and not EMBED_DESIRED_VISIBLE:
        user32.ShowWindow(CURRENT_CANVAS_HWND, SW_HIDE)


def _window_rect(user32, hwnd):
    rect = _RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def _client_size(user32, hwnd):
    rect = _RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    return rect.right - rect.left, rect.bottom - rect.top


def resize_embedded_canvas():
    global CURRENT_CANVAS_HWND, _LAST_RESIZE_PARAMS
    if not CURRENT_CANVAS_HWND or not OWN_HWND:
        return
    user32 = _user32()
    if not user32.IsWindow(CURRENT_CANVAS_HWND):
        CURRENT_CANVAS_HWND = None
        _LAST_RESIZE_PARAMS = None
        return
    width, height = _client_size(user32, OWN_HWND)
    params = (CURRENT_CANVAS_HWND, width, height, CURRENT_SIDEBAR_PX)
    if params == _LAST_RESIZE_PARAMS:
        return
    _LAST_RESIZE_PARAMS = params

    embed_x = CURRENT_SIDEBAR_PX
    embed_y = TOPBAR_HEIGHT_PX
    embed_w = max(width - CURRENT_SIDEBAR_PX, 50)
    embed_h = max(height - TOPBAR_HEIGHT_PX, 50)
    _fit_and_center(user32, CURRENT_CANVAS_HWND, embed_x, embed_y, embed_w, embed_h)


def _fit_and_center(user32, hwnd, x, y, w, h):
    req_w, req_h = w, h
    actual_w, actual_h = w, h
    for _ in range(4):
        user32.SetWindowPos(hwnd, 0, x, y, req_w, req_h, SWP_NOZORDER | SWP_FRAMECHANGED)
        l, t, r, b = _window_rect(user32, hwnd)
        actual_w, actual_h = max(r - l, 1), max(b - t, 1)
        if actual_w <= w and actual_h <= h:
            break
        shrink = min(w / actual_w, h / actual_h) * 0.97
        req_w = max(int(req_w * shrink), 50)
        req_h = max(int(req_h * shrink), 50)

    if actual_w < w or actual_h < h:
        centered_x = x + max((w - actual_w) // 2, 0)
        centered_y = y + max((h - actual_h) // 2, 0)
        user32.SetWindowPos(hwnd, 0, centered_x, centered_y, actual_w, actual_h, SWP_NOZORDER)


def set_sidebar_collapsed(collapsed):
    global CURRENT_SIDEBAR_PX
    CURRENT_SIDEBAR_PX = SIDEBAR_COLLAPSED_PX if collapsed else SIDEBAR_EXPANDED_PX
    resize_embedded_canvas()


def embed_emulator_window(engine_key, pid):
    global CURRENT_CANVAS_HWND, OWN_HWND, CURRENT_EMBEDDED_HMENU, _LAST_RESIZE_PARAMS
    _LAST_RESIZE_PARAMS = None
    title_hint = EMBED_TITLE_HINTS.get(engine_key)
    if not title_hint:
        return
    emu_hwnd = _find_window_containing(pid, title_hint)
    if not emu_hwnd:
        return
    own_hwnd = OWN_HWND or _find_window_containing(os.getpid(), "PKLab", timeout=10.0)
    if not own_hwnd:
        return
    OWN_HWND = own_hwnd
    user32 = _user32()

    CURRENT_EMBEDDED_HMENU = user32.GetMenu(emu_hwnd) or None

    style = user32.GetWindowLongW(emu_hwnd, GWL_STYLE) & 0xFFFFFFFF
    style &= ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
    style |= WS_CHILD
    user32.SetWindowLongW(emu_hwnd, GWL_STYLE, _to_signed32(style))
    user32.SetParent(emu_hwnd, own_hwnd)
    CURRENT_CANVAS_HWND = emu_hwnd
    if not EMBED_DESIRED_VISIBLE and engine_key != "melonds":
        user32.ShowWindow(emu_hwnd, SW_HIDE)
    for _ in range(4):
        resize_embedded_canvas()
        time.sleep(0.75)

    if engine_key == "melonds" and not EMBED_DESIRED_VISIBLE and CURRENT_CANVAS_HWND and user32.IsWindow(CURRENT_CANVAS_HWND):
        user32.ShowWindow(CURRENT_CANVAS_HWND, SW_HIDE)


def _focus_embedded(user32):
    hwnd = CURRENT_CANVAS_HWND
    if not hwnd or not user32.IsWindow(hwnd):
        return
    kernel32 = ctypes.windll.kernel32
    me = kernel32.GetCurrentThreadId()
    target = user32.GetWindowThreadProcessId(hwnd, None)
    attached = bool(target and target != me and user32.AttachThreadInput(me, target, True))
    try:
        user32.SetFocus(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(me, target, False)


def _focus_guard_loop():
    user32 = _user32()
    was_down = False
    pt = _POINT()
    while True:
        hwnd = CURRENT_CANVAS_HWND
        if not hwnd or not EMBED_DESIRED_VISIBLE:
            was_down = False
            time.sleep(0.2)
            continue
        down = bool(user32.GetAsyncKeyState(0x01) & 0x8000 or user32.GetAsyncKeyState(0x02) & 0x8000)
        if down and not was_down and user32.GetCursorPos(ctypes.byref(pt)):
            under = user32.WindowFromPoint(pt)
            if under and (under == hwnd or user32.IsChild(hwnd, under)):
                try:
                    _focus_embedded(user32)
                except Exception:
                    pass
        was_down = down
        time.sleep(0.02)


SPEED_STEPS = (1, 2, 5, 10, 20, 100)
MELONDS_FPS = (60.0, 1000.0, 30.0)
_MELONDS_FPS_SIG = struct.pack("<ddd", *MELONDS_FPS)
_MGBA_SYNC_SIG = bytes.fromhex("d007000200000000")
CURRENT_SPEED = 1
_SPEED_TARGET = {"pid": None, "addr": None, "fmt": None, "base": None, "pm": None}
_SPEED_LOCK = threading.Lock()
_SPEED_SCAN_CHUNK = 0x200000
SPEED_AUTO_RESET = {"pending": False}


def _speed_available():
    return (CURRENT_ENGINE_KEY in ("melonds", "mgba", "azahar") and CURRENT_CANVAS_HWND is not None
            and CURRENT_EMULATOR_PROC is not None and CURRENT_EMULATOR_PROC.poll() is None)


def _find_speed_target(pm, engine_key):
    import pymem.memory
    handle = pm.process_handle
    hits = []
    addr = 0
    while addr < 0x7FFFFFFF0000 and len(hits) < 2:
        try:
            mbi = pymem.memory.virtual_query(handle, addr)
        except Exception:
            break
        base, size = mbi.BaseAddress or 0, mbi.RegionSize
        if not size:
            break
        if mbi.State == 0x1000 and mbi.Protect == 0x04 and mbi.Type == 0x20000 and size < 0x10000000:
            off = 0
            while off < size and len(hits) < 2:
                try:
                    data = pm.read_bytes(base + off, min(_SPEED_SCAN_CHUNK + 32, size - off))
                except Exception:
                    break
                if engine_key == "melonds":
                    i = data.find(_MELONDS_FPS_SIG)
                    while 0 <= i < _SPEED_SCAN_CHUNK:
                        if (off + i) % 8 == 0:
                            hits.append((base + off + i, "<d", MELONDS_FPS[0]))
                        i = data.find(_MELONDS_FPS_SIG, i + 1)
                else:
                    i = data.find(_MGBA_SYNC_SIG)
                    while 0 <= i < _SPEED_SCAN_CHUNK:
                        if (off + i) % 4 == 0 and i + 0x14 <= len(data):
                            fps = struct.unpack_from("<f", data, i + 0x10)[0]
                            if 59.0 <= fps <= 61.0:
                                hits.append((base + off + i + 0x10, "<f", fps))
                        i = data.find(_MGBA_SYNC_SIG, i + 1)
                off += _SPEED_SCAN_CHUNK
                time.sleep(0)
        addr = base + size
    return hits[0] if len(hits) == 1 else None


_AZAHAR_LIMIT_LABEL = b"\x16frame_limit\x00"


def _find_azahar_speed_target(pm):
    import pymem.memory
    handle = pm.process_handle
    addr = 0
    while addr < 0x7FFFFFFF0000:
        try:
            mbi = pymem.memory.virtual_query(handle, addr)
        except Exception:
            break
        base, size = mbi.BaseAddress or 0, mbi.RegionSize
        if not size:
            break
        if mbi.State == 0x1000 and mbi.Type == 0x1000000 and mbi.Protect in (0x04, 0x08) and size < 0x10000000:
            off = 0
            while off < size:
                try:
                    data = pm.read_bytes(base + off, min(_SPEED_SCAN_CHUNK + 32, size - off))
                except Exception:
                    break
                i = data.find(_AZAHAR_LIMIT_LABEL)
                while 0 <= i < _SPEED_SCAN_CHUNK:
                    v = base + off + i - 0x20
                    try:
                        obj = pm.read_bytes(v - 0x18, 0x30)
                    except Exception:
                        obj = b""
                    if len(obj) == 0x30 and struct.unpack_from("<dd", obj, 0x20) == (100.0, 1000.0):
                        return (v if obj[0] else v - 0x10), "<d", 100.0
                    i = data.find(_AZAHAR_LIMIT_LABEL, i + 1)
                off += _SPEED_SCAN_CHUNK
                time.sleep(0)
        addr = base + size
    return None


def _speed_target():
    proc = CURRENT_EMULATOR_PROC
    t = _SPEED_TARGET
    if t["pid"] == proc.pid and t["addr"]:
        return t
    import pymem
    try:
        pm = pymem.Pymem()
        pm.open_process_from_id(proc.pid)
    except Exception:
        return None
    found = None
    for _ in range(8):
        found = (_find_azahar_speed_target(pm) if CURRENT_ENGINE_KEY == "azahar"
                 else _find_speed_target(pm, CURRENT_ENGINE_KEY))
        if found:
            break
        time.sleep(0.2)
    if not found:
        try:
            pm.close_process()
        except Exception:
            pass
        return None
    t.update(pid=proc.pid, addr=found[0], fmt=found[1], base=found[2], pm=pm)
    return t


def _write_speed(t, speed):
    want = struct.pack(t["fmt"], t["base"] * speed)
    if t["pm"].read_bytes(t["addr"], len(want)) != want:
        t["pm"].write_bytes(t["addr"], want, len(want))


def _speed_log(msg):
    if STATE:
        STATE.log("[Vitesse] " + msg)


def set_emulator_speed(speed):
    global CURRENT_SPEED
    if speed not in SPEED_STEPS or not _speed_available():
        return False
    t0 = time.time()
    if not _SPEED_LOCK.acquire(timeout=3):
        _speed_log(f"x{speed} refusé : réglage précédent toujours en cours")
        return False
    try:
        t = _speed_target()
        if not t:
            _speed_log(f"x{speed} impossible : cible introuvable dans {CURRENT_ENGINE_KEY} ({time.time() - t0:.2f} s)")
            return False
        try:
            _write_speed(t, speed)
        except Exception as e:
            _speed_log(f"x{speed} : écriture impossible ({e!r})")
            _forget_speed_target()
            return False
        CURRENT_SPEED = speed
    finally:
        _SPEED_LOCK.release()
    _set_emulator_priority(speed > 1)
    _speed_log(f"x{speed} appliqué ({CURRENT_ENGINE_KEY}, cible 0x{t['addr']:X}, {time.time() - t0:.2f} s)")
    return True


def _take_auto_reset():
    hit = SPEED_AUTO_RESET["pending"]
    SPEED_AUTO_RESET["pending"] = False
    return hit


def _set_emulator_priority(fast):
    proc = CURRENT_EMULATOR_PROC
    if proc is None:
        return
    try:
        k = ctypes.windll.kernel32
        k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k.SetPriorityClass(ctypes.c_void_p(int(proc._handle)), 0x4000 if fast else 0x20)
    except Exception:
        pass


def _speed_watchdog_loop():
    u = ctypes.windll.user32
    u.SendMessageTimeoutW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t,
                                      ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]
    u.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    res = ctypes.c_size_t()
    misses = {"émulateur": 0, "fenêtre PKLab": 0}
    while True:
        time.sleep(0.5)
        h = CURRENT_CANVAS_HWND
        if CURRENT_SPEED == 1 or not h:
            misses = dict.fromkeys(misses, 0)
            continue
        for name, w in (("émulateur", h), ("fenêtre PKLab", OWN_HWND)):
            if not w:
                continue
            try:
                ok = u.SendMessageTimeoutW(w, 0, 0, 0, 0x0002, 400, ctypes.byref(res))
            except Exception:
                ok = 1
            if ok:
                misses[name] = 0
                continue
            misses[name] += 1
            _speed_log(f"{name} ne répond pas ({misses[name]}/3) à x{CURRENT_SPEED}")
        bad = [n for n, m in misses.items() if m >= 3]
        if bad:
            misses = dict.fromkeys(misses, 0)
            if set_emulator_speed(1):
                SPEED_AUTO_RESET["pending"] = True
                _speed_log("remise à x1 : " + ", ".join(bad) + " ne répondait plus")


_FPS_TITLE = (re.compile(r"\((\d+(?:[.,]\d+)?)\s*(?:ips|fps)\)", re.I), re.compile(r"\[(\d+)/\d+\]"))


def emulator_fps():
    h = CURRENT_CANVAS_HWND
    if not h or not _speed_available():
        return None
    try:
        buf = ctypes.create_unicode_buffer(256)
        _user32().GetWindowTextW(h, buf, 256)
    except Exception:
        return None
    for rx in _FPS_TITLE:
        m = rx.search(buf.value)
        if m:
            return round(float(m.group(1).replace(",", ".")))
    return None


def keep_emulator_speed():
    if CURRENT_SPEED == 1 or not _speed_available():
        return
    with _SPEED_LOCK:
        t = _SPEED_TARGET
        if t["addr"] and t["pid"] == CURRENT_EMULATOR_PROC.pid:
            try:
                _write_speed(t, CURRENT_SPEED)
            except Exception:
                pass


def _forget_speed_target():
    pm = _SPEED_TARGET["pm"]
    _SPEED_TARGET.update(pid=None, addr=None, fmt=None, base=None, pm=None)
    if pm:
        try:
            pm.close_process()
        except Exception:
            pass


def _reset_speed_state():
    global CURRENT_SPEED
    with _SPEED_LOCK:
        CURRENT_SPEED = 1
        _forget_speed_target()


CURRENT_EMULATOR_PROC = None
CURRENT_ENGINE_KEY = None


def _emulator_audio_session():
    if not _PYCAW_AVAILABLE or CURRENT_EMULATOR_PROC is None or CURRENT_EMULATOR_PROC.poll() is not None:
        return None
    pid = CURRENT_EMULATOR_PROC.pid
    try:
        for session in AudioUtilities.GetAllSessions():
            if session.ProcessId == pid:
                return session.SimpleAudioVolume
    except Exception:
        pass
    return None


EMULATOR_PID_FILE = os.path.join(BASE_DIR, ".emulator_pid")


def _write_emulator_pid_file(pid, exe_path):
    try:
        with open(EMULATOR_PID_FILE, "w") as f:
            f.write(f"{pid}:{os.path.basename(exe_path)}")
    except Exception:
        pass


def _clear_emulator_pid_file():
    try:
        os.remove(EMULATOR_PID_FILE)
    except Exception:
        pass


def _kill_stale_emulator():
    try:
        with open(EMULATOR_PID_FILE, "r") as f:
            pid_str, exe_name = f.read().strip().split(":", 1)
    except Exception:
        return
    _clear_emulator_pid_file()
    try:
        subprocess.run(
            ["taskkill", "/F", "/FI", f"PID eq {pid_str}", "/FI", f"IMAGENAME eq {exe_name}"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


def stop_emulator():
    global CURRENT_EMULATOR_PROC, CURRENT_CANVAS_HWND, CURRENT_EMBEDDED_HMENU, _LAST_RESIZE_PARAMS
    _reset_speed_state()
    proc = CURRENT_EMULATOR_PROC
    CURRENT_EMULATOR_PROC = None
    CURRENT_CANVAS_HWND = None
    CURRENT_EMBEDDED_HMENU = None
    _LAST_RESIZE_PARAMS = None
    _clear_emulator_pid_file()
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        pass


MELONDS_KEYBOARD_DEFAULTS = {
    "Up": 16777235, "Down": 16777237, "Left": 16777234, "Right": 16777236,
    "A": 88, "B": 90, "X": 83, "Y": 65,
    "L": 81, "R": 87, "Start": 16777220, "Select": 16777219,
}


def _toml_line_key(line):
    return line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None


def _toml_force(lines, section, key, value):
    sec = next((i for i, l in enumerate(lines) if l.strip() == section), None)
    if sec is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines += ["\n", section + "\n", f"{key} = {value}\n"]
        return
    end = next((i for i in range(sec + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
    pos = next((i for i in range(sec + 1, end) if _toml_line_key(lines[i]) == key), None)
    if pos is None:
        lines.insert(sec + 1, f"{key} = {value}\n")
    else:
        lines[pos] = f"{key} = {value}\n"


def _ensure_melonds_keyboard_defaults(melonds_dir):
    toml_path = os.path.join(melonds_dir, "melonDS.toml")
    top = {"TargetFPS": f"{MELONDS_FPS[0]:.1f}", "LimitFPS": "true", "FastForwardFPS": f"{MELONDS_FPS[1]:.1f}",
           "SlowmoFPS": f"{MELONDS_FPS[2]:.1f}"}
    try:
        try:
            with open(toml_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            lines = []
        first_section = next((i for i, l in enumerate(lines) if l.strip().startswith("[")), len(lines))
        seen = set()
        for i in range(first_section):
            k = _toml_line_key(lines[i])
            if k in top:
                lines[i] = f"{k} = {top[k]}\n"
                seen.add(k)
        missing = [f"{k} = {v}\n" for k, v in top.items() if k not in seen]
        lines[first_section:first_section] = missing
        start = next((i for i, l in enumerate(lines) if l.strip() == "[Instance0.Keyboard]"), None)
        if start is None:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            lines += ["\n", "[Instance0.Keyboard]\n"]
            start = len(lines) - 1
        end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
        found = set()
        for i in range(start + 1, end):
            k = _toml_line_key(lines[i])
            if k is None:
                continue
            val = lines[i].split("=", 1)[1].strip()
            if k in MELONDS_KEYBOARD_DEFAULTS:
                found.add(k)
                if val == "-1":
                    lines[i] = f"{k} = {MELONDS_KEYBOARD_DEFAULTS[k]}\n"
        lines[end:end] = [f"{k} = {v}\n" for k, v in MELONDS_KEYBOARD_DEFAULTS.items() if k not in found]
        _toml_force(lines, "[JIT]", "Enable", "true")
        _toml_force(lines, "[Screen]", "UseGL", "true")
        with open(toml_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception:
        pass


def launch_emulator(engine_key, rom_path, load_state=False):
    cfg = EMULATOR_BUNDLES.get(engine_key)
    if not cfg:
        return False, "Moteur inconnu"
    if not rom_path or not os.path.exists(rom_path):
        return False, "ROM introuvable"
    state = state1_path(engine_key, rom_path) if load_state else None
    if load_state and not (state and os.path.isfile(state)):
        return False, "Aucune sauvegarde dans le state 1 pour ce jeu"
    if engine_key == "azahar":
        exe = os.path.join(AZAHAR_DIR, cfg["exe_name"])
        if not os.path.isfile(exe):
            return False, "AZAHAR_MISSING"
    else:
        exe = _ensure_bundled_extracted(engine_key)
    if not exe:
        return False, "Exécutable introuvable dans l'appli"
    global EMBED_DESIRED_VISIBLE, CURRENT_ENGINE_KEY
    EMBED_DESIRED_VISIBLE = True
    CURRENT_ENGINE_KEY = engine_key
    if engine_key == "melonds":
        _ensure_melonds_keyboard_defaults(os.path.dirname(exe))
        for key in gen4_maps.REPO_BY_GAME:
            gen4_maps.set_rom_path(key, rom_path)
        for key in gen5_maps.GAMES:
            gen5_maps.set_rom_path(key, rom_path)
    elif engine_key == "azahar":
        hit = rom_finder.identify(rom_path)
        if hit:
            ctr_maps.set_rom_path(hit[1], rom_path)
    elif rom_path.lower().endswith(GBC_EXTS):
        global GEN2_ROM_PATH
        GEN2_ROM_PATH = rom_path
    else:
        gen3_maps.set_rom_path(rom_path)
    load_rom_side_data(rom_path)
    args = [exe, rom_path]
    if cfg["needs_script"]:
        args += ["--script", _bridge_script(rom_path)]
    if state and engine_key == "mgba":
        args += ["-t", state]
    _kill_stale_emulator()
    stop_emulator()
    if engine_key == "mgba":
        _prepare_mgba_config()
    if engine_key == "azahar":
        _prepare_azahar_config()
    try:
        proc = subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW,
                                cwd=os.path.dirname(exe) if engine_key == "azahar" else None)
        global CURRENT_EMULATOR_PROC
        CURRENT_EMULATOR_PROC = proc
        _write_emulator_pid_file(proc.pid, cfg["exe_name"])
        try:
            _speed_log(f"lancement {cfg['label']} ({os.path.getsize(exe)} octets, PKLab {paths.APP_VERSION}, {os.cpu_count()} cœurs)")
        except OSError:
            pass
        if cfg["needs_script"]:
            threading.Thread(target=_hide_window_by_title, args=(proc.pid, "Script"), daemon=True).start()
        threading.Thread(target=embed_emulator_window, args=(engine_key, proc.pid), daemon=True).start()
        if state and engine_key in ("melonds", "azahar"):
            threading.Thread(target=_load_state1_when_ready, args=(proc,), daemon=True).start()
        return True, None
    except Exception as e:
        return False, str(e)


_HACKMODE_RAW = []


def read_hackmode_raw():
    if not _HACKMODE_RAW:
        try:
            with open(HACKMODE_OVERRIDE_PATH, "r", encoding="utf-8") as f:
                _HACKMODE_RAW.append(f.read().strip() or None)
        except OSError:
            _HACKMODE_RAW.append(None)
    return _HACKMODE_RAW[0]


def read_hackmode_override():
    v = read_hackmode_raw()
    if v in ("on", "true"):
        return True
    if v in ("off", "false"):
        return False
    return None


GEN5_ITEM_POCKET = {1: "bag_items", 50: "bag_medicine"}
GEN5_CHEATS = {
    "master_ball": {"label": "Master Ball", "items": [(1, 999)]},
    "rare_candy": {"label": "Super Bonbon", "items": [(50, 999)]},
    "money": {"label": "Argent", "money": True},
}
BAG_SLOT_SIZE = 4
BAG_SCAN_SLOTS = 60
BAG_STACK_CAP = 99
MAX_MONEY = 999999


GEN3_CHEATS = {
    "master_ball": "Master Ball",
    "rare_candy": "Super Bonbon",
    "money": "Argent",
}
GEN3_CHEAT_REQUEST_PATH = os.path.join(BASE_DIR, "gen3_cheat_request.txt")
GEN3_CHEAT_RESULT_PATH = os.path.join(BASE_DIR, "gen3_cheat_result.txt")
GEN3_CHEAT_TIMEOUT = 2.0


def _enrich_encounter(mon, hack_mode):
    data = engine.get_species_data(mon["species"], hack_mode)
    name = data[0] if data else "???"
    out = dict(mon)
    out["name"] = name
    return out


def give_cheat_item_gen3(cheat_key):
    if cheat_key not in GEN3_CHEATS:
        return False, "Triche inconnue"
    for path in (GEN3_CHEAT_REQUEST_PATH, GEN3_CHEAT_RESULT_PATH):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    with open(GEN3_CHEAT_REQUEST_PATH, "w", encoding="utf-8") as f:
        f.write(cheat_key)
    deadline = time.time() + GEN3_CHEAT_TIMEOUT
    while time.time() < deadline:
        try:
            with open(GEN3_CHEAT_RESULT_PATH, "r", encoding="utf-8") as f:
                result = f.read().strip()
        except FileNotFoundError:
            time.sleep(0.05)
            continue
        try:
            os.remove(GEN3_CHEAT_RESULT_PATH)
        except FileNotFoundError:
            pass
        if result == "ok" or result.startswith("ok:"):
            return True, None
        if result.startswith("error:"):
            return False, result[len("error:"):]
        return False, result or "Echec"
    return False, "Le script mGBA ne répond pas (vérifie qu'il est bien chargé)"


GEN4_ITEM_POCKET = {1: "bag_balls", 50: "bag_items"}


def _give_item_host(pm, pocket_host_addr, item_id, add_qty, cap=BAG_STACK_CAP):
    for i in range(BAG_SCAN_SLOTS):
        addr = pocket_host_addr + i * BAG_SLOT_SIZE
        try:
            slot_item = pm.read_ushort(addr)
            slot_qty = pm.read_ushort(addr + 2)
        except Exception:
            return False
        if slot_item == item_id:
            pm.write_ushort(addr + 2, min(slot_qty + add_qty, cap))
            return True
        if slot_item == 0 and slot_qty == 0:
            pm.write_ushort(addr, item_id)
            pm.write_ushort(addr + 2, min(add_qty, cap))
            return True
    return False


def give_cheat_item_nds(cheat):
    reader, party_nds = STATE.nds, STATE.nds_party_addr
    if reader is None or party_nds is None:
        return False, "Partie du joueur non localisée (es-tu bien en jeu ?)"
    pm = STATE.mem.pm
    if cheat.get("money"):
        addr = reader.save_addr(party_nds, "money")
        if addr is None:
            return False, "Adresse argent non configurée pour ce jeu"
        try:
            if pm.read_uint(reader.host(addr)) > MAX_MONEY:
                return False, "Adresse argent non confirmée (valeur actuelle improbable)"
            pm.write_uint(reader.host(addr), MAX_MONEY)
        except Exception:
            return False, "Lecture mémoire impossible"
        return True, None
    pockets = GEN4_ITEM_POCKET if reader.gen == 4 else GEN5_ITEM_POCKET
    for item_id, qty in cheat["items"]:
        addr = reader.save_addr(party_nds, pockets.get(item_id, ""))
        if addr is None:
            return False, "Objet non configuré"
        if not _give_item_host(pm, reader.host(addr), item_id, qty):
            return False, "Sac plein (aucun emplacement libre trouvé)"
    return True, None


def give_cheat_item_3ds(cheat_key):
    reader = STATE.ctr if STATE else None
    if reader is None or not STATE.ctr_game_key:
        return False, "Aucun jeu 3DS détecté"
    if cheat_key not in reader.cheats():
        return False, "Triche non disponible pour ce jeu"
    if not STATE.last_player_entries:
        return False, "Partie du joueur non localisée (es-tu bien en jeu ?)"
    cheat = GEN5_CHEATS[cheat_key]
    if cheat.get("money"):
        return reader.set_max_money()
    for item_id, qty in cheat["items"]:
        ok, err = reader.give_item(item_id, qty)
        if not ok:
            return False, err
    return True, None


def give_cheat_item(cheat_key):
    if CURRENT_ENGINE_KEY == "azahar":
        return give_cheat_item_3ds(cheat_key)
    if read_gen3_raw() is not None:
        return give_cheat_item_gen3(cheat_key)
    if STATE is None or STATE.mem is None or STATE.nds is None:
        return False, "Aucun jeu détecté"
    cheat = GEN5_CHEATS.get(cheat_key)
    if not cheat:
        return False, "Triche inconnue"
    return give_cheat_item_nds(cheat)


class State:
    def __init__(self):
        self.mem = None
        self.hack_mode = False
        self.tick = 0
        self.last_signature = ""
        self.last_write_time = 0
        self.last_output_json = None
        self.last_player_entries = []
        self.player_empty_streak = 0
        self.minimap_game_key = None
        self.minimap_map_key = None
        self.minimap_bundle = None
        self.minimap_pos = None
        self.minimap_pending = None
        self.nds = None
        self.nds_game_key = None
        self.nds_party_addr = None
        self.nds_last_locate = 0.0
        self.nds_lost_since = None
        self.nds_in_battle = False
        self.ctr = None
        self.ctr_game_key = None
        self.ctr_last_detect = 0.0

    def log(self, msg):
        try:
            print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)
        except Exception:
            pass
        if msg.startswith(("[NDS", "Erreur", "[Vitesse", "Boucle")):
            try:
                with open(DETECTION_LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            except Exception:
                pass

    def request_redetect(self):
        global _GEN3_LAST_RAW
        _GEN3_LAST_RAW = None
        try:
            os.remove(GEN3_RAW_PATH)
        except OSError:
            pass
        self.last_output_json = None
        self.last_signature = ""
        self.last_player_entries = []
        self.minimap_game_key = None
        self.minimap_map_key = None
        self.minimap_bundle = None
        self.minimap_pos = None
        self.minimap_pending = None
        self.mem = None
        self.nds = None
        self.nds_game_key = None
        self.nds_party_addr = None
        self.nds_last_locate = 0.0
        self.nds_lost_since = None
        self.nds_in_battle = False
        if self.ctr is not None:
            self.ctr.close()
        self.ctr = None
        self.ctr_game_key = None
        self.ctr_last_detect = 0.0

    def tick_once_azahar(self):
        if self.ctr is None:
            self.ctr = azahar_reader.AzaharReader(pid=CURRENT_EMULATOR_PROC.pid if CURRENT_EMULATOR_PROC else None)
        now = time.time()
        if self.ctr_game_key is None:
            if now - self.ctr_last_detect < 1.0:
                return
            self.ctr_last_detect = now
            self.ctr_game_key = self.ctr.detect()
            if self.ctr_game_key is None:
                return
            self.log(f"[3DS] {self.ctr_game_key} détecté")
        party = self.ctr.party()
        if party is None:
            self.ctr_game_key = None
            return
        player_entries = []
        for slot, mon in enumerate(party):
            data = engine.get_species_data(mon["species"], engine.GEN6, mon.get("form") or 0)
            if data:
                name, t1, t2 = data
                player_entries.append({"label": str(slot + 1), "mon": mon, "name": name, "t1": t1, "t2": t2})
        opp = self.ctr.opponents(party, now)
        if len(opp) == 1:
            entries, battle_type = [("Wild", opp[0])], "wild"
        elif opp:
            entries, battle_type = [(str(i + 1), m) for i, m in enumerate(opp)], "trainer"
        else:
            entries, battle_type = [], None
        self._write_output(self.ctr_game_key, entries, player_entries, battle_type, hack_mode=engine.GEN6)
        pos = self.ctr.position()
        if pos is not None:
            pos = {"x": 0, "y": 0, "mapGroup": 0, "mapNum": pos["zone"]}
        self._update_minimap(self.ctr_game_key, pos,
                             fetch_bundle=lambda key, p: ctr_maps.get_zone_bundle(key, p["mapNum"]))

    def attach_emulator(self):
        mem = NdsMemory("melonDS.exe")
        try:
            mem.attach()
        except NdsEmulatorNotFound:
            return False
        self.mem = mem
        self.log("melonDS détecté.")
        return True

    def tick_once_nds(self):
        hm_override = read_hackmode_override()
        if hm_override is not None:
            self.hack_mode = hm_override

        if self.nds is not None and self.nds.mem is not self.mem:
            self.nds = None
        if self.nds is None:
            now = time.time()
            if now - self.nds_last_locate < NDS_LOCATE_INTERVAL:
                return self.nds_game_key is not None
            self.nds_last_locate = now
            found = NdsReader.find_main_ram(self.mem)
            if found is None:
                self.nds_game_key = None
                return False
            self.nds_game_key = found[1]
            self.nds = NdsReader.locate(self.mem, found)
            if self.nds is None:
                return True
            where = (f"pointeur de sauvegarde à 0x{self.nds.ptr_addr:08X}" if self.nds.ptr_addr is not None
                     else f"decalage {self.nds.delta:+#x}")
            self.log(f"[NDS] {found[1]} : {where}")

        try:
            snap = self.nds.snapshot()
        except Exception:
            snap = None
        now = time.time()
        if snap is None:
            if self.nds_lost_since is None:
                self.nds_lost_since = now
            elif now - self.nds_lost_since > NDS_LOST_GRACE_S:
                self.log(f"[NDS] données illisibles depuis {NDS_LOST_GRACE_S:.0f}s, nouvelle localisation")
                self.nds = None
                self.nds_party_addr = None
                self.nds_lost_since = None
            return True
        self.nds_lost_since = None
        party_addr, party, opponents, in_battle = snap
        self.nds_party_addr = party_addr

        if in_battle != self.nds_in_battle:
            self.nds_in_battle = in_battle
            self.log("[NDS] début de combat" if in_battle else "[NDS] fin de combat")

        player_entries = []
        for slot, mon in enumerate(party):
            data = engine.get_species_data(mon["species"], self.hack_mode)
            if data:
                name, t1, t2 = data
                player_entries.append({"label": str(slot + 1), "mon": mon, "name": name, "t1": t1, "t2": t2})

        entries = []
        battle_type = None
        if in_battle and opponents:
            if len(opponents) == 1:
                entries = [("Wild", opponents[0])]
                battle_type = "wild"
            else:
                entries = [(str(i + 1), m) for i, m in enumerate(opponents)]
                battle_type = "trainer"

        self._write_output(self.nds_game_key, entries, player_entries, battle_type)
        loc = self.nds.read_location(party_addr)
        if loc is not None:
            loc = {"x": loc["x"], "y": loc["y"], "mapGroup": 0, "mapNum": loc["zone"]}
        self._update_minimap(self.nds_game_key, loc,
                             fetch_bundle=lambda key, pos: (gen5_maps if key in gen5_maps.GAMES else gen4_maps).get_zone_bundle(
                                 key, pos["mapNum"], progress=self.log, scan_dirs=rom_scan_dirs()))
        return True

    def tick_once_gen3_lua(self, raw):
        hm_override = read_hackmode_override()
        if hm_override is not None:
            self.hack_mode = hm_override

        player_entries = []
        for i, raw_mon in enumerate(raw.get("player", [])):
            mon = gen3_engine.finalize_gen3_mon(raw_mon)
            data = engine.get_species_data(mon["species"], self.hack_mode)
            if data:
                name, t1, t2 = data
                player_entries.append({"label": str(i + 1), "mon": mon, "name": name, "t1": t1, "t2": t2})

        entries = []
        battle_type = None
        enemy_raw = raw.get("enemy") or []
        if enemy_raw:
            mon = gen3_engine.finalize_gen3_mon(enemy_raw[0])
            entries.append(("Wild", mon))
            battle_type = "wild"

        active_key = gen3_game_key_from_code(raw.get("game")) or "EMERALD"
        self._write_output(active_key, entries, player_entries, battle_type)
        self._update_minimap(active_key, raw.get("pos"))

    def tick_once_gen2(self, raw):
        hm_override = read_hackmode_override()
        if hm_override is not None:
            self.hack_mode = hm_override
        player_entries = []
        for i, r in enumerate(raw.get("player") or []):
            mon = finalize_gen2_mon(r)
            data = engine.get_species_data(mon["species"], self.hack_mode)
            if data:
                name, t1, t2 = data
                player_entries.append({"label": str(i + 1), "mon": mon, "name": name, "t1": t1, "t2": t2})
        enemy = [finalize_gen2_mon(r) for r in raw.get("enemy") or []]
        kind = raw.get("battle") if enemy else None
        if kind == "trainer":
            entries = [(str(i + 1), m) for i, m in enumerate(enemy)]
        elif kind:
            entries, kind = [("Wild", enemy[0])], "wild"
        else:
            entries = []
        key = gen3_game_key_from_code(raw.get("game")) or "CRYSTAL"
        self._write_output(key, entries, player_entries, kind)
        tod = raw.get("tod")
        tod = {0: 0, 1: 1, 2: 2}.get(tod, 1)
        if tod != getattr(self, "gen2_tod", None):
            self.gen2_tod = tod
            if self.minimap_game_key == key:
                self.minimap_map_key = None
        names = lambda sp: (engine.get_species_data(sp, False) or (f"#{sp}",))[0]
        self._update_minimap(key, raw.get("pos"), fetch_bundle=lambda k, pos: gen2_maps.get_map_bundle(
            gen2_rom_for(k), pos["mapGroup"], pos["mapNum"], tod, names))

    def _update_minimap(self, game_key, pos, fetch_bundle=None):
        if pos is None:
            self.minimap_pos = None
            self.minimap_pending = None
            return
        if game_key != self.minimap_game_key:
            self.minimap_game_key = game_key
            self.minimap_map_key = None
            self.minimap_bundle = None
        map_key = (pos["mapGroup"], pos["mapNum"])

        candidate = (pos["x"], pos["y"], map_key)
        if candidate != self.minimap_pending:
            self.minimap_pending = candidate
            return
        if map_key == self.minimap_map_key and self.minimap_bundle:
            w = self.minimap_bundle.get("width")
            h = self.minimap_bundle.get("height")
            ox = self.minimap_bundle.get("originX", 0)
            oy = self.minimap_bundle.get("originY", 0)
            if w and h and not (0 <= pos["x"] - ox < w and 0 <= pos["y"] - oy < h):
                return
        self.minimap_pos = pos
        if map_key == self.minimap_map_key:
            return
        self.minimap_map_key = map_key
        try:
            if fetch_bundle is not None:
                self.minimap_bundle = fetch_bundle(game_key, pos)
            else:
                self.minimap_bundle = gen3_maps.get_map_bundle(game_key, pos["mapGroup"], pos["mapNum"], progress=self.log,
                                                               scan_dirs=rom_scan_dirs())
        except Exception as e:
            self.log(f"Erreur rendu minimap: {e}")
            self.minimap_bundle = None

    def _write_output(self, active_key, entries, player_entries, battle_type, hack_mode=None):
        hack_mode = self.hack_mode if hack_mode is None else hack_mode
        player_entries = [pe for pe in player_entries if (pe["mon"]["hpMax"] or 0) > 1]

        if player_entries:
            self.last_player_entries = player_entries
            self.player_empty_streak = 0
        else:
            self.player_empty_streak += 1
            if self.player_empty_streak < PLAYER_EMPTY_STREAK_TO_CLEAR:
                player_entries = self.last_player_entries
            else:
                self.last_player_entries = []

        signature = ",".join(str(m["species"]) for _, m in entries) + "|" + ",".join(str(pe["mon"]["species"]) for pe in player_entries)

        now = time.time()
        if signature != self.last_signature or (now - self.last_write_time) >= HEARTBEAT_INTERVAL:
            self.last_write_time = now
            self.tick += 1
            mons_json = [engine.serialize_mon(label, mon, hack_mode, player_entries) for label, mon in entries]
            player_json = [engine.serialize_mon(pe["label"], pe["mon"], hack_mode, None) for pe in player_entries]
            data = {
                "game": active_key,
                "romFiche": os.path.basename(ROM_SIDE_PATH) if ROM_SIDE_PATH else None,
                "updated": int(time.time()),
                "tick": self.tick,
                "battleType": battle_type,
                "mons": [m for m in mons_json if m],
                "playerMons": [m for m in player_json if m],
            }
            self.last_output_json = json.dumps(data, ensure_ascii=False).encode("utf-8")

        self.last_signature = signature


SHINY_ATK_DV = {2, 3, 6, 7, 10, 11, 14, 15}


def finalize_gen2_mon(r):
    dv = r.get("dv") or {}
    atk, df, spe, spc = (int(dv.get(k, 0)) for k in ("atk", "def", "spe", "spc"))
    hp = (atk & 1) << 3 | (df & 1) << 2 | (spe & 1) << 1 | (spc & 1)
    return {"species": r["species"], "hpCur": r["hpCur"], "hpMax": r["hpMax"], "level": r["level"],
            "ability": None, "nature": None, "pid": None,
            "ivs": {"hp": hp, "atk": atk, "def": df, "spa": spc, "spd": spc, "spe": spe, "dv": True},
            "shiny": df == 10 and spe == 10 and spc == 10 and atk in SHINY_ATK_DV}


def poll_loop(state):
    while True:
        delay = POLL_INTERVAL
        t_iter = time.time()
        try:
            keep_emulator_speed()
            gen3_raw = read_gen3_raw()
            if gen3_raw is not None and gen3_raw.get("gen") == 2:
                state.tick_once_gen2(gen3_raw)
            elif gen3_raw is not None:
                state.tick_once_gen3_lua(gen3_raw)
            elif CURRENT_ENGINE_KEY == "azahar" and CURRENT_EMULATOR_PROC is not None and CURRENT_EMULATOR_PROC.poll() is None:
                state.tick_once_azahar()
            elif (state.mem is not None and state.mem.process_alive()) or state.attach_emulator():
                if not state.tick_once_nds():
                    delay = NDS_LOCATE_INTERVAL
            else:
                state.mem = None
                delay = 0.5
        except Exception as e:
            alive = False
            try:
                alive = state.mem is not None and state.mem.process_alive()
            except Exception:
                pass
            state.log(f"Erreur boucle principale ({'émulateur toujours actif' if alive else 'émulateur fermé'}): {e!r}")
            if not alive:
                state.mem = None
            delay = POLL_INTERVAL if alive else 2
        took = time.time() - t_iter
        if took > 3:
            state.log(f"Boucle principale lente : {took:.1f} s (vitesse x{CURRENT_SPEED})")
        time.sleep(delay)


STATE = None


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def translate_path(self, path):
        p = super().translate_path(path)
        if not os.path.exists(p) and paths.FROZEN:
            rel = os.path.relpath(p, self.directory)
            if not rel.startswith(".."):
                return os.path.join(paths.RES_DIR, rel)
        return p

    def _local(self):
        hosts = (f"localhost:{PORT}", f"127.0.0.1:{PORT}")
        origin = self.headers.get("Origin")
        if self.headers.get("Host", "") in hosts and (origin is None or origin in tuple("http://" + h for h in hosts)):
            return True
        self.send_response(403)
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _send_json(self, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._local():
            return
        if self.path.split("?")[0] == "/pokemon_battle_data.json":
            body = (STATE.last_output_json if STATE and STATE.last_output_json is not None
                    else b'{"game":null,"tick":0,"battleType":null,"mons":[],"playerMons":[]}')
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/hackmode":
            v = read_hackmode_raw() or ""
            self._send_json({"hackMode": v})
            return
        if self.path == "/api/emulators":
            self._send_json({
                "engines": [{"key": k, "label": v["label"], "romExt": v["rom_ext"], "romExts": v.get("rom_exts", [v["rom_ext"]])} for k, v in EMULATOR_BUNDLES.items()],
            })
            return
        if self.path.startswith("/api/roms"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            engine_key = (qs.get("engine") or [""])[0]
            if (qs.get("rescan") or [""])[0] == "1":
                ROM_INDEX.start(force=True)
            found = ROM_INDEX.roms(engine_key) if engine_key in EMULATOR_BUNDLES else []
            self._send_json({"roms": [r["path"] for r in found], "found": found, "scanning": ROM_INDEX.scanning})
            return
        if self.path.startswith("/api/state1"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            st = state1_path((qs.get("engine") or [""])[0], (qs.get("rom") or [""])[0])
            self._send_json({"exists": bool(st and os.path.isfile(st))})
            return
        if self.path == "/api/rom-fiche":
            side = ROM_SIDE_PATH
            if not side or not os.path.isfile(side):
                self._send_json({"ok": False})
                return
            with open(side, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/saves":
            self._send_json({"saves": save_files()})
            return
        if self.path == "/api/rando-roms":
            self._send_json({"roms": rando_roms()})
            return
        if self.path == "/api/shiny-roms":
            self._send_json({"roms": shiny_roms()})
            return
        if self.path == "/api/created-roms":
            self._send_json({"roms": created_roms()})
            return
        if self.path.startswith("/api/check-update"):
            self._send_json({"ok": True, "version": APP_VERSION, "configured": bool(UPDATE_REPO)}
                            if "local=1" in self.path else check_update())
            return
        if self.path == "/api/embedded-menu":
            self._send_json({"menu": get_embedded_menu()})
            return
        if self.path == "/api/cheats":
            available = []
            gen3_raw = read_gen3_raw()
            if CURRENT_ENGINE_KEY == "azahar":
                if STATE and STATE.ctr and STATE.ctr_game_key:
                    available = [{"key": k, "label": GEN5_CHEATS[k]["label"]} for k in STATE.ctr.cheats()]
            elif gen3_raw is not None:
                if gen3_game_key_from_code(gen3_raw.get("game")):
                    available = [{"key": k, "label": v} for k, v in GEN3_CHEATS.items()]
            elif STATE and STATE.mem and STATE.nds_game_key in GAMES:
                game = GAMES[STATE.nds_game_key]
                has_money = "money" in game.get("live_offsets", {}) or "money" in game.get("addrs", {})
                available = [{"key": k, "label": v["label"]} for k, v in GEN5_CHEATS.items()
                             if not v.get("money") or has_money]
            self._send_json({"cheats": available})
            return
        if self.path == "/api/detect-status":
            gen3_raw = read_gen3_raw()
            if gen3_raw is not None:
                key = gen3_game_key_from_code(gen3_raw.get("game"))
                self._send_json({"detected": key is not None and bool(gen3_raw.get("player")), "game": key})
                return
            if STATE and STATE.ctr_game_key and CURRENT_ENGINE_KEY == "azahar":
                self._send_json({"detected": bool(STATE.last_player_entries), "game": STATE.ctr_game_key})
                return
            nds = STATE.nds if STATE and STATE.mem else None
            self._send_json({"detected": nds is not None, "game": nds.key if nds else None})
            return
        if self.path == "/api/azahar-install":
            st = azahar_setup.status()
            st["installed"] = azahar_setup.installed(AZAHAR_DIR)
            self._send_json(st)
            return
        if self.path == "/api/volume":
            vol = _emulator_audio_session()
            if vol is None:
                self._send_json({"available": False, "volume": None, "muted": None})
                return
            try:
                self._send_json({
                    "available": True,
                    "volume": round(vol.GetMasterVolume() * 100),
                    "muted": bool(vol.GetMute()),
                })
            except Exception:
                self._send_json({"available": False, "volume": None, "muted": None})
            return
        if self.path == "/api/fast-forward":
            self._send_json({"available": _speed_available(), "speed": CURRENT_SPEED, "speeds": list(SPEED_STEPS), "fps": emulator_fps(),
                             "autoReset": _take_auto_reset()})
            return
        if self.path == "/api/minimap":
            if STATE and STATE.minimap_bundle and STATE.minimap_pos:
                bundle = dict(STATE.minimap_bundle)
                bundle["playerX"] = STATE.minimap_pos["x"]
                bundle["playerY"] = STATE.minimap_pos["y"]
                hack_mode = STATE.hack_mode
                if "originX" in bundle:
                    bundle["playerX"] -= bundle.pop("originX")
                    bundle["playerY"] -= bundle.pop("originY")
                if "dotX" in bundle:
                    bundle["playerX"] = bundle.pop("dotX")
                    bundle["playerY"] = bundle.pop("dotY")
                if "gen4Game" in bundle:
                    hour = time.localtime().tm_hour
                    bundle["encounters"] = gen4_maps.build_encounters(bundle.pop("gen4Game"), bundle.pop("gen4Raw"), hour)
                    bundle["timeOfDay"] = gen4_maps.TIME_OF_DAY_LABELS[gen4_maps.time_of_day(hour)]
                enc = bundle.get("encounters")
                if enc:
                    bundle["encounters"] = {
                        cat: [_enrich_encounter(mon, hack_mode) for mon in mons]
                        for cat, mons in enc.items()
                    }
                self._send_json(bundle)
            else:
                self._send_json({})
            return
        super().do_GET()

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        try:
            return json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            return {}

    def do_HEAD(self):
        if self._local():
            super().do_HEAD()

    def do_POST(self):
        if not self._local():
            return
        if self.path == "/api/hackmode":
            data = self._read_json_body()
            hack = "on" if data.get("hackMode") else "off"
            _HACKMODE_RAW[:] = [hack]
            try:
                with open(HACKMODE_OVERRIDE_PATH, "w", encoding="utf-8") as f:
                    f.write(hack)
            except OSError:
                pass
            self._send_json({"ok": True, "hackMode": hack})
            return
        if self.path == "/api/lang":
            i18n.set_lang(str(self._read_json_body().get("lang", "")))
            self._send_json({"ok": True, "lang": i18n.LANG})
            return
        if self.path == "/api/redetect":
            if STATE:
                STATE.request_redetect()
            self._send_json({"ok": True})
            return
        if self.path == "/api/give-cheat":
            data = self._read_json_body()
            ok, err = give_cheat_item(str(data.get("cheat", "")).strip())
            self._send_json({"ok": ok, "error": err})
            return
        if self.path == "/api/volume":
            data = self._read_json_body()
            vol = _emulator_audio_session()
            ok = False
            if vol is not None:
                try:
                    if "volume" in data and data["volume"] is not None:
                        v = max(0, min(100, int(data["volume"])))
                        vol.SetMasterVolume(v / 100.0, None)
                    if "muted" in data and data["muted"] is not None:
                        vol.SetMute(bool(data["muted"]), None)
                    ok = True
                except Exception:
                    ok = False
            self._send_json({"ok": ok, "available": vol is not None})
            return
        if self.path == "/api/fast-forward":
            data = self._read_json_body()
            try:
                speed = int(data.get("speed", 1))
            except (TypeError, ValueError):
                speed = 1
            applied = set_emulator_speed(speed)
            self._send_json({"ok": applied, "speed": CURRENT_SPEED})
            return
        if self.path == "/api/embed-visibility":
            data = self._read_json_body()
            visible = bool(data.get("visible", True))
            global EMBED_DESIRED_VISIBLE
            EMBED_DESIRED_VISIBLE = visible
            ok = False
            user32 = _user32()
            if CURRENT_CANVAS_HWND and user32.IsWindow(CURRENT_CANVAS_HWND):
                user32.ShowWindow(CURRENT_CANVAS_HWND, SW_SHOW if visible else SW_HIDE)
                ok = True
            self._send_json({"ok": ok})
            return
        if self.path == "/api/confirm-quit-to-library":
            choice = ask_save_state_choice()
            if choice == "save":
                send_save_state_hotkey()
            self._send_json({"choice": choice})
            return
        if self.path == "/api/launch":
            data = self._read_json_body()
            engine_key = str(data.get("engine", "")).strip()
            rom_path = str(data.get("rom", "")).strip()
            load_state = bool(data.get("loadState"))
            ok, err = launch_emulator(engine_key, rom_path, load_state)
            if ok and STATE:
                STATE.request_redetect()
            new_game = ok and not load_state and not rom_has_save(rom_path)
            self._send_json({"ok": ok, "error": err, "newGame": new_game})
            return
        if self.path == "/api/save-load":
            self._send_json(save_load(self._read_json_body()))
            return
        if self.path == "/api/save-write":
            self._send_json(save_write(self._read_json_body()))
            return
        if self.path == "/api/save-export-mon":
            self._send_json(save_export_mon(self._read_json_body()))
            return
        if self.path == "/api/save-import-mon":
            self._send_json(save_import_mon(self._read_json_body()))
            return
        if self.path == "/api/save-create-mon":
            self._send_json(save_create_mon(self._read_json_body()))
            return
        if self.path == "/api/save-remove-mon":
            self._send_json(save_remove_mon(self._read_json_body()))
            return
        if self.path == "/api/save-restore":
            self._send_json(save_restore(self._read_json_body()))
            return
        if self.path == "/api/save-pick":
            path = pick_save_dialog()
            if path and path not in SAVE_PICKED:
                SAVE_PICKED.append(path)
            self._send_json({"ok": bool(path), "path": path})
            return
        if self.path == "/api/rando-pick":
            self._send_json(rando_pick_rom())
            return
        if self.path == "/api/pick-rom":
            self._send_json({"path": pick_rom_dialog()})
            return
        if self.path == "/api/randomize":
            self._send_json(run_randomizer(self._read_json_body()))
            return
        if self.path == "/api/shiny-pick":
            self._send_json(shiny_pick_rom())
            return
        if self.path == "/api/shiny-make":
            self._send_json(run_shiny_tool(self._read_json_body()))
            return
        if self.path == "/api/created-rom-delete":
            self._send_json(created_rom_delete(self._read_json_body()))
            return
        if self.path == "/api/created-rom-action":
            self._send_json(created_rom_action(self._read_json_body()))
            return
        if self.path == "/api/open-link":
            key = (self._read_json_body() or {}).get("key")
            url = ABOUT_LINKS.get(key)
            if url:
                webbrowser.open(url)
            self._send_json({"ok": bool(url)})
            return
        if self.path == "/api/apply-update":
            self._send_json(apply_update())
            return
        if self.path == "/api/open-update":
            if UPDATE_INFO.get("url"):
                webbrowser.open(UPDATE_INFO["url"])
            self._send_json({"ok": bool(UPDATE_INFO.get("url"))})
            return
        if self.path == "/api/open-report":
            data = self._read_json_body()
            rep = data.get("path") or ""
            if rep.endswith(".txt") and os.path.isfile(rep) and any(
                    os.path.dirname(r["path"]) == os.path.dirname(rep) for r in rando_roms()):
                os.startfile(rep)
                self._send_json({"ok": True})
            else:
                self._send_json({"ok": False})
            return
        if self.path == "/api/azahar-install":
            if not azahar_setup.installed(AZAHAR_DIR):
                azahar_setup.start(AZAHAR_DIR)
            self._send_json(azahar_setup.status())
            return
        if self.path == "/api/stop":
            stop_emulator()
            self._send_json({"ok": True})
            return
        if self.path == "/api/sidebar":
            data = self._read_json_body()
            set_sidebar_collapsed(bool(data.get("collapsed", False)))
            self._send_json({"ok": True})
            return
        if self.path == "/api/embedded-menu-command":
            data = self._read_json_body()
            ok = send_embedded_menu_command(int(data.get("id", 0)))
            self._send_json({"ok": ok})
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass


class _Server(http.server.ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True


def run_server(httpd=None):
    with httpd or _Server(("127.0.0.1", PORT), Handler) as h:
        h.serve_forever()


def ask_save_state_choice():
    if CURRENT_EMULATOR_PROC is None or CURRENT_EMULATOR_PROC.poll() is not None:
        return "nosave"
    user32 = _user32()
    MB_YESNOCANCEL = 0x00000003
    MB_ICONQUESTION = 0x00000020
    IDYES, IDCANCEL = 6, 2
    result = user32.MessageBoxW(
        OWN_HWND,
        i18n.tr("Sauvegarder en Save State 1 avant de quitter ?"),
        "PKLab",
        MB_YESNOCANCEL | MB_ICONQUESTION,
    )
    if result == IDCANCEL:
        return "cancel"
    if result == IDYES:
        return "save"
    return "nosave"


def on_window_closing():
    choice = ask_save_state_choice()
    if choice == "cancel":
        return False
    if choice == "save":
        send_save_state_hotkey()
    stop_emulator()
    return True


def main():
    global STATE
    if "--wait-pid" in sys.argv:
        i = sys.argv.index("--wait-pid")
        updater.cleanup_old_exe(sys.argv[i + 1] if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit() else None)
    else:
        updater.cleanup_old_exe()
    try:
        httpd = _Server(("127.0.0.1", PORT), Handler)
    except OSError:
        ctypes.windll.user32.MessageBoxW(None, i18n.tr("PKLab est déjà ouvert."), "PKLab", 0x40)
        return
    _kill_stale_emulator()
    state = State()
    STATE = state
    threading.Thread(target=poll_loop, args=(state,), daemon=True).start()
    threading.Thread(target=run_server, args=(httpd,), daemon=True).start()
    threading.Thread(target=_focus_guard_loop, daemon=True).start()
    threading.Thread(target=_speed_watchdog_loop, daemon=True).start()
    ROM_INDEX.start()

    atexit.register(stop_emulator)

    try:
        site_version = int(os.path.getmtime(res("pklab.html")))
    except OSError:
        site_version = int(time.time())
    site_url = f"http://localhost:{PORT}/pklab.html?v={site_version}"

    try:
        import webview
        window = webview.create_window(
            "PKLab",
            site_url,
            width=1180, height=820, min_size=(760, 560),
            maximized=True,
        )
        window.events.closing += on_window_closing
        window.events.resized += lambda *a, **kw: resize_embedded_canvas()
        webview.start(
            icon=res("app", "assets", "app_icon.ico"),
            private_mode=False,
            storage_path=os.path.join(BASE_DIR, "webview_data"),
        )
    except Exception as e:
        print(f"Impossible d'ouvrir la fenêtre intégrée ({e}), ouverture dans le navigateur...")
        webbrowser.open(site_url)
        print("Laisse cette fenêtre de console ouverte - la fermer arrête l'appli.")
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
