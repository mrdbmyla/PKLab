import io
import json
import os
import random
import shutil
import struct

import ctr_rom
import i18n
import randomizer_ctr as RC
import rom_finder

MAX_SPECIES = 721
NUM_TYPES = 18
WATER = 10
LEGENDARIES_6 = {*range(716, 722)}
PERSONAL = {"XY": ("a/2/1/8", 0x40), "ORAS": ("a/1/9/5", 0x50)}
EVOLUTION = {"XY": "a/2/1/5", "ORAS": "a/1/9/2"}
FAMILY = {"POKEMON X": "XY", "POKEMON Y": "XY", "POKEMON OR": "ORAS", "POKEMON AS": "ORAS"}
ZONES = {"XY": {"garc": "a/0/1/2", "table": -1, "start": 0x10, "text": "a/0/7/5", "names": 72},
         "ORAS": {"garc": "a/0/1/3", "table": -2, "start": 0x0E, "text": "a/0/7/4", "names": 90}}
XY_LAYOUT = [(12, False)] * 5 + [(5, True), (5, False)] + [(3, True)] * 3 + [(15, False)]
ORAS_LAYOUT = [(12, False), (12, False), (3, False), (5, True), (5, False)] + [(3, True)] * 3 + [(15, False)]
LAYOUT = {"XY": XY_LAYOUT, "ORAS": ORAS_LAYOUT}
SUPPORTED = {"seed", "noLegendaries", "wild", "wildSimilar", "wildTheme", "wildWater", "wildLevels", "catchEmAll",
             "sameStage", "trainers", "trainerSimilar", "trainerLevels", "bossTheme", "e4Unique", "evolveByLevel",
             "fullyEvolvedAt", "rivalStarter", "betterMovesets", "starters", "starterList", "starter3stage", "starterTypes",
             "gifts", "giftSimilar", "evolutions", "evoSimilar", "evoSameType", "evoImpossible", "evoEasier", "evoNoTime",
             "statics", "fossils", "fossilSimilar", "eggs", *RC.PERSONAL_KEYS, *RC.TRAINER_EXTRA_KEYS,
             "shuffleTrainerNames", "shuffleClassNames", "runIndoors", "startShoes", "starterText", "trades", "fastText", "fieldItems"}
TRAINERS = {"XY": {"data": "a/0/3/8", "poke": "a/0/4/0", "count": 3, "cls": 1, "text": "a/0/7/5", "names": 20},
            "ORAS": {"data": "a/0/3/6", "poke": "a/0/3/8", "count": 7, "cls": 2, "text": "a/0/7/4", "names": 21}}
LEARNSETS = {"XY": "a/2/1/4", "ORAS": "a/1/9/1"}
STARTERS = {"XY": (650, 653, 656), "ORAS": (252, 255, 258)}
GIFT_SIZE = {"XY": 0x18, "ORAS": 0x24}
FIELD = "DllField.cro"
SELECT = "DllPoke3Select.cro"
STATIC_ANCHOR = {"XY": (716, 0, 50), "ORAS": (383, 1, 45)}
STATIC_SIZE = 0xC
TRADE_FIRST = {"XY": (129, 133, 83), "ORAS": (296, 300, 222)}
TRADE_SIZE = 0x24
BATTLE_TYPE = {"XY": 2, "ORAS": 6}
BOSS_WORDS = ("Champion", "Conseil 4", "Boss Team", "Leader Team")
LEVEL_METHODS = {4, 9, 10, 11, 12, 13, 14, 23, 24}
LEVEL_IN_BYTE7 = {4, 9, 10, 11, 12, 13, 14, 23, 24, 32, 33}


class CtrEvos:
    def __init__(self, entries, rec, max_species, types):
        self.data = [bytearray(e) for e in entries]
        self.orig = [bytes(e) for e in entries]
        self.rec, self.max, self.types = rec, max_species, types

    def _parse(self, e):
        out = []
        for o in range(0, len(e) - self.rec + 1, self.rec):
            m, p, t = struct.unpack_from("<HHH", e, o)
            out.append([m, e[o + 7] if self.rec == 8 and m in LEVEL_IN_BYTE7 else p, t])
        return out

    def evolutions(self, s):
        return self._parse(self.data[s]) if s < len(self.data) else []

    def original(self, s):
        return self._parse(self.orig[s]) if s < len(self.orig) else []

    def set_evo(self, s, slot, method, param, target):
        e, o = self.data[s], slot * self.rec
        if self.rec == 6:
            struct.pack_into("<HHH", e, o, method, param, target)
            return
        old_m, old_a, old_t = struct.unpack_from("<HHH", e, o)
        level = method in LEVEL_IN_BYTE7
        arg = (old_a if method == old_m else 0) if level else param
        lv = param if level else (e[o + 7] if method == old_m else 0)
        struct.pack_into("<HHHBB", e, o, method, arg, target, e[o + 6] if target == old_t else 0xFF, min(lv, 100))

    def set_evo_target(self, s, slot, target):
        m, p, _ = self.evolutions(s)[slot]
        self.set_evo(s, slot, m, p, target)

    def clear_evolutions(self, s):
        self.data[s][:] = bytes(len(self.data[s]))

    def changed(self):
        return [i for i, e in enumerate(self.data) if bytes(e) != self.orig[i]]


def fiche_evolutions(fiche, base, ev):
    import randomizer as R
    if not base or not ev.changed() or "species" not in fiche:
        return
    species = {k: dict(v) for k, v in fiche["species"].items()}
    for sp in species.values():
        sp.pop("pre", None)
    for s in range(1, ev.max + 1):
        sp = species.get(str(s))
        if sp is None:
            continue
        texts = {t: x for t, x in sp.get("ev", [])}
        orig = ev.original(s)
        evs = []
        for slot, (m, p, t) in enumerate(ev.evolutions(s)):
            if not m or not 0 < t <= ev.max:
                continue
            om, op, ot = orig[slot] if slot < len(orig) else (0, 0, 0)
            same = (om, op) == (m, p)
            evs.append([t, (texts.get(ot) if same else None) or R._evo_text(base, m, p) or texts.get(ot)
                        or "Gain de niveau"])
        if evs:
            sp["ev"] = evs
        else:
            sp.pop("ev", None)
    for s, sp in species.items():
        for t, _ in sp.get("ev", []):
            if str(t) in species:
                species[str(t)]["pre"] = int(s)
    fiche["species"] = species


def evolution_lines(changes, names):
    return [f"  {names(s)} : {names(o) if o else 'chaque niveau'} -> {names(n)}" for s, o, n in changes]


def mods_dir(azahar_dir, tid):
    return os.path.join(azahar_dir, "user", "load", "mods", f"{tid:016X}")


def save_dir(azahar_dir, tid):
    return os.path.join(azahar_dir, "user", "sdmc", "Nintendo 3DS", "0" * 32, "0" * 32, "title",
                        f"{tid >> 32:08x}", f"{tid & 0xFFFFFFFF:08x}")


def read_tid(path):
    with open(path, "rb") as f:
        h = f.read(0x200)
    if h[0x100:0x104] == b"NCSD":
        return struct.unpack_from("<Q", h, 0x108)[0]
    if h[0x100:0x104] == b"NCCH":
        return struct.unpack_from("<Q", h, 0x118)[0]
    return None


def pick_tid(base, azahar_dir, used):
    for k in range(128):
        tid = (base & 0xFFFFFFFF00FFFFFF) | 0x80000000 | (k << 24)
        if tid in used or os.path.exists(mods_dir(azahar_dir, tid)) or os.path.exists(save_dir(azahar_dir, tid)):
            continue
        return tid
    raise ValueError("Trop de copies aléatoires de ce jeu : supprimes-en une")


def copy_with_tid(src, dst, tid):
    need = os.path.getsize(src) + (64 << 20)
    if shutil.disk_usage(os.path.dirname(os.path.abspath(dst))).free < need:
        raise ValueError(f"Pas assez d'espace disque ({need >> 30} Go nécessaires)")
    try:
        shutil.copyfile(src, dst)
        with open(dst, "r+b") as f:
            h = f.read(0x200)
            if h[0x100:0x104] == b"NCSD":
                part = struct.unpack_from("<I", h, 0x120)[0] * 0x200
                f.seek(0x108)
                f.write(struct.pack("<Q", tid))
            else:
                part = 0
            f.seek(part)
            n = f.read(0x200)
            if n[0x100:0x104] != b"NCCH":
                raise ValueError("partition NCCH absente")
            for off in (0x108, 0x118):
                f.seek(part + off)
                f.write(struct.pack("<Q", tid))
    except Exception:
        if os.path.exists(dst):
            os.remove(dst)
        raise


class Gen6Rom:
    def __init__(self, path):
        hit = rom_finder.identify(path)
        self.game = hit[1] if hit else None
        self.family = FAMILY.get(self.game)
        if not self.family:
            raise ValueError("ROM 3DS : seuls X, Y, Rubis Oméga et Saphir Alpha sont pris en charge pour l'instant")
        self.base_tid = rom_finder.base_tid(read_tid(path))
        if self.base_tid != read_tid(path):
            raise ValueError("Choisis la ROM d'origine, pas une copie aléatoire")
        fs = ctr_rom.RomFS(path)
        try:
            ppath, psize = PERSONAL[self.family]
            self.personal_raw = fs.read(ppath)
            self.pfiles = ctr_rom.garc(self.personal_raw)
            blob = self.pfiles[-1]
            self.personal = {s: blob[psize * s:psize * (s + 1)] for s in range(1, MAX_SPECIES + 1)}
            self.moves_raw = fs.read(RC.MOVES[self.family])
            self.mfiles = ctr_rom.garc(self.moves_raw)
            self.learn_raw = fs.read(LEARNSETS[self.family])
            self.evo_raw = fs.read(EVOLUTION[self.family])
            self.evos = ctr_rom.garc(self.evo_raw)
            z = ZONES[self.family]
            self.zone_garc = fs.read(z["garc"])
            names = ctr_rom.text(ctr_rom.garc(fs.read(z["text"]))[z["names"]])
            t = TRAINERS[self.family]
            self.tr_data_garc = fs.read(t["data"])
            self.tr_data = ctr_rom.garc(self.tr_data_garc)
            self.tr_poke_garc = fs.read(t["poke"])
            self.class_names = ctr_rom.text(ctr_rom.garc(fs.read(t["text"]))[t["names"]])
            self.learn = ctr_rom.garc(self.learn_raw)
            self.field = bytearray(fs.read(FIELD))
            self.select = bytearray(fs.read(SELECT)) if SELECT in fs.files else bytearray()
            self.at = {n: fs.files[n] for n in (z["garc"], t["poke"], t["data"], FIELD, SELECT, EVOLUTION[self.family], ppath,
                                                RC.MOVES[self.family], LEARNSETS[self.family])
                       if n in fs.files}
        finally:
            fs.close()
        self.zone_at = self.at[z["garc"]]
        self.tr_poke = ctr_rom.garc(self.tr_poke_garc)
        self.gift_offsets = self._gifts()
        self.static_offsets = self._statics()
        self.select_offsets = self._select()
        self.zone_files = ctr_rom.garc(self.zone_garc)
        table = ctr_rom.lz11(self.zone_files[z["table"]])
        self.zone_names = {}
        for i in range(len(table) // 0x38):
            idx = struct.unpack_from("<H", table, i * 0x38 + 0x1C)[0] & 0x1FF
            self.zone_names[i] = names[idx] if idx < len(names) else ""
        self.zone_count = len(table) // 0x38

    def _select(self):
        first = STARTERS[self.family]
        pat = b"".join(struct.pack("<I", s) + bytes(0x50) for s in first[:2]) + struct.pack("<I", first[2])
        o = bytes(self.select).find(pat)
        return [] if o < 0 else [o, o + 0x54, o + 0xA8]

    def _statics(self):
        f = bytes(self.field)

        def ok(o):
            if o < 0 or o + STATIC_SIZE > len(f):
                return False
            sp, form, lv, item = struct.unpack_from("<HBBH", f, o)
            return 0 < sp <= MAX_SPECIES and form < 32 and 0 < lv <= 100 and (item == 0xFFFF or item < 1000)
        o = f.find(struct.pack("<HBB", *STATIC_ANCHOR[self.family]))
        if o < 0:
            return []
        while ok(o - STATIC_SIZE):
            o -= STATIC_SIZE
        out = []
        while ok(o):
            out.append(o)
            o += STATIC_SIZE
        return out

    def gift_kind(self, o):
        if self.family == "ORAS" and self.field[o + 5] == 1 and struct.unpack_from("<H", self.field, o + 0x12)[0] == 0xEA64:
            return "eggs"
        return "fossils" if struct.unpack_from("<H", self.field, o)[0] in RC.FOSSILS else "gifts"

    def _gifts(self):
        size = GIFT_SIZE[self.family]
        first = STARTERS[self.family]
        for o in range(0, len(self.field) - size * 3, 4):
            if all(struct.unpack_from("<H", self.field, o + i * size)[0] == first[i] for i in range(3)):
                break
        else:
            return []
        out = []
        while o + size <= len(self.field):
            sp, b2, b3, lv = struct.unpack_from("<HBB", self.field, o) + (self.field[o + 5],)
            if not (0 < sp <= MAX_SPECIES and b2 == 0 and b3 == 0 and 0 < lv <= 100):
                break
            out.append(o)
            o += size
        return out

    def moves_at_level(self, s, lv):
        e = self.learn[s] if s < len(self.learn) else b""
        moves = []
        for i in range(0, len(e) - 3, 4):
            m, at = struct.unpack_from("<hh", e, i)
            if m < 0:
                break
            if at <= lv:
                if m in moves:
                    moves.remove(m)
                moves.append(m)
        moves = moves[-4:]
        return moves + [0] * (4 - len(moves))

    def next_stage(self, s, level=None, rng=None):
        nxt = []
        for m, p, t in self.evolutions(s):
            if t == s:
                continue
            if level is None or (m in LEVEL_METHODS and 0 < p <= level) or (m not in LEVEL_METHODS and level >= 40):
                nxt.append(t)
        if not nxt:
            return None
        return rng.choice(nxt) if rng else nxt[0]

    def chain(self, s):
        out = [s]
        while len(out) < 3:
            n = self.next_stage(out[-1])
            if not n or n in out:
                break
            out.append(n)
        return out

    def types(self, s):
        p = self.personal[s]
        return p[6], p[7]

    def bst(self, s):
        return sum(self.personal[s][0:6])

    def evolutions(self, s):
        e = self.evos[s] if s < len(self.evos) else b""
        out = []
        for i in range(0, len(e) - 5, 6):
            m, p, t = struct.unpack_from("<HHH", e, i)
            if m and 0 < t <= MAX_SPECIES:
                out.append((m, p, t))
        return out


def _wild(g, rng, opts, pool, bst, names, pick, R):
    mode = opts["wild"]
    z = ZONES[g.family]
    new_files = list(g.zone_files)
    decoded = {}
    sites = []
    for zone in range(g.zone_count):
        f = g.zone_files[zone]
        d = bytearray(ctr_rom.lz11(f))
        if d[:2] != b"ZO":
            continue
        n = struct.unpack_from("<H", d, 2)[0]
        offs = struct.unpack_from(f"<{n + 1}I", d, 4)
        if n < 4 or offs[4] - offs[3] < z["start"] + 4:
            continue
        o = offs[3] + z["start"]
        end = offs[4]
        for count, water in LAYOUT[g.family]:
            for _ in range(count):
                if o + 4 > end:
                    break
                v, lo = struct.unpack_from("<HB", d, o)
                if v & 0x7FF and lo:
                    sites.append((zone, o, water))
                o += 4
        decoded[zone] = d
    types_of = {s: set(R._type_list(*g.types(s))) for s in pool}
    water_pool = [s for s in pool if WATER in types_of[s]]
    global_map, zone_maps, themes, seen_all, by_zone = {}, {}, {}, set(), {}
    for zone, at, water in sites:
        d = decoded[zone]
        v, lo, hi = struct.unpack_from("<HBB", d, at)
        old = v & 0x7FF
        new = old
        if mode != "off" and 0 < old <= MAX_SPECIES:
            src = pool
            if opts["wildTheme"]:
                theme = themes.setdefault(zone, rng.randrange(NUM_TYPES))
                src = [x for x in pool if theme in types_of[x]] or pool
            if water and opts["wildWater"]:
                src = [x for x in src if x in water_pool] or water_pool or src
            cands = ([x for x in src if x not in seen_all] or src) if opts["catchEmAll"] else src
            key = (old, water)
            if mode == "global":
                if key not in global_map:
                    global_map[key] = pick(rng, cands, bst, old, opts["wildSimilar"], set(global_map.values()))
                new = global_map[key]
            elif mode == "zone":
                zm = zone_maps.setdefault(zone, {})
                if key not in zm:
                    zm[key] = pick(rng, cands, bst, old, opts["wildSimilar"], set(zm.values()))
                new = zm[key]
            else:
                new = pick(rng, cands, bst, old, opts["wildSimilar"])
            seen_all.add(new)
            v = new if new != old else v
        if opts["wildLevels"]:
            lo = max(2, min(100, round(lo * (1 + opts["wildLevels"] / 100))))
            hi = max(lo, min(100, round(hi * (1 + opts["wildLevels"] / 100))))
        struct.pack_into("<HBB", d, at, v, lo, hi)
        by_zone.setdefault(zone, set()).add((old, new))
    for zone, d in decoded.items():
        if bytes(d) != ctr_rom.lz11(g.zone_files[zone]):
            new_files[zone] = ctr_rom.lz11_pack(d)
    lines = []
    for zone in sorted(by_zone):
        changed = sorted((o, n) for o, n in by_zone[zone] if o != n)
        if changed:
            lines.append(f"  {g.zone_names.get(zone) or 'Zone'} ({zone})")
            lines += [f"    {names(o)} -> {names(n)}" for o, n in changed]
    log = (f"Pokémon sauvages : mode {mode}, {len(sites)} emplacements (herbes, fleurs, surf, pêche, Éclate-Roc, hordes)"
           + (", force similaire" if opts["wildSimilar"] and mode != "off" else "")
           + (", un type par zone" if opts["wildTheme"] else "")
           + (", Eau en surf et pêche" if opts["wildWater"] else "")
           + (f", niveaux {opts['wildLevels']:+d} %" if opts["wildLevels"] else ""))
    changed = new_files != g.zone_files
    return (ctr_rom.garc_build(g.zone_garc, new_files) if changed else None), log, lines


def _starters(g, rng, opts, pool, pre, log, names, R):
    if opts["starters"] == "off" or len(g.gift_offsets) < 3:
        if opts["starters"] != "off":
            log.append("Starters : NON modifiés (table introuvable)")
        return None
    old = list(STARTERS[g.family])
    if opts["starters"] == "custom":
        chosen = [int(x) for x in opts["starterList"][:3] if str(x).strip()]
        if len(chosen) != 3 or any(not (1 <= c <= MAX_SPECIES) for c in chosen):
            raise ValueError("Starters choisis : il faut 3 Pokémon (n° 1 à 721)")
    else:
        evolves = {s: [t for _, _, t in g.evolutions(s) if t != s] for s in range(1, MAX_SPECIES + 1)}
        basics = [s for s in pool if s not in pre and evolves[s] and s not in old]
        if opts["starter3stage"]:
            basics = [s for s in basics if any(evolves[t] for t in evolves[s])] or basics
        if opts["starters"] == "randomAny":
            basics = [s for s in pool if s not in old]
        chosen = R._three_starters(rng, basics, g.types, opts["starterTypes"])
    for o, new in zip(g.gift_offsets[:3], chosen):
        struct.pack_into("<H", g.field, o, new)
        g.field[o + 4] = 0
    for o, new in zip(g.select_offsets, chosen):
        struct.pack_into("<I", g.select, o, new)
    if not g.select_offsets:
        log.append("Écran de choix des starters : NON modifié (fiches introuvables)")
    mapping = dict(zip(old, chosen))
    log.append("Starters : " + ", ".join(f"{names(o)} -> {names(n)}" for o, n in mapping.items()))
    return mapping


STARTER_TEXT = {"ORAS": {"text": ["a/0/7/9"] + [f"a/0/8/{i}" for i in range(7)], "game": [f"a/0/7/{i}" for i in range(1, 9)],
                         "species": 98, "types": 18, "edits": ((202, (24, 25, 26)), (606, (3, 4, 5)))},
                "XY": {"text": [f"a/0/7/{i}" for i in range(2, 10)], "game": [f"a/0/7/{i}" for i in range(2, 10)],
                       "species": 80, "types": 17, "edits": ((22, (536, 537, 538)),)}}


def _starter_text_paths(family):
    c = STARTER_TEXT[family]
    return sorted(set(c["text"]) | set(c["game"]))


def _seq_find(chars, part):
    for i in range(len(chars) - len(part) + 1):
        if part and chars[i:i + len(part)] == part:
            return i
    return -1


def _starter_edit(data, fi, line_ids, mapping, sp, ty, types_of):
    lines = [(list(x), f) for x, f in ctr_rom.text_raw(data)]
    touched = False
    for k in line_ids:
        if k >= len(lines):
            continue
        chars, flag = lines[k]
        for old, new in mapping.items():
            if old < len(sp) and new < len(sp) and _seq_find(chars, sp[old]) >= 0:
                chars = RC.swap_text(chars, sp[old], sp[new])
                if fi == 606:
                    hits = [(_seq_find(chars, t), t) for t in ty if t]
                    hits = [h for h in hits if h[0] >= 0]
                    if hits:
                        pos, t = min(hits, key=lambda h: (h[0], -len(h[1])))
                        chars = chars[:pos] + ty[types_of(new)[0]] + chars[pos + len(t):]
                break
        if chars != lines[k][0]:
            lines[k] = (chars, flag)
            touched = True
    return ctr_rom.text_pack(lines) if touched else None


def _starter_text6(g, lists, raws, mapping, types_of, log):
    c = STARTER_TEXT[g.family]
    full, part, changed = 0, 0, set()
    for tp, gp in zip(c["text"], c["game"]):
        if tp not in lists or gp not in lists:
            continue
        sp = [RC.clean_text(x) for x, _ in ctr_rom.text_raw(lists[gp][c["species"]])]
        ty = [RC.clean_text(x) for x, _ in ctr_rom.text_raw(lists[gp][c["types"]])]
        edits = {}
        for fi, line_ids in c["edits"]:
            if fi < len(lists[tp]):
                data = _starter_edit(lists[tp][fi], fi, line_ids, mapping, sp, ty, types_of)
                if data is not None:
                    edits[fi] = data
        order = [fi for fi, _ in c["edits"] if fi in edits]
        for n in range(len(order), 0, -1):
            trial = list(lists[tp])
            for fi in order[:n]:
                trial[fi] = edits[fi]
            if len(ctr_rom.garc_build(raws[tp], trial)) <= g.at[tp][1]:
                lists[tp] = trial
                changed.add(tp)
                if n == len(order):
                    full += 1
                else:
                    part += 1
                break
    if g.family == "ORAS":
        what = (f"écran de choix + explication des types : {full} langues, écran de choix seul : {part} langues, "
                f"inchangé : {len(c['text']) - full - part} langues (pas assez de place) ; forces et faiblesses citées inchangées")
    else:
        what = (f"répliques du rival : {full} langues sur {len(c['text'])}, les autres inchangées (pas assez de place) ; "
                "quiz de Sannah inchangé")
    log.append(f"Texte des starters : {what} (non vérifié en jeu)")
    return changed


def _gifts(g, rng, opts, pool, bst, pre, log, names, pick):
    def writer(o):
        def write(new):
            struct.pack_into("<H", g.field, o, new)
            g.field[o + 4] = 0
        return write
    entries = [(g.gift_kind(o), struct.unpack_from("<H", g.field, o)[0], g.field[o + 5], writer(o)) for o in g.gift_offsets[3:]]
    return RC.randomize_gifts(entries, rng, opts, pool, bst, pre, log, names, pick)


def _statics(g, rng, opts, pool, bst, legend, log, names, R):
    if opts["statics"] != "off" and not g.static_offsets:
        log.append("Pokémon fixes : NON modifiés (table introuvable)")
        return []

    def writer(o):
        def write(new, lv):
            if new != struct.unpack_from("<H", g.field, o)[0]:
                struct.pack_into("<H", g.field, o, new)
                g.field[o + 2] = 0
        return write
    entries = [(struct.unpack_from("<H", g.field, o)[0], g.field[o + 3], writer(o)) for o in g.static_offsets]
    return RC.randomize_statics(entries, rng, opts, pool, bst, legend, log, names, R)


def trade_table(code, family):
    first = TRADE_FIRST[family]
    pat = struct.pack("<H", first[0])
    o = code.find(pat)
    while o >= 0:
        if o % 2 == 0 and o + TRADE_SIZE * 3 <= len(code) and all(
                struct.unpack_from("<H", code, o + i * TRADE_SIZE)[0] == first[i] for i in range(3)):
            idx = struct.unpack_from("<H", code, o + 2)[0]
            out, q = [], o
            while q + TRADE_SIZE <= len(code):
                sp, k, lv = struct.unpack_from("<HHB", code, q)
                if not (0 < sp <= MAX_SPECIES and k == idx + len(out) and 0 < lv <= 100):
                    break
                out.append(q)
                q += TRADE_SIZE
            if len(out) >= 3:
                return out
        o = code.find(pat, o + 1)
    return []


def _trades(g, code, rng, opts, pool, bst, log, names, R):
    if opts["trades"] == "off":
        return [], []
    offs = trade_table(code, g.family)
    if not offs:
        log.append("Échanges en jeu : NON modifiés (table introuvable)")
        return [], []
    buf = bytearray(code)

    def got_writer(o):
        def write(new):
            struct.pack_into("<H", buf, o, new)
            ratio = g.personal[new][0x12]
            if ratio == 255:
                buf[o + 0xD] = 2
            elif ratio == 254:
                buf[o + 0xD] = 1
            elif ratio == 0 or buf[o + 0xD] > 1:
                buf[o + 0xD] = 0
        return write

    def asked_writer(o):
        def write(new):
            struct.pack_into("<H", buf, o + 0x20, new)
        return write
    entries = [(struct.unpack_from("<H", code, o)[0], struct.unpack_from("<H", code, o + 0x20)[0], got_writer(o), asked_writer(o))
               for o in offs]
    lines = RC.randomize_trades(entries, rng, opts, pool, bst, log, names, R)
    log[-1] += " ; programme du jeu modifié (correctif code.ips)"
    return lines, [(o, bytes(buf[o:o + TRADE_SIZE])) for o in offs if buf[o:o + TRADE_SIZE] != code[o:o + TRADE_SIZE]]


def _field_items(g, src_path, rng, opts, log, base):
    g.scripts_new = None
    if opts["fieldItems"] == "off":
        return []
    import save_editor
    name = RC.FIELD_SCRIPTS[g.family]
    fs = ctr_rom.RomFS(src_path)
    try:
        g.scripts_raw = fs.read(name)
        g.at[name] = fs.files[name]
    finally:
        fs.close()
    new, lines = RC.randomize_field_items(ctr_rom.garc(g.scripts_raw), g.family, RC.MAX_ITEM[g.family],
                                          save_editor.item_pockets_default(g.family), rng, opts, log,
                                          (base or {}).get("items", {}))
    g.scripts_new = new
    return lines


def _trainers(g, rng, opts, pool, bst, log, names, pick, starter_map, R):
    touch = (opts["trainers"] != "off" or opts["trainerLevels"] or opts["fullyEvolvedAt"] or opts["betterMovesets"]
             or (starter_map and opts["rivalStarter"]))
    if not touch:
        return list(g.tr_poke), []
    t = TRAINERS[g.family]
    types_of = {s: set(R._type_list(*g.types(s))) for s in pool}
    old_lines, new_lines = {}, {}
    if starter_map and opts["rivalStarter"]:
        for i, s in enumerate(STARTERS[g.family]):
            for stage, x in enumerate(g.chain(s)):
                old_lines[x] = (i, stage)
            new_lines[i] = g.chain(starter_map[s])
    order = []
    for i in range(1, len(g.tr_data)):
        d = g.tr_data[i]
        if len(d) <= max(t["count"], t["cls"]) or i >= len(g.tr_poke):
            continue
        cls = struct.unpack_from("<H", d, t["cls"])[0] if g.family == "ORAS" else d[t["cls"]]
        cname = g.class_names[cls] if cls < len(g.class_names) else ""
        important = any(w in cname for w in BOSS_WORDS) or cname == "Maître"
        order.append((i, d[0], d[t["count"]], cname, important))
    if opts["e4Unique"]:
        order.sort(key=lambda x: not x[4])
    new_poke = list(g.tr_poke)
    lines, count, rivals, e4set, used_all = [], 0, 0, set(), set()
    for i, fmt, n, cname, important in order:
        size = 8 + (2 if fmt & 2 else 0) + (8 if fmt & 1 else 0)
        blob = bytearray(g.tr_poke[i])
        if n * size > len(blob):
            continue
        src, theme = pool, None
        if opts["trainers"] == "theme" or (opts["bossTheme"] and important and opts["trainers"] != "off"):
            theme = rng.randrange(NUM_TYPES)
            src = [x for x in pool if theme in types_of[x]] or pool
        src = R._trainer_src(src, opts, important, e4set, used_all)
        team, used, is_rival = [], set(), False
        for k in range(n):
            o = k * size
            lv, old = struct.unpack_from("<HH", blob, o + 2)
            new = old
            rival_mon = old in old_lines and cname == "Dresseur"
            if rival_mon:
                idx, stage = old_lines[old]
                chain = new_lines[idx]
                new = chain[min(stage, len(chain) - 1)]
                is_rival = True
            elif opts["trainers"] != "off" and 0 < old <= MAX_SPECIES:
                new = pick(rng, src, bst, old, opts["trainerSimilar"], used)
            if opts["trainerLevels"]:
                lv = max(2, min(100, round(lv * (1 + opts["trainerLevels"] / 100))))
            if opts["evolveByLevel"] and not rival_mon:
                for _ in range(2):
                    nxt = g.next_stage(new, lv, rng)
                    if not nxt:
                        break
                    new = nxt
            if opts["fullyEvolvedAt"] and lv >= opts["fullyEvolvedAt"] and not rival_mon:
                for _ in range(3):
                    nxt = g.next_stage(new, None, rng)
                    if not nxt:
                        break
                    new = nxt
            used.add(new)
            used_all.add(new)
            if important:
                e4set.add(new)
            struct.pack_into("<HH", blob, o + 2, lv, new)
            if new != old:
                struct.pack_into("<H", blob, o + 6, 0)
            if fmt & 1 and (new != old or opts["betterMovesets"] or opts["trainerLevels"]):
                mo = o + 8 + (2 if fmt & 2 else 0)
                struct.pack_into("<4H", blob, mo, *g.moves_at_level(new, lv))
            team.append(f"{names(old)}→{names(new)} Nv{lv}" if new != old else f"{names(new)} Nv{lv}")
        new_poke[i] = bytes(blob)
        count += 1
        rivals += is_rival
        if important or is_rival:
            label = f"{cname or 'Dresseur'} n°{i}"
            lines.append(f"  {label}{' (type ' + (R.TYPE_FR + ['Fée'])[theme] + ')' if theme is not None else ''} : "
                         + ", ".join(team))
    log.append(f"Dresseurs : {opts['trainers']}, {count} équipes"
               + (", force similaire" if opts["trainerSimilar"] and opts["trainers"] != "off" else "")
               + (", Champions / Conseil 4 / Maître : un type chacun" if opts["bossTheme"] and opts["trainers"] != "off" else "")
               + (f", niveaux {opts['trainerLevels']:+d} %" if opts["trainerLevels"] else "")
               + (f", complètement évolués dès le Nv. {opts['fullyEvolvedAt']}" if opts["fullyEvolvedAt"] else "")
               + (f", lignée des starters suivie par les rivaux ({rivals} équipes)" if old_lines else ""))
    return new_poke, lines


def _mons6(blob, fmt, n):
    size = 8 + (2 if fmt & 2 else 0) + (8 if fmt & 1 else 0)
    out = []
    for k in range(n):
        o = k * size
        out.append({"head": bytes(blob[o:o + 8]), "lv": struct.unpack_from("<H", blob, o + 2)[0],
                    "sp": struct.unpack_from("<H", blob, o + 4)[0],
                    "item": struct.unpack_from("<H", blob, o + 8)[0] if fmt & 2 else 0,
                    "moves": list(struct.unpack_from("<4H", blob, o + 8 + (2 if fmt & 2 else 0))) if fmt & 1 else None})
    return out, bytes(blob[n * size:])


def _pack6(mons, fmt, tail):
    out = bytearray()
    for m in mons:
        out += m["head"]
        if fmt & 2:
            out += struct.pack("<H", m["item"])
        if fmt & 1:
            out += struct.pack("<4H", *m["moves"])
    return bytes(out + tail)


def _trainer_extras(g, new_poke, rng, opts, pool, bst, log, R):
    if not RC.extras_wanted(opts):
        return new_poke, None
    t = TRAINERS[g.family]
    bt = BATTLE_TYPE[g.family]
    poke = list(new_poke)
    tr = [bytearray(d) for d in g.tr_data]
    starter_species = {x for s in STARTERS[g.family] for x in g.chain(s)}
    plans = []
    for i in range(1, min(len(tr), len(poke))):
        d = tr[i]
        if len(d) <= max(t["count"], t["cls"], bt):
            continue
        fmt, n = d[0], d[t["count"]]
        size = 8 + (2 if fmt & 2 else 0) + (8 if fmt & 1 else 0)
        if n == 0 or n * size > len(poke[i]) or n * size > len(g.tr_poke[i]):
            continue
        cls = struct.unpack_from("<H", d, t["cls"])[0] if g.family == "ORAS" else d[t["cls"]]
        cname = g.class_names[cls] if cls < len(g.class_names) else ""
        cat = RC.trainer_category(cname, [m["sp"] for m in _mons6(g.tr_poke[i], fmt, n)[0]], starter_species)
        mons, tail = _mons6(poke[i], fmt, n)
        base = [dict(m) for m in mons]
        extra = int(opts["extra" + cat] or 0)
        double = bool(opts["doubleBattles"]) and d[bt] == 0
        if double and n + extra < 2:
            extra = 2 - n
        added = 0
        for _ in range(max(0, min(extra, 6 - len(mons)))):
            ref = max(mons, key=lambda m: m["lv"])
            used = {m["sp"] for m in mons}
            sp = R._pick(rng, pool, bst, ref["sp"] if ref["sp"] in bst else rng.choice(pool), True, used)
            head = bytearray(ref["head"])
            head[1] = 0
            struct.pack_into("<HH", head, 4, sp, 0)
            mons.append({"head": bytes(head), "lv": ref["lv"], "sp": sp, "item": 0,
                         "moves": g.moves_at_level(sp, ref["lv"]) if fmt & 1 else None})
            added += 1
        new_fmt, items = fmt, 0
        if opts["items" + cat]:
            new_fmt |= 2
            items = RC.give_items(mons, rng, opts, R)
        plans.append({"i": i, "cat": cat, "fmt": fmt, "new_fmt": new_fmt, "mons": mons, "base": base, "tail": tail,
                      "added": added, "items": items, "double": double and len(mons) >= 2})

    def default(mons):
        return all(m["moves"] == g.moves_at_level(m["sp"], m["lv"]) for m in mons)

    def blob(pl):
        return _pack6(pl["mons"], pl["new_fmt"], pl["tail"])

    def align(x):
        return (len(x) + 3) & ~3

    for pl in plans:
        poke[pl["i"]] = blob(pl)
    slot = g.at[t["poke"]][1]
    size = len(ctr_rom.garc_build(g.tr_poke_garc, poke))
    for pl in sorted(plans, key=lambda pl: -len(pl["mons"])):
        if size <= slot:
            break
        if pl["new_fmt"] & 1 and default(pl["mons"]):
            old = align(poke[pl["i"]])
            pl["new_fmt"] &= ~1
            poke[pl["i"]] = blob(pl)
            size += align(poke[pl["i"]]) - old
    skipped = 0
    order = {"Regular": 0, "Important": 1, "Boss": 2}
    for pl in sorted(plans, key=lambda pl: (order[pl["cat"]], rng.random())):
        if size <= slot:
            break
        if not (pl["added"] or pl["items"]):
            continue
        old = align(poke[pl["i"]])
        pl["mons"], pl["added"], pl["items"] = pl["base"], 0, 0
        pl["new_fmt"] = pl["fmt"] & ~1 if pl["fmt"] & 1 and default(pl["base"]) else pl["fmt"]
        pl["double"] = pl["double"] and len(pl["base"]) >= 2
        poke[pl["i"]] = blob(pl)
        size += align(poke[pl["i"]]) - old
        skipped += 1
    added = items = doubles = 0
    for pl in plans:
        d = tr[pl["i"]]
        d[0] = pl["new_fmt"]
        d[t["count"]] = len(pl["mons"])
        if pl["double"]:
            d[bt] = 1
            doubles += 1
        added += pl["added"]
        items += pl["items"]
    RC.extras_log(log, opts, added, items, doubles, skipped)
    return poke, [bytes(d) for d in tr]


def randomize(src_path, options, out_path, fiche_base, azahar_dir, used_tids=()):
    import randomizer as R
    import randomizer_gen2
    opts = dict(R.DEFAULTS)
    opts.update({k: v for k, v in (options or {}).items() if k in R.DEFAULTS})
    for k in ("wildLevels", "trainerLevels"):
        opts[k] = max(-50, min(200, int(opts[k] or 0)))
    g = Gen6Rom(src_path)
    seed = opts["seed"]
    if seed in (None, ""):
        seed = random.SystemRandom().randrange(1, 10 ** 9)
    seed = int(seed)
    rng = random.Random(f"{g.game}:{seed}:" + json.dumps({k: v for k, v in opts.items() if k != "seed"}, sort_keys=True))
    R._USAGE.clear()
    base_names = (fiche_base or {}).get("species", {})

    def names(sid):
        return base_names.get(str(sid), {}).get("name", f"#{sid}")

    pre = {}
    for s in range(1, MAX_SPECIES + 1):
        for _, _, t in g.evolutions(s):
            if t != s:
                pre.setdefault(t, s)
    kids = {}
    for s_, p_ in pre.items():
        kids.setdefault(p_, []).append(s_)
    R._STAGE.clear()
    for s_ in range(1, MAX_SPECIES + 1):
        R._STAGE[s_] = 2 if s_ not in kids else (1 if s_ in pre else 0)

    def pick(rng_, pool_, bst_, old_, similar_, avoid_=()):
        return R._pick(rng_, pool_, bst_, old_, similar_, avoid_, opts["sameStage"])

    legend = R.LEGENDARIES | LEGENDARIES_6
    pool = [s for s in range(1, MAX_SPECIES + 1) if not (opts["noLegendaries"] and s in legend)]
    log = []
    field0 = bytes(g.field)
    select0 = bytes(g.select)
    ev = CtrEvos(g.evos, 6, MAX_SPECIES, None)
    d = RC.CtrData(g.family, g.pfiles, PERSONAL[g.family][1], g.mfiles, g.learn, ev, MAX_SPECIES)
    ev.types, g.personal, g.learn = d.types, d.p, d.learn
    try:
        with RC.core(R, MAX_SPECIES, d.max_move, RC.MAX_ABILITY[g.family]):
            bst, evo_changes, tm_labels, code_ips = RC.randomize_core(g, d, ev, rng, opts, pool, log, names, fiche_base, src_path, R)
        starters = _starters(g, rng, opts, pool, pre, log, names, R)
        garc, wild_log, wild_lines = _wild(g, rng, opts, pool, bst, names, pick, R)
        log.append(wild_log)
        tr_poke, trainer_lines = _trainers(g, rng, opts, pool, bst, log, names, pick, starters, R)
        tr_poke, tr_data = _trainer_extras(g, tr_poke or g.tr_poke, rng, opts, pool, bst, log, R)
        gift_lines = _gifts(g, rng, opts, pool, bst, pre, log, names, pick)
        static_lines = _statics(g, rng, opts, pool, bst, legend, log, names, R)
        trade_lines, trade_ips = _trades(g, ctr_rom.exefs_code(src_path) if opts["trades"] != "off" else b"",
                                         rng, opts, pool, bst, log, names, R)
        code_ips = code_ips + trade_ips
        item_lines = _field_items(g, src_path, rng, opts, log, fiche_base)
    finally:
        R._STAGE.clear()
    files = {}
    if garc is not None:
        files[ZONES[g.family]["garc"]] = garc
    if tr_poke != g.tr_poke:
        files[TRAINERS[g.family]["poke"]] = ctr_rom.garc_build(g.tr_poke_garc, tr_poke)
    if tr_data and tr_data != g.tr_data:
        files[TRAINERS[g.family]["data"]] = ctr_rom.garc_build(g.tr_data_garc, tr_data)
    if g.scripts_new is not None:
        files[RC.FIELD_SCRIPTS[g.family]] = ctr_rom.garc_build(g.scripts_raw, g.scripts_new)
    if bytes(g.field) != field0:
        files[FIELD] = bytes(g.field)
    if bytes(g.select) != select0:
        files[SELECT] = bytes(g.select)
    if ev.changed():
        files[EVOLUTION[g.family]] = ctr_rom.garc_build(g.evo_raw, g.evos)
    if d.personal_changed():
        files[PERSONAL[g.family][0]] = ctr_rom.garc_build(g.personal_raw, d.personal_files())
    if d.moves_changed():
        files[RC.MOVES[g.family]] = ctr_rom.garc_build(g.moves_raw, d.move_files())
    if d.learn_changed():
        files[LEARNSETS[g.family]] = ctr_rom.garc_build(g.learn_raw, d.learn_files())
    skipped = sorted({RC.LABELS.get(k, randomizer_gen2.UNSUPPORTED.get(k, k))
                      for k in R.DEFAULTS if k not in SUPPORTED and opts.get(k) != R.DEFAULTS[k]
                      and opts.get(k) not in ("off", False, 0, None, [])})
    if skipped:
        log.append("Pas encore disponible en 6G (ignoré) : " + ", ".join(skipped))
    RC.native_tweaks(opts, log)
    paths, idx = RC.name_files(g.family, opts)
    st_paths = _starter_text_paths(g.family) if starters and opts["starterText"] else []
    if paths or st_paths:
        fs = ctr_rom.RomFS(src_path)
        try:
            raws = {p: fs.read(p) for p in sorted(set(paths) | set(st_paths)) if p in fs.files}
            g.at.update({p: fs.files[p] for p in raws})
        finally:
            fs.close()
        lists = {p: list(ctr_rom.garc(r)) for p, r in raws.items()}
        changed_paths = set()
        if paths:
            for p, changed in RC.shuffle_names({p: {i: lists[p][i] for i in idx if i < len(lists[p])} for p in paths
                                                if p in lists}, g.family, rng, opts, log).items():
                for i, data in changed.items():
                    lists[p][i] = data
                changed_paths.add(p)
        if st_paths:
            changed_paths |= _starter_text6(g, lists, raws, starters, d.types, log)
        for p in sorted(changed_paths):
            files[p] = ctr_rom.garc_build(raws[p], lists[p])
    if not files and not code_ips:
        raise ValueError("Aucun changement demandé")
    if out_path is None:
        root, ext = os.path.splitext(src_path)
        out_path = f"{root} ({ {'en': 'Random', 'es': 'Aleatorio'}.get(i18n.LANG, 'Aleatoire')} {seed}){ext}"
    if os.path.abspath(out_path) == os.path.abspath(src_path):
        raise ValueError("refus d'écraser la ROM d'origine")
    for name, data in files.items():
        if len(data) > g.at[name][1]:
            raise ValueError(f"Données trop grandes pour la ROM ({name})")
    tid = pick_tid(g.base_tid, azahar_dir, set(used_tids))
    copy_with_tid(src_path, out_path, tid)
    try:
        with open(out_path, "r+b") as f:
            for name, data in files.items():
                at, size = g.at[name]
                f.seek(at)
                f.write(data + bytes(size - len(data)))
        check = ctr_rom.RomFS(out_path)
        try:
            ok = all(check.read(name)[:len(data)] == data for name, data in files.items())
        finally:
            check.close()
        if not ok:
            raise ValueError("Vérification de la ROM créée échouée")
    except Exception:
        os.remove(out_path)
        raise
    stem = os.path.splitext(out_path)[0]
    fiche = dict(fiche_base or {"species": {}, "moves": {}})
    fiche["randomized"] = True
    fiche_evolutions(fiche, fiche_base, ev)
    RC.fiche_update(fiche, fiche_base, d, tm_labels, R)
    import shiny_patch
    t = shiny_patch.side_threshold(src_path)
    if t != 8:
        fiche["shinyThreshold"] = t
    if os.path.isdir(src_path + ".exefsdir"):
        shutil.copytree(src_path + ".exefsdir", out_path + ".exefsdir", dirs_exist_ok=True)
    RC.write_ips(out_path, code_ips, src_path)
    with open(stem + ".pklab.json", "w", encoding="utf-8") as f:
        json.dump(fiche, f, ensure_ascii=False, separators=(",", ":"))
    report_path = stem + ".txt"
    f = io.StringIO()
    f.write(f"Randomizer PKLab\nROM d'origine : {os.path.basename(src_path)} ({g.game})\n"
            f"Graine : {seed}   Sans légendaires : {'oui' if opts['noLegendaries'] else 'non'}\n"
            f"Identifiant de la copie : {tid:016X} (sauvegarde séparée)\n\n")
    f.write("\n".join("- " + x for x in log) + "\n")
    if trainer_lines:
        f.write("\nDresseurs importants\n" + "\n".join(trainer_lines) + "\n")
    if gift_lines:
        f.write("\nPokémon offerts\n" + "\n".join(gift_lines) + "\n")
    if static_lines:
        f.write("\nPokémon fixes\n" + "\n".join(static_lines) + "\n")
    if trade_lines:
        f.write("\nÉchanges\n" + "\n".join(trade_lines) + "\n")
    if evo_changes:
        f.write("\nÉvolutions\n" + "\n".join(evolution_lines(evo_changes, names)) + "\n")
    if item_lines:
        f.write("\nObjets au sol\n" + "\n".join(item_lines) + "\n")
    if wild_lines:
        f.write("\nPokémon sauvages\n" + "\n".join(wild_lines) + "\n")
    with open(report_path, "w", encoding="utf-8") as out:
        out.write(i18n.tr_lines(f.getvalue()))
    return out_path, report_path, {"seed": seed, "game": g.game, "changes": log,
                                   "starters": [names(x) for x in starters.values()] if starters else None, "tid": f"{tid:016X}"}
