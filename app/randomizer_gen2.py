import io
import json
import os
import random
import re

import gen2_maps
import i18n
import save_gen2 as G2
import shiny_patch

MAX_SPECIES = 251
TYPE_MAP = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 7: 6, 8: 7, 9: 8, 20: 9, 21: 10, 22: 11, 23: 12, 24: 13, 25: 14,
            26: 15, 27: 16}
STARTERS = (152, 155, 158)
BOSS_CLASSES = {1, 2, 3, 4, 5, 6, 7, 8, 11, 13, 14, 15, 16, 17, 18, 19, 21, 26, 35, 46, 63, 64}
RIVAL_CLASSES = {9, 42}
EVO_LEVEL, EVO_ITEM, EVO_TRADE, EVO_HAPPY, EVO_STAT = 1, 2, 3, 4, 5
UNSUPPORTED = {"types": "types des Pokémon", "abilities": "talents (n'existent pas en 2G)", "stats": "statistiques de base",
               "expCurve": "courbes d'expérience", "learnsets": "attaques apprises", "tms": "CT et CS", "tmMoves": "CT et CS",
               "tutorMoves": "tuteurs d'attaques", "tutorCompat": "tuteurs d'attaques", "evolutions": "évolutions des Pokémon",
               "movePower": "données des attaques", "moveTypes": "données des attaques", "moveAccuracy": "données des attaques",
               "movePP": "données des attaques", "moveCategory": "données des attaques", "trades": "échanges en jeu",
               "statics": "Pokémon fixes", "gifts": "Pokémon offerts", "fieldItems": "objets au sol", "fossils": "fossiles et œufs",
               "eggs": "fossiles et œufs", "shops": "objets des magasins", "wildHeldItems": "objets des Pokémon sauvages",
               "extraBoss": "Pokémon en plus (boss)", "extraImportant": "Pokémon en plus (importants)",
               "extraRegular": "Pokémon en plus (autres)", "itemsBoss": "objets des dresseurs", "itemsImportant": "objets des dresseurs",
               "itemsRegular": "objets des dresseurs", "doubleBattles": "combats doubles", "shuffleTrainerNames": "noms de dresseurs",
               "shuffleClassNames": "noms de classes", "runIndoors": "réglages du jeu", "startShoes": "réglages du jeu",
               "fastText": "réglages du jeu"}


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
        if i < 0:
            raise ValueError("2G : table des évolutions introuvable")
        bank = i // 0x4000
        ga = (i % 0x4000 + 0x4000).to_bytes(2, "little")
        t = rom.find(ga, bank * 0x4000, bank * 0x4000 + 0x4000)
        if t < 0:
            raise ValueError("2G : pointeurs des évolutions introuvables")
        self.evo_at = {}
        for s in range(1, MAX_SPECIES + 1):
            p = _ptr(rom, bank, t + 2 * (s - 1))
            if p is None:
                raise ValueError("2G : pointeur d'évolution invalide")
            self.evo_at[s] = p

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
    bst = {s: g.bst(s) for s in range(1, MAX_SPECIES + 1)}
    log = []
    if opts["minCatchRate"]:
        for s in range(1, MAX_SPECIES + 1):
            g.raise_catch_rate(s, opts["minCatchRate"])
        log.append(f"Taux de capture minimum : {opts['minCatchRate']}")
    starters = _starters(g, rng, opts, pool, pre, log, names, R)
    wild_lines = _wild(g, rng, opts, pool, bst, log, names, pick, R)
    trainer_lines = _trainers(g, rng, opts, pool, bst, log, names, pick, starters, R)
    skipped = sorted({label for k, label in UNSUPPORTED.items() if opts.get(k) not in ("off", False, 0, None, [])})
    if skipped:
        log.append("Pas encore disponible en 2G (ignoré) : " + ", ".join(skipped))
    shiny_patch.gbc_checksum(rom)
    return _finish(src_path, out_path, rom, g.game, seed, opts, log, fiche_base, trainer_lines, wild_lines, starters, names)


def _finish(src_path, out_path, rom, game_key, seed, opts, log, fiche_base, trainer_lines, wild_lines, starters, names):
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
    with open(report_path, "w", encoding="utf-8") as out:
        out.write(i18n.tr_lines(f.getvalue()))
    return out_path, report_path, {"seed": seed, "game": game_key, "changes": log,
                                   "starters": [names(s) for s in starters.values()] if starters else None}
