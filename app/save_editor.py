import os
import struct

from games_gen3 import SUBSTRUCT_ORDERS, gen3_species_to_national

GEN3_SIG = 0x08012025
GEN3_SECTION_DATA = {0: 3884, 13: 2000}

_G3 = {0: " ", 0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-", 0xB0: "…", 0xB1: "“", 0xB2: "”", 0xB3: "‘", 0xB4: "’",
       0xB5: "♂", 0xB6: "♀", 0xB8: ",", 0xBA: "/", 0x1B: "é", 0x1A: "è", 0x1C: "ê", 0x16: "à", 0x19: "ç", 0x20: "î",
       0x24: "ô", 0x06: "É", 0x01: "À", 0x0B: "Î", 0x5C: "(", 0x5D: ")", 0x2D: "&", 0x2E: "+", 0x35: "=", 0x36: ";",
       0x53: "PK", 0x54: "MN"}
for _i in range(26):
    _G3[0xBB + _i] = chr(65 + _i)
    _G3[0xD5 + _i] = chr(97 + _i)
for _i in range(10):
    _G3[0xA1 + _i] = str(_i)


def g3_text(b):
    out = []
    for c in b:
        if c == 0xFF:
            break
        out.append(_G3.get(c, "?"))
    return "".join(out)


def _g3_checksum(data):
    s = sum(struct.unpack_from(f"<{len(data) // 4}I", data)) & 0xFFFFFFFF
    return ((s >> 16) + (s & 0xFFFF)) & 0xFFFF


class Gen3Save:
    gen = 3

    def __init__(self, raw):
        self.raw = bytearray(raw)
        self.slot, self.sections, self.problems = self._pick_slot()
        s0, s1 = self.sections[0][1], self.sections[1][1]
        self.family = "FRLG" if self._party_ok(s1, 0x34) and not self._party_ok(s1, 0x234) else "RSE"
        self.key = 0
        if self.family == "FRLG":
            self.key = struct.unpack_from("<I", s0, 0xF20)[0]
        else:
            k = struct.unpack_from("<I", s0, 0xAC)[0]
            self.key = 0 if k in (0, 1) else k

    def _pick_slot(self):
        best = None
        for slot in (0, 1):
            secs, ok, idx = {}, True, None
            for k in range(14):
                o = slot * 0xE000 + k * 0x1000
                sid, csum, sig, index = struct.unpack_from("<HHII", self.raw, o + 0xFF4)
                if sig != GEN3_SIG or sid > 13:
                    ok = False
                    break
                secs[sid] = (o, self.raw[o:o + 0xF80])
                idx = index
            if ok and len(secs) == 14 and (best is None or idx > best[0]):
                best = (idx, slot, secs)
        if best is None:
            raise ValueError("Sauvegarde 3G non reconnue (aucun emplacement valide)")
        problems = []
        for sid, (o, data) in best[2].items():
            size = GEN3_SECTION_DATA.get(sid, 3968)
            if _g3_checksum(data[:size]) != struct.unpack_from("<H", self.raw, o + 0xFF6)[0]:
                problems.append(f"section {sid} : somme de contrôle fausse")
        return best[1], best[2], problems

    @staticmethod
    def _party_ok(s1, off):
        n = struct.unpack_from("<I", s1, off)[0]
        if not 1 <= n <= 6:
            return False
        return all(decode_pk3(s1[off + 4 + 100 * i:off + 4 + 100 * (i + 1)]) for i in range(n))

    def trainer(self):
        s0 = self.sections[0][1]
        s1 = self.sections[1][1]
        money = struct.unpack_from("<I", s1, 0x290 if self.family == "FRLG" else 0x490)[0] ^ self.key
        h, m, sec = struct.unpack_from("<HBB", s0, 0xE)
        tid = struct.unpack_from("<I", s0, 0xA)[0]
        return {"name": g3_text(s0[0:7]), "gender": "fille" if s0[8] else "garçon", "tid": tid & 0xFFFF,
                "sid": tid >> 16, "money": money, "playtime": f"{h} h {m:02d} min {sec:02d} s"}

    def party(self):
        s1 = self.sections[1][1]
        off = 0x34 if self.family == "FRLG" else 0x234
        n = struct.unpack_from("<I", s1, off)[0]
        return [decode_pk3(s1[off + 4 + 100 * i:off + 4 + 100 * (i + 1)]) for i in range(min(n, 6))]

    def pc(self):
        buf = b"".join(self.sections[k][1][:GEN3_SECTION_DATA.get(k, 3968)] for k in range(5, 14))
        boxes = []
        for b in range(14):
            box = []
            for i in range(30):
                o = 4 + (b * 30 + i) * 80
                box.append(decode_pk3(buf[o:o + 80]))
            boxes.append(box)
        names = [g3_text(buf[4 + 420 * 80 + 9 * b:4 + 420 * 80 + 9 * b + 9]) for b in range(14)]
        return boxes, names


def decode_pk3(raw):
    if len(raw) < 80:
        return None
    pid, otid = struct.unpack_from("<II", raw, 0)
    if pid == 0 and otid == 0:
        return None
    key = pid ^ otid
    data = struct.pack("<12I", *(w ^ key for w in struct.unpack_from("<12I", raw, 0x20)))
    if sum(struct.unpack("<24H", data)) & 0xFFFF != struct.unpack_from("<H", raw, 0x1C)[0]:
        return {"bad": True, "pid": pid}
    order = SUBSTRUCT_ORDERS[pid % 24]
    sub = {c: data[12 * i:12 * i + 12] for i, c in enumerate(order)}
    species, item, exp, ppb, friend = struct.unpack_from("<HHIBB", sub["G"], 0)
    moves = list(struct.unpack_from("<4H", sub["A"], 0))
    pp = list(sub["A"][8:12])
    evs = list(sub["E"][0:6])
    pokerus, met_loc, origins, ivword, ribbons = struct.unpack_from("<BBHII", sub["M"], 0)
    ivs = [(ivword >> (5 * k)) & 31 for k in range(6)]
    out = {"pid": pid, "tid": otid & 0xFFFF, "sid": otid >> 16, "nickname": g3_text(raw[8:18]),
           "ot": g3_text(raw[20:27]), "species": gen3_species_to_national(species), "species_raw": species, "item": item,
           "exp": exp, "friendship": friend, "moves": moves, "pp": pp, "pp_ups": ppb, "evs": evs, "ivs": ivs,
           "egg": bool(ivword >> 30 & 1), "ability_slot": ivword >> 31, "nature": pid % 25, "met_location": met_loc,
           "ball": (origins >> 11) & 0xF, "met_level": origins & 0x7F, "language": raw[18],
           "shiny": ((otid >> 16) ^ (otid & 0xFFFF) ^ (pid >> 16) ^ (pid & 0xFFFF)) < 8, "bad": False}
    if len(raw) >= 100:
        out["level"] = raw[0x54]
        out["hp"], out["hp_max"] = struct.unpack_from("<HH", raw, 0x56)
        out["stats"] = list(struct.unpack_from("<5H", raw, 0x5A))
    return out


GEN45_ORDERS = [SUBSTRUCT_ORDERS[i].translate(str.maketrans("GAEM", "ABCD")) for i in range(24)]


def _lcg_xor(data, seed):
    out = bytearray(data)
    for i in range(0, len(out) - 1, 2):
        seed = (seed * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        struct.pack_into("<H", out, i, struct.unpack_from("<H", out, i)[0] ^ (seed >> 16))
    return bytes(out)


def _crc16_ccitt(data):
    c = 0xFFFF
    for b in data:
        c ^= b << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    return c


def _u16_text(raw, gen4):
    out = []
    cm = None
    if gen4:
        try:
            import gen4_maps
            cm = gen4_maps._charmap()
        except Exception:
            cm = {}
    for i in range(0, len(raw) - 1, 2):
        c = struct.unpack_from("<H", raw, i)[0]
        if c == 0xFFFF or (not gen4 and c == 0):
            break
        out.append(cm.get(c, "?") if gen4 else chr(c))
    return "".join(x for x in out if not x.startswith("{"))


def decode_pk45(raw, gen):
    if len(raw) < 136:
        return None
    pid, _, csum = struct.unpack_from("<IHH", raw, 0)
    if pid == 0 and csum == 0:
        return None
    data = _lcg_xor(raw[8:136], csum)
    if sum(struct.unpack("<64H", data)) & 0xFFFF != csum:
        return {"bad": True, "pid": pid}
    order = GEN45_ORDERS[((pid & 0x3E000) >> 13) % 24]
    blk = {c: data[32 * i:32 * i + 32] for i, c in enumerate(order)}
    A, B, C, D = blk["A"], blk["B"], blk["C"], blk["D"]
    species, item, tid, sid, exp, friend, ability = struct.unpack_from("<HHHHIBB", A, 0)
    ivword = struct.unpack_from("<I", B, 16)[0]
    out = {"pid": pid, "species": species, "item": item, "tid": tid, "sid": sid, "exp": exp, "friendship": friend,
           "ability": ability, "evs": list(A[16:22]), "moves": list(struct.unpack_from("<4H", B, 0)), "pp": list(B[8:12]),
           "pp_ups": list(B[12:16]), "ivs": [(ivword >> (5 * k)) & 31 for k in range(6)], "egg": bool(ivword >> 30 & 1),
           "nature": B[0x19] if gen == 5 else pid % 25, "form": B[0x18] >> 3,
           "nickname": _u16_text(C[0:22], gen == 4), "ot": _u16_text(D[0:16], gen == 4),
           "shiny": (tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF)) < 8, "bad": False}
    if len(raw) >= 220:
        extra = _lcg_xor(raw[136:236 if len(raw) >= 236 else 220], pid)
        out["level"] = extra[4]
        out["hp"], out["hp_max"] = struct.unpack_from("<HH", extra, 6)
        out["stats"] = list(struct.unpack_from("<5H", extra, 10))
    return out


GEN4_LAYOUT = {
    "DP": {"general": (0, 0xC100), "storage": (0xC100, 0x121E0), "footer": 0x14, "party": 0x94, "trainer": 0x64},
    "PT": {"general": (0, 0xCF2C), "storage": (0xCF2C, 0x121E4), "footer": 0x14, "party": 0x9C, "trainer": 0x68},
    "HGSS": {"general": (0, 0xF628), "storage": (0xF700, 0x12310), "footer": 0x10, "party": 0x94, "trainer": 0x64},
}


class Gen4Save:
    gen = 4

    def __init__(self, raw, family):
        self.raw = bytearray(raw)
        self.family = family
        L = GEN4_LAYOUT[family]
        self.blocks, self.problems = {}, []
        for name in ("general", "storage"):
            start, size = L[name]
            good = []
            for copy in (0, 0x40000):
                o = copy + start
                if _crc16_ccitt(self.raw[o:o + size - L["footer"]]) == struct.unpack_from("<H", self.raw, o + size - 2)[0]:
                    good.append((struct.unpack_from("<I", self.raw, o + size - L["footer"])[0], o))
            if not good:
                self.problems.append(f"bloc {name} : aucune copie valide")
                good = [(0, start)]
            self.blocks[name] = max(good)[1]

    def general(self):
        o = self.blocks["general"]
        return self.raw[o:o + GEN4_LAYOUT[self.family]["general"][1]]

    def trainer(self):
        g = self.general()
        t = GEN4_LAYOUT[self.family]["trainer"]
        tid, sid, money = struct.unpack_from("<HHI", g, t + 0x10)
        return {"name": _u16_text(g[t:t + 16], True), "tid": tid, "sid": sid, "money": money,
                "gender": "fille" if g[t + 0x18] else "garçon"}

    def party(self):
        g = self.general()
        p = GEN4_LAYOUT[self.family]["party"]
        n = struct.unpack_from("<I", g, p)[0]
        return [decode_pk45(g[p + 4 + 236 * i:p + 4 + 236 * (i + 1)], 4) for i in range(min(n, 6))]


    def pc(self):
        o = self.blocks["storage"]
        st = self.raw[o:o + GEN4_LAYOUT[self.family]["storage"][1]]
        boxes = []
        for b in range(18):
            base = b * 0x1000 if self.family == "HGSS" else 4 + b * 30 * 136
            boxes.append([decode_pk45(st[base + 136 * i:base + 136 * (i + 1)], 4) for i in range(30)])
        return boxes, [f"Boîte {b + 1}" for b in range(18)]


class Gen5Save:
    gen = 5

    def __init__(self, raw, family):
        self.raw = bytearray(raw)
        self.family = family
        self.problems = []
        if not self._party_ok():
            self.problems.append("équipe illisible")

    def _party_ok(self):
        n = struct.unpack_from("<I", self.raw, 0x18E04)[0]
        return 0 <= n <= 6 and all((m := decode_pk45(self.raw[0x18E08 + 220 * i:0x18E08 + 220 * (i + 1)], 5)) and not m["bad"]
                                   for i in range(n))

    def trainer(self):
        tid, sid = struct.unpack_from("<HH", self.raw, 0x19414)
        money = struct.unpack_from("<I", self.raw, 0x21100 if self.family == "B2W2" else 0x21200)[0]
        return {"name": _u16_text(self.raw[0x19404:0x19414], False), "tid": tid, "sid": sid, "money": money}

    def party(self):
        n = struct.unpack_from("<I", self.raw, 0x18E04)[0]
        return [decode_pk45(self.raw[0x18E08 + 220 * i:0x18E08 + 220 * (i + 1)], 5) for i in range(min(n, 6))]

    def pc(self):
        boxes = [[decode_pk45(self.raw[0x400 + b * 0x1000 + 136 * i:0x400 + b * 0x1000 + 136 * (i + 1)], 5) for i in range(30)]
                 for b in range(24)]
        return boxes, [f"Boîte {b + 1}" for b in range(24)]


GEN5_FAMILY = {"POKEMON B": "BW", "POKEMON W": "BW", "POKEMON B2": "B2W2", "POKEMON W2": "B2W2"}
GEN4_FAMILY = {"POKEMON D": "DP", "POKEMON P": "DP", "POKEMON PL": "PT", "POKEMON HG": "HGSS", "POKEMON SS": "HGSS"}


def open_save(path, game_key=None):
    raw = open(path, "rb").read()
    if len(raw) in (0x20000, 0x20010):
        return Gen3Save(raw[:0x20000])
    if len(raw) == 0x80000:
        fams = [GEN4_FAMILY[game_key]] if game_key in GEN4_FAMILY else ["PT", "HGSS", "DP"]
        if game_key not in GEN5_FAMILY:
            for fam in fams:
                sv = Gen4Save(raw, fam)
                if not sv.problems:
                    return sv
        fam = GEN5_FAMILY.get(game_key) or ("B2W2" if raw[0x3EE04:0x3EE08] == raw[0x18E04:0x18E08] and
                                             raw[0x3CE04:0x3CE08] != raw[0x18E04:0x18E08] else "BW")
        sv = Gen5Save(raw, fam)
        if not sv.problems:
            return sv
    raise ValueError(f"Format de sauvegarde pas encore pris en charge ({len(raw)} octets)")


if __name__ == "__main__":
    import sys
    sv = open_save(sys.argv[1])
    print(os.path.basename(sys.argv[1]), sv.family, "| problèmes", sv.problems)
    print(sv.trainer())
    for m in sv.party():
        print("  ", m and {k: m[k] for k in ("species", "nickname", "level", "moves", "ivs", "evs", "item", "ot", "shiny") if k in m})


def pk3_unpack(raw):
    pid, otid = struct.unpack_from("<II", raw, 0)
    key = pid ^ otid
    data = struct.pack("<12I", *(w ^ key for w in struct.unpack_from("<12I", raw, 0x20)))
    order = SUBSTRUCT_ORDERS[pid % 24]
    return bytes(raw[:0x20]), {c: bytearray(data[12 * i:12 * i + 12]) for i, c in enumerate(order)}, bytes(raw[0x50:])


def pk3_pack(head, sub, tail):
    pid, otid = struct.unpack_from("<II", head, 0)
    order = SUBSTRUCT_ORDERS[pid % 24]
    data = b"".join(bytes(sub[c]) for c in order)
    head = bytearray(head)
    struct.pack_into("<H", head, 0x1C, sum(struct.unpack("<24H", data)) & 0xFFFF)
    key = pid ^ otid
    return bytes(head) + struct.pack("<12I", *(w ^ key for w in struct.unpack("<12I", data))) + bytes(tail)


def pk45_unpack(raw):
    pid, _, csum = struct.unpack_from("<IHH", raw, 0)
    data = _lcg_xor(raw[8:136], csum)
    order = GEN45_ORDERS[((pid & 0x3E000) >> 13) % 24]
    extra = _lcg_xor(raw[136:], pid) if len(raw) > 136 else b""
    return bytes(raw[:8]), {c: bytearray(data[32 * i:32 * i + 32]) for i, c in enumerate(order)}, bytearray(extra)


def pk45_pack(head, blk, extra):
    pid = struct.unpack_from("<I", head, 0)[0]
    order = GEN45_ORDERS[((pid & 0x3E000) >> 13) % 24]
    data = b"".join(bytes(blk[c]) for c in order)
    csum = sum(struct.unpack("<64H", data)) & 0xFFFF
    head = bytearray(head)
    struct.pack_into("<H", head, 6, csum)
    return bytes(head) + _lcg_xor(data, csum) + (_lcg_xor(bytes(extra), pid) if extra else b"")


def _gen3_fix_section(sv, sid):
    o, data = sv.sections[sid]
    sv.raw[o:o + 0xF80] = data
    struct.pack_into("<H", sv.raw, o + 0xFF6, _g3_checksum(bytes(data[:GEN3_SECTION_DATA.get(sid, 3968)])))


def _gen4_fix_block(sv, name):
    o = sv.blocks[name]
    size, foot = GEN4_LAYOUT[sv.family][name][1], GEN4_LAYOUT[sv.family]["footer"]
    struct.pack_into("<H", sv.raw, o + size - 2, _crc16_ccitt(bytes(sv.raw[o:o + size - foot])))


GEN5_BLOCKS = {
    "BW": {"table": (0x23F00, 0x8C), "party": (0x18E00, 0x534, 0x34), "trainer": (0x19400, 0x68, 0x36),
           "money": (0x21200, 0xEC, 0x68), "backup": 0x24000},
    "B2W2": {"table": (0x25F00, 0x94), "party": (0x18E00, 0x534, 0x34), "trainer": (0x19400, 0xB0, 0x36),
             "money": (0x21100, 0xF0, 0x68), "backup": 0x26000},
}


def _gen5_fix(sv, start, length, tab_off):
    t0, tlen = GEN5_BLOCKS[sv.family]["table"]
    c = _crc16_ccitt(bytes(sv.raw[start:start + length]))
    struct.pack_into("<H", sv.raw, start + length + 2, c)
    struct.pack_into("<H", sv.raw, t0 + tab_off, c)
    struct.pack_into("<H", sv.raw, t0 + tlen + 0xE, _crc16_ccitt(bytes(sv.raw[t0:t0 + tlen])))


def read_mon(sv, where):
    if isinstance(sv, Gen3Save):
        if where[0] == "party":
            s1 = sv.sections[1][1]
            off = (0x38 if sv.family == "FRLG" else 0x238) + 100 * where[1]
            return bytes(s1[off:off + 100])
        buf = b"".join(bytes(sv.sections[k][1][:GEN3_SECTION_DATA.get(k, 3968)]) for k in range(5, 14))
        o = 4 + (where[1] * 30 + where[2]) * 80
        return buf[o:o + 80]
    if isinstance(sv, Gen4Save):
        if where[0] == "party":
            o = sv.blocks["general"] + GEN4_LAYOUT[sv.family]["party"] + 4 + 236 * where[1]
            return bytes(sv.raw[o:o + 236])
        base = where[1] * 0x1000 if sv.family == "HGSS" else 4 + where[1] * 30 * 136
        o = sv.blocks["storage"] + base + 136 * where[2]
        return bytes(sv.raw[o:o + 136])
    if where[0] == "party":
        return bytes(sv.raw[0x18E08 + 220 * where[1]:0x18E08 + 220 * (where[1] + 1)])
    o = 0x400 + where[1] * 0x1000 + 136 * where[2]
    return bytes(sv.raw[o:o + 136])


def write_mon(sv, where, raw):
    if isinstance(sv, Gen3Save):
        if where[0] == "party":
            o, s1 = sv.sections[1]
            off = (0x38 if sv.family == "FRLG" else 0x238) + 100 * where[1]
            s1[off:off + 100] = raw
            _gen3_fix_section(sv, 1)
            return
        sizes = [GEN3_SECTION_DATA.get(k, 3968) for k in range(5, 14)]
        buf = bytearray(b"".join(bytes(sv.sections[k][1][:sizes[k - 5]]) for k in range(5, 14)))
        o = 4 + (where[1] * 30 + where[2]) * 80
        buf[o:o + 80] = raw
        pos = 0
        for k in range(5, 14):
            sv.sections[k][1][:sizes[k - 5]] = buf[pos:pos + sizes[k - 5]]
            pos += sizes[k - 5]
            _gen3_fix_section(sv, k)
        return
    if isinstance(sv, Gen4Save):
        if where[0] == "party":
            o = sv.blocks["general"] + GEN4_LAYOUT[sv.family]["party"] + 4 + 236 * where[1]
            sv.raw[o:o + 236] = raw
            _gen4_fix_block(sv, "general")
        else:
            base = where[1] * 0x1000 if sv.family == "HGSS" else 4 + where[1] * 30 * 136
            o = sv.blocks["storage"] + base + 136 * where[2]
            sv.raw[o:o + 136] = raw
            _gen4_fix_block(sv, "storage")
        return
    B = GEN5_BLOCKS[sv.family]
    if where[0] == "party":
        o = 0x18E08 + 220 * where[1]
        sv.raw[o:o + 220] = raw
        _gen5_fix(sv, *B["party"])
    else:
        o = 0x400 + where[1] * 0x1000 + 136 * where[2]
        sv.raw[o:o + 136] = raw
        _gen5_fix(sv, 0x400 + where[1] * 0x1000, 0xFF0, 2 + 2 * where[1])


_BASE = {}


def _data_dir():
    from paths import res
    return res("data")


def species_table(rom_path):
    import randomizer as R
    import randomizer_gen3 as R3
    import randomizer_gen4 as R4
    import gen4_maps
    with open(rom_path, "rb") as f:
        rom = bytearray(f.read())
    out = {}
    if rom_path.lower().endswith(".gba"):
        base = R3._one(bytes(rom), bytes([45, 49, 49, 45, 65, 65, 12, 3, 45]), "stats", -28)
        for nat in range(1, 387):
            o = base + 28 * _gen3_internal(nat)
            out[nat] = list(rom[o:o + 6]) + [rom[o + 19], rom[o + 16], rom[o + 18], rom[o + 22], rom[o + 23], 0]
        return out
    key = gen4_maps._rom_title(rom_path)
    if key in R4.PATHS4:
        g, last, gpos, spos, fpos, apos, nab = R4.Gen4Rom(rom, key), 493, 19, 16, 18, 22, 2
    else:
        g, last, gpos, spos, fpos, apos, nab = R.Gen5Rom(rom, key), 649, 21, 18, 20, 24, 3
    for nat in range(1, last + 1):
        o = g.personal[nat][0]
        ab = list(rom[o + apos:o + apos + nab]) + [0] * (3 - nab)
        out[nat] = list(rom[o:o + 6]) + [rom[o + gpos], rom[o + spos], rom[o + fpos]] + ab
    return out


def base_table(gen):
    if not _BASE:
        import json
        with open(os.path.join(_data_dir(), "base_stats.json"), encoding="utf-8") as f:
            _BASE.update({g: {int(k): v for k, v in t.items()} for g, t in json.load(f).items()})
    return _BASE[str(gen)]


def exp_for_level(growth, n):
    if n <= 1:
        return 1 if n == 1 else 0
    c = n ** 3
    if growth == 0:
        return c
    if growth == 1:
        if n <= 50:
            return c * (100 - n) // 50
        if n <= 68:
            return c * (150 - n) // 100
        if n <= 98:
            return c * ((1911 - 10 * n) // 3) // 500
        return c * (160 - n) // 100
    if growth == 2:
        if n <= 15:
            return c * ((n + 1) // 3 + 24) // 50
        if n <= 36:
            return c * (n + 14) // 50
        return c * (n // 2 + 32) // 50
    if growth == 3:
        return max(0, 6 * c // 5 - 15 * n * n + 100 * n - 140)
    if growth == 4:
        return 4 * c // 5
    return 5 * c // 4


def level_for_exp(growth, exp):
    n = 1
    while n < 100 and exp_for_level(growth, n + 1) <= exp:
        n += 1
    return n


def calc_stats(nat, base, ivs, evs, level, nature):
    out = [1 if nat == 292 else (2 * base[0] + ivs[0] + evs[0] // 4) * level // 100 + level + 10]
    up, down = nature // 5, nature % 5
    for k in range(1, 6):
        v = (2 * base[k] + ivs[k] + evs[k] // 4) * level // 100 + 5
        if up != down and k - 1 == up:
            v = v * 110 // 100
        elif up != down and k - 1 == down:
            v = v * 90 // 100
        out.append(v)
    return out


def _unown_form(pid):
    return (((pid >> 24) & 3) << 6 | ((pid >> 16) & 3) << 4 | ((pid >> 8) & 3) << 2 | (pid & 3)) % 28


def new_pid(pid, tid, sid, nature, nat):
    import random
    rng = random.Random(pid ^ nature)
    lo8 = pid & 0xFF
    shiny = (tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF)) < 8
    for _ in range(2000000):
        lo16 = rng.randrange(256) << 8 | lo8
        hi16 = (tid ^ sid ^ lo16 ^ rng.randrange(8)) if shiny else rng.randrange(0x10000)
        q = hi16 << 16 | lo16
        if q % 25 != nature or ((tid ^ sid ^ hi16 ^ lo16) < 8) != shiny:
            continue
        if (hi16 % 10 < 5) != ((pid >> 16) % 10 < 5):
            continue
        if nat == 201 and _unown_form(q) != _unown_form(pid):
            continue
        return q
    raise ValueError("aucun PID trouvé pour cette nature")


def edit_mon(sv, where, changes, table=None):
    table = table or base_table(sv.gen)
    raw = read_mon(sv, where)
    gen3 = isinstance(sv, Gen3Save)
    if gen3:
        head, sub, tail = pk3_unpack(raw)
        G, A, E, M = sub["G"], sub["A"], sub["E"], sub["M"]
        tail = bytearray(tail)
        nat0 = gen3_species_to_national(struct.unpack_from("<H", G, 0)[0])
        exp_at = (G, 4)
        if "species" in changes:
            struct.pack_into("<H", G, 0, _gen3_internal(changes["species"]))
        if "item" in changes:
            struct.pack_into("<H", G, 2, changes["item"])
        if "friendship" in changes:
            G[9] = changes["friendship"]
        if "moves" in changes:
            old = struct.unpack_from("<4H", A, 0)
            struct.pack_into("<4H", A, 0, *changes["moves"])
            for k, mv in enumerate(changes["moves"]):
                if mv != old[k]:
                    A[8 + k] = _move_pp(3, mv) if mv else 0
                    G[8] &= ~(3 << (2 * k)) & 0xFF
        if "evs" in changes:
            E[0:6] = bytes(changes["evs"])
        if "ivs" in changes:
            w = struct.unpack_from("<I", M, 4)[0] & 0xC0000000
            for k, v in enumerate(changes["ivs"]):
                w |= (v & 31) << (5 * k)
            struct.pack_into("<I", M, 4, w)
        nat = gen3_species_to_national(struct.unpack_from("<H", G, 0)[0])
        evs = list(E[0:6])
        ivw = struct.unpack_from("<I", M, 4)[0]
        pid, otid = struct.unpack_from("<II", head, 0)
        tid, sid = otid & 0xFFFF, otid >> 16
    else:
        head, blk, extra = pk45_unpack(raw)
        A, B = blk["A"], blk["B"]
        tail = extra
        nat0 = struct.unpack_from("<H", A, 0)[0]
        exp_at = (A, 8)
        if "species" in changes:
            struct.pack_into("<H", A, 0, changes["species"])
        if "item" in changes:
            struct.pack_into("<H", A, 2, changes["item"])
        if "friendship" in changes:
            A[12] = changes["friendship"]
        if "evs" in changes:
            A[16:22] = bytes(changes["evs"])
        if "moves" in changes:
            old = struct.unpack_from("<4H", B, 0)
            struct.pack_into("<4H", B, 0, *changes["moves"])
            for k, mv in enumerate(changes["moves"]):
                if mv != old[k]:
                    B[8 + k] = _move_pp(sv.gen, mv) if mv else 0
                    B[12 + k] = 0
        if "ivs" in changes:
            w = struct.unpack_from("<I", B, 16)[0] & 0xC0000000
            for k, v in enumerate(changes["ivs"]):
                w |= (v & 31) << (5 * k)
            struct.pack_into("<I", B, 16, w)
        nat = struct.unpack_from("<H", A, 0)[0]
        evs = list(A[16:22])
        ivw = struct.unpack_from("<I", B, 16)[0]
        pid = struct.unpack_from("<I", head, 0)[0]
        tid, sid = struct.unpack_from("<HH", A, 4)

    nature = B[0x19] if sv.gen == 5 else pid % 25
    if "nature" in changes and int(changes["nature"]) != nature:
        nature = int(changes["nature"]) % 25
        if sv.gen == 5:
            B[0x19] = nature
        else:
            pid = new_pid(pid, tid, sid, nature, nat)
            head = bytearray(head)
            struct.pack_into("<I", head, 0, pid)

    buf, off = exp_at
    exp = struct.unpack_from("<I", buf, off)[0]
    party = where[0] == "party" and len(tail) >= 20
    if nat0 in table and nat in table:
        level = tail[4] if party and tail[4] else level_for_exp(table[nat0][6], exp)
        if "level" in changes:
            level = max(1, min(100, int(changes["level"])))
        if "level" in changes or nat != nat0:
            exp = exp_for_level(table[nat][6], level)
            struct.pack_into("<I", buf, off, exp)
        stat_keys = {"species", "ivs", "evs", "level", "nature", "recalc"}
        if party and stat_keys & set(changes):
            ivs = [(ivw >> (5 * k)) & 31 for k in range(6)]
            st = calc_stats(nat, table[nat][:6], ivs, evs, level, nature)
            hp, hp_max = struct.unpack_from("<HH", tail, 6)
            hp = 0 if hp == 0 else max(1, min(st[0], hp + st[0] - hp_max))
            if changes.get("recalc"):
                hp = st[0]
            tail[4] = level
            struct.pack_into("<HH5H", tail, 6, hp, *st)
    elif "level" in changes:
        raise ValueError(f"données de l'espèce {nat} absentes : niveau non modifiable")

    if gen3:
        write_mon(sv, where, pk3_pack(head, sub, bytes(tail)))
    else:
        write_mon(sv, where, pk45_pack(head, blk, tail))


_PP = {}


def _move_pp(gen, move):
    if not _PP:
        import json
        import sys
        from paths import res
        with open(res("data", "move_pp.json"), encoding="utf-8") as f:
            _PP.update(json.load(f))
    return _PP.get(str(gen), {}).get(str(move), 0)


def _gen3_internal(nat):
    for i in range(1, 412):
        if gen3_species_to_national(i) == nat:
            return i
    raise ValueError(f"espèce {nat} inconnue en 3G")


def set_money(sv, value):
    value = max(0, min(999999, int(value)))
    if isinstance(sv, Gen3Save):
        o, s1 = sv.sections[1]
        struct.pack_into("<I", s1, 0x290 if sv.family == "FRLG" else 0x490, value ^ sv.key)
        _gen3_fix_section(sv, 1)
    elif isinstance(sv, Gen4Save):
        struct.pack_into("<I", sv.raw, sv.blocks["general"] + GEN4_LAYOUT[sv.family]["trainer"] + 0x14, value)
        _gen4_fix_block(sv, "general")
    else:
        start, length, tab = GEN5_BLOCKS[sv.family]["money"]
        struct.pack_into("<I", sv.raw, start, value)
        _gen5_fix(sv, start, length, tab)


BAG3 = {"E": [("pc", "PC", 0x498, 50, None), ("items", "Objets", 0x560, 30, 1), ("key", "Objets rares", 0x5D8, 30, 5),
              ("balls", "Balls", 0x650, 16, 2), ("tm", "CT / CS", 0x690, 64, 3), ("berries", "Baies", 0x790, 46, 4)],
        "RS": [("pc", "PC", 0x498, 50, None), ("items", "Objets", 0x560, 20, 1), ("key", "Objets rares", 0x5B0, 20, 5),
               ("balls", "Balls", 0x600, 16, 2), ("tm", "CT / CS", 0x640, 64, 3), ("berries", "Baies", 0x740, 46, 4)],
        "FRLG": [("pc", "PC", 0x298, 30, None), ("items", "Objets", 0x310, 42, 1), ("key", "Objets rares", 0x3B8, 30, 2),
                 ("balls", "Balls", 0x430, 13, 3), ("tm", "CT / CS", 0x464, 58, 4), ("berries", "Baies", 0x54C, 43, 5)]}
_P4 = [("items", "Objets", 165, 0), ("key", "Objets rares", 50, 7), ("tm", "CT / CS", 100, 3), ("mail", "Lettres", 12, 5),
       ("med", "Soins", 40, 1), ("berries", "Baies", 64, 4), ("balls", "Balls", 15, 2), ("battle", "Combat", 30, 6)]
BAG4_START = {"DP": 0x624, "PT": 0x630, "HGSS": 0x644}
_P5 = [("items", "Objets", 310, 0), ("key", "Objets rares", 83, 4), ("tm", "CT / CS", 109, 2), ("med", "Soins", 48, 1),
       ("berries", "Baies", 64, 3)]
BAG5_BLOCK = {"BW": (0x18400, 0x9C0, 0x32), "B2W2": (0x18400, 0x9EC, 0x32)}


def save_family(sv):
    if isinstance(sv, Gen3Save):
        return "FRLG" if sv.family == "FRLG" else ("RS" if sv.key == 0 else "E")
    return sv.family


def _pockets(sv):
    fam = save_family(sv)
    if isinstance(sv, Gen3Save):
        return BAG3[fam]
    out, o = [], (BAG4_START[fam] if isinstance(sv, Gen4Save) else 0)
    for key, label, n, code in (_P4 if isinstance(sv, Gen4Save) else _P5):
        if fam == "HGSS":
            n = {"tm": 101, "balls": 24}.get(key, n)
        out.append((key, label, o, n, code))
        o += 4 * n
    return out


def _bag_buf(sv):
    if isinstance(sv, Gen3Save):
        return sv.sections[1][1], 0
    if isinstance(sv, Gen4Save):
        return sv.raw, sv.blocks["general"]
    return sv.raw, BAG5_BLOCK[sv.family][0]


def bag(sv):
    buf, base = _bag_buf(sv)
    xor = sv.key & 0xFFFF if isinstance(sv, Gen3Save) else 0
    out = []
    for key, label, off, n, code in _pockets(sv):
        items = []
        for i in range(n):
            it, q = struct.unpack_from("<HH", buf, base + off + 4 * i)
            if it:
                items.append([it, q ^ (0 if key == "pc" else xor)])
        out.append({"key": key, "label": label, "size": n, "code": code, "items": items})
    return out


def set_bag(sv, pockets):
    buf, base = _bag_buf(sv)
    xor = sv.key & 0xFFFF if isinstance(sv, Gen3Save) else 0
    top = 99 if isinstance(sv, Gen3Save) else 999
    for key, label, off, n, code in _pockets(sv):
        if key not in pockets:
            continue
        items = [(int(a), int(q)) for a, q in pockets[key] if int(a) and int(q) > 0]
        if len(items) > n:
            raise ValueError(f"{label} : {len(items)} objets pour {n} places")
        for i in range(n):
            a, q = items[i] if i < len(items) else (0, 0)
            q = min(q, 999 if key == "pc" else top)
            struct.pack_into("<HH", buf, base + off + 4 * i, a, (q if a else 0) ^ (0 if key == "pc" else xor))
    if isinstance(sv, Gen3Save):
        _gen3_fix_section(sv, 1)
    elif isinstance(sv, Gen4Save):
        _gen4_fix_block(sv, "general")
    else:
        _gen5_fix(sv, *BAG5_BLOCK[sv.family])


def item_pockets(rom_path):
    import randomizer as R
    import randomizer_gen4 as R4
    import gen4_maps
    import nds_rebuild
    with open(rom_path, "rb") as f:
        rom = f.read()
    out = {}
    if rom_path.lower().endswith(".gba"):
        o = next((o for o in range(0, len(rom) - 44 * 12, 4)
                  if all(struct.unpack_from("<H", rom, o + 44 * i + 14)[0] == i for i in range(12))), None)
        if o is None:
            raise ValueError("3G : table des objets introuvable")
        title = rom[0xA0:0xAC].decode("latin-1")
        last = 374 if title.startswith(("POKEMON FIRE", "POKEMON LEAF")) else 348 if title.startswith(("POKEMON RUBY", "POKEMON SAPP")) else 376
        for i in range(1, last + 1):
            if struct.unpack_from("<H", rom, o + 44 * i + 14)[0] == i:
                out[i] = rom[o + 44 * i + 26]
        return out
    key = gen4_maps._rom_title(rom_path)
    if key in R4.PATHS4:
        path, last = {"POKEMON D": ("itemtool/itemdata/item_data.narc", 464), "POKEMON P": ("itemtool/itemdata/item_data.narc", 464),
                      "POKEMON PL": ("itemtool/itemdata/pl_item_data.narc", 467)}.get(key, ("a/0/1/7", 536))
        sp = R.narc_spans(rom, path)
        a9 = bytes(nds_rebuild.arm9_read(rom)[0])
        e = lambda t, k, c: struct.unpack_from("<H", a9, t + 8 * k + 2 * c)[0]
        tab = [t for t in range(0, len(a9) - 8 * 30, 2)
               if e(t, 1, 3) == 1 and e(t, 4, 3) == 4 and e(t, 17, 3) == 13 and e(t, 28, 3) == 24 and e(t, 1, 0) == 1]
        if len(tab) != 1:
            raise ValueError("4G : table des objets introuvable dans l'ARM9")
        for i in range(1, last + 1):
            d = e(tab[0], i, 0)
            if 0 < d < len(sp):
                out[i] = (struct.unpack_from("<H", rom, sp[d][0] + 8)[0] >> 7) & 15
        return out
    sp = R.narc_spans(rom, "a/0/2/4")
    for i in range(1, len(sp)):
        out[i] = (struct.unpack_from("<H", rom, sp[i][0] + 8)[0] >> 7) & 15
    return out


_POCKETS = {}


def item_pockets_default(family):
    if not _POCKETS:
        import json
        with open(os.path.join(_data_dir(), "item_pockets.json"), encoding="utf-8") as f:
            _POCKETS.update({k: {int(i): c for i, c in v.items()} for k, v in json.load(f).items()})
    return _POCKETS[family]


DEX3_SEEN = {"E": (0x988, 0x3B24), "RS": (0x938, 0x3A8C), "FRLG": (0x5F8, 0x3A18)}
DEX4 = {"DP": 0x12DC, "PT": 0x1328, "HGSS": 0x12B8}
DEX5 = {"BW": (0x21600, 0x4D4, 0x6E), "B2W2": (0x21400, 0x4DC, 0x6C)}
DEX_MAX = {3: 386, 4: 493, 5: 649}


def _sb1_at(sv, off):
    return sv.sections[1 + off // 3968][1], off % 3968


def _bits(buf, o, n):
    return {i + 1 for i in range(n) if buf[o + (i >> 3)] >> (i & 7) & 1}


def _set_bit(buf, o, nat, on):
    i = nat - 1
    if on:
        buf[o + (i >> 3)] |= 1 << (i & 7)
    else:
        buf[o + (i >> 3)] &= ~(1 << (i & 7)) & 0xFF


def _dex_where(sv):
    if isinstance(sv, Gen4Save):
        o = sv.blocks["general"] + DEX4[sv.family]
        if struct.unpack_from("<I", sv.raw, o)[0] != 0xBEEFCAFE:
            raise ValueError("Pokédex 4G introuvable")
        return o
    if isinstance(sv, Gen5Save):
        o = DEX5[sv.family][0]
        if struct.unpack_from("<I", sv.raw, o)[0] != 0xBEEFCAFE:
            raise ValueError("Pokédex 5G introuvable")
        return o
    return None


def dex(sv):
    n = DEX_MAX[sv.gen]
    if isinstance(sv, Gen3Save):
        s0 = sv.sections[0][1]
        caught, seen = _bits(s0, 0x28, n), _bits(s0, 0x5C, n)
    elif isinstance(sv, Gen4Save):
        o = _dex_where(sv)
        caught, seen = _bits(sv.raw, o + 4, n), _bits(sv.raw, o + 0x44, n)
    else:
        o = _dex_where(sv) + 8
        caught = _bits(sv.raw, o, n)
        seen = set().union(*(_bits(sv.raw, o + 0x54 * k, n) for k in range(1, 5)))
    return {"max": n, "seen": sorted(seen | caught), "caught": sorted(caught)}


def set_dex(sv, seen, caught, table=None):
    n = DEX_MAX[sv.gen]
    caught = {int(x) for x in caught if 1 <= int(x) <= n}
    seen = {int(x) for x in seen if 1 <= int(x) <= n} | caught
    table = table or base_table(sv.gen)
    female = lambda nat: len(table.get(nat, [])) > 7 and table[nat][7] == 254
    old = set(dex(sv)["seen"])
    if isinstance(sv, Gen3Save):
        s0 = sv.sections[0][1]
        fam = save_family(sv)
        copies = [_sb1_at(sv, o) for o in DEX3_SEEN[fam]]
        for nat in range(1, n + 1):
            _set_bit(s0, 0x28, nat, nat in caught)
            _set_bit(s0, 0x5C, nat, nat in seen)
            for buf, o in copies:
                _set_bit(buf, o, nat, nat in seen)
        for sid in {0, 1} | {1 + o // 3968 for o in DEX3_SEEN[fam]}:
            _gen3_fix_section(sv, sid)
        return
    if isinstance(sv, Gen4Save):
        o = _dex_where(sv)
        for nat in range(1, n + 1):
            _set_bit(sv.raw, o + 4, nat, nat in caught)
            _set_bit(sv.raw, o + 0x44, nat, nat in seen)
            if nat not in seen or nat not in old:
                for g in (0x84, 0xC4):
                    _set_bit(sv.raw, o + g, nat, nat in seen and female(nat))
        _gen4_fix_block(sv, "general")
        return
    start, length, tab = DEX5[sv.family]
    o = _dex_where(sv) + 8
    for nat in range(1, n + 1):
        _set_bit(sv.raw, o, nat, nat in caught)
        if nat not in seen or nat not in old:
            for k in range(1, 9):
                _set_bit(sv.raw, o + 0x54 * k, nat, False)
            if nat in seen:
                k = 2 if female(nat) else 1
                _set_bit(sv.raw, o + 0x54 * k, nat, True)
                _set_bit(sv.raw, o + 0x54 * (k + 4), nat, True)
    _gen5_fix(sv, start, length, tab)


MON_EXT = {3: ".pk3", 4: ".pk4", 5: ".pk5"}
BOX_SIZE = {3: 80, 4: 136, 5: 136}
PARTY_SIZE = {3: 100, 4: 236, 5: 220}


def export_mon(sv, where):
    raw = read_mon(sv, where)
    if isinstance(sv, Gen3Save):
        if decode_pk3(raw) is None:
            return None
        head, sub, _ = pk3_unpack(raw[:80])
        return bytes(head) + b"".join(bytes(sub[c]) for c in "GAEM")
    if decode_pk45(raw[:136], sv.gen) is None:
        return None
    head, blk, _ = pk45_unpack(raw[:136])
    return bytes(head) + b"".join(bytes(blk[c]) for c in "ABCD")


def _box_raw_from_file(sv, data):
    gen = sv.gen
    if len(data) not in (BOX_SIZE[gen], PARTY_SIZE[gen]):
        raise ValueError(f"fichier de {len(data)} octets : pas un Pokémon {gen}G")
    data = bytes(data[:BOX_SIZE[gen]])
    if gen == 3:
        plain = struct.unpack_from("<H", data, 0x1C)[0] == sum(struct.unpack_from("<24H", data, 0x20)) & 0xFFFF
        if plain and struct.unpack_from("<H", data, 0x20)[0]:
            raw = pk3_pack(data[:0x20], {c: data[0x20 + 12 * i:0x2C + 12 * i] for i, c in enumerate("GAEM")}, b"")
        else:
            raw = data
        m = decode_pk3(raw)
    else:
        plain = struct.unpack_from("<H", data, 6)[0] == sum(struct.unpack_from("<64H", data, 8)) & 0xFFFF
        if plain and struct.unpack_from("<H", data, 8)[0]:
            raw = pk45_pack(data[:8], {c: data[8 + 32 * i:40 + 32 * i] for i, c in enumerate("ABCD")}, b"")
        else:
            raw = data
        m = decode_pk45(raw, gen)
    if not m or m.get("bad"):
        raise ValueError("fichier illisible (somme de contrôle fausse ou mauvaise génération)")
    if not 1 <= m["species"] <= DEX_MAX[gen]:
        raise ValueError(f"espèce {m['species']} inconnue en {gen}G")
    return raw


def _party_count_at(sv):
    if isinstance(sv, Gen3Save):
        return sv.sections[1][1], (0x34 if sv.family == "FRLG" else 0x234)
    if isinstance(sv, Gen4Save):
        return sv.raw, sv.blocks["general"] + GEN4_LAYOUT[sv.family]["party"]
    return sv.raw, 0x18E04


def import_mon(sv, where, data, table=None):
    place_mon(sv, where, _box_raw_from_file(sv, data), table)


def remove_mon(sv, where):
    if where[0] != "party":
        write_mon(sv, where, bytes(BOX_SIZE[sv.gen]))
        return
    buf, o = _party_count_at(sv)
    n = struct.unpack_from("<I", buf, o)[0]
    if n <= 1:
        raise ValueError("impossible de retirer le dernier Pokémon de l'équipe")
    if where[1] >= n:
        raise ValueError("place déjà vide")
    mons = [read_mon(sv, ("party", k)) for k in range(n)]
    del mons[where[1]]
    struct.pack_into("<I", buf, o, n - 1)
    for k in range(6):
        write_mon(sv, ("party", k), mons[k] if k < len(mons) else bytes(PARTY_SIZE[sv.gen]))


MOVE_MAX = {3: 354, 4: 467, 5: 559}


def check_mon(gen, m, table=None, pockets=None):
    if not m:
        return []
    if m.get("bad"):
        return ["données abîmées (somme de contrôle fausse)"]
    out = []
    if not 1 <= m["species"] <= DEX_MAX[gen]:
        out.append(f"espèce {m['species']} inconnue en {gen}G")
    if sum(m["evs"]) > 510:
        out.append(f"EV : {sum(m['evs'])} au total (510 maximum)")
    mv = [x for x in m["moves"] if x]
    if not mv:
        out.append("aucune attaque")
    if len(set(mv)) != len(mv):
        out.append("la même attaque deux fois")
    if any(x > MOVE_MAX[gen] for x in mv):
        out.append("attaque inconnue dans ce jeu")
    if m["item"] and pockets is not None and m["item"] not in pockets:
        out.append("objet tenu inconnu dans ce jeu")
    if m.get("nature", 0) >= 25:
        out.append("nature invalide")
    if table and m["species"] in table and not m.get("egg"):
        lv = level_for_exp(table[m["species"]][6], m["exp"])
        if m.get("level") and m["level"] != lv:
            out.append(f"niveau {m['level']} mais expérience du niveau {lv}")
        if m["exp"] > exp_for_level(table[m["species"]][6], 100):
            out.append("expérience au-delà du niveau 100")
    return out


def _plain_upper(name):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", name) if unicodedata.category(c) != "Mn").upper()


def _encode_name(gen, name, size):
    if gen == 3:
        inv = {v: k for k, v in _G3.items() if len(v) == 1}
        out = bytearray(inv[c] for c in _plain_upper(name) if c in inv)[:size]
        return bytes(out + b"\xFF" * (size - len(out)))
    if gen == 4:
        import gen4_maps
        inv = {v: k for k, v in gen4_maps._charmap().items() if len(v) == 1}
        codes = [inv[c] for c in _plain_upper(name) if c in inv]
    else:
        codes = [ord(c) for c in name]
    codes = codes[:size - 1] + [0xFFFF]
    return struct.pack(f"<{size}H", *(codes + [0] * (size - len(codes))))


def _template_mon(sv):
    t = sv.trainer()
    raws = [read_mon(sv, ("party", i))[:BOX_SIZE[sv.gen]] for i in range(len(sv.party()))]
    dec = (lambda r: decode_pk3(r)) if sv.gen == 3 else (lambda r: decode_pk45(r, sv.gen))
    good = [r for r in raws if (m := dec(r)) and not m.get("bad")]
    if not good:
        raise ValueError("aucun Pokémon lisible dans l'équipe pour servir de modèle")
    own = [r for r in good if (m := dec(r))["tid"] == t["tid"] and m["sid"] == t["sid"]]
    return (own or good)[0]


def species_names_raw(rom_path):
    import randomizer as R
    import randomizer_gen3 as R3
    import randomizer_gen4 as R4
    import gen4_maps
    import nds_rebuild
    with open(rom_path, "rb") as f:
        rom = f.read()
    out = {}
    if rom_path.lower().endswith(".gba"):
        inv = {v: k for k, v in _G3.items() if len(v) == 1}
        pika = bytes(inv[c] for c in "PIKACHU") + b"\xFF"
        starts = [h - 11 * 25 for h in R3._find_all(rom, pika) if h >= 11 * 25 and rom[h - 11 * 24 - 1] in (0xFF, 0)]
        starts = [t for t in starts if rom[t + 11:t + 12] != b"\xFF"]
        if not starts:
            raise ValueError("3G : noms des Pokémon introuvables")
        t = starts[0]
        for nat in range(1, 387):
            o = t + 11 * _gen3_internal(nat)
            out[nat] = bytes(rom[o:o + 11]).split(b"\xFF")[0][:10]
        return out
    key = gen4_maps._rom_title(rom_path)
    if key in R4.PATHS4:
        inv = {v: k for k, v in gen4_maps._charmap().items() if len(v) == 1}
        pika = [inv[c] for c in "PIKACHU"]
        for bank in gen4_maps._narc_files(gen4_maps._rom_file(rom, R4.PATHS4[key]["msg"])):
            try:
                _, msgs = R4.msg_raw(bank)
            except Exception:
                continue
            if len(msgs) > 493 and [c for c in msgs[25] if c != 0xFFFF] == pika:
                return {nat: [c for c in msgs[nat] if c != 0xFFFF][:10] for nat in range(1, 494)}
        raise ValueError("4G : noms des Pokémon introuvables")
    import gen5_maps
    s_, e_ = R.file_span(bytearray(rom), gen5_maps.GAMES[key]["narcs"]["text"])
    members, _ = nds_rebuild.narc_unpack(bytes(rom[s_:e_]))
    for bank in members:
        try:
            names = nds_rebuild.text_unpack(bank)["blocks"][0]
            if len(names) > 649 and [c for c in nds_rebuild.decompress(names[25]) if c != 0xFFFF] == [ord(c) for c in "Pikachu"]:
                return {nat: [c for c in nds_rebuild.decompress(names[nat]) if c != 0xFFFF][:10] for nat in range(1, 650)}
        except Exception:
            continue
    raise ValueError("5G : noms des Pokémon introuvables")


def _trainer_name_raw(sv):
    if isinstance(sv, Gen3Save):
        return bytes(sv.sections[0][1][0:7])
    if isinstance(sv, Gen4Save):
        o = sv.blocks["general"] + GEN4_LAYOUT[sv.family]["trainer"]
        return bytes(sv.raw[o:o + 16])
    return bytes(sv.raw[0x19404:0x19414])


def create_mon(sv, where, species, level, nature, shiny=False, moves=None, table=None, ivs=None, names=None):
    import random
    rng = random.SystemRandom()
    gen = sv.gen
    table = table or base_table(gen)
    species, level, nature = int(species), max(1, min(100, int(level))), int(nature) % 25
    if species not in table or not 1 <= species <= DEX_MAX[gen]:
        raise ValueError(f"espèce {species} inconnue en {gen}G")
    info = table[species]
    growth, ratio = info[6], info[7]
    friend = info[8] if len(info) > 8 else 70
    abil = info[9:12] if len(info) > 9 else [0, 0, 0]
    t = sv.trainer()
    tid, sid = t["tid"], t["sid"]
    moves = [int(m) for m in (moves or []) if int(m)][:4]
    if not moves:
        moves = [33]
    moves += [0] * (4 - len(moves))
    ivs = [int(v) & 31 for v in ivs] if ivs else [rng.randrange(32) for _ in range(6)]
    for _ in range(10 ** 6):
        lo = rng.randrange(0x10000)
        hi = (tid ^ sid ^ lo ^ rng.randrange(8)) if shiny else rng.randrange(0x10000)
        pid = hi << 16 | lo
        if ((tid ^ sid ^ hi ^ lo) < 8) != bool(shiny):
            continue
        if gen < 5 and pid % 25 != nature:
            continue
        break
    female = ratio == 254 or (ratio not in (0, 255) and (pid & 0xFF) < ratio)
    exp = exp_for_level(growth, level)
    ivword = sum(v << (5 * k) for k, v in enumerate(ivs))
    tmpl = _template_mon(sv)
    if gen == 3:
        head, sub, _ = pk3_unpack(tmpl)
        head = bytearray(head)
        struct.pack_into("<II", head, 0, pid, tid | sid << 16)
        if names and species in names:
            head[8:18] = (bytes(names[species]) + b"\xFF" * 10)[:10]
        else:
            head[8:18] = _encode_name(3, _species_name(sv, species), 10)
        head[19] = 2
        head[20:27] = _trainer_name_raw(sv)
        head[27] = 0
        G, A, E, M = (bytearray(12) for _ in range(4))
        struct.pack_into("<HHIBB", G, 0, _gen3_internal(species), 0, exp, 0, friend)
        struct.pack_into("<4H", A, 0, *moves)
        A[8:12] = bytes(_move_pp(3, m) if m else 0 for m in moves)
        old_m = sub["M"]
        origins = struct.unpack_from("<H", old_m, 2)[0] & ~0x7F | level
        slot = rng.randrange(2) if abil[1] else 0
        struct.pack_into("<BBHII", M, 0, 0, old_m[1], origins, ivword | slot << 31, 0)
        raw = pk3_pack(head, {"G": G, "A": A, "E": E, "M": M}, b"")
    else:
        head, blk, _ = pk45_unpack(tmpl)
        head = bytearray(head)
        struct.pack_into("<I", head, 0, pid)
        A, B, C, D = blk["A"], blk["B"], blk["C"], blk["D"]
        slot = (pid >> 16 & 1) if gen == 5 else (pid & 1)
        ability = abil[slot] if abil[slot] else abil[0]
        lang = A[15]
        A[:] = bytes(32)
        struct.pack_into("<HHHHIBBBB", A, 0, species, 0, tid, sid, exp, friend, ability, 0, lang)
        keep_b = bytes(B[0x1B:])
        B[:] = bytes(32)
        struct.pack_into("<4H", B, 0, *moves)
        B[8:12] = bytes(_move_pp(gen, m) if m else 0 for m in moves)
        struct.pack_into("<I", B, 16, ivword)
        B[0x18] = (4 if ratio == 255 else 2 if female else 0)
        if gen == 5:
            B[0x19] = nature
        B[0x1B:] = keep_b
        origin = C[0x17]
        C[:] = bytes(32)
        if names and species in names:
            codes = list(names[species])[:10] + [0xFFFF]
            C[0:22] = struct.pack("<11H", *(codes + [0] * (11 - len(codes))))
        else:
            C[0:22] = _encode_name(gen, _species_name(sv, species), 11)
        C[0x17] = origin
        D[0:16] = _trainer_name_raw(sv)
        import datetime
        today = datetime.date.today()
        D[0x13:0x16] = bytes([today.year % 100, today.month, today.day])
        D[0x1A] = 0
        D[0x1C] = (D[0x1C] & 0x80) | level
        raw = pk45_pack(head, blk, b"")
    place_mon(sv, where, raw, table)


def _species_name(sv, species):
    import json
    vg = {3: 6, 4: 9, 5: 14}[sv.gen]
    with open(os.path.join(_data_dir(), "fiche", f"vg_{vg}.json"), encoding="utf-8") as f:
        return json.load(f)["species"][str(species)]["name"]


def place_mon(sv, where, raw, table=None):
    if where[0] != "party":
        write_mon(sv, where, raw)
        return
    buf, o = _party_count_at(sv)
    n = struct.unpack_from("<I", buf, o)[0]
    i = where[1]
    if i > n or i >= 6:
        raise ValueError("équipe : choisis un Pokémon à remplacer ou la première place libre")
    if i == n:
        struct.pack_into("<I", buf, o, n + 1)
    if sv.gen == 3:
        full = raw + bytes(20)
    else:
        head, blk, _ = pk45_unpack(raw)
        full = pk45_pack(head, blk, bytearray(PARTY_SIZE[sv.gen] - 136))
    write_mon(sv, where, full)
    edit_mon(sv, where, {"recalc": True}, table)


def write_save(sv, path):
    if isinstance(sv, Gen5Save):
        d = GEN5_BLOCKS[sv.family]["backup"]
        sv.raw[d:2 * d] = sv.raw[0:d]
    raw = bytes(sv.raw)
    old = open(path, "rb").read()
    if len(old) == 0x20010:
        raw += old[0x20000:]
    if not os.path.exists(path + ".bak"):
        with open(path + ".bak", "wb") as f:
            f.write(old)
    with open(path, "wb") as f:
        f.write(raw)
