import io
import json
import os
import random
import re
from contextlib import contextmanager

import gen2_maps
import i18n
import randomizer_ctr as RC
import save_gen2 as G2
import shiny_patch

MAX_SPECIES = 251
TYPE_MAP = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 7: 6, 8: 7, 9: 8, 20: 9, 21: 10, 22: 11, 23: 12, 24: 13, 25: 14,
            26: 15, 27: 16}
STARTERS = (152, 155, 158)
BOSS_CLASSES = {1, 2, 3, 4, 5, 6, 7, 8, 11, 13, 14, 15, 16, 17, 18, 19, 21, 26, 35, 46, 63, 64}
RIVAL_CLASSES = {9, 42}
EVO_LEVEL, EVO_ITEM, EVO_TRADE, EVO_HAPPY, EVO_STAT = 1, 2, 3, 4, 5
UNSUPPORTED = {"abilities": "talents (n'existent pas en 2G)",
               "tutorMoves": "tuteurs d'attaques", "tutorCompat": "tuteurs d'attaques",
               "moveCategory": "catégorie des attaques (fixée par le type en 2G)",
               "fossils": "fossiles (pas de fossiles à ranimer en 2G)",
               "doubleBattles": "combats doubles (n'existent pas en 2G)", "runIndoors": "course (n'existe pas en 2G)",
               "startShoes": "course (n'existe pas en 2G)"}


def _ptr(rom, bank, o):
    v = rom[o] | rom[o + 1] << 8
    return bank * 0x4000 + v - 0x4000 if 0x4000 <= v < 0x8000 else None


class Gen2Rom:
    def __init__(self, rom):
        self.rom = rom
        self.game = G2.rom_game_key(rom)
        self.bs = G2.base_stats_offset(bytes(rom))
        self._evos_table()
        self._trainer_table()

    def stats(self, s):
        return list(self.rom[self.bs + 32 * (s - 1) + 1:self.bs + 32 * (s - 1) + 7])

    def bst(self, s):
        return sum(self.stats(s))

    def types(self, s):
        o = self.bs + 32 * (s - 1)
        return TYPE_MAP.get(self.rom[o + 7], 0), TYPE_MAP.get(self.rom[o + 8], 0)

    def raise_catch_rate(self, s, v):
        o = self.bs + 32 * (s - 1) + 9
        self.rom[o] = max(self.rom[o], v)

    def _evos_table(self):
        rom = bytes(self.rom)
        i = rom.find(bytes([EVO_LEVEL, 16, 2, 0, 1, 0x21, 4, 0x2D, 7, 0x49]))
        if i >= 0:
            bank = i // 0x4000
            ga = (i % 0x4000 + 0x4000).to_bytes(2, "little")
            t = rom.find(ga, bank * 0x4000, bank * 0x4000 + 0x4000)
        if i < 0 or t < 0:
            bank, t = self._evos_scan(rom)
        self.evo_at = {}
        for s in range(1, MAX_SPECIES + 1):
            p = _ptr(rom, bank, t + 2 * (s - 1))
            if p is None:
                raise ValueError("2G : pointeur d'évolution invalide")
            self.evo_at[s] = p

    @staticmethod
    def _chunk_end(rom, o):
        for _ in range(8):
            m = rom[o]
            if m == 0:
                break
            if m > EVO_STAT:
                return None
            o += 4 if m == EVO_STAT else 3
        else:
            return None
        o += 1
        for _ in range(40):
            if rom[o] == 0:
                return o + 1
            if not (1 <= rom[o] <= 100 and 1 <= rom[o + 1] <= 251):
                return None
            o += 2
        return None

    def _evos_scan(self, rom):
        for bank in range(1, len(rom) // 0x4000):
            lo = bank * 0x4000
            for t in range(lo, lo + 0x4000 - 2 * MAX_SPECIES):
                v0 = rom[t] | rom[t + 1] << 8
                if not 0x4000 <= v0 < 0x8000:
                    continue
                v1 = rom[t + 2] | rom[t + 3] << 8
                if not 0 < v1 - v0 < 120:
                    continue
                ptrs = [lo + (rom[t + 2 * k] | rom[t + 2 * k + 1] << 8) - 0x4000 for k in range(MAX_SPECIES)]
                if any(not lo <= p < lo + 0x4000 for p in ptrs):
                    continue
                if all(self._chunk_end(rom, ptrs[k]) == ptrs[k + 1] for k in range(MAX_SPECIES - 1)):
                    return bank, t
        raise ValueError("2G : table des évolutions introuvable")

    def evolutions(self, s):
        o, out = self.evo_at[s], []
        while self.rom[o]:
            m = self.rom[o]
            if m == EVO_STAT:
                out.append((m, self.rom[o + 1], self.rom[o + 3]))
                o += 4
            else:
                out.append((m, self.rom[o + 1], self.rom[o + 2]))
                o += 3
        return out

    def learnset(self, s):
        o = self.evo_at[s]
        while self.rom[o]:
            o += 4 if self.rom[o] == EVO_STAT else 3
        o += 1
        out = []
        while self.rom[o]:
            out.append((self.rom[o], self.rom[o + 1]))
            o += 2
        return out

    def moves_at_level(self, s, level):
        moves = []
        for lv, m in self.learnset(s):
            if lv > level:
                break
            if m in moves:
                moves.remove(m)
            moves.append(m)
        moves = moves[-4:]
        return moves + [0] * (4 - len(moves))

    def _trainer_table(self):
        rom = bytes(self.rom)
        hits = [m.start() for m in re.finditer(rb"\x50[\x00-\x03]\x07\x10", rom)]
        self.trainer_groups = []
        for h in hits:
            name = h
            while name > 0 and rom[name - 1] >= 0x7F and h - name < 11:
                name -= 1
            bank = name // 0x4000
            ga = (name % 0x4000 + 0x4000).to_bytes(2, "little")
            t = rom.rfind(ga, bank * 0x4000, name)
            if t < 0 or (name - t) % 2 or not 60 <= (name - t) // 2 <= 70:
                continue
            ptrs = [_ptr(rom, bank, t + 2 * k) for k in range((name - t) // 2)]
            if None in ptrs or ptrs[0] != name or any(b < a for a, b in zip(ptrs, ptrs[1:])):
                continue
            groups = []
            for c, start in enumerate(ptrs, 1):
                end = ptrs[c] if c < len(ptrs) else None
                parsed = self._parse_group(start, end)
                if parsed is None:
                    break
                groups.append((c, parsed))
            if len(groups) == len(ptrs):
                self.trainer_groups = groups
                self.trainer_ptrs, self.trainer_ptr_at = ptrs, t
                self.trainer_end = 0
                for _, group in groups:
                    for _, mons in group:
                        at, item_at, moves_at = mons[-1]
                        self.trainer_end = max(self.trainer_end, at + 2 + (1 if item_at is not None else 0)
                                               + (4 if moves_at is not None else 0) + 1)
                return
        raise ValueError("2G : table des dresseurs introuvable")

    def _parse_group(self, o, end):
        rom, out = self.rom, []
        while end is None or o < end:
            name = o
            while rom[o] != 0x50:
                if rom[o] < 0x7F or o - name > 12:
                    return out if end is None and out else None
                o += 1
            o += 1
            kind = rom[o]
            if kind > 3:
                return out if end is None and out else None
            o += 1
            mons = []
            while rom[o] != 0xFF:
                lv, sp = rom[o], rom[o + 1]
                if not (1 <= lv <= 100 and 1 <= sp <= MAX_SPECIES) or len(mons) >= 6:
                    return out if end is None and out else None
                item = o + 2 if kind & 2 else None
                moves = o + 2 + (1 if kind & 2 else 0) if kind & 1 else None
                mons.append((o, item, moves))
                o += 2 + (1 if kind & 2 else 0) + (4 if kind & 1 else 0)
            if not mons:
                return out if end is None and out else None
            o += 1
            out.append((G2.text(rom[name:name + 12]), mons))
        return out if o == end else None


def _pre_map(g):
    pre = {}
    for s in range(1, MAX_SPECIES + 1):
        for _, _, t in g.evolutions(s):
            if 0 < t <= MAX_SPECIES:
                pre.setdefault(t, s)
    return pre


def _next_stage(g, s, level=None, rng=None):
    nxt = []
    for m, p, t in g.evolutions(s):
        if not 0 < t <= MAX_SPECIES or t == s:
            continue
        if level is None or (m in (EVO_LEVEL, EVO_STAT) and 0 < p <= level) or (m not in (EVO_LEVEL, EVO_STAT) and level >= 40):
            nxt.append(t)
    if not nxt:
        return None
    return rng.choice(nxt) if rng else nxt[0]


def _wild(g, rng, opts, pool, bst, log, names, pick, R):
    mode = opts["wild"]
    if mode == "off" and not opts["wildLevels"]:
        return []
    rom = g.rom
    src_rom = bytes(rom)
    types_of = {s: set(R._type_list(*g.types(s))) for s in pool}
    water_pool = [s for s in pool if R.WATER in types_of[s]]
    sites = []
    for o, k in gen2_maps._tables(src_rom, 47, gen2_maps._valid_grass, 4):
        for i in range(k):
            e = o + 47 * i
            sites += [((rom[e], rom[e + 1]), e + 5 + 2 * j, False) for j in range(21)]
    for o, k in gen2_maps._tables(src_rom, 9, gen2_maps._valid_water, 4):
        for i in range(k):
            e = o + 9 * i
            sites += [((rom[e], rom[e + 1]), e + 3 + 2 * j, True) for j in range(3)]
    landmarks = gen2_maps.zone_names(src_rom)
    global_map, zone_maps, themes, seen_all, by_zone = {}, {}, {}, set(), {}
    for zone, at, water in sites:
        old = rom[at + 1]
        src = pool
        if opts["wildTheme"]:
            theme = themes.setdefault(zone, rng.randrange(R.NUM_TYPES))
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
                zm = zone_maps.setdefault(zone, {})
                if key not in zm:
                    zm[key] = pick(rng, cands, bst, old, opts["wildSimilar"], set(zm.values()))
                new = zm[key]
            else:
                new = pick(rng, cands, bst, old, opts["wildSimilar"])
            seen_all.add(new)
            rom[at + 1] = new
        if opts["wildLevels"]:
            rom[at] = max(2, min(100, round(src_rom[at] * (1 + opts["wildLevels"] / 100))))
        by_zone.setdefault(zone, set()).add((old, new))
    log.append(f"Pokémon sauvages : mode {mode}, {len(sites)} emplacements (herbes et surf)"
               + (", force similaire" if opts["wildSimilar"] and mode != "off" else "")
               + (", un type par zone" if opts["wildTheme"] else "")
               + (", Eau en surf" if opts["wildWater"] else "")
               + (f", niveaux {opts['wildLevels']:+d} %" if opts["wildLevels"] else "")
               + " ; pêche, arbres et rochers inchangés")
    lines = []
    for zone in sorted(by_zone):
        head = landmarks.get(zone) or f"Zone {zone[0]}-{zone[1]}"
        changed = sorted((o, n) for o, n in by_zone[zone] if o != n)
        if changed:
            lines.append(f"  {head}")
            lines += [f"    {names(o)} -> {names(n)}" for o, n in changed]
    return lines


def _starter_sites(g):
    rom = bytes(g.rom)
    gives = []
    for s in STARTERS:
        hits = [m.start() for m in re.finditer(bytes([0x2D, s, 5, 0xAD]), rom)]
        if len(hits) != 1:
            return None
        gives.append((hits[0], s))
    gives.sort()
    sites, prev = {}, gives[0][0] - 120
    for at, s in gives:
        found = [at + 1]
        for o in range(max(prev, at - 120), at):
            if rom[o + 1] != s:
                continue
            if rom[o] in (0x55, 0x56) or (rom[o] in (0x83, 0x84, 0x40) and rom[o + 2] == 0):
                found.append(o + 1)
        if len(found) != 4:
            return None
        sites[s] = found
        prev = at + 6
    return sites


def _starters(g, rng, opts, pool, pre, log, names, R):
    if opts["starters"] == "off":
        return None
    sites = _starter_sites(g)
    if not sites:
        log.append("Starters : NON modifiés (script du labo non trouvé)")
        return None
    if opts["starters"] == "custom":
        chosen = [int(x) for x in opts["starterList"][:3] if str(x).strip()]
        if len(chosen) != 3 or any(not (1 <= c <= MAX_SPECIES) for c in chosen):
            raise ValueError("Starters choisis : il faut 3 Pokémon de la 2G (n° 1 à 251)")
    else:
        evolves = {s: [t for _, _, t in g.evolutions(s) if 0 < t <= MAX_SPECIES] for s in range(1, MAX_SPECIES + 1)}
        basics = [s for s in pool if s not in pre and evolves[s] and s not in STARTERS]
        if opts["starter3stage"]:
            basics = [s for s in basics if any(evolves[t] for t in evolves[s])] or basics
        if opts["starters"] == "randomAny":
            basics = [s for s in pool if s not in STARTERS]
        chosen = R._three_starters(rng, basics, g.types, opts["starterTypes"])
    mapping = dict(zip(STARTERS, chosen))
    for old, offs in sites.items():
        for o in offs:
            g.rom[o] = mapping[old]
    log.append("Starters : " + ", ".join(f"{names(o)} -> {names(n)}" for o, n in mapping.items())
               + " (labo du Prof. Orme : image, cri, nom et Pokémon donné)")
    return mapping


ELM_TAIL = b"\xf4\x7f\xab\xa4\x55\x54\x8c\x8e\x8d"
TYPE_WORDS = ["normal", "combat", "vol", "poison", "sol", "roche", "insecte", "spectre", "acier", "de feu", "\xd5eau",
              "plante", "\xealectrik", "psy", "glace", "dragon", "t\xean\xbbbres"]


def _type_word(i):
    w = TYPE_WORDS[i] if 0 <= i < len(TYPE_WORDS) else ""
    out = bytearray()
    for ch in w:
        c = ord(ch)
        out.append(c if c >= 0x80 else G2._INV[ch])
    return bytes(out)


def _starter_text2(g, mapping, log):
    names = G2.species_names_rom(bytes(g.rom))
    done = 0
    for old, new in mapping.items():
        pat = b"\x4f" + names[old] + ELM_TAIL + b"\x7f"
        at = bytes(g.rom).find(pat)
        if at < 0 or bytes(g.rom).find(pat, at + 1) >= 0:
            continue
        start = at + 1
        end = bytes(g.rom).find(b"\xe6\x57", start + len(pat), start + len(pat) + 16)
        if end < 0:
            continue
        room = end + 2 - start
        word = _type_word(g.types(new)[0])
        text = names[new] + ELM_TAIL + b"\x7f" + word + b"\xe6\x57"
        if len(text) > room:
            text = names[new] + ELM_TAIL + b"\xe6\x57"
        if len(text) > room:
            continue
        g.rom[start:start + len(text)] = text
        done += 1
    if done:
        log.append(f"Texte du Prof. Orme : nom et type des nouveaux starters ({done}/3 répliques)")
    else:
        log.append("Texte du Prof. Orme : NON modifié (répliques introuvables)")


def _line_chain(g, s):
    chain = [s]
    while len(chain) < 3:
        nxt = _next_stage(g, chain[-1])
        if not nxt:
            break
        chain.append(nxt)
    return chain


def _trainers(g, rng, opts, pool, bst, log, names, pick, starter_map, R):
    touch = (opts["trainers"] != "off" or opts["trainerLevels"] or opts["fullyEvolvedAt"] or opts["betterMovesets"]
             or (starter_map and opts["rivalStarter"]))
    if not touch:
        return []
    rom = g.rom
    types_of = {s: set(R._type_list(*g.types(s))) for s in pool}
    old_lines, new_lines = {}, {}
    if starter_map and opts["rivalStarter"]:
        for i, s in enumerate(STARTERS):
            for stage, x in enumerate(_line_chain(g, s)):
                old_lines[x] = (i, stage)
            new_lines[i] = _line_chain(g, starter_map[s])
    order = [(c, name, mons) for c, group in g.trainer_groups for name, mons in group]
    if opts["e4Unique"]:
        order.sort(key=lambda x: x[0] not in BOSS_CLASSES)
    lines, count, rivals, e4set, used_all = [], 0, 0, set(), set()
    for cls, tname, mons in order:
        important = cls in BOSS_CLASSES
        src, theme = pool, None
        if opts["trainers"] == "theme" or (opts["bossTheme"] and important and opts["trainers"] != "off"):
            theme = rng.randrange(R.NUM_TYPES)
            src = [x for x in pool if theme in types_of[x]] or pool
        src = R._trainer_src(src, opts, important, e4set, used_all)
        team, used, is_rival = [], set(), False
        for at, item_at, moves_at in mons:
            lv, old = rom[at], rom[at + 1]
            new = old
            if old in old_lines and cls in RIVAL_CLASSES:
                i, stage = old_lines[old]
                chain = new_lines[i]
                new = chain[min(stage, len(chain) - 1)]
                is_rival = True
            elif opts["trainers"] != "off":
                new = pick(rng, src, bst, old, opts["trainerSimilar"], used)
            if opts["trainerLevels"]:
                lv = max(2, min(100, round(lv * (1 + opts["trainerLevels"] / 100))))
                rom[at] = lv
            if opts["evolveByLevel"] and not is_rival:
                for _ in range(2):
                    nxt = _next_stage(g, new, lv, rng)
                    if not nxt:
                        break
                    new = nxt
            if opts["fullyEvolvedAt"] and lv >= opts["fullyEvolvedAt"] and not is_rival:
                for _ in range(3):
                    nxt = _next_stage(g, new, None, rng)
                    if not nxt:
                        break
                    new = nxt
            used.add(new)
            used_all.add(new)
            if important:
                e4set.add(new)
            rom[at + 1] = new
            if moves_at is not None and (new != old or opts["betterMovesets"] or opts["trainerLevels"]):
                rom[moves_at:moves_at + 4] = bytes(g.moves_at_level(new, lv))
            team.append(f"{names(old)}→{names(new)} Nv{lv}" if new != old else f"{names(new)} Nv{lv}")
        count += 1
        rivals += is_rival
        if important or is_rival:
            label = "Rival" if cls in RIVAL_CLASSES and tname in ("", "?") else (tname.title() if tname else f"classe {cls}")
            lines.append(f"  {label}{' (type ' + R.TYPE_FR[theme] + ')' if theme is not None else ''} : " + ", ".join(team))
    log.append(f"Dresseurs : {opts['trainers']}, {count} équipes"
               + (", force similaire" if opts["trainerSimilar"] and opts["trainers"] != "off" else "")
               + (", Champions / Conseil 4 / Maître : un type chacun" if opts["bossTheme"] and opts["trainers"] != "off" else "")
               + (f", niveaux {opts['trainerLevels']:+d} %" if opts["trainerLevels"] else "")
               + (f", complètement évolués dès le Nv. {opts['fullyEvolvedAt']}" if opts["fullyEvolvedAt"] else "")
               + (f", lignée des starters suivie par le rival ({rivals} équipes)" if old_lines else ""))
    return lines


TYPE_INV = {v: k for k, v in TYPE_MAP.items()}
MAX_MOVE = 251
TM_SIG = bytes([223, 29, 174, 205, 46, 92, 192, 249])
HM_MOVES2 = {15, 19, 57, 70, 148, 250, 127}
FIELD_TMS2 = {"CT02", "CT08"}
STONES = {8, 0x16, 0x17, 0x18, 0x22, 0xA9}
HELD2 = [0x03, 0x49, 0x4A, 0x4C, 0x4D, 0x4E, 0x4F, 0x50, 0x51, 0x52, 0x53, 0x54, 0x58, 0x5F, 0x60, 0x62, 0x66, 0x68,
         0x6A, 0x6B, 0x6C, 0x6D, 0x71, 0x75, 0x77, 0x7D, 0x8A, 0x8B, 0x8C, 0x8F, 0x90, 0x92, 0x96, 0xAD, 0xAE]
BERRIES2 = [0x4A, 0x4E, 0x4F, 0x50, 0x53, 0x54, 0x6D, 0x8B, 0x96, 0xAD, 0xAE]
STAT_TO5 = {1: 9, 2: 11, 3: 10}
STAT_TO2 = {v: k for k, v in STAT_TO5.items()}
HAPPY_TO5 = {1: 1, 2: 2, 3: 3}


@contextmanager
def core2(R):
    saved = (R.MAX_SPECIES, R.MAX_MOVE, R.MAX_ABILITY, R.NUM_TYPES)
    R.MAX_SPECIES, R.MAX_MOVE, R.MAX_ABILITY, R.NUM_TYPES = MAX_SPECIES, MAX_MOVE, 0, 17
    try:
        yield
    finally:
        R.MAX_SPECIES, R.MAX_MOVE, R.MAX_ABILITY, R.NUM_TYPES = saved


class Gen2Core:
    tm_count, hm_count = 50, 7
    has_move_category = False
    max_item = 0xFF

    def __init__(self, g):
        self.g = g
        self.rom = g.rom
        r = bytes(g.rom)
        self.mv = G2.moves_offset(r)
        hits = [m.start() for m in re.finditer(re.escape(TM_SIG), r)]
        self.tm_list = hits[0] if len(hits) == 1 else None
        self.p0, self.m0, self.l0, self.e0 = self._snap()

    def _snap(self):
        return (bytes(self.rom[self.g.bs:self.g.bs + 32 * MAX_SPECIES]), bytes(self.rom[self.mv:self.mv + 7 * MAX_MOVE]),
                {s: self.learnset(s) for s in range(1, MAX_SPECIES + 1)},
                {s: self.evolutions(s) for s in range(1, MAX_SPECIES + 1)})

    def _bs(self, s):
        return self.g.bs + 32 * (s - 1)

    def stats(self, s):
        return self.g.stats(s)

    def set_stats(self, s, v):
        o = self._bs(s) + 1
        self.rom[o:o + 6] = bytes(max(1, min(255, x)) for x in v)

    def bst(self, s):
        return self.g.bst(s)

    def types(self, s):
        return self.g.types(s)

    def set_types(self, s, t1, t2):
        o = self._bs(s)
        self.rom[o + 7], self.rom[o + 8] = TYPE_INV[t1], TYPE_INV[t2]

    def abilities(self, s):
        return [0, 0, 0]

    def set_abilities(self, s, a):
        pass

    def set_growth(self, s, v):
        self.rom[self._bs(s) + 22] = v

    def raise_catch_rate(self, s, v):
        self.g.raise_catch_rate(s, v)

    def held_item_pool(self):
        return list(HELD2)

    def set_held_items(self, s, items):
        o = self._bs(s)
        self.rom[o + 11], self.rom[o + 12] = (list(items) + [0, 0])[:2]

    def tm_bits(self, s):
        o = self._bs(s) + 24
        return int.from_bytes(self.rom[o:o + 8], "little")

    def set_tm_bits(self, s, bits):
        o = self._bs(s) + 24
        keep = (1 << 57) - 1
        old = int.from_bytes(self.rom[o:o + 8], "little")
        self.rom[o:o + 8] = ((bits & keep) | (old & ~keep)).to_bytes(8, "little")

    def move(self, m):
        o = self.mv + 7 * (m - 1)
        power, t = self.rom[o + 2], self.rom[o + 3]
        return {"type": TYPE_MAP.get(t, 0), "cat": 0 if power == 0 else (1 if t < 20 else 2), "power": power,
                "acc": round(self.rom[o + 4] * 100 / 255), "pp": self.rom[o + 5]}

    def set_move(self, m, d):
        o = self.mv + 7 * (m - 1)
        old = self.move(m)
        self.rom[o + 2] = max(0, min(255, d["power"]))
        if d["type"] != old["type"] and self.rom[o + 3] in TYPE_MAP:
            self.rom[o + 3] = TYPE_INV[d["type"]]
        if d["acc"] != old["acc"]:
            self.rom[o + 4] = max(1, min(255, round(d["acc"] * 255 / 100)))
        self.rom[o + 5] = max(1, min(63, d["pp"])) if d["pp"] else 0

    def _evo_entries(self, s):
        o, out = self.g.evo_at[s], []
        while self.rom[o]:
            out.append(o)
            o += 4 if self.rom[o] == EVO_STAT else 3
        return out

    def evolutions(self, s):
        out = []
        for o in self._evo_entries(s):
            m, p = self.rom[o], self.rom[o + 1]
            if m == EVO_LEVEL:
                out.append([4, p, self.rom[o + 2]])
            elif m == EVO_ITEM:
                out.append([8, p, self.rom[o + 2]])
            elif m == EVO_TRADE:
                out.append([5, 0, self.rom[o + 2]] if p == 0xFF else [6, p, self.rom[o + 2]])
            elif m == EVO_HAPPY:
                out.append([HAPPY_TO5.get(p, 1), 0, self.rom[o + 2]])
            else:
                out.append([STAT_TO5.get(self.rom[o + 2], 9), p, self.rom[o + 3]])
        return out

    def set_evo(self, s, slot, method, param, target):
        o = self._evo_entries(s)[slot]
        stat = self.rom[o] == EVO_STAT
        if method in STAT_TO2:
            if stat:
                self.rom[o + 1], self.rom[o + 2], self.rom[o + 3] = param, STAT_TO2[method], target
            return
        if stat:
            return
        if method == 8 and param not in STONES:
            method, param = 4, 37
        code = {4: (EVO_LEVEL, param), 8: (EVO_ITEM, param), 5: (EVO_TRADE, 0xFF), 6: (EVO_TRADE, param),
                1: (EVO_HAPPY, 1), 2: (EVO_HAPPY, 2), 3: (EVO_HAPPY, 3)}.get(method)
        if code:
            self.rom[o], self.rom[o + 1], self.rom[o + 2] = code[0], code[1], target

    def set_evo_target(self, s, slot, target):
        o = self._evo_entries(s)[slot]
        self.rom[o + (3 if self.rom[o] == EVO_STAT else 2)] = target

    def clear_evolutions(self, s):
        raise ValueError("2G : évolutions à chaque niveau impossibles")

    def learnset(self, s):
        return [[m, lv] for lv, m in self.g.learnset(s)]

    def set_learnset(self, s, entries):
        o = self.g.evo_at[s]
        while self.rom[o]:
            o += 4 if self.rom[o] == EVO_STAT else 3
        o += 1
        for m, lv in entries:
            if not self.rom[o]:
                break
            self.rom[o], self.rom[o + 1] = lv, m
            o += 2

    def tm_labels(self):
        if self.tm_list is None:
            return {}
        out = {f"CT{i + 1:02d}": self.rom[self.tm_list + i] for i in range(50)}
        out.update({f"CS{i + 1:02d}": self.rom[self.tm_list + 50 + i] for i in range(7)})
        return out

    def personal_changed(self):
        return bytes(self.rom[self.g.bs:self.g.bs + 32 * MAX_SPECIES]) != self.p0

    def moves_changed(self):
        return bytes(self.rom[self.mv:self.mv + 7 * MAX_MOVE]) != self.m0


def _tm_moves2(d, rng, opts, log, R):
    if opts["tmMoves"] == "off":
        return None
    if d.tm_list is None:
        log.append("CT : NON modifiées (liste des CT introuvable)")
        return None
    labels = d.tm_labels()
    keep = FIELD_TMS2 if opts["keepFieldTMs"] else set()
    banned = {R.STRUGGLE} | HM_MOVES2 | (R.GAME_BREAKING_MOVES if opts["noGameBreaking"] else set())
    used = {labels[k] for k in keep}
    pool = [m for m in range(1, MAX_MOVE + 1) if m not in banned and m not in used]
    rng.shuffle(pool)
    for i in range(50):
        lab = f"CT{i + 1:02d}"
        if lab in keep:
            continue
        labels[lab] = pool.pop()
        d.rom[d.tm_list + i] = labels[lab]
    log.append("CT : attaques aléatoires (sans doublon, CS inchangées"
               + (", Coup d'Boule et Éclate-Roc gardées pour le terrain" if keep else "") + ")")
    return labels


def _fiche2(fiche, base, d, labels, R):
    if not base or "species" not in fiche:
        return
    tnames = base.get("typeNames") or R.TYPE_FR
    if d.moves_changed():
        moves = dict(fiche.get("moves", {}))
        for k, v in moves.items():
            m = int(k)
            if 0 < m <= MAX_MOVE:
                x = d.move(m)
                moves[k] = [v[0], tnames[x["type"]] if x["type"] < len(tnames) else "?",
                            x["power"] if x["power"] > 1 else None, x["acc"] if 0 < x["acc"] <= 100 else None]
        fiche["moves"] = moves
    labels = labels or d.tm_labels()
    order = sorted(labels, key=lambda x: (x[:2] == "CS", int(x[2:])))
    bit = {lab: int(lab[2:]) - 1 + (50 if lab.startswith("CS") else 0) for lab in order}
    species = {k: dict(v) for k, v in fiche["species"].items()}
    for s in range(1, MAX_SPECIES + 1):
        sp = species.get(str(s))
        if sp is None:
            continue
        sp["types"] = [tnames[t] for t in R._type_list(*d.types(s)) if t < len(tnames)]
        bits = d.tm_bits(s)
        sp["tm"] = [[lab, labels[lab]] for lab in order if bits >> bit[lab] & 1]
        sp["lv"] = [[lv, mv] for mv, lv in d.learnset(s)]
        old = d.e0[s]
        new = d.evolutions(s)
        if old != new and sp.get("ev") and len(sp["ev"]) == len(new):
            sp["ev"] = [[n[2], f"Nv. {n[1]}" if n[0] == 4 and (o[0], o[1]) != (n[0], n[1]) else e[1]] + list(e[2:])
                        for e, o, n in zip(sp["ev"], old, new)]
        species[str(s)] = sp
    fiche["species"] = species


OPS = {"CRYSTAL": {"load": 0x5D, "start": 0x5F, "cry": 0x84, "pic": 0x56, "sound": 0x85, "wait": 0x86},
       "GOLD": {"load": 0x5C, "start": 0x5E, "cry": 0x83, "pic": 0x55, "sound": 0x84, "wait": 0x85}}
OPS["SILVER"] = OPS["GOLD"]
MART_SIG = bytes([4, 0x12, 9, 0x0D, 0x0C, 0xFF])
POKE_BALL_SPRITE = 0x54
KEY_POCKET, TM_POCKET = 2, 4


def _pockets(rom):
    try:
        return G2.item_pockets_rom(bytes(rom))
    except ValueError:
        return {}


def _marts(rom):
    r = bytes(rom)
    h = r.find(MART_SIG)
    if h < 0 or r.find(MART_SIG, h + 1) >= 0:
        return []
    bank = h // 0x4000
    ga = (h % 0x4000 + 0x4000).to_bytes(2, "little")
    best = []
    for m in re.finditer(re.escape(ga), r[bank * 0x4000:(bank + 1) * 0x4000]):
        o, out = bank * 0x4000 + m.start(), []
        while True:
            p = _ptr(r, bank, o)
            if p is None:
                break
            n = r[p]
            if not 1 <= n <= 20 or r[p + 1 + n] != 0xFF or any(not 1 <= x <= 0xF9 for x in r[p + 1:p + 1 + n]):
                break
            out.append((p + 1, list(r[p + 1:p + 1 + n])))
            o += 2
        if len(out) > len(best):
            best = out
    return best


def _shops2(g, rng, opts, log):
    if opts["shops"] == "off":
        return
    marts = _marts(g.rom)
    if not marts:
        log.append("Magasins : NON modifiés (table introuvable)")
        return
    pockets = _pockets(g.rom)
    keep = lambda it: it == 5 or pockets.get(it) in (KEY_POCKET, TM_POCKET)
    lists = [list(v) for _, v in marts]
    pool = sorted({it for l in lists for it in l if not keep(it)})
    if opts["shops"] == "shuffle":
        slots = [(i, k) for i, l in enumerate(lists) for k, it in enumerate(l) if not keep(it)]
        vals = [lists[i][k] for i, k in slots]
        rng.shuffle(vals)
        for (i, k), v in zip(slots, vals):
            lists[i][k] = v
    else:
        for l in lists:
            for k, it in enumerate(l):
                if not keep(it):
                    l[k] = rng.choice(pool)
    for l in lists:
        for k in range(len(l)):
            if l.index(l[k]) != k and not keep(l[k]):
                free = [x for x in pool if x not in l]
                if free:
                    l[k] = rng.choice(free)
    changed = 0
    for (o, old), l in zip(marts, lists):
        changed += sum(a != b for a, b in zip(old, l))
        g.rom[o:o + len(l)] = bytes(l)
    log.append(f"Magasins : {len(lists)} boutiques, {changed} objets changés (CT/CS, objets rares et Poké Ball de base gardés) - "
               + ("mélangés" if opts["shops"] == "shuffle" else "parmi les objets vendus dans le jeu"))


def _item_balls(rom):
    r = bytes(rom)
    out, seen = [], set()
    for o in range(0x10000, len(r) - 13):
        if r[o] != POKE_BALL_SPRITE or r[o + 3] != 1 or r[o + 7] & 0x0F != 1 or r[o + 1] < 4 or r[o + 2] < 4:
            continue
        v = r[o + 9] | r[o + 10] << 8
        if not 0x4000 <= v < 0x8000:
            continue
        p = (o // 0x4000) * 0x4000 + v - 0x4000
        if 1 <= r[p] <= 0xF9 and 1 <= r[p + 1] <= 99 and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _event_block(r, o):
    p = o + 2
    n = r[p]
    for i in range(n):
        y, x, w, mg, mn = r[p + 1 + 5 * i:p + 6 + 5 * i]
        if not (1 <= mg <= 26 and 1 <= mn <= 100 and 1 <= w <= 30 and x < 80 and y < 80):
            return None
    p += 1 + 5 * n
    if r[p] > 30:
        return None
    p += 1 + 8 * r[p]
    n = r[p]
    if n > 40:
        return None
    bgs = []
    for i in range(n):
        y, x, f = r[p + 1 + 5 * i:p + 4 + 5 * i]
        v = r[p + 4 + 5 * i] | r[p + 5 + 5 * i] << 8
        if f > 8 or x > 80 or y > 80 or not 0x4000 <= v < 0x8000:
            return None
        bgs.append((f, v))
    p += 1 + 5 * n
    if r[p] > 16:
        return None
    return bgs


def _hidden_items(rom):
    r = bytes(rom)
    out = []
    for m in re.finditer(rb"(?=\x00\x00[\x01-\x28])", r[0x4000:]):
        o = m.start() + 0x4000
        bgs = _event_block(r, o) if o + 300 < len(r) else None
        for f, v in bgs or ():
            q = (o // 0x4000) * 0x4000 + v - 0x4000 + 2
            if f == 7 and 1 <= r[q] <= 0xF9 and q not in out:
                out.append(q)
    return out


def _field_items2(g, rng, opts, log, names_items):
    if opts["fieldItems"] == "off":
        return []
    groups = [("Objets au sol", _item_balls(g.rom)), ("Objets cachés", _hidden_items(g.rom))]
    if not groups[0][1]:
        log.append("Objets au sol : NON modifiés (objets introuvables)")
        return []
    pockets = _pockets(g.rom)
    fixed = lambda it: pockets.get(it) == KEY_POCKET or it >= 0xF3
    tms_all = sorted(i for i, p in pockets.items() if p == TM_POCKET and i < 0xF3)
    every = [g.rom[p] for _, sites in groups for p in sites]
    tms = [t for t in tms_all if t not in every]
    common = sorted({it for it in every if not fixed(it) and pockets.get(it) != TM_POCKET}
                    | {it for _, l in _marts(g.rom) for it in l if not fixed(it) and pockets.get(it) != TM_POCKET})
    out = []
    for label, sites in groups:
        if not sites:
            log.append(f"{label} : NON modifiés (objets introuvables)")
            continue
        old = [g.rom[p] for p in sites]
        movable = [i for i, it in enumerate(old) if not fixed(it)]
        new = list(old)
        if opts["fieldItems"] == "shuffle":
            vals = [old[i] for i in movable]
            rng.shuffle(vals)
            for i, v in zip(movable, vals):
                new[i] = v
        else:
            for i in movable:
                if pockets.get(old[i]) == TM_POCKET:
                    pick = rng.choice(tms or tms_all)
                    if pick in tms:
                        tms.remove(pick)
                    new[i] = pick
                else:
                    new[i] = rng.choice(common)
        for p, it in zip(sites, new):
            g.rom[p] = it
        log.append(f"{label} : {len(sites)} objets " + ("mélangés" if opts["fieldItems"] == "shuffle" else "aléatoires (CT -> CT)")
                   + ", objets rares gardés")
        out += [f"  {names_items(a)} -> {names_items(b)}" for a, b in zip(old, new) if a != b]
    return out


def _static_sites(g):
    op = OPS[g.game]
    r = bytes(g.rom)
    pat = re.compile(re.escape(bytes([op["load"]])) + rb"[\x01-\xFB][\x01-\x64](?=" + re.escape(bytes([op["start"]]))
                     + rb"|\x1e\x03." + re.escape(bytes([op["start"]])) + rb")", re.S)
    out = []
    for m in pat.finditer(r):
        o = m.start()
        sp = r[o + 1]
        prev = r[o - 3:o]
        if prev == bytes([op["cry"], sp, 0]) or prev[:2] == b"\x1e\x03" or prev[0] == 0x0F \
                or (prev[2] == 0x49 and r[o - 2] != op["load"]):
            out.append(o)
    return out


def _statics2(g, rng, opts, pool, bst, log, names, R):
    if opts["statics"] == "off":
        return []
    op = OPS[g.game]
    sites = _static_sites(g)
    if not sites:
        log.append("Pokémon fixes : NON modifiés (scripts introuvables)")
        return []

    def writer(o):
        old = g.rom[o + 1]

        def write(new, lv):
            g.rom[o + 1] = new
            for c in range(o - 8, o):
                if g.rom[c] == op["cry"] and g.rom[c + 1] == old and g.rom[c + 2] == 0:
                    g.rom[c + 1] = new
        return write
    entries = [(g.rom[o + 1], g.rom[o + 2], writer(o)) for o in sites]
    return RC.randomize_statics(entries, rng, opts, pool, bst, set(R.LEGENDARIES) & set(range(1, MAX_SPECIES + 1)),
                                log, names, R)


def _gift_sites(g):
    op = OPS[g.game]
    r = bytes(g.rom)
    starters = getattr(g, "starter_offsets", None)
    if starters is None:
        starters = {o for offs in (_starter_sites(g) or {}).values() for o in offs}
    out = []
    pat = re.compile(rb"\x2D[\x01-\xFB][\x01-\x64].[\x00\x01]", re.S)
    for m in pat.finditer(r):
        o = m.start()
        if o + 1 in starters:
            continue
        for back in (4, 5):
            w = r[o - back:o - back + 4]
            if w[0] == op["sound"] and w[2] == 0 and w[3] == op["wait"]:
                out.append(("gifts", o))
                break
    for m in re.finditer(rb"\x2E[\x01-\xFB][\x01-\x64]", r):
        o = m.start()
        if r[o - 6:o - 2] == b"\x1c\x01\x06\x06":
            out.append(("eggs", o))
    return out


def _gifts2(g, rng, opts, pool, bst, pre, log, names, pick):
    if opts["gifts"] == "off" and opts["eggs"] == "off":
        return []
    op = OPS[g.game]

    def writer(o):
        old = g.rom[o + 1]

        def write(new):
            g.rom[o + 1] = new
            for c in range(o - 14, o):
                if (g.rom[c] == op["cry"] and g.rom[c + 1] == old and g.rom[c + 2] == 0) or \
                        (g.rom[c] == op["pic"] and g.rom[c + 1] == old):
                    g.rom[c + 1] = new
        return write
    entries = [(kind, g.rom[o + 1], g.rom[o + 2], writer(o)) for kind, o in _gift_sites(g)]
    sh = _shuckle_site(g.rom)
    if sh:
        o, cp = sh

        def write_shuckle(new):
            g.rom[o + 1] = new
            if cp is not None:
                g.rom[cp + 1] = new
        entries.append(("gifts", g.rom[o + 1], g.rom[o + 6], write_shuckle))
    lines = RC.randomize_gifts(entries, rng, dict(opts, fossils="off"), pool, bst, pre, log, names, pick)
    if lines:
        log.append("Pokémon offerts 2G : les dialogues citent encore les anciens Pokémon")
    return lines


def _shuckle_site(rom):
    r = bytes(rom)
    hits = list(re.finditer(rb"\x3E\xD5\xEA..\x3E\x0F\xEA", r, re.S))
    if len(hits) != 1:
        return None
    o = hits[0].start()
    wram = r[o + 3:o + 5]
    m = re.search(rb"\xFA" + re.escape(wram) + rb"\xFE\xD5", r[o:o + 0x100])
    return o, (o + m.start() + 3 if m else None)


def _trade_table(g):
    r = bytes(g.rom)

    def ok(o):
        if r[o] > 3 or not (1 <= r[o + 1] <= MAX_SPECIES and 1 <= r[o + 2] <= MAX_SPECIES) or r[o + 31] != 0:
            return False
        for start in (3, 19):
            name = r[o + start:o + start + 11]
            if name[0] < 0x7F or 0x50 not in name:
                return False
            k = name.index(0x50)
            if any(c < 0x7F for c in name[:k]) or any(c != 0x50 for c in name[k:]):
                return False
        return True
    for o in range(0, len(r) - 32 * 6):
        if ok(o) and all(ok(o + 32 * i) for i in range(1, 5)):
            n = 5
            while o + 32 * (n + 1) <= len(r) and ok(o + 32 * n):
                n += 1
            return o, n
    return None, 0


def _trades2(g, rng, opts, pool, bst, log, names, R):
    if opts["trades"] == "off":
        return []
    o, n = _trade_table(g)
    if not n:
        log.append("Échanges en jeu : NON modifiés (table introuvable)")
        return []

    def setter(at):
        def write(v):
            g.rom[at] = v
        return write
    entries = [(g.rom[o + 32 * i + 2], g.rom[o + 32 * i + 1], setter(o + 32 * i + 2), setter(o + 32 * i + 1)) for i in range(n)]
    lines = RC.randomize_trades(entries, rng, opts, pool, bst, log, names, R)
    log.append("Échanges 2G : les surnoms et dialogues d'origine restent")
    return lines


def _parse_trainers(rom, start, end):
    out, o = [], start
    while o < end:
        k = rom.index(0x50, o)
        name = bytes(rom[o:k + 1])
        kind = rom[k + 1]
        o = k + 2
        mons = []
        while rom[o] != 0xFF:
            m = {"lv": rom[o], "sp": rom[o + 1], "item": rom[o + 2] if kind & 2 else 0,
                 "moves": list(rom[o + 2 + (1 if kind & 2 else 0):o + 6 + (1 if kind & 2 else 0)]) if kind & 1 else None}
            mons.append(m)
            o += 2 + (1 if kind & 2 else 0) + (4 if kind & 1 else 0)
        o += 1
        out.append({"name": name, "kind": kind, "mons": mons})
    return out


def _pack_trainer(t):
    out = bytearray(t["name"]) + bytes([t["kind"]])
    for m in t["mons"]:
        out += bytes([m["lv"], m["sp"]])
        if t["kind"] & 2:
            out.append(m["item"])
        if t["kind"] & 1:
            out += bytes(m["moves"])
    return bytes(out + b"\xff")


NAME_CHARS = set(range(0x80, 0x9A)) | set(range(0xA0, 0xBA)) | {0x7F, 0xE0, 0xE3, 0xE8}
CLASS_CHARS = NAME_CHARS | set(range(0xF6, 0x100)) | {0x4A, 0x54, 0xE1, 0xE2, 0xE6, 0xE7, 0xEF, 0xF3, 0xF4, 0xF5}
CLASS_FIRST = ("CHAMPION", "LEADER", "ARENALEITER", "CAPOPALESTRA", "LIDER")


def _plain2(name):
    return len(name) > 1 and name[-1] == 0x50 and all(c in NAME_CHARS for c in name[:-1])


def _class_ok(name):
    return len(name) > 1 and name[-1] == 0x50 and all(c in CLASS_CHARS for c in name[:-1])


def _shuffle_trainer_names(groups, rng):
    ts = [t for group in groups for t in group if _plain2(t["name"])]
    names = [t["name"] for t in ts]
    rng.shuffle(names)
    for t, nm in zip(ts, names):
        t["name"] = nm
    return len(ts)


def _rewrite_trainer_ptrs(g, groups):
    o = g.trainer_ptrs[0]
    for i, group in enumerate(groups):
        g.rom[g.trainer_ptr_at + 2 * i:g.trainer_ptr_at + 2 * i + 2] = (o % 0x4000 + 0x4000).to_bytes(2, "little")
        o += sum(len(_pack_trainer(t)) for t in group)


def _class_names(rom, n):
    r = bytes(rom)
    for word in CLASS_FIRST:
        o = r.find(G2.encode(word, len(word) + 1)[:len(word)] + b"\x50")
        while o >= 0:
            out, p = [], o
            for _ in range(n):
                k = r.find(b"\x50", p, p + 14)
                if k < 0 or not _class_ok(r[p:k + 1]):
                    break
                out.append((p, r[p:k + 1]))
                p = k + 1
            if len(out) == n:
                return out
            o = r.find(G2.encode(word, len(word) + 1)[:len(word)] + b"\x50", o + 1)
    return None


def _class_names2(g, rng, opts, log):
    if not opts["shuffleClassNames"]:
        return
    n = len(getattr(g, "trainer_ptrs", None) or ())
    table = _class_names(g.rom, n) if n else None
    if not table:
        log.append("Noms de classes : NON mélangés (table introuvable)")
        return
    names = [nm for _, nm in table]
    rng.shuffle(names)
    blob = b"".join(names)
    g.rom[table[0][0]:table[0][0] + len(blob)] = blob
    log.append(f"Noms mélangés : classes de dresseurs ({n} noms)")


TEXT_DELAY_RE = re.compile(rb"\xFA..\xE6\x07\x18\x02\x3E\x01\xEA..", re.S)


def _fast_text2(g, opts, log):
    if not opts["fastText"]:
        return
    hits = [m.start() for m in TEXT_DELAY_RE.finditer(bytes(g.rom))]
    if len(hits) != 1:
        log.append(f"Texte rapide : NON appliqué (code introuvable : {len(hits)} résultats)")
        return
    g.rom[hits[0] + 4] = 0x06
    log.append("Texte : vitesse « rapide » instantanée, « moyen » et « lent » accélérés (phase expérimentale)")


def _trainer_extras2(g, rng, opts, pool, bst, log, R):
    cats = ("Boss", "Important", "Regular")
    names_only = not (any(opts["extra" + c] for c in cats) or any(opts["items" + c] for c in cats))
    if names_only and not opts["shuffleTrainerNames"]:
        return
    if not getattr(g, "trainer_ptrs", None):
        log.append("Noms de dresseurs : NON mélangés (table introuvable)" if names_only
                   else "Dresseurs, équipes agrandies : NON modifiées (table introuvable)")
        return
    if names_only:
        groups = [_parse_trainers(g.rom, g.trainer_ptrs[c], g.trainer_ptrs[c + 1] if c + 1 < len(g.trainer_ptrs)
                                  else g.trainer_end) for c in range(len(g.trainer_ptrs))]
        n = _shuffle_trainer_names(groups, rng)
        blob = b"".join(_pack_trainer(t) for group in groups for t in group)
        if len(blob) == g.trainer_end - g.trainer_ptrs[0]:
            g.rom[g.trainer_ptrs[0]:g.trainer_end] = blob
            log.append(f"Noms mélangés : dresseurs ({n} noms)")
            _rewrite_trainer_ptrs(g, groups)
        return
    rom = g.rom
    ptrs, end_old = g.trainer_ptrs, g.trainer_end
    bank_end = (ptrs[0] // 0x4000 + 1) * 0x4000
    if any(rom[end_old:bank_end]):
        log.append("Dresseurs, équipes agrandies : NON modifiées (pas de place libre après les dresseurs)")
        return
    groups = [_parse_trainers(rom, ptrs[c], ptrs[c + 1] if c + 1 < len(ptrs) else end_old) for c in range(len(ptrs))]
    plans = []
    for c, group in enumerate(groups, 1):
        cat = "Boss" if c in BOSS_CLASSES else ("Important" if c in RIVAL_CLASSES else "Regular")
        for t in group:
            base = {"kind": t["kind"], "mons": [dict(m) for m in t["mons"]]}
            added = 0
            for _ in range(max(0, min(int(opts["extra" + cat] or 0), 6 - len(t["mons"])))):
                ref = max(t["mons"], key=lambda m: m["lv"])
                used = {m["sp"] for m in t["mons"]}
                sp = R._pick(rng, pool, bst, ref["sp"], True, used)
                t["mons"].append({"lv": ref["lv"], "sp": sp, "item": 0,
                                  "moves": g.moves_at_level(sp, ref["lv"]) if t["kind"] & 1 else None})
                added += 1
            items = 0
            if opts["items" + cat]:
                t["kind"] |= 2
                choices = BERRIES2 if opts["itemsConsumable"] else HELD2
                top = max(m["lv"] for m in t["mons"])
                first = next(m for m in t["mons"] if m["lv"] == top)
                for m in t["mons"]:
                    if not opts["itemsHighestOnly"] or m is first:
                        m["item"] = rng.choice(choices)
                        items += 1
            plans.append({"t": t, "cat": cat, "base": base, "added": added, "items": items})
    shuffled = _shuffle_trainer_names(groups, rng) if opts["shuffleTrainerNames"] else 0
    room = bank_end - ptrs[0]
    size = sum(len(_pack_trainer(p["t"])) for p in plans)
    skipped = 0
    order = {"Regular": 0, "Important": 1, "Boss": 2}
    for p in sorted(plans, key=lambda p: (order[p["cat"]], rng.random())):
        if size <= room:
            break
        if not (p["added"] or p["items"]):
            continue
        before = len(_pack_trainer(p["t"]))
        p["t"]["kind"], p["t"]["mons"] = p["base"]["kind"], p["base"]["mons"]
        p["added"] = p["items"] = 0
        size += len(_pack_trainer(p["t"])) - before
        skipped += 1
    if size > room:
        log.append("Dresseurs, équipes agrandies : NON modifiées (pas assez de place)")
        return
    blob = b"".join(_pack_trainer(t) for group in groups for t in group)
    rom[ptrs[0]:ptrs[0] + len(blob)] = blob
    rom[ptrs[0] + len(blob):max(end_old, ptrs[0] + len(blob))] = bytes(max(0, end_old - ptrs[0] - len(blob)))
    _rewrite_trainer_ptrs(g, groups)
    if shuffled:
        log.append(f"Noms mélangés : dresseurs ({shuffled} noms)")
    added = sum(p["added"] for p in plans)
    items = sum(p["items"] for p in plans)
    parts = []
    if added:
        parts.append(f"{added} Pokémon en plus (boss {opts['extraBoss']}, importants {opts['extraImportant']}, "
                     f"autres {opts['extraRegular']})")
    if items:
        parts.append(f"{items} objets tenus" + (" (baies seulement)" if opts["itemsConsumable"] else "")
                     + (" (plus haut niveau seulement)" if opts["itemsHighestOnly"] else ""))
    if skipped:
        parts.append(f"{skipped} dresseurs laissés tels quels faute de place dans la ROM")
    log.append("Dresseurs, équipes agrandies : " + (", ".join(parts) or "rien à changer")
               + f" ; {len(blob)} octets sur {room} disponibles dans la banque")


def randomize(src_path, options, out_path=None, fiche_base=None):
    import randomizer as R
    opts = dict(R.DEFAULTS)
    opts.update({k: v for k, v in (options or {}).items() if k in R.DEFAULTS})
    for k in ("wildLevels", "trainerLevels"):
        opts[k] = max(-50, min(200, int(opts[k] or 0)))
    for k, hi in (("minCatchRate", 255), ("fullyEvolvedAt", 100)):
        opts[k] = max(0, min(hi, int(opts[k] or 0)))
    with open(src_path, "rb") as f:
        rom = bytearray(f.read())
    g = Gen2Rom(rom)
    if not g.game:
        raise ValueError("ROM 2G non reconnue")
    seed = opts["seed"]
    if seed in (None, ""):
        seed = random.SystemRandom().randrange(1, 10 ** 9)
    seed = int(seed)
    rng = random.Random(f"{g.game}:{seed}:" + json.dumps({k: v for k, v in opts.items() if k != "seed"}, sort_keys=True))
    R._USAGE.clear()
    base_names = (fiche_base or {}).get("species", {})

    def names(sid):
        return base_names.get(str(sid), {}).get("name", f"#{sid}")

    pre = _pre_map(g)
    kids = {}
    for s_, p_ in pre.items():
        kids.setdefault(p_, []).append(s_)
    R._STAGE.clear()
    for s_ in range(1, MAX_SPECIES + 1):
        R._STAGE[s_] = 2 if s_ not in kids else (1 if s_ in pre else 0)

    def pick(rng_, pool_, bst_, old_, similar_, avoid_=()):
        return R._pick(rng_, pool_, bst_, old_, similar_, avoid_, opts["sameStage"])

    pool = [s for s in range(1, MAX_SPECIES + 1) if not (opts["noLegendaries"] and s in R.LEGENDARIES)]
    log = []
    d = Gen2Core(g)
    if opts["evolutions"] == "everyLevel":
        opts["evolutions"] = "off"
        log.append("Évolutions à chaque niveau : impossible en 2G (pas de place dans la ROM), ignoré")
    abilities_asked = opts["abilities"]
    opts["abilities"] = "off"
    with core2(R):
        order, pre_core = R._family_order(d)
        R._randomize_moves_data(d, rng, opts, log)
        R._randomize_personal(d, rng, opts, order, pre_core, log)
        bst = {s: g.bst(s) for s in range(1, MAX_SPECIES + 1)}
        R._randomize_evolutions(d, rng, opts, bst, pool, log, names)
        R._randomize_learnsets(d, rng, opts, log)
        labels = _tm_moves2(d, rng, opts, log, R)
        R._tm_compat_after(d, rng, opts, log, labels or d.tm_labels(), fiche_base)
    if fiche_base and (d.personal_changed() or d.moves_changed() or labels
                       or any(d.learnset(s) != d.l0[s] for s in range(1, MAX_SPECIES + 1))
                       or any(d.evolutions(s) != d.e0[s] for s in range(1, MAX_SPECIES + 1))):
        fiche_base = dict(fiche_base)
        _fiche2(fiche_base, fiche_base, d, labels, R)
    g.starter_offsets = {o for offs in (_starter_sites(g) or {}).values() for o in offs}
    starters = _starters(g, rng, opts, pool, pre, log, names, R)
    if starters and opts["starterText"]:
        _starter_text2(g, starters, log)
    wild_lines = _wild(g, rng, opts, pool, bst, log, names, pick, R)
    trainer_lines = _trainers(g, rng, opts, pool, bst, log, names, pick, starters, R)
    items_fr = (fiche_base or {}).get("items", {})
    sections = [("Pokémon fixes", _statics2(g, rng, opts, pool, bst, log, names, R)),
                ("Pokémon offerts", _gifts2(g, rng, opts, pool, bst, pre, log, names, pick)),
                ("Échanges", _trades2(g, rng, opts, pool, bst, log, names, R))]
    _shops2(g, rng, opts, log)
    sections.append(("Objets au sol", _field_items2(g, rng, opts, log, lambda i: items_fr.get(str(i), f"objet {i}"))))
    _trainer_extras2(g, rng, opts, pool, bst, log, R)
    _class_names2(g, rng, opts, log)
    _fast_text2(g, opts, log)
    opts["abilities"] = abilities_asked
    skipped = sorted({label for k, label in UNSUPPORTED.items() if opts.get(k) not in ("off", False, 0, None, [])})
    if skipped:
        log.append("Pas encore disponible en 2G (ignoré) : " + ", ".join(skipped))
    shiny_patch.gbc_checksum(rom)
    return _finish(src_path, out_path, rom, g.game, seed, opts, log, fiche_base, trainer_lines, wild_lines, starters, names,
                   sections)


def _finish(src_path, out_path, rom, game_key, seed, opts, log, fiche_base, trainer_lines, wild_lines, starters, names,
            sections=()):
    if out_path is None:
        root, ext = os.path.splitext(src_path)
        out_path = f"{root} ({ {'en': 'Random', 'es': 'Aleatorio'}.get(i18n.LANG, 'Aleatoire')} {seed}){ext}"
    if os.path.abspath(out_path) == os.path.abspath(src_path):
        raise ValueError("refus d'écraser la ROM d'origine")
    with open(out_path, "wb") as f:
        f.write(rom)
    stem = os.path.splitext(out_path)[0]
    fiche = dict(fiche_base or {"species": {}, "moves": {}})
    fiche["randomized"] = True
    t = shiny_patch.side_threshold(src_path)
    if t != 8:
        fiche["shinyThreshold"] = t
    with open(stem + ".pklab.json", "w", encoding="utf-8") as f:
        json.dump(fiche, f, ensure_ascii=False, separators=(",", ":"))
    report_path = stem + ".txt"
    f = io.StringIO()
    f.write(f"Randomizer PKLab\nROM d'origine : {os.path.basename(src_path)} ({game_key})\n"
            f"Graine : {seed}   Sans légendaires : {'oui' if opts['noLegendaries'] else 'non'}\n\n")
    f.write("\n".join("- " + x for x in log) + "\n")
    if trainer_lines:
        f.write("\nDresseurs importants\n" + "\n".join(trainer_lines) + "\n")
    if wild_lines:
        f.write("\nPokémon sauvages\n" + "\n".join(wild_lines) + "\n")
    for title, lines in sections:
        if lines:
            f.write(f"\n{title}\n" + "\n".join(lines) + "\n")
    with open(report_path, "w", encoding="utf-8") as out:
        out.write(i18n.tr_lines(f.getvalue()))
    return out_path, report_path, {"seed": seed, "game": game_key, "changes": log,
                                   "starters": [names(s) for s in starters.values()] if starters else None}
