import os
import struct
from collections import Counter
from contextlib import contextmanager

import ctr_rom

MOVES = {"XY": "a/2/1/2", "ORAS": "a/1/8/9", "SM": "a/0/1/1", "USUM": "a/0/1/1"}
MAX_ABILITY = {"XY": 188, "ORAS": 191, "SM": 232, "USUM": 233}
HM_COUNT = {"XY": 5, "ORAS": 7, "SM": 0, "USUM": 0}
MAX_ITEM = {"XY": 717, "ORAS": 775, "SM": 920, "USUM": 959}
_CT = [f"CT{i:02d}" for i in range(1, 101)]
TM_ORDER = {"XY": _CT[:92] + [f"CS{i:02d}" for i in range(1, 6)] + _CT[92:],
            "ORAS": _CT[:92] + [f"CS{i:02d}" for i in range(1, 7)] + _CT[92:] + ["CS07"],
            "SM": _CT, "USUM": _CT}
FIELD_TMS = {"XY": {"CT70", "CT94"}, "ORAS": {"CT70", "CT94"}, "SM": set(), "USUM": set()}
HM_MOVES = {15, 19, 57, 70, 127, 249, 291}
FORM_ABILITIES = {176, 197, 208, 209, 210, 211, 225}
Z_MOVES = {*range(622, 659), *range(695, 704), 719, *range(723, 729)}
PERSONAL_KEYS = {"types", "dualTypes", "abilities", "banWonderGuard", "twoAbilities", "banTrapping", "banNegative",
                 "banUseless", "stats", "expCurve", "minCatchRate", "wildHeldItems", "learnsets", "noGameBreaking",
                 "goodDamaging", "reorderDamaging", "tms", "fullHM", "tmSanity", "movePower", "moveTypes",
                 "moveAccuracy", "movePP", "moveCategory", "tmMoves", "keepFieldTMs", "tutorMoves", "tutorCompat",
                 "tutorSanity", "shops"}


@contextmanager
def core(R, max_species, max_move, max_ability):
    saved = (R.MAX_SPECIES, R.MAX_MOVE, R.MAX_ABILITY, R.NUM_TYPES, R.ALWAYS_BANNED_ABILITIES)
    R.MAX_SPECIES, R.MAX_MOVE, R.MAX_ABILITY, R.NUM_TYPES = max_species, max_move, max_ability, 18
    R.ALWAYS_BANNED_ABILITIES = set(saved[4]) | FORM_ABILITIES
    try:
        yield
    finally:
        R.MAX_SPECIES, R.MAX_MOVE, R.MAX_ABILITY, R.NUM_TYPES, R.ALWAYS_BANNED_ABILITIES = saved


def mini_split(blob):
    n = struct.unpack_from("<H", blob, 2)[0]
    offs = struct.unpack_from(f"<{n + 1}I", blob, 4)
    return blob[:offs[0]], [blob[offs[i]:offs[i + 1]] for i in range(n)], blob[offs[n]:]


class CtrData:
    def __init__(self, family, pfiles, rec, mfiles, learn, ev, max_species):
        self.family, self.rec, self.ev, self.max = family, rec, ev, max_species
        self.p = [bytearray(x) for x in pfiles]
        self.p0 = [bytes(x) for x in pfiles]
        self.mini = len(mfiles) == 1 and mfiles[0][:2] == b"WD"
        if self.mini:
            self.mhead, ent, self.mtail = mini_split(mfiles[0])
        else:
            ent = mfiles
        self.mv = [bytearray(x) for x in ent]
        self.m0 = [bytes(x) for x in ent]
        self.learn = [bytearray(x) for x in learn]
        self.l0 = [bytes(x) for x in learn]
        self.max_move = len(self.mv) - 1
        self.tm_count, self.hm_count = 100, HM_COUNT[family]
        self.max_item = MAX_ITEM[family]
        self.banned_moves = {m for m in Z_MOVES if m <= self.max_move}

    def stats(self, s):
        return list(self.p[s][0:6])

    def set_stats(self, s, v):
        self.p[s][0:6] = bytes(v)

    def types(self, s):
        return self.p[s][6], self.p[s][7]

    def set_types(self, s, t1, t2):
        self.p[s][6], self.p[s][7] = t1, t2

    def abilities(self, s):
        return list(self.p[s][0x18:0x1B])

    def set_abilities(self, s, a):
        a1, a2, a3 = (list(a) + [0, 0, 0])[:3]
        self.p[s][0x18:0x1B] = bytes([a1, a2 or a1, a3 or a1])

    def set_growth(self, s, v):
        self.p[s][0x15] = v

    def raise_catch_rate(self, s, v):
        self.p[s][8] = max(self.p[s][8], v)

    def held_item_pool(self):
        import randomizer as R
        return [i for i in R.HELD_ITEMS if i <= self.max_item]

    def set_held_items(self, s, items):
        struct.pack_into("<3H", self.p[s], 0xC, *(list(items) + [0, 0, 0])[:3])

    def tm_bits(self, s):
        return int.from_bytes(self.p[s][0x28:0x38], "little")

    def set_tm_bits(self, s, bits):
        self.p[s][0x28:0x38] = bits.to_bytes(16, "little")

    def bst(self, s):
        return sum(self.p[s][0:6])

    def move(self, m):
        e = self.mv[m]
        return {"type": e[0], "cat": e[2], "power": e[3], "acc": e[4], "pp": e[5]}

    def set_move(self, m, d):
        e = self.mv[m]
        e[0], e[2], e[3], e[4], e[5] = d["type"], d["cat"], d["power"], d["acc"], d["pp"]

    def learnset(self, s):
        e = self.learn[s] if s < len(self.learn) else b""
        out = []
        for i in range(0, len(e) - 3, 4):
            m, lv = struct.unpack_from("<hh", e, i)
            if m < 0:
                break
            out.append([m, lv])
        return out

    def set_learnset(self, s, entries):
        for i, (m, lv) in enumerate(entries):
            struct.pack_into("<hh", self.learn[s], 4 * i, m, lv)

    def evolutions(self, s):
        return self.ev.evolutions(s)

    def set_evo(self, s, slot, method, param, target):
        self.ev.set_evo(s, slot, method, param, target)

    def clear_evolutions(self, s):
        self.ev.clear_evolutions(s)

    def set_evo_target(self, s, slot, target):
        self.ev.set_evo_target(s, slot, target)

    def personal_files(self):
        out = [bytes(x) for x in self.p]
        last = bytearray(out[-1])
        for s in range(len(out) - 1):
            if out[s] != self.p0[s] and self.rec * (s + 1) <= len(last):
                last[self.rec * s:self.rec * (s + 1)] = out[s]
        out[-1] = bytes(last)
        return out

    def personal_changed(self):
        return any(bytes(x) != y for x, y in zip(self.p, self.p0))

    def move_files(self):
        ent = [bytes(x) for x in self.mv]
        if not self.mini:
            return ent
        return [self.mhead + b"".join(ent) + self.mtail]

    def moves_changed(self):
        return any(bytes(x) != y for x, y in zip(self.mv, self.m0))

    def learn_files(self):
        return [bytes(x) for x in self.learn]

    def learn_changed(self):
        return any(bytes(x) != y for x, y in zip(self.learn, self.l0))


def base_tm_labels(base):
    labels = {}
    for sp in (base or {}).get("species", {}).values():
        for lab, mv in sp.get("tm", []):
            labels.setdefault(lab, mv)
    return labels


def tm_table(code, family, base):
    labels = base_tm_labels(base)
    order = TM_ORDER[family]
    if not all(lab in labels for lab in order):
        return None, labels
    o = code.find(struct.pack(f"<{len(order)}H", *[labels[lab] for lab in order]))
    return (o if o >= 0 else None), labels


def randomize_tm_moves(d, code, rng, opts, log, base, R):
    if opts["tmMoves"] == "off":
        return None, []
    off, labels = tm_table(code, d.family, base)
    if off is None:
        log.append("CT : NON modifiées (table introuvable dans ce jeu)")
        return None, []
    order = TM_ORDER[d.family]
    labels = {lab: labels[lab] for lab in order}
    moves = {m: d.move(m) for m in range(1, d.max_move + 1)}
    banned = {R.STRUGGLE, R.METRONOME if opts["learnsets"] == "metronome" else 0} | HM_MOVES | d.banned_moves
    if opts["noGameBreaking"]:
        banned |= R.GAME_BREAKING_MOVES
    keep = {lab for lab in order if lab.startswith("CS") or (opts["keepFieldTMs"] and lab in FIELD_TMS[d.family])}
    used = {labels[lab] for lab in keep}
    pool = [m for m in range(1, d.max_move + 1) if m not in banned and m not in used]
    good = [m for m in pool if moves[m]["cat"] != 0 and moves[m]["power"] >= 70]
    pct = max(0, min(100, int(opts["goodDamaging"] or 0)))
    for lab in order:
        if lab in keep:
            continue
        src = good if pct and rng.random() * 100 < pct else pool
        src = [m for m in src if m not in used] or [m for m in pool if m not in used]
        labels[lab] = rng.choice(src)
        used.add(labels[lab])
    data = struct.pack(f"<{len(order)}H", *[labels[lab] for lab in order])
    log.append("Attaques des CT : aléatoires" + (" (CS gardées" + (", Flash/Éclate-Roc gardées" if opts["keepFieldTMs"] else "")
                                                 + ")" if d.hm_count else "") + " ; programme du jeu modifié (correctif code.ips)")
    return labels, [(off, data)]


TUTOR_HEAD = (450, 343, 162, 530, 324, 442, 402, 529, 340, 67, 441, 253, 9, 7, 8)


def _tutor_groups(code, o, sep):
    groups, p = [], o
    for _ in range(4):
        n = 0
        while n < 40 and struct.unpack_from("<H", code, p + 2 * n)[0] != sep:
            n += 1
        if n == 40:
            return []
        groups.append((p, n))
        p += 2 * n + 2
    return groups


def tutor_tables(code, family, sep):
    head = struct.pack("<15H", *TUTOR_HEAD)
    old = code.find(head + struct.pack("<H", sep))
    groups = _tutor_groups(code, old, sep) if old >= 0 else []
    if family == "ORAS":
        return {"tables": groups, "bits": [(0x40 + 4 * i, n) for i, (_, n) in enumerate(groups)]} if groups else None
    if family == "USUM":
        o = code.find(head + struct.pack("<H", 277))
        if o < 0:
            return None
        return {"tables": [(o, 67)], "bits": [(0x3C, 67)], "mirror": groups}
    return None


def randomize_tutors(d, code, rng, opts, log, labels, R):
    if opts["tutorMoves"] == "off" and opts["tutorCompat"] == "off" and not opts["tutorSanity"]:
        return []
    t = tutor_tables(code, d.family, d.max_move + 1) if code else None
    if not t:
        log.append("Tuteurs : aucun tuteur modifiable dans ce jeu" if d.family in ("XY", "SM") else "Tuteurs : NON modifiés (table introuvable)")
        return []
    groups = [list(struct.unpack_from(f"<{n}H", code, o)) for o, n in t["tables"]]
    old = [list(x) for x in groups]
    records = []
    if opts["tutorMoves"] == "random":
        banned = {R.STRUGGLE} | HM_MOVES | d.banned_moves | (R.GAME_BREAKING_MOVES if opts["noGameBreaking"] else set()) \
            | set((labels or {}).values())
        pool = [m for m in range(1, d.max_move + 1) if m not in banned]
        good = [m for m in pool if d.move(m)["cat"] != 0 and d.move(m)["power"] >= 70]
        pct = max(0, min(100, int(opts["goodDamaging"] or 0)))
        used = set()
        for grp in groups:
            for i in range(len(grp)):
                src = good if pct and rng.random() * 100 < pct else pool
                src = [m for m in src if m not in used] or [m for m in pool if m not in used]
                grp[i] = rng.choice(src)
                used.add(grp[i])
        for (o, n), grp in zip(t["tables"], groups):
            records.append((o, struct.pack(f"<{n}H", *grp)))
        remap = {a: b for go, gn in zip(old, groups) for a, b in zip(go, gn)}
        for o, n in t.get("mirror", []):
            vals = struct.unpack_from(f"<{n}H", code, o)
            records.append((o, struct.pack(f"<{n}H", *[remap.get(v, v) for v in vals])))
    for s in range(1, d.max + 1):
        types = set(R._type_list(*d.types(s)))
        learned = {mv for mv, _ in d.learnset(s)}
        for (bo, n), grp in zip(t["bits"], groups):
            nb = (n + 7) // 8
            raw = int.from_bytes(d.p[s][bo:bo + nb], "little")
            mask = (1 << n) - 1
            bits = raw & mask
            if opts["tutorCompat"] == "all":
                bits = mask
            elif opts["tutorCompat"] in ("random", "type"):
                count = bin(bits).count("1")
                cands = list(range(n))
                wt = [4.0 if opts["tutorCompat"] == "type" and d.move(grp[i])["type"] in types else 1.0 for i in cands]
                chosen = set()
                while len(chosen) < count and cands:
                    k = rng.choices(range(len(cands)), weights=wt)[0]
                    chosen.add(cands.pop(k))
                    wt.pop(k)
                bits = sum(1 << i for i in chosen)
            if opts["tutorSanity"]:
                for i, mv in enumerate(grp):
                    if mv in learned:
                        bits |= 1 << i
            d.p[s][bo:bo + nb] = ((raw & ~mask) | bits).to_bytes(nb, "little")
    total = sum(len(x) for x in groups)
    log.append(f"Tuteurs ({total}) : " + ", ".join(x for x, on in (
        ("attaques aléatoires (programme du jeu modifié, correctif code.ips)", opts["tutorMoves"] == "random"),
        ({"random": "compatibilité aléatoire (même nombre)", "type": "compatibilité aléatoire, types du Pokémon privilégiés",
          "all": "tous compatibles"}.get(opts["tutorCompat"], ""), opts["tutorCompat"] != "off"),
        ("attaques apprises par niveau compatibles", opts["tutorSanity"])) if on))
    return records


FOSSILS = {138, 140, 142, 345, 347, 408, 410, 564, 566, 696, 698}
GIFT_LABEL = {"gifts": "", "fossils": "Fossile : ", "eggs": "Œuf : "}


def randomize_gifts(entries, rng, opts, pool, bst, pre, log, names, pick):
    basics = [x for x in pool if x not in pre]
    lines, count, used = [], {"gifts": 0, "fossils": 0, "eggs": 0}, set()
    for kind, old, lv, write in entries:
        if opts[kind] == "off":
            continue
        if kind == "eggs":
            new = rng.choice([x for x in basics if x != old] or pool)
        elif kind == "fossils":
            new = pick(rng, pool, bst, old, opts["fossilSimilar"], used)
            used.add(new)
        else:
            new = pick(rng, pool, bst, old, opts["giftSimilar"])
        write(new)
        count[kind] += 1
        lines.append(f"  {GIFT_LABEL[kind]}{names(old)} -> {names(new)} Nv{lv}")
    if opts["gifts"] != "off":
        log.append(f"Pokémon offerts : {count['gifts']} changés" + (", force similaire" if opts["giftSimilar"] else "")
                   + " (fossiles et œufs à part)")
    if opts["fossils"] != "off":
        log.append(f"Fossiles : {count['fossils']} remplacés" + (", force similaire" if opts["fossilSimilar"] else ""))
    if opts["eggs"] != "off":
        log.append(f"Œufs offerts : {count['eggs']} remplacés (Pokémon de base)")
    return lines


def randomize_statics(entries, rng, opts, pool, bst, legend, log, names, R):
    if opts["statics"] == "off":
        return []
    legend_pool = sorted(x for x in legend if x in bst)
    mapping, lines = {}, []
    for old, lv, write in entries:
        if old not in mapping:
            if opts["statics"] == "swap" and old in legend:
                mapping[old] = R._pick(rng, legend_pool, bst, old, True, set(mapping.values()) | {old})
            else:
                src = [x for x in pool if (x in legend) == (old in legend)] if opts["statics"] == "swap" else pool
                mapping[old] = R._pick(rng, src or pool, bst, old, True, set(mapping.values()))
            lines.append(f"  {names(old)} Nv{lv} -> {names(mapping[old])}")
        write(mapping[old], lv)
    log.append(f"Pokémon fixes (légendaires, rencontres scriptées) : {len(entries)} rencontres, {len(mapping)} espèces remplacées ("
               + ("légendaires ↔ légendaires" if opts["statics"] == "swap" else "force similaire") + ")")
    return lines


def randomize_trades(entries, rng, opts, pool, bst, log, names, R):
    if opts["trades"] == "off":
        return []
    lines = []
    for i, (got, asked, write_got, write_asked) in enumerate(entries):
        new_got = R._pick(rng, pool, bst, got, False)
        write_got(new_got)
        new_asked = asked
        if opts["trades"] == "both" and 0 < asked:
            new_asked = R._pick(rng, pool, bst, asked, False, {new_got})
            write_asked(new_asked)
        lines.append(f"  Échange {i} : donne {names(asked)}→{names(new_asked)}, reçoit {names(got)}→{names(new_got)}" if asked
                     else f"  Échange {i} : donne un Pokémon au choix, reçoit {names(got)}→{names(new_got)}")
    log.append(f"Échanges en jeu : {len(lines)} échanges ("
               + ("Pokémon reçus et demandés" if opts["trades"] == "both" else "Pokémon reçus") + ")")
    return lines


CTR_TM_ITEMS = set(range(328, 428)) | set(range(618, 621)) | set(range(690, 695)) | {737}
SHOP_SIG = {"XY": (4, 17, 4, 3), "ORAS": (4, 17, 18, 4), "SM": (4, 17, 18, 22), "USUM": (4, 17, 18, 22)}


def shop_lists(blob, family, max_item):
    lo = blob.find(struct.pack("<4H", *SHOP_SIG[family]))
    if lo < 0:
        return []
    head = struct.unpack_from("<200H", blob, lo)
    idx = [i for i, x in enumerate(head) if x == 4][:6]
    if len(idx) < 6:
        return []
    co = blob.find(bytes(b - a for a, b in zip(idx, idx[1:])))
    if co < 0:
        return []
    out, p, i = [], lo, co
    while 0 < blob[i] <= 60:
        vals = list(struct.unpack_from(f"<{blob[i]}H", blob, p))
        if any(v == 0 or v > max_item for v in vals):
            break
        out.append((p, vals))
        p += 2 * blob[i]
        i += 1
    return out


def randomize_shops(blob, family, max_item, rng, opts, log, items):
    if opts["shops"] == "off":
        return []
    shops = shop_lists(blob, family, max_item) if blob else []
    if not shops:
        log.append("Magasins : NON modifiés (table introuvable)")
        return []
    keep = lambda it: (it == 4 or it in CTR_TM_ITEMS
                       or str(items.get(str(it), "")).startswith(("CT", "CS")))
    lists = [list(v) for _, v in shops]
    pool_items = sorted({it for l in lists for it in l if not keep(it)})
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
                    l[k] = rng.choice(pool_items)
    for l in lists:
        for k in range(len(l)):
            if l.index(l[k]) != k and not keep(l[k]):
                free = [x for x in pool_items if x not in l]
                if free:
                    l[k] = rng.choice(free)
    changed = sum(a != b for (_, x), y in zip(shops, lists) for a, b in zip(x, y))
    log.append(f"Magasins : {len(lists)} boutiques, {changed} objets changés (CT et Poké Ball de base gardées) - "
               + ("mélangés" if opts["shops"] == "shuffle" else "parmi les objets vendus dans le jeu"))
    return [(p, struct.pack(f"<{len(l)}H", *l)) for (p, _), l in zip(shops, lists)]


AMX_MAGIC = b"\xe0\xf1\x0a\x0a"
CTR_HM_ITEMS = set(range(420, 428)) | {737}
FIELD_SCRIPTS = {"XY": "a/0/3/1", "ORAS": "a/0/2/9"}


def amx_code(s):
    size, _, _, _, istart, _, final, _ = struct.unpack_from("<IIHHIIII", s, 0)
    count = (final - istart) // 4
    code, x, j, f = [], 0, 0, istart
    while len(code) < count and f < size:
        b = s[f]
        f += 1
        v = b & 0x7F
        j += 1
        x = (v - 0x80 if v & 0x40 else v) if j == 1 else (x << 7) | v
        if b & 0x80:
            continue
        code.append(x & 0xFFFFFFFF)
        j = 0
    if len(code) != count or f != size:
        raise ValueError("script AMX illisible")
    return code


def amx_pack(s, code):
    istart = struct.unpack_from("<I", s, 0x0C)[0]
    out = bytearray(s[:istart])
    for v in code:
        n = v - (1 << 32) if v >> 31 else v
        k = 1
        while not -(1 << (7 * k - 1)) <= n < 1 << (7 * k - 1):
            k += 1
        m = v if k == 5 else n
        for i in range(k - 1, -1, -1):
            out.append((m >> (7 * i)) & 0x7F | (0x80 if i else 0))
    struct.pack_into("<I", out, 0, len(out))
    return bytes(out)


def item_table(code, max_item, min_count=100):
    n = len(code)
    k = 0
    while (3 * k + 3 <= n and code[n - 1 - 3 * k] == code[n - 1] - k
           and 1 <= code[n - 3 - 3 * k] <= max_item and 1 <= code[n - 2 - 3 * k] <= 99):
        k += 1
    if k < min_count or code[n - 1] - k + 1 not in (0, 1):
        return None
    return n - 3 * k


def field_item_tables(scripts, max_item):
    out = []
    for i, s in enumerate(scripts):
        if isinstance(s, list) or s[4:8] != AMX_MAGIC:
            continue
        try:
            code = amx_code(s)
        except (ValueError, IndexError, struct.error):
            continue
        start = item_table(code, max_item)
        if start is not None:
            out.append((i, code, start))
    return out


def field_item_picks(groups, family, max_item, pockets, rng, mode, balance):
    six = family in ("XY", "ORAS")
    fixed = lambda it: pockets.get(it) in ((4,) if six else (4, 5, 6)) or it in CTR_HM_ITEMS
    is_tm = lambda it: it in CTR_TM_ITEMS and it not in CTR_HM_ITEMS
    every = [it for g in groups for it in g]
    tms_all = sorted(it for it in CTR_TM_ITEMS - CTR_HM_ITEMS if it <= max_item)
    tms = [t for t in tms_all if t not in every]
    common = sorted({it for it in every if not fixed(it) and not is_tm(it)})
    out = []
    for old in groups:
        movable = [k for k, it in enumerate(old) if not fixed(it)]
        new = list(old)
        if mode == "shuffle":
            vals = [old[k] for k in movable]
            rng.shuffle(vals)
            for k, v in zip(movable, vals):
                new[k] = v
        else:
            for k in movable:
                if is_tm(old[k]):
                    pick = rng.choice(tms or tms_all)
                    if pick in tms:
                        tms.remove(pick)
                    new[k] = pick
                else:
                    new[k] = rng.choice(common)
            if balance:
                small = [it for it in common if it < 64]
                extra = sum((v >= 64) - (o >= 64) for v, o in zip(new, old))
                big = [k for k in movable if new[k] >= 64 and not is_tm(new[k])]
                rng.shuffle(big)
                while extra > 0 and big and small:
                    new[big.pop()] = rng.choice(small)
                    extra -= 1
                if extra > 0:
                    new = [n if (n >= 64) == (o >= 64) else o for n, o in zip(new, old)]
        out.append(new)
    return out


def field_items_log(log, opts, total, changed):
    log.append(f"Objets au sol : {total} objets, {changed} changés - "
               + ("mélangés" if opts["fieldItems"] == "shuffle" else "aléatoires (CT -> CT)") + ", objets rares gardés")


def randomize_field_items(scripts, family, max_item, pockets, rng, opts, log, items):
    if opts["fieldItems"] == "off":
        return None, []
    tables = field_item_tables(scripts, max_item)
    if not tables:
        log.append("Objets au sol : NON modifiés (objets introuvables)")
        return None, []
    name = lambda i: items.get(str(i), f"objet {i}")
    groups = [[c[p] for p in range(st, len(c), 3)] for _, c, st in tables]
    picks = field_item_picks(groups, family, max_item, pockets, rng, opts["fieldItems"], True)
    new_scripts = list(scripts)
    lines = []
    total = changed = 0
    for (i, code, st), old, new in zip(tables, groups, picks):
        code = list(code)
        for p, it in zip(range(st, len(code), 3), new):
            code[p] = it
        packed = amx_pack(scripts[i], code)
        if len(packed) > struct.unpack_from("<I", scripts[i], 0)[0]:
            raise ValueError("objets au sol : script trop grand")
        new_scripts[i] = packed
        total += len(old)
        changed += sum(a != b for a, b in zip(old, new))
        lines += [f"  {name(a)} -> {name(b)}" for a, b in zip(old, new) if a != b]
    field_items_log(log, opts, total, changed)
    return new_scripts, lines


def event_item_sites(ed, max_item):
    if ed[:2] != b"ED":
        return []
    n = struct.unpack_from("<H", ed, 2)[0]
    offs = struct.unpack_from(f"<{n + 1}I", ed, 4)
    out = []
    for si in range(n):
        base, end = offs[si], offs[si + 1]
        if ed[base:base + 2] != b"EI" or end - base < 8:
            continue
        v = struct.unpack_from("<H", ed, base + 2)[0]
        if end - base < 8 + 4 * v:
            continue
        tabs = [struct.unpack_from("<I", ed, base + 4)[0]] + list(struct.unpack_from(f"<{v}I", ed, base + 8))
        if tabs[0] != 8 + 4 * v or tabs[-1] != end - base:
            continue
        for t in range(v):
            lo, hi = base + tabs[t], base + tabs[t + 1]
            if lo == hi:
                continue
            count = struct.unpack_from("<I", ed, lo)[0]
            if 4 + count * 0x5C != hi - lo:
                return []
            for k in range(count):
                e = lo + 4 + k * 0x40 + 0x30
                it, zero, q = struct.unpack_from("<HHH", ed, e)
                if not (1 <= it <= max_item and zero == 0 and 1 <= q <= 99):
                    return []
                out.append(e)
    return out


def randomize_core(g, d, ev, rng, opts, pool, log, names, base, src_path, R):
    import ctr_rom
    if not d.hm_count:
        opts["fullHM"] = False
    order, pre = R._family_order(d)
    R._randomize_moves_data(d, rng, opts, log)
    R._randomize_personal(d, rng, opts, order, pre, log)
    bst = {s: d.bst(s) for s in range(1, d.max + 1)}
    evo_changes = R._randomize_evolutions(ev, rng, opts, bst, pool, log, names, d.max)
    g.evos = [bytes(e) for e in ev.data]
    R._randomize_learnsets(d, rng, opts, log)
    labels, ips = None, []
    tutors = opts["tutorMoves"] != "off" or opts["tutorCompat"] != "off" or opts["tutorSanity"]
    six = d.family in ("XY", "ORAS")
    code = ctr_rom.exefs_code(src_path) if (opts["tmMoves"] != "off" or (tutors and d.family in ("ORAS", "USUM"))
                                            or (six and opts["shops"] != "off")) else None
    if opts["tmMoves"] != "off":
        labels, ips = randomize_tm_moves(d, code, rng, opts, log, base, R)
    R._tm_compat_after(d, rng, opts, log, labels, base)
    ips += randomize_tutors(d, code, rng, opts, log, labels, R)
    if six:
        ips += randomize_shops(code, d.family, d.max_item, rng, opts, log, (base or {}).get("items", {}))
    return bst, evo_changes, labels, ips


def write_ips(out_path, records, src_path):
    if not records:
        return
    folder = out_path + ".exefsdir"
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "code.ips")
    src = os.path.join(src_path + ".exefsdir", "code.ips")
    body = bytearray(b"PATCH")
    if os.path.isfile(src):
        with open(src, "rb") as f:
            old = f.read()
        if old[:5] == b"PATCH" and old[-3:] == b"EOF":
            body = bytearray(old[:-3])
    for o, data in records:
        for k in range(0, len(data), 0xFFFF):
            chunk = data[k:k + 0xFFFF]
            body += (o + k).to_bytes(3, "big") + len(chunk).to_bytes(2, "big") + chunk
    body += b"EOF"
    with open(path, "wb") as f:
        f.write(body)


def read_ips(path):
    with open(path, "rb") as f:
        b = f.read()
    out, p = [], 5
    while b[p:p + 3] != b"EOF":
        o = int.from_bytes(b[p:p + 3], "big")
        n = int.from_bytes(b[p + 3:p + 5], "big")
        out.append((o, b[p + 5:p + 5 + n]))
        p += 5 + n
    return out


def fiche_update(fiche, base, d, labels, R):
    if not base or "species" not in fiche:
        return
    tnames = base.get("typeNames") or (R.TYPE_FR + ["Fée"])
    if d.moves_changed():
        moves = dict(fiche.get("moves", {}))
        for k, v in moves.items():
            m = int(k)
            if 0 < m <= d.max_move:
                x = d.move(m)
                moves[k] = [v[0], tnames[x["type"]] if x["type"] < len(tnames) else "?",
                            x["power"] if x["power"] > 1 else None, x["acc"] if 0 < x["acc"] <= 100 else None]
        fiche["moves"] = moves
    pers, learn = d.personal_changed(), d.learn_changed()
    if not (pers or learn or labels):
        return
    names = labels or base_tm_labels(base)
    order = sorted(names, key=lambda x: (x[:2] == "CS", int(x[2:])))
    bit = {lab: int(lab[2:]) - 1 + (100 if lab.startswith("CS") else 0) for lab in order}
    species = {k: dict(v) for k, v in fiche["species"].items()}
    for s in range(1, d.max + 1):
        sp = species.get(str(s))
        if sp is None:
            continue
        if pers:
            sp["types"] = [tnames[t] for t in R._type_list(*d.types(s)) if t < len(tnames)]
            ab, abil = d.abilities(s), []
            for i, a in enumerate(ab):
                if a and (i == 0 or a not in ab[:i]):
                    nm = base.get("abilities", {}).get(str(a), f"#{a}")
                    abil.append([nm, i == 2])
            sp["ab"] = abil
            st = d.stats(s)
            sp["st"] = [st[0], st[1], st[2], st[4], st[5], st[3]]
        if pers or labels:
            bits = d.tm_bits(s)
            sp["tm"] = [[lab, names[lab]] for lab in order if bits >> bit[lab] & 1]
        if learn:
            sp["lv"] = [[lv, mv] for mv, lv in d.learnset(s)]
        species[str(s)] = sp
    fiche["species"] = species


TRAINER_EXTRA_KEYS = {"extraBoss", "extraImportant", "extraRegular", "itemsBoss", "itemsImportant", "itemsRegular",
                      "itemsConsumable", "itemsHighestOnly", "doubleBattles"}
LABELS = {"trainers": "dresseurs", "starters": "starters", "fieldItems": "objets au sol", "trades": "échanges",
          "fastText": "texte rapide", "starterText": "texte de l'écran des starters", "doubleBattles": "combats doubles",
          "extraBoss": "Pokémon en plus chez les dresseurs", "extraImportant": "Pokémon en plus chez les dresseurs",
          "extraRegular": "Pokémon en plus chez les dresseurs"}
BOSS_CLASSES = ("Champion", "Conseil 4", "Maître", "Capitaine", "Doyen", "Arène de Kanto")
IMPORTANT_CLASSES = ("Boss Team", "Leader Team", "Admin Team", "Présidente", "Directeur", "Professeur Pokémon")
CATEGORY_KEYS = ("Boss", "Important", "Regular")


def trainer_category(cname, species, starter_species):
    if any(w in cname for w in BOSS_CLASSES):
        return "Boss"
    if any(w in cname for w in IMPORTANT_CLASSES) or (cname.startswith("Dresse") and set(species) & starter_species):
        return "Important"
    return "Regular"


def extras_wanted(opts):
    return any(opts["extra" + c] for c in CATEGORY_KEYS) or any(opts["items" + c] for c in CATEGORY_KEYS) or opts["doubleBattles"]


def give_items(mons, rng, opts, R):
    choices = R.BERRIES if opts["itemsConsumable"] else R.HELD_ITEMS
    top = max(m["lv"] for m in mons)
    first = next(m for m in mons if m["lv"] == top)
    n = 0
    for m in mons:
        if not opts["itemsHighestOnly"] or m is first:
            m["item"] = rng.choice(choices)
            n += 1
    return n


def extras_log(log, opts, added, items, doubles, skipped):
    parts = []
    if added:
        parts.append(f"{added} Pokémon en plus (boss {opts['extraBoss']}, importants {opts['extraImportant']}, "
                     f"autres {opts['extraRegular']})")
    if items:
        parts.append(f"{items} objets tenus" + (" (baies seulement)" if opts["itemsConsumable"] else "")
                     + (" (plus haut niveau seulement)" if opts["itemsHighestOnly"] else ""))
    if doubles:
        parts.append(f"{doubles} dresseurs en combat double (phase expérimentale)")
    if skipped:
        parts.append(f"{skipped} dresseurs laissés tels quels faute de place dans la ROM")
    log.append("Dresseurs, équipes agrandies : " + (", ".join(parts) or "rien à changer"))


NAME_TEXTS = {"XY": ("a/0/7/", range(2, 10), 21, 20), "ORAS": ("a/0/7/", range(1, 9), 22, 21),
              "SM": ("a/0/3/", range(10), 105, 106), "USUM": ("a/0/3/", range(10), 110, 111)}


def _plain_name(chars):
    chars = list(chars)
    while chars and chars[-1] == 0:
        chars.pop()
    return bool(chars) and all(0x20 <= c < 0xE000 and c != 0x10 for c in chars)


def name_files(family, opts):
    pref, langs, tn, cn = NAME_TEXTS[family]
    idx = [i for k, i in (("shuffleTrainerNames", tn), ("shuffleClassNames", cn)) if opts[k]]
    return [pref + str(lang) for lang in langs] if idx else [], idx


def shuffle_names(sources, family, rng, opts, log):
    pref, langs, tn, cn = NAME_TEXTS[family]
    jobs = [(k, i) for k, i in (("shuffleTrainerNames", tn), ("shuffleClassNames", cn)) if opts[k]]
    out, done = {}, []
    for key, i in jobs:
        texts = {p: ctr_rom.text_raw(f[i]) for p, f in sources.items() if f.get(i)}
        if not texts:
            continue
        n = Counter(len(t) for t in texts.values()).most_common(1)[0][0]
        texts = {p: t for p, t in texts.items() if len(t) == n}
        ok = [j for j in range(1, n) if all(_plain_name(t[j][0]) for t in texts.values())]
        perm = ok[:]
        rng.shuffle(perm)
        langs_done = 0
        for p, t in texts.items():
            new = list(t)
            for a, b in zip(ok, perm):
                new[a] = t[b]
            data = ctr_rom.text_pack(new)
            if len(data) == len(sources[p][i]):
                out.setdefault(p, {})[i] = data
                langs_done += 1
        done.append(f"{'dresseurs' if key == 'shuffleTrainerNames' else 'classes de dresseurs'} "
                    f"({len(ok)} noms, {langs_done} langues)")
    if jobs:
        log.append("Noms mélangés : " + (", ".join(done) or "rien trouvé"))
    return out


def native_tweaks(opts, log):
    if opts["runIndoors"] or opts["startShoes"]:
        log.append("Course : rien à changer en 6G/7G (course déjà autorisée en intérieur et disponible dès le début de l'aventure, non vérifié en jeu)")
    if opts["fastText"]:
        log.append("Texte rapide : rien à changer en 6G/7G (choisir « Vitesse du texte : Rapide » dans les options du jeu, non vérifié en jeu)")


def clean_text(chars):
    out = list(chars)
    while out and out[-1] == 0:
        out.pop()
    return out


def swap_text(chars, old, new):
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
