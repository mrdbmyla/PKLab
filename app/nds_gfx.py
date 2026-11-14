import struct

import numpy as np

OAM_SIZES = {0: [(8, 8), (16, 16), (32, 32), (64, 64)],
             1: [(16, 8), (32, 8), (32, 16), (64, 32)],
             2: [(8, 16), (8, 32), (16, 32), (32, 64)]}


def chunk_span(d, magic):
    p = 0x10
    while p + 8 <= len(d):
        m, size = d[p:p + 4], struct.unpack_from("<I", d, p + 4)[0]
        if m == magic:
            return p, size
        if size <= 0:
            break
        p += size
    raise ValueError("chunk introuvable : " + magic.decode())


def palette(d, count=16):
    p, _ = chunk_span(d, b"TTLP")
    size = struct.unpack_from("<I", d, p + 16)[0]
    raw = np.frombuffer(d[p + 0x18:p + 0x18 + min(size, count * 2)], "<u2")
    return raw.copy()


def set_palette(d, colors):
    d = bytearray(d)
    p, _ = chunk_span(d, b"TTLP")
    struct.pack_into(f"<{len(colors)}H", d, p + 0x18, *[int(c) for c in colors])
    return bytes(d)


def tiles4(d):
    p, _ = chunk_span(d, b"RAHC")
    bpp = struct.unpack_from("<I", d, p + 12)[0]
    size = struct.unpack_from("<I", d, p + 0x18)[0]
    if bpp != 3:
        raise ValueError("seulement 4 bpp")
    b = np.frombuffer(d[p + 0x20:p + 0x20 + size], np.uint8)
    return np.stack([b & 15, b >> 4], -1).reshape(-1, 8, 8)


def set_tiles4(d, tiles):
    d = bytearray(d)
    p, _ = chunk_span(d, b"RAHC")
    flat = tiles.reshape(-1, 2).astype(np.uint8)
    data = (flat[:, 0] | (flat[:, 1] << 4)).astype(np.uint8).tobytes()
    size = struct.unpack_from("<I", d, p + 0x18)[0]
    if len(data) != size:
        raise ValueError("taille d'image différente")
    d[p + 0x20:p + 0x20 + size] = data
    return bytes(d)


def cells(d):
    p, _ = chunk_span(d, b"KBEC")
    n, attr, off = struct.unpack_from("<HHI", d, p + 8)
    entry = 16 if attr & 1 else 8
    base = p + 8 + off
    out = []
    for c in range(n):
        noam, _, oam_off = struct.unpack_from("<HHI", d, base + entry * c)
        ob = base + entry * n + oam_off
        oams = []
        for j in range(noam):
            a0, a1, a2 = struct.unpack_from("<HHH", d, ob + 6 * j)
            y = a0 & 0xFF
            y = y - 256 if y >= 128 else y
            x = a1 & 0x1FF
            x = x - 512 if x >= 256 else x
            w, h = OAM_SIZES[a0 >> 14][a1 >> 14]
            oams.append((x, y, w, h, a2 & 0x3FF, bool(a1 & 0x1000), bool(a1 & 0x2000)))
        out.append(oams)
    return out


def paint_cell(tiles, oams, img, shift=0):
    tiles = tiles.copy()
    half = img.shape[0] // 2
    for x, y, w, h, tile, hf, vf in oams:
        k = tile << shift
        x0, y0 = x + half, y + half
        for ty in range(h // 8):
            for tx in range(w // 8):
                if k < len(tiles):
                    tiles[k] = img[y0 + ty * 8:y0 + ty * 8 + 8, x0 + tx * 8:x0 + tx * 8 + 8]
                k += 1
    return tiles

