import struct


def read_dict(data, off):
    rev, count, size_dict, _dummy, ofs_entry = struct.unpack_from("<BBHHH", data, off)
    e = off + ofs_entry
    size_unit, size_name = struct.unpack_from("<HH", data, e)
    out = []
    names_off = e + 4 + size_unit * count
    for i in range(count):
        ent_off = e + 4 + size_unit * i
        name = data[names_off + 16 * i: names_off + 16 * i + 16].split(b"\0")[0].decode("latin-1")
        out.append((name, data[ent_off: ent_off + size_unit], ent_off))
    return out


def blocks(data):
    magic = data[:4]
    n = struct.unpack_from("<H", data, 0xE)[0]
    offs = struct.unpack_from(f"<{n}I", data, 0x10)
    return magic, {data[o:o + 4]: o for o in offs}


class Model:
    def __init__(self, data):
        _, blk = blocks(data)
        mdl0 = blk[b"MDL0"]
        models = read_dict(data, mdl0 + 8)
        name, ent, _ = models[0]
        base = mdl0 + struct.unpack_from("<I", ent)[0]
        self.name = name
        size, ofs_sbc, ofs_mat, ofs_shp, ofs_evp = struct.unpack_from("<5I", data, base)
        info = base + 20
        (self.sbc_type, _, _, self.num_node, self.num_mat, self.num_shp, _, _,
         pos_scale, inv_pos_scale, self.num_vtx, self.num_poly, self.num_tri, self.num_quad) = struct.unpack_from(
            "<8BiiHHHH", data, info)
        self.pos_scale = pos_scale / 4096.0
        self.box = struct.unpack_from("<6h", data, info + 0x1C)
        self.sbc = data[base + ofs_sbc: base + ofs_mat]
        mat = base + ofs_mat
        ofs_tex2mat, ofs_pltt2mat = struct.unpack_from("<HH", data, mat)
        self.materials = []
        for mname, ment, _ in read_dict(data, mat + 4):
            m = mat + struct.unpack_from("<I", ment)[0]
            (_tag, _sz, dif_amb, spe_emi, poly_attr, poly_mask, tex_param, tex_mask, pltt_base, flag,
             ow, oh) = struct.unpack_from("<HHIIIIIIHHHH", data, m)
            self.materials.append({"name": mname, "difAmb": dif_amb, "polyAttr": poly_attr, "texParam": tex_param,
                                   "flag": flag, "w": ow, "h": oh, "tex": None, "pltt": None})
        for kind, ofs in (("tex", ofs_tex2mat), ("pltt", ofs_pltt2mat)):
            for tname, tent, _ in read_dict(data, mat + ofs):
                lst_off, num, _bound = struct.unpack_from("<HBB", tent)
                for k in range(num):
                    mi = data[mat + lst_off + k]
                    self.materials[mi][kind] = tname
        shp = base + ofs_shp
        self.shapes = []
        for sname, sent, _ in read_dict(data, shp):
            s = shp + struct.unpack_from("<I", sent)[0]
            _tag, _sz, flag, ofs_dl, size_dl = struct.unpack_from("<HHIII", data, s)
            self.shapes.append({"name": sname, "dl": data[s + ofs_dl: s + ofs_dl + size_dl]})
        self.draws = self._parse_sbc()

    def _parse_sbc(self):
        sbc = self.sbc
        i, cur_mat, out = 0, None, []
        while i < len(sbc):
            op = sbc[i]
            base = op & 0x1F
            if base == 0x00:
                i += 1
            elif base == 0x01:
                break
            elif base == 0x02:
                i += 3
            elif base == 0x03:
                i += 2
            elif base == 0x04:
                cur_mat = sbc[i + 1]
                i += 2
            elif base == 0x05:
                out.append((cur_mat, sbc[i + 1]))
                i += 2
            elif base == 0x06:
                i += 4 + {0x00: 0, 0x20: 1, 0x40: 1, 0x60: 2}[op & 0x60]
            elif base in (0x07, 0x08):
                i += 2 + (1 if op & 0x20 else 0) + (1 if op & 0x40 else 0)
            elif base == 0x09:
                n = sbc[i + 2]
                i += 3 + 3 * n
            elif base == 0x0A:
                i += 9
            elif base == 0x0B:
                i += 1
            elif base in (0x0C, 0x0D):
                i += 3
            else:
                raise ValueError(f"SBC op inconnu 0x{op:02X} a {i}")
        return out


GX_PARAMS = {0x00: 0, 0x10: 1, 0x11: 0, 0x12: 1, 0x13: 1, 0x14: 1, 0x15: 0, 0x16: 16, 0x17: 12, 0x18: 16,
             0x19: 12, 0x1A: 9, 0x1B: 3, 0x1C: 3, 0x20: 1, 0x21: 1, 0x22: 1, 0x23: 2, 0x24: 1, 0x25: 1,
             0x26: 1, 0x27: 1, 0x28: 1, 0x29: 1, 0x2A: 1, 0x2B: 1, 0x30: 1, 0x31: 1, 0x32: 1, 0x33: 1,
             0x34: 32, 0x40: 1, 0x41: 0, 0x50: 1, 0x60: 1, 0x70: 3, 0x71: 2, 0x72: 1}


def _s(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def run_display_list(dl):
    words = struct.unpack_from(f"<{len(dl) // 4}I", dl)
    i = 0
    vtx = [0, 0, 0]
    st = (0.0, 0.0)
    col = None
    prim, buf, tris = None, [], []

    def emit():
        v = ((vtx[0] / 4096.0, vtx[1] / 4096.0, vtx[2] / 4096.0), st, col)
        buf.append(v)
        if prim == 0 and len(buf) == 3:
            tris.append(tuple(buf)); buf.clear()
        elif prim == 1 and len(buf) == 4:
            tris.append((buf[0], buf[1], buf[2])); tris.append((buf[0], buf[2], buf[3])); buf.clear()
        elif prim == 2 and len(buf) >= 3:
            n = len(buf)
            tris.append((buf[-3], buf[-2], buf[-1]) if n % 2 else (buf[-2], buf[-3], buf[-1]))
        elif prim == 3 and len(buf) >= 4 and len(buf) % 2 == 0:
            a, b, c, d = buf[-4], buf[-3], buf[-2], buf[-1]
            tris.append((a, b, d)); tris.append((a, d, c))

    while i < len(words):
        cmds = [(words[i] >> (8 * k)) & 0xFF for k in range(4)]
        i += 1
        for c in cmds:
            n = GX_PARAMS.get(c)
            if n is None:
                raise ValueError(f"GX cmd inconnu 0x{c:02X}")
            p = words[i:i + n]
            i += n
            if c == 0x40:
                prim, buf = p[0] & 3, []
            elif c == 0x41:
                buf = []
            elif c == 0x20:
                v = p[0]
                col = ((v & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, ((v >> 10) & 31) * 255 // 31)
            elif c == 0x22:
                st = (_s(p[0] & 0xFFFF, 16) / 16.0, _s(p[0] >> 16, 16) / 16.0)
            elif c == 0x23:
                vtx = [_s(p[0] & 0xFFFF, 16), _s(p[0] >> 16, 16), _s(p[1] & 0xFFFF, 16)]; emit()
            elif c == 0x24:
                vtx = [_s(p[0] & 0x3FF, 10) << 6, _s((p[0] >> 10) & 0x3FF, 10) << 6, _s((p[0] >> 20) & 0x3FF, 10) << 6]; emit()
            elif c == 0x25:
                vtx[0], vtx[1] = _s(p[0] & 0xFFFF, 16), _s(p[0] >> 16, 16); emit()
            elif c == 0x26:
                vtx[0], vtx[2] = _s(p[0] & 0xFFFF, 16), _s(p[0] >> 16, 16); emit()
            elif c == 0x27:
                vtx[1], vtx[2] = _s(p[0] & 0xFFFF, 16), _s(p[0] >> 16, 16); emit()
            elif c == 0x28:
                vtx[0] += _s(p[0] & 0x3FF, 10); vtx[1] += _s((p[0] >> 10) & 0x3FF, 10); vtx[2] += _s((p[0] >> 20) & 0x3FF, 10); emit()
    return tris


def _wrap(v, size, repeat, flip):
    import numpy as np
    if not repeat:
        return np.clip(v, 0, size - 1)
    if flip:
        m = np.mod(v, 2 * size)
        return np.where(m >= size, 2 * size - 1 - m, m)
    return np.mod(v, size)


def render_top(canvas, zbuf, tris, tex, tex_param, diffuse, to_px):
    import numpy as np
    H, W = zbuf.shape
    rep_s, rep_t = bool(tex_param & (1 << 16)), bool(tex_param & (1 << 17))
    flip_s, flip_t = bool(tex_param & (1 << 18)), bool(tex_param & (1 << 19))
    for tri in tris:
        P = np.array([to_px(v[0][0], v[0][2]) for v in tri], float)
        Y = np.array([v[0][1] for v in tri], float)
        ST = np.array([v[1] for v in tri], float)
        C = np.array([v[2] if v[2] is not None else diffuse for v in tri], float)
        (x0, y0), (x1, y1), (x2, y2) = P
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-6:
            continue
        minx, maxx = max(int(np.floor(P[:, 0].min())), 0), min(int(np.ceil(P[:, 0].max())), W - 1)
        miny, maxy = max(int(np.floor(P[:, 1].min())), 0), min(int(np.ceil(P[:, 1].max())), H - 1)
        if minx > maxx or miny > maxy:
            continue
        gx, gy = np.meshgrid(np.arange(minx, maxx + 1) + 0.5, np.arange(miny, maxy + 1) + 0.5)
        w0 = ((x1 - gx) * (y2 - gy) - (x2 - gx) * (y1 - gy)) / area
        w1 = ((x2 - gx) * (y0 - gy) - (x0 - gx) * (y2 - gy)) / area
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue
        depth = w0 * Y[0] + w1 * Y[1] + w2 * Y[2]
        zb = zbuf[miny:maxy + 1, minx:maxx + 1]
        m = inside & (depth >= zb - 1e-4)
        if not m.any():
            continue
        col = (w0[..., None] * C[0] + w1[..., None] * C[1] + w2[..., None] * C[2]) / 255.0
        if tex is not None:
            th, tw = tex.shape[:2]
            s = w0 * ST[0, 0] + w1 * ST[1, 0] + w2 * ST[2, 0]
            t = w0 * ST[0, 1] + w1 * ST[1, 1] + w2 * ST[2, 1]
            si = _wrap(np.floor(s).astype(int), tw, rep_s, flip_s)
            ti = _wrap(np.floor(t).astype(int), th, rep_t, flip_t)
            texel = tex[ti, si]
            m &= texel[..., 3] >= 128
            rgb = texel[..., :3] * col
        else:
            rgb = 255.0 * col
        cv = canvas[miny:maxy + 1, minx:maxx + 1]
        cv[m] = rgb[m]
        zb[m] = depth[m]


class TexSet:

    def __init__(self, data):
        _, blk = blocks(data)
        t = blk[b"TEX0"]
        (_m, _sz, _p, tex_size, tex_info, _p2, tex_data, _p3, ctex_size, ctex_info, _p4, ctex_data,
         ctex_idx, _p5, pltt_size, pltt_info, pltt_data) = struct.unpack_from("<4sIIHHIIIHHIIIIIII", data, t)
        self.data, self.t = data, t
        self.tex_data, self.ctex_data, self.ctex_idx, self.pltt_data = t + tex_data, t + ctex_data, t + ctex_idx, t + pltt_data
        self.textures = {}
        for name, ent, _ in read_dict(data, t + tex_info):
            p, _extra = struct.unpack_from("<II", ent)
            self.textures[name] = {"ofs": (p & 0xFFFF) << 3, "w": 8 << ((p >> 20) & 7), "h": 8 << ((p >> 23) & 7),
                                   "fmt": (p >> 26) & 7, "c0": (p >> 29) & 1}
        self.palettes = {}
        for name, ent, _ in read_dict(data, t + pltt_info):
            o, _f = struct.unpack_from("<HH", ent)
            self.palettes[name] = o << 3
        self._cache = {}

    def _color(self, pal_ofs, i):
        v = struct.unpack_from("<H", self.data, self.pltt_data + pal_ofs + 2 * i)[0]
        return [((v >> s) & 31) * 255 // 31 for s in (0, 5, 10)]

    def decode(self, tex_name, pltt_name):
        import numpy as np
        key = (tex_name, pltt_name)
        if key in self._cache:
            return self._cache[key]
        t = self.textures.get(tex_name)
        if t is None:
            return None
        w, h, fmt = t["w"], t["h"], t["fmt"]
        pal = self.palettes.get(pltt_name, 0)
        d = self.data
        out = np.zeros((h, w, 4), np.uint8)
        n = w * h
        if fmt == 7:
            px = struct.unpack_from(f"<{n}H", d, self.tex_data + t["ofs"])
            for k, v in enumerate(px):
                out[k // w, k % w] = [((v >> s) & 31) * 255 // 31 for s in (0, 5, 10)] + [255 if v & 0x8000 else 0]
        elif fmt == 5:
            base = self.ctex_data + t["ofs"]
            idx_base = self.ctex_idx + t["ofs"] // 2
            bw = w // 4
            for b in range((w // 4) * (h // 4)):
                bits = struct.unpack_from("<I", d, base + 4 * b)[0]
                info = struct.unpack_from("<H", d, idx_base + 2 * b)[0]
                po = pal + (info & 0x3FFF) * 4
                mode = info >> 14
                c0, c1 = self._color(po, 0), self._color(po, 1)
                if mode == 0:
                    cols = [c0 + [255], c1 + [255], self._color(po, 2) + [255], [0, 0, 0, 0]]
                elif mode == 1:
                    cols = [c0 + [255], c1 + [255], [(a + b2) // 2 for a, b2 in zip(c0, c1)] + [255], [0, 0, 0, 0]]
                elif mode == 2:
                    cols = [c0 + [255], c1 + [255], self._color(po, 2) + [255], self._color(po, 3) + [255]]
                else:
                    cols = [c0 + [255], c1 + [255], [(5 * a + 3 * b2) // 8 for a, b2 in zip(c0, c1)] + [255],
                            [(3 * a + 5 * b2) // 8 for a, b2 in zip(c0, c1)] + [255]]
                by, bx = (b // bw) * 4, (b % bw) * 4
                for k in range(16):
                    out[by + k // 4, bx + k % 4] = cols[(bits >> (2 * k)) & 3]
        else:
            bpp = {1: 8, 2: 2, 3: 4, 4: 8, 6: 8}[fmt]
            raw = d[self.tex_data + t["ofs"]: self.tex_data + t["ofs"] + n * bpp // 8]
            ncol = {1: 32, 2: 4, 3: 16, 4: 256, 6: 8}[fmt]
            pv = struct.unpack_from(f"<{ncol}H", d, self.pltt_data + pal) if self.pltt_data + pal + 2 * ncol <= len(d) else [0] * ncol
            palette = np.array([[((v >> s) & 31) * 255 // 31 for s in (0, 5, 10)] for v in pv], np.uint8)
            arr = np.frombuffer(raw, np.uint8)
            if bpp == 2:
                idx = np.stack([(arr >> s) & 3 for s in (0, 2, 4, 6)], 1).reshape(-1)
                alpha = np.full(n, 255, np.uint8)
            elif bpp == 4:
                idx = np.stack([arr & 15, arr >> 4], 1).reshape(-1)
                alpha = np.full(n, 255, np.uint8)
            elif fmt == 1:
                idx, a = arr & 31, arr >> 5
                alpha = (a.astype(np.uint16) * 255 // 7).astype(np.uint8)
            elif fmt == 6:
                idx, a = arr & 7, arr >> 3
                alpha = (a.astype(np.uint16) * 255 // 31).astype(np.uint8)
            else:
                idx = arr
                alpha = np.full(n, 255, np.uint8)
            rgb = palette[idx[:n]]
            if t["c0"] and fmt in (2, 3, 4):
                alpha = np.where(idx[:n] == 0, 0, alpha).astype(np.uint8)
            out = np.concatenate([rgb, alpha[:n, None]], 1).reshape(h, w, 4)
        self._cache[key] = out
        return out
