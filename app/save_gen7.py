import struct

import azahar_reader as A
import memecrypto
import save_gen6 as G6

FAMILIES = {0x6BE00: "SM", 0x6CC00: "USUM"}
TITLES = {"POKEMON S": "SM", "POKEMON M": "SM", "POKEMON US": "USUM", "POKEMON UM": "USUM"}
DEX_MAX = {"SM": 802, "USUM": 807}
MOVE_MAX = {"SM": 719, "USUM": 728}
VERSION = {"POKEMON S": 30, "POKEMON M": 31, "POKEMON US": 32, "POKEMON UM": 33}
VG = {"SM": 17, "USUM": 18}
BOXES = 32
SIGN_BLOCK = 36
POCKETS = {
    "SM": [("items", "Objets", 0x000, 430, 0), ("key", "Objets rares", 0x6B8, 184, 4), ("tm", "CT", 0x998, 108, 2),
           ("med", "Soins", 0xB48, 64, 1), ("berries", "Baies", 0xC48, 72, 3), ("z", "Cristaux Z", 0xD68, 30, 5)],
    "USUM": [("items", "Objets", 0x000, 427, 0), ("key", "Objets rares", 0x6AC, 198, 4), ("tm", "CT", 0x9C4, 108, 2),
             ("med", "Soins", 0xB74, 60, 1), ("berries", "Baies", 0xC64, 67, 3), ("z", "Cristaux Z", 0xD70, 35, 5),
             ("rotom", "Motismart", 0xDFC, 11, 6)],
}
DEX_CAUGHT = 0x88
DEX_SEEN = DEX_CAUGHT + 0x68
DEX_STRIDE = 0x8C
PERSONAL = "a/0/1/7"


def _table():
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
        t.append(c)
    return t


_CRC = _table()


def crc(data):
    c = 0xFFFF
    for b in bytes(data):
        c = (c >> 8) ^ _CRC[(c ^ b) & 0xFF]
    return c ^ 0xFFFF


class Gen7Save(G6.Gen6Save):
    gen = 7
    NAME = 0x38
    BOXES = BOXES

    def __init__(self, raw, family, game_key=None):
        self.raw = bytearray(raw)
        self.family = family
        self.game_key = game_key
        self.problems = []
        self.blocks = []
        mo = len(raw) - 0x1F0
        if struct.unpack_from("<I", raw, mo)[0] != 0x42454546:
            raise ValueError("sauvegarde 7G vide : sauvegarde d'abord une fois dans le jeu")
        off, p = 0, mo + 4
        while p + 8 <= len(raw):
            ln, bid, ck = struct.unpack_from("<IHH", raw, p)
            if not ln:
                break
            self.blocks.append((off, ln, p + 6))
            off = (off + ln + 0x1FF) & ~0x1FF
            p += 8
        if len(self.blocks) <= SIGN_BLOCK:
            raise ValueError("sauvegarde 7G : table des blocs incomplète")
        self.at = [o for o, _, _ in self.blocks]
        self.TRAINER = self.at[3]
        self.PARTY = self.at[4]
        self.MONEY = self.at[9] + 4
        self.DEX = self.at[6]
        self.DEX_MAX = DEX_MAX[family]
        self.MOVE_MAX = MOVE_MAX[family]
        bad = [i for i, (o, ln, at) in enumerate(self.blocks)
               if i != SIGN_BLOCK and crc(raw[o:o + ln]) != struct.unpack_from("<H", raw, at)[0]]
        if bad:
            self.problems.append(f"{len(bad)} bloc(s) avec une somme de contrôle fausse")
        if not memecrypto.check_save(raw):
            self.problems.append("signature de la sauvegarde invalide")
        if not 0 <= self.party_count() <= 6:
            self.problems.append("équipe illisible")

    def box_start(self):
        return self.at[14]

    def version(self):
        return VERSION.get(self.game_key) or (31 if self.family == "SM" else 33)

    def fix(self):
        sig_at = memecrypto.SIZES[len(self.raw)][0]
        self.raw[sig_at:sig_at + 0x80] = bytes(0x80)
        for o, ln, at in self.blocks:
            struct.pack_into("<H", self.raw, at, crc(self.raw[o:o + ln]))

    def finish(self):
        self.fix()
        self.raw = bytearray(memecrypto.resign_save(bytes(self.raw)))
        return bytes(self.raw)

    def box_names(self):
        o = self.at[13]
        out = []
        for b in range(BOXES):
            name = G6.text(self.raw[o + 0x22 * b:o + 0x22 * (b + 1)])
            out.append(name or f"Boîte {b + 1}")
        return out

    def pc(self):
        return [[G6.decode(self.read(("box", b, i))) for i in range(30)] for b in range(BOXES)], self.box_names()


def open_save(raw, game_key=None):
    fam = TITLES.get(game_key) or FAMILIES.get(len(raw))
    if not fam or len(raw) != {v: k for k, v in FAMILIES.items()}[fam]:
        raise ValueError(f"Format de sauvegarde 7G inconnu ({len(raw)} octets)")
    return Gen7Save(raw, fam, game_key)


def rom_family(rom_path):
    import rom_finder
    hit = rom_finder.identify(rom_path)
    fam = TITLES.get(hit[1]) if hit else None
    if not fam:
        raise ValueError("ROM 3DS : jeu de 7G non reconnu")
    return fam


def personal_rom(rom_path):
    import ctr_rom
    fam = rom_family(rom_path)
    fs = ctr_rom.RomFS(rom_path)
    try:
        files = ctr_rom.garc(fs.read(PERSONAL))
    finally:
        fs.close()
    blob = files[-1]
    if len(blob) < 0x54 * (DEX_MAX[fam] + 1):
        raise ValueError("ROM 3DS : données des Pokémon introuvables")
    out = {}
    for nat in range(1, DEX_MAX[fam] + 1):
        p = blob[0x54 * nat:0x54 * (nat + 1)]
        out[nat] = list(p[0:6]) + [p[0x15], p[0x12], p[0x14], p[0x18], p[0x19], p[0x1A]]
    return out


def bag(sv):
    out = []
    base = sv.at[0]
    for key, label, off, n, code in POCKETS[sv.family]:
        items = []
        for i in range(n):
            v = struct.unpack_from("<I", sv.raw, base + off + 4 * i)[0]
            if v & 0x3FF:
                items.append([v & 0x3FF, v >> 10 & 0x3FF])
        out.append({"key": key, "label": label, "size": n, "code": code, "items": items})
    return out


def set_bag(sv, pockets):
    base = sv.at[0]
    for key, label, off, n, code in POCKETS[sv.family]:
        if key not in pockets:
            continue
        items = [(int(a), min(A.ITEM_CAP, int(q))) for a, q in pockets[key] if int(a) and int(q) >= 0]
        if len(items) > n:
            raise ValueError(f"{label} : {len(items)} objets pour {n} places")
        if any(not 0 < a < 0x400 for a, q in items):
            raise ValueError(f"{label} : numéro d'objet hors limites")
        cur = [struct.unpack_from("<I", sv.raw, base + off + 4 * i)[0] for i in range(n)]
        want = {}
        for a, q in items:
            want.setdefault(a, []).append(q)
        slots = [0] * n
        for i, v in enumerate(cur):
            a = v & 0x3FF
            if a and want.get(a):
                slots[i] = a | want[a].pop(0) << 10 | v & 0xFFF00000
        free = (i for i in range(n) if not slots[i])
        for a, qs in want.items():
            for q in qs:
                slots[next(free)] = a | q << 10
        for i, v in enumerate(slots):
            struct.pack_into("<I", sv.raw, base + off + 4 * i, v)


def dex(sv):
    o = sv.DEX
    caught = G6._bits(sv.raw, o + DEX_CAUGHT, sv.DEX_MAX)
    seen = set().union(*(G6._bits(sv.raw, o + DEX_SEEN + DEX_STRIDE * k, sv.DEX_MAX) for k in range(4)))
    return {"max": sv.DEX_MAX, "seen": sorted(seen | caught), "caught": sorted(caught)}


def set_dex(sv, seen, caught, table):
    n = sv.DEX_MAX
    caught = {int(x) for x in caught if 1 <= int(x) <= n}
    seen = {int(x) for x in seen if 1 <= int(x) <= n} | caught
    old = set(dex(sv)["seen"])
    o = sv.DEX
    for nat in range(1, n + 1):
        G6._set_bit(sv.raw, o + DEX_CAUGHT, nat, nat in caught)
        if nat not in seen or nat not in old:
            for k in range(8):
                G6._set_bit(sv.raw, o + DEX_SEEN + DEX_STRIDE * k, nat, False)
            if nat in seen:
                info = table.get(nat, [])
                k = 1 if len(info) > 7 and info[7] == 254 else 0
                G6._set_bit(sv.raw, o + DEX_SEEN + DEX_STRIDE * k, nat, True)
                G6._set_bit(sv.raw, o + DEX_SEEN + DEX_STRIDE * (k + 4), nat, True)


def set_money(sv, value):
    G6.set_money(sv, value)


def from_file(data, family="USUM"):
    return G6.from_file(data, DEX_MAX[family], 7)


def check_mon(m, table, pockets, exp_for_level, level_for_exp, family="USUM"):
    return G6.check_mon(m, table, pockets, exp_for_level, level_for_exp, DEX_MAX[family], MOVE_MAX[family], 7)
