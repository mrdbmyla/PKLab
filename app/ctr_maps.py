import os
import struct
import threading
import time

import ctr_rom
from paths import BASE_DIR

TOWNMAP_VERSION = 1

LAND = [20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1]
SURF = [50, 30, 15, 4, 1]
ROD = [60, 35, 5]
HORDE = [7] * 15

XY_TABLES = [("land", 12, LAND), ("yellowFlowers", 12, LAND), ("purpleFlowers", 12, LAND), ("redFlowers", 12, LAND),
             ("longGrass", 12, LAND), ("water", 5, SURF), ("rockSmash", 5, SURF), ("oldRod", 3, ROD),
             ("goodRod", 3, ROD), ("superRod", 3, ROD), ("horde", 15, HORDE)]
ORAS_TABLES = [("land", 12, LAND), ("longGrass", 12, LAND), ("dexnav", 3, [0, 0, 0]), ("water", 5, SURF),
               ("rockSmash", 5, SURF), ("oldRod", 3, ROD), ("goodRod", 3, ROD), ("superRod", 3, ROD),
               ("horde", 15, HORDE)]

GAMES = {
    "POKEMON Y": {"zones": "a/0/1/2", "table": -1, "text": "a/0/7/5", "names": 72, "enc_section": 3,
                  "enc_start": 0x10, "layout": XY_TABLES,
                  "townmap": {"archive": "a/0/6/9", "image": "timg/townmap_bg1.bclim", "blyt": "blyt/townmap_lower.bclyt",
                              "pane": "0", "points": "a/0/6/8", "rec": 64, "tag": "XY"}},
    "POKEMON OR": {"zones": "a/0/1/3", "table": -2, "text": "a/0/7/4", "names": 90, "enc_section": 3,
                   "enc_start": 0x0E, "layout": ORAS_TABLES,
                   "townmap": {"archive": "a/0/6/7", "image": "timg/poke_navi_map.bclim", "blyt": "blyt/map_lower.bclyt",
                               "pane": "0", "points": "a/0/6/6", "rec": 60, "tag": "ORAS"}},
    "POKEMON US": {"zones": "a/0/7/7", "table": 0, "stride": 0x54, "text": "a/0/3/3", "names": 72, "layout": None,
                   "worlds": "a/0/9/1", "areas": "a/0/8/2", "townmap": {"alola": "a/2/3/8", "tag": "USUM"}},
    "POKEMON S": {"zones": "a/0/7/7", "table": 0, "stride": 0x54, "text": "a/0/3/3", "names": 67, "layout": None,
                  "worlds": "a/0/9/1", "areas": "a/0/8/2", "townmap": {"alola": "a/2/3/4", "tag": "SM"}},
}
GAMES["POKEMON X"] = GAMES["POKEMON Y"]
GAMES["POKEMON AS"] = GAMES["POKEMON OR"]
GAMES["POKEMON UM"] = GAMES["POKEMON US"]
GAMES["POKEMON M"] = GAMES["POKEMON S"]

_lock = threading.Lock()
_ROMS = {}
_PATHS = {}


def set_rom_path(game_key, path):
    _PATHS[game_key] = path


def _load(game_key):
    path = _PATHS.get(game_key)
    cfg = GAMES.get(game_key)
    if not path or not cfg:
        return None
    with _lock:
        hit = _ROMS.get(path)
        if hit:
            return hit
        fs = ctr_rom.RomFS(path)
        try:
            zones = ctr_rom.garc(fs.read(cfg["zones"]))
            names = ctr_rom.text(ctr_rom.garc(fs.read(cfg["text"]))[cfg["names"]])
            blocks = _zone_blocks(fs, cfg) if cfg.get("worlds") else {}
            try:
                townmap = _townmap(fs, cfg.get("townmap"))
            except Exception:
                townmap = None
        finally:
            fs.close()
        table = ctr_rom.lz11(zones[cfg["table"]])
        stride = cfg.get("stride", 0x38)
        rom = {"zones": zones, "table": table, "names": names, "stride": stride, "count": len(table) // stride, "cache": {},
               "blocks": blocks, "path": path, "townmap": townmap}
        _ROMS[path] = rom
        return rom


def _encounters(cfg, zone_file):
    try:
        d = ctr_rom.lz11(zone_file)
        if d[:2] != b"ZO":
            return None
        n = struct.unpack_from("<H", d, 2)[0]
        offs = struct.unpack_from(f"<{n + 1}I", d, 4)
        s = d[offs[cfg["enc_section"]]:offs[cfg["enc_section"] + 1]]
    except Exception:
        return None
    out = {}
    o = cfg["enc_start"]
    for cat, count, rates in cfg["layout"]:
        rows = []
        for i in range(count):
            if o + 4 > len(s):
                break
            v, lo, hi = struct.unpack_from("<HBB", s, o)
            o += 4
            sp = v & 0x7FF
            if sp and lo:
                rows.append({"species": sp, "form": v >> 11, "minLevel": lo, "maxLevel": max(lo, hi), "rate": rates[i]})
        if rows:
            out[cat] = rows
    return out or None


def get_zone_bundle(game_key, zone):
    rom = _load(game_key)
    if rom is None or not 0 <= zone < rom["count"]:
        return None
    cfg = GAMES[game_key]
    key = (zone, not 6 <= time.localtime().tm_hour < 18) if cfg.get("worlds") else zone
    if key in rom["cache"]:
        return dict(rom["cache"][key])
    name_idx = struct.unpack_from("<H", rom["table"], zone * rom["stride"] + 0x1C)[0] & 0x1FF
    place = rom["names"][name_idx] if name_idx < len(rom["names"]) else ""
    if cfg.get("worlds"):
        enc = _encounters7(rom, cfg, zone)
    else:
        enc = _encounters(cfg, rom["zones"][zone]) if cfg["layout"] and zone < len(rom["zones"]) else None
    bundle = {"name": f"CTR_{game_key}_{zone}", "displayName": place or f"Zone {zone}", "image": None,
              "width": None, "height": None, "encounters": enc}
    tm = rom.get("townmap")
    dot = _townmap_dot(rom, zone, name_idx) if tm else None
    if dot:
        src = dot[2] if len(dot) > 2 else tm
        bundle.update(image=src["image"], width=src["w"] / 16, height=src["h"] / 16, dotX=dot[0] / 16 - 0.5,
                      dotY=dot[1] / 16 - 0.5)
    rom["cache"][key] = bundle
    return dict(bundle)


TYPES7 = {0: "land", 1: "flowers", 2: "cave", 3: "sand", 4: "water", 6: "fishing", 8: "cave2"}


def _b36(n):
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    s = ""
    while True:
        n, r = divmod(n, 36)
        s = digits[r] + s
        if not n:
            return s


def _save_png(name, w, h, rows):
    out = os.path.join(BASE_DIR, "map_cache", "ctr", f"{name}_{TOWNMAP_VERSION}.png")
    if not os.path.exists(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmp = out + ".tmp"
        with open(tmp, "wb") as f:
            f.write(ctr_rom.png(w, h, rows))
        os.replace(tmp, out)
    return "/" + os.path.relpath(out, BASE_DIR).replace(os.sep, "/")


def _townmap7(fs, tcfg):
    first = ctr_rom.garc(fs.read(tcfg["alola"]))[0]
    files = ctr_rom.sarc(ctr_rom.lz11(first if isinstance(first, bytes) else first[0]))
    islands = {}
    for i in range(1, 6):
        raw = files.get(f"timg/land_{i:02d}.bflim")
        if not raw:
            continue
        w, h, rows = ctr_rom.bflim(raw)
        islands[i] = {"image": _save_png(f"townmap_{tcfg['tag']}_{i}", w, h, rows), "w": w, "h": h, "rows": rows}
    return {"alola": islands}


def _alpha(isl, x, y):
    if not (0 <= x < isl["w"] and 0 <= y < isl["h"]):
        return 0
    return isl["rows"][y * (isl["w"] * 4 + 1) + 1 + x * 4 + 3]


def _alola_point(rom, zone):
    t, st = rom["table"], rom["stride"]
    e = t[zone * st:(zone + 1) * st]
    isl = rom["townmap"]["alola"].get(e[0x3F])
    if not isl:
        return None
    ex, ez = struct.unpack_from("<ii", e, 0x44)
    if not (ex or ez):
        ex, ez = struct.unpack_from("<i4xi", e, 0x10)
    x, y = ex * 256 / 50000, ez * 256 / 50000
    if not (ex or ez) or not _alpha(isl, int(x), int(y)):
        return None
    return isl, (x, y)


def _townmap(fs, tcfg):
    if not tcfg:
        return None
    if tcfg.get("alola"):
        return _townmap7(fs, tcfg)
    files = ctr_rom.darc(ctr_rom.lz11(ctr_rom.garc(fs.read(tcfg["archive"]))[0]))
    w, h, rows = ctr_rom.bclim(files[tcfg["image"]])
    panes = ctr_rom.layout_panes(files[tcfg["blyt"]])
    bx, by = panes[tcfg["pane"]][:2]
    raw = ctr_rom.lz11(ctr_rom.garc(fs.read(tcfg["points"]))[0])
    points = {}
    rec = tcfg["rec"]
    for i in range(len(raw) // rec):
        zone, pid = struct.unpack_from("<H2xH", raw, i * rec)
        p = panes.get(_b36(pid))
        if p and zone not in points:
            points[zone] = (w / 2 + p[0] - bx, h / 2 - (p[1] - by))
    return {"image": _save_png(f"townmap_{tcfg['tag']}", w, h, rows), "w": w, "h": h, "points": points}


def _townmap_dot(rom, zone, name_idx):
    if "alola" in rom["townmap"]:
        hit = _alola_point(rom, zone)
        if hit is None:
            t, st = rom["table"], rom["stride"]
            for z in range(rom["count"]):
                if z != zone and struct.unpack_from("<H", t, z * st + 0x1C)[0] & 0x1FF == name_idx:
                    hit = _alola_point(rom, z)
                    if hit:
                        break
        if hit is None:
            return None
        isl, (x, y) = hit
        return x, y, isl
    points = rom["townmap"]["points"]
    if zone in points:
        return points[zone]
    t, st = rom["table"], rom["stride"]
    for z in sorted(points):
        if 0 <= z < rom["count"] and struct.unpack_from("<H", t, z * st + 0x1C)[0] & 0x1FF == name_idx:
            return points[z]
    return None


def _zone_blocks(fs, cfg):
    out = {}
    for w, f in enumerate(ctr_rom.garc(fs.read(cfg["worlds"]))):
        try:
            b = ctr_rom.lz11(f if not isinstance(f, list) else f[0])
            if b[:2] != b"WD":
                continue
            sec = struct.unpack_from("<I", b, 4)[0]
            end = struct.unpack_from("<I", b, 8)[0]
            s = b[sec:end]
            o2, o3 = struct.unpack_from("<II", s, 8)
            for k in range(o2, o3 - 3, 4):
                z, blk = struct.unpack_from("<HH", s, k)
                out.setdefault(z, []).append(blk)
        except Exception:
            continue
    return out


def _encounters7(rom, cfg, zone):
    blocks = rom["blocks"].get(zone)
    if not blocks:
        return None
    night = not 6 <= time.localtime().tm_hour < 18
    out = {}
    fs = ctr_rom.RomFS(rom["path"])
    try:
        for blk in sorted(set(blocks)):
            raw = ctr_rom.garc_file(fs, cfg["areas"], blk * 11 + 9)
            if not raw:
                continue
            b = ctr_rom.lz11(raw)
            if b[:2] != b"EA":
                continue
            n = struct.unpack_from("<H", b, 2)[0]
            offs = struct.unpack_from(f"<{n + 1}I", b, 4)
            for i in range(n):
                if offs[i + 1] - offs[i] < 0x1C8:
                    continue
                t = offs[i] + (0x164 if night else 0)
                kind = struct.unpack_from("<I", b, offs[i])[0]
                lo, hi = b[t + 4], b[t + 5]
                rates = b[t + 6:t + 16]
                cat = TYPES7.get(kind, "other")
                rows = out.setdefault(cat, [])
                for k in range(10):
                    v = struct.unpack_from("<I", b, t + 0x10 + 4 * k)[0]
                    sp = v & 0x7FF
                    if sp and rates[k]:
                        rows.append({"species": sp, "form": (v >> 11) & 0x1F, "minLevel": lo, "maxLevel": max(lo, hi),
                                     "rate": rates[k]})
    finally:
        fs.close()
    for cat in out:
        tables = max(1, len(out[cat]) // 10)
        for r in out[cat]:
            r["rate"] = round(r["rate"] / tables)
    return {k: v for k, v in out.items() if v} or None
