import os
import re
import struct


def side_path(stem):
    new, old = stem + ".pklab.json", stem + ".pwh.json"
    if not os.path.isfile(new) and os.path.isfile(old):
        try:
            os.replace(old, new)
        except OSError:
            return old
    return new

MIN_N, MAX_N = 2, 65536
LOOP_MAX_T = 32768
THUMB_NOP = bytes.fromhex("c046")


def _km(t, mmax):
    def r(x): return int(x + 0.5)
    k = 0
    while r(t / (1 << k)) > mmax:
        k += 1
    return k, max(1, min(mmax, r(t / (1 << k))))


def _label(t):
    if t >= 0x10000:
        return "100 %"
    real = 65536 / t
    return "1 / " + (f"{real:.0f}" if abs(real - round(real)) < 0.05 else f"{real:.1f}".replace(".", ","))


def resolve(value, ds=False):
    value = str(value or "").strip()
    if value == "always":
        return {"always": True, "t": 0x10000, "label": "100 %"}
    try:
        n = float(value.replace(",", "."))
    except ValueError:
        raise ValueError("Chance invalide : tape un nombre (1 sur N)")
    if not MIN_N <= n <= MAX_N:
        raise ValueError(f"Chance hors limites : 1 sur {MIN_N} à 1 sur {MAX_N} (ou « Tous shiny »)")
    want = 65536 / n
    mmax = 255 if ds else 256
    k, m = _km(want, mmax)
    t = m << k
    lk, lm = _km(min(t, LOOP_MAX_T), mmax)
    return {"always": False, "t": t, "k": k, "m": m, "loop": (lk, lm), "label": _label(t)}


def _sites(code, imm, end=None):
    out = []
    end = len(code) - 4 if end is None else min(end, len(code) - 4)
    for a in range(24, end, 2):
        h = code[a] | code[a + 1] << 8
        if h >> 11 != 5 or h & 0xFF != imm:
            continue
        b = code[a + 2] | code[a + 3] << 8
        cond = b >> 8 & 0xF
        if b >> 12 != 0xD or cond not in (2, 3, 8, 9):
            continue
        eors = sum(1 for k in range(a - 24, a, 2) if (code[k] | code[k + 1] << 8) >> 6 == 0x101)
        if eors < 2:
            continue
        out.append((a, cond, (b & 0xFF) >= 0x80))
    return out


def _new_branch(code, a, cond):
    b = code[a + 2] | code[a + 3] << 8
    if cond in (3, 9):
        off = b & 0xFF
        off = off - 0x100 if off >= 0x80 else off
        return struct.pack("<H", 0xE000 | (off & 0x7FF))
    return THUMB_NOP


def _lsl(d, s, n): return 0x0000 | n << 6 | s << 3 | d
def _lsr(d, s, n): return 0x0800 | n << 6 | s << 3 | d
def _eor(d, s): return 0x4040 | s << 3 | d
def _and(d, s): return 0x4000 | s << 3 | d
def _h(code, a): return code[a] | code[a + 1] << 8
def _pack(hs): return b"".join(struct.pack("<H", h) for h in hs)


NOP = 0x46C0
LOOP3 = [0x1C21, 0x4643, 0x4019, 0x0C09, 0x4034, 0x4061, 0x9A05, 0x1C10, 0x4018, 0x0C00, 0x4041, 0x4032, 0x4051]


def _gba_block(rom, a, loop, k):
    if loop:
        start = a - 2 * len(LOOP3)
        if [_h(rom, start + 2 * i) for i in range(len(LOOP3))] != LOOP3:
            return None
        new = [0x9A05, _eor(2, 4), _lsr(1, 2, 16 + k), _lsl(2, 2, 16), _lsr(2, 2, 16 + k), _eor(1, 2),
               0x4643, _lsl(4, 4, 16), _lsr(4, 4, 16)]
        return start, _pack(new + [NOP] * (len(LOOP3) - len(new)))
    start = a - 16
    h = [_h(rom, start + 2 * i) for i in range(8)]
    if h[0] >> 6 != 0x0800 >> 6 | 16 or h[1] >> 11 != 9 or h[4] >> 6 != 0x0800 >> 6 | 16:
        return None
    A, X = h[0] & 7, h[0] >> 3 & 7
    M = h[1] >> 8 & 7
    B, Y = h[4] & 7, h[4] >> 3 & 7
    if (h[2], h[3], h[5], h[6], h[7]) != (_and(X, M), _eor(A, X), _eor(A, B), _and(Y, M), _eor(A, Y)):
        return None
    if len({A, X, Y, M}) != 4 or _h(rom, a) & 7 << 8 != A << 8:
        return None
    new = [_eor(X, Y), h[1], _lsr(A, X, 16 + k), _lsl(X, X, 16), _lsr(X, X, 16 + k), _eor(A, X), NOP, NOP]
    return start, _pack(new)


def patch_gba(rom, value, log):
    p = resolve(value)
    sites = _sites(rom, 7, end=0x400000)
    if len(sites) != 5 or sum(1 for s in sites if s[2]) != 1:
        log.append(f"Chance de shiny : NON changée (tests introuvables : {len(sites)} au lieu de 5)")
        return False
    edits = []
    for a, cond, loop in sites:
        if p["always"]:
            if not loop:
                edits.append((a + 2, _new_branch(rom, a, cond)))
            continue
        k, m = p["loop"] if loop else (p["k"], p["m"])
        if k:
            blk = _gba_block(rom, a, loop, k)
            if blk is None:
                log.append("Chance de shiny : NON changée (code d'un test inattendu)")
                return False
            edits.append(blk)
        edits.append((a, bytes([m - 1])))
    for off, data in edits:
        rom[off:off + len(data)] = data
    log.append(f"Chance de shiny : {p['label']} (au lieu de 1 / 8192 ; non testé en jeu)")
    return True


GBC_DV_SITE = re.compile(rb"\xcd(..)\x47\xcd\1\x4f\x21(?:\x0c\xd2|\xf5\xd0)\x78\x22\x71", re.S)


def _gbc_free(rom, bank, need):
    start, end = bank * 0x4000, bank * 0x4000 + 0x4000
    i = end
    while i > start and rom[i - 1] == 0:
        i -= 1
    a = i + 16
    return a if a + need <= end else None


def gbc_checksum(rom):
    struct.pack_into(">H", rom, 0x14E, (sum(rom) - rom[0x14E] - rom[0x14F]) & 0xFFFF)


def patch_gbc(rom, value, log):
    p = resolve(value)
    sites = list(GBC_DV_SITE.finditer(bytes(rom)))
    if len(sites) != 1:
        log.append(f"Chance de shiny : NON changée (code des DV introuvable : {len(sites)} au lieu de 1)")
        return False
    site = sites[0].start()
    rnd = sites[0].group(1)
    call = b"\xcd" + rnd
    code = bytearray(call + b"\x47" + call + b"\x4f\xc5")
    if not p["always"]:
        t = min(p["t"], 0xFFFF)
        hi, lo = t >> 8, t & 0xFF
        code += call + bytes([0xFE, hi, 0x38, 0, 0x20, 0]) + call + bytes([0xFE, lo, 0x38, 0])
        no = len(code)
        code += b"\xc1\xc9"
        yes = len(code)
        j1, j2, j3 = no - 11, no - 9, no - 2
        code[j1 + 1] = yes - (j1 + 2)
        code[j2 + 1] = no - (j2 + 2)
        code[j3 + 1] = yes - (j3 + 2)
    code += b"\xc1\x78\xe6\xf0\xf6\x2a\x47\x0e\xaa\xc9"
    bank = site // 0x4000
    at = _gbc_free(rom, bank, len(code))
    if at is None:
        log.append("Chance de shiny : NON changée (pas de place libre dans la ROM)")
        return False
    rom[at:at + len(code)] = code
    gb = 0x4000 + at % 0x4000 if bank else at
    rom[site:site + 8] = bytes([0xCD, gb & 0xFF, gb >> 8, 0, 0, 0, 0, 0])
    gbc_checksum(rom)
    log.append(f"Chance de shiny : {p['label']} pour les Pokémon sauvages (au lieu de 1 / 8192)")
    return True


def _ds_shifts(a9, a):
    return [o for o in range(a - 0x24, a, 2) if _h(a9, o) >> 6 == (0x0800 >> 6 | 16)]


def patch_nds(rom, value, log):
    p = resolve(value, ds=True)
    import nds_rebuild
    a9, _ = nds_rebuild.arm9_read(rom)
    sites = _sites(a9, 8)
    tests = [s for s in sites if not s[2]]
    if len(tests) != 1 or len(sites) > 2:
        log.append(f"Chance de shiny : NON changée (test introuvable : {len(tests)} trouvés)")
        return False
    new = bytearray(a9)
    for a, cond, loop in sites:
        if p["always"]:
            if not loop:
                new[a + 2:a + 4] = _new_branch(a9, a, cond)
            continue
        k, m = p["loop"] if loop else (p["k"], p["m"])
        if k:
            sh = _ds_shifts(a9, a)
            if len(sh) != 4:
                log.append(f"Chance de shiny : NON changée (code d'un test inattendu : {len(sh)} décalages)")
                return False
            for o in sh:
                struct.pack_into("<H", new, o, _h(a9, o) & ~(31 << 6) | (16 + k) << 6)
        new[a] = m
    diff = [i for i in range(len(a9)) if a9[i] != new[i]]
    if diff:
        nds_rebuild.code_set_bytes(rom, None, diff[0], bytes(new[diff[0]:diff[-1] + 1]))
    log.append(f"Chance de shiny : {p['label']} (au lieu de 1 / 8192 ; non testé en jeu)")
    return True


def side_threshold(rom_path):
    import json
    import os
    stem = os.path.splitext(rom_path)[0]
    for side in (stem + ".shiny.json", side_path(stem)):
        try:
            with open(side, encoding="utf-8") as f:
                t = json.load(f).get("shinyThreshold")
            if t:
                return int(t)
        except Exception:
            pass
    return 8


def threshold(value, ds=False):
    try:
        return resolve(value, ds=ds)["t"]
    except ValueError:
        return 8


def make_shiny_rom(src, out, value):
    import json
    import os
    ds = src.lower().endswith(".nds")
    resolve(value, ds=ds)
    if side_threshold(src) != 8:
        raise ValueError("Cette ROM a déjà une chance de shiny modifiée : pars de la ROM d'avant")
    with open(src, "rb") as f:
        rom = bytearray(f.read())
    log = []
    if src.lower().endswith((".gbc", ".gb")):
        ok = patch_gbc(rom, value, log)
    else:
        ok = patch_nds(rom, value, log) if ds else patch_gba(rom, value, log)
    if not ok:
        raise ValueError(log[-1] if log else "ROM non prise en charge")
    with open(out, "wb") as f:
        f.write(rom)
    t = threshold(value, ds=ds)
    src_side = side_path(os.path.splitext(src)[0])
    if os.path.isfile(src_side):
        with open(src_side, encoding="utf-8") as f:
            data = json.load(f)
        data["shinyThreshold"] = t
        with open(os.path.splitext(out)[0] + ".pklab.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    else:
        with open(os.path.splitext(out)[0] + ".shiny.json", "w", encoding="utf-8") as f:
            json.dump({"shinyThreshold": t, "source": os.path.basename(src), "choice": value}, f)
    return log[-1]
