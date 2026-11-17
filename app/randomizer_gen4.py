import struct

import gen4_maps

MAX_SPECIES = 493
MAX_MOVE = 467
MAX_ABILITY = 123

_DP = {"learn": "poketool/personal/wotbl.narc", "evo": "poketool/personal/evo.narc",
       "moves": "poketool/waza/waza_tbl.narc", "trdata": "poketool/trainer/trdata.narc",
       "trpoke": "poketool/trainer/trpoke.narc", "seal": False, "enc_kind": "dp", "msg": "msgdata/msg.narc", "vg": 8}
PATHS4 = {
    "POKEMON D": dict(_DP, personal="poketool/personal/personal.narc", enc="fielddata/encountdata/d_enc_data.narc"),
    "POKEMON P": dict(_DP, personal="poketool/personal_pearl/personal.narc", enc="fielddata/encountdata/p_enc_data.narc"),
    "POKEMON PL": dict(_DP, personal="poketool/personal/pl_personal.narc", moves="poketool/waza/pl_waza_tbl.narc",
                       enc="fielddata/encountdata/pl_enc_data.narc", seal=True, msg="msgdata/pl_msg.narc", vg=9),
    "POKEMON HG": {"personal": "a/0/0/2", "learn": "a/0/3/3", "evo": "a/0/3/4", "moves": "a/0/1/1",
                   "trdata": "a/0/5/5", "trpoke": "a/0/5/6", "enc": "a/0/3/7", "seal": True, "enc_kind": "hgss",
                   "msg": "a/0/2/7", "vg": 10},
}
PATHS4["POKEMON SS"] = dict(PATHS4["POKEMON HG"], enc="a/1/3/6")


def to5_type(t):
    return t if t < 9 else (0 if t == 9 else t - 1)


def to4_type(t):
    return t if t < 9 else t + 1


def to5_method(m):
    return m if m < 7 else m + 1


def to4_method(m):
    if m == 7:
        return 5
    return m if m < 7 else m - 1


class Gen4Rom:
    tm_count, hm_count, max_item = 92, 8, 536

    def __init__(self, rom, game_key):
        import randomizer as R
        self.rom = rom
        self.key = game_key
        self.p = PATHS4[game_key]
        self.personal = R.narc_spans(rom, self.p["personal"])
        self.learn = R.narc_spans(rom, self.p["learn"])
        self.evo = R.narc_spans(rom, self.p["evo"])
        self.moves = R.narc_spans(rom, self.p["moves"])

    def stats(self, s):
        o = self.personal[s][0]
        return list(self.rom[o:o + 6])

    def set_stats(self, s, v):
        o = self.personal[s][0]
        self.rom[o:o + 6] = bytes(v)

    def bst(self, s):
        return sum(self.stats(s))

    def types(self, s):
        o = self.personal[s][0]
        return to5_type(self.rom[o + 6]), to5_type(self.rom[o + 7])

    def set_types(self, s, t1, t2):
        o = self.personal[s][0]
        self.rom[o + 6], self.rom[o + 7] = to4_type(t1), to4_type(t2)

    def abilities(self, s):
        o = self.personal[s][0]
        return [self.rom[o + 22], self.rom[o + 23], 0]

    def set_abilities(self, s, a):
        o = self.personal[s][0]
        self.rom[o + 22], self.rom[o + 23] = a[0], a[1]

    def tm_bits(self, s):
        o = self.personal[s][0]
        return int.from_bytes(self.rom[o + 28:o + 41], "little") & ((1 << 100) - 1)

    def set_tm_bits(self, s, bits):
        o = self.personal[s][0]
        old = int.from_bytes(self.rom[o + 28:o + 41], "little")
        new = (old & ~((1 << 100) - 1)) | (bits & ((1 << 100) - 1))
        self.rom[o + 28:o + 41] = new.to_bytes(13, "little")

    def set_growth(self, s, v):
        self.rom[self.personal[s][0] + 19] = v

    def raise_catch_rate(self, s, v):
        o = self.personal[s][0] + 8
        self.rom[o] = max(self.rom[o], v)

    def set_held_items(self, s, items):
        struct.pack_into("<2H", self.rom, self.personal[s][0] + 12, *(list(items) + [0, 0])[:2])

    def learnset(self, s):
        start, end = self.learn[s]
        out = []
        for o in range(start, end - 1, 2):
            v = struct.unpack_from("<H", self.rom, o)[0]
            if v == 0xFFFF:
                break
            out.append([v & 0x1FF, v >> 9])
        return out

    def set_learnset(self, s, entries):
        start, _ = self.learn[s]
        for i, (mv, lv) in enumerate(entries):
            struct.pack_into("<H", self.rom, start + 2 * i, (mv & 0x1FF) | (lv << 9))

    def evolutions(self, s):
        start, _ = self.evo[s]
        out = []
        for i in range(7):
            m, p, t = struct.unpack_from("<HHH", self.rom, start + 6 * i)
            out.append([to5_method(m) if m else 0, p, t])
        return out

    def set_evo(self, s, slot, method, param, target):
        start, _ = self.evo[s]
        struct.pack_into("<HHH", self.rom, start + 6 * slot, to4_method(method) if method else 0, param, target)

    def clear_evolutions(self, s):
        start, _ = self.evo[s]
        self.rom[start:start + 42] = bytes(42)

    def set_evo_target(self, s, slot, target):
        start, _ = self.evo[s]
        struct.pack_into("<H", self.rom, start + 6 * slot + 4, target)

    def move(self, m):
        o = self.moves[m][0]
        cat = {0: 1, 1: 2, 2: 0}.get(self.rom[o + 2], 0)
        return {"type": to5_type(self.rom[o + 4]), "cat": cat, "power": self.rom[o + 3], "acc": self.rom[o + 5],
                "pp": self.rom[o + 6]}

    def set_move(self, m, d):
        o = self.moves[m][0]
        self.rom[o + 2] = {1: 0, 2: 1, 0: 2}[d["cat"]]
        self.rom[o + 3], self.rom[o + 4], self.rom[o + 5], self.rom[o + 6] = (
            d["power"], to4_type(d["type"]), d["acc"], d["pp"])


def encounter_slots(g):
    import randomizer as R
    out = []
    for table, (s, e) in enumerate(R.narc_spans(g.rom, g.p["enc"])):
        if g.p["enc_kind"] == "dp":
            if e - s < 424:
                continue
            for i in range(12):
                out.append((table, s + 8 + 8 * i, 4, [s + 4 + 8 * i], False))
            for off in range(100, 180, 4):
                out.append((table, s + off, 4, [], False))
            for base in (204, 292, 336, 380):
                for i in range(5):
                    out.append((table, s + base + 8 + 8 * i, 4, [s + base + 4 + 8 * i, s + base + 5 + 8 * i], True))
        else:
            if e - s < 196:
                continue
            for part in (20, 44, 68):
                for i in range(12):
                    out.append((table, s + part + 2 * i, 2, [s + 8 + i], False))
            for i in range(4):
                out.append((table, s + 92 + 2 * i, 2, [], False))
            for base, n, water in ((100, 5, True), (120, 2, False), (128, 5, True), (148, 5, True), (168, 5, True)):
                for i in range(n):
                    out.append((table, s + base + 2 + 4 * i, 2, [s + base + 4 * i, s + base + 1 + 4 * i], water))
            for i in range(4):
                out.append((table, s + 188 + 2 * i, 2, [], i > 0))
    return out


def randomize_wild(g, rng, opts, pool, bst, log, names, pick, type_list):
    import randomizer as R
    mode = opts["wild"]
    if mode == "off" and not opts["wildLevels"]:
        return []
    types_of = {s: set(type_list(*g.types(s))) for s in pool}
    water_pool = [s for s in pool if R.WATER in types_of[s]]
    global_map, zone_maps, themes, seen_all = {}, {}, {}, set()
    by_table, count = {}, 0
    levels_done = set()
    for table, off, size, lv_offs, water in encounter_slots(g):
        fmt = "<i" if size == 4 else "<H"
        old = struct.unpack_from(fmt, g.rom, off)[0]
        if size == 2:
            old &= 0x3FF
        if not (0 < old <= MAX_SPECIES):
            continue
        src = pool
        if opts["wildTheme"]:
            theme = themes.setdefault(table, rng.randrange(R.NUM_TYPES))
            src = [x for x in pool if theme in types_of[x]] or pool
        if water and opts["wildWater"]:
            src = [x for x in src if x in water_pool] or water_pool or src
        new = old
        if mode != "off":
            cands = [x for x in src if x not in seen_all] or src if opts["catchEmAll"] else src
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
            struct.pack_into(fmt, g.rom, off, new)
        if opts["wildLevels"]:
            for lo in lv_offs:
                if lo in levels_done:
                    continue
                levels_done.add(lo)
                if size == 4 and lo % 8 == (off - 4) % 8 and not water:
                    lv = struct.unpack_from("<i", g.rom, lo)[0]
                    struct.pack_into("<i", g.rom, lo, max(1, min(100, round(lv * (1 + opts["wildLevels"] / 100)))))
                else:
                    g.rom[lo] = max(1, min(100, round(g.rom[lo] * (1 + opts["wildLevels"] / 100))))
        by_table.setdefault(table, {})[(old, new)] = True
        count += 1
    log.append(f"Pokémon sauvages : mode {mode}, {count} emplacements"
               + (", force similaire" if opts["wildSimilar"] and mode != "off" else "")
               + (", un type par zone" if opts["wildTheme"] else "")
               + (", Eau en surf/pêche" if opts["wildWater"] else "")
               + (f", niveaux {opts['wildLevels']:+d} %" if opts["wildLevels"] else ""))
    lines = []
    for table in sorted(by_table):
        lines.append(f"  Table {table}")
        for old, new in sorted(by_table[table]):
            if old != new:
                lines.append(f"    {names(old)} -> {names(new)}")
    return lines


def class_names(g):
    try:
        banks = gen4_maps._narc_files(gen4_maps._rom_file(g.rom, g.p["msg"]))
        repo = gen4_maps.GAMES[g.key]["repo"]
    except Exception:
        return []
    for b in banks:
        try:
            strings = gen4_maps._decode_messages(repo, b)
        except Exception:
            continue
        if 60 <= len(strings) <= 200 and any(x.strip() in ("Conseil 4", "Elite Four") for x in strings) \
                and all(len(x) < 30 for x in strings):
            return [x.strip() for x in strings]
    return []


def randomize_trainers(g, rng, opts, pool, bst, log, names, pick, type_list, best_moves, moves_at_level,
                       starter_map=None, pre=None):
    import randomizer as R
    import randomizer_gen3 as R3
    touch = (opts["trainers"] != "off" or opts["trainerLevels"] or opts["fullyEvolvedAt"] or opts["betterMovesets"]
             or opts["learnsets"] == "metronome" or (starter_map and opts["rivalStarter"]))
    if not touch:
        return []
    old_lines, new_lines = {}, {}
    if starter_map and opts["rivalStarter"]:
        old_starters = list(starter_map)
        old_lines = R3._line_stage(pre or {}, old_starters)
        for i, s in enumerate(old_starters):
            chain, cur = [], starter_map[s]
            for _ in range(3):
                chain.append(cur)
                nxt = [t for m, _, t in g.evolutions(cur) if m and 0 < t <= MAX_SPECIES]
                if not nxt:
                    break
                cur = nxt[0]
            new_lines[i] = chain
    classes = class_names(g)
    pool = [x for x in pool if 25 not in g.abilities(x)[:2]] or pool
    td = R.narc_spans(g.rom, g.p["trdata"])
    tp = R.narc_spans(g.rom, g.p["trpoke"])
    types_of = {s: set(type_list(*g.types(s))) for s in pool}
    seal = 2 if g.p["seal"] else 0
    lines, count = [], 0

    def is_important(t):
        ds, de = td[t]
        if de - ds < 4:
            return False
        c = classes[g.rom[ds + 1]] if g.rom[ds + 1] < len(classes) else ""
        return c in R.IMPORTANT_CLASSES or c.startswith("Champion")
    order = list(range(1, min(len(td), len(tp))))
    if opts["e4Unique"]:
        order.sort(key=lambda t: not is_important(t))
    e4set, used_all = set(), set()
    for t in order:
        ds, de = td[t]
        if de - ds < 4:
            continue
        flags, cls, n = g.rom[ds], g.rom[ds + 1], g.rom[ds + 3]
        size = 6 + (2 if flags & 2 else 0) + (8 if flags & 1 else 0) + seal
        ps, pe = tp[t]
        if n == 0 or pe - ps < n * size:
            continue
        cname = classes[cls] if cls < len(classes) else f"classe {cls}"
        important = cname in R.IMPORTANT_CLASSES or cname.startswith("Champion")
        src, theme = pool, None
        if opts["trainers"] == "theme" or (opts["bossTheme"] and important and opts["trainers"] != "off"):
            theme = rng.randrange(R.NUM_TYPES)
            src = [x for x in pool if theme in types_of[x]] or pool
        src = R._trainer_src(src, opts, important, e4set, used_all)
        team, used = [], set()
        for k in range(n):
            o = ps + k * size
            lv = struct.unpack_from("<H", g.rom, o + 2)[0]
            raw = struct.unpack_from("<H", g.rom, o + 4)[0]
            old = raw & 0x3FF
            new = old
            if old in old_lines:
                i, stage = old_lines[old]
                new = new_lines[i][min(stage, len(new_lines[i]) - 1)]
            elif opts["trainers"] != "off" and 0 < old <= MAX_SPECIES:
                new = pick(rng, src, bst, old, opts["trainerSimilar"], used)
            if opts["trainerLevels"]:
                lv = max(1, min(100, round(lv * (1 + opts["trainerLevels"] / 100))))
                struct.pack_into("<H", g.rom, o + 2, lv)
            if opts["evolveByLevel"] and 0 < new <= MAX_SPECIES and old not in old_lines:
                new = R._evolve_for_level(g, new, lv, rng)
            if opts["fullyEvolvedAt"] and lv >= opts["fullyEvolvedAt"] and 0 < new <= MAX_SPECIES and old not in old_lines:
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
                struct.pack_into("<H", g.rom, o + 4, new)
            if flags & 1:
                mo = o + 6 + (2 if flags & 2 else 0)
                if opts["learnsets"] == "metronome":
                    struct.pack_into("<4H", g.rom, mo, R.METRONOME, 0, 0, 0)
                elif opts["betterMovesets"]:
                    struct.pack_into("<4H", g.rom, mo, *best_moves(g, new, lv))
                elif new != old or opts["learnsets"] != "off":
                    struct.pack_into("<4H", g.rom, mo, *moves_at_level(g, new, lv))
            team.append(f"{names(old)}→{names(new)} Nv{lv}" if new != old else f"{names(new)} Nv{lv}")
        count += 1
        if important:
            lines.append(f"  #{t} {cname}{' (type ' + R.TYPE_FR[theme] + ')' if theme is not None else ''} : " + ", ".join(team))
    log.append(f"Dresseurs : {opts['trainers']}, {count} dresseurs"
               + (", force similaire" if opts["trainerSimilar"] and opts["trainers"] != "off" else "")
               + (", Champions / Conseil 4 / Maître : un type chacun" if opts["bossTheme"] and opts["trainers"] != "off" else "")
               + (f", niveaux {opts['trainerLevels']:+d} %" if opts["trainerLevels"] else "")
               + (f", complètement évolués dès le Nv. {opts['fullyEvolvedAt']}" if opts["fullyEvolvedAt"] else "")
               + (", meilleures attaques (dresseurs à attaques choisies)" if opts["betterMovesets"] else "")
               + (", lignée des starters suivie" if old_lines else ""))
    return lines


def trainer_categories(g, pre):
    import randomizer as R
    import randomizer_gen3 as R3
    classes = class_names(g)
    old = STARTERS4["hgss" if g.key in ("POKEMON HG", "POKEMON SS") else "dp"]
    lines = R3._line_stage(pre, old)
    td, tp = R.narc_spans(g.rom, g.p["trdata"]), R.narc_spans(g.rom, g.p["trpoke"])
    seal = 2 if g.p["seal"] else 0
    out = {}
    for t in range(1, min(len(td), len(tp))):
        ds, de = td[t]
        if de - ds < 4:
            continue
        flags, cls, n = g.rom[ds], g.rom[ds + 1], g.rom[ds + 3]
        size = 6 + (2 if flags & 2 else 0) + (8 if flags & 1 else 0) + seal
        ps, pe = tp[t]
        species = [struct.unpack_from("<H", g.rom, ps + size * k + 4)[0] & 0x3FF for k in range(n) if ps + size * (k + 1) <= pe]
        cname = classes[cls] if cls < len(classes) else ""
        out[t] = "boss" if cname in R.IMPORTANT_CLASSES or cname.startswith("Champion") else \
            "important" if any(s in lines for s in species) else "regular"
    return out


def trainer_extras(g, rng, opts, pool, bst, cats, log, pick, best_moves, moves_at_level):
    import nds_rebuild
    import randomizer as R
    cat_key = {"boss": "Boss", "important": "Important", "regular": "Regular"}
    if not any(opts["extra" + c] for c in cat_key.values()) and not any(opts["items" + c] for c in cat_key.values()):
        return
    seal = 2 if g.p["seal"] else 0
    td = R.narc_spans(g.rom, g.p["trdata"])
    s, e = R.file_span(g.rom, g.p["trpoke"])
    members, btnf = nds_rebuild.narc_unpack(bytes(g.rom[s:e]))
    held = [i for i in R.HELD_ITEMS if i <= g.max_item]
    berries = [i for i in R.BERRIES if i <= g.max_item]
    added = items = 0
    for t in range(1, min(len(td), len(members))):
        ds, de = td[t]
        if de - ds < 4:
            continue
        flags, n = g.rom[ds], g.rom[ds + 3]
        size = 6 + (2 if flags & 2 else 0) + (8 if flags & 1 else 0) + seal
        m = members[t]
        if n == 0 or len(m) < n * size:
            continue
        mons = []
        for k in range(n):
            o = k * size
            diff, ga, lv, sp = struct.unpack_from("<BBHH", m, o)
            item = struct.unpack_from("<H", m, o + 6)[0] if flags & 2 else 0
            moves = list(struct.unpack_from("<4H", m, o + 6 + (2 if flags & 2 else 0))) if flags & 1 else None
            sl = struct.unpack_from("<H", m, o + size - 2)[0] if seal else 0
            mons.append({"diff": diff, "ga": ga, "lv": lv, "sp": sp, "item": item, "moves": moves, "seal": sl})
        cat = cat_key[cats.get(t, "regular")]
        for _ in range(max(0, min(int(opts["extra" + cat] or 0), 6 - len(mons)))):
            ref = max(mons, key=lambda d: d["lv"])
            used = {d["sp"] & 0x3FF for d in mons}
            old = ref["sp"] & 0x3FF
            sp = pick(rng, pool, bst, old if old in bst else rng.choice(pool), True, used)
            mons.append({"diff": ref["diff"], "ga": 0, "lv": ref["lv"], "sp": sp, "item": 0, "moves": None, "seal": 0})
            added += 1
        new_flags = flags
        if opts["items" + cat]:
            new_flags |= 2
            choices = berries if opts["itemsConsumable"] else held
            top = max(d["lv"] for d in mons)
            first_top = next(d for d in mons if d["lv"] == top)
            for d in mons:
                if not opts["itemsHighestOnly"] or d is first_top:
                    d["item"] = rng.choice(choices)
                    items += 1
        if new_flags & 1:
            for d in mons:
                if d["moves"] is None:
                    sp = d["sp"] & 0x3FF
                    d["moves"] = [R.METRONOME, 0, 0, 0] if opts["learnsets"] == "metronome" else \
                        best_moves(g, sp, d["lv"]) if opts["betterMovesets"] else moves_at_level(g, sp, d["lv"])
        out = bytearray()
        for d in mons:
            out += struct.pack("<BBHH", d["diff"], d["ga"], d["lv"], d["sp"])
            if new_flags & 2:
                out += struct.pack("<H", d["item"])
            if new_flags & 1:
                out += struct.pack("<4H", *d["moves"])
            if seal:
                out += struct.pack("<H", d["seal"])
        members[t] = bytes(out)
        g.rom[ds] = new_flags
        g.rom[ds + 3] = len(mons)
    where = nds_rebuild.replace_file(g.rom, g.p["trpoke"], nds_rebuild.narc_pack(members, btnf))
    parts = []
    if added:
        parts.append(f"{added} Pokémon en plus (boss {opts['extraBoss']}, importants {opts['extraImportant']}, "
                     f"autres {opts['extraRegular']})")
    if items:
        parts.append(f"{items} objets tenus" + (" (baies seulement)" if opts["itemsConsumable"] else "")
                     + (" (plus haut niveau seulement)" if opts["itemsHighestOnly"] else ""))
    log.append("Dresseurs, équipes agrandies : " + (", ".join(parts) or "rien à changer") + f" ; fichier {where}")


def make_doubles(g, opts, log):
    import randomizer as R
    if not opts["doubleBattles"]:
        return
    n = 0
    for s, e in R.narc_spans(g.rom, g.p["trdata"]):
        if e - s >= 20 and g.rom[s + 3] >= 2 and struct.unpack_from("<I", g.rom, s + 0x10)[0] == 0:
            struct.pack_into("<I", g.rom, s + 0x10, 1)
            n += 1
    log.append(f"Combats doubles : {n} dresseurs de plus (ceux qui ont au moins 2 Pokémon) (phase expérimentale)")


def shuffle_names(g, rng, opts, log):
    import nds_rebuild
    import randomizer as R
    if not opts["shuffleTrainerNames"] and not opts["shuffleClassNames"]:
        return
    path = g.p["msg"]
    span = R.file_span(g.rom, path)
    members, btnf = nds_rebuild.narc_unpack(bytes(g.rom[span[0]:span[1]]))
    n_trainers = len(R.narc_spans(g.rom, g.p["trdata"]))
    cls_bank = None
    for b in range(len(members)):
        try:
            strings = gen4_maps._decode_messages(gen4_maps.GAMES[g.key]["repo"], members[b])
        except Exception:
            continue
        if 60 <= len(strings) <= 200 and any(x.strip() in ("Conseil 4", "Elite Four") for x in strings):
            cls_bank = b
            break
    done = []
    for flag, bank, label in (("shuffleTrainerNames", None if cls_bank is None else cls_bank - 1, "dresseurs"),
                              ("shuffleClassNames", cls_bank, "classes")):
        if not opts[flag]:
            continue
        try:
            key, msgs = msg_raw(members[bank])
        except Exception:
            msgs = []
        if bank is None or (label == "dresseurs" and len(msgs) != n_trainers) or len(msgs) < 3:
            log.append(f"Noms des {label} : NON modifiés (banque introuvable)")
            continue
        rest = msgs[1:]
        rng.shuffle(rest)
        members[bank] = msg_pack(key, [msgs[0]] + rest)
        done.append(f"noms des {label} ({len(rest)})")
    if done:
        nds_rebuild.replace_file(g.rom, path, nds_rebuild.narc_pack(members, btnf))
        log.append("Mélangés : " + ", ".join(done))


STARTERS4 = {"dp": (387, 390, 393), "hgss": (152, 155, 158)}
STARTER_TABLES4 = {"POKEMON D": [63, 64], "POKEMON P": [63, 64], "POKEMON PL": [78],
                   "POKEMON HG": [None, 61], "POKEMON SS": [None, 61]}
SCRIPTS4 = {"POKEMON D": "fielddata/script/scr_seq_release.narc", "POKEMON P": "fielddata/script/scr_seq_release.narc",
            "POKEMON PL": "fielddata/script/scr_seq.narc", "POKEMON HG": "a/0/1/2", "POKEMON SS": "a/0/1/2"}


def _code(g, where):
    import nds_rebuild
    return nds_rebuild.arm9_read(g.rom)[0] if where is None else nds_rebuild.overlay_read(g.rom, where)


def randomize_starters(g, rng, opts, pool, pre, log, names):
    import nds_rebuild
    import randomizer as R
    if opts["starters"] == "off":
        return None
    old = STARTERS4["hgss" if g.key in ("POKEMON HG", "POKEMON SS") else "dp"]
    table = struct.pack("<3I", *old)
    places = []
    for where in STARTER_TABLES4[g.key]:
        d = _code(g, where)
        at = d.find(table)
        if at >= 0 and d.find(table, at + 1) < 0:
            places.append((where, at))
    if not places:
        log.append("Starters : NON modifiés (table de l'écran de choix non trouvée)")
        return None
    if opts["starters"] == "custom":
        chosen = [int(x) for x in opts["starterList"][:3] if str(x).strip()]
        if len(chosen) != 3 or any(not (1 <= c <= MAX_SPECIES) for c in chosen):
            raise ValueError("Starters choisis : il faut 3 Pokémon de la 4G (n° 1 à 493)")
    else:
        evolves = {s: [t for m, _, t in g.evolutions(s) if m and 0 < t <= MAX_SPECIES] for s in range(1, MAX_SPECIES + 1)}
        basics = [s for s in pool if s not in pre and evolves[s] and s not in old]
        if opts["starter3stage"]:
            basics = [s for s in basics if any(evolves[t] for t in evolves[s])] or basics
        if opts["starters"] == "randomAny":
            basics = [s for s in pool if s not in old]
        chosen = R._three_starters(rng, basics, g.types, opts["starterTypes"])
    mapping = dict(zip(old, chosen))
    for where, at in places:
        nds_rebuild.code_set_bytes(g.rom, where, at, struct.pack("<3I", *chosen))
    sites = 0
    for s, e in R.narc_spans(g.rom, SCRIPTS4[g.key]):
        f = g.rom[s:e]
        for o in range(4, len(f) - 1):
            v = struct.unpack_from("<H", f, o)[0]
            cmd = f[o - 4] | (f[o - 3] << 8)
            if v in mapping and f[o - 1] == 0x80 and cmd in (0x11, 0x28, 0x29, 0x1C0):
                struct.pack_into("<H", g.rom, s + o, mapping[v])
                sites += 1
    shown = _starter_sprites(g, old, chosen)
    texts = _starter_texts(g, old, chosen)
    log.append("Starters : " + ", ".join(f"{names(o)} -> {names(n)}" for o, n in mapping.items())
               + f" ({len(places)} table(s) de l'écran de choix, {sites} comparaisons de script, images de l'écran : "
               + ("oui" if shown else "table ARM9" if g.key in ("POKEMON HG", "POKEMON SS") else "NON") + f", {texts} texte(s) de l'écran)")
    return mapping


SPRITE_CODE4 = {"POKEMON D": 64, "POKEMON P": 64, "POKEMON PL": 78}


def _sprite_block(x, sp):
    if sp < 256:
        hw = [0x2200 | x, 0x0092, 0x18A8, 0x1C29, 0x2200 | sp]
    elif x <= sp <= x + 255:
        hw = [0x2200 | x, 0x0090, 0x1940, 0x1C29, 0x3200 | (sp - x)]
    else:
        d = sp - 4 * x
        if not -255 <= d <= 255:
            raise ValueError(f"espèce {sp} hors de portée")
        hw = [0x2200 | x, 0x0092, 0x18A8, 0x1C29, (0x3200 | d) if d >= 0 else (0x3A00 | -d)]
    return struct.pack("<5H", *hw)


def _starter_sprites(g, old, chosen):
    import nds_rebuild
    ov = SPRITE_CODE4.get(g.key)
    if ov is None:
        return False
    d = _code(g, ov)
    blocks = [_sprite_block(0x81 + i, sp) for i, sp in enumerate(old)]
    at = d.find(blocks[0])
    if at < 0 or d.find(blocks[0], at + 1) >= 0 or any(d[at + 14 * i:at + 14 * i + 10] != blocks[i] for i in range(3)):
        return False
    for i, sp in enumerate(chosen):
        nds_rebuild.code_set_bytes(g.rom, ov, at + 14 * i, _sprite_block(0x81 + i, sp))
    return True


TEXTS4 = {"POKEMON D": ("msgdata/msg.narc", 320), "POKEMON P": ("msgdata/msg.narc", 320),
          "POKEMON PL": ("msgdata/pl_msg.narc", 360), "POKEMON HG": ("a/0/2/7", 190), "POKEMON SS": ("a/0/2/7", 190)}


def msg_raw(data):
    count, key = struct.unpack_from("<HH", data, 0)
    out = []
    for i in range(1, count + 1):
        ak = (765 * i * key) & 0xFFFF
        ak |= ak << 16
        off, ln = struct.unpack_from("<II", data, 4 + 8 * (i - 1))
        off ^= ak
        ln ^= ak
        ck = (i * 596947) & 0xFFFF
        cs = []
        for j in range(ln):
            cs.append(struct.unpack_from("<H", data, off + 2 * j)[0] ^ ck)
            ck = (ck + 18749) & 0xFFFF
        out.append(cs)
    return key, out


def msg_pack(key, msgs):
    head = bytearray(struct.pack("<HH", len(msgs), key))
    body = bytearray()
    off = 4 + 8 * len(msgs)
    for i, cs in enumerate(msgs, 1):
        ak = (765 * i * key) & 0xFFFF
        ak |= ak << 16
        head += struct.pack("<II", (off + len(body)) ^ ak, len(cs) ^ ak)
        ck = (i * 596947) & 0xFFFF
        for c in cs:
            body += struct.pack("<H", c ^ ck)
            ck = (ck + 18749) & 0xFFFF
    return bytes(head + body)


def _replace_seq(cs, a, b, after_space=False):
    out, i, n = [], 0, 0
    while i < len(cs):
        if a and cs[i:i + len(a)] == a and (not after_space or (out and out[-1] == 478)):
            out += b
            i += len(a)
            n += 1
        else:
            out.append(cs[i])
            i += 1
    return out, n


def _starter_texts(g, old, chosen):
    import nds_rebuild
    path, bank = TEXTS4[g.key]
    span = nds_rebuild._fat(g.rom)[1][nds_rebuild.file_id(g.rom, path)]
    members, btnf = nds_rebuild.narc_unpack(bytes(g.rom[span[0]:span[1]]))
    raws = {}

    def bank_raw(b):
        if b not in raws:
            try:
                raws[b] = msg_raw(members[b])[1]
            except Exception:
                raws[b] = []
        return raws[b]

    key, msgs = msg_raw(members[bank])
    big = [b for b in range(len(members)) if len(bank_raw(b)) >= 494]
    names = next((b for b in big if all(any(_replace_seq(m, bank_raw(b)[s][:-1], [])[1] for m in msgs) for s in old)), None)
    if names is None:
        return 0
    name = lambda s: bank_raw(names)[s][:-1]
    cats = next((b for b in big if b != names and all(bank_raw(b)[s][:-1] and not _replace_seq(
        bank_raw(b)[s][:-1], name(s), [])[1] and any(_replace_seq(m, bank_raw(b)[s][:-1], [])[1] for m in msgs)
        for s in old)), None)
    tnames = None
    if g.key in ("POKEMON HG", "POKEMON SS"):
        inv = {}
        for c, ch in gen4_maps._charmap().items():
            inv.setdefault(ch, c)
        words = ["Normal", "Combat", "Vol", "Poison", "Sol", "Roche", "Insecte", "Spectre", "Acier", "???",
                 "Feu", "Eau", "Plante", "Electrik", "Psy", "Glace", "Dragon", "Ténèbres"]
        if all(ch in inv for w in words for ch in w):
            tnames = [[inv[ch] for ch in w] for w in words]
    orig_type = {152: 12, 155: 10, 158: 11}
    changed = 0
    for i, m in enumerate(msgs):
        new = m
        for o, n in zip(old, chosen):
            new, hit = _replace_seq(new, name(o), name(n))
            if not hit:
                continue
            if cats is not None:
                new, _ = _replace_seq(new, bank_raw(cats)[o][:-1], bank_raw(cats)[n][:-1])
            if tnames is not None and o in orig_type:
                nt = to4_type(g.types(n)[0])
                new, _ = _replace_seq(new, tnames[orig_type[o]], tnames[nt], after_space=True)
            break
        if new != m:
            msgs[i] = new
            changed += 1
    if changed:
        members[bank] = msg_pack(key, msgs)
        nds_rebuild.replace_file(g.rom, path, nds_rebuild.narc_pack(members, btnf))
    return changed


EVENT_OPS4 = {"dp": {"gift": 0x96, "egg": 0x97, "wild": (0x124, 0x2BD)}, "hgss": {"gift": 0x89, "egg": 0x8A, "wild": (0x24D,)}}
STATICS4 = {"POKEMON PL": {(480, 50), (493, 80), (378, 30), (379, 30), (491, 50), (377, 30), (486, 1), (483, 70), (484, 70),
                           (485, 50), (487, 47), (425, 15), (482, 50), (479, 20), (442, 25)},
            "POKEMON D": {(425, 22), (493, 80), (485, 70), (487, 70), (492, 30), (486, 70), (482, 50), (480, 50), (491, 40),
                          (479, 15), (442, 25)},
            "POKEMON HG": {(144, 50), (101, 23), (383, 50), (130, 30), (382, 50), (131, 20), (150, 70), (146, 50), (384, 50),
                           (143, 50), (185, 20), (245, 40), (145, 50)}}
STATICS4["POKEMON P"] = STATICS4["POKEMON D"]
STATICS4["POKEMON SS"] = STATICS4["POKEMON HG"]
GIFTS4 = {"POKEMON PL": {(133, 20), (137, 25)}, "POKEMON D": {(133, 5)},
          "POKEMON HG": {(236, 10), (147, 15), (483, 1), (484, 1), (487, 1), (72, 15), (133, 5)}}
GIFTS4["POKEMON P"] = GIFTS4["POKEMON D"]
GIFTS4["POKEMON SS"] = GIFTS4["POKEMON HG"]
EGGS4 = {"POKEMON PL": (175, 447), "POKEMON D": (440, 447), "POKEMON P": (440, 447), "POKEMON HG": (179, 194, 218),
         "POKEMON SS": (179, 194, 218)}
TRADES4 = {"POKEMON D": "resource/fra/pokemon_trade/fld_trade.narc", "POKEMON P": "resource/fra/pokemon_trade/fld_trade.narc",
           "POKEMON PL": "resource/fra/pokemon_trade/fld_trade.narc", "POKEMON HG": "a/1/1/2", "POKEMON SS": "a/1/1/2"}
LANG_DIRS4 = ("fra", "eng", "ger", "ita", "spa", "jpn", "kor")


def trade_path4(rom, key):
    import randomizer as R
    path = TRADES4[key]
    if "/fra/" not in path:
        return path
    for lang in LANG_DIRS4:
        cand = path.replace("/fra/", f"/{lang}/")
        try:
            R.file_span(rom, cand)
            return cand
        except KeyError:
            continue
    return path
TM_ITEMS4 = range(328, 420)


def _event_sites(g, kind, pairs):
    import randomizer as R
    ops = EVENT_OPS4["hgss" if g.key in ("POKEMON HG", "POKEMON SS") else "dp"][kind]
    ops = ops if isinstance(ops, tuple) else (ops,)
    out = {}
    for s, e in R.narc_spans(g.rom, SCRIPTS4[g.key]):
        f = bytes(g.rom[s:e])
        for op in ops:
            for sp, lv in pairs:
                pat = struct.pack("<HH", op, sp) + (struct.pack("<H", lv) if lv is not None else b"")
                o = 0
                while (o := f.find(pat, o)) >= 0:
                    out[s + o + 2] = (sp, lv)
                    o += 1
    return out


def _item_sites(g):
    import randomizer as R
    op = 0x29 if g.key in ("POKEMON HG", "POKEMON SS") else 0x28
    best = []
    for s, e in R.narc_spans(g.rom, SCRIPTS4[g.key]):
        f = bytes(g.rom[s:e])
        hits, o = [], 0
        while (o := f.find(bytes([op, 0, 8, 0x80]), o)) >= 0:
            if f[o + 6:o + 10] == bytes([op, 0, 9, 0x80]) and 0 < struct.unpack_from("<H", f, o + 4)[0] <= 536:
                hits.append(s + o + 4)
            o += 1
        if len(hits) > len(best):
            best = hits
    return best if len(best) >= 200 else []


FOSSIL_TABLE4 = struct.pack("<14H", 103, 142, 101, 138, 102, 140, 99, 345, 100, 347, 104, 410, 105, 408)


def _fossil_table(g):
    for where in ([None] if g.key not in ("POKEMON HG", "POKEMON SS") else [21]):
        d = _code(g, where)
        if d.count(FOSSIL_TABLE4) == 1:
            return where, d.find(FOSSIL_TABLE4)
    return None, None


SHOPS4 = {
    "POKEMON PL": (29, (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 25, 26, 27, 28), ([146, 14], [142, 11])),
    "POKEMON D": (28, (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 14, 24, 25, 26, 27), ([142, 11], [146, 14])),
    "POKEMON P": (28, (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 14, 24, 25, 26, 27), ([142, 11], [146, 14])),
    "POKEMON HG": (40, (0, 2, 5, 6, 7, 12, 14, 16, 19, 31, 33, 34, 36), ([146, 14], [146, 15])),
}
SHOPS4["POKEMON SS"] = SHOPS4["POKEMON HG"]
HIDDEN4 = {"POKEMON PL": 257, "POKEMON D": 229, "POKEMON P": 229, "POKEMON HG": 231, "POKEMON SS": 231}
MAIL_ITEMS4 = range(135, 149)


def _shop_lists4(g):
    import nds_rebuild
    if g.key not in SHOPS4:
        return []
    n, _, first = SHOPS4[g.key]
    a9 = bytes(nds_rebuild.arm9_read(g.rom)[0])
    pat = b"".join(struct.pack(f"<{len(x)}H", *x) + b"\xff\xff" for x in first)
    if a9.count(pat) != 1:
        return []
    o, out = a9.find(pat), []
    while len(out) < n and o + 2 <= len(a9):
        if a9[o:o + 2] == b"\0\0" and a9[o + 2:o + 4] != b"\xff\xff":
            o += 2
            continue
        q = o
        while q + 2 <= len(a9) and a9[q:q + 2] != b"\xff\xff" and (q - o) < 64:
            q += 2
        if a9[q:q + 2] != b"\xff\xff":
            return []
        out.append((o, list(struct.unpack_from(f"<{(q - o) // 2}H", a9, o))))
        o = q + 2
    return out if len(out) == n else []


def _hidden_items4(g):
    import nds_rebuild
    import numpy as np
    if g.key not in HIDDEN4:
        return []
    n = HIDDEN4[g.key]
    a9 = bytes(nds_rebuild.arm9_read(g.rom)[0])
    found = []
    for phase in range(4):
        u = np.frombuffer(a9, dtype="<u2", count=(len(a9) // 2 - phase) // 4 * 4, offset=2 * phase).reshape(-1, 4)
        ok = (u[:, 0] >= 1) & (u[:, 0] <= 467) & (u[:, 2] == 0) & (u[:, 3] < 1024) & (u[:, 1] < 0x400)
        i = 0
        while i < len(ok):
            if not ok[i]:
                i += 1
                continue
            j = i
            while j < len(ok) and ok[j]:
                j += 1
            for r0 in range(i, j - n + 1):
                if len(np.unique(u[r0:r0 + n, 3])) == n:
                    found.append(2 * phase + 8 * r0)
                    break
            i = j
    return [found[0] + 8 * k for k in range(n)] if len(found) == 1 else []


def randomize_events(g, rng, opts, pool, bst, pre, log, names, pick):
    import randomizer as R
    lines = []
    if opts["statics"] != "off":
        sites = _event_sites(g, "wild", STATICS4[g.key])
        legend_pool = [s for s in range(1, MAX_SPECIES + 1) if s in R.LEGENDARIES]
        mapping = {}
        if g.key in ("POKEMON HG", "POKEMON SS"):
            for s_, e_ in R.narc_spans(g.rom, SCRIPTS4[g.key]):
                f = bytes(g.rom[s_:e_])
                for sp in (249, 250):
                    pat = struct.pack("<HHH", 0x29, 0x400A, sp)
                    o = 0
                    while (o := f.find(pat, o)) >= 0:
                        sites[s_ + o + 4] = (sp, None)
                        o += 1
        for off, (sp, lv) in sorted(sites.items()):
            if sp not in mapping:
                if opts["statics"] == "swap" and sp in R.LEGENDARIES:
                    mapping[sp] = pick(rng, legend_pool, bst, sp, True, set(mapping.values()) | {sp})
                else:
                    mapping[sp] = pick(rng, [x for x in pool if x not in R.LEGENDARIES] or pool, bst, sp, True,
                                       set(mapping.values()))
            struct.pack_into("<H", g.rom, off, mapping[sp])
        log.append(f"Pokémon fixes : {len(sites)} combats, {len(mapping)} espèces"
                   + (" (légendaires ↔ légendaires)" if opts["statics"] == "swap" else " (force similaire)")
                   + " ; le Pokémon visible sur la carte garde son apparence")
        lines += [f"  {names(a)} -> {names(b)}" for a, b in mapping.items()]
    if opts["gifts"] != "off":
        sites = _event_sites(g, "gift", GIFTS4[g.key])
        mapping = {}
        for off, (sp, lv) in sorted(sites.items()):
            if sp not in mapping:
                mapping[sp] = pick(rng, pool, bst, sp, opts["giftSimilar"], set(mapping.values()))
            struct.pack_into("<H", g.rom, off, mapping[sp])
        log.append(f"Pokémon offerts : {len(mapping)} espèces changées (les dialogues citent encore les anciennes)")
        lines += [f"  {names(a)} -> {names(b)} (offert)" for a, b in mapping.items()]
    if opts["eggs"] != "off":
        sites = _event_sites(g, "egg", {(sp, None) for sp in EGGS4[g.key]})
        basics = [s for s in pool if s not in pre]
        for off, (sp, _) in sorted(sites.items()):
            new = rng.choice(basics)
            struct.pack_into("<H", g.rom, off, new)
            lines.append(f"  œuf {names(sp)} -> {names(new)}")
        log.append(f"Œufs offerts : {len(sites)} changé(s) (Pokémon de base)")
    if opts["fossils"] != "off":
        where, off = _fossil_table(g)
        if off is None:
            log.append("Fossiles : NON modifiés (table introuvable)")
        else:
            import nds_rebuild
            pairs = list(struct.unpack_from("<14H", _code(g, where), off))
            used = set()
            for i in range(1, 14, 2):
                old = pairs[i]
                pairs[i] = pick(rng, pool, bst, old, opts["fossilSimilar"], used)
                used.add(pairs[i])
                lines.append(f"  fossile {names(old)} -> {names(pairs[i])}")
            nds_rebuild.code_set_bytes(g.rom, where, off, struct.pack("<14H", *pairs))
            log.append("Fossiles : 7 Pokémon ressuscités aléatoires" + (" (force similaire)" if opts["fossilSimilar"] else ""))
    if opts["trades"] != "off":
        n = 0
        try:
            spans = R.narc_spans(g.rom, trade_path4(g.rom, g.key))
        except KeyError:
            spans = []
            log.append("Échanges : NON modifiés (fichier introuvable)")
        for s, e in spans:
            if e - s < 0x50:
                continue
            got, asked = struct.unpack_from("<I", g.rom, s)[0], struct.unpack_from("<I", g.rom, s + 0x4C)[0]
            if not (1 <= got <= MAX_SPECIES and 1 <= asked <= MAX_SPECIES):
                continue
            new_got = pick(rng, pool, bst, got, False)
            struct.pack_into("<I", g.rom, s, new_got)
            new_asked = asked
            if opts["trades"] == "both":
                new_asked = pick(rng, pool, bst, asked, False, {new_got})
                struct.pack_into("<I", g.rom, s + 0x4C, new_asked)
            lines.append(f"  échange : {names(asked)} -> {names(new_asked)} contre {names(got)} -> {names(new_got)}")
            n += 1
        log.append(f"Échanges en jeu : {n} " + ("(Pokémon reçus et demandés)" if opts["trades"] == "both" else "(Pokémon reçus)"))
    if opts["fieldItems"] != "off":
        items = _item_sites(g)
        hidden = _hidden_items4(g)
        if not items:
            log.append("Pas encore disponible pour ce jeu (ignoré) : objets au sol")
        else:
            cur = [struct.unpack_from("<H", g.rom, o)[0] for o in items]
            if opts["fieldItems"] == "shuffle":
                new = cur[:]
                rng.shuffle(new)
            else:
                pool_items = sorted({it for it in cur if it not in TM_ITEMS4})
                new = [rng.choice(list(TM_ITEMS4)) if it in TM_ITEMS4 else rng.choice(pool_items) for it in cur]
            for o, it in zip(items, new):
                struct.pack_into("<H", g.rom, o, it)
            log.append(f"Objets au sol : {len(items)} " + ("mélangés" if opts["fieldItems"] == "shuffle" else
                                                         "aléatoires (parmi les objets au sol du jeu ; les CT restent des CT)"))
        if hidden:
            import nds_rebuild
            a9 = bytes(nds_rebuild.arm9_read(g.rom)[0])
            cur = [struct.unpack_from("<H", a9, o)[0] for o in hidden]
            if opts["fieldItems"] == "shuffle":
                new = cur[:]
                rng.shuffle(new)
            else:
                pool_items = sorted({it for it in cur if it not in TM_ITEMS4 and it < 420})
                new = [it if it >= 420 else rng.choice(list(TM_ITEMS4)) if it in TM_ITEMS4 else rng.choice(pool_items) for it in cur]
            buf = bytearray(a9[hidden[0]:hidden[-1] + 2])
            for o, it in zip(hidden, new):
                struct.pack_into("<H", buf, o - hidden[0], it)
            nds_rebuild.code_set_bytes(g.rom, None, hidden[0], bytes(buf))
            log.append(f"Objets cachés : {len(hidden)} " + ("mélangés" if opts["fieldItems"] == "shuffle" else
                                                          "aléatoires (les CT restent des CT)"))
    if opts["shops"] != "off":
        import nds_rebuild
        shops = _shop_lists4(g)
        if not shops:
            log.append("Pas encore disponible pour ce jeu (ignoré) : magasins")
        else:
            main = SHOPS4[g.key][1]
            keep = lambda it: it in TM_ITEMS4 or it >= 420 or it == 4
            pool_items = sorted({it for i in main for it in shops[i][1] if not keep(it) and it not in MAIL_ITEMS4})
            changed = 0
            lists = {i: list(shops[i][1]) for i in main}
            if opts["shops"] == "shuffle":
                slots = [(i, k) for i in main for k, it in enumerate(lists[i]) if not keep(it)]
                vals = [lists[i][k] for i, k in slots]
                rng.shuffle(vals)
                for (i, k), v in zip(slots, vals):
                    lists[i][k] = v
                for i in main:
                    for k in range(len(lists[i])):
                        if lists[i].index(lists[i][k]) != k and not keep(lists[i][k]):
                            free = [x for x in pool_items if x not in lists[i]]
                            if free:
                                lists[i][k] = rng.choice(free)
            else:
                for i in main:
                    for k, it in enumerate(lists[i]):
                        if not keep(it):
                            free = [x for x in pool_items if x not in lists[i]]
                            if free:
                                lists[i][k] = rng.choice(free)
            a9 = bytes(nds_rebuild.arm9_read(g.rom)[0])
            lo, hi = shops[0][0], shops[-1][0] + 2 * len(shops[-1][1])
            buf = bytearray(a9[lo:hi])
            for i in main:
                for k, it in enumerate(lists[i]):
                    at = shops[i][0] + 2 * k - lo
                    if struct.unpack_from("<H", buf, at)[0] != it:
                        struct.pack_into("<H", buf, at, it)
                        changed += 1
            nds_rebuild.code_set_bytes(g.rom, None, lo, bytes(buf))
            log.append(f"Magasins : {len(main)} boutiques du jeu, {changed} objets changés (CT et Poké Balls gardés) - "
                       + ("mélangés" if opts["shops"] == "shuffle" else "parmi les objets vendus dans le jeu"))
    return lines


TUTOR_FILE_HGSS = "fielddata/wazaoshie/waza_oshie.bin"


def _tutor_layout(g):
    import nds_rebuild
    if g.key == "POKEMON PL":
        d = nds_rebuild.overlay_read(g.rom, 5)
        for o in range(0, len(d) - 40, 2):
            if struct.unpack_from("<3H", d, o)[0] == 291 and struct.unpack_from("<H", d, o + 12)[0] == 189 \
                    and struct.unpack_from("<H", d, o + 24)[0] == 210:
                return 5, o, 38, 12, "code", o + 38 * 12, 5
    elif g.key in ("POKEMON HG", "POKEMON SS"):
        d = nds_rebuild.overlay_read(g.rom, 1)
        for o in range(0, len(d) - 16, 2):
            if struct.unpack_from("<H", d, o)[0] == 291 and d[o + 2] == 40 and struct.unpack_from("<H", d, o + 4)[0] == 189 \
                    and d[o + 6] == 32:
                return 1, o, 52, 4, "file", None, 8
    return None


def randomize_tutors(g, rng, opts, log, tm_labels=None):
    import nds_rebuild
    import randomizer as R
    if opts["tutorMoves"] == "off" and opts["tutorCompat"] == "off" and not opts["tutorSanity"]:
        return
    lay = _tutor_layout(g)
    if not lay:
        log.append("Tuteurs : aucun dans ce jeu" if g.key in ("POKEMON D", "POKEMON P") else "Tuteurs : NON modifiés (table introuvable)")
        return
    ov, off, n, stride, kind, coff, width = lay
    code = bytearray(nds_rebuild.overlay_read(g.rom, ov))
    moves = [struct.unpack_from("<H", code, off + stride * i)[0] for i in range(n)]
    if opts["tutorMoves"] == "random":
        banned = {R.STRUGGLE} | (R.GAME_BREAKING_MOVES if opts["noGameBreaking"] else set()) | set((tm_labels or {}).values())
        pool = [m for m in range(1, MAX_MOVE + 1) if m not in banned]
        data = {m: g.move(m) for m in pool}
        good = [m for m in pool if data[m]["cat"] != 0 and data[m]["power"] >= 70]
        pct = max(0, min(100, int(opts["goodDamaging"] or 0)))
        used = set()
        for i in range(n):
            src = good if pct and rng.random() * 100 < pct else pool
            src = [m for m in src if m not in used] or [m for m in pool if m not in used]
            moves[i] = rng.choice(src)
            used.add(moves[i])
            struct.pack_into("<H", code, off + stride * i, moves[i])
    if kind == "file":
        span = R.file_span(g.rom, TUTOR_FILE_HGSS)
        get = lambda s: (span[0] + width * (s - 1))
        buf = g.rom
    else:
        get = lambda s: (coff + width * (s - 1))
        buf = code
    types = {m: g.move(m)["type"] for m in moves}
    index = {m: i for i, m in enumerate(moves)}
    full = (1 << n) - 1
    for s in range(1, MAX_SPECIES + 1):
        o = get(s)
        bits = int.from_bytes(buf[o:o + width], "little")
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
        buf[o:o + width] = (bits & ((1 << (8 * width)) - 1)).to_bytes(width, "little")
    old = nds_rebuild.overlay_read(g.rom, ov)
    first = next((i for i in range(len(code)) if code[i] != old[i]), None)
    if first is not None:
        last = max(i for i in range(len(code)) if code[i] != old[i])
        nds_rebuild.code_set_bytes(g.rom, ov, first, bytes(code[first:last + 1]))
    log.append(f"Tuteurs ({n}) : " + ", ".join(x for x, on in (
        ("attaques aléatoires (les dialogues citent encore les anciennes)", opts["tutorMoves"] == "random"),
        ({"random": "compatibilité aléatoire (même nombre)", "type": "compatibilité aléatoire, types du Pokémon privilégiés",
          "all": "tous compatibles"}.get(opts["tutorCompat"], ""), opts["tutorCompat"] != "off"),
        ("attaques apprises par niveau compatibles", opts["tutorSanity"])) if on))


TM_ORDER4 = [f"CT{i:02d}" for i in range(1, 93)] + [f"CS{i:02d}" for i in range(1, 9)]


def randomize_tm_moves(g, rng, opts, log, base):
    import nds_rebuild
    import randomizer as R
    if opts["tmMoves"] == "off" or not base:
        return None
    a9 = nds_rebuild.arm9_read(g.rom)[0]
    off = R._tm_table(a9, base)
    if off is None:
        log.append("CT : NON modifiées (table introuvable)")
        return None
    labels = dict(zip(TM_ORDER4, struct.unpack_from("<100H", a9, off)))
    hm_moves = {labels[k] for k in labels if k.startswith("CS")}
    keep = {k for k in labels if k.startswith("CS") or (opts["keepFieldTMs"] and k in ("CT28", "CT70"))}
    banned = {R.STRUGGLE} | hm_moves | (R.GAME_BREAKING_MOVES if opts["noGameBreaking"] else set())
    used = {labels[k] for k in keep}
    pool = [m for m in range(1, MAX_MOVE + 1) if m not in banned and m not in used]
    moves = {m: g.move(m) for m in pool}
    good = [m for m in pool if moves[m]["cat"] != 0 and moves[m]["power"] >= 70]
    pct = max(0, min(100, int(opts["goodDamaging"] or 0)))
    for k in TM_ORDER4:
        if k in keep:
            continue
        src = good if pct and rng.random() * 100 < pct else pool
        src = [m for m in src if m not in used] or [m for m in pool if m not in used]
        labels[k] = rng.choice(src)
        used.add(labels[k])
    nds_rebuild.code_set_bytes(g.rom, None, off, struct.pack("<100H", *[labels[k] for k in TM_ORDER4]))
    log.append("Attaques des CT : aléatoires (CS gardées" + (", Tunnel/Flash gardées" if opts["keepFieldTMs"] else "") + ")")
    return labels
