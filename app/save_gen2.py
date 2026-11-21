import os
import re
import struct

SAVE_SIZE = 0x8000
MON_PARTY = 48
MON_BOX = 32
NAME_LEN = 11
DEX_MAX = 251
MOVE_MAX = 251
EGG = 0xFD

LAYOUT = {
    "C": {
        "blocks": [(0xD47B, 0xDCA5, 0x2009), (0xDCA5, 0xDCD7, 0x2833), (0xDCD7, 0xDFF5, 0x2865)],
        "main": (0x2009, 0x2B83, 0x2D0D),
        "backup": [(0xD47B, 0xDCA5, 0x1209), (0xDCA5, 0xDCD7, 0x1A33), (0xDCD7, 0xDFF5, 0x1A65)],
        "backup_sum": 0x1F0D, "backup_order": [0, 1, 2],
        "sbox": 0x2D10,
        "w": {"id": 0xD47B, "name": 0xD47D, "time": 0xD4C4, "money": 0xD84E, "tm": 0xD859, "items": 0xD892,
              "key": 0xD8BC, "balls": 0xD8D7, "pc": 0xD8F1, "curbox": 0xDB72, "boxnames": 0xDB75,
              "party": 0xDCD7, "caught": 0xDE99, "seen": 0xDEB9},
    },
    "GS": {
        "blocks": [(0xD1A1, 0xD9EE, 0x2009), (0xD9EE, 0xDA22, 0x2856), (0xDA22, 0xDF01, 0x288A)],
        "main": (0x2009, 0x2D69, 0x2D69),
        "backup": [(0xD571, 0xD9EE, 0x0C6B), (0xDA22, 0xDF01, 0x10E8), (0xD1A1, 0xD3C7, 0x15C7),
                   (0xD3C7, 0xD571, 0x3D96), (0xD9EE, 0xDA22, 0x7E39)],
        "backup_sum": 0x7E6D,
        "sbox": 0x2D6C,
        "w": {"id": 0xD1A1, "name": 0xD1A3, "time": 0xD1EB, "money": 0xD573, "tm": 0xD57E, "items": 0xD5B7,
              "key": 0xD5E1, "balls": 0xD5FC, "pc": 0xD616, "curbox": 0xD8BC, "boxnames": 0xD8BF,
              "party": 0xDA22, "caught": 0xDBE4, "seen": 0xDC04},
    },
}
FAMILY_BY_GAME = {"CRYSTAL": "C", "GOLD": "GS", "SILVER": "GS"}
BOX_SLOTS = 20
BOX_BYTES = 1 + BOX_SLOTS + 1 + BOX_SLOTS * MON_BOX + 2 * BOX_SLOTS * NAME_LEN
POCKETS = [("items", "Objets", "items", 20, 1), ("key", "Objets rares", "key", 25, 2), ("balls", "Balls", "balls", 12, 3),
           ("tm", "CT / CS", "tm", 57, 4), ("pc", "PC", "pc", 50, None)]
TM_ITEMS = [i for i in range(0xBF, 0xFA) if i not in (0xC3, 0xDC)]

CHARS = {0x7F: " ", 0xE0: "'", 0xE3: "-", 0xE6: "?", 0xE7: "!", 0xE8: ".", 0xF4: ",", 0xEF: "♂", 0xF5: "♀", 0xF3: "/",
         0x9A: "(", 0x9B: ")", 0x9C: ":", 0x9D: ";", 0xE1: "PK", 0xE2: "MN"}
for _i in range(26):
    CHARS[0x80 + _i] = chr(65 + _i)
    CHARS[0xA0 + _i] = chr(97 + _i)
for _i in range(10):
    CHARS[0xF6 + _i] = str(_i)
_INV = {v: k for k, v in CHARS.items() if len(v) == 1}


def text(b):
    out = []
    for c in b:
        if c == 0x50:
            break
        out.append(CHARS.get(c, "?"))
    return "".join(out)


def encode(name, size=NAME_LEN):
    import unicodedata
    plain = "".join(c for c in unicodedata.normalize("NFD", name) if unicodedata.category(c) != "Mn").upper()
    out = bytearray(_INV[c] for c in plain if c in _INV)[:size - 1]
    return bytes(out + b"\x50" * (size - len(out)))


def _sum(buf, a, b):
    return sum(buf[a:b]) & 0xFFFF


def shiny_dvs(atk, de, spe, spc):
    return de == 10 and spe == 10 and spc == 10 and atk in (2, 3, 6, 7, 10, 11, 14, 15)


def hp_dv(atk, de, spe, spc):
    return ((atk & 1) << 3) | ((de & 1) << 2) | ((spe & 1) << 1) | (spc & 1)


class Gen2Save:
    gen = 2

    def __init__(self, raw, family):
        self.tail = bytes(raw[SAVE_SIZE:])
        self.raw = bytearray(raw[:SAVE_SIZE])
        self.family = family
        self.L = LAYOUT[family]
        self.problems = []
        a, b, c = self.L["main"]
        if _sum(self.raw, a, b) != struct.unpack_from("<H", self.raw, c)[0]:
            if self._backup_ok():
                self._restore_from_backup()
                self.problems.append("copie principale abîmée : copie de secours utilisée")
            else:
                raise ValueError("Sauvegarde 2G non reconnue (somme de contrôle fausse)")

    def _backup_parts(self):
        return [(self.L["blocks"], w0, w1, s) for w0, w1, s in self.L["backup"]]

    def _backup_ok(self):
        total = sum(_sum(self.raw, s, s + (w1 - w0)) for _, w0, w1, s in self._backup_parts())
        return total & 0xFFFF == struct.unpack_from("<H", self.raw, self.L["backup_sum"])[0]

    def _restore_from_backup(self):
        for _, w0, w1, s in self._backup_parts():
            o = self.w(w0)
            self.raw[o:o + (w1 - w0)] = self.raw[s:s + (w1 - w0)]

    def w(self, addr):
        for w0, w1, s in self.L["blocks"]:
            if w0 <= addr < w1:
                return s + addr - w0
        raise ValueError(f"adresse {addr:#x} hors sauvegarde")

    def at(self, key):
        return self.w(self.L["w"][key])

    def trainer(self):
        o = self.at("time")
        h, m, s = struct.unpack_from(">H", self.raw, o)[0], self.raw[o + 2], self.raw[o + 3]
        return {"name": text(self.raw[self.at("name"):self.at("name") + NAME_LEN]),
                "tid": struct.unpack_from(">H", self.raw, self.at("id"))[0], "sid": 0,
                "money": int.from_bytes(self.raw[self.at("money"):self.at("money") + 3], "big"),
                "playtime": f"{h} h {m:02d} min {s:02d} s"}

    def party_base(self):
        return self.at("party")

    def party_count(self):
        n = self.raw[self.party_base()]
        return n if n <= 6 else 0

    def _party_slot(self, i):
        p = self.party_base()
        return (p + 1 + i, p + 8 + MON_PARTY * i, p + 8 + MON_PARTY * 6 + NAME_LEN * i,
                p + 8 + MON_PARTY * 6 + NAME_LEN * 6 + NAME_LEN * i)

    def party(self):
        out = []
        for i in range(self.party_count()):
            sp, mon, ot, nick = self._party_slot(i)
            out.append(decode(self.raw[mon:mon + MON_PARTY], self.raw[ot:ot + NAME_LEN], self.raw[nick:nick + NAME_LEN],
                              self.raw[sp] == EGG))
        return out

    def cur_box(self):
        return self.raw[self.at("curbox")] & 0x7F

    def box_base(self, b):
        if b == self.cur_box():
            return self.L["sbox"]
        bank, k = (2, b) if b < 7 else (3, b - 7)
        return bank * 0x2000 + k * 0x450

    def _box_slot(self, b, i):
        base = self.box_base(b)
        mons = base + 2 + BOX_SLOTS
        return (base + 1 + i, mons + MON_BOX * i, mons + MON_BOX * BOX_SLOTS + NAME_LEN * i,
                mons + MON_BOX * BOX_SLOTS + NAME_LEN * BOX_SLOTS + NAME_LEN * i)

    def box_count(self, b):
        n = self.raw[self.box_base(b)]
        return n if n <= BOX_SLOTS else 0

    def pc(self):
        boxes = []
        for b in range(14):
            n = self.box_count(b)
            box = []
            for i in range(BOX_SLOTS):
                if i >= n:
                    box.append(None)
                    continue
                sp, mon, ot, nick = self._box_slot(b, i)
                box.append(decode(self.raw[mon:mon + MON_BOX], self.raw[ot:ot + NAME_LEN], self.raw[nick:nick + NAME_LEN],
                                  self.raw[sp] == EGG))
            boxes.append(box)
        o = self.at("boxnames")
        names = [text(self.raw[o + 9 * b:o + 9 * b + 9]) or f"Boîte {b + 1}" for b in range(14)]
        return boxes, names

    def slot(self, where):
        return self._party_slot(where[1]) if where[0] == "party" else self._box_slot(where[1], where[2])

    def count_at(self, where):
        if where[0] == "party":
            return self.party_base(), 6
        return self.box_base(where[1]), BOX_SLOTS

    def finish(self):
        a, b, c = self.L["main"]
        struct.pack_into("<H", self.raw, c, _sum(self.raw, a, b))
        total = 0
        for _, w0, w1, s in self._backup_parts():
            o = self.w(w0)
            self.raw[s:s + (w1 - w0)] = self.raw[o:o + (w1 - w0)]
            total += _sum(self.raw, s, s + (w1 - w0))
        struct.pack_into("<H", self.raw, self.L["backup_sum"], total & 0xFFFF)
        return bytes(self.raw) + self.tail


def decode(raw, ot=b"", nick=b"", egg=False):
    raw = bytes(raw)
    species = raw[0]
    if not 1 <= species <= DEX_MAX:
        return {"bad": True, "species": species}
    atk, de, spe, spc = raw[21] >> 4, raw[21] & 15, raw[22] >> 4, raw[22] & 15
    out = {"species": species, "item": raw[1], "moves": list(raw[2:6]), "tid": struct.unpack_from(">H", raw, 6)[0], "sid": 0,
           "exp": int.from_bytes(raw[8:11], "big"), "evs": list(struct.unpack_from(">5H", raw, 11)),
           "ivs": [atk, de, spe, spc], "dv": True, "hp_dv": hp_dv(atk, de, spe, spc),
           "pp": [p & 63 for p in raw[23:27]], "pp_ups": [p >> 6 for p in raw[23:27]],
           "friendship": raw[27], "pokerus": raw[28], "level": raw[31], "nature": None,
           "egg": bool(egg), "shiny": shiny_dvs(atk, de, spe, spc), "bad": False,
           "ot": text(ot), "nickname": text(nick)}
    if len(raw) >= MON_PARTY:
        out["hp"], out["hp_max"] = struct.unpack_from(">HH", raw, 34)
        out["stats"] = list(struct.unpack_from(">5H", raw, 38))
    return out


def open_save(raw, game_key=None):
    fams = [FAMILY_BY_GAME[game_key]] if game_key in FAMILY_BY_GAME else ["C", "GS"]
    err = None
    for fam in fams:
        try:
            return Gen2Save(raw, fam)
        except ValueError as e:
            err = e
    raise err


def read_mon(sv, where):
    sp, mon, ot, nick = sv.slot(where)
    size = MON_PARTY if where[0] == "party" else MON_BOX
    return bytes(sv.raw[mon:mon + size]), bytes(sv.raw[ot:ot + NAME_LEN]), bytes(sv.raw[nick:nick + NAME_LEN]), sv.raw[sp] == EGG


def write_mon(sv, where, raw, ot=None, nick=None, egg=None):
    sp, mon, o_ot, o_nick = sv.slot(where)
    size = MON_PARTY if where[0] == "party" else MON_BOX
    sv.raw[mon:mon + size] = bytes(raw[:size]).ljust(size, b"\0")
    if ot is not None:
        sv.raw[o_ot:o_ot + NAME_LEN] = ot
    if nick is not None:
        sv.raw[o_nick:o_nick + NAME_LEN] = nick
    if egg is None:
        egg = sv.raw[sp] == EGG
    sv.raw[sp] = EGG if egg else raw[0]


def calc_stats(base, dvs, statexp, level):
    import math
    atk, de, spe, spc = dvs
    full = [hp_dv(atk, de, spe, spc), atk, de, spe, spc]
    bases = [base[0], base[1], base[2], base[3], base[4]]
    out = []
    for k in range(5):
        bonus = min(255, math.ceil(math.sqrt(statexp[k]))) // 4
        v = ((bases[k] + full[k]) * 2 + bonus) * level // 100
        out.append(v + level + 10 if k == 0 else v + 5)
    spd = ((base[5] + spc) * 2 + min(255, math.ceil(math.sqrt(statexp[4]))) // 4) * level // 100 + 5
    return [out[0], out[1], out[2], out[3], out[4], spd]


def edit_mon(sv, where, changes, table, exp_for_level, level_for_exp, move_pp):
    raw, ot, nick, egg = read_mon(sv, where)
    raw = bytearray(raw)
    nat0 = raw[0]
    if "species" in changes:
        s = int(changes["species"])
        if not 1 <= s <= DEX_MAX:
            raise ValueError(f"espèce {s} inconnue en 2G")
        raw[0] = s
    if "item" in changes:
        raw[1] = int(changes["item"]) & 0xFF
    if "moves" in changes:
        mv = [int(m) for m in changes["moves"]][:4] + [0] * (4 - len(changes["moves"][:4]))
        for k, m in enumerate(mv):
            if m != raw[2 + k]:
                raw[2 + k] = m
                raw[23 + k] = move_pp(2, m) if m else 0
    if "friendship" in changes:
        raw[27] = max(0, min(255, int(changes["friendship"])))
    if "ivs" in changes:
        d = [max(0, min(15, int(v))) for v in list(changes["ivs"])[:4]]
        raw[21], raw[22] = d[0] << 4 | d[1], d[2] << 4 | d[3]
    if "evs" in changes:
        struct.pack_into(">5H", raw, 11, *[max(0, min(65535, int(v))) for v in list(changes["evs"])[:5]])
    nat = raw[0]
    exp = int.from_bytes(raw[8:11], "big")
    if nat0 in table and nat in table:
        level = raw[31] if raw[31] else level_for_exp(table[nat0][6], exp)
        if "level" in changes:
            level = max(1, min(100, int(changes["level"])))
        if "level" in changes or nat != nat0:
            raw[8:11] = exp_for_level(table[nat][6], level).to_bytes(3, "big")
        raw[31] = level
        if where[0] == "party" and {"species", "ivs", "evs", "level", "recalc"} & set(changes):
            st = calc_stats(table[nat][:6], [raw[21] >> 4, raw[21] & 15, raw[22] >> 4, raw[22] & 15],
                            list(struct.unpack_from(">5H", raw, 11)), level)
            hp, hp_max = struct.unpack_from(">HH", raw, 34)
            hp = st[0] if changes.get("recalc") else (0 if hp == 0 else max(1, min(st[0], hp + st[0] - hp_max)))
            struct.pack_into(">HH5H", raw, 34, hp, st[0], st[1], st[2], st[3], st[4], st[5])
    elif "level" in changes:
        raise ValueError(f"données de l'espèce {nat} absentes : niveau non modifiable")
    write_mon(sv, where, bytes(raw), egg=egg)


def set_money(sv, value):
    o = sv.at("money")
    sv.raw[o:o + 3] = max(0, min(999999, int(value))).to_bytes(3, "big")


def bag(sv):
    out = []
    for key, label, wkey, n, code in POCKETS:
        o = sv.at(wkey)
        items = []
        if key == "tm":
            for k, it in enumerate(TM_ITEMS):
                if sv.raw[o + k]:
                    items.append([it, sv.raw[o + k]])
        else:
            cnt = min(sv.raw[o], n)
            for i in range(cnt):
                if key == "key":
                    items.append([sv.raw[o + 1 + i], 1])
                else:
                    items.append([sv.raw[o + 1 + 2 * i], sv.raw[o + 2 + 2 * i]])
        out.append({"key": key, "label": label, "size": n, "code": code, "items": items})
    return out


def set_bag(sv, pockets):
    for key, label, wkey, n, code in POCKETS:
        if key not in pockets:
            continue
        items = [(int(a), int(q)) for a, q in pockets[key] if int(a) and int(q) > 0]
        o = sv.at(wkey)
        if key == "tm":
            qty = {a: min(q, 99) for a, q in items}
            bad = [a for a in qty if a not in TM_ITEMS]
            if bad:
                raise ValueError(f"{label} : objet {bad[0]} n'est pas une CT/CS")
            for k, it in enumerate(TM_ITEMS):
                sv.raw[o + k] = qty.get(it, 0) if it < 0xF3 else min(1, qty.get(it, 0))
            continue
        if len(items) > n:
            raise ValueError(f"{label} : {len(items)} objets pour {n} places")
        sv.raw[o] = len(items)
        if key == "key":
            for i in range(n + 1):
                sv.raw[o + 1 + i] = items[i][0] if i < len(items) else (0xFF if i == len(items) else 0)
        else:
            for i in range(n + 1):
                a, q = items[i] if i < len(items) else ((0xFF, 0) if i == len(items) else (0, 0))
                sv.raw[o + 1 + 2 * i] = a
                if i < n:
                    sv.raw[o + 2 + 2 * i] = min(q, 99)


def _bits(buf, o):
    return {i + 1 for i in range(DEX_MAX) if buf[o + (i >> 3)] >> (i & 7) & 1}


def dex(sv):
    caught, seen = _bits(sv.raw, sv.at("caught")), _bits(sv.raw, sv.at("seen"))
    return {"max": DEX_MAX, "seen": sorted(seen | caught), "caught": sorted(caught)}


def set_dex(sv, seen, caught):
    caught = {int(x) for x in caught if 1 <= int(x) <= DEX_MAX}
    seen = {int(x) for x in seen if 1 <= int(x) <= DEX_MAX} | caught
    for key, s in (("caught", caught), ("seen", seen)):
        o = sv.at(key)
        for nat in range(1, DEX_MAX + 1):
            i = nat - 1
            if nat in s:
                sv.raw[o + (i >> 3)] |= 1 << (i & 7)
            else:
                sv.raw[o + (i >> 3)] &= ~(1 << (i & 7)) & 0xFF


def export_mon(sv, where):
    raw, ot, nick, egg = read_mon(sv, where)
    if not 1 <= raw[0] <= DEX_MAX:
        return None
    full = bytearray(raw[:MON_BOX].ljust(MON_PARTY, b"\0"))
    if len(raw) >= MON_PARTY:
        full = bytearray(raw)
    return bytes([1, EGG if egg else raw[0], 0xFF]) + bytes(full) + ot + nick


def from_file(data):
    data = bytes(data)
    if len(data) == 73 and data[0] == 1 and data[2] == 0xFF:
        raw, ot, nick, egg = data[3:51], data[51:62], data[62:73], data[1] == EGG
    elif len(data) in (MON_BOX, MON_PARTY):
        raw, ot, nick, egg = data.ljust(MON_PARTY, b"\0"), encode("PKLAB"), b"", False
    else:
        raise ValueError(f"fichier de {len(data)} octets : pas un Pokémon 2G (.pk2)")
    if not 1 <= raw[0] <= DEX_MAX:
        raise ValueError(f"espèce {raw[0]} inconnue en 2G")
    if not nick:
        nick = encode("POKEMON")
    return bytes(raw), bytes(ot), bytes(nick), egg


def place_mon(sv, where, raw, ot, nick, egg, finish_edit):
    base, cap = sv.count_at(where)
    n = sv.raw[base] if sv.raw[base] <= cap else 0
    i = where[1] if where[0] == "party" else where[2]
    if i > n or i >= cap:
        raise ValueError("choisis un Pokémon à remplacer ou la première place libre")
    if i == n:
        sv.raw[base] = n + 1
        sv.raw[base + 1 + n + 1] = 0xFF
    write_mon(sv, where, raw, ot, nick, egg)
    if where[0] == "party":
        finish_edit()


def remove_mon(sv, where):
    base, cap = sv.count_at(where)
    n = sv.raw[base] if sv.raw[base] <= cap else 0
    i = where[1] if where[0] == "party" else where[2]
    if where[0] == "party" and n <= 1:
        raise ValueError("impossible de retirer le dernier Pokémon de l'équipe")
    if i >= n:
        raise ValueError("place déjà vide")
    mons = [read_mon(sv, (where[0], k) if where[0] == "party" else ("box", where[1], k)) for k in range(n)]
    del mons[i]
    for k in range(cap):
        w = ("party", k) if where[0] == "party" else ("box", where[1], k)
        if k < len(mons):
            raw, ot, nick, egg = mons[k]
            write_mon(sv, w, raw, ot, nick, egg)
        else:
            sp, mon, o_ot, o_nick = sv.slot(w)
            size = MON_PARTY if where[0] == "party" else MON_BOX
            sv.raw[mon:mon + size] = bytes(size)
            sv.raw[o_ot:o_ot + NAME_LEN] = bytes(NAME_LEN)
            sv.raw[o_nick:o_nick + NAME_LEN] = bytes(NAME_LEN)
            sv.raw[sp] = 0xFF if k == len(mons) else 0
    sv.raw[base] = len(mons)


def check_mon(m, table=None, pockets=None, exp_for_level=None, level_for_exp=None):
    if not m:
        return []
    if m.get("bad"):
        return ["données illisibles"]
    out = []
    mv = [x for x in m["moves"] if x]
    if not mv:
        out.append("aucune attaque")
    if len(set(mv)) != len(mv):
        out.append("la même attaque deux fois")
    if any(x > MOVE_MAX for x in mv):
        out.append("attaque inconnue dans ce jeu")
    if m["item"] and pockets is not None and m["item"] not in pockets:
        out.append("objet tenu inconnu dans ce jeu")
    if table and m["species"] in table and not m.get("egg") and level_for_exp:
        lv = level_for_exp(table[m["species"]][6], m["exp"])
        if m.get("level") and m["level"] != lv:
            out.append(f"niveau {m['level']} mais expérience du niveau {lv}")
        if m["exp"] > exp_for_level(table[m["species"]][6], 100):
            out.append("expérience au-delà du niveau 100")
    return out


def create_mon(sv, where, species, level, shiny, moves, table, exp_for_level, move_pp, name_raw=None, dvs=None):
    import random
    rng = random.SystemRandom()
    species, level = int(species), max(1, min(100, int(level)))
    if species not in table or not 1 <= species <= DEX_MAX:
        raise ValueError(f"espèce {species} inconnue en 2G")
    info = table[species]
    moves = [int(m) for m in (moves or []) if int(m)][:4] or [33]
    moves += [0] * (4 - len(moves))
    if dvs:
        d = [int(v) & 15 for v in dvs][:4]
    elif shiny:
        d = [rng.choice((2, 3, 6, 7, 10, 11, 14, 15)), 10, 10, 10]
    else:
        while True:
            d = [rng.randrange(16) for _ in range(4)]
            if not shiny_dvs(*d):
                break
    tid = sv.trainer()["tid"]
    raw = bytearray(MON_PARTY)
    raw[0] = species
    raw[2:6] = bytes(moves)
    struct.pack_into(">H", raw, 6, tid)
    raw[8:11] = exp_for_level(info[6], level).to_bytes(3, "big")
    raw[21], raw[22] = d[0] << 4 | d[1], d[2] << 4 | d[3]
    raw[23:27] = bytes(move_pp(2, m) if m else 0 for m in moves)
    raw[27] = 70
    raw[31] = level
    nick = (bytes(name_raw) + b"\x50" * NAME_LEN)[:NAME_LEN] if name_raw else encode(str(species))
    o = sv.at("name")
    ot = bytes(sv.raw[o:o + NAME_LEN])
    return bytes(raw), ot, nick


def _find(rom, pat, start=0):
    return rom.find(pat, start)


def _numbered_table(rom, width, count):
    pat = re.compile(b"".join(re.escape(bytes([n])) + b".{%d}" % (width - 1) for n in range(1, 6)), re.S)
    for m in pat.finditer(rom):
        o = m.start()
        if o + width * count <= len(rom) and all(rom[o + width * (n - 1)] == n for n in range(1, count + 1)):
            return o
    return -1


def base_stats_rom(rom):
    o = base_stats_offset(rom)
    out = {}
    for nat in range(1, DEX_MAX + 1):
        e = o + 32 * (nat - 1)
        if rom[e] != nat:
            raise ValueError("2G : table des statistiques incohérente")
        out[nat] = [rom[e + 1], rom[e + 2], rom[e + 3], rom[e + 4], rom[e + 5], rom[e + 6], rom[e + 22], rom[e + 13], 70, 0, 0, 0]
    return out


def base_stats_offset(rom):
    o = _find(rom, bytes([1, 45, 49, 49, 45, 65, 65, 22, 3]))
    if o < 0:
        o = _numbered_table(rom, 32, DEX_MAX)
    if o < 0:
        raise ValueError("2G : table des statistiques introuvable")
    return o


def moves_offset(rom):
    o = _find(rom, bytes([1, 0, 40, 0, 255, 35, 0, 2]))
    if o < 0:
        o = _numbered_table(rom, 7, MOVE_MAX)
    if o < 0:
        raise ValueError("2G : table des attaques introuvable")
    return o


def move_pp_rom(rom):
    o = moves_offset(rom)
    return {m: rom[o + 7 * (m - 1) + 5] for m in range(1, MOVE_MAX + 1)}


def item_attr_offset(rom):
    sig = struct.pack("<H", 1200)
    o = _find(rom, sig)
    while o >= 0:
        b = o - 7
        if b >= 0 and rom[b + 5] == 3 and rom[b + 12] == 3 and struct.unpack_from("<H", rom, b + 21)[0] == 600 \
                and struct.unpack_from("<H", rom, b + 28)[0] == 200 and rom[b + 26] == 3 and rom[b + 33] == 3:
            return b
        o = _find(rom, sig, o + 1)
    raise ValueError("2G : table des objets introuvable")


def item_pockets_rom(rom):
    o = item_attr_offset(rom)
    out = {}
    for i in range(1, 0xFA):
        p = rom[o + 7 * (i - 1) + 5]
        if 1 <= p <= 4:
            out[i] = p
    return out


def species_names_offset(rom):
    first, second = encode("BULBIZARRE")[:10], encode("HERBIZARRE")[:10]
    o = _find(rom, first)
    while o >= 0:
        if rom[o + 10:o + 20] == second:
            return o
        o = _find(rom, first, o + 1)
    raise ValueError("2G : noms des Pokémon introuvables")


def species_names_rom(rom):
    o = species_names_offset(rom)
    return {nat: bytes(rom[o + 10 * (nat - 1):o + 10 * nat]).split(b"\x50")[0] for nat in range(1, DEX_MAX + 1)}


def rom_game_key(rom):
    title = bytes(rom[0x134:0x13F]).split(b"\0")[0].decode("latin-1", "replace")
    if title.startswith("PM_CRYSTAL"):
        return "CRYSTAL"
    if title.startswith("POKEMON_GLD"):
        return "GOLD"
    if title.startswith("POKEMON_SLV"):
        return "SILVER"
    return None


if __name__ == "__main__":
    import sys
    sv = open_save(open(sys.argv[1], "rb").read())
    print(sv.family, sv.problems, sv.trainer())
    for m in sv.party():
        print(m)
    print(bag(sv))
    print(dex(sv))
    print(os.path.basename(sys.argv[1]))
