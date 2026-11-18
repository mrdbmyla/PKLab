import io
import json
import os
import random
import shutil
import struct

import ctr_maps
import ctr_rom
import i18n
import rom_finder
import randomizer_gen6 as G6

NUM_TYPES = 18
WATER = 10
FAMILY = {"POKEMON S": "SM", "POKEMON M": "SM", "POKEMON US": "USUM", "POKEMON UM": "USUM"}
MAX = {"SM": 802, "USUM": 807}
LEGENDARIES_7 = {*range(716, 722), 772, 773, *range(785, 808)}
GARCS = {"SM": {"personal": "a/0/1/7", "evo": "a/0/1/4", "learn": "a/0/1/3", "trdata": "a/1/0/5", "trpoke": "a/1/0/6",
                "static": "a/1/5/5", "classes": 106},
         "USUM": {"personal": "a/0/1/7", "evo": "a/0/1/4", "learn": "a/0/1/3", "trdata": "a/1/0/6", "trpoke": "a/1/0/7",
                  "static": "a/1/5/9", "classes": 111}}
AREAS = ("a/0/8/2", "a/0/8/3")
STARTERS = (722, 725, 728)
STORY = {"SM": (41, 55, 107), "USUM": (39, 60, 112)}
DOTS = [0x2E, 0x2E, 0x2E, 0]
GIFT = 0x14
TRPOKE = 0x20
WATER_KINDS = {4, 6}
BOSS_WORDS = ("Capitaine", "Doyen", "Conseil 4", "Boss Team", "Présidente", "Professeur Pokémon", "Admin Team")
LEVEL_METHODS = {4, 9, 10, 11, 12, 13, 14, 23, 24}
SUPPORTED = G6.SUPPORTED


class Garc:
    def __init__(self, fs, name):
        self.name = name
        self.base, self.size = fs.files[name]
        head = fs._read(self.base, 0x1C)
        if head[:4] != b"CRAG":
            raise ValueError(f"GARC invalide ({name})")
        hsize = struct.unpack_from("<I", head, 4)[0]
        self.data_off = struct.unpack_from("<I", head, 0x10)[0]
        self.head = fs._read(self.base, self.data_off)
        fato_size, self.count = struct.unpack_from("<IH", self.head, hsize + 4)
        offs = struct.unpack_from(f"<{self.count}I", self.head, hsize + 0xC)
        fatb = hsize + fato_size
        self.entry = [fatb + 0xC + o for o in offs]

    def span(self, i):
        e = self.entry[i]
        if struct.unpack_from("<I", self.head, e)[0] != 1:
            return None
        return struct.unpack_from("<III", self.head, e + 4)

    def read(self, fs, i):
        sp = self.span(i)
        if not sp:
            return None
        return fs._read(self.base + self.data_off + sp[0], sp[2])

    def patch(self, f, i, data):
        start, end, _ = self.span(i)
        if len(data) > end - start:
            return False
        f.seek(self.base + self.data_off + start)
        f.write(data)
        f.seek(self.base + self.entry[i] + 12)
        f.write(struct.pack("<I", len(data)))
        return True


class Gen7Rom:
    def __init__(self, path):
        hit = rom_finder.identify(path)
        self.game = hit[1] if hit else None
        self.family = FAMILY.get(self.game)
        if not self.family:
            raise ValueError("ROM 3DS : jeu de 7G non reconnu")
        self.max = MAX[self.family]
        self.base_tid = rom_finder.base_tid(G6.read_tid(path))
        if self.base_tid != G6.read_tid(path):
            raise ValueError("Choisis la ROM d'origine, pas une copie aléatoire")
        c = GARCS[self.family]
        fs = ctr_rom.RomFS(path)
        try:
            blob = ctr_rom.garc(fs.read(c["personal"]))[-1]
            self.personal = {s: blob[0x54 * s:0x54 * (s + 1)] for s in range(1, self.max + 1)}
            self.evos = ctr_rom.garc(fs.read(c["evo"]))
            self.learn = ctr_rom.garc(fs.read(c["learn"]))
            self.tr_data = ctr_rom.garc(fs.read(c["trdata"]))
            self.trpoke = Garc(fs, c["trpoke"])
            self.tr_poke = [self.trpoke.read(fs, i) or b"" for i in range(self.trpoke.count)]
            self.static = Garc(fs, c["static"])
            self.gifts = bytearray(self.static.read(fs, 0))
            self.class_names = ctr_rom.text(ctr_rom.garc(fs.read("a/0/3/3"))[c["classes"]])
            name = max(AREAS, key=lambda n: fs.files.get(n, (0, 0))[1])
            self.areas = Garc(fs, name)
            self.area_raw = {}
            for i in range(9, self.areas.count, 11):
                raw = self.areas.read(fs, i)
                if raw and raw[:1] == b"\x11":
                    self.area_raw[i] = raw
            self.area_names = self._area_names(fs)
            self.story = {}
            story_file, sp_file, ty_file = STORY[self.family]
            for lang in range(10):
                try:
                    sg = Garc(fs, f"a/0/4/{lang}")
                    gt = ctr_rom.garc(fs.read(f"a/0/3/{lang}"))
                    self.story[lang] = (sg, ctr_rom.text_raw(sg.read(fs, story_file)),
                                        [_clean(c) for c, _ in ctr_rom.text_raw(gt[sp_file])],
                                        [_clean(c) for c, _ in ctr_rom.text_raw(gt[ty_file])])
                except Exception:
                    continue
        finally:
            fs.close()
        self.gift_offsets = self._gift_offsets()

    def _area_names(self, fs):
        cfg = ctr_maps.GAMES.get(self.game)
        out = {}
        try:
            zones = ctr_rom.garc(fs.read(cfg["zones"]))
            table = ctr_rom.lz11(zones[cfg["table"]])
            names = ctr_rom.text(ctr_rom.garc(fs.read(cfg["text"]))[cfg["names"]])
            for zone, blocks in ctr_maps._zone_blocks(fs, cfg).items():
                if (zone + 1) * cfg["stride"] > len(table):
                    continue
                idx = struct.unpack_from("<H", table, zone * cfg["stride"] + 0x1C)[0] & 0x1FF
                for b in blocks:
                    if idx < len(names) and names[idx]:
                        out.setdefault(b * 11 + 9, set()).add(names[idx])
        except Exception:
            return {}
        return {k: " / ".join(sorted(v)) for k, v in out.items()}

    def _gift_offsets(self):
        if len(self.gifts) < GIFT * 3 or any(struct.unpack_from("<H", self.gifts, GIFT * i)[0] != STARTERS[i] for i in range(3)):
            return []
        out = []
        for o in range(0, len(self.gifts) - GIFT + 1, GIFT):
            sp, lv = struct.unpack_from("<H", self.gifts, o)[0], self.gifts[o + 3]
            if 0 < sp <= self.max and 0 < lv <= 100:
                out.append(o)
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

    def evolutions(self, s):
        e = self.evos[s] if s < len(self.evos) else b""
        out = []
        for i in range(0, len(e) - 7, 8):
            m, p, t = struct.unpack_from("<HHH", e, i)
            if m and 0 < t <= self.max:
                out.append((m, e[i + 7] if m in LEVEL_METHODS else p, t))
        return out

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


def _clean(chars):
    out = list(chars)
    while out and out[-1] == 0:
        out.pop()
    return out


def _swap(chars, old, new):
    if not old:
        return chars
    out, i = [], 0
    while i < len(chars):
        if chars[i:i + len(old)] == old:
            out += new
            i += len(old)
        else:
            out.append(chars[i])
            i += 1
    return out


def _starter_text(g, mapping, log):
    story_file = STORY[g.family][0]
    out, done = [], []
    for lang, (sg, lines, sp, ty) in sorted(g.story.items()):
        lines = [(list(c), f) for c, f in lines]
        if len(lines) < (20 if g.family == "SM" else 17):
            continue
        for j, old in enumerate(STARTERS):
            new = mapping[old]
            on, nn = sp[old], sp[new]
            ot, nt = ty[g.types(old)[0]], ty[g.types(new)[0]]

            def fix(k, name=True, typ=True):
                c, f = lines[k]
                if name:
                    c = _swap(c, on, nn)
                if typ:
                    c = _swap(c, ot, nt)
                lines[k] = (c, f)
            if g.family == "SM":
                fix(1 + j)
                fix(4 + j, name=False)
                fix(11 + j, typ=False)
                lines[14 + j] = (list(DOTS), lines[14 + j][1])
                lines[17 + j] = (list(DOTS), lines[17 + j][1])
            else:
                lines[1 + j] = (nn + [0x20, 0x28] + nt + [0x29, 0], lines[1 + j][1])
                lines[4 + j] = (list(DOTS), lines[4 + j][1])
                fix(7 + j, name=False)
                lines[14 + j] = (nn + [0], lines[14 + j][1])
        data = ctr_rom.text_pack(lines)
        sp_ = sg.span(story_file)
        if sp_ and len(data) <= sp_[1] - sp_[0]:
            out.append((sg, story_file, data))
            done.append(lang)
    log.append(f"Écran de choix des starters : noms et types changés ({len(done)} langues sur {len(g.story)}),"
               " modèles 3D d'origine")
    return out


def _slots(d):
    if d[:2] != b"EA":
        return []
    n = struct.unpack_from("<H", d, 2)[0]
    offs = struct.unpack_from(f"<{n + 1}I", d, 4)
    out = []
    for i in range(n):
        if offs[i + 1] - offs[i] < 0x2CC:
            continue
        kind = struct.unpack_from("<I", d, offs[i])[0]
        for half in (0, 0x164):
            p = offs[i] + 4 + half
            spots = [p + 0xC + 4 * k for k in range(80)] + [p + 0x14C + 4 * k for k in range(6)]
            out.append((p, kind in WATER_KINDS, spots))
    return out


def _wild(g, rng, opts, pool, bst, names, pick, R):
    mode = opts["wild"]
    decoded, orig, tables = {}, {}, []
    for i, raw in g.area_raw.items():
        d = bytearray(ctr_rom.lz11(raw))
        t = _slots(d)
        if t:
            decoded[i] = d
            orig[i] = bytes(d)
            tables += [(i,) + x for x in t]
    types_of = {s: set(R._type_list(*g.types(s))) for s in pool}
    water_pool = [s for s in pool if WATER in types_of[s]]
    global_map, area_maps, themes, seen_all, by_area = {}, {}, {}, set(), {}
    sites = 0
    for area, p, water, spots in tables:
        d = decoded[area]
        if opts["wildLevels"]:
            lo = max(2, min(100, round(d[p] * (1 + opts["wildLevels"] / 100)))) if d[p] else 0
            hi = max(lo, min(100, round(d[p + 1] * (1 + opts["wildLevels"] / 100)))) if d[p + 1] else 0
            d[p], d[p + 1] = lo, hi
        if mode == "off":
            continue
        for at in spots:
            v = struct.unpack_from("<I", d, at)[0]
            old = v & 0x7FF
            if not 0 < old <= g.max:
                continue
            sites += 1
            src = pool
            if opts["wildTheme"]:
                theme = themes.setdefault(area, rng.randrange(NUM_TYPES))
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
                am = area_maps.setdefault(area, {})
                if key not in am:
                    am[key] = pick(rng, cands, bst, old, opts["wildSimilar"], set(am.values()))
                new = am[key]
            else:
                new = pick(rng, cands, bst, old, opts["wildSimilar"])
            seen_all.add(new)
            if new != old:
                struct.pack_into("<I", d, at, (v & ~0xFFFF) | new)
            by_area.setdefault(area, set()).add((old, new))
    changed = {}
    for area, d in decoded.items():
        if bytes(d) != orig[area]:
            changed[area] = ctr_rom.lz11_pack(bytes(d))
    lines = []
    for area in sorted(by_area):
        pairs = sorted((o, n) for o, n in by_area[area] if o != n)
        if pairs:
            lines.append(f"  {g.area_names.get(area) or 'Zone'} ({(area - 9) // 11})")
            lines += [f"    {names(o)} -> {names(n)}" for o, n in pairs]
    log = (f"Pokémon sauvages : mode {mode}, {sites} emplacements (herbes, fleurs, grottes, sable, surf, pêche, renforts SOS)"
           + (", force similaire" if opts["wildSimilar"] and mode != "off" else "")
           + (", un type par zone" if opts["wildTheme"] else "")
           + (", Eau en surf et pêche" if opts["wildWater"] else "")
           + (f", niveaux {opts['wildLevels']:+d} %" if opts["wildLevels"] else ""))
    return changed, log, lines


def _starters(g, rng, opts, pool, pre, log, names, R):
    if opts["starters"] == "off" or len(g.gift_offsets) < 3:
        if opts["starters"] != "off":
            log.append("Starters : NON modifiés (table introuvable)")
        return None
    old = list(STARTERS)
    if opts["starters"] == "custom":
        chosen = [int(x) for x in opts["starterList"][:3] if str(x).strip()]
        if len(chosen) != 3 or any(not (1 <= c <= g.max) for c in chosen):
            raise ValueError(f"Starters choisis : il faut 3 Pokémon (n° 1 à {g.max})")
    else:
        evolves = {s: [t for _, _, t in g.evolutions(s) if t != s] for s in range(1, g.max + 1)}
        basics = [s for s in pool if s not in pre and evolves[s] and s not in old]
        if opts["starter3stage"]:
            basics = [s for s in basics if any(evolves[t] for t in evolves[s])] or basics
        if opts["starters"] == "randomAny":
            basics = [s for s in pool if s not in old]
        chosen = R._three_starters(rng, basics, g.types, opts["starterTypes"])
    for o, new in zip(g.gift_offsets[:3], chosen):
        struct.pack_into("<H", g.gifts, o, new)
        g.gifts[o + 2] = 0
    mapping = dict(zip(old, chosen))
    log.append("Starters : " + ", ".join(f"{names(o)} -> {names(n)}" for o, n in mapping.items()))
    return mapping


def _gifts(g, rng, opts, pool, bst, log, names, pick):
    if opts["gifts"] == "off" or len(g.gift_offsets) <= 3:
        return []
    lines = []
    for o in g.gift_offsets[3:]:
        old = struct.unpack_from("<H", g.gifts, o)[0]
        new = pick(rng, pool, bst, old, opts["giftSimilar"])
        struct.pack_into("<H", g.gifts, o, new)
        g.gifts[o + 2] = 0
        lines.append(f"  {names(old)} -> {names(new)} Nv{g.gifts[o + 3]}")
    log.append(f"Pokémon offerts : {len(lines)} changés" + (", force similaire" if opts["giftSimilar"] else ""))
    return lines


def _trainers(g, rng, opts, pool, bst, log, names, pick, starter_map, R):
    touch = (opts["trainers"] != "off" or opts["trainerLevels"] or opts["fullyEvolvedAt"] or opts["betterMovesets"]
             or (starter_map and opts["rivalStarter"]))
    if not touch:
        return {}, []
    types_of = {s: set(R._type_list(*g.types(s))) for s in pool}
    old_lines, new_lines = {}, {}
    if starter_map and opts["rivalStarter"]:
        for i, s in enumerate(STARTERS):
            for stage, x in enumerate(g.chain(s)):
                old_lines[x] = (i, stage)
            new_lines[i] = g.chain(starter_map[s])
    order = []
    for i in range(1, min(len(g.tr_data), len(g.tr_poke))):
        d = g.tr_data[i]
        if len(d) < 4 or d[3] * TRPOKE > len(g.tr_poke[i]):
            continue
        cname = g.class_names[d[0]] if d[0] < len(g.class_names) else ""
        important = any(w in cname for w in BOSS_WORDS)
        order.append((i, d[3], cname, important))
    if opts["e4Unique"]:
        order.sort(key=lambda x: not x[3])
    out, lines, count, rivals, e4set, used_all = {}, [], 0, 0, set(), set()
    for i, n, cname, important in order:
        blob = bytearray(g.tr_poke[i])
        src, theme = pool, None
        if opts["trainers"] == "theme" or (opts["bossTheme"] and important and opts["trainers"] != "off"):
            theme = rng.randrange(NUM_TYPES)
            src = [x for x in pool if theme in types_of[x]] or pool
        src = R._trainer_src(src, opts, important, e4set, used_all)
        team, used, is_rival = [], set(), False
        for k in range(n):
            o = k * TRPOKE
            lv, old = struct.unpack_from("<HH", blob, o + 0xE)
            new = old
            rival_mon = old in old_lines and cname.startswith("Dresseur")
            if rival_mon:
                idx, stage = old_lines[old]
                chain = new_lines[idx]
                new = chain[min(stage, len(chain) - 1)]
                is_rival = True
            elif opts["trainers"] != "off" and 0 < old <= g.max:
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
            struct.pack_into("<HH", blob, o + 0xE, lv, new)
            if new != old:
                struct.pack_into("<H", blob, o + 0x12, 0)
            had_moves = any(struct.unpack_from("<4H", blob, o + 0x18))
            if had_moves and (new != old or opts["betterMovesets"] or opts["trainerLevels"]) or opts["betterMovesets"]:
                struct.pack_into("<4H", blob, o + 0x18, *g.moves_at_level(new, lv))
            team.append(f"{names(old)}→{names(new)} Nv{lv}" if new != old else f"{names(new)} Nv{lv}")
        if bytes(blob) != g.tr_poke[i]:
            out[i] = bytes(blob)
        count += 1
        rivals += is_rival
        if important or is_rival:
            lines.append(f"  {cname or 'Dresseur'} n°{i}"
                         + (f" (type {(R.TYPE_FR + ['Fée'])[theme]})" if theme is not None else "") + " : " + ", ".join(team))
    log.append(f"Dresseurs : {opts['trainers']}, {count} équipes"
               + (", force similaire" if opts["trainerSimilar"] and opts["trainers"] != "off" else "")
               + (", Capitaines / Doyens / Conseil 4 : un type chacun" if opts["bossTheme"] and opts["trainers"] != "off" else "")
               + (f", niveaux {opts['trainerLevels']:+d} %" if opts["trainerLevels"] else "")
               + (f", complètement évolués dès le Nv. {opts['fullyEvolvedAt']}" if opts["fullyEvolvedAt"] else "")
               + (f", lignée des starters suivie par les rivaux ({rivals} équipes)" if old_lines else ""))
    return out, lines


def randomize(src_path, options, out_path, fiche_base, azahar_dir, used_tids=()):
    import randomizer as R
    import randomizer_gen2
    opts = dict(R.DEFAULTS)
    opts.update({k: v for k, v in (options or {}).items() if k in R.DEFAULTS})
    for k in ("wildLevels", "trainerLevels"):
        opts[k] = max(-50, min(200, int(opts[k] or 0)))
    g = Gen7Rom(src_path)
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
    for s in range(1, g.max + 1):
        for _, _, t in g.evolutions(s):
            if t != s:
                pre.setdefault(t, s)
    kids = {}
    for s_, p_ in pre.items():
        kids.setdefault(p_, []).append(s_)
    R._STAGE.clear()
    for s_ in range(1, g.max + 1):
        R._STAGE[s_] = 2 if s_ not in kids else (1 if s_ in pre else 0)

    def pick(rng_, pool_, bst_, old_, similar_, avoid_=()):
        return R._pick(rng_, pool_, bst_, old_, similar_, avoid_, opts["sameStage"])

    legend = R.LEGENDARIES | LEGENDARIES_7
    pool = [s for s in range(1, g.max + 1) if not (opts["noLegendaries"] and s in legend)]
    bst = {s: g.bst(s) for s in range(1, g.max + 1)}
    log = []
    gifts0 = bytes(g.gifts)
    try:
        starters = _starters(g, rng, opts, pool, pre, log, names, R)
        areas, wild_log, wild_lines = _wild(g, rng, opts, pool, bst, names, pick, R)
        log.append(wild_log)
        trainers, trainer_lines = _trainers(g, rng, opts, pool, bst, log, names, pick, starters, R)
        gift_lines = _gifts(g, rng, opts, pool, bst, log, names, pick)
    finally:
        R._STAGE.clear()
    story = _starter_text(g, starters, log) if starters and opts["starterText"] else []
    patches = story + [(g.areas, i, d) for i, d in sorted(areas.items())] + [(g.trpoke, i, d) for i, d in sorted(trainers.items())]
    if bytes(g.gifts) != gifts0:
        patches.append((g.static, 0, bytes(g.gifts)))
    skipped = sorted({randomizer_gen2.UNSUPPORTED.get(k, {"trainers": "dresseurs", "starters": "starters"}.get(k, k))
                      for k in R.DEFAULTS if k not in SUPPORTED and opts.get(k) != R.DEFAULTS[k]
                      and opts.get(k) not in ("off", False, 0, None, [])})
    if skipped:
        log.append("Pas encore disponible en 7G (ignoré) : " + ", ".join(skipped))
    if not patches:
        raise ValueError("Aucun changement demandé")
    for garc_, i, data in patches:
        sp = garc_.span(i)
        if not sp or len(data) > sp[1] - sp[0]:
            raise ValueError(f"Données trop grandes pour la ROM ({garc_.name} n°{i})")
    if out_path is None:
        root, ext = os.path.splitext(src_path)
        out_path = f"{root} ({ {'en': 'Random', 'es': 'Aleatorio'}.get(i18n.LANG, 'Aleatoire')} {seed}){ext}"
    if os.path.abspath(out_path) == os.path.abspath(src_path):
        raise ValueError("refus d'écraser la ROM d'origine")
    tid = G6.pick_tid(g.base_tid, azahar_dir, set(used_tids))
    G6.copy_with_tid(src_path, out_path, tid)
    try:
        with open(out_path, "r+b") as f:
            for garc_, i, data in patches:
                if not garc_.patch(f, i, data):
                    raise ValueError(f"Données trop grandes pour la ROM ({garc_.name} n°{i})")
        check = ctr_rom.RomFS(out_path)
        try:
            ok = all((ctr_rom.garc_file(check, garc_.name, i) or b"")[:len(data)] == data for garc_, i, data in patches)
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
        shutil.copytree(ips, out_path + ".exefsdir", dirs_exist_ok=True)
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
