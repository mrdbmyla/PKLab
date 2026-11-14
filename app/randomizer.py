import io
import json
import os
import random
import struct

import numpy as np

import gen4_maps
import i18n
import gen5_maps
import nds_gfx
import nds_rebuild
import randomizer_gen3 as R3
import shiny_patch
import randomizer_gen4 as R4

MAX_SPECIES = 649
MAX_MOVE = 559
MAX_ABILITY = 164
NUM_TYPES = 17
WATER = 10
STRUGGLE = 165
WONDER_GUARD = 25
LEGENDARIES = {144, 145, 146, 150, 151, 243, 244, 245, 249, 250, 251, *range(377, 387),
               *range(480, 495), *range(638, 650)}
SEASON_SIZE = 232
SLOT_GROUPS = [(8, 12, False), (56, 12, False), (104, 12, False), (152, 5, True), (172, 5, True),
               (192, 5, True), (212, 5, True)]
STARTERS = (495, 498, 501)
TYPE_FR = ["Normal", "Combat", "Vol", "Poison", "Sol", "Roche", "Insecte", "Spectre", "Acier", "Feu", "Eau",
           "Plante", "Électrik", "Psy", "Glace", "Dragon", "Ténèbres"]
IMPORTANT_CLASSES = {"Champion", "Conseil 4", "Maître", "Gym Leader", "Elite Four", "Leader", "Arena Leader"}

PATHS = {
    "BW": {"personal": "a/0/1/6", "learn": "a/0/1/8", "evo": "a/0/1/9", "moves": "a/0/2/1",
           "trdata": "a/0/9/2", "trpoke": "a/0/9/3", "classes": 191, "scripts": "a/0/5/7",
           "starter_files": (12, 76, 112, 304, 634, 782),
           "trainer_names": 190, "species_names": 70, "story_text": "a/0/0/3", "starter_text": 30,
           "trades": "a/1/6/5", "static_op": 0x0178, "item_script": 864, "monkey_script": 304, "starter_overlay": 223,
           "starter_gfx": "a/2/0/5"},
    "B2W2": {"personal": "a/0/1/6", "learn": "a/0/1/8", "evo": "a/0/1/9", "moves": "a/0/2/1",
             "trdata": "a/0/9/1", "trpoke": "a/0/9/2", "classes": 383, "scripts": "a/0/5/6",
             "starter_files": (794, 808, 854, 878),
             "trainer_names": 382, "species_names": 90, "story_text": "a/0/0/3", "starter_text": 53,
             "trades": "a/1/6/3", "static_op": 0x0174, "item_script": 1240, "starter_overlay": 316,
             "starter_gfx": "a/2/0/2"},
}
GAME_FAMILY = {"POKEMON B": "BW", "POKEMON W": "BW", "POKEMON B2": "B2W2", "POKEMON W2": "B2W2"}

DEFAULTS = {
    "seed": None, "noLegendaries": True,
    "wild": "zone", "wildSimilar": True, "wildTheme": False, "wildWater": True, "wildLevels": 0,
    "catchEmAll": False, "wildHeldItems": False, "minCatchRate": 0,
    "trainers": "off", "trainerSimilar": True, "sameStage": True, "evolveByLevel": False, "trainerLevels": 0, "bossTheme": True,
    "fullyEvolvedAt": 0, "betterMovesets": False, "rivalStarter": True,
    "types": "off", "dualTypes": False, "abilities": "off", "banWonderGuard": True, "twoAbilities": False,
    "banTrapping": False, "banNegative": True, "banUseless": False, "stats": "off", "expCurve": "off",
    "learnsets": "off", "noGameBreaking": True, "goodDamaging": 0, "reorderDamaging": False, "tms": "off",
    "tutorMoves": "off", "tutorCompat": "off", "tutorSanity": False,
    "evolutions": "off", "evoSimilar": True, "evoSameType": False, "fullHM": False, "tmSanity": False, "e4Unique": False, "evoImpossible": False, "evoEasier": False, "evoNoTime": False,
    "movePower": False, "moveTypes": False, "moveAccuracy": False, "movePP": False, "moveCategory": False,
    "starters": "off", "starterList": [], "starter3stage": True, "starterTypes": True, "starterText": True,
    "extraBoss": 0, "extraImportant": 0, "extraRegular": 0,
    "itemsBoss": False, "itemsImportant": False, "itemsRegular": False, "itemsConsumable": False,
    "itemsHighestOnly": False, "doubleBattles": False, "shuffleTrainerNames": False, "shuffleClassNames": False,
    "tmMoves": "off", "keepFieldTMs": True, "trades": "off", "statics": "off",
    "gifts": "off", "giftSimilar": True, "fieldItems": "off", "fossils": "off", "fossilSimilar": False, "eggs": "off",
    "shops": "off", "runIndoors": False, "startShoes": False, "fastText": False,
}
ALWAYS_BANNED_ABILITIES = {121, 161, 59, 122}
TRAPPING_ABILITIES = {23, 42, 71}
NEGATIVE_ABILITIES = {54, 100, 103, 112, 129}
USELESS_ABILITIES = {50, 35, 53, 118, 107, 108, 119, 57, 58, 132, 140}
METRONOME = 118
GAME_BREAKING_MOVES = {49, 82, 12, 32, 90, 329, 147}
HELD_ITEMS = ([*range(149, 164), *range(184, 208), 209, 210, 213, 214, 217, 219, 220, 221, 222, 230, 232, 233, 234,
               *range(237, 252), 253, 254, 255, *range(265, 272), 275, 276, 277, *range(280, 288),
               *range(295, 316), 317, 318, 326, 327, *range(538, 565)])
EXP_CURVES = {"mediumfast": 0, "fast": 4, "mediumslow": 3, "slow": 5}


def file_span(rom, path):
    fnt_off, _, fat_off, _ = struct.unpack_from("<IIII", rom, 0x40)
    d = 0xF000
    parts = path.split("/")
    for i, part in enumerate(parts):
        sub_off, fid, _ = struct.unpack_from("<IHH", rom, fnt_off + 8 * (d & 0xFFF))
        p = fnt_off + sub_off
        found = None
        while rom[p]:
            b = rom[p]
            n = b & 0x7F
            name = bytes(rom[p + 1:p + 1 + n]).decode("latin-1")
            p += 1 + n
            if b & 0x80:
                ident = struct.unpack_from("<H", rom, p)[0]
                p += 2
            else:
                ident = fid
                fid += 1
            if name == part:
                found = ident
                break
        if found is None:
            raise KeyError(path)
        if i == len(parts) - 1:
            return struct.unpack_from("<II", rom, fat_off + 8 * found)
        d = found


def narc_spans(rom, path):
    base, _ = file_span(rom, path)
    if bytes(rom[base:base + 4]) != b"NARC":
        raise ValueError(path + " : NARC invalide")
    p = base + struct.unpack_from("<H", rom, base + 0xC)[0]
    if bytes(rom[p:p + 4]) != b"BTAF":
        raise ValueError(path + " : NARC invalide")
    btaf_size, count = struct.unpack_from("<IH", rom, p + 4)
    entries = [struct.unpack_from("<II", rom, p + 12 + 8 * i) for i in range(count)]
    p += btaf_size
    p += struct.unpack_from("<I", rom, p + 4)[0]
    if bytes(rom[p:p + 4]) != b"GMIF":
        raise ValueError(path + " : NARC invalide")
    img = p + 8
    return [(img + s, img + e) for s, e in entries]


class Gen5Rom:
    def __init__(self, rom, game_key):
        self.rom = rom
        self.key = game_key
        self.p = PATHS[GAME_FAMILY[game_key]]
        self.personal = narc_spans(rom, self.p["personal"])
        self.learn = narc_spans(rom, self.p["learn"])
        self.evo = narc_spans(rom, self.p["evo"])
        self.moves = narc_spans(rom, self.p["moves"])

    def stats(self, s):
        o = self.personal[s][0]
        return list(self.rom[o:o + 6])

    def set_stats(self, s, v):
        o = self.personal[s][0]
        self.rom[o:o + 6] = bytes(v)

    def types(self, s):
        o = self.personal[s][0]
        return self.rom[o + 6], self.rom[o + 7]

    def set_types(self, s, t1, t2):
        o = self.personal[s][0]
        self.rom[o + 6], self.rom[o + 7] = t1, t2

    def abilities(self, s):
        o = self.personal[s][0]
        return list(self.rom[o + 24:o + 27])

    def set_abilities(self, s, a):
        o = self.personal[s][0]
        self.rom[o + 24:o + 27] = bytes(a)

    tm_count, hm_count, max_item = 95, 6, 638

    def set_growth(self, s, v):
        self.rom[self.personal[s][0] + 21] = v

    def raise_catch_rate(self, s, v):
        o = self.personal[s][0] + 8
        self.rom[o] = max(self.rom[o], v)

    def set_held_items(self, s, items):
        struct.pack_into("<3H", self.rom, self.personal[s][0] + 12, *(list(items) + [0, 0, 0])[:3])

    def set_move(self, m, d):
        o = self.moves[m][0]
        self.rom[o], self.rom[o + 2], self.rom[o + 3], self.rom[o + 4], self.rom[o + 5] = (
            d["type"], d["cat"], d["power"], d["acc"], d["pp"])

    def tm_bits(self, s):
        o = self.personal[s][0]
        return int.from_bytes(self.rom[o + 40:o + 56], "little")

    def set_tm_bits(self, s, bits):
        o = self.personal[s][0]
        self.rom[o + 40:o + 56] = bits.to_bytes(16, "little")

    def bst(self, s):
        return sum(self.stats(s))

    def learnset(self, s):
        start, end = self.learn[s]
        out = []
        for o in range(start, end - 3, 4):
            mv, lv = struct.unpack_from("<HH", self.rom, o)
            if mv == 0xFFFF:
                break
            out.append([mv, lv])
        return out

    def set_learnset(self, s, entries):
        start, _ = self.learn[s]
        for i, (mv, lv) in enumerate(entries):
            struct.pack_into("<HH", self.rom, start + 4 * i, mv, lv)

    def evolutions(self, s):
        start, _ = self.evo[s]
        return [list(struct.unpack_from("<HHH", self.rom, start + 6 * i)) for i in range(7)]

    def set_evo(self, s, slot, method, param, target):
        start, _ = self.evo[s]
        struct.pack_into("<HHH", self.rom, start + 6 * slot, method, param, target)

    def clear_evolutions(self, s):
        start, end = self.evo[s]
        self.rom[start:start + 42] = bytes(42)

    def set_evo_target(self, s, slot, target):
        start, _ = self.evo[s]
        struct.pack_into("<H", self.rom, start + 6 * slot + 4, target)

    def move(self, m):
        o = self.moves[m][0]
        return {"type": self.rom[o], "cat": self.rom[o + 2], "power": self.rom[o + 3], "acc": self.rom[o + 4],
                "pp": self.rom[o + 5]}


_USAGE = {}


def _weighted_choice(rng, cands):
    w = [1.0 / (1 + _USAGE.get(s, 0)) ** 2 for s in cands]
    s = rng.choices(cands, weights=w)[0]
    _USAGE[s] = _USAGE.get(s, 0) + 1
    return s


_STAGE = {}


def _pick(rng, pool, bst, old, similar, avoid=(), stage=False):
    cands = [s for s in pool if s not in avoid] or list(pool)
    if stage and old in _STAGE:
        cands = [s for s in cands if _STAGE.get(s) == _STAGE[old]] or cands
    if not cands:
        return old
    if similar and old in bst:
        b = bst[old]
        for margin in (0.10, 0.20, 0.35, 10.0):
            near = [s for s in cands if abs(bst[s] - b) <= b * margin]
            if near:
                return _weighted_choice(rng, near)
        return _weighted_choice(rng, cands)
    return rng.choice(cands)


def _three_starters(rng, basics, types_of, distinct_types=True):
    if not distinct_types:
        return rng.sample(basics, 3)
    for _ in range(300):
        trio = rng.sample(basics, 3)
        if len({types_of(c)[0] for c in trio}) == 3:
            return trio
    return rng.sample(basics, 3)


def _family_order(g):
    pre = {}
    for s in range(1, MAX_SPECIES + 1):
        for method, _, target in g.evolutions(s):
            if method and 0 < target <= MAX_SPECIES and target not in pre:
                pre[target] = s
    order, seen = [], set()

    def visit(s):
        if s in seen:
            return
        seen.add(s)
        if s in pre:
            visit(pre[s])
        order.append(s)
    for s in range(1, MAX_SPECIES + 1):
        visit(s)
    return order, pre


def _type_list(t1, t2):
    return [t1] if t1 == t2 else [t1, t2]


LEVEL_METHODS = {4, 9, 10, 11, 12, 13, 14, 23, 24}


def _evolve_for_level(g, species, level, rng):
    for _ in range(2):
        nxt = [t for m, p, t in g.evolutions(species) if m and 0 < t <= MAX_SPECIES and t != species
               and ((m in LEVEL_METHODS and 0 < p <= level) or (m not in LEVEL_METHODS and level >= 40))]
        if not nxt:
            break
        species = rng.choice(nxt)
    return species


def _trainer_src(src, opts, important, e4set, used_all):
    if opts["e4Unique"] and not important:
        src = [x for x in src if x not in e4set] or src
    if opts["trainers"] == "even":
        src = [x for x in src if x not in used_all] or src
    return src


TUTOR_GROUPS5 = ((13, 28), (43, 60), (0, 13), (28, 43))


def _tutor_table5(g):
    if GAME_FAMILY.get(g.key) != "B2W2":
        return None
    d = nds_rebuild.overlay_read(g.rom, 36)
    o = d.find(struct.pack("<3I", 450, 2, 1))
    if o < 156 or struct.unpack_from("<I", d, o - 156)[0] != 20:
        return None
    return o - 156


def _randomize_tutors5(g, rng, opts, log, tm_labels):
    if opts["tutorMoves"] == "off" and opts["tutorCompat"] == "off" and not opts["tutorSanity"]:
        return
    start = _tutor_table5(g)
    if start is None:
        log.append("Tuteurs : aucun dans ce jeu" if GAME_FAMILY.get(g.key) == "BW" else "Tuteurs : NON modifiés (table introuvable)")
        return
    code = bytearray(nds_rebuild.overlay_read(g.rom, 36))
    moves = [struct.unpack_from("<I", code, start + 12 * i)[0] for i in range(60)]
    if opts["tutorMoves"] == "random":
        banned = {STRUGGLE} | (GAME_BREAKING_MOVES if opts["noGameBreaking"] else set()) | set((tm_labels or {}).values())
        pool = [m for m in range(1, MAX_MOVE + 1) if m not in banned]
        data = {m: g.move(m) for m in pool}
        good = [m for m in pool if data[m]["cat"] != 0 and data[m]["power"] >= 70]
        pct = max(0, min(100, int(opts["goodDamaging"] or 0)))
        used = set()
        for i in range(60):
            src = good if pct and rng.random() * 100 < pct else pool
            src = [m for m in src if m not in used] or [m for m in pool if m not in used]
            moves[i] = rng.choice(src)
            used.add(moves[i])
            struct.pack_into("<I", code, start + 12 * i, moves[i])
        old = nds_rebuild.overlay_read(g.rom, 36)
        first = next(i for i in range(len(code)) if code[i] != old[i])
        last = max(i for i in range(len(code)) if code[i] != old[i])
        nds_rebuild.code_set_bytes(g.rom, 36, first, bytes(code[first:last + 1]))
    types = {m: g.move(m)["type"] for m in moves}
    for s in range(1, MAX_SPECIES + 1):
        o = g.personal[s][0] + 60
        for w, (a, b) in enumerate(TUTOR_GROUPS5):
            n = b - a
            bits = struct.unpack_from("<I", g.rom, o + 4 * w)[0]
            if opts["tutorCompat"] == "all":
                bits = (1 << n) - 1
            elif opts["tutorCompat"] in ("random", "type"):
                count = bin(bits & ((1 << n) - 1)).count("1")
                st = set(_type_list(*g.types(s)))
                cands = list(range(n))
                wt = [4.0 if opts["tutorCompat"] == "type" and types[moves[a + i]] in st else 1.0 for i in cands]
                chosen = set()
                while len(chosen) < count and cands:
                    k = rng.choices(range(len(cands)), weights=wt)[0]
                    chosen.add(cands.pop(k))
                    wt.pop(k)
                bits = sum(1 << i for i in chosen)
            if opts["tutorSanity"]:
                for mv, _ in g.learnset(s):
                    if mv in moves[a:b]:
                        bits |= 1 << moves[a:b].index(mv)
            struct.pack_into("<I", g.rom, o + 4 * w, bits)
    log.append("Tuteurs (60) : " + ", ".join(x for x, on in (
        ("attaques aléatoires (les dialogues citent encore les anciennes)", opts["tutorMoves"] == "random"),
        ({"random": "compatibilité aléatoire (même nombre)", "type": "compatibilité aléatoire, types du Pokémon privilégiés",
          "all": "tous compatibles"}.get(opts["tutorCompat"], ""), opts["tutorCompat"] != "off"),
        ("attaques apprises par niveau compatibles", opts["tutorSanity"])) if on))


def _tm_compat_after(g, rng, opts, log, labels, base):
    if opts["tms"] != "type" and not opts["fullHM"] and not opts["tmSanity"]:
        return
    if not labels and base:
        labels = {}
        for sp in base.get("species", {}).values():
            for lab, mv in sp.get("tm", []):
                labels.setdefault(lab, mv)
    if not labels:
        log.append("Compatibilité CT : NON modifiée (liste des CT inconnue)")
        return
    n_tm = g.tm_count
    bit_of = {lab: (int(lab[2:]) - 1 if lab.startswith("CT") else n_tm + int(lab[2:]) - 1) for lab in labels}
    tm_bits = {bit_of[lab]: mv for lab, mv in labels.items() if lab.startswith("CT") and bit_of[lab] < n_tm}
    move_type = {mv: g.move(mv)["type"] for mv in set(labels.values()) if 0 < mv <= MAX_MOVE}
    by_move = {}
    for b, mv in tm_bits.items():
        by_move.setdefault(mv, b)
    hm_mask = ((1 << g.hm_count) - 1) << n_tm
    for s in range(1, MAX_SPECIES + 1):
        bits = g.tm_bits(s)
        if opts["tms"] == "type":
            types = set(_type_list(*g.types(s)))
            count = bin(bits & ((1 << n_tm) - 1)).count("1")
            cands = list(tm_bits)
            w = [4.0 if move_type.get(tm_bits[b]) in types else 1.0 for b in cands]
            chosen = set()
            while len(chosen) < count and cands:
                i = rng.choices(range(len(cands)), weights=w)[0]
                chosen.add(cands.pop(i))
                w.pop(i)
            bits = (bits & hm_mask) | sum(1 << b for b in chosen)
        if opts["fullHM"]:
            bits |= hm_mask
        if opts["tmSanity"]:
            for mv, _ in g.learnset(s):
                if mv in by_move:
                    bits |= 1 << by_move[mv]
        g.set_tm_bits(s, bits)
    log.append("Compatibilité CT : " + ", ".join(x for x, on in (
        ("aléatoire, types du Pokémon privilégiés (même nombre)", opts["tms"] == "type"),
        ("toutes les CS pour tous", opts["fullHM"]),
        ("les attaques apprises par niveau qui sont des CT sont compatibles", opts["tmSanity"])) if on))


def _randomize_moves_data(g, rng, opts, log):
    keys = ("movePower", "moveTypes", "moveAccuracy", "movePP", "moveCategory")
    if not getattr(g, "has_move_category", True):
        opts = dict(opts, moveCategory=False)
    if not any(opts[k] for k in keys):
        return
    for m in range(1, MAX_MOVE + 1):
        if m == STRUGGLE:
            continue
        d = g.move(m)
        damaging = d["cat"] != 0 and d["power"] > 1
        if opts["moveTypes"]:
            d["type"] = rng.randrange(NUM_TYPES)
        if opts["movePower"] and damaging:
            d["power"] = rng.randrange(4, 31) * 5
        if opts["moveCategory"] and damaging:
            d["cat"] = rng.choice((1, 2))
        if opts["moveAccuracy"] and 0 < d["acc"] <= 100 and d["power"] != 1:
            d["acc"] = rng.choice((100, 100, 100, 95, 90, 90, 85, 80, 75, 70, 60, 50))
        if opts["movePP"] and d["pp"]:
            d["pp"] = rng.randrange(1, 9) * 5
        g.set_move(m, d)
    done = [label for k, label in zip(keys, ("puissance", "type", "précision", "PP", "catégorie")) if opts[k]]
    log.append("Attaques : " + ", ".join(done) + " aléatoires")


def _randomize_personal(g, rng, opts, order, pre, log):
    new_types, new_abil, perms, weights = {}, {}, {}, {}
    banned = set(ALWAYS_BANNED_ABILITIES)
    if opts["banWonderGuard"]:
        banned.add(WONDER_GUARD)
    for k, group in (("banTrapping", TRAPPING_ABILITIES), ("banNegative", NEGATIVE_ABILITIES),
                     ("banUseless", USELESS_ABILITIES)):
        if opts[k]:
            banned |= group
    abil_pool = [a for a in range(1, MAX_ABILITY + 1) if a not in banned]
    curve = EXP_CURVES.get(opts["expCurve"])
    for s in order:
        parent = pre.get(s)
        if opts["types"] != "off":
            if parent in new_types and opts["types"] == "random":
                t1, t2 = new_types[parent]
                if rng.random() < 0.25:
                    t2 = rng.randrange(NUM_TYPES)
            else:
                t1 = rng.randrange(NUM_TYPES)
                t2 = rng.randrange(NUM_TYPES) if rng.random() < 0.5 else t1
            if opts["dualTypes"] and t2 == t1:
                t2 = rng.choice([t for t in range(NUM_TYPES) if t != t1])
            new_types[s] = (t1, t2)
            g.set_types(s, t1, t2)
        if opts["abilities"] != "off":
            if parent in new_abil and opts["abilities"] == "random":
                a = new_abil[parent]
            else:
                a1 = rng.choice(abil_pool)
                a2 = rng.choice([x for x in abil_pool if x != a1]) if opts["twoAbilities"] or rng.random() < 0.6 else 0
                a3 = rng.choice([x for x in abil_pool if x not in (a1, a2)])
                a = [a1, a2, a3]
            new_abil[s] = a
            g.set_abilities(s, a)
        if opts["stats"] != "off":
            st = g.stats(s)
            if opts["stats"] == "shuffle":
                perm = perms.get(parent) or rng.sample(range(6), 6)
                perms[s] = perm
                g.set_stats(s, [st[i] for i in perm])
            else:
                total = sum(st)
                w = weights.get(parent) if opts["stats"] == "random" and parent in weights else \
                    [rng.random() + 0.2 for _ in range(6)]
                weights[s] = w
                vals = [max(10, min(255, round(total * x / sum(w)))) for x in w]
                vals[rng.randrange(6)] += total - sum(vals)
                g.set_stats(s, [max(1, min(255, v)) for v in vals])
            if st[0] == 1:
                new = g.stats(s)
                if opts["stats"] == "shuffle":
                    rest = st[1:]
                    rng.shuffle(rest)
                    g.set_stats(s, [1] + rest)
                elif new[0] != 1:
                    extra = new[0] - 1
                    g.set_stats(s, [1] + [min(255, v + extra // 5 + (1 if i < extra % 5 else 0))
                                          for i, v in enumerate(new[1:])])
        if opts["tms"] not in ("off", "type"):
            bits = g.tm_bits(s)
            n_tm = g.tm_count
            hms = bits & (((1 << g.hm_count) - 1) << n_tm)
            if opts["tms"] == "all":
                tms = (1 << n_tm) - 1
            else:
                count = bin(bits & ((1 << n_tm) - 1)).count("1")
                tms = sum(1 << i for i in rng.sample(range(n_tm), count))
            g.set_tm_bits(s, tms | hms)
        if curve is not None:
            g.set_growth(s, curve)
        if opts["minCatchRate"]:
            g.raise_catch_rate(s, min(255, int(opts["minCatchRate"])))
        if opts["wildHeldItems"]:
            held = g.held_item_pool() if hasattr(g, "held_item_pool") else [i for i in HELD_ITEMS if i <= g.max_item]
            g.set_held_items(s, [rng.choice(held) if rng.random() < 0.3 else 0,
                                 rng.choice(held) if rng.random() < 0.3 else 0, 0])
    if opts["types"] != "off":
        log.append("Types : aléatoires (" + ("évolutions cohérentes" if opts["types"] == "random" else "chaque espèce à part") + ")" + (", toujours deux types" if opts["dualTypes"] else ""))
    if opts["abilities"] != "off":
        log.append(f"Talents : aléatoires (évolutions cohérentes), {MAX_ABILITY - len(banned)} talents possibles"
                   + (", toujours deux talents" if opts["twoAbilities"] else ""))
    if opts["tms"] not in ("off", "type"):
        log.append("Compatibilité CT : " + ("toutes les CT" if opts["tms"] == "all" else "aléatoire (même nombre)"))
    if opts["stats"] != "off":
        log.append("Stats de base : " + {"shuffle": "mélangées", "random": "aléatoires (même total, même répartition dans la famille)"}
                   .get(opts["stats"], "aléatoires (même total, chacun la sienne)") + ", Munja garde 1 PV")
    if curve is not None:
        log.append("Courbe d'expérience : la même pour tous (" + opts["expCurve"] + ")")
    if opts["minCatchRate"]:
        log.append(f"Taux de capture minimum : {opts['minCatchRate']}")
    if opts["wildHeldItems"]:
        log.append("Objets tenus par les Pokémon sauvages : aléatoires (objets utiles en combat)")


def _randomize_evolutions(g, rng, opts, bst, pool, log, names):
    changes = []
    if opts["evolutions"] == "everyLevel":
        for s in range(1, MAX_SPECIES + 1):
            new = rng.choice([x for x in pool if x != s])
            g.clear_evolutions(s)
            g.set_evo(s, 0, 4, 1, new)
            changes.append((s, 0, new))
        log.append("Évolutions : à chaque niveau, vers une espèce au hasard")
        return changes
    if opts["evolutions"] == "random":
        types_of = {s: set(_type_list(*g.types(s))) for s in range(1, MAX_SPECIES + 1)}
        kids = {s: {t for m, _, t in g.evolutions(s) if m and 0 < t <= MAX_SPECIES} for s in range(1, MAX_SPECIES + 1)}
        parents = {s: set() for s in range(1, MAX_SPECIES + 1)}
        for s, ts in kids.items():
            for t in ts:
                parents[t].add(s)

        def above(x, seen=()):
            return max((1 + above(p, seen + (x,)) for p in parents[x] if p not in seen), default=0)

        def below(x, seen=()):
            return max((1 + below(k, seen + (x,)) for k in kids[x] if k not in seen), default=0)

        def reaches(a, b):
            todo, seen = [a], set()
            while todo:
                x = todo.pop()
                if x == b:
                    return True
                if x not in seen:
                    seen.add(x)
                    todo.extend(kids[x])
            return False
        depth = {x: below(x) for x in range(1, MAX_SPECIES + 1)}
        for s in range(1, MAX_SPECIES + 1):
            for slot, (method, _, target) in enumerate(g.evolutions(s)):
                if not method or not (0 < target <= MAX_SPECIES):
                    continue
                up = above(s)
                ok = [x for x in pool if x != s and x != target and x not in kids[s] and up + 1 + depth[x] <= 2
                      and not reaches(x, s)]
                cands = [x for x in ok if bst[x] >= bst[s] * 0.95] if opts["evoSimilar"] else list(ok)
                if opts["evoSameType"]:
                    cands = [x for x in cands if types_of[x] & types_of[s]] or cands
                new = _pick(rng, cands or ok or pool, bst, target, opts["evoSimilar"])
                g.set_evo_target(s, slot, new)
                kids[s].discard(target)
                parents[target].discard(s)
                kids[s].add(new)
                parents[new].add(s)
                for x in {s} | set(parents[s]) | {a for a in range(1, MAX_SPECIES + 1) if reaches(a, s)}:
                    depth[x] = below(x)
                changes.append((s, target, new))
        log.append(f"Évolutions : {len(changes)} évolutions vers des espèces aléatoires ("
                   + ("au moins aussi fortes, " if opts["evoSimilar"] else "") + "3 stades maximum"
                   + (", partageant un type" if opts["evoSameType"] else "") + ")")
    fixed = 0
    for s in range(1, MAX_SPECIES + 1):
        for slot, (method, param, target) in enumerate(g.evolutions(s)):
            new_m, new_p = method, param
            if opts["evoImpossible"] and method in (5, 7, 16):
                new_m, new_p = 4, 37
            elif opts["evoImpossible"] and method == 6:
                new_m = 8
            if opts["evoNoTime"]:
                if new_m in (2, 3):
                    new_m = 1
                elif new_m in (19, 20):
                    new_m = 8
            if opts["evoEasier"] and new_m in (4, 9, 10, 11, 12, 13, 14, 15, 23, 24) and new_p > 40:
                new_p = 40
            if (new_m, new_p) != (method, param):
                g.set_evo(s, slot, new_m, new_p, target)
                fixed += 1
    if fixed:
        what = [t for k, t in (("evoImpossible", "échanges/beauté remplacés (Nv. 37 ou objet)"),
                               ("evoNoTime", "sans condition d'heure"), ("evoEasier", "niveaux plafonnés à 40")) if opts[k]]
        log.append(f"Évolutions plus simples : {fixed} méthodes changées (" + ", ".join(what) + ")")
    return changes


def _randomize_learnsets(g, rng, opts, log):
    moves = {m: g.move(m) for m in range(1, MAX_MOVE + 1) if m != STRUGGLE}
    if opts["noGameBreaking"]:
        moves = {m: d for m, d in moves.items() if m not in GAME_BREAKING_MOVES}
    if opts["learnsets"] == "metronome":
        for s in range(1, MAX_SPECIES + 1):
            g.set_learnset(s, [[METRONOME, lv] for _, lv in g.learnset(s)])
        log.append("Attaques par niveau : mode Métronome seulement")
        return
    damaging = [m for m, d in moves.items() if d["cat"] != 0 and d["power"] > 1]
    good = [m for m in damaging if moves[m]["power"] >= 70 and (moves[m]["acc"] >= 85 or moves[m]["acc"] > 100)]
    all_moves = list(moves)
    pct = max(0, min(100, int(opts["goodDamaging"] or 0)))
    for s in range(1, MAX_SPECIES + 1):
        entries = g.learnset(s)
        if not entries:
            continue
        if opts["learnsets"] != "off":
            types = set(_type_list(*g.types(s)))
            same = opts["learnsets"] == "type"
            used, new = set(), []
            for i, (_, lv) in enumerate(entries):
                if i == 0:
                    src = ([m for m in damaging if moves[m]["type"] in types] if same else damaging) or damaging
                elif pct and rng.random() * 100 < pct:
                    src = ([m for m in good if moves[m]["type"] in types] if same and rng.random() < 0.5 else good) or good
                elif same and rng.random() < 0.5:
                    src = [m for m in all_moves if moves[m]["type"] in types] or all_moves
                else:
                    src = all_moves
                cands = [m for m in src if m not in used] or src
                m = rng.choice(cands)
                used.add(m)
                new.append([m, lv])
            entries = new
        if opts["reorderDamaging"]:
            pos = [i for i, (m, _) in enumerate(entries) if m in damaging]
            ordered = sorted((entries[i][0] for i in pos), key=lambda m: moves[m]["power"])
            for i, m in zip(pos, ordered):
                entries[i][0] = m
        g.set_learnset(s, entries)
    if opts["learnsets"] != "off":
        log.append("Attaques par niveau : aléatoires" + (" (types du Pokémon privilégiés)" if opts["learnsets"] == "type" else "")
                   + ", 1re attaque toujours offensive" + (f", {pct} % d'attaques offensives fortes" if pct else "")
                   + (", sans attaques qui cassent le jeu" if opts["noGameBreaking"] else ""))
    if opts["reorderDamaging"]:
        log.append("Attaques offensives rangées de la plus faible à la plus forte")


def _moves_at_level(g, species, level):
    seen = []
    for mv, lv in g.learnset(species):
        if lv <= level and mv not in seen:
            seen.append(mv)
    out = seen[-4:]
    return out + [0] * (4 - len(out))


def _best_moves(g, species, level):
    known = []
    for mv, lv in g.learnset(species):
        if lv <= level and mv not in known:
            known.append(mv)
    types = set(_type_list(*g.types(species)))
    data = {m: g.move(m) for m in known}

    def score(m):
        d = data[m]
        acc = d["acc"] if 0 < d["acc"] <= 100 else 100
        return d["power"] * (1.5 if d["type"] in types else 1) * acc / 100
    attacks = sorted((m for m in known if data[m]["cat"] != 0 and data[m]["power"] > 1), key=score, reverse=True)
    out, seen_types = [], set()
    for m in attacks:
        if data[m]["type"] not in seen_types and len(out) < 3:
            out.append(m)
            seen_types.add(data[m]["type"])
    status = [m for m in reversed(known) if data[m]["cat"] == 0]
    if status:
        out.append(status[0])
    for m in attacks:
        if len(out) >= 4:
            break
        if m not in out:
            out.append(m)
    out = out[:4]
    return out + [0] * (4 - len(out)) if out else _moves_at_level(g, species, level)


def _starter_sites(g):
    try:
        spans = narc_spans(g.rom, g.p["scripts"])
    except Exception:
        return []
    sites = []
    for fi in g.p["starter_files"]:
        if fi >= len(spans):
            continue
        s, e = spans[fi]
        f = g.rom[s:e]
        for o in range(4, len(f) - 1):
            v = struct.unpack_from("<H", f, o)[0]
            if v not in STARTERS:
                continue
            setvar = f[o - 4] == 0x28 and f[o - 3] == 0 and f[o - 1] == 0x80
            cmd57 = f[o - 3] == 0x57 and f[o - 2] == 0
            push = f[o - 2] == 0x08 and f[o - 1] == 0
            if setvar or cmd57 or push:
                sites.append((s + o, v))
    return sites


def _starter_images(g, chosen, sprite_dir):
    try:
        from PIL import Image
    except Exception:
        return "images NON changées (Pillow absent)"
    if not sprite_dir:
        return "images NON changées (dossier des sprites inconnu)"
    s, e = file_span(g.rom, g.p["starter_gfx"])
    members, btnf = nds_rebuild.narc_unpack(bytes(g.rom[s:e]))
    if len(members) < 26 or members[12][:4] != b"RGCN" or members[21][:4] != b"RECN":
        return "images NON changées (archive non reconnue)"
    cell = nds_gfx.cells(members[21])[0]
    done = 0
    for i, sp in enumerate(chosen):
        path = os.path.join(sprite_dir, f"{sp}.png")
        if not os.path.isfile(path):
            continue
        im = Image.open(path).convert("RGBA")
        if im.size != (96, 96):
            im = im.resize((96, 96), Image.NEAREST)
        rgba = np.array(im)
        opaque = rgba[:, :, 3] >= 128
        rgb = Image.fromarray(rgba[:, :, :3]).quantize(15, method=Image.MEDIANCUT, dither=Image.NONE) \
            if len({tuple(c) for c in rgba[opaque][:, :3]}) > 15 else None
        if rgb is not None:
            q = np.array(rgb)
            pal_rgb = np.array(rgb.getpalette()[:45], np.int32).reshape(15, 3)
            idx = np.where(opaque, q + 1, 0)
        else:
            colors = sorted({tuple(c) for c in rgba[opaque][:, :3]})
            lut = {c: k + 1 for k, c in enumerate(colors)}
            idx = np.zeros((96, 96), np.uint8)
            for y, x in zip(*np.nonzero(opaque)):
                idx[y, x] = lut[tuple(rgba[y, x, :3])]
            pal_rgb = np.array(colors + [(0, 0, 0)] * (15 - len(colors)), np.int32)
        bgr = [int((r >> 3) | ((g_ >> 3) << 5) | ((b >> 3) << 10)) for r, g_, b in pal_rgb[:15]]
        normal_i, dark_i = 2 * i, 2 * i + 1
        old_n = nds_gfx.palette(members[normal_i], 16)
        old_d = nds_gfx.palette(members[dark_i], 16)
        num = sum(int(c) & 31 for c in old_d[1:]) + sum(int(c) >> 5 & 31 for c in old_d[1:]) + sum(int(c) >> 10 & 31 for c in old_d[1:])
        den = sum(int(c) & 31 for c in old_n[1:]) + sum(int(c) >> 5 & 31 for c in old_n[1:]) + sum(int(c) >> 10 & 31 for c in old_n[1:])
        k = num / den if den else 0.15
        dark = [int(round((c & 31) * k)) | int(round((c >> 5 & 31) * k)) << 5 | int(round((c >> 10 & 31) * k)) << 10 for c in bgr]
        members[normal_i] = nds_gfx.set_palette(members[normal_i], [int(old_n[0])] + bgr)
        members[dark_i] = nds_gfx.set_palette(members[dark_i], [int(old_d[0])] + dark)
        tiles = nds_gfx.tiles4(members[12 + i])
        members[12 + i] = nds_gfx.set_tiles4(members[12 + i], nds_gfx.paint_cell(tiles, cell, idx.astype(np.uint8)))
        done += 1
    nds_rebuild.replace_file(g.rom, g.p["starter_gfx"], nds_rebuild.narc_pack(members, btnf))
    return f"{done} images redessinées"


def _randomize_starters(g, rng, opts, pool, pre, log, names, sprite_dir=None):
    if opts["starters"] == "off":
        return None
    sites = _starter_sites(g)
    if not {v for _, v in sites} >= set(STARTERS):
        log.append("Starters : NON modifiés (scripts de ce jeu non reconnus)")
        return None
    if opts["starters"] == "custom":
        chosen = [int(x) for x in opts["starterList"][:3] if str(x).strip()]
        if len(chosen) != 3 or any(not (1 <= c <= MAX_SPECIES) for c in chosen):
            raise ValueError("Starters choisis : il faut 3 Pokémon")
    else:
        evolves = {}
        for s in range(1, MAX_SPECIES + 1):
            evolves[s] = [t for m, _, t in g.evolutions(s) if m and 0 < t <= MAX_SPECIES]
        basics = [s for s in pool if s not in pre and evolves[s] and s not in STARTERS]
        if opts["starter3stage"]:
            three = [s for s in basics if any(evolves[t] for t in evolves[s])]
            basics = three or basics
        if opts["starters"] == "randomAny":
            basics = [s for s in pool if s not in STARTERS]
        chosen = _three_starters(rng, basics, g.types, opts["starterTypes"])
    mapping = dict(zip(STARTERS, chosen))
    for off, v in sites:
        struct.pack_into("<H", g.rom, off, mapping[v])
    table = struct.pack("<3H", *STARTERS)
    ov = nds_rebuild.overlay_read(g.rom, g.p["starter_overlay"])
    at = ov.find(table)
    if at >= 0 and ov.find(table, at + 1) < 0:
        new_ov = bytearray(ov)
        struct.pack_into("<3H", new_ov, at, *chosen)
        screen = "écran de choix mis à jour"
        if not nds_rebuild.overlay_patch_in_place(g.rom, g.p["starter_overlay"], at, struct.pack("<3H", *chosen)):
            nds_rebuild.overlay_write_compressed(g.rom, g.p["starter_overlay"], bytes(new_ov))
            screen += " (recompressé)"
        screen += ", " + _starter_images(g, chosen, sprite_dir)
    else:
        screen = "écran de choix NON trouvé"
    log.append("Starters : " + ", ".join(f"{names(o)} -> {names(n)}" for o, n in mapping.items())
               + f" ({len(sites)} emplacements de script, {screen})")
    return mapping


def _evolution_line(g, first, rng=None):
    line = [first]
    while len(line) < 3:
        nxt = [t for m, _, t in g.evolutions(line[-1]) if m and 0 < t <= MAX_SPECIES and t not in line]
        if not nxt:
            break
        line.append(nxt[0])
    return line


def _randomize_wild(g, rng, opts, pool, bst, log, places, names):
    if opts["wild"] == "off" and not opts["wildLevels"]:
        return
    mode = opts["wild"]
    types_of = {s: set(_type_list(*g.types(s))) for s in pool}
    water_pool = [s for s in pool if WATER in types_of[s]]
    global_map = {}
    by_table = {}
    seen_all = set()
    slots = 0
    for table, (s, e) in enumerate(narc_spans(g.rom, gen5_maps.GAMES[g.key]["narcs"]["enc"])):
        if (e - s) % SEASON_SIZE:
            continue
        zone_map = {}
        theme = rng.randrange(NUM_TYPES) if opts["wildTheme"] else None
        for season in range((e - s) // SEASON_SIZE):
            blk = s + season * SEASON_SIZE
            for off, n, water in SLOT_GROUPS:
                src = pool
                if theme is not None:
                    src = [x for x in pool if theme in types_of[x]] or pool
                if water and opts["wildWater"]:
                    src = [x for x in src if x in water_pool] or water_pool or src
                for i in range(n):
                    p = blk + off + 4 * i
                    old = struct.unpack_from("<H", g.rom, p)[0] & 0x7FF
                    if not old or not g.rom[p + 2] or old > MAX_SPECIES:
                        continue
                    new = old
                    if mode != "off":
                        cands = src
                        if opts["catchEmAll"]:
                            cands = [x for x in src if x not in seen_all] or src
                        key = (old, water)
                        if mode == "global":
                            if key not in global_map:
                                global_map[key] = _pick(rng, cands, bst, old, opts["wildSimilar"], set(global_map.values()),
                                                        opts["sameStage"])
                            new = global_map[key]
                        elif mode == "zone":
                            if key not in zone_map:
                                zone_map[key] = _pick(rng, cands, bst, old, opts["wildSimilar"], set(zone_map.values()),
                                                      opts["sameStage"])
                            new = zone_map[key]
                        else:
                            new = _pick(rng, cands, bst, old, opts["wildSimilar"], (), opts["sameStage"])
                        seen_all.add(new)
                        struct.pack_into("<H", g.rom, p, new)
                    if opts["wildLevels"]:
                        for k in (2, 3):
                            g.rom[p + k] = max(1, min(100, round(g.rom[p + k] * (1 + opts["wildLevels"] / 100))))
                    by_table.setdefault(table, {})[(old, new)] = True
                    slots += 1
    log.append(f"Pokémon sauvages : mode {mode}, {slots} emplacements"
               + (", force similaire" if opts["wildSimilar"] and mode != "off" else "")
               + (", un type par zone" if opts["wildTheme"] else "")
               + (", Eau en surf/pêche" if opts["wildWater"] else "")
               + (f", attrapez-les tous ({len(seen_all)} espèces différentes)" if opts["catchEmAll"] else "")
               + (f", niveaux {opts['wildLevels']:+d} %" if opts["wildLevels"] else ""))
    lines = []
    for table in sorted(by_table):
        lines.append(f"  Table {table} ({', '.join(places.get(table, [])) or 'lieu inconnu'})")
        for old, new in sorted(by_table[table]):
            if old != new:
                lines.append(f"    {names(old)} -> {names(new)}")
    return lines


def _class_names(g):
    try:
        text = gen4_maps._narc_files(gen4_maps._rom_file(g.rom, gen5_maps.GAMES[g.key]["narcs"]["text"]))
        return gen5_maps._decode_text_bank(text[g.p["classes"]])
    except Exception:
        return []


def _randomize_trainers(g, rng, opts, pool, bst, log, names, starters):
    touch = (opts["trainers"] != "off" or opts["trainerLevels"] or opts["fullyEvolvedAt"] or opts["betterMovesets"]
             or opts["learnsets"] == "metronome")
    if not touch:
        return []
    classes = _class_names(g)
    td = narc_spans(g.rom, g.p["trdata"])
    tp = narc_spans(g.rom, g.p["trpoke"])
    pool = [x for x in pool if 25 not in g.abilities(x)[:2]] or pool
    types_of = {s: set(_type_list(*g.types(s))) for s in pool}
    starter_line = {}
    if opts["rivalStarter"]:
        for i, first in enumerate(STARTERS):
            new_line = _evolution_line(g, starters[first]) if starters else [first, first + 1, first + 2]
            for stage in range(3):
                starter_line[first + stage] = new_line[min(stage, len(new_line) - 1)]
    lines, count, rival = [], 0, 0
    order = list(range(1, min(len(td), len(tp))))
    if opts["e4Unique"]:
        order.sort(key=lambda t: not (td[t][1] - td[t][0] >= 4 and (classes[g.rom[td[t][0] + 1]] if g.rom[td[t][0] + 1] < len(classes)
                                                                    else "") in IMPORTANT_CLASSES))
    e4set, used_all = set(), set()
    for t in order:
        ds, de = td[t]
        if de - ds < 4:
            continue
        flags, cls, n = g.rom[ds], g.rom[ds + 1], g.rom[ds + 3]
        size = 8 + (2 if flags & 2 else 0) + (8 if flags & 1 else 0)
        ps, pe = tp[t]
        if n == 0 or pe - ps < n * size:
            continue
        cname = classes[cls] if cls < len(classes) else f"classe {cls}"
        important = cname in IMPORTANT_CLASSES
        src = pool
        theme = None
        if opts["trainers"] == "theme" or (opts["bossTheme"] and important and opts["trainers"] != "off"):
            theme = rng.randrange(NUM_TYPES)
            src = [x for x in pool if theme in types_of[x]] or pool
        src = _trainer_src(src, opts, important, e4set, used_all)
        team = []
        used = set()
        for k in range(n):
            o = ps + k * size
            lv = g.rom[o + 2]
            old = struct.unpack_from("<H", g.rom, o + 4)[0]
            new = old
            if old in starter_line:
                new = starter_line[old]
                rival += 1
            elif opts["trainers"] != "off" and 0 < old <= MAX_SPECIES:
                new = _pick(rng, src, bst, old, opts["trainerSimilar"], used, opts["sameStage"])
            if opts["trainerLevels"]:
                lv = max(1, min(100, round(lv * (1 + opts["trainerLevels"] / 100))))
                g.rom[o + 2] = lv
            if opts["evolveByLevel"] and 0 < new <= MAX_SPECIES and old not in starter_line:
                new = _evolve_for_level(g, new, lv, rng)
            if opts["fullyEvolvedAt"] and lv >= opts["fullyEvolvedAt"] and 0 < new <= MAX_SPECIES \
                    and old not in starter_line:
                for _ in range(3):
                    nxt = [x for m, _, x in g.evolutions(new) if m and 0 < x <= MAX_SPECIES and x != new]
                    if not nxt:
                        break
                    new = rng.choice(nxt)
            used.add(new)
            used_all.add(new)
            if important:
                e4set.add(new)
            if new != old:
                struct.pack_into("<HH", g.rom, o + 4, new, 0)
            if flags & 1:
                mo = o + 8 + (2 if flags & 2 else 0)
                if opts["learnsets"] == "metronome":
                    struct.pack_into("<4H", g.rom, mo, METRONOME, 0, 0, 0)
                elif opts["betterMovesets"]:
                    struct.pack_into("<4H", g.rom, mo, *_best_moves(g, new, lv))
                elif new != old or opts["learnsets"] != "off":
                    struct.pack_into("<4H", g.rom, mo, *_moves_at_level(g, new, lv))
            team.append(f"{names(old)}→{names(new)} Nv{lv}" if new != old else f"{names(new)} Nv{lv}")
        count += 1
        if important:
            lines.append(f"  #{t} {cname}{' (type ' + TYPE_FR[theme] + ')' if theme is not None else ''} : " + ", ".join(team))
    log.append(f"Dresseurs : {opts['trainers']}, {count} dresseurs"
               + (", force similaire" if opts["trainerSimilar"] and opts["trainers"] != "off" else "")
               + (", Champions / Conseil 4 / Maître : un type chacun" if opts["bossTheme"] and opts["trainers"] != "off" else "")
               + (f", niveaux {opts['trainerLevels']:+d} %" if opts["trainerLevels"] else "")
               + (f", complètement évolués dès le Nv. {opts['fullyEvolvedAt']}" if opts["fullyEvolvedAt"] else "")
               + (", meilleures attaques (dresseurs à attaques choisies)" if opts["betterMovesets"] else "")
               + (f", le rival garde la lignée du starter ({rival} Pokémon)" if opts["rivalStarter"] else ""))
    return lines


BERRIES = [*range(149, 164), *range(184, 208), 209, 210]


def _trainer_categories(g):
    classes = _class_names(g)
    td = narc_spans(g.rom, g.p["trdata"])
    tp = narc_spans(g.rom, g.p["trpoke"])
    out = {}
    for t in range(1, min(len(td), len(tp))):
        ds, de = td[t]
        if de - ds < 4:
            continue
        flags, cls, n = g.rom[ds], g.rom[ds + 1], g.rom[ds + 3]
        size = 8 + (2 if flags & 2 else 0) + (8 if flags & 1 else 0)
        ps, pe = tp[t]
        species = [struct.unpack_from("<H", g.rom, ps + k * size + 4)[0] for k in range(n) if ps + (k + 1) * size <= pe]
        cname = classes[cls] if cls < len(classes) else ""
        if cname in IMPORTANT_CLASSES:
            out[t] = "boss"
        elif any(495 <= s <= 503 for s in species) or cname == "Boss":
            out[t] = "important"
        else:
            out[t] = "regular"
    return out


def _trainer_extras(g, rng, opts, pool, bst, cats, log):
    cat_key = {"boss": "Boss", "important": "Important", "regular": "Regular"}
    wanted = any(opts["extra" + c] for c in cat_key.values()) or any(opts["items" + c] for c in cat_key.values()) \
        or opts["doubleBattles"]
    if not wanted:
        return
    td = narc_spans(g.rom, g.p["trdata"])
    s, e = file_span(g.rom, g.p["trpoke"])
    members, btnf = nds_rebuild.narc_unpack(bytes(g.rom[s:e]))
    added = items = doubles = 0
    for t in range(1, min(len(td), len(members))):
        ds, de = td[t]
        if de - ds < 4:
            continue
        flags, btype, n = g.rom[ds], g.rom[ds + 2], g.rom[ds + 3]
        size = 8 + (2 if flags & 2 else 0) + (8 if flags & 1 else 0)
        m = members[t]
        if n == 0 or len(m) < n * size:
            continue
        mons = []
        for k in range(n):
            o = k * size
            iv, ab, lv, x, sp, form = struct.unpack_from("<BBBBHH", m, o)
            item = struct.unpack_from("<H", m, o + 8)[0] if flags & 2 else 0
            moves = list(struct.unpack_from("<4H", m, o + 8 + (2 if flags & 2 else 0))) if flags & 1 else None
            mons.append({"iv": iv, "ab": ab, "lv": lv, "x": x, "sp": sp, "form": form, "item": item, "moves": moves})
        cat = cat_key[cats.get(t, "regular")]
        extra = int(opts["extra" + cat] or 0)
        double = opts["doubleBattles"] and btype == 0
        if double and n + extra < 2:
            extra = 2 - n
        for _ in range(max(0, min(extra, 6 - len(mons)))):
            ref = max(mons, key=lambda d: d["lv"])
            used = {d["sp"] for d in mons}
            sp = _pick(rng, pool, bst, ref["sp"] if ref["sp"] in bst else rng.choice(pool), True, used)
            mons.append({"iv": ref["iv"], "ab": 0, "lv": ref["lv"], "x": 0, "sp": sp, "form": 0, "item": 0,
                         "moves": None})
            added += 1
        new_flags = flags
        if opts["items" + cat]:
            new_flags |= 2
            choices = BERRIES if opts["itemsConsumable"] else HELD_ITEMS
            top = max(d["lv"] for d in mons)
            first_top = next(d for d in mons if d["lv"] == top)
            for d in mons:
                if not opts["itemsHighestOnly"] or d is first_top:
                    d["item"] = rng.choice(choices)
                    items += 1
        if new_flags & 1:
            for d in mons:
                if d["moves"] is None:
                    if opts["learnsets"] == "metronome":
                        d["moves"] = [METRONOME, 0, 0, 0]
                    elif opts["betterMovesets"]:
                        d["moves"] = _best_moves(g, d["sp"], d["lv"])
                    else:
                        d["moves"] = _moves_at_level(g, d["sp"], d["lv"])
        out = bytearray()
        for d in mons:
            out += struct.pack("<BBBBHH", d["iv"], d["ab"], d["lv"], d["x"], d["sp"], d["form"])
            if new_flags & 2:
                out += struct.pack("<H", d["item"])
            if new_flags & 1:
                out += struct.pack("<4H", *d["moves"])
        members[t] = bytes(out)
        g.rom[ds] = new_flags
        g.rom[ds + 3] = len(mons)
        if double and len(mons) >= 2:
            g.rom[ds + 2] = 1
            doubles += 1
    where = nds_rebuild.replace_file(g.rom, g.p["trpoke"], nds_rebuild.narc_pack(members, btnf))
    parts = []
    if added:
        parts.append(f"{added} Pokémon en plus (boss {opts['extraBoss']}, importants {opts['extraImportant']}, "
                     f"autres {opts['extraRegular']})")
    if items:
        parts.append(f"{items} objets tenus" + (" (baies seulement)" if opts["itemsConsumable"] else "")
                     + (" (plus haut niveau seulement)" if opts["itemsHighestOnly"] else ""))
    if doubles:
        parts.append(f"{doubles} dresseurs en combat double (phase expérimentale)")
    log.append("Dresseurs, équipes agrandies : " + (", ".join(parts) or "rien à changer") + f" ; fichier {where}")


def _replace_word(chars, old, new):
    out, i, n = [], 0, len(old)
    while i < len(chars):
        if chars[i:i + n] == old and (i == 0 or not chr(chars[i - 1]).isalpha()) \
                and (i + n >= len(chars) or chars[i + n] >= 0xF000 or not chr(chars[i + n]).isalpha()):
            out += new
            i += n
        else:
            out.append(chars[i])
            i += 1
    return out


def _texts(g, rng, opts, starters, log):
    do_starters = bool(starters) and opts["starterText"]
    if not (do_starters or opts["shuffleTrainerNames"] or opts["shuffleClassNames"]):
        return
    s, e = file_span(g.rom, gen5_maps.GAMES[g.key]["narcs"]["text"])
    sys_members, sys_btnf = nds_rebuild.narc_unpack(bytes(g.rom[s:e]))
    changed_sys = False
    if opts["shuffleTrainerNames"] or opts["shuffleClassNames"]:
        for key, bank in (("shuffleTrainerNames", g.p["trainer_names"]), ("shuffleClassNames", g.p["classes"])):
            if not opts[key]:
                continue
            t = nds_rebuild.text_unpack(sys_members[bank])
            strings = t["blocks"][0]
            idx = [i for i in range(1, len(strings))
                   if nds_rebuild.to_str(strings[i]).strip() not in ("", "Rival", "no data", "-")
                   and all(c < 0xF000 or c == 0xFFFF for c in nds_rebuild.decompress(strings[i]))]
            vals = [strings[i] for i in idx]
            rng.shuffle(vals)
            for i, v in zip(idx, vals):
                strings[i] = v
            sys_members[bank] = nds_rebuild.text_pack(t)
            changed_sys = True
        log.append("Noms mélangés : " + ", ".join(x for k, x in (("shuffleTrainerNames", "dresseurs"),
                                                                  ("shuffleClassNames", "classes de dresseurs")) if opts[k]))
    if changed_sys:
        where = nds_rebuild.replace_file(g.rom, gen5_maps.GAMES[g.key]["narcs"]["text"],
                                         nds_rebuild.narc_pack(sys_members, sys_btnf))
        log.append(f"Textes système : fichier {where}")
    if do_starters:
        species = nds_rebuild.text_unpack(sys_members[g.p["species_names"]])["blocks"][0]
        name = lambda sid: [c for c in nds_rebuild.decompress(species[sid]) if c != 0xFFFF]
        s, e = file_span(g.rom, g.p["story_text"])
        members, btnf = nds_rebuild.narc_unpack(bytes(g.rom[s:e]))
        t = nds_rebuild.text_unpack(members[g.p["starter_text"]])
        count = 0
        for b in t["blocks"]:
            for i, chars in enumerate(b):
                new = chars
                for k, (old_sp, new_sp) in enumerate(starters.items()):
                    new = _replace_word(new, name(old_sp), [0xE000 + k])
                for k, (old_sp, new_sp) in enumerate(starters.items()):
                    new = _replace_word(new, [0xE000 + k], name(new_sp))
                if new != chars:
                    b[i] = new
                    count += 1
        members[g.p["starter_text"]] = nds_rebuild.text_pack(t)
        where = nds_rebuild.replace_file(g.rom, g.p["story_text"], nds_rebuild.narc_pack(members, btnf))
        log.append(f"Textes des starters (« quel était ton premier Pokémon ? ») : {count} phrases mises à jour ; fichier {where}")


TM_TABLE_ORDER = [f"CT{i:02d}" for i in range(1, 93)] + [f"CS{i:02d}" for i in range(1, 7)] + ["CT93", "CT94", "CT95"]
FIELD_TMS = {"CT28", "CT70", "CT94"}
HM_MOVES = {15, 19, 57, 70, 127, 291}


def _tm_table(a9, base):
    lab = {}
    for sp in base["species"].values():
        for label, mv in sp["tm"]:
            lab[label] = mv
    first = struct.pack("<5H", *[lab[f"CT0{i}"] for i in range(1, 6)])
    off = a9.find(first)
    if off < 0 or a9.find(first, off + 1) >= 0:
        return None
    return off


def _randomize_tm_moves(g, rng, opts, log, base):
    if opts["tmMoves"] == "off" or not base:
        return None
    a9, mp = nds_rebuild.arm9_read(g.rom)
    a9 = bytearray(a9)
    off = _tm_table(a9, base)
    if off is None:
        log.append("CT : NON modifiées (table introuvable dans ce jeu)")
        return None
    table = list(struct.unpack_from("<101H", a9, off))
    labels = dict(zip(TM_TABLE_ORDER, table))
    moves = {m: g.move(m) for m in range(1, MAX_MOVE + 1)}
    banned = {STRUGGLE, METRONOME if opts["learnsets"] == "metronome" else 0} | HM_MOVES
    if opts["noGameBreaking"]:
        banned |= GAME_BREAKING_MOVES
    keep = {lab for lab in labels if lab.startswith("CS") or (opts["keepFieldTMs"] and lab in FIELD_TMS)}
    used = {labels[lab] for lab in keep}
    pool = [m for m in range(1, MAX_MOVE + 1) if m not in banned and m not in used]
    good = [m for m in pool if moves[m]["cat"] != 0 and moves[m]["power"] >= 70]
    pct = max(0, min(100, int(opts["goodDamaging"] or 0)))
    for lab in TM_TABLE_ORDER:
        if lab in keep:
            continue
        src = good if pct and rng.random() * 100 < pct else pool
        src = [m for m in src if m not in used] or [m for m in pool if m not in used]
        m = rng.choice(src)
        used.add(m)
        labels[lab] = m
    struct.pack_into("<101H", a9, off, *[labels[lab] for lab in TM_TABLE_ORDER])
    nds_rebuild.arm9_write(g.rom, a9, mp)
    log.append("Attaques des CT : aléatoires (CS gardées" + (", Tunnel/Flash/Éclate-Roc gardées" if opts["keepFieldTMs"] else "")
               + ") ; programme du jeu (ARM9) recompressé")
    return labels


def _randomize_trades(g, rng, opts, pool, bst, log, names):
    if opts["trades"] == "off":
        return []
    spans = narc_spans(g.rom, g.p["trades"])
    lines = []
    for i, (s, e) in enumerate(spans):
        if e - s < 108:
            continue
        got = struct.unpack_from("<I", g.rom, s + 4)[0]
        asked = struct.unpack_from("<I", g.rom, s + 96)[0]
        if not (0 < got <= MAX_SPECIES):
            continue
        new_got = _pick(rng, pool, bst, got, False)
        struct.pack_into("<II", g.rom, s + 4, new_got, 0)
        new_asked = asked
        if opts["trades"] == "both" and 0 < asked <= MAX_SPECIES:
            new_asked = _pick(rng, pool, bst, asked, False, {new_got})
            struct.pack_into("<I", g.rom, s + 96, new_asked)
        lines.append(f"  Échange {i} : donne {names(asked)}→{names(new_asked)}, reçoit {names(got)}→{names(new_got)}")
    log.append(f"Échanges en jeu : {len(lines)} échanges ("
               + ("Pokémon reçus et demandés" if opts["trades"] == "both" else "Pokémon reçus") + ")")
    return lines


def _randomize_statics(g, rng, opts, pool, bst, log, names):
    if opts["statics"] == "off":
        return []
    spans = narc_spans(g.rom, g.p["scripts"])
    op = g.p["static_op"]
    legend_pool = sorted(LEGENDARIES)
    lines = []
    for fi, (s, e) in enumerate(spans):
        f = g.rom[s:e]
        sites = []
        for o in range(0, len(f) - 5):
            if f[o] == op & 0xFF and f[o + 1] == op >> 8:
                sp, lv = struct.unpack_from("<HH", f, o + 2)
                if 1 <= sp <= MAX_SPECIES and 5 <= lv <= 100:
                    sites.append((o + 2, sp, lv))
        if not sites:
            continue
        mapping = {}
        for o, sp, lv in sites:
            if sp not in mapping:
                if opts["statics"] == "swap" and sp in LEGENDARIES:
                    mapping[sp] = _pick(rng, legend_pool, bst, sp, True, set(mapping.values()) | {sp})
                else:
                    src = [x for x in pool if (x in LEGENDARIES) == (sp in LEGENDARIES)] if opts["statics"] == "swap" else pool
                    mapping[sp] = _pick(rng, src or pool, bst, sp, True, set(mapping.values()))
            struct.pack_into("<H", g.rom, s + o, mapping[sp])
        for o in range(0, len(f) - 5):
            if f[o] == 0xAB and f[o + 1] == 0:
                sp = struct.unpack_from("<H", f, o + 2)[0]
                if sp in mapping and struct.unpack_from("<H", f, o + 4)[0] == 0:
                    struct.pack_into("<H", g.rom, s + o + 2, mapping[sp])
        for old, new in mapping.items():
            lv = next(l for _, sp, l in sites if sp == old)
            lines.append(f"  {names(old)} Nv{lv} -> {names(new)} (script {fi})")
    log.append(f"Pokémon fixes (légendaires, statues...) : {len(lines)} remplacés ("
               + ("légendaires ↔ légendaires" if opts["statics"] == "swap" else "force similaire") + ")")
    return lines


FIELD_ITEM_POOL = ([2, 3, 4, *range(6, 16), *range(17, 70), *range(76, 93), *range(106, 111), *range(116, 120), 134,
                    *range(149, 164), *range(169, 175), *range(184, 225), *range(228, 236), *range(237, 256),
                    *range(265, 272), 275, 276, 277, *range(280, 288), *range(289, 316), *range(317, 328),
                    *range(538, 572), 577, *range(580, 592)])
TM_ITEMS = [*range(328, 420), 618, 619, 620]
HM_ITEMS = set(range(420, 426))
MONKEYS = (511, 513, 515)


def _randomize_gifts(g, rng, opts, pool, bst, log, names):
    if opts["gifts"] == "off":
        return []
    spans = narc_spans(g.rom, g.p["scripts"])
    lines = []
    for fi, (s, e) in enumerate(spans):
        f = g.rom[s:e]
        sites = []
        for o in range(0, len(f) - 9):
            if f[o + 1] == 0x01 and f[o] == 0x0E and f[o + 3] == 0x80:
                sp, form, lv = struct.unpack_from("<HHH", f, o + 4)
                if 1 <= sp <= MAX_SPECIES and form < 32 and 1 <= lv <= 100:
                    sites.append((o + 4, o + 6, sp, lv))
            elif f[o + 1] == 0x02 and f[o] == 0xEA and f[o + 3] == 0x80 and g.p["static_op"] == 0x0174:
                sp, lv = struct.unpack_from("<HH", f, o + 4)
                if 1 <= sp <= MAX_SPECIES and 1 <= lv <= 100:
                    sites.append((o + 4, None, sp, lv))
        if fi == g.p.get("monkey_script"):
            for o in range(3, len(f) - 1):
                if f[o - 3] == 0x57 and f[o - 2] == 0 and f[o - 1] == 1:
                    sp = struct.unpack_from("<H", f, o)[0]
                    if sp in MONKEYS:
                        sites.append((o, None, sp, 10))
        if not sites:
            continue
        mapping = {}
        for o, form_off, sp, lv in sites:
            if sp not in mapping:
                mapping[sp] = _pick(rng, pool, bst, sp, opts["giftSimilar"], set(mapping.values()))
            struct.pack_into("<H", g.rom, s + o, mapping[sp])
            if form_off is not None:
                struct.pack_into("<H", g.rom, s + form_off, 0)
        for o in range(0, len(f) - 5):
            if f[o] == 0xAB and f[o + 1] == 0:
                sp = struct.unpack_from("<H", f, o + 2)[0]
                if sp in mapping and struct.unpack_from("<H", f, o + 4)[0] == 0:
                    struct.pack_into("<H", g.rom, s + o + 2, mapping[sp])
        for old, new in mapping.items():
            lines.append(f"  {names(old)} -> {names(new)} (script {fi})")
    log.append(f"Pokémon offerts : {len(lines)} remplacés" + (" (force similaire)" if opts["giftSimilar"] else "")
               + " ; fossiles et œufs non concernés")
    return lines


def _field_item_sites(g):
    spans = narc_spans(g.rom, g.p["scripts"])
    fi = g.p["item_script"]
    if fi >= len(spans):
        return []
    s, e = spans[fi]
    f = g.rom[s:e]
    sites = [s + o + 4 for o in range(0, len(f) - 12)
             if f[o:o + 4] == b"\x28\x00\x0c\x80" and f[o + 6:o + 10] == b"\x28\x00\x0d\x80"]
    return sites if len(sites) > 100 else []


def _hidden_item_sites5(g):
    spans = narc_spans(g.rom, g.p["scripts"])
    fi = g.p["item_script"] + 1
    if fi >= len(spans):
        return []
    s, e = spans[fi]
    f = g.rom[s:e]
    h0, h1, h2 = b"\x2a\x00\x00\x80", b"\x2a\x00\x01\x80", b"\x2a\x00\x02\x80"
    sites = [s + o + 4 for o in range(0, len(f) - 16) if f[o:o + 4] == h0 and f[o + 6:o + 10] == h1 and f[o + 12:o + 16] == h2
             and 1 <= struct.unpack_from("<H", f, o + 4)[0] <= 638]
    return sites if len(sites) > 100 else []


def _new_field_items(rng, mode, old):
    if mode == "shuffle":
        movable = [i for i, it in enumerate(old) if it not in HM_ITEMS]
        vals = [old[i] for i in movable]
        rng.shuffle(vals)
        new = list(old)
        for i, v in zip(movable, vals):
            new[i] = v
        return new
    tms = [t for t in TM_ITEMS if t not in old]
    new = []
    for it in old:
        if it in HM_ITEMS or not (1 <= it <= 638):
            new.append(it)
        elif it in TM_ITEMS:
            pick = rng.choice(tms or TM_ITEMS)
            if pick in tms:
                tms.remove(pick)
            new.append(pick)
        else:
            new.append(rng.choice(FIELD_ITEM_POOL))
    return new


def _randomize_field_items(g, rng, opts, log, items_fr):
    if opts["fieldItems"] == "off":
        return []
    sites = _field_item_sites(g)
    if not sites:
        log.append("Objets au sol : NON modifiés (script des objets introuvable)")
        return []
    name = lambda i: items_fr.get(str(i), f"objet {i}")
    out = []
    for label, group in (("Objets au sol", sites), ("Objets cachés", _hidden_item_sites5(g))):
        if not group:
            continue
        old = [struct.unpack_from("<H", g.rom, p)[0] for p in group]
        new = _new_field_items(rng, opts["fieldItems"], old)
        for p, it in zip(group, new):
            struct.pack_into("<H", g.rom, p, it)
        log.append(f"{label} : {len(group)} objets " + ("mélangés" if opts["fieldItems"] == "shuffle" else "aléatoires (CT -> CT)"))
        out += [f"  {name(a)} -> {name(b)}" for a, b in zip(old, new) if a != b]
    return out


SHOP5_BW_SETS = ((333112, 333116, 333126, 333132, 333156, 333200, 333284, 333298, 333312, 333328, 333344, 333360, 333376, 333392, 333410, 333428, 333446, 333468, 333490, 333512, 333560, 333588, 333620, 333684, 333718, 333754),
    (333104, 333108, 333118, 333124, 333148, 333192, 333276, 333290, 333304, 333320, 333336, 333352, 333368, 333384, 333402, 333420, 333438, 333460, 333482, 333504, 333552, 333580, 333612, 333676, 333710, 333746),
    (333096, 333100, 333110, 333116, 333140, 333184, 333268, 333282, 333296, 333312, 333328, 333344, 333360, 333376, 333394, 333412, 333430, 333452, 333474, 333496, 333544, 333572, 333604, 333668, 333702, 333738),
    (333116, 333120, 333130, 333136, 333160, 333204, 333288, 333302, 333316, 333332, 333348, 333364, 333380, 333396, 333414, 333432, 333450, 333472, 333494, 333516, 333564, 333592, 333624, 333688, 333722, 333758),
    (333108, 333112, 333122, 333128, 333152, 333196, 333280, 333294, 333308, 333324, 333340, 333356, 333372, 333388, 333406, 333424, 333442, 333464, 333486, 333508, 333556, 333584, 333616, 333680, 333714, 333750),
    (333088, 333092, 333106, 333128, 333112, 333228, 333264, 333278, 333292, 333308, 333324, 333340, 333356, 333372, 333390, 333408, 333492, 333426, 333448, 333470, 333540, 333568, 333600, 333664, 333698, 333734),
    (333080, 333084, 333098, 333120, 333104, 333220, 333256, 333270, 333284, 333300, 333316, 333332, 333348, 333364, 333382, 333400, 333484, 333418, 333440, 333462, 333532, 333560, 333592, 333656, 333690, 333726),
    (332356, 332360, 332370, 332392, 332400, 332468, 332528, 332542, 332572, 332620, 332588, 332604, 332556, 332636, 332654, 332672, 332690, 332712, 332734, 332756, 332804, 332832, 332864, 332928, 332962, 332998),
    (332348, 332352, 332362, 332384, 332392, 332460, 332520, 332534, 332564, 332612, 332580, 332596, 332548, 332628, 332646, 332664, 332682, 332704, 332726, 332748, 332796, 332824, 332856, 332920, 332954, 332990),
    (333092, 333096, 333110, 333132, 333116, 333232, 333268, 333282, 333296, 333312, 333328, 333344, 333360, 333376, 333394, 333412, 333496, 333430, 333452, 333474, 333544, 333572, 333604, 333668, 333702, 333738),
    (333084, 333088, 333102, 333124, 333108, 333224, 333260, 333274, 333288, 333304, 333320, 333336, 333352, 333368, 333386, 333404, 333488, 333422, 333444, 333466, 333536, 333564, 333596, 333660, 333694, 333730))
SHOP5_BW_SIZES = (2, 2, 3, 4, 4, 6, 7, 7, 8, 8, 8, 8, 8, 9, 9, 9, 11, 11, 11, 11, 14, 16, 16, 17, 18, 19)
MAIL_ITEMS5 = range(137, 149)


def _shop_lists5(g):
    import nds_rebuild
    if g.key in ("POKEMON B", "POKEMON W"):
        ov = bytes(nds_rebuild.overlay_read(g.rom, 21))
        for offs in SHOP5_BW_SETS:
            if offs[-1] + 2 * SHOP5_BW_SIZES[-1] > len(ov):
                continue
            lists = [list(struct.unpack_from(f"<{n}H", ov, o)) for o, n in zip(offs, SHOP5_BW_SIZES)]
            if lists[0] != [4, 17] or lists[16][:3] != [4, 3, 17] or any(not 0 < x < 700 for l in lists for x in l):
                continue

            def write(new, offs=offs):
                lo, hi = offs[0], offs[-1] + 2 * SHOP5_BW_SIZES[-1]
                buf = bytearray(ov[lo:hi])
                for o, n, l in zip(offs, SHOP5_BW_SIZES, new):
                    struct.pack_into(f"<{n}H", buf, o - lo, *l)
                nds_rebuild.code_set_bytes(g.rom, 21, lo, bytes(buf))
            return lists, write
        return None
    if g.key in ("POKEMON B2", "POKEMON W2"):
        s, e = file_span(g.rom, "a/2/8/2")
        members, btnf = nds_rebuild.narc_unpack(bytes(g.rom[s:e]))
        lists = [list(struct.unpack_from(f"<{len(m) // 2}H", m)) for m in members[:32]]
        if lists[0] != [4, 17] or any(not 0 < x < 700 for l in lists for x in l):
            return None

        def write(new):
            for i, l in enumerate(new):
                members[i] = struct.pack(f"<{len(l)}H", *l)
            nds_rebuild.replace_file(g.rom, "a/2/8/2", nds_rebuild.narc_pack(members, btnf))
        return lists, write
    return None


def _randomize_shops5(g, rng, opts, log, items_fr):
    if opts["shops"] == "off":
        return
    got = _shop_lists5(g)
    if got is None:
        log.append("Pas encore disponible pour ce jeu (ignoré) : magasins")
        return
    lists, write = got
    keep = lambda it: it in TM_ITEMS or it in HM_ITEMS or it == 4 or it >= 540
    pool_items = sorted({it for l in lists for it in l if not keep(it) and it not in MAIL_ITEMS5})
    before = [list(l) for l in lists]
    if opts["shops"] == "shuffle":
        slots = [(i, k) for i, l in enumerate(lists) for k, it in enumerate(l) if not keep(it)]
        vals = [lists[i][k] for i, k in slots]
        rng.shuffle(vals)
        for (i, k), v in zip(slots, vals):
            lists[i][k] = v
        for l in lists:
            for k in range(len(l)):
                if l.index(l[k]) != k and not keep(l[k]):
                    free = [x for x in pool_items if x not in l]
                    if free:
                        l[k] = rng.choice(free)
    else:
        for l in lists:
            for k, it in enumerate(l):
                if not keep(it):
                    free = [x for x in pool_items if x not in l]
                    if free:
                        l[k] = rng.choice(free)
    write(lists)
    changed = sum(a != b for x, y in zip(before, lists) for a, b in zip(x, y))
    log.append(f"Magasins : {len(lists)} boutiques, {changed} objets changés (CT et Poké Balls gardés) - "
               + ("mélangés" if opts["shops"] == "shuffle" else "parmi les objets vendus dans le jeu"))


FOSSILS = (138, 140, 142, 345, 347, 408, 410, 564, 566)


def _randomize_fossils_eggs(g, rng, opts, pool, bst, pre, log, names):
    if opts["fossils"] == "off" and opts["eggs"] == "off":
        return []
    spans = narc_spans(g.rom, g.p["scripts"])
    lines = []
    basics = [x for x in pool if x not in pre]
    for fi, (s, e) in enumerate(spans):
        f = g.rom[s:e]
        if opts["fossils"] != "off":
            sites = [o + 4 for o in range(0, len(f) - 6)
                     if f[o:o + 4] == b"\x28\x00\x23\x80" and struct.unpack_from("<H", f, o + 4)[0] in FOSSILS]
            if len(sites) >= 7:
                used = set()
                for o in sites:
                    old = struct.unpack_from("<H", f, o)[0]
                    new = _pick(rng, pool, bst, old, opts["fossilSimilar"], used)
                    used.add(new)
                    struct.pack_into("<H", g.rom, s + o, new)
                    lines.append(f"  Fossile : {names(old)} -> {names(new)}")
        if opts["eggs"] != "off":
            for o in range(0, len(f) - 8):
                if f[o] == 0x0F and f[o + 1] == 0x01 and f[o + 3] == 0x80:
                    old = struct.unpack_from("<H", f, o + 4)[0]
                    if 1 <= old <= MAX_SPECIES:
                        new = rng.choice([x for x in basics if x != old] or pool)
                        struct.pack_into("<H", g.rom, s + o + 4, new)
                        lines.append(f"  Œuf : {names(old)} -> {names(new)} (script {fi})")
    done = [x for k, x in (("fossils", "fossiles"), ("eggs", "œufs")) if opts[k] != "off"]
    log.append(f"{' et '.join(done).capitalize()} : {len(lines)} remplacés (œufs : Pokémon de base)")
    return lines


def _table_places(rom_bytes, game_key):
    try:
        zones = gen4_maps._narc_files(gen4_maps._rom_file(rom_bytes, gen5_maps.GAMES[game_key]["narcs"]["zones"]))[0]
        text = gen4_maps._narc_files(gen4_maps._rom_file(rom_bytes, gen5_maps.GAMES[game_key]["narcs"]["text"]))
        names = gen5_maps._decode_text_bank(text[gen5_maps.GAMES[game_key]["names_bank"]])
    except Exception:
        return {}
    out = {}
    for z in range(len(zones) // 48):
        hdr = zones[48 * z:48 * z + 48]
        table = struct.unpack_from("<H", hdr, 20)[0] & 0x1FFF
        if table == 0x1FFF:
            continue
        name = names[hdr[26]] if hdr[26] < len(names) else f"zone {z}"
        if name not in out.setdefault(table, []):
            out[table].append(name)
    return out


def _evo_text(base, method, param):
    item = lambda: base.get("items", {}).get(str(param), f"objet {param}")
    move = lambda: base["moves"].get(str(param), [f"attaque {param}"])[0]
    sp = lambda: base["species"].get(str(param), {}).get("name", f"#{param}")
    return {
        1: lambda: "Bonheur élevé + gain de niveau", 2: lambda: "Bonheur élevé + gain de niveau, le jour",
        3: lambda: "Bonheur élevé + gain de niveau, la nuit", 4: lambda: f"Nv. {param}", 5: lambda: "Échange",
        6: lambda: "Échange en tenant " + item(), 7: lambda: "Échange contre Carabing / Escargaume",
        8: lambda: item(), 9: lambda: f"Nv. {param}, Attaque > Défense", 10: lambda: f"Nv. {param}, Attaque = Défense",
        11: lambda: f"Nv. {param}, Attaque < Défense", 12: lambda: f"Nv. {param}, selon la personnalité (aléatoire)",
        13: lambda: f"Nv. {param}, selon la personnalité (aléatoire)", 14: lambda: f"Nv. {param}",
        15: lambda: "Apparaît quand Ningale évolue (Nv. 20) s'il reste une place dans l'équipe et une Poké Ball",
        16: lambda: "Beauté au maximum + gain de niveau", 17: lambda: item() + ", mâle", 18: lambda: item() + ", femelle",
        19: lambda: "Gain de niveau en tenant " + item() + ", le jour", 20: lambda: "Gain de niveau en tenant " + item() + ", la nuit",
        21: lambda: "Gain de niveau en connaissant " + move(), 22: lambda: "Gain de niveau avec " + sp() + " dans l'équipe",
        23: lambda: f"Nv. {param}, mâle", 24: lambda: f"Nv. {param}, femelle",
    }.get(method, lambda: None)()


def _fiche_data(g, base, evo_changes, tm_moves=None):
    tnames = base["typeNames"]
    moves = {}
    for m in range(1, MAX_MOVE + 1):
        d = g.move(m)
        name = base["moves"].get(str(m), [f"#{m}"])[0]
        moves[m] = [name, tnames[d["type"]] if d["type"] < len(tnames) else "?",
                    d["power"] if d["power"] > 1 else None, d["acc"] if 0 < d["acc"] <= 100 else None]
    tm_label = {}
    for sp in base["species"].values():
        for label, _ in sp["tm"]:
            n = int(label[2:])
            tm_label[label] = n - 1 if label.startswith("CT") else g.tm_count + n - 1
    label_move = {}
    for sp in base["species"].values():
        for label, mv in sp["tm"]:
            label_move[label] = mv
    if tm_moves:
        label_move.update(tm_moves)
    order = sorted(tm_label, key=lambda x: (x[:2] == "CS", x))
    old_target = {(s, o): n for s, o, n in evo_changes}
    species, engine_types = {}, {}
    for s in range(1, MAX_SPECIES + 1):
        b = base["species"].get(str(s), {})
        t1, t2 = g.types(s)
        st = g.stats(s)
        ab = g.abilities(s)
        abil = []
        for i, a in enumerate(ab):
            if a and (i != 1 or a != ab[0]):
                nm = base["abilities"].get(str(a), f"#{a}")
                if [nm, i == 2] not in abil:
                    abil.append([nm, i == 2])
        bits = g.tm_bits(s)
        sp = {"name": b.get("name", f"#{s}"), "types": [tnames[t] for t in _type_list(t1, t2)], "ab": abil,
              "lv": [[lv, mv] for mv, lv in g.learnset(s)],
              "tm": [[lab, label_move[lab]] for lab in order if bits >> tm_label[lab] & 1],
              "st": [st[0], st[1], st[2], st[4], st[5], st[3]]}
        texts = {t: txt for t, txt in b.get("ev", [])}
        evs = []
        for method, param, target in g.evolutions(s):
            if method and 0 < target <= MAX_SPECIES:
                orig = next((o for (ss, o), n in old_target.items() if ss == s and n == target), target)
                evs.append([target, _evo_text(base, method, param) or texts.get(orig, "Gain de niveau dans un lieu spécial")])
        if evs:
            sp["ev"] = evs
        species[s] = sp
        engine_types[s] = [t1 + 1, (t2 + 1) if t2 != t1 else None]
    for s, sp in species.items():
        for target, _ in sp.get("ev", []):
            species.setdefault(target, {})["pre"] = s
    return {"vg": base["vg"], "gen": 5, "moves": moves, "species": species, "engineTypes": engine_types,
            "randomized": True}


GEN4_UNSUPPORTED = {"trades": "échanges",
                    "statics": "Pokémon fixes", "gifts": "Pokémon offerts", "fossils": "fossiles",
                    "eggs": "œufs", "fieldItems": "objets au sol", "doubleBattles": "combats doubles",
                    "shuffleTrainerNames": "noms de dresseurs", "shuffleClassNames": "noms de classes",
                    "extraBoss": "Pokémon en plus (boss)", "extraImportant": "Pokémon en plus (importants)",
                    "extraRegular": "Pokémon en plus (autres)", "itemsBoss": "objets des dresseurs",
                    "itemsImportant": "objets des dresseurs", "itemsRegular": "objets des dresseurs"}
GEN3_UNSUPPORTED = dict({k: v for k, v in GEN4_UNSUPPORTED.items()
                         if k not in ("trades", "statics", "gifts", "fossils", "eggs", "fieldItems", "shuffleTrainerNames",
                                      "shuffleClassNames", "doubleBattles", "extraBoss", "extraImportant",
                                      "extraRegular", "itemsBoss", "itemsImportant", "itemsRegular")},
                        moveCategory="catégorie des attaques (fixée par le type en 3G)")


def randomize(src_path, options, out_path=None, fiche_base=None, sprite_dir=None):
    global MAX_SPECIES, MAX_MOVE, MAX_ABILITY
    saved = (MAX_SPECIES, MAX_MOVE, MAX_ABILITY)
    if gen4_maps._rom_title(src_path) in R4.PATHS4:
        MAX_SPECIES, MAX_MOVE, MAX_ABILITY = R4.MAX_SPECIES, R4.MAX_MOVE, R4.MAX_ABILITY
    elif R3.gba_title(src_path) in R3.GAMES3:
        MAX_SPECIES, MAX_MOVE, MAX_ABILITY = R3.MAX_SPECIES, R3.MAX_MOVE, R3.MAX_ABILITY
    try:
        return _randomize(src_path, options, out_path, fiche_base, sprite_dir)
    finally:
        MAX_SPECIES, MAX_MOVE, MAX_ABILITY = saved


def _randomize(src_path, options, out_path=None, fiche_base=None, sprite_dir=None):
    opts = dict(DEFAULTS)
    opts.update({k: v for k, v in (options or {}).items() if k in DEFAULTS})
    for k in ("wildLevels", "trainerLevels"):
        opts[k] = max(-50, min(200, int(opts[k] or 0)))
    for k, hi in (("minCatchRate", 255), ("goodDamaging", 100), ("fullyEvolvedAt", 100),
                  ("extraBoss", 5), ("extraImportant", 5), ("extraRegular", 5)):
        opts[k] = max(0, min(hi, int(opts[k] or 0)))
    game_key = gen4_maps._rom_title(src_path)
    gen4 = game_key in R4.PATHS4
    gen3 = False
    if game_key not in GAME_FAMILY and not gen4:
        game_key = R3.gba_title(src_path)
        gen3 = game_key in R3.GAMES3
        if not gen3:
            raise ValueError(f"Jeu non pris en charge pour l'instant : {game_key} (jeux 3G, 4G et 5G seulement)")
    seed = opts["seed"]
    if seed in (None, ""):
        seed = random.SystemRandom().randrange(1, 10 ** 9)
    seed = int(seed)
    rng = random.Random(f"{game_key}:{seed}:" + json.dumps({k: v for k, v in opts.items() if k != "seed"}, sort_keys=True))
    _USAGE.clear()
    with open(src_path, "rb") as f:
        rom = bytearray(f.read())
    g = R3.Gen3Rom(rom, game_key) if gen3 else R4.Gen4Rom(rom, game_key) if gen4 else Gen5Rom(rom, game_key)
    base_names = (fiche_base or {}).get("species", {})

    def names(sid):
        return base_names.get(str(sid), {}).get("name", f"#{sid}")

    order, pre = _family_order(g)
    kids = {}
    for s_, p_ in pre.items():
        kids.setdefault(p_, []).append(s_)
    _STAGE.clear()
    for s_ in range(1, MAX_SPECIES + 1):
        _STAGE[s_] = 2 if s_ not in kids else (1 if s_ in pre else 0)

    def pick_ws(rng_, pool_, bst_, old_, similar_, avoid_=()):
        return _pick(rng_, pool_, bst_, old_, similar_, avoid_, opts["sameStage"])
    pool = [s for s in range(1, MAX_SPECIES + 1) if not (opts["noLegendaries"] and s in LEGENDARIES)]
    log = []

    _randomize_moves_data(g, rng, opts, log)
    _randomize_personal(g, rng, opts, order, pre, log)
    bst = {s: g.bst(s) for s in range(1, MAX_SPECIES + 1)}
    evo_changes = _randomize_evolutions(g, rng, opts, bst, pool, log, names)
    _randomize_learnsets(g, rng, opts, log)
    if gen3:
        starters = R3.randomize_starters(g, rng, opts, pool, pre, log, names)
        wild_lines = R3.randomize_wild(g, rng, opts, pool, bst, log, names, pick_ws, _type_list)
        cats3 = R3.trainer_categories(g, pre)
        trainer_lines = R3.randomize_trainers(g, rng, opts, pool, bst, log, names, pick_ws, _type_list,
                                              _best_moves, _moves_at_level, R3.STARTERS3[g.family], starters, pre)
        tm_moves = R3.randomize_tm_moves(g, rng, opts, log)
        _tm_compat_after(g, rng, opts, log, tm_moves, fiche_base)
        R3.randomize_tutors(g, rng, opts, log)
        gift_lines = R3.randomize_events(g, rng, opts, pool, bst, pre, log, names, _pick)
        R3.shuffle_names(g, rng, opts, log)
        R3.trainer_extras(g, rng, opts, pool, bst, cats3, log, _pick, _best_moves, _moves_at_level)
        R3.make_doubles(g, opts, log)
        R3.apply_tweaks(g, opts, log)
        skipped = sorted({label for k, label in GEN3_UNSUPPORTED.items() if opts[k] not in ("off", False, 0, None)})
        if skipped:
            log.append("Pas encore disponible en 3G (ignoré) : " + ", ".join(skipped))
        return _finish(src_path, out_path, rom, g, game_key, seed, opts, log, names, fiche_base, evo_changes, tm_moves,
                       trainer_lines, wild_lines, [], [], gift_lines, [], starters)
    if gen4:
        wild_lines = R4.randomize_wild(g, rng, opts, pool, bst, log, names, pick_ws, _type_list)
        starters = R4.randomize_starters(g, rng, opts, pool, pre, log, names)
        cats4 = R4.trainer_categories(g, pre)
        trainer_lines = R4.randomize_trainers(g, rng, opts, pool, bst, log, names, pick_ws, _type_list,
                                              _best_moves, _moves_at_level, starters, pre)
        tm_moves = R4.randomize_tm_moves(g, rng, opts, log, fiche_base)
        _tm_compat_after(g, rng, opts, log, tm_moves, fiche_base)
        R4.randomize_tutors(g, rng, opts, log, tm_moves)
        gift_lines = R4.randomize_events(g, rng, opts, pool, bst, pre, log, names, _pick)
        R4.shuffle_names(g, rng, opts, log)
        R4.trainer_extras(g, rng, opts, pool, bst, cats4, log, _pick, _best_moves, _moves_at_level)
        R4.make_doubles(g, opts, log)
        skipped = sorted({label for k, label in GEN4_UNSUPPORTED.items() if opts[k] not in ("off", False, 0, None)
                          and k not in ("trades", "statics", "gifts", "fossils", "eggs", "fieldItems", "shuffleTrainerNames",
                                        "shuffleClassNames", "doubleBattles", "extraBoss", "extraImportant", "extraRegular",
                                        "itemsBoss", "itemsImportant", "itemsRegular")})
        if skipped:
            log.append("Pas encore disponible en 4G (ignoré) : " + ", ".join(skipped))
        trade_lines, static_lines, item_lines = [], [], []
        return _finish(src_path, out_path, rom, g, game_key, seed, opts, log, names, fiche_base, evo_changes, tm_moves,
                       trainer_lines, wild_lines, trade_lines, static_lines, gift_lines, item_lines, starters)
    tm_moves = _randomize_tm_moves(g, rng, opts, log, fiche_base)
    _tm_compat_after(g, rng, opts, log, tm_moves, fiche_base)
    _randomize_tutors5(g, rng, opts, log, tm_moves)
    starters = _randomize_starters(g, rng, opts, pool, pre, log, names, sprite_dir)
    places = _table_places(rom, game_key)
    wild_lines = _randomize_wild(g, rng, opts, pool, bst, log, places, names) or []
    cats = _trainer_categories(g)
    trainer_lines = _randomize_trainers(g, rng, opts, pool, bst, log, names, starters)
    _trainer_extras(g, rng, opts, pool, bst, cats, log)
    _texts(g, rng, opts, starters, log)
    trade_lines = _randomize_trades(g, rng, opts, pool, bst, log, names)
    static_lines = _randomize_statics(g, rng, opts, pool, bst, log, names)
    gift_lines = _randomize_gifts(g, rng, opts, pool, bst, log, names)
    gift_lines += _randomize_fossils_eggs(g, rng, opts, pool, bst, pre, log, names)
    item_lines = _randomize_field_items(g, rng, opts, log, (fiche_base or {}).get("items", {}))
    _randomize_shops5(g, rng, opts, log, (fiche_base or {}).get("items", {}))

    return _finish(src_path, out_path, rom, g, game_key, seed, opts, log, names, fiche_base, evo_changes, tm_moves,
                   trainer_lines, wild_lines, trade_lines, static_lines, gift_lines, item_lines, starters)


def _finish(src_path, out_path, rom, g, game_key, seed, opts, log, names, fiche_base, evo_changes, tm_moves,
            trainer_lines, wild_lines, trade_lines, static_lines, gift_lines, item_lines, starters):
    if out_path is None:
        root, ext = os.path.splitext(src_path)
        out_path = f"{root} ({ {'en': 'Random', 'es': 'Aleatorio'}.get(i18n.LANG, 'Aleatoire')} {seed}){ext}"
    if os.path.abspath(out_path) == os.path.abspath(src_path):
        raise ValueError("refus d'écraser la ROM d'origine")
    with open(out_path, "wb") as f:
        f.write(rom)
    stem = os.path.splitext(out_path)[0]
    if fiche_base:
        with open(stem + ".pklab.json", "w", encoding="utf-8") as f:
            fiche = _fiche_data(g, fiche_base, evo_changes, tm_moves)
            t = shiny_patch.side_threshold(src_path)
            if t != 8:
                fiche["shinyThreshold"] = t
            json.dump(fiche, f, ensure_ascii=False, separators=(",", ":"))
    report_path = stem + ".txt"
    f = io.StringIO()
    if True:
        f.write(f"Randomizer PKLab\nROM d'origine : {os.path.basename(src_path)} ({game_key})\n"
                f"Graine : {seed}   Sans légendaires : {'oui' if opts['noLegendaries'] else 'non'}\n\n")
        f.write("\n".join("- " + x for x in log) + "\n")
        if evo_changes:
            f.write("\nÉvolutions\n" + "\n".join(f"  {names(s)} : {names(o) if o else 'chaque niveau'} -> {names(n)}" for s, o, n in evo_changes) + "\n")
        if trainer_lines:
            f.write("\nDresseurs importants\n" + "\n".join(trainer_lines) + "\n")
        if gift_lines:
            f.write("\nPokémon offerts\n" + "\n".join(gift_lines) + "\n")
        if item_lines:
            f.write("\nObjets au sol\n" + "\n".join(item_lines) + "\n")
        if static_lines:
            f.write("\nPokémon fixes\n" + "\n".join(static_lines) + "\n")
        if trade_lines:
            f.write("\nÉchanges en jeu\n" + "\n".join(trade_lines) + "\n")
        if wild_lines:
            f.write("\nPokémon sauvages\n" + "\n".join(wild_lines) + "\n")
    with open(report_path, "w", encoding="utf-8") as out:
        out.write(i18n.tr_lines(f.getvalue()))
    return out_path, report_path, {"seed": seed, "game": game_key, "changes": log,
                                   "starters": [names(s) for s in starters.values()] if starters else None}


def randomize_wild(src_path, seed=None, mode="zone", similar=True, no_legendaries=True, out_path=None, species_names=None):
    base = {"species": {str(k): {"name": v} for k, v in (species_names or {}).items()}} if species_names else None
    out, report, summary = randomize(src_path, {"seed": seed, "wild": mode, "wildSimilar": similar,
                                                "noLegendaries": no_legendaries, "wildWater": False},
                                     out_path=out_path, fiche_base=None)
    return out, report, summary
