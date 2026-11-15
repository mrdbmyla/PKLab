import os
import re

import save_gen2 as G2

GRASS_RATES = [30, 30, 20, 10, 5, 4, 1]
WATER_RATES = [60, 30, 10]
TOD_LABELS = ["matin", "jour", "nuit"]
NUM_GROUPS = 26
_CACHE = {}
_SMALL = {"de", "du", "des", "la", "le", "les", "en", "sur", "et", "au", "aux"}


def _title(s):
    words = []
    for i, w in enumerate(s.lower().split()):
        if i and w in _SMALL:
            words.append(w)
        elif w.startswith(("s.s.", "c.")):
            words.append(w.upper())
        else:
            words.append("-".join(p[:1].upper() + p[1:] for p in w.split("-")))
    return " ".join(words)


def _str_at(rom, o):
    out = []
    while o < len(rom) and rom[o] != 0x50 and len(out) < 40:
        c = rom[o]
        out.append(G2.CHARS.get(c, " ") if c >= 0x7F else " ")
        o += 1
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _ptr(rom, bank, o):
    v = rom[o] | rom[o + 1] << 8
    if not 0x4000 <= v < 0x8000:
        return None
    return bank * 0x4000 + v - 0x4000


def _landmarks(rom):
    pat = re.compile(rb"\x00\x00..\x94\x74..\x88\x74..\x6c\x74..\x6c\x60", re.S)
    m = pat.search(rom)
    if not m:
        return {}
    o, bank = m.start(), m.start() // 0x4000
    names = {}
    for i in range(1, 120):
        e = o + 4 * i
        p = _ptr(rom, bank, e + 2)
        if p is None:
            break
        name = _str_at(rom, p)
        if not name:
            break
        names[i] = _title(name)
    return names


def _map_headers(rom):
    for o in range(0, len(rom) - 2 * NUM_GROUPS):
        if (rom[o] | rom[o + 1] << 8) != (o % 0x4000) + 0x4000 + 2 * NUM_GROUPS:
            continue
        bank = o // 0x4000
        ptrs = [rom[o + 2 * k] | rom[o + 2 * k + 1] << 8 for k in range(NUM_GROUPS)]
        if not all(0x4000 <= p < 0x8000 for p in ptrs):
            continue
        if any(b - a <= 0 or (b - a) % 9 for a, b in zip(ptrs, ptrs[1:])):
            continue
        out = {}
        bounds = ptrs + [None]
        for g in range(NUM_GROUPS):
            start = bank * 0x4000 + ptrs[g] - 0x4000
            count = (ptrs[g + 1] - ptrs[g]) // 9 if bounds[g + 1] else 0
            if not count:
                k = 0
                while start + 9 * (k + 1) <= len(rom) and 1 <= rom[start + 9 * k] < 0x80 and rom[start + 9 * k + 1] < 0x30 \
                        and 0x4000 <= (rom[start + 9 * k + 3] | rom[start + 9 * k + 4] << 8) < 0x8000 and k < 40:
                    k += 1
                count = k
            for n in range(count):
                h = start + 9 * n
                out[(g + 1, n + 1)] = {"landmark": rom[h + 5], "fish": rom[h + 8]}
        return out
    return {}


def _valid_grass(rom, o):
    if o + 47 > len(rom):
        return False
    g, n = rom[o], rom[o + 1]
    if not (1 <= g <= NUM_GROUPS and 1 <= n <= 120):
        return False
    if not all(rom[o + 2 + k] <= 100 for k in range(3)):
        return False
    for k in range(21):
        lv, sp = rom[o + 5 + 2 * k], rom[o + 6 + 2 * k]
        if not (1 <= lv <= 100 and 1 <= sp <= 251):
            return False
    return True


def _valid_water(rom, o):
    if o + 9 > len(rom):
        return False
    g, n = rom[o], rom[o + 1]
    if not (1 <= g <= NUM_GROUPS and 1 <= n <= 120 and rom[o + 2] <= 100):
        return False
    return all(1 <= rom[o + 3 + 2 * k] <= 100 and 1 <= rom[o + 4 + 2 * k] <= 251 for k in range(3))


def _tables(rom, size, valid, min_run):
    out, o = [], 0
    while o < len(rom):
        if valid(rom, o):
            k = 0
            while valid(rom, o + size * k):
                k += 1
            if k >= min_run and rom[o + size * k] == 0xFF:
                out.append((o, k))
                o += size * k + 1
                continue
        o += 1
    return out


def _wild(rom):
    grass, water = {}, {}
    for o, k in _tables(rom, 47, _valid_grass, 4):
        for i in range(k):
            e = o + 47 * i
            key = (rom[e], rom[e + 1])
            if key in grass:
                continue
            slots = [[(rom[e + 5 + 14 * t + 2 * s], rom[e + 6 + 14 * t + 2 * s]) for s in range(7)] for t in range(3)]
            grass[key] = {"rates": list(rom[e + 2:e + 5]), "slots": slots, "at": e}
    for o, k in _tables(rom, 9, _valid_water, 4):
        for i in range(k):
            e = o + 9 * i
            key = (rom[e], rom[e + 1])
            if key in water:
                continue
            water[key] = {"rate": rom[e + 2], "slots": [(rom[e + 3 + 2 * s], rom[e + 4 + 2 * s]) for s in range(3)], "at": e}
    return grass, water


def rom_data(rom_path):
    try:
        key = (os.path.normcase(rom_path), os.path.getmtime(rom_path))
    except OSError:
        return None
    if key not in _CACHE:
        with open(rom_path, "rb") as f:
            rom = f.read()
        grass, water = _wild(rom)
        _CACHE.clear()
        _CACHE[key] = {"landmarks": _landmarks(rom), "headers": _map_headers(rom), "grass": grass, "water": water}
    return _CACHE[key]


def _rows(slots, rates, names):
    return [{"species": sp, "name": names(sp), "minLevel": lv, "maxLevel": lv, "rate": r} for (lv, sp), r in zip(slots, rates)]


def get_map_bundle(rom_path, group, num, tod, names):
    d = rom_data(rom_path) if rom_path else None
    if d is None:
        return None
    head = d["headers"].get((group, num))
    lm = head and d["landmarks"].get(head["landmark"])
    tod = tod if tod in (0, 1, 2) else 1
    enc = {}
    if (group, num) in d["grass"]:
        enc["land"] = _rows(d["grass"][(group, num)]["slots"][tod], GRASS_RATES, names)
    if (group, num) in d["water"]:
        enc["water"] = _rows(d["water"][(group, num)]["slots"], WATER_RATES, names)
    return {"name": f"{group}:{num}", "displayName": lm or f"Zone {group}-{num}", "image": None, "width": None,
            "height": None, "encounters": enc or None, "timeOfDay": TOD_LABELS[tod]}


def zone_names(rom):
    lm = _landmarks(rom)
    return {k: lm[h["landmark"]] for k, h in _map_headers(rom).items() if h["landmark"] in lm}
