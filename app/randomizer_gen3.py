import os
import struct

import numpy as np

from randomizer_gen4 import to4_method, to4_type, to5_method, to5_type
from shiny_patch import THUMB_NOP

MAX_SPECIES = 386
MAX_MOVE = 354
MAX_ABILITY = 77
GBA = 0x08000000

GAMES3 = {"POKEMON EMER": "E", "POKEMON FIRE": "FRLG", "POKEMON LEAF": "FRLG", "POKEMON RUBY": "RS",
          "POKEMON SAPP": "RS"}

CHARS = {0: " ", 0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-", 0xB8: ",", 0xB4: "'", 0x1B: "é", 0x1A: "è", 0x16: "à",
         0x19: "ç", 0x1C: "ê", 0x20: "î", 0x24: "ô", 0x06: "É", 0xB5: "♂", 0xB6: "♀", 0x53: "PK", 0x54: "MN"}
for _i in range(26):
    CHARS[0xBB + _i] = chr(65 + _i)
    CHARS[0xD5 + _i] = chr(97 + _i)
for _i in range(10):
    CHARS[0xA1 + _i] = str(_i)


def gba_title(path):
    try:
        with open(path, "rb") as f:
            f.seek(0xA0)
            return f.read(12).split(b"\0")[0].decode("latin-1")
    except OSError:
        return None


def decode(rom, o, n):
    out = []
    for b in rom[o:o + n]:
        if b == 0xFF:
            break
        out.append(CHARS.get(b, "?"))
    return "".join(out)


def _encode(s):
    inv = {v: k for k, v in CHARS.items()}
    return bytes(inv[c] for c in s)


def _find_all(rom, pat):
    out, o = [], 0
    while (o := rom.find(pat, o)) >= 0:
        out.append(o)
        o += 1
    return out


def _one(rom, pat, what, delta=0):
    hits = _find_all(rom, pat)
    if len(hits) != 1:
        raise ValueError(f"3G : table {what} introuvable ({len(hits)} résultats)")
    return hits[0] + delta


BOSS_MARKERS3 = ("ELITE FOUR", "CONSEIL 4", "TOP 4", "ELITE VIER", "ALTO MANDO", "CONSIGLIO 4")
BOSS_CLASSES3 = {"CHAMPION", "CONSEIL 4", "MAITRE", "LEADER", "ELITE FOUR"}


class Gen3Rom:
    tm_count, hm_count = 50, 8
    has_move_category = False

    def __init__(self, rom, game_key):
        self.rom = rom
        self.key = game_key
        self.family = GAMES3[game_key]
        r = bytes(rom)
        self.base = _one(r, bytes([45, 49, 49, 45, 65, 65, 12, 3, 45]), "stats", -28)
        mv = [o - 12 for o in _find_all(r, bytes([0, 40, 0, 100, 35])) if r[o + 13:o + 17] == bytes([50, 1, 100, 25])]
        if len(mv) != 1:
            raise ValueError("3G : table des attaques introuvable")
        self.moves = mv[0]
        ev = [o - 40 for o in _find_all(r, struct.pack("<4H", 4, 16, 2, 0)) if r[o + 40:o + 46] == struct.pack("<3H", 4, 32, 3)]
        if len(ev) != 1:
            raise ValueError("3G : table des évolutions introuvable")
        self.evo = ev[0]
        ls = _one(r, struct.pack("<3H", 33 | 1 << 9, 45 | 4 << 9, 73 | 7 << 9), "attaques par niveau")
        ptrs = _find_all(r, struct.pack("<I", GBA + ls))
        self.learnptr = min(ptrs) if len(ptrs) == 2 and ptrs[1] - ptrs[0] == 4 else (ptrs[0] - 4 if len(ptrs) == 1 else None)
        if self.learnptr is None:
            raise ValueError("3G : pointeurs des attaques par niveau introuvables")
        bits = sum(1 << (t - 1) for t in (6, 9, 10, 11, 17, 19, 21, 22, 27, 32, 36, 42, 43, 44, 45))
        bits |= sum(1 << (49 + h) for h in (1, 4, 5, 6))
        tmc = [o - 8 for o in _find_all(r, bits.to_bytes(8, "little")) if r[o - 8:o] == bytes(8)]
        if len(tmc) != 1:
            raise ValueError("3G : table de compatibilité CT introuvable")
        self.tmcompat = tmc[0]
        self.tmlists = _find_all(r, struct.pack("<5H", 264, 337, 352, 347, 46))
        if not self.tmlists or any(r[o:o + 116] != r[self.tmlists[0]:self.tmlists[0] + 116] for o in self.tmlists):
            raise ValueError("3G : liste des CT introuvable")
        self.natdex = _one(r, b"".join(struct.pack("<H", i) for i in range(1, 252)), "Pokédex national")
        self.nat_of, self.int_of = {}, {}
        for i in range(1, 412):
            n = struct.unpack_from("<H", r, self.natdex + 2 * (i - 1))[0]
            if 1 <= n <= MAX_SPECIES:
                self.nat_of[i] = n
                self.int_of[n] = i
        if len(self.int_of) != MAX_SPECIES:
            raise ValueError("3G : correspondance des numéros d'espèces incomplète")
        self.items = self._find_items(r)
        self.tutors = None
        hits = _find_all(r, struct.pack("<5H", 5, 14, 25, 34, 38))
        if len(hits) == 1:
            n = 30 if self.family == "E" else 15
            width = 4 if n == 30 else 2
            compat = hits[0] + 2 * n
            compat += (-compat) % width
            if int.from_bytes(r[compat:compat + width], "little") == 0:
                self.tutors = (hits[0], n, compat, width)

    def nat(self, internal):
        return self.nat_of.get(internal, 0)

    def internal(self, nat):
        return self.int_of[nat]

    def _bs(self, s):
        return self.base + 28 * self.int_of[s]

    def stats(self, s):
        o = self._bs(s)
        return list(self.rom[o:o + 6])

    def set_stats(self, s, v):
        o = self._bs(s)
        self.rom[o:o + 6] = bytes(v)

    def bst(self, s):
        return sum(self.stats(s))

    def types(self, s):
        o = self._bs(s)
        return to5_type(self.rom[o + 6]), to5_type(self.rom[o + 7])

    def set_types(self, s, t1, t2):
        o = self._bs(s)
        self.rom[o + 6], self.rom[o + 7] = to4_type(t1), to4_type(t2)

    def abilities(self, s):
        o = self._bs(s)
        return [self.rom[o + 22], self.rom[o + 23], 0]

    def set_abilities(self, s, a):
        o = self._bs(s)
        self.rom[o + 22], self.rom[o + 23] = a[0], a[1]

    def set_growth(self, s, v):
        self.rom[self._bs(s) + 19] = v

    def raise_catch_rate(self, s, v):
        o = self._bs(s) + 8
        self.rom[o] = max(self.rom[o], v)

    def set_held_items(self, s, items):
        struct.pack_into("<2H", self.rom, self._bs(s) + 12, *(list(items) + [0, 0])[:2])

    def tm_bits(self, s):
        o = self.tmcompat + 8 * self.int_of[s]
        return int.from_bytes(self.rom[o:o + 8], "little")

    def set_tm_bits(self, s, bits):
        o = self.tmcompat + 8 * self.int_of[s]
        self.rom[o:o + 8] = bits.to_bytes(8, "little")

    def _learn_start(self, s):
        return struct.unpack_from("<I", self.rom, self.learnptr + 4 * self.int_of[s])[0] - GBA

    def learnset(self, s):
        o = self._learn_start(s)
        out = []
        while True:
            v = struct.unpack_from("<H", self.rom, o)[0]
            if v == 0xFFFF:
                return out
            out.append([v & 0x1FF, v >> 9])
            o += 2

    def set_learnset(self, s, entries):
        o = self._learn_start(s)
        for i, (mv, lv) in enumerate(entries):
            struct.pack_into("<H", self.rom, o + 2 * i, mv | lv << 9)

    def evolutions(self, s):
        o = self.evo + 40 * self.int_of[s]
        out = []
        for i in range(5):
            m, p, t = struct.unpack_from("<3H", self.rom, o + 8 * i)
            out.append([to5_method(m) if m else 0, p, self.nat(t)])
        return out

    def set_evo(self, s, slot, method, param, target):
        struct.pack_into("<4H", self.rom, self.evo + 40 * self.int_of[s] + 8 * slot,
                         to4_method(method) if method else 0, param, self.int_of[target] if target else 0, 0)

    def clear_evolutions(self, s):
        o = self.evo + 40 * self.int_of[s]
        self.rom[o:o + 40] = bytes(40)

    def set_evo_target(self, s, slot, target):
        struct.pack_into("<H", self.rom, self.evo + 40 * self.int_of[s] + 8 * slot + 4, self.int_of[target])

    def move(self, m):
        o = self.moves + 12 * m
        power, t4 = self.rom[o + 1], self.rom[o + 2]
        return {"type": to5_type(t4), "cat": 0 if power == 0 else (1 if t4 < 9 else 2), "power": power,
                "acc": self.rom[o + 3], "pp": self.rom[o + 4]}

    def set_move(self, m, d):
        o = self.moves + 12 * m
        self.rom[o + 1], self.rom[o + 2], self.rom[o + 3], self.rom[o + 4] = (
            d["power"], to4_type(d["type"]), d["acc"], d["pp"])

    def _find_items(self, r):
        for o in range(0, len(r) - 44 * 12, 4):
            if all(struct.unpack_from("<H", r, o + 44 * i + 14)[0] == i for i in range(12)):
                return o
        return None

    def held_item_pool(self):
        if self.items is None:
            return []
        out = []
        for i in range(1, 400):
            o = self.items + 44 * i
            if o + 44 > len(self.rom) or struct.unpack_from("<H", self.rom, o + 14)[0] not in (i, 0):
                break
            if struct.unpack_from("<H", self.rom, o + 14)[0] == i and self.rom[o + 18]:
                out.append(i)
        return out

    max_item = 376

    def _valid(self, p):
        return GBA <= p < GBA + len(self.rom) - 64

    def _slots_ok(self, p, n):
        o = p - GBA
        if o + 4 * n > len(self.rom):
            return False
        for i in range(n):
            lo, hi, sp = struct.unpack_from("<BBH", self.rom, o + 4 * i)
            if not (1 <= lo <= hi <= 100 and sp in self.nat_of):
                return False
        return True

    def _info_ok(self, p, n):
        if p == 0:
            return True
        if not self._valid(p):
            return False
        o = p - GBA
        q = struct.unpack_from("<I", self.rom, o + 4)[0]
        return 0 < self.rom[o] <= 100 and self._valid(q) and self._slots_ok(q, n)

    def _header_ok(self, p):
        if p < 0 or p + 20 > len(self.rom):
            return False
        ptrs = struct.unpack_from("<4I", self.rom, p + 4)
        return any(ptrs) and all(self._info_ok(x, n) for x, n in zip(ptrs, (12, 5, 5, 10)))

    def wild_headers(self):
        if hasattr(self, "_wild"):
            return self._wild
        W = np.frombuffer(bytes(self.rom[:len(self.rom) // 4 * 4]), "<u4")
        best = []
        seen = set()
        for i in np.nonzero((W >> 24) == 8)[0]:
            p = 4 * int(i) - 4
            if p in seen or not self._header_ok(p):
                continue
            while self._header_ok(p - 20):
                p -= 20
            run = []
            while self._header_ok(p):
                run.append(p)
                seen.add(p)
                p += 20
            if self.rom[p] == 0xFF and len(run) > len(best):
                best = run
        self._wild = best
        return best

    def encounter_slots(self):
        out = []
        for h, p in enumerate(self.wild_headers()):
            ptrs = struct.unpack_from("<4I", self.rom, p + 4)
            for kind, (x, n) in enumerate(zip(ptrs, (12, 5, 5, 10))):
                if not x:
                    continue
                q = struct.unpack_from("<I", self.rom, x - GBA + 4)[0] - GBA
                for i in range(n):
                    out.append((h, q + 4 * i + 2, [q + 4 * i, q + 4 * i + 1], kind in (1, 3)))
        return out

    def _trainer_ok(self, o):
        if o < 0 or o + 40 > len(self.rom):
            return False
        flags, size = self.rom[o], self.rom[o + 32]
        ptr = struct.unpack_from("<I", self.rom, o + 36)[0]
        if flags > 3 or not 1 <= size <= 6 or self.rom[o + 33:o + 36] != b"\0\0\0" or not self._valid(ptr):
            return False
        step = 16 if flags & 1 else 8
        q = ptr - GBA
        for k in range(size):
            iv, lv, sp = struct.unpack_from("<HHH", self.rom, q + step * k)
            if not (1 <= lv <= 100 and sp in self.nat_of and iv <= 255):
                return False
        return True

    def trainers(self):
        if hasattr(self, "_trainers"):
            return self._trainers
        W = np.frombuffer(bytes(self.rom[:len(self.rom) // 4 * 4]), "<u4")
        best = []
        for i in np.nonzero((W >> 24) == 8)[0]:
            o = 4 * int(i) - 36
            if best and best[0] <= o <= best[-1]:
                continue
            if not self._trainer_ok(o):
                continue
            run = []
            while self._trainer_ok(o):
                run.append(o)
                o += 40
            if len(run) > len(best):
                best = run
        self._trainers = best
        return best

    def _class_marker(self):
        for name in BOSS_MARKERS3:
            o = self.rom.find(_encode(name) + b"\xFF")
            if o >= 0:
                return o
        return -1

    def class_table(self):
        o = self._class_marker()
        if o < 0:
            return None
        k = 0
        while k < 120:
            e = self.rom[o - 13 * (k + 1):o - 13 * k]
            t = e[:e.index(0xFF)] if 0xFF in e else None
            if t is None or not all(b in CHARS for b in t):
                break
            k += 1
        return o - 13 * k

    def class_names(self):
        o = self._class_marker()
        if o < 0:
            return []
        k = 0
        while k < 120:
            e = self.rom[o - 13 * (k + 1):o - 13 * k]
            t = e[:e.index(0xFF)] if 0xFF in e else None
            if t is None or not all(b in CHARS for b in t):
                break
            k += 1
        start = o - 13 * k
        out = []
        for j in range(120):
            e = self.rom[start + 13 * j:start + 13 * j + 13]
            if 0xFF not in e:
                break
            out.append(decode(self.rom, start + 13 * j, 13))
        return out


def randomize_wild(g, rng, opts, pool, bst, log, names, pick, type_list):
    import randomizer as R
    mode = opts["wild"]
    if mode == "off" and not opts["wildLevels"]:
        return []
    types_of = {s: set(type_list(*g.types(s))) for s in pool}
    water_pool = [s for s in pool if R.WATER in types_of[s]]
    global_map, zone_maps, themes, seen_all = {}, {}, {}, set()
    by_table, count, levels_done = {}, 0, set()
    for table, off, lv_offs, water in g.encounter_slots():
        old = g.nat(struct.unpack_from("<H", g.rom, off)[0])
        if not old:
            continue
        src = pool
        if opts["wildTheme"]:
            theme = themes.setdefault(table, rng.randrange(R.NUM_TYPES))
            src = [x for x in pool if theme in types_of[x]] or pool
        if water and opts["wildWater"]:
            src = [x for x in src if x in water_pool] or water_pool or src
        new = old
        if mode != "off":
            cands = ([x for x in src if x not in seen_all] or src) if opts["catchEmAll"] else src
            key = (old, water)
            if mode == "global":
                if key not in global_map:
                    global_map[key] = pick(rng, cands, bst, old, opts["wildSimilar"], set(global_map.values()))
                new = global_map[key]
            elif mode == "zone":
                zm = zone_maps.setdefault(table, {})
                if key not in zm:
                    zm[key] = pick(rng, cands, bst, old, opts["wildSimilar"], set(zm.values()))
                new = zm[key]
            else:
                new = pick(rng, cands, bst, old, opts["wildSimilar"])
            seen_all.add(new)
            struct.pack_into("<H", g.rom, off, g.internal(new))
        if opts["wildLevels"]:
            for lo in lv_offs:
                if lo not in levels_done:
                    levels_done.add(lo)
                    g.rom[lo] = max(1, min(100, round(g.rom[lo] * (1 + opts["wildLevels"] / 100))))
            a, b = lv_offs
            if g.rom[a] > g.rom[b]:
                g.rom[a] = g.rom[b]
        by_table.setdefault(table, {})[(old, new)] = True
        count += 1
    log.append(f"Pokémon sauvages : mode {mode}, {count} emplacements"
               + (", force similaire" if opts["wildSimilar"] and mode != "off" else "")
               + (", un type par zone" if opts["wildTheme"] else "")
               + (", Eau en surf/pêche" if opts["wildWater"] else "")
               + (f", niveaux {opts['wildLevels']:+d} %" if opts["wildLevels"] else ""))
    lines = []
    for table in sorted(by_table):
        lines.append(f"  Zone {table}")
        for old, new in sorted(by_table[table]):
            if old != new:
                lines.append(f"    {names(old)} -> {names(new)}")
    return lines


def _norm(s):
    return s.upper().replace("Î", "I").replace("É", "E")


def _line_stage(pre, starters):
    out = {}
    for i, s in enumerate(starters):
        stage, cur = 0, [s]
        while cur and stage < 3:
            for x in cur:
                out.setdefault(x, (i, stage))
            cur, stage = [t for t, p in pre.items() if p in cur], stage + 1
    return out


def randomize_trainers(g, rng, opts, pool, bst, log, names, pick, type_list, best_moves, moves_at_level,
                       old_starters=None, starter_map=None, pre=None):
    import randomizer as R
    touch = (opts["trainers"] != "off" or opts["trainerLevels"] or opts["fullyEvolvedAt"] or opts["betterMovesets"]
             or opts["learnsets"] == "metronome" or (starter_map and opts["rivalStarter"]))
    if not touch:
        return []
    classes = g.class_names()
    pool = [x for x in pool if 25 not in g.abilities(x)[:2]] or pool
    important_names = BOSS_CLASSES3
    types_of = {s: set(type_list(*g.types(s))) for s in pool}
    old_lines = _line_stage(pre or {}, old_starters) if starter_map and opts["rivalStarter"] else {}
    new_lines = {}
    if old_lines:
        for i, s in enumerate(old_starters):
            chain, cur = [], starter_map[s]
            for _ in range(3):
                chain.append(cur)
                nxt = [t for m, _, t in g.evolutions(cur) if m and t]
                if not nxt:
                    break
                cur = nxt[0]
            new_lines[i] = chain
    lines, count, done_parties, rivals = [], 0, set(), 0
    order = list(enumerate(g.trainers(), 1))
    if opts["e4Unique"]:
        order.sort(key=lambda x: not (g.rom[x[1] + 1] < len(classes) and _norm(classes[g.rom[x[1] + 1]]) in important_names))
    e4set, used_all = set(), set()
    for t, o in order:
        flags, cls, n = g.rom[o], g.rom[o + 1], g.rom[o + 32]
        party = struct.unpack_from("<I", g.rom, o + 36)[0] - GBA
        if party in done_parties:
            continue
        done_parties.add(party)
        step = 16 if flags & 1 else 8
        cname = classes[cls] if cls < len(classes) else f"classe {cls}"
        important = _norm(cname) in important_names
        src, theme = pool, None
        if opts["trainers"] == "theme" or (opts["bossTheme"] and important and opts["trainers"] != "off"):
            theme = rng.randrange(R.NUM_TYPES)
            src = [x for x in pool if theme in types_of[x]] or pool
        src = R._trainer_src(src, opts, important, e4set, used_all)
        team, used, is_rival = [], set(), False
        for k in range(n):
            p = party + step * k
            lv = struct.unpack_from("<H", g.rom, p + 2)[0]
            old = g.nat(struct.unpack_from("<H", g.rom, p + 4)[0])
            new = old
            if old in old_lines:
                i, stage = old_lines[old]
                chain = new_lines[i]
                new = chain[min(stage, len(chain) - 1)]
                is_rival = True
            elif opts["trainers"] != "off" and old:
                new = pick(rng, src, bst, old, opts["trainerSimilar"], used)
            if opts["trainerLevels"]:
                lv = max(1, min(100, round(lv * (1 + opts["trainerLevels"] / 100))))
                struct.pack_into("<H", g.rom, p + 2, lv)
            if opts["evolveByLevel"] and new and old not in old_lines:
                new = R._evolve_for_level(g, new, lv, rng)
            if opts["fullyEvolvedAt"] and lv >= opts["fullyEvolvedAt"] and new and old not in old_lines:
                for _ in range(3):
                    nxt = [x for m, _, x in g.evolutions(new) if m and x and x != new]
                    if not nxt:
                        break
                    new = rng.choice(nxt)
            used.add(new)
            used_all.add(new)
            if important:
                e4set.add(new)
            if new != old:
                struct.pack_into("<H", g.rom, p + 4, g.internal(new))
            if flags & 1:
                mo = p + (8 if flags & 2 else 6)
                if opts["learnsets"] == "metronome":
                    struct.pack_into("<4H", g.rom, mo, R.METRONOME, 0, 0, 0)
                elif opts["betterMovesets"]:
                    struct.pack_into("<4H", g.rom, mo, *best_moves(g, new, lv))
                elif new != old or opts["learnsets"] != "off":
                    struct.pack_into("<4H", g.rom, mo, *moves_at_level(g, new, lv))
            team.append(f"{names(old)}→{names(new)} Nv{lv}" if new != old else f"{names(new)} Nv{lv}")
        count += 1
        rivals += is_rival
        if important or is_rival:
            name = decode(g.rom, o + 4, 12)
            lines.append(f"  #{t} {cname} {name}{' (type ' + R.TYPE_FR[theme] + ')' if theme is not None else ''} : "
                         + ", ".join(team))
    log.append(f"Dresseurs : {opts['trainers']}, {count} équipes"
               + (", force similaire" if opts["trainerSimilar"] and opts["trainers"] != "off" else "")
               + (", Champions / Conseil 4 / Maître : un type chacun" if opts["bossTheme"] and opts["trainers"] != "off" else "")
               + (f", niveaux {opts['trainerLevels']:+d} %" if opts["trainerLevels"] else "")
               + (f", complètement évolués dès le Nv. {opts['fullyEvolvedAt']}" if opts["fullyEvolvedAt"] else "")
               + (", meilleures attaques (dresseurs à attaques choisies)" if opts["betterMovesets"] else "")
               + (f", lignée des starters suivie ({rivals} équipes)" if old_lines else ""))
    return lines


STARTERS3 = {"RS": (252, 255, 258), "E": (252, 255, 258), "FRLG": (1, 7, 4)}


def _frlg_sites(g):
    out = []
    for n in range(3):
        pat = bytes([0x16]) + struct.pack("<HH", 0x4001, n) + bytes([0x16]) + struct.pack("<H", 0x4002)
        hits = [o for o in _find_all(bytes(g.rom), pat) if g.rom[o + 10:o + 13] == bytes([0x16, 0x03, 0x40])
                and g.rom[o + 15:o + 18] == bytes([0x16, 0x04, 0x40])
                and {struct.unpack_from("<H", g.rom, o + d)[0] for d in (8, 13)} in ({1, 4}, {4, 7}, {1, 7})]
        if len(hits) != 1:
            return []
        out.append((hits[0] + 8, hits[0] + 13))
    return out


def randomize_starters(g, rng, opts, pool, pre, log, names):
    if opts["starters"] == "off":
        return None
    old = STARTERS3[g.family]
    if g.family == "FRLG":
        sites = _frlg_sites(g)
        if not sites or [g.nat(struct.unpack_from("<H", g.rom, a)[0]) for a, _ in sites] != list(old):
            log.append("Starters : NON modifiés (script du labo non trouvé)")
            return None
    else:
        table = struct.pack("<3H", *[g.internal(s) for s in old])
        hits = _find_all(bytes(g.rom), table)
        if len(hits) != 1:
            log.append("Starters : NON modifiés (table non trouvée)")
            return None
    if opts["starters"] == "custom":
        chosen = [int(x) for x in opts["starterList"][:3] if str(x).strip()]
        if len(chosen) != 3 or any(not (1 <= c <= MAX_SPECIES) for c in chosen):
            raise ValueError("Starters choisis : il faut 3 Pokémon de la 3G (n° 1 à 386)")
    else:
        evolves = {s: [t for m, _, t in g.evolutions(s) if m and t] for s in range(1, MAX_SPECIES + 1)}
        basics = [s for s in pool if s not in pre and evolves[s] and s not in old]
        if opts["starter3stage"]:
            basics = [s for s in basics if any(evolves[t] for t in evolves[s])] or basics
        if opts["starters"] == "randomAny":
            basics = [s for s in pool if s not in old]
        import randomizer as R
        chosen = R._three_starters(rng, basics, g.types, opts["starterTypes"])
    mapping = dict(zip(old, chosen))
    if g.family == "FRLG":
        for a, b in sites:
            p = g.nat(struct.unpack_from("<H", g.rom, a)[0])
            r = g.nat(struct.unpack_from("<H", g.rom, b)[0])
            struct.pack_into("<H", g.rom, a, g.internal(mapping[p]))
            struct.pack_into("<H", g.rom, b, g.internal(mapping.get(r, r)))
        where = "script du labo (joueur + rival)"
    else:
        g.rom[hits[0]:hits[0] + 6] = struct.pack("<3H", *[g.internal(s) for s in chosen])
        where = "table du sac du Prof. (image, cri, Pokémon donné)"
    log.append("Starters : " + ", ".join(f"{names(o)} -> {names(n)}" for o, n in mapping.items()) + f" ({where})")
    return mapping


GIFTS3 = {"E": {(155, 5), (158, 5), (152, 5), (374, 5), (351, 25), (345, 20), (347, 20)},
          "FRLG": {(133, 25), (138, 5), (140, 5), (142, 5), (129, 5), (131, 25)},
          "RS": {(374, 5), (351, 25), (345, 20), (347, 20)}}
FOSSILS3 = {345, 347, 138, 140, 142}
STATICS3 = {"E": {(379, 40), (101, 30), (185, 40), (377, 40), (378, 40), (382, 70), (100, 25), (352, 30), (384, 70), (383, 70)},
            "FRLG": {(150, 70), (146, 50), (105, 30), (145, 50), (101, 34), (143, 30), (144, 50), (97, 30)},
            "RS": {(379, 40), (383, 45), (382, 45), (377, 40), (378, 40), (100, 25), (352, 30), (384, 70), (380, 50),
                   (381, 50), (101, 30)}}
EVENTMONS3 = {"E": {(380, 50), (381, 50), (151, 30), (386, 30), (249, 70), (250, 70)}, "FRLG": {(386, 30), (249, 70), (250, 70)},
              "RS": set()}
EGGS3 = {"E": (360,), "FRLG": (175,), "RS": (360,)}
TRADES3 = {"E": (273, 280, 4), "FRLG": (122, 63, 9), "RS": (296, 287, 3)}
TM_ITEMS3 = range(289, 339)


def _finditem_sites(g):
    out, o, r = [], 0, bytes(g.rom)
    pat = b"\x1A\x00\x80"
    while (o := r.find(pat, o)) >= 0:
        if r[o + 5:o + 8] == b"\x1A\x01\x80" and r[o + 10:o + 12] == b"\x09\x01":
            it = struct.unpack_from("<H", r, o + 3)[0]
            if 0 < it < 400:
                out.append(o + 3)
        o += 1
    return out


def _script_sites(g, op, pairs):
    r = bytes(g.rom)
    out = {}
    for sp, lv in pairs:
        pat = bytes([op]) + struct.pack("<HB", g.internal(sp), lv)
        o = 0
        while (o := r.find(pat, o)) >= 0:
            out[o + 1] = (sp, lv)
            o += 1
    return out


def _trade_table(g):
    sp, req, n = TRADES3[g.family]
    r = bytes(g.rom)
    pat = struct.pack("<H", g.internal(sp))
    o = 0
    while (o := r.find(pat, o)) >= 0:
        base = o - 12
        if base >= 0 and struct.unpack_from("<H", r, base + 0x38)[0] == g.internal(req) and \
                all(g.nat(struct.unpack_from("<H", r, base + 60 * k + 12)[0]) and
                    g.nat(struct.unpack_from("<H", r, base + 60 * k + 0x38)[0]) for k in range(n)):
            return base, n
        o += 1
    return None, 0


def _sellable_items(g):
    key_pocket = g.rom[g.items + 44 * 259 + 26]
    good = []
    for it in range(1, 377):
        o = g.items + 44 * it
        if struct.unpack_from("<H", g.rom, o + 14)[0] == it and g.rom[o + 26] != key_pocket                 and struct.unpack_from("<H", g.rom, o + 16)[0] > 0 and not 121 <= it <= 132 and not 289 <= it <= 346:
            good.append(it)
    return good


def _hidden_item_sites(g):
    r, n, out, seen = bytes(g.rom), len(g.rom), [], set()
    for o in range(0, n - 20, 4):
        cnt = r[o:o + 4]
        if cnt[3] == 0 or cnt[0] > 80 or cnt[1] > 64 or cnt[2] > 64 or cnt[3] > 64:
            continue
        ptrs = struct.unpack_from("<4I", r, o + 4)
        in_rom = lambda p: GBA <= p < GBA + n and p % 4 == 0
        if any(not (in_rom(p) or (c == 0 and p == 0)) for c, p in zip(cnt, ptrs)):
            continue
        b = ptrs[3] - GBA
        if b in seen or b + 12 * cnt[3] > n:
            continue
        ok = True
        for k in range(cnt[3]):
            q = b + 12 * k
            x, y = struct.unpack_from("<HH", r, q)
            if x > 400 or y > 400 or r[q + 5] > 8 or struct.unpack_from("<H", r, q + 6)[0]:
                ok = False
                break
        if not ok:
            continue
        seen.add(b)
        for k in range(cnt[3]):
            q = b + 12 * k
            if r[q + 5] == 7 and 0 < struct.unpack_from("<H", r, q + 8)[0] < 377:
                out.append(q + 8)
    return out


def _shop_lists(g, lo=None, hi=None):
    r, n, out = bytes(g.rom), len(g.rom), {}
    o = 0
    while (o := r.find(b"\x86", o)) >= 0:
        if o + 5 <= n and (lo is None or lo <= o <= hi):
            p = struct.unpack_from("<I", r, o + 1)[0]
            if GBA <= p < GBA + n - 2 and p % 2 == 0 and (p - GBA) not in out:
                q, items = p - GBA, []
                while q + 2 <= n and len(items) <= 40:
                    v = struct.unpack_from("<H", r, q)[0]
                    if v == 0:
                        break
                    items.append(v)
                    q += 2
                if 1 <= len(items) <= 40 and q + 2 <= n and all(0 < i < 377 for i in items):
                    out[p - GBA] = items
        o += 1
    return out


def randomize_events(g, rng, opts, pool, bst, pre, log, names, pick):
    import randomizer as R
    lines = []
    script_lo = script_hi = None
    items = _finditem_sites(g)
    known = items + list(_script_sites(g, 0x79, GIFTS3[g.family])) + list(_script_sites(g, 0xB6, STATICS3[g.family]))
    if known:
        script_lo, script_hi = min(known) - 0x40000, max(known) + 0x40000
    if opts["statics"] != "off":
        sites = _script_sites(g, 0xB6, STATICS3[g.family])
        r = bytes(g.rom)
        for sp, lv in EVENTMONS3[g.family]:
            pat = bytes([0x16, 0x04, 0x80]) + struct.pack("<H", g.internal(sp)) + bytes([0x16, 0x05, 0x80]) + struct.pack("<H", lv)
            o = 0
            while (o := r.find(pat, o)) >= 0:
                sites[o + 3] = (sp, lv)
                o += 1
        legend_pool = [s for s in range(1, MAX_SPECIES + 1) if s in R.LEGENDARIES]
        mapping = {}
        for off, (sp, lv) in sorted(sites.items()):
            if sp not in mapping:
                if opts["statics"] == "swap" and sp in R.LEGENDARIES:
                    mapping[sp] = pick(rng, legend_pool, bst, sp, True, set(mapping.values()) | {sp})
                else:
                    mapping[sp] = pick(rng, [x for x in pool if x not in R.LEGENDARIES] or pool, bst, sp, True,
                                       set(mapping.values()))
            struct.pack_into("<H", g.rom, off, g.internal(mapping[sp]))
            near = bytes(g.rom[off - 0x200:off + 0x200])
            for pat in (bytes([0xA1]) + struct.pack("<H", g.internal(sp)),):
                o = 0
                while (o := near.find(pat, o)) >= 0:
                    if o + 3 <= len(near):
                        struct.pack_into("<H", g.rom, off - 0x200 + o + 1, g.internal(mapping[sp]))
                    o += 1
            o = 0
            while (o := near.find(b"\x16", o)) >= 0:
                if o + 5 <= len(near) and near[o + 2] in (0x40, 0x80) and struct.unpack_from("<H", near, o + 3)[0] == g.internal(sp):
                    struct.pack_into("<H", g.rom, off - 0x200 + o + 3, g.internal(mapping[sp]))
                o += 1
        log.append(f"Pokémon fixes : {len(sites)} combats, {len(mapping)} espèces"
                   + (" (légendaires ↔ légendaires)" if opts["statics"] == "swap" else " (force similaire)"))
        lines += [f"  {names(a)} -> {names(b)}" for a, b in mapping.items()]
    if opts["gifts"] != "off" or opts["fossils"] != "off":
        sites = _script_sites(g, 0x79, GIFTS3[g.family])
        mapping = {}
        for off, (sp, lv) in sorted(sites.items()):
            fossil = sp in FOSSILS3
            if (fossil and opts["fossils"] == "off") or (not fossil and opts["gifts"] == "off"):
                continue
            if sp not in mapping:
                similar = opts["fossilSimilar"] if fossil else opts["giftSimilar"]
                mapping[sp] = pick(rng, pool, bst, sp, similar, set(mapping.values()))
            struct.pack_into("<H", g.rom, off, g.internal(mapping[sp]))
        log.append(f"Pokémon offerts / fossiles : {len(mapping)} espèces changées (les dialogues citent encore les anciennes)")
        lines += [f"  {names(a)} -> {names(b)} (offert)" for a, b in mapping.items()]
    if opts["eggs"] != "off":
        r = bytes(g.rom)
        basics = [s for s in pool if s not in pre]
        done = 0
        for sp in EGGS3[g.family]:
            pat = bytes([0x7A]) + struct.pack("<H", g.internal(sp))
            hits, o = [], 0
            while (o := r.find(pat, o)) >= 0:
                if script_lo is None or script_lo <= o <= script_hi:
                    hits.append(o)
                o += 1
            if len(hits) == 1:
                new = rng.choice(basics)
                struct.pack_into("<H", g.rom, hits[0] + 1, g.internal(new))
                lines.append(f"  œuf {names(sp)} -> {names(new)}")
                done += 1
        log.append(f"Œufs offerts : {done} changé(s) (Pokémon de base)")
    if opts["trades"] != "off":
        base, n = _trade_table(g)
        if base is None:
            log.append("Échanges : NON modifiés (table introuvable)")
        else:
            for k in range(n):
                o = base + 60 * k
                got = g.nat(struct.unpack_from("<H", g.rom, o + 12)[0])
                asked = g.nat(struct.unpack_from("<H", g.rom, o + 0x38)[0])
                new_got = pick(rng, pool, bst, got, False)
                struct.pack_into("<H", g.rom, o + 12, g.internal(new_got))
                new_asked = asked
                if opts["trades"] == "both":
                    new_asked = pick(rng, pool, bst, asked, False, {new_got})
                    struct.pack_into("<H", g.rom, o + 0x38, g.internal(new_asked))
                lines.append(f"  échange : {names(asked)} -> {names(new_asked)} contre {names(got)} -> {names(new_got)}")
            log.append(f"Échanges en jeu : {n} " + ("(Pokémon reçus et demandés)" if opts["trades"] == "both" else "(Pokémon reçus)"))
    if opts["fieldItems"] != "off" and items:
        good = _sellable_items(g)
        for label, sites in (("Objets au sol", items), ("Objets cachés", _hidden_item_sites(g))):
            if not sites:
                continue
            cur = [struct.unpack_from("<H", g.rom, o)[0] for o in sites]
            tms = [i for i, it in enumerate(cur) if it in TM_ITEMS3]
            if opts["fieldItems"] == "shuffle":
                new = cur[:]
                rng.shuffle(new)
            else:
                new = [rng.choice(list(TM_ITEMS3)) if it in TM_ITEMS3 else rng.choice(good) for it in cur]
            for o, it in zip(sites, new):
                struct.pack_into("<H", g.rom, o, it)
            log.append(f"{label} : {len(sites)} " + ("mélangés" if opts["fieldItems"] == "shuffle" else
                                                     f"aléatoires ({len(tms)} CT restent des CT)"))
    if opts["shops"] != "off":
        shops = _shop_lists(g, script_lo, script_hi)
        good = [x for x in _sellable_items(g) if x != 4]
        price = lambda it: struct.unpack_from("<H", g.rom, g.items + 44 * it + 16)[0]
        keep = lambda it: it in TM_ITEMS3 or it == 4 or not 0 < it < 377 or it not in good
        changed = 0
        if opts["shops"] == "shuffle":
            slots = [(o, k) for o, lst in sorted(shops.items()) for k, it in enumerate(lst) if not keep(it)]
            vals = [shops[o][k] for o, k in slots]
            rng.shuffle(vals)
            for (o, k), v in zip(slots, vals):
                shops[o][k] = v
            for o, lst in shops.items():
                for k in range(len(lst)):
                    if lst.index(lst[k]) != k and not keep(lst[k]):
                        free = [x for x in good if x not in lst and price(x) <= 4 * max(1, price(lst[k]))]
                        if free:
                            lst[k] = rng.choice(free)
        else:
            for o, lst in shops.items():
                for k, it in enumerate(lst):
                    if keep(it):
                        continue
                    p = price(it)
                    near = [x for x in good if x not in lst and p // 2 <= price(x) <= p * 2] or [x for x in good if x not in lst]
                    lst[k] = rng.choice(near)
        for o, lst in shops.items():
            for k, it in enumerate(lst):
                if struct.unpack_from("<H", g.rom, o + 2 * k)[0] != it:
                    struct.pack_into("<H", g.rom, o + 2 * k, it)
                    changed += 1
        log.append(f"Magasins : {len(shops)} listes, {changed} objets changés (CT et Poké Balls gardés)"
                   + (" - mélangés" if opts["shops"] == "shuffle" else " - prix proches"))
    return lines


def trainer_categories(g, pre):
    classes = g.class_names()
    lines = _line_stage(pre, STARTERS3[g.family])
    out = {}
    for o in g.trainers():
        cname = classes[g.rom[o + 1]] if g.rom[o + 1] < len(classes) else ""
        q = struct.unpack_from("<I", g.rom, o + 36)[0] - GBA
        step = 16 if g.rom[o] & 1 else 8
        species = [g.nat(struct.unpack_from("<H", g.rom, q + step * k + 4)[0]) for k in range(g.rom[o + 32])]
        out[o] = "boss" if _norm(cname) in BOSS_CLASSES3 else \
            "important" if any(s in lines for s in species) else "regular"
    return out


def _free_space(g, size):
    r = np.frombuffer(bytes(g.rom), np.uint8)
    ff = (r == 0xFF).astype(np.int8)
    d = np.diff(np.concatenate(([0], ff, [0])))
    st, en = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
    i = int(np.argmax(en - st))
    start = (int(st[i]) + 0x1000 + 3) & ~3
    if start + size > int(en[i]):
        return None
    return start


def trainer_extras(g, rng, opts, pool, bst, cats, log, pick, best_moves, moves_at_level):
    import randomizer as R
    cat_key = {"boss": "Boss", "important": "Important", "regular": "Regular"}
    if not any(opts["extra" + c] for c in cat_key.values()) and not any(opts["items" + c] for c in cat_key.values()):
        return
    held = g.held_item_pool()
    berry_pocket = g.rom[g.items + 44 * 133 + 26]
    berries = [i for i in held if g.rom[g.items + 44 * i + 26] == berry_pocket]
    moved, added, items = [], 0, 0
    sharers = {}
    for o in g.trainers():
        sharers.setdefault(struct.unpack_from("<I", g.rom, o + 36)[0] - GBA, []).append(o)
    for q, owners in sharers.items():
        o = owners[0]
        flags, n = g.rom[o], g.rom[o + 32]
        step = 16 if flags & 1 else 8
        mons = []
        for k in range(n):
            p = q + step * k
            iv, lv, sp = struct.unpack_from("<HHH", g.rom, p)
            item = struct.unpack_from("<H", g.rom, p + 6)[0] if flags & 2 else 0
            moves = list(struct.unpack_from("<4H", g.rom, p + (8 if flags & 2 else 6))) if flags & 1 else None
            mons.append({"iv": iv, "lv": lv, "sp": sp, "item": item, "moves": moves})
        cat = cat_key[cats.get(o, "regular")]
        for _ in range(max(0, min(int(opts["extra" + cat] or 0), 6 - len(mons)))):
            ref = max(mons, key=lambda d: d["lv"] & 0xFF)
            used = {g.nat(d["sp"]) for d in mons}
            old = g.nat(ref["sp"])
            sp = pick(rng, pool, bst, old if old in bst else rng.choice(pool), True, used)
            mons.append({"iv": ref["iv"], "lv": ref["lv"], "sp": g.internal(sp), "item": 0, "moves": None})
            added += 1
        new_flags = flags
        if opts["items" + cat] and held:
            new_flags |= 2
            choices = berries if opts["itemsConsumable"] and berries else held
            top = max(d["lv"] & 0xFF for d in mons)
            first_top = next(d for d in mons if d["lv"] & 0xFF == top)
            for d in mons:
                if not opts["itemsHighestOnly"] or d is first_top:
                    d["item"] = rng.choice(choices)
                    items += 1
        if new_flags & 1:
            for d in mons:
                if d["moves"] is None:
                    nat = g.nat(d["sp"])
                    d["moves"] = [R.METRONOME, 0, 0, 0] if opts["learnsets"] == "metronome" else \
                        best_moves(g, nat, d["lv"] & 0xFF) if opts["betterMovesets"] else moves_at_level(g, nat, d["lv"] & 0xFF)
        out = bytearray()
        for d in mons:
            out += struct.pack("<HHH", d["iv"], d["lv"], d["sp"])
            if new_flags & 1:
                out += struct.pack("<H", d["item"]) + struct.pack("<4H", *d["moves"]) if new_flags & 2 else \
                    struct.pack("<4H", *d["moves"]) + b"\0\0"
            else:
                out += struct.pack("<H", d["item"] if new_flags & 2 else 0)
        if len(mons) == n:
            g.rom[q:q + len(out)] = out
        else:
            moved.append((owners, bytes(out)))
        for ow in owners:
            g.rom[ow] = new_flags
            g.rom[ow + 32] = len(mons)
    if moved:
        total = sum((len(b) + 3) & ~3 for _, b in moved)
        at = _free_space(g, total)
        if at is None:
            log.append("Dresseurs : Pokémon en plus NON ajoutés (pas assez de place libre dans la ROM)")
            return
        for owners, b in moved:
            g.rom[at:at + len(b)] = b
            for ow in owners:
                struct.pack_into("<I", g.rom, ow + 36, GBA + at)
            at += (len(b) + 3) & ~3
    parts = []
    if added:
        parts.append(f"{added} Pokémon en plus (boss {opts['extraBoss']}, importants {opts['extraImportant']}, "
                     f"autres {opts['extraRegular']})")
    if items:
        parts.append(f"{items} objets tenus" + (" (baies seulement)" if opts["itemsConsumable"] else "")
                     + (" (plus haut niveau seulement)" if opts["itemsHighestOnly"] else ""))
    log.append("Dresseurs, équipes agrandies : " + (", ".join(parts) or "rien à changer")
               + (f" ; {len(moved)} équipes déplacées dans l'espace libre de la ROM" if moved else ""))


def make_doubles(g, opts, log):
    if not opts["doubleBattles"]:
        return
    n = 0
    for o in g.trainers():
        if g.rom[o + 32] >= 2 and not g.rom[o + 0x18]:
            g.rom[o + 0x18] = 1
            n += 1
    log.append(f"Combats doubles : {n} dresseurs de plus (ceux qui ont au moins 2 Pokémon) (phase expérimentale)")


def shuffle_names(g, rng, opts, log):
    if opts["shuffleTrainerNames"]:
        offs = [o + 4 for o in g.trainers() if g.rom[o + 4] != 0xFF]
        names = [bytes(g.rom[o:o + 12]) for o in offs]
        rng.shuffle(names)
        for o, nm in zip(offs, names):
            g.rom[o:o + 12] = nm
        log.append(f"Noms des dresseurs : {len(offs)} mélangés")
    if opts["shuffleClassNames"]:
        start = g.class_table()
        if start is None:
            log.append("Noms des classes : NON modifiés (table introuvable)")
        else:
            n = len(g.class_names())
            entries = [bytes(g.rom[start + 13 * i:start + 13 * i + 13]) for i in range(n)]
            rng.shuffle(entries)
            for i, e in enumerate(entries):
                g.rom[start + 13 * i:start + 13 * i + 13] = e
            log.append(f"Noms des classes de dresseurs : {n} mélangés")


def randomize_tutors(g, rng, opts, log):
    import randomizer as R
    if opts["tutorMoves"] == "off" and opts["tutorCompat"] == "off" and not opts["tutorSanity"]:
        return
    if not g.tutors:
        log.append("Tuteurs : aucun dans ce jeu")
        return
    off, n, compat, width = g.tutors
    moves = list(struct.unpack_from(f"<{n}H", g.rom, off))
    if opts["tutorMoves"] == "random":
        banned = {R.STRUGGLE} | (R.GAME_BREAKING_MOVES if opts["noGameBreaking"] else set())
        tm = set(struct.unpack_from("<58H", g.rom, g.tmlists[0]))
        pool = [m for m in range(1, MAX_MOVE + 1) if m not in banned and m not in tm]
        data = {m: g.move(m) for m in pool}
        good = [m for m in pool if data[m]["cat"] != 0 and data[m]["power"] >= 70]
        pct = max(0, min(100, int(opts["goodDamaging"] or 0)))
        used = set()
        for i in range(n):
            src = good if pct and rng.random() * 100 < pct else pool
            src = [m for m in src if m not in used] or [m for m in pool if m not in used]
            moves[i] = rng.choice(src)
            used.add(moves[i])
        struct.pack_into(f"<{n}H", g.rom, off, *moves)
    types = {m: g.move(m)["type"] for m in moves}
    index = {m: i for i, m in enumerate(moves)}
    full = (1 << n) - 1
    for s in range(1, MAX_SPECIES + 1):
        o = compat + width * g.internal(s)
        bits = int.from_bytes(g.rom[o:o + width], "little")
        if opts["tutorCompat"] == "all":
            bits = full
        elif opts["tutorCompat"] in ("random", "type"):
            count = bin(bits & full).count("1")
            st = set(R._type_list(*g.types(s)))
            cands = list(range(n))
            w = [4.0 if opts["tutorCompat"] == "type" and types[moves[i]] in st else 1.0 for i in cands]
            chosen = set()
            while len(chosen) < count and cands:
                k = rng.choices(range(len(cands)), weights=w)[0]
                chosen.add(cands.pop(k))
                w.pop(k)
            bits = sum(1 << i for i in chosen)
        if opts["tutorSanity"]:
            for mv, _ in g.learnset(s):
                if mv in index:
                    bits |= 1 << index[mv]
        g.rom[o:o + width] = bits.to_bytes(width, "little")
    log.append(f"Tuteurs ({n}) : " + ", ".join(x for x, on in (
        ("attaques aléatoires (les dialogues citent encore les anciennes)", opts["tutorMoves"] == "random"),
        ({"random": "compatibilité aléatoire (même nombre)", "type": "compatibilité aléatoire, types du Pokémon privilégiés",
          "all": "tous compatibles"}.get(opts["tutorCompat"], ""), opts["tutorCompat"] != "off"),
        ("attaques apprises par niveau compatibles", opts["tutorSanity"])) if on))


TM_ORDER3 = [f"CT{i:02d}" for i in range(1, 51)] + [f"CS{i:02d}" for i in range(1, 9)]


def randomize_tm_moves(g, rng, opts, log):
    import randomizer as R
    if opts["tmMoves"] == "off":
        return None
    labels = dict(zip(TM_ORDER3, struct.unpack_from("<58H", g.rom, g.tmlists[0])))
    hm_moves = {labels[k] for k in labels if k.startswith("CS")}
    field = ("CT28",) if g.family == "FRLG" else ("CT28", "CT43")
    keep = {k for k in labels if k.startswith("CS") or (opts["keepFieldTMs"] and k in field)}
    banned = {R.STRUGGLE} | hm_moves | (R.GAME_BREAKING_MOVES if opts["noGameBreaking"] else set())
    used = {labels[k] for k in keep}
    pool = [m for m in range(1, MAX_MOVE + 1) if m not in banned and m not in used]
    moves = {m: g.move(m) for m in pool}
    good = [m for m in pool if moves[m]["cat"] != 0 and moves[m]["power"] >= 70]
    pct = max(0, min(100, int(opts["goodDamaging"] or 0)))
    for k in TM_ORDER3:
        if k in keep:
            continue
        src = good if pct and rng.random() * 100 < pct else pool
        src = [m for m in src if m not in used] or [m for m in pool if m not in used]
        labels[k] = rng.choice(src)
        used.add(labels[k])
    data = struct.pack("<58H", *[labels[k] for k in TM_ORDER3])
    for o in g.tmlists:
        g.rom[o:o + 116] = data
    log.append("Attaques des CT : aléatoires (CS gardées" + (", Tunnel" + ("" if g.family == "FRLG" else "/Force Cachée")
                                                            + " gardées" if opts["keepFieldTMs"] else "") + ")")
    return labels


_map_cache = {}


def _light(rom):
    g = Gen3Rom.__new__(Gen3Rom)
    g.rom = rom
    natdex = _one(rom, b"".join(struct.pack("<H", i) for i in range(1, 252)), "Pokédex national")
    g.nat_of = {}
    for i in range(1, 412):
        n = struct.unpack_from("<H", rom, natdex + 2 * (i - 1))[0]
        if 1 <= n <= MAX_SPECIES:
            g.nat_of[i] = n
    return g


def wild_for_map(path, group, num, rates):
    key = (path, os.path.getmtime(path))
    if key not in _map_cache:
        with open(path, "rb") as f:
            g = _light(f.read())
        by_map = {}
        for p in g.wild_headers():
            by_map.setdefault((g.rom[p], g.rom[p + 1]), struct.unpack_from("<4I", g.rom, p + 4))
        _map_cache.clear()
        _map_cache[key] = (g, by_map)
    g, by_map = _map_cache[key]
    ptrs = by_map.get((group, num))
    if ptrs is None:
        return None
    land_r, water_r, rock_r, fish_r, fish_groups = rates

    def mons(ptr, n, rs):
        q = struct.unpack_from("<I", g.rom, ptr - GBA + 4)[0] - GBA
        out = []
        for i in range(n):
            lo, hi, sp = struct.unpack_from("<BBH", g.rom, q + 4 * i)
            if g.nat_of.get(sp):
                out.append({"species": g.nat_of[sp], "minLevel": lo, "maxLevel": hi, "rate": rs[i]})
        return out
    out = {}
    if ptrs[0]:
        out["land"] = mons(ptrs[0], 12, land_r)
    if ptrs[1]:
        out["water"] = mons(ptrs[1], 5, water_r)
    if ptrs[2]:
        out["rockSmash"] = mons(ptrs[2], 5, rock_r)
    if ptrs[3]:
        fish = mons(ptrs[3], 10, fish_r)
        for rod, (lo, hi) in fish_groups.items():
            out[{"old_rod": "oldRod", "good_rod": "goodRod", "super_rod": "superRod"}[rod]] = fish[lo:hi]
    return out or None


RUN_SIG3 = {"E": bytes.fromhex("817e04200840002806d0"), "FRLG": bytes.fromhex("417e02200840002806d0"),
            "RS": bytes.fromhex("0248c07d082803d10120" + "02e0")}
TEXT_SIG3 = bytes.fromhex("080401000002")


def apply_tweaks(g, opts, log):
    r = bytes(g.rom)
    if opts["runIndoors"]:
        sig = RUN_SIG3[g.family]
        hits = _find_all(r, sig)
        if len(hits) == 1:
            g.rom[hits[0] + 4] = 0x00
            log.append("Course (chaussures) autorisée partout, même à l'intérieur (phase expérimentale)")
        else:
            log.append(f"Course en intérieur : NON appliquée (code introuvable : {len(hits)} résultats)")
    if opts.get("startShoes"):
        if g.family != "FRLG":
            log.append("Chaussures de course : déjà disponibles dès le début dans ce jeu (rien à changer)")
        else:
            pool = struct.pack("<I", 0x82F)
            sites = []
            p = r.find(pool)
            while p >= 0:
                if p % 4 == 0:
                    for a in range(max(0, p - 0x200), p, 2):
                        h = struct.unpack_from("<H", r, a)[0]
                        if h >> 11 == 9 and ((a + 4) & ~3) + (h & 0xFF) * 4 == p:
                            b = a + 2
                            if ((struct.unpack_from("<H", r, b)[0] & 0xF800) == 0xF000
                                    and (struct.unpack_from("<H", r, b + 2)[0] & 0xF800) in (0xF800, 0xE800)
                                    and r[b + 4:b + 8] == bytes.fromhex("00060028")
                                    and r[b + 9] == 0xD0):
                                sites.append(b + 8)
                p = r.find(pool, p + 1)
            if len(sites) == 1:
                g.rom[sites[0]:sites[0] + 2] = THUMB_NOP
                log.append("Chaussures de course disponibles dès le début (phase expérimentale)")
            else:
                log.append(f"Chaussures dès le début : NON appliquées (code introuvable : {len(sites)} résultats)")
    if opts["fastText"]:
        hits = _find_all(r, TEXT_SIG3) if g.family != "RS" else []
        if len(hits) == 1:
            g.rom[hits[0]:hits[0] + 3] = bytes([4, 1, 0])
            log.append("Texte : vitesse « rapide » instantanée, « moyen » et « lent » accélérés (phase expérimentale)")
        else:
            log.append("Texte rapide : NON appliqué ("
                       + ("pas disponible pour Rubis / Saphir" if g.family == "RS" else f"table introuvable : {len(hits)} résultats") + ")")
