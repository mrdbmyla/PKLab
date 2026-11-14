import struct


def file_id(rom, path):
    fnt_off = struct.unpack_from("<I", rom, 0x40)[0]
    d = 0xF000
    parts = path.split("/")
    for i, part in enumerate(parts):
        sub_off, fid, _ = struct.unpack_from("<IHH", rom, fnt_off + 8 * (d & 0xFFF))
        p = fnt_off + sub_off
        found = None
        while rom[p]:
            b = rom[p]
            n = b & 0x7F
            name = bytes(rom[p + 1:p + 1 + n]).decode("latin-1")
            p += 1 + n
            if b & 0x80:
                ident = struct.unpack_from("<H", rom, p)[0]
                p += 2
            else:
                ident = fid
                fid += 1
            if name == part:
                found = ident
                break
        if found is None:
            raise KeyError(path)
        if i == len(parts) - 1:
            return found
        d = found


def _fat(rom):
    fat_off, fat_size = struct.unpack_from("<II", rom, 0x48)
    return fat_off, [struct.unpack_from("<II", rom, fat_off + 8 * i) for i in range(fat_size // 8)]


def _content_end(rom):
    _, fat = _fat(rom)
    ends = [e for s, e in fat if e > s]
    for off_at, size_at in ((0x20, 0x2C), (0x30, 0x3C), (0x40, 0x44), (0x48, 0x4C), (0x50, 0x54), (0x58, 0x5C)):
        o, n = struct.unpack_from("<II", rom, off_at)[0], struct.unpack_from("<I", rom, size_at)[0]
        ends.append(o + n)
    ends.append(struct.unpack_from("<I", rom, 0x80)[0])
    if rom[0x12] & 2:
        ends.append(struct.unpack_from("<I", rom, 0x210)[0])
    return max(ends)


def replace_file(rom, path, data):
    fid = file_id(rom, path)
    fat_off, fat = _fat(rom)
    start, end = fat[fid]
    nxt = min([s for s, e in fat if s >= end and e > s] + [_content_end(rom)])
    if start + len(data) <= nxt:
        rom[start:start + len(data)] = data
        if start + len(data) < end:
            rom[start + len(data):end] = b"\xFF" * (end - start - len(data))
        struct.pack_into("<II", rom, fat_off + 8 * fid, start, start + len(data))
        return "en place"
    new = (_content_end(rom) + 0x1FF) & ~0x1FF
    if new + len(data) > len(rom):
        size = len(rom)
        while size < new + len(data):
            size *= 2
        rom.extend(b"\xFF" * (size - len(rom)))
    rom[new:new + len(data)] = data
    rom[start:end] = b"\xFF" * (end - start)
    struct.pack_into("<II", rom, fat_off + 8 * fid, new, new + len(data))
    return "déplacé"


def narc_unpack(data):
    p = struct.unpack_from("<H", data, 0xC)[0]
    if data[:4] != b"NARC" or data[p:p + 4] != b"BTAF":
        raise ValueError("NARC invalide")
    btaf_size, count = struct.unpack_from("<IH", data, p + 4)
    entries = [struct.unpack_from("<II", data, p + 12 + 8 * i) for i in range(count)]
    p += btaf_size
    btnf_size = struct.unpack_from("<I", data, p + 4)[0]
    btnf = bytes(data[p:p + btnf_size])
    p += btnf_size
    if data[p:p + 4] != b"GMIF":
        raise ValueError("NARC invalide")
    base = p + 8
    return [bytes(data[base + s:base + e]) for s, e in entries], btnf


def narc_pack(members, btnf):
    entries, blob = [], bytearray()
    for m in members:
        entries.append((len(blob), len(blob) + len(m)))
        blob += m
        while len(blob) % 4:
            blob += b"\xFF"
    btaf = b"BTAF" + struct.pack("<IHH", 12 + 8 * len(members), len(members), 0) + b"".join(
        struct.pack("<II", s, e) for s, e in entries)
    gmif = b"GMIF" + struct.pack("<I", 8 + len(blob)) + bytes(blob)
    total = 16 + len(btaf) + len(btnf) + len(gmif)
    head = b"NARC" + struct.pack("<HHIHH", 0xFFFE, 0x0100, total, 16, 3)
    return head + btaf + btnf + gmif


def _key(i):
    return (0x7C89 + i * 0x2983) & 0xFFFF


def text_unpack(data):
    nb, ne, _, _ = struct.unpack_from("<HHII", data, 0)
    offs = struct.unpack_from(f"<{nb}I", data, 12)
    blocks, unks = [], []
    for b in range(nb):
        blk = offs[b]
        strings, unk = [], []
        for i in range(ne):
            off, ln, u = struct.unpack_from("<IHH", data, blk + 4 + 8 * i)
            enc = struct.unpack_from(f"<{ln}H", data, blk + off)
            key = _key(i)
            dec = []
            for c in enc:
                dec.append(c ^ key)
                key = ((key << 3) | (key >> 13)) & 0xFFFF
            strings.append(dec)
            unk.append(u)
        blocks.append(strings)
        unks.append(unk)
    return {"blocks": blocks, "unk": unks}


def text_pack(t):
    blocks = t["blocks"]
    nb, ne = len(blocks), len(blocks[0]) if blocks else 0
    out_blocks = []
    for b, strings in enumerate(blocks):
        table, body = bytearray(), bytearray()
        pos = 4 + 8 * ne
        for i, dec in enumerate(strings):
            key = _key(i)
            enc = []
            for c in dec:
                enc.append(c ^ key)
                key = ((key << 3) | (key >> 13)) & 0xFFFF
            table += struct.pack("<IHH", pos + len(body), len(dec), t["unk"][b][i])
            body += struct.pack(f"<{len(enc)}H", *enc)
        while (4 + len(table) + len(body)) % 4:
            body += b"\x00\x00"
        size = 4 + len(table) + len(body)
        out_blocks.append(struct.pack("<I", size) + bytes(table) + bytes(body))
    head_len = 12 + 4 * nb
    offs, pos = [], head_len
    for blk in out_blocks:
        offs.append(pos)
        pos += len(blk)
    head = struct.pack("<HHII", nb, ne, len(out_blocks[0]) if out_blocks else 0, 0) + struct.pack(f"<{nb}I", *offs)
    return head + b"".join(out_blocks)


def decompress(chars):
    if not chars or chars[0] != 0xF100:
        return list(chars)
    out, bits, nbits = [], 0, 0
    for c in chars[1:]:
        if c == 0xFFFF and nbits < 9:
            break
        bits |= c << nbits
        nbits += 16
        while nbits >= 9:
            v = bits & 0x1FF
            bits >>= 9
            nbits -= 9
            if v == 0x1FF:
                return out + [0xFFFF]
            out.append(v)
    return out + [0xFFFF]


def to_str(chars):
    return "".join(chr(c) for c in decompress(chars) if c < 0xF000)


def blz_decompress(data):
    data = bytes(data)
    inc = struct.unpack_from("<I", data, len(data) - 4)[0]
    if inc == 0:
        return data
    word = struct.unpack_from("<I", data, len(data) - 8)[0]
    hdr, enc = word >> 24, word & 0xFFFFFF
    out = bytearray(data) + bytearray(inc)
    src = len(data) - hdr
    dst = len(out)
    stop = len(data) - enc
    while dst > stop:
        src -= 1
        flags = data[src]
        for bit in range(8):
            if dst <= stop:
                break
            if flags & (0x80 >> bit):
                src -= 2
                v = data[src] | (data[src + 1] << 8)
                n = (v >> 12) + 3
                disp = (v & 0xFFF) + 3
                for _ in range(n):
                    dst -= 1
                    out[dst] = out[dst + disp]
            else:
                src -= 1
                dst -= 1
                out[dst] = data[src]
    return bytes(out)


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def arm9_read(rom):
    off, _, load, size = struct.unpack_from("<IIII", rom, 0x20)
    a9 = bytes(rom[off:off + size])
    mp = a9.find(struct.pack("<I", 0xDEC00621)) - 0x1C
    if mp < 0:
        raise ValueError("ARM9 : paramètres introuvables")
    cend = struct.unpack_from("<I", a9, mp + 0x14)[0]
    if cend:
        a9 = blz_decompress(a9[:cend - load]) + a9[cend - load:]
    return a9, mp


def arm9_write(rom, a9, mp):
    off, _, load, size = struct.unpack_from("<IIII", rom, 0x20)
    cur = bytes(rom[off:off + size])
    cend = struct.unpack_from("<I", cur, mp + 0x14)[0]
    if cend:
        comp = cur[:cend - load]
        enc = struct.unpack_from("<I", comp, len(comp) - 8)[0] & 0xFFFFFF
        min_prefix = len(comp) - enc
        tail = cur[cend - load:]
        body = a9[:len(a9) - len(tail)] if tail else a9
    else:
        min_prefix, tail, body = mp + 0x20, b"", a9
    data = blz_compress(body, min_prefix=max(min_prefix, mp + 0x20))
    if data is None:
        raise ValueError("ARM9 : compression impossible")
    data = bytearray(data)
    struct.pack_into("<I", data, mp + 0x14, load + len(data))
    new = bytes(data) + bytes(tail)
    nxt = min([s for s, e in _fat(rom)[1] if s >= off + size and e > s] + [struct.unpack_from("<I", rom, 0x50)[0]])
    rom[off:off + size] = b"\xFF" * size
    if off + len(new) > nxt:
        off = (_content_end(rom) + 0x1FF) & ~0x1FF
        if off + len(new) > len(rom):
            new_size = len(rom)
            while new_size < off + len(new):
                new_size *= 2
            rom.extend(b"\xFF" * (new_size - len(rom)))
    rom[off:off + len(new)] = new
    struct.pack_into("<I", rom, 0x20, off)
    struct.pack_into("<I", rom, 0x2C, len(new))
    struct.pack_into("<H", rom, 0x15E, crc16(rom[:0x15E]))


def overlay_read(rom, index):
    ovt = struct.unpack_from("<I", rom, 0x50)[0] + 32 * index
    fid = struct.unpack_from("<I", rom, ovt + 24)[0]
    flags = struct.unpack_from("<I", rom, ovt + 28)[0]
    s, e = _fat(rom)[1][fid]
    raw = bytes(rom[s:e])
    return blz_decompress(raw) if flags >> 24 & 1 else raw


def blz_literal_map(data):
    data = bytes(data)
    inc = struct.unpack_from("<I", data, len(data) - 4)[0]
    word = struct.unpack_from("<I", data, len(data) - 8)[0]
    hdr, enc = word >> 24, word & 0xFFFFFF
    src = len(data) - hdr
    dst = len(data) + inc
    stop = len(data) - enc
    literal, copied_from = {}, set()
    for i in range(stop):
        literal[i] = i
    while dst > stop:
        src -= 1
        flags = data[src]
        for bit in range(8):
            if dst <= stop:
                break
            if flags & (0x80 >> bit):
                src -= 2
                v = data[src] | (data[src + 1] << 8)
                n = (v >> 12) + 3
                disp = (v & 0xFFF) + 3
                for _ in range(n):
                    dst -= 1
                    copied_from.add(dst + disp)
            else:
                src -= 1
                dst -= 1
                literal[dst] = src
    return literal, copied_from


def patch_compressed(raw, offset, new_bytes):
    literal, copied = blz_literal_map(raw)
    out = bytearray(raw)
    for k, b in enumerate(new_bytes):
        pos = offset + k
        if pos not in literal or pos in copied:
            return None
        out[literal[pos]] = b
    return bytes(out)


def _blz_encode(raw):
    rev = raw[::-1]
    n = len(rev)
    out = bytearray()
    heads = {}
    i = 0

    def add(pos):
        if pos + 3 <= n:
            heads.setdefault(rev[pos:pos + 3], []).append(pos)
    while i < n:
        flag_at = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if i >= n:
                break
            best_len, best_disp = 0, 0
            if i + 3 <= n:
                for j in reversed(heads.get(rev[i:i + 3], [])):
                    disp = i - j
                    if disp < 3:
                        continue
                    if disp > 0x1002:
                        break
                    ln = 3
                    while ln < 18 and i + ln < n and rev[j + ln] == rev[i + ln]:
                        ln += 1
                    if ln > best_len:
                        best_len, best_disp = ln, disp
                        if ln == 18:
                            break
            if best_len >= 3:
                flags |= 0x80 >> bit
                v = ((best_len - 3) << 12) | (best_disp - 3)
                out += bytes((v >> 8, v & 0xFF))
                for k in range(best_len):
                    add(i + k)
                i += best_len
            else:
                out.append(rev[i])
                add(i)
                i += 1
        out[flag_at] = flags
    return bytes(out[::-1])


def blz_compress(raw, min_prefix=0):
    raw = bytes(raw)
    for prefix in range(min_prefix, len(raw) + 1, 0x80):
        payload = _blz_encode(raw[prefix:])
        body = raw[:prefix] + payload
        pad = (-len(body)) % 4
        hdr = pad + 8
        enc = len(payload) + hdr
        total = len(body) + hdr
        inc = len(raw) - total
        if inc <= 0:
            break
        data = body + b"\xFF" * pad + struct.pack("<II", (hdr << 24) | enc, inc)
        if _blz_inplace_safe(data) and blz_decompress(data) == raw:
            return data
    return None


def _blz_inplace_safe(data):
    inc = struct.unpack_from("<I", data, len(data) - 4)[0]
    word = struct.unpack_from("<I", data, len(data) - 8)[0]
    hdr, enc = word >> 24, word & 0xFFFFFF
    src, dst, stop = len(data) - hdr, len(data) + inc, len(data) - enc
    while dst > stop:
        src -= 1
        flags = data[src]
        for bit in range(8):
            if dst <= stop:
                break
            if flags & (0x80 >> bit):
                src -= 2
                dst -= ((data[src] | (data[src + 1] << 8)) >> 12) + 3
            else:
                src -= 1
                dst -= 1
            if dst < src:
                return False
    return True


def overlay_write_compressed(rom, index, raw):
    data = blz_compress(raw)
    if data is None:
        raise ValueError(f"overlay {index} : compression impossible")
    ovt = struct.unpack_from("<I", rom, 0x50)[0] + 32 * index
    fid = struct.unpack_from("<I", rom, ovt + 24)[0]
    fat_off, fat = _fat(rom)
    start, end = fat[fid]
    nxt = min([s for s, e in fat if s >= end and e > s] + [_content_end(rom)])
    rom[start:end] = b"\xFF" * (end - start)
    new = start
    if start + len(data) > nxt:
        new = (_content_end(rom) + 0x1FF) & ~0x1FF
    rom[new:new + len(data)] = data
    struct.pack_into("<II", rom, fat_off + 8 * fid, new, new + len(data))
    old = struct.unpack_from("<I", rom, ovt + 28)[0]
    struct.pack_into("<I", rom, ovt + 28, (old & 0xFF000000) | (len(data) & 0xFFFFFF) | 0x01000000)


def overlay_patch_in_place(rom, index, offset, new_bytes):
    ovt = struct.unpack_from("<I", rom, 0x50)[0] + 32 * index
    fid = struct.unpack_from("<I", rom, ovt + 24)[0]
    if not struct.unpack_from("<I", rom, ovt + 28)[0] >> 24 & 1:
        return False
    s, e = _fat(rom)[1][fid]
    patched = patch_compressed(bytes(rom[s:e]), offset, new_bytes)
    if patched is None:
        return False
    rom[s:e] = patched
    return True


def code_set_bytes(rom, where, offset, new_bytes):
    new_bytes = bytes(new_bytes)
    if where is None:
        off, _, load, size = struct.unpack_from("<IIII", rom, 0x20)
        cur = bytes(rom[off:off + size])
        mp = cur.find(struct.pack("<I", 0xDEC00621)) - 0x1C
        cend = struct.unpack_from("<I", cur, mp + 0x14)[0] if mp >= 0 else 0
        if not cend:
            rom[off + offset:off + offset + len(new_bytes)] = new_bytes
            return
        a9, mp = arm9_read(rom)
        a9 = bytearray(a9)
        a9[offset:offset + len(new_bytes)] = new_bytes
        arm9_write(rom, bytes(a9), mp)
        return
    ovt = struct.unpack_from("<I", rom, 0x50)[0] + 32 * where
    fid = struct.unpack_from("<I", rom, ovt + 24)[0]
    if not struct.unpack_from("<I", rom, ovt + 28)[0] >> 24 & 1:
        s, _ = _fat(rom)[1][fid]
        rom[s + offset:s + offset + len(new_bytes)] = new_bytes
        return
    if overlay_patch_in_place(rom, where, offset, new_bytes):
        return
    raw = bytearray(overlay_read(rom, where))
    raw[offset:offset + len(new_bytes)] = new_bytes
    overlay_write_compressed(rom, where, bytes(raw))
