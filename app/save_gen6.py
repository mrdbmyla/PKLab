import binascii
import datetime
import random
import struct

import azahar_reader as A

SIZE = 232
PARTY_SIZE = 260
FAMILIES = {0x65600: "XY", 0x76000: "ORAS"}
BOX_START = {"XY": 0x22600, "ORAS": 0x33000}
BOXES = 31
PARTY = 0x14200
TRAINER = 0x14000
MONEY = 0x4208
BAG = 0x400
DEX = 0x15000
DEX_MAX = 721
MOVE_MAX = 621
POCKETS = {
    "XY": [("items", "Objets", 0x000, 400, 0), ("key", "Objets rares", 0x640, 96, 4), ("tm", "CT / CS", 0x7C0, 106, 2),
           ("med", "Soins", 0x968, 64, 1), ("berries", "Baies", 0xA68, 72, 3)],
    "ORAS": [("items", "Objets", 0x000, 400, 0), ("key", "Objets rares", 0x640, 96, 4), ("tm", "CT / CS", 0x7C0, 108, 2),
             ("med", "Soins", 0x970, 64, 1), ("berries", "Baies", 0xA70, 72, 3)],
}
VERSION = {"XY": 24, "ORAS": 26}
BALL_POKE = 4
TITLES = {"POKEMON X": "XY", "POKEMON Y": "XY", "POKEMON OR": "ORAS", "POKEMON AS": "ORAS"}


def crc(data):
    return binascii.crc_hqx(bytes(data), 0xFFFF)


def decrypt(raw):
    raw = bytes(raw[:SIZE])
    return A.decrypt_pk6(raw)


def encrypt(pk):
    pk = bytearray(pk[:SIZE])
    struct.pack_into("<H", pk, 6, sum(struct.unpack_from("<112H", pk, 8)) & 0xFFFF)
    ec = struct.unpack_from("<I", pk)[0]
    order = A.ORDER[((ec >> 13) & 31) % 24]
    plain = {c: bytes(pk[8 + 56 * i:64 + 56 * i]) for i, c in enumerate("ABCD")}
    body = b"".join(plain[c] for c in order)
    return bytes(pk[:8]) + A._xor(body, A._keys(ec, 112))


def crypt_party(ec, stats):
    return A._xor(bytes(stats), A._keys(ec, 14))


EMPTY = encrypt(bytes(SIZE))


def text(b):
    s = bytes(b).decode("utf-16-le", "replace")
    return s.split("\0")[0]


def encode(name, chars=13):
    raw = name[:chars - 1].encode("utf-16-le")
    return raw + bytes(2 * chars - len(raw))


def is_shiny(tid, sid, pid):
    return (tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF)) < 16


def decode(raw):
    if len(raw) < SIZE or not any(raw[:SIZE]):
        return None
    pk = decrypt(raw)
    if not A.checksum_ok(pk):
        return {"bad": True, "pid": 0}
    species = struct.unpack_from("<H", pk, 8)[0]
    if species == 0:
        return None
    item, tid, sid, exp = struct.unpack_from("<HHHI", pk, 0x0A)
    pid = struct.unpack_from("<I", pk, 0x18)[0]
    iv = struct.unpack_from("<I", pk, 0x74)[0]
    handler = pk[0x93]
    out = {"pid": pid, "ec": struct.unpack_from("<I", pk)[0], "species": species, "item": item, "tid": tid, "sid": sid,
           "exp": exp, "ability": pk[0x14], "ability_slot": pk[0x15], "nature": pk[0x1C], "form": pk[0x1D] >> 3,
           "evs": list(pk[0x1E:0x24]), "moves": list(struct.unpack_from("<4H", pk, 0x5A)), "pp": list(pk[0x62:0x66]),
           "pp_ups": list(pk[0x66:0x6A]), "ivs": [(iv >> (5 * k)) & 31 for k in range(6)], "egg": bool(iv >> 30 & 1),
           "friendship": pk[0xA2] if handler else pk[0xCA], "nickname": text(pk[0x40:0x5A]), "ot": text(pk[0xB0:0xCA]),
           "shiny": is_shiny(tid, sid, pid), "bad": False}
    if len(raw) >= PARTY_SIZE:
        st = crypt_party(out["ec"], raw[SIZE:PARTY_SIZE])
        out["level"] = st[4]
        out["hp"], out["hp_max"] = struct.unpack_from("<HH", st, 8)
        out["stats"] = list(struct.unpack_from("<5H", st, 0xC))
    return out


class Gen6Save:
    gen = 6

    def __init__(self, raw, family):
        self.raw = bytearray(raw)
        self.family = family
        self.problems = []
        self.blocks = []
        mo = len(raw) - 0x1F0
        if struct.unpack_from("<I", raw, mo)[0] != 0x42454546:
            raise ValueError("sauvegarde 6G : table des blocs introuvable")
        off, p = 0, mo + 4
        while p + 8 <= len(raw):
            ln, bid, ck = struct.unpack_from("<IHH", raw, p)
            if not ln:
                break
            self.blocks.append((off, ln, p + 6))
            off = (off + ln + 0x1FF) & ~0x1FF
            p += 8
        bad = [i for i, (o, ln, at) in enumerate(self.blocks) if crc(raw[o:o + ln]) != struct.unpack_from("<H", raw, at)[0]]
        if bad:
            self.problems.append(f"{len(bad)} bloc(s) avec une somme de contrôle fausse")
        if not 0 <= self.party_count() <= 6:
            self.problems.append("équipe illisible")

    def fix(self):
        for o, ln, at in self.blocks:
            struct.pack_into("<H", self.raw, at, crc(self.raw[o:o + ln]))

    def finish(self):
        self.fix()
        return bytes(self.raw)

    def party_count(self):
        return self.raw[PARTY + 6 * PARTY_SIZE]

    def set_party_count(self, n):
        self.raw[PARTY + 6 * PARTY_SIZE] = n

    def trainer(self):
        tid, sid = struct.unpack_from("<HH", self.raw, TRAINER)
        return {"name": text(self.raw[TRAINER + 0x48:TRAINER + 0x62]), "tid": tid, "sid": sid,
                "money": struct.unpack_from("<I", self.raw, MONEY)[0],
                "gender": "fille" if self.raw[TRAINER + 5] else "garçon"}

    def slot(self, where):
        if where[0] == "party":
            return PARTY + PARTY_SIZE * where[1], PARTY_SIZE
        return BOX_START[self.family] + SIZE * (where[1] * 30 + where[2]), SIZE

    def read(self, where):
        o, n = self.slot(where)
        return bytes(self.raw[o:o + n])

    def write(self, where, raw):
        o, n = self.slot(where)
        if len(raw) != n:
            raise ValueError("taille de Pokémon incorrecte")
        self.raw[o:o + n] = raw

    def party(self):
        return [decode(self.read(("party", i))) for i in range(min(self.party_count(), 6))]

    def pc(self):
        return [[decode(self.read(("box", b, i))) for i in range(30)] for b in range(BOXES)], \
            [f"Boîte {b + 1}" for b in range(BOXES)]


PERSONAL = {"XY": ("a/2/1/8", 0x40), "ORAS": ("a/1/9/5", 0x50)}


def rom_family(rom_path):
    import rom_finder
    hit = rom_finder.identify(rom_path)
    fam = TITLES.get(hit[1]) if hit else None
    if not fam:
        raise ValueError("ROM 3DS : jeu de 6G non reconnu")
    return fam


def personal_rom(rom_path):
    import ctr_rom
    path, size = PERSONAL[rom_family(rom_path)]
    fs = ctr_rom.RomFS(rom_path)
    try:
        files = ctr_rom.garc(fs.read(path))
    finally:
        fs.close()
    blob = files[-1]
    if len(blob) < size * 722:
        raise ValueError("ROM 3DS : données des Pokémon introuvables")
    out = {}
    for nat in range(1, DEX_MAX + 1):
        p = blob[size * nat:size * (nat + 1)]
        out[nat] = list(p[0:6]) + [p[0x15], p[0x12], p[0x14], p[0x18], p[0x19], p[0x1A]]
    return out


def open_save(raw, game_key=None):
    fam = TITLES.get(game_key) or FAMILIES.get(len(raw))
    if not fam or len(raw) != {v: k for k, v in FAMILIES.items()}[fam]:
        raise ValueError(f"Format de sauvegarde 6G inconnu ({len(raw)} octets)")
    return Gen6Save(raw, fam)


def set_money(sv, value):
    struct.pack_into("<I", sv.raw, MONEY, max(0, min(A.MAX_MONEY, int(value))))


def bag(sv):
    out = []
    for key, label, off, n, code in POCKETS[sv.family]:
        items = []
        for i in range(n):
            it, q = struct.unpack_from("<HH", sv.raw, BAG + off + 4 * i)
            if it:
                items.append([it, q])
        out.append({"key": key, "label": label, "size": n, "code": code, "items": items})
    return out


def set_bag(sv, pockets):
    for key, label, off, n, code in POCKETS[sv.family]:
        if key not in pockets:
            continue
        items = [(int(a), min(A.ITEM_CAP, int(q))) for a, q in pockets[key] if int(a) and int(q) > 0]
        if len(items) > n:
            raise ValueError(f"{label} : {len(items)} objets pour {n} places")
        for i in range(n):
            a, q = items[i] if i < len(items) else (0, 0)
            struct.pack_into("<HH", sv.raw, BAG + off + 4 * i, a, q if a else 0)


def _bits(buf, o, n):
    return {i + 1 for i in range(n) if buf[o + (i >> 3)] >> (i & 7) & 1}


def _set_bit(buf, o, nat, on):
    i = nat - 1
    if on:
        buf[o + (i >> 3)] |= 1 << (i & 7)
    else:
        buf[o + (i >> 3)] &= ~(1 << (i & 7)) & 0xFF


def dex(sv):
    o = DEX + 8
    caught = _bits(sv.raw, o, DEX_MAX)
    seen = set().union(*(_bits(sv.raw, o + 0x60 * k, DEX_MAX) for k in range(1, 5)))
    return {"max": DEX_MAX, "seen": sorted(seen | caught), "caught": sorted(caught)}


def set_dex(sv, seen, caught, table):
    caught = {int(x) for x in caught if 1 <= int(x) <= DEX_MAX}
    seen = {int(x) for x in seen if 1 <= int(x) <= DEX_MAX} | caught
    old = set(dex(sv)["seen"])
    o = DEX + 8
    for nat in range(1, DEX_MAX + 1):
        _set_bit(sv.raw, o, nat, nat in caught)
        if nat not in seen or nat not in old:
            for k in range(1, 9):
                _set_bit(sv.raw, o + 0x60 * k, nat, False)
            if nat in seen:
                info = table.get(nat, [])
                k = 2 if len(info) > 7 and info[7] == 254 else 1
                _set_bit(sv.raw, o + 0x60 * k, nat, True)
                _set_bit(sv.raw, o + 0x60 * (k + 4), nat, True)


def _parts(sv, where):
    raw = sv.read(where)
    pk = bytearray(decrypt(raw))
    stats = bytearray(crypt_party(struct.unpack_from("<I", pk)[0], raw[SIZE:])) if where[0] == "party" else None
    return pk, stats


def _store(sv, where, pk, stats):
    enc = encrypt(pk)
    if stats is not None:
        enc += crypt_party(struct.unpack_from("<I", pk)[0], stats)
    sv.write(where, enc)


def edit_mon(sv, where, changes, table, exp_for_level, level_for_exp, calc_stats, move_pp):
    pk, stats = _parts(sv, where)
    if not A.checksum_ok(pk) or not struct.unpack_from("<H", pk, 8)[0]:
        raise ValueError("place vide ou Pokémon abîmé")
    nat0 = struct.unpack_from("<H", pk, 8)[0]
    if "species" in changes:
        struct.pack_into("<H", pk, 8, int(changes["species"]))
    nat = struct.unpack_from("<H", pk, 8)[0]
    if nat != nat0 and nat in table:
        ab = table[nat][9:12]
        slot = {1: 0, 2: 1, 4: 2}.get(pk[0x15], 0)
        pk[0x14] = ab[slot] or ab[0]
    if "item" in changes:
        struct.pack_into("<H", pk, 0x0A, int(changes["item"]))
    if "friendship" in changes:
        pk[0xA2 if pk[0x93] else 0xCA] = max(0, min(255, int(changes["friendship"])))
    if "evs" in changes:
        pk[0x1E:0x24] = bytes(max(0, min(252, int(v))) for v in changes["evs"])
    if "moves" in changes:
        old = struct.unpack_from("<4H", pk, 0x5A)
        new = [int(m) for m in changes["moves"]]
        struct.pack_into("<4H", pk, 0x5A, *new)
        for k, mv in enumerate(new):
            if mv != old[k]:
                pk[0x62 + k] = move_pp(6, mv) if mv else 0
                pk[0x66 + k] = 0
    if "ivs" in changes:
        w = struct.unpack_from("<I", pk, 0x74)[0] & 0xC0000000
        for k, v in enumerate(changes["ivs"]):
            w |= (int(v) & 31) << (5 * k)
        struct.pack_into("<I", pk, 0x74, w)
    if "nature" in changes:
        pk[0x1C] = int(changes["nature"]) % 25
    exp = struct.unpack_from("<I", pk, 0x10)[0]
    if nat0 in table and nat in table:
        level = stats[4] if stats and stats[4] else level_for_exp(table[nat0][6], exp)
        if "level" in changes:
            level = max(1, min(100, int(changes["level"])))
        if "level" in changes or nat != nat0:
            struct.pack_into("<I", pk, 0x10, exp_for_level(table[nat][6], level))
        if stats is not None and {"species", "ivs", "evs", "level", "nature", "recalc"} & set(changes):
            iv = struct.unpack_from("<I", pk, 0x74)[0]
            st = calc_stats(nat, table[nat][:6], [(iv >> (5 * k)) & 31 for k in range(6)], list(pk[0x1E:0x24]), level,
                            pk[0x1C])
            hp, hp_max = struct.unpack_from("<HH", stats, 8)
            hp = st[0] if changes.get("recalc") else (0 if hp == 0 else max(1, min(st[0], hp + st[0] - hp_max)))
            stats[4] = level
            struct.pack_into("<HH5H", stats, 8, hp, *st)
    elif "level" in changes:
        raise ValueError(f"données de l'espèce {nat} absentes : niveau non modifiable")
    _store(sv, where, pk, stats)


def export_mon(sv, where):
    m = decode(sv.read(where))
    if not m or m.get("bad"):
        return None
    return decrypt(sv.read(where))


def from_file(data):
    if len(data) not in (SIZE, PARTY_SIZE):
        raise ValueError(f"fichier de {len(data)} octets : pas un Pokémon 6G (.pk6)")
    data = bytes(data[:SIZE])
    plain = struct.unpack_from("<H", data, 6)[0] == sum(struct.unpack_from("<112H", data, 8)) & 0xFFFF
    pk = data if plain and struct.unpack_from("<H", data, 8)[0] else decrypt(data)
    if not A.checksum_ok(pk):
        raise ValueError("fichier illisible (somme de contrôle fausse ou mauvaise génération)")
    nat = struct.unpack_from("<H", pk, 8)[0]
    if not 1 <= nat <= DEX_MAX:
        raise ValueError(f"espèce {nat} inconnue en 6G")
    return bytes(pk)


def place_mon(sv, where, pk, recalc):
    if where[0] != "party":
        sv.write(where, encrypt(pk))
        return
    n = sv.party_count()
    i = where[1]
    if i > n or i >= 6:
        raise ValueError("équipe : choisis un Pokémon à remplacer ou la première place libre")
    if i == n:
        sv.set_party_count(n + 1)
    sv.write(where, encrypt(pk) + crypt_party(struct.unpack_from("<I", pk)[0], bytes(PARTY_SIZE - SIZE)))
    recalc()


def _empty(sv):
    seen = {}
    for b in range(BOXES):
        for i in range(30):
            r = sv.read(("box", b, i))
            if decode(r) is None:
                seen[r] = seen.get(r, 0) + 1
    return max(seen, key=seen.get) if seen else EMPTY


def remove_mon(sv, where):
    if where[0] != "party":
        sv.write(where, _empty(sv))
        return
    n = sv.party_count()
    if n <= 1:
        raise ValueError("impossible de retirer le dernier Pokémon de l'équipe")
    if where[1] >= n:
        raise ValueError("place déjà vide")
    mons = [sv.read(("party", k)) for k in range(n)]
    del mons[where[1]]
    sv.set_party_count(n - 1)
    for k in range(6):
        sv.write(("party", k), mons[k] if k < len(mons) else EMPTY + bytes(PARTY_SIZE - SIZE))


def check_mon(m, table, pockets, exp_for_level, level_for_exp):
    if not m:
        return []
    if m.get("bad"):
        return ["données abîmées (somme de contrôle fausse)"]
    out = []
    if not 1 <= m["species"] <= DEX_MAX:
        out.append(f"espèce {m['species']} inconnue en 6G")
    if sum(m["evs"]) > 510:
        out.append(f"EV : {sum(m['evs'])} au total (510 maximum)")
    mv = [x for x in m["moves"] if x]
    if not mv:
        out.append("aucune attaque")
    if len(set(mv)) != len(mv):
        out.append("la même attaque deux fois")
    if any(x > MOVE_MAX for x in mv):
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


def _template(sv):
    t = sv.trainer()
    good = []
    for i in range(sv.party_count()):
        pk = decrypt(sv.read(("party", i)))
        if A.checksum_ok(pk) and struct.unpack_from("<H", pk, 8)[0]:
            good.append(pk)
    if not good:
        raise ValueError("aucun Pokémon lisible dans l'équipe pour servir de modèle")
    own = [p for p in good if struct.unpack_from("<HH", p, 0x0C) == (t["tid"], t["sid"])]
    return bytearray((own or good)[0])


def create_mon(sv, species, level, nature, shiny, moves, table, ivs, name, exp_for_level, move_pp):
    rng = random.SystemRandom()
    species, level, nature = int(species), max(1, min(100, int(level))), int(nature) % 25
    if species not in table or not 1 <= species <= DEX_MAX:
        raise ValueError(f"espèce {species} inconnue en 6G")
    info = table[species]
    growth, ratio, friend, abil = info[6], info[7], info[8], info[9:12]
    t = sv.trainer()
    tid, sid = t["tid"], t["sid"]
    moves = [int(m) for m in (moves or []) if int(m)][:4] or [33]
    moves += [0] * (4 - len(moves))
    ivs = [int(v) & 31 for v in ivs] if ivs else [rng.randrange(32) for _ in range(6)]
    while True:
        lo = rng.randrange(0x10000)
        hi = (tid ^ sid ^ lo ^ rng.randrange(16)) if shiny else rng.randrange(0x10000)
        if is_shiny(tid, sid, hi << 16 | lo) == bool(shiny):
            break
    pid = hi << 16 | lo
    female = ratio == 254 or (ratio not in (0, 255) and (pid & 0xFF) < ratio)
    tmpl = _template(sv)
    pk = bytearray(SIZE)
    struct.pack_into("<I", pk, 0, rng.randrange(1, 1 << 32))
    struct.pack_into("<HHHHI", pk, 8, species, 0, tid, sid, exp_for_level(growth, level))
    slot = rng.randrange(2) if abil[1] and abil[1] != abil[0] else 0
    pk[0x14], pk[0x15] = abil[slot] or abil[0], 1 << slot
    struct.pack_into("<I", pk, 0x18, pid)
    pk[0x1C] = nature
    pk[0x1D] = 4 if ratio == 255 else 2 if female else 0
    pk[0x40:0x5A] = encode(name)
    struct.pack_into("<4H", pk, 0x5A, *moves)
    pk[0x62:0x66] = bytes(move_pp(6, m) if m else 0 for m in moves)
    struct.pack_into("<4H", pk, 0x6A, *moves)
    struct.pack_into("<I", pk, 0x74, sum(v << (5 * k) for k, v in enumerate(ivs)))
    pk[0x93] = 0
    pk[0x94:0xA2] = tmpl[0x94:0xA2]
    pk[0xB0:0xCA] = tmpl[0xB0:0xCA]
    pk[0xCA] = friend
    today = datetime.date.today()
    pk[0xD4:0xD7] = bytes([today.year % 100, today.month, today.day])
    struct.pack_into("<H", pk, 0xDA, struct.unpack_from("<H", tmpl, 0xDA)[0])
    pk[0xDC] = BALL_POKE
    pk[0xDD] = (tmpl[0xDD] & 0x80) | level
    pk[0xDF] = tmpl[0xDF] or VERSION[sv.family]
    pk[0xE0:0xE4] = tmpl[0xE0:0xE4]
    return bytes(pk)
