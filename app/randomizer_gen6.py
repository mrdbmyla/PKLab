import io
import json
import os
import random
import shutil
import struct

import ctr_rom
import i18n
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
             "gifts", "giftSimilar"}
TRAINERS = {"XY": {"data": "a/0/3/8", "poke": "a/0/4/0", "count": 3, "cls": 1, "text": "a/0/7/5", "names": 20},
            "ORAS": {"data": "a/0/3/6", "poke": "a/0/3/8", "count": 7, "cls": 2, "text": "a/0/7/4", "names": 21}}
LEARNSETS = {"XY": "a/2/1/4", "ORAS": "a/1/9/1"}
STARTERS = {"XY": (650, 653, 656), "ORAS": (252, 255, 258)}
GIFT_SIZE = {"XY": 0x18, "ORAS": 0x24}
FIELD = "DllField.cro"
SELECT = "DllPoke3Select.cro"
BOSS_WORDS = ("Champion", "Conseil 4", "Boss Team", "Leader Team")
LEVEL_METHODS = {4, 9, 10, 11, 12, 13, 14, 23, 24}


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
    shutil.copyfile(src, dst)
    try:
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
            blob = ctr_rom.garc(fs.read(ppath))[-1]
            self.personal = {s: blob[psize * s:psize * (s + 1)] for s in range(1, MAX_SPECIES + 1)}
            self.evos = ctr_rom.garc(fs.read(EVOLUTION[self.family]))
            z = ZONES[self.family]
            self.zone_garc = fs.read(z["garc"])
            names = ctr_rom.text(ctr_rom.garc(fs.read(z["text"]))[z["names"]])
            t = TRAINERS[self.family]
            self.tr_data = ctr_rom.garc(fs.read(t["data"]))
            self.tr_poke_garc = fs.read(t["poke"])
            self.class_names = ctr_rom.text(ctr_rom.garc(fs.read(t["text"]))[t["names"]])
            self.learn = ctr_rom.garc(fs.read(LEARNSETS[self.family]))
            self.field = bytearray(fs.read(FIELD))
            self.select = bytearray(fs.read(SELECT)) if SELECT in fs.files else bytearray()
            self.at = {n: fs.files[n] for n in (z["garc"], t["poke"], FIELD, SELECT) if n in fs.files}
        finally:
            fs.close()
        self.zone_at = self.at[z["garc"]]
        self.tr_poke = ctr_rom.garc(self.tr_poke_garc)
        self.gift_offsets = self._gifts()
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


def _gifts(g, rng, opts, pool, bst, log, names, pick):
    if opts["gifts"] == "off" or len(g.gift_offsets) <= 3:
        return []
    lines = []
    for o in g.gift_offsets[3:]:
        old = struct.unpack_from("<H", g.field, o)[0]
        new = pick(rng, pool, bst, old, opts["giftSimilar"])
        struct.pack_into("<H", g.field, o, new)
        g.field[o + 4] = 0
        lines.append(f"  {names(old)} -> {names(new)} Nv{g.field[o + 5]}")
    log.append(f"Pokémon offerts : {len(lines)} changés" + (", force similaire" if opts["giftSimilar"] else ""))
    return lines


def _trainers(g, rng, opts, pool, bst, log, names, pick, starter_map, R):
    touch = (opts["trainers"] != "off" or opts["trainerLevels"] or opts["fullyEvolvedAt"] or opts["betterMovesets"]
             or (starter_map and opts["rivalStarter"]))
    if not touch:
        return None, []
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
    if new_poke == g.tr_poke:
        return None, lines
    return ctr_rom.garc_build(g.tr_poke_garc, new_poke), lines


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
    bst = {s: g.bst(s) for s in range(1, MAX_SPECIES + 1)}
    log = []
    field0 = bytes(g.field)
    select0 = bytes(g.select)
    try:
        starters = _starters(g, rng, opts, pool, pre, log, names, R)
        garc, wild_log, wild_lines = _wild(g, rng, opts, pool, bst, names, pick, R)
        log.append(wild_log)
        tr_garc, trainer_lines = _trainers(g, rng, opts, pool, bst, log, names, pick, starters, R)
        gift_lines = _gifts(g, rng, opts, pool, bst, log, names, pick)
    finally:
        R._STAGE.clear()
    files = {}
    if garc is not None:
        files[ZONES[g.family]["garc"]] = garc
    if tr_garc is not None:
        files[TRAINERS[g.family]["poke"]] = tr_garc
    if bytes(g.field) != field0:
        files[FIELD] = bytes(g.field)
    if bytes(g.select) != select0:
        files[SELECT] = bytes(g.select)
    skipped = sorted({randomizer_gen2.UNSUPPORTED.get(k, {"trainers": "dresseurs", "starters": "starters"}.get(k, k))
                      for k in R.DEFAULTS if k not in SUPPORTED and opts.get(k) != R.DEFAULTS[k]
                      and opts.get(k) not in ("off", False, 0, None, [])})
    if skipped:
        log.append("Pas encore disponible en 6G (ignoré) : " + ", ".join(skipped))
    if not files:
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
    import shiny_patch
    t = shiny_patch.side_threshold(src_path)
    if t != 8:
        fiche["shinyThreshold"] = t
    ips = src_path + ".exefsdir"
    if os.path.isdir(ips):
        shutil.copytree(ips, out_path + ".exefsdir")
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
    if wild_lines:
        f.write("\nPokémon sauvages\n" + "\n".join(wild_lines) + "\n")
    with open(report_path, "w", encoding="utf-8") as out:
        out.write(i18n.tr_lines(f.getvalue()))
    return out_path, report_path, {"seed": seed, "game": g.game, "changes": log,
                                   "starters": [names(x) for x in starters.values()] if starters else None, "tid": f"{tid:016X}"}
