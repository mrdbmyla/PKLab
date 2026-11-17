import struct

MEDIA = 0x200


class RomFS:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        head = self._read(0, 0x200)
        if head[0x100:0x104] == b"NCSD":
            part = struct.unpack_from("<I", head, 0x120)[0] * MEDIA
        elif head[0x100:0x104] == b"NCCH":
            part = 0
        else:
            raise ValueError("ROM 3DS non reconnue")
        ncch = self._read(part, 0x200)
        if ncch[0x100:0x104] != b"NCCH":
            raise ValueError("partition NCCH absente")
        if not ncch[0x18F] & 4:
            raise ValueError("ROM chiffrée (non prise en charge)")
        romfs = part + struct.unpack_from("<I", ncch, 0x1B0)[0] * MEDIA
        ivfc = self._read(romfs, 0x60)
        if ivfc[:4] != b"IVFC":
            raise ValueError("RomFS invalide")
        master = struct.unpack_from("<I", ivfc, 0x08)[0]
        block = 1 << struct.unpack_from("<I", ivfc, 0x4C)[0]
        self.lv3 = romfs + ((0x60 + master + block - 1) // block) * block
        h = self._read(self.lv3, 0x28)
        (_, self.dh_off, _, self.dm_off, self.dm_size, _, _, self.fm_off, self.fm_size,
         self.data_off) = struct.unpack("<IIIIIIIIII", h)
        self.dm = self._read(self.lv3 + self.dm_off, self.dm_size)
        self.fm = self._read(self.lv3 + self.fm_off, self.fm_size)
        self.files = {}
        self._walk(0, "")

    def close(self):
        self.f.close()

    def _read(self, off, size):
        self.f.seek(off)
        return self.f.read(size)

    def _walk(self, d, prefix):
        _, _, child, first_file, _, nlen = struct.unpack_from("<IIIIII", self.dm, d)
        name = self.dm[d + 0x18:d + 0x18 + nlen].decode("utf-16-le")
        path = prefix + name + "/" if d else ""
        f = first_file
        while f != 0xFFFFFFFF:
            _, sib, off, size, _, fl = struct.unpack_from("<IIQQII", self.fm, f)
            fname = self.fm[f + 0x20:f + 0x20 + fl].decode("utf-16-le")
            self.files[path + fname] = (self.lv3 + self.data_off + off, size)
            f = sib
        c = child
        while c != 0xFFFFFFFF:
            self._walk(c, path)
            c = struct.unpack_from("<I", self.dm, c + 4)[0]

    def read(self, name):
        off, size = self.files[name]
        return self._read(off, size)


def garc(data):
    if data[:4] != b"CRAG":
        raise ValueError("GARC invalide")
    hsize = struct.unpack_from("<I", data, 4)[0]
    data_off = struct.unpack_from("<I", data, 0x10)[0]
    o = hsize
    if data[o:o + 4] != b"OTAF":
        raise ValueError("FATO absent")
    fato_size, count = struct.unpack_from("<IH", data, o + 4)
    offs = struct.unpack_from(f"<{count}I", data, o + 0xC)
    fatb = o + fato_size
    out = []
    for i in range(count):
        e = fatb + 0xC + offs[i]
        bits = struct.unpack_from("<I", data, e)[0]
        e += 4
        subs = []
        for b in range(32):
            if bits >> b & 1:
                start, end, _ = struct.unpack_from("<III", data, e)
                subs.append(data[data_off + start:data_off + end])
                e += 12
        out.append(subs[0] if len(subs) == 1 else subs)
    return out


def text(data):
    sections, lines = struct.unpack_from("<HH", data, 0)
    sec = struct.unpack_from("<I", data, 0x0C)[0]
    key = 0x7C89
    out = []
    for i in range(lines):
        off, ln = struct.unpack_from("<IH", data, sec + 4 + 8 * i)
        raw = data[sec + off:sec + off + 2 * ln]
        k = key
        chars = []
        for j in range(ln):
            c = struct.unpack_from("<H", raw, 2 * j)[0] ^ k
            k = ((k << 3) | (k >> 13)) & 0xFFFF
            chars.append(c)
        key = (key + 0x2983) & 0xFFFF
        s = []
        j = 0
        while j < len(chars):
            c = chars[j]
            if c == 0:
                break
            if c == 0x10:
                n = chars[j + 1]
                j += 2 + n
                continue
            if c == 0xE07F:
                s.append(" ")
            elif c in (0xE08D, 0xE08E):
                s.append(" ")
            else:
                s.append(chr(c) if c < 0xE000 else "")
            j += 1
        out.append("".join(s))
    return out


def lz11(data):
    if not data or data[0] != 0x11:
        return data
    size = data[1] | data[2] << 8 | data[3] << 16
    pos = 4
    if size == 0:
        size = struct.unpack_from("<I", data, 4)[0]
        pos = 8
    out = bytearray()
    while len(out) < size and pos < len(data):
        flags = data[pos]
        pos += 1
        for bit in range(8):
            if len(out) >= size or pos >= len(data):
                break
            if not flags & (0x80 >> bit):
                out.append(data[pos])
                pos += 1
                continue
            b0 = data[pos]
            ind = b0 >> 4
            if ind == 0:
                length = (((b0 & 0xF) << 4) | (data[pos + 1] >> 4)) + 0x11
                disp = ((data[pos + 1] & 0xF) << 8 | data[pos + 2]) + 1
                pos += 3
            elif ind == 1:
                length = (((b0 & 0xF) << 12) | (data[pos + 1] << 4) | (data[pos + 2] >> 4)) + 0x111
                disp = ((data[pos + 2] & 0xF) << 8 | data[pos + 3]) + 1
                pos += 4
            else:
                length = ind + 1
                disp = ((b0 & 0xF) << 8 | data[pos + 1]) + 1
                pos += 2
            for _ in range(length):
                out.append(out[-disp])
    return bytes(out[:size])


def darc(data):
    data = data[data.find(b"darc"):]
    toff = struct.unpack_from("<I", data, 0x10)[0]
    count = struct.unpack_from("<I", data, toff + 8)[0]
    names_base = toff + count * 12
    out = {}
    ends = []
    path = []
    for i in range(count):
        nraw, off, size = struct.unpack_from("<III", data, toff + i * 12)
        e = names_base + (nraw & 0xFFFFFF)
        k = e
        while data[k:k + 2] != b"\0\0":
            k += 2
        name = data[e:k].decode("utf-16-le")
        while ends and i >= ends[-1]:
            ends.pop()
            path.pop()
        if nraw >> 24:
            if i:
                ends.append(size)
                path.append(name)
        else:
            full = "/".join(p for p in path + [name] if p not in ("", "."))
            out[full] = data[off:off + size]
    return out


_ETC_MOD = ((2, 8, -2, -8), (5, 17, -5, -17), (9, 29, -9, -29), (13, 42, -13, -42),
            (18, 60, -18, -60), (24, 80, -24, -80), (33, 106, -33, -106), (47, 183, -47, -183))


def _etc1(v):
    if (v >> 33) & 1:
        r, g, b = (v >> 59) & 31, (v >> 51) & 31, (v >> 43) & 31
        d = [((v >> s) & 7) - (8 if (v >> s) & 4 else 0) for s in (56, 48, 40)]
        c1 = tuple((x << 3) | (x >> 2) for x in (r, g, b))
        c2 = tuple((((x + dx) & 31) << 3) | (((x + dx) & 31) >> 2) for x, dx in zip((r, g, b), d))
    else:
        c1 = tuple(((v >> s) & 15) * 17 for s in (60, 52, 44))
        c2 = tuple(((v >> s) & 15) * 17 for s in (56, 48, 40))
    flip = (v >> 32) & 1
    t1, t2 = _ETC_MOD[(v >> 37) & 7], _ETC_MOD[(v >> 34) & 7]
    px = [None] * 16
    for x in range(4):
        for y in range(4):
            i = x * 4 + y
            idx = ((v >> (i + 16)) & 1) * 2 + ((v >> i) & 1)
            second = y >= 2 if flip else x >= 2
            base, t = (c2, t2) if second else (c1, t1)
            m = t[idx]
            px[y * 4 + x] = tuple(min(255, max(0, c + m)) for c in base)
    return px


def _morton(i):
    return ((i & 1) | ((i >> 1) & 2) | ((i >> 2) & 4), ((i >> 1) & 1) | ((i >> 2) & 2) | ((i >> 3) & 4))


def bclim(data):
    j = data.rfind(b"CLIM")
    imag = data.find(b"imag", j)
    w, h, fmt = struct.unpack_from("<HHI", data, imag + 8)
    return _texture(data[:j], w, h, fmt)


def bflim(data):
    j = data.rfind(b"FLIM")
    imag = data.find(b"imag", j)
    w, h, _, fmt, swizzle = struct.unpack_from("<HHHBB", data, imag + 8)
    if swizzle != 8:
        return _texture(data[:j], w, h, fmt)
    tw, th, rows = _texture(data[:j], h, w, fmt)
    stride = tw * 4 + 1
    out = bytearray()
    for y in range(w):
        out.append(0)
        for x in range(h):
            o = x * stride + 1 + y * 4
            out += rows[o:o + 4]
    return h, w, bytes(out)


def _texture(raw, w, h, fmt):
    pw = ph = 8
    while pw < w:
        pw *= 2
    while ph < h:
        ph *= 2
    rgba = bytearray(pw * ph * 4)
    pos = 0
    if fmt in (10, 11):
        for ty in range(0, ph, 8):
            for tx in range(0, pw, 8):
                for blk in range(4):
                    bx, by = tx + (blk & 1) * 4, ty + (blk >> 1) * 4
                    alpha = None
                    if fmt == 11:
                        alpha = struct.unpack_from("<Q", raw, pos)[0]
                        pos += 8
                    px = _etc1(struct.unpack_from("<Q", raw, pos)[0])
                    pos += 8
                    for y in range(4):
                        for x in range(4):
                            a = 255 if alpha is None else ((alpha >> ((x * 4 + y) * 4)) & 15) * 17
                            o = ((by + y) * pw + bx + x) * 4
                            rgba[o:o + 4] = bytes(px[y * 4 + x]) + bytes((a,))
    else:
        bpp = {0: 1, 1: 1, 2: 1, 3: 2, 5: 2, 6: 3, 7: 2, 8: 2, 9: 4}[fmt]
        for ty in range(0, ph, 8):
            for tx in range(0, pw, 8):
                for i in range(64):
                    x, y = _morton(i)
                    c = raw[pos:pos + bpp]
                    pos += bpp
                    if fmt == 9:
                        p = (c[3], c[2], c[1], c[0])
                    elif fmt == 6:
                        p = (c[2], c[1], c[0], 255)
                    elif fmt in (5, 7, 8):
                        v = c[0] | c[1] << 8
                        if fmt == 5:
                            p = ((v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31, 255)
                        elif fmt == 7:
                            p = ((v >> 11) * 255 // 31, ((v >> 6) & 31) * 255 // 31, ((v >> 1) & 31) * 255 // 31, 255 * (v & 1))
                        else:
                            p = ((v >> 12) * 17, ((v >> 8) & 15) * 17, ((v >> 4) & 15) * 17, (v & 15) * 17)
                    elif fmt == 3:
                        p = (c[1], c[1], c[1], c[0])
                    elif fmt == 2:
                        p = ((c[0] >> 4) * 17,) * 3 + ((c[0] & 15) * 17,)
                    elif fmt == 1:
                        p = (255, 255, 255, c[0])
                    else:
                        p = (c[0], c[0], c[0], 255)
                    o = ((ty + y) * pw + tx + x) * 4
                    rgba[o:o + 4] = bytes(p)
    rows = b"".join(b"\0" + bytes(rgba[r * pw * 4:(r * pw + w) * 4]) for r in range(h))
    return w, h, rows


def png(w, h, rows):
    import zlib

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def sarc(data):
    data = data[data.find(b"SARC"):]
    hlen = struct.unpack_from("<H", data, 4)[0]
    doff = struct.unpack_from("<I", data, 0xC)[0]
    shl, count = struct.unpack_from("<HH", data, hlen + 4)
    q = hlen + shl + count * 16
    nbase = q + struct.unpack_from("<H", data, q + 4)[0]
    out = {}
    for i in range(count):
        _, attr, s, e = struct.unpack_from("<IIII", data, hlen + shl + i * 16)
        if attr & 0x01000000:
            o = nbase + (attr & 0xFFFF) * 4
            out[data[o:data.index(b"\0", o)].decode("utf-8", "replace")] = data[doff + s:doff + e]
    return out


def layout_panes(data):
    hlen = struct.unpack_from("<H", data, 6)[0]
    n = struct.unpack_from("<I", data, 0x10)[0]
    pos = hlen
    out = {}
    stack = []
    last = None
    for _ in range(n):
        if pos + 8 > len(data):
            break
        magic = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        if magic == b"pas1":
            stack.append(last)
        elif magic == b"pae1":
            if stack:
                stack.pop()
        elif magic in (b"pan1", b"pic1", b"txt1", b"wnd1", b"bnd1", b"prt1"):
            name = data[pos + 0xC:pos + 0x1C].split(b"\0")[0].decode("latin1")
            tx, ty = struct.unpack_from("<ff", data, pos + 0x24)
            w, h = struct.unpack_from("<ff", data, pos + 0x44)
            parent = out.get(stack[-1]) if stack and stack[-1] else None
            ax, ay = (parent[0] + tx, parent[1] + ty) if parent else (tx, ty)
            out[name] = (ax, ay, w, h)
            last = name
        pos += size
    return out


def garc_file(rom, name, index):
    base, size = rom.files[name]
    head = rom._read(base, 0x1C)
    if head[:4] != b"CRAG":
        raise ValueError("GARC invalide")
    hsize = struct.unpack_from("<I", head, 4)[0]
    data_off = struct.unpack_from("<I", head, 0x10)[0]
    fato = rom._read(base + hsize, 0xC)
    fato_size, count = struct.unpack_from("<IH", fato, 4)
    if not 0 <= index < count:
        return None
    off = struct.unpack_from("<I", rom._read(base + hsize + 0xC + 4 * index, 4))[0]
    e = base + hsize + fato_size + 0xC + off
    bits = struct.unpack_from("<I", rom._read(e, 4))[0]
    if not bits:
        return None
    start, end, _ = struct.unpack_from("<III", rom._read(e + 4, 12))
    return rom._read(base + data_off + start, end - start)


def _lz11_match(data, pos, heads, n):
    best_len, best_disp = 0, 0
    if pos + 3 > n:
        return 0, 0
    cands = heads.get(data[pos:pos + 3])
    if not cands:
        return 0, 0
    limit = min(0x10110, n - pos)
    for c in reversed(cands):
        d = pos - c
        if d > 0x1000:
            break
        ln = 3
        while ln < limit and data[c + ln] == data[pos + ln]:
            ln += 1
        if ln > best_len:
            best_len, best_disp = ln, d
            if ln == limit:
                break
    return best_len, best_disp


def lz11_pack(data):
    data = bytes(data)
    n = len(data)
    out = bytearray(b"\x11" + n.to_bytes(3, "little") if n < 0x1000000 else b"\x11\x00\x00\x00" + n.to_bytes(4, "little"))
    heads = {}
    added = 0

    def index_to(limit):
        nonlocal added
        while added < min(limit, n - 2):
            lst = heads.setdefault(data[added:added + 3], [])
            lst.append(added)
            if lst[0] < added - 0x1000:
                k = 0
                while lst[k] < added - 0x1000:
                    k += 1
                del lst[:k]
            added += 1

    pos = 0
    while pos < n:
        flag_at = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if pos >= n:
                break
            index_to(pos)
            ln, disp = _lz11_match(data, pos, heads, n)
            if ln >= 3:
                index_to(pos + 1)
                ln2, _ = _lz11_match(data, pos + 1, heads, n)
                if ln2 > ln + 1:
                    ln = 0
            if ln >= 3:
                flags |= 0x80 >> bit
                d = disp - 1
                if ln <= 0x10:
                    out += bytes(((ln - 1) << 4 | d >> 8, d & 0xFF))
                elif ln <= 0x110:
                    v = ln - 0x11
                    out += bytes((v >> 4, (v & 0xF) << 4 | d >> 8, d & 0xFF))
                else:
                    v = ln - 0x111
                    out += bytes((0x10 | v >> 12, (v >> 4) & 0xFF, (v & 0xF) << 4 | d >> 8, d & 0xFF))
                pos += ln
            else:
                out.append(data[pos])
                pos += 1
        out[flag_at] = flags
    while len(out) % 4:
        out.append(0)
    return bytes(out)


def garc_build(original, files):
    if original[:4] != b"CRAG":
        raise ValueError("GARC invalide")
    hsize, _, version = struct.unpack_from("<IHH", original, 4)
    if version != 0x0400:
        raise ValueError("version de GARC non prise en charge")
    data_off = struct.unpack_from("<I", original, 0x10)[0]
    fato_size, count = struct.unpack_from("<IH", original, hsize + 4)
    if count != len(files):
        raise ValueError("nombre de fichiers différent")
    offs = struct.unpack_from(f"<{count}I", original, hsize + 0xC)
    fatb = hsize + fato_size
    head = bytearray(original[:data_off])
    body = bytearray()
    largest = 0
    for i, blob in enumerate(files):
        e = fatb + 0xC + offs[i]
        if struct.unpack_from("<I", original, e)[0] != 1:
            raise ValueError("GARC à sous-fichiers multiples non pris en charge")
        o_start, o_end, o_len = struct.unpack_from("<III", original, e + 4)
        size = o_len if bytes(blob) == original[data_off + o_start:data_off + o_end] else len(blob)
        start = len(body)
        body += blob[:size]
        while len(body) % 4:
            body.append(0xFF)
        struct.pack_into("<III", head, e + 4, start, len(body), size)
        largest = max(largest, size)
    fimb = fatb + struct.unpack_from("<I", original, fatb + 4)[0]
    struct.pack_into("<I", head, fimb + 8, len(body))
    struct.pack_into("<I", head, 0x14, data_off + len(body))
    struct.pack_into("<I", head, 0x18, largest)
    return bytes(head + body)


def blz(data):
    data = bytearray(data)
    info, extra = struct.unpack_from("<II", data, len(data) - 8)
    top = info & 0xFFFFFF
    bottom = info >> 24
    out = data + bytearray(extra)
    src = len(data) - bottom
    dst = len(out)
    end = len(data) - top
    while src > end:
        src -= 1
        flags = out[src]
        for _ in range(8):
            if src <= end:
                break
            if flags & 0x80:
                src -= 2
                v = out[src] | out[src + 1] << 8
                disp = (v & 0xFFF) + 3
                for _ in range((v >> 12) + 3):
                    dst -= 1
                    out[dst] = out[dst + disp]
            else:
                src -= 1
                dst -= 1
                out[dst] = out[src]
            flags = (flags << 1) & 0xFF
    return bytes(out)


def exefs_code(path):
    with open(path, "rb") as f:
        h = f.read(0x200)
        part = struct.unpack_from("<I", h, 0x120)[0] * MEDIA if h[0x100:0x104] == b"NCSD" else 0
        f.seek(part)
        n = f.read(0x200)
        ex = f.read(0x400)
        if n[0x100:0x104] != b"NCCH" or not n[0x18F] & 4:
            raise ValueError("ROM 3DS non prise en charge (chiffrée ?)")
        exefs = part + struct.unpack_from("<I", n, 0x1A0)[0] * MEDIA
        f.seek(exefs)
        eh = f.read(0x200)
        for i in range(10):
            if eh[i * 16:i * 16 + 8].rstrip(b"\0") == b".code":
                off, size = struct.unpack_from("<II", eh, i * 16 + 8)
                f.seek(exefs + 0x200 + off)
                raw = f.read(size)
                return blz(raw) if ex[0xD] & 1 else raw
    raise ValueError("code du jeu introuvable")

