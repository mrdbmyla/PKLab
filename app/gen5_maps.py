import hashlib
import json
import math
import os
import struct

import gen4_maps

_BW_NARCS = {"zones": "a/0/1/2", "text": "a/0/0/2", "matrix": "a/0/0/9", "blocks": "a/0/0/8",
             "map_tex": "a/0/1/4", "packs_ext": "a/2/2/9", "packs_int": "a/2/3/0",
             "btex_ext": "a/1/7/6", "btex_int": "a/1/7/7", "enc": "a/1/2/6"}
_B2W2_NARCS = {"zones": "a/0/1/2", "text": "a/0/0/2", "matrix": "a/0/0/9", "blocks": "a/0/0/8",
               "map_tex": "a/0/1/4", "packs_ext": "a/2/2/5", "packs_int": "a/2/2/6",
               "btex_ext": "a/1/7/4", "btex_int": "a/1/7/5", "enc": "a/1/2/7"}
GAMES = {"POKEMON B": {"narcs": _BW_NARCS, "names_bank": 89}, "POKEMON W": {"narcs": _BW_NARCS, "names_bank": 89},
         "POKEMON B2": {"narcs": _B2W2_NARCS, "names_bank": 109}, "POKEMON W2": {"narcs": _B2W2_NARCS, "names_bank": 109}}
TILE_PX = 16
RENDER_VERSION = "g5b"
from paths import BASE_DIR as _BASE_DIR
CACHE_DIR = os.path.join(_BASE_DIR, "map_cache", "gen5")
GRASS_RATES = [20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1]
SURF_RATES = [60, 30, 5, 4, 1]
FISH_RATES = [40, 40, 15, 4, 1]
SEASON_LABELS = {"fr": ["Printemps", "Été", "Automne", "Hiver"], "en": ["Spring", "Summer", "Autumn", "Winter"]}

_ROM_PATHS = {k: None for k in GAMES}
_rom_data = {}


def set_rom_path(game_key, path):
    if _ROM_PATHS.get(game_key) != path:
        _rom_data.pop(game_key, None)
    _ROM_PATHS[game_key] = path


def _decode_text_bank(data):
    nblocks, nentries = struct.unpack_from("<HH", data, 0)
    block = struct.unpack_from("<I", data, 12)[0]
    out = []
    for i in range(nentries):
        off, ln, _ = struct.unpack_from("<IHH", data, block + 4 + 8 * i)
        enc = struct.unpack_from(f"<{ln}H", data, block + off)
        key = enc[-1] ^ 0xFFFF
        dec = [0] * ln
        for j in range(ln - 1, -1, -1):
            dec[j] = enc[j] ^ key
            key = ((key >> 3) | (key << 13)) & 0xFFFF
        s = []
        for c in dec:
            if c == 0xFFFF:
                break
            s.append(" " if c == 0xFFFE else ("" if c >= 0xF000 else chr(c)))
        out.append("".join(s).strip())
    return out


def _load_rom(game_key, scan_dirs):
    if game_key in _rom_data:
        return _rom_data[game_key]
    path = gen4_maps._find_rom(game_key, scan_dirs) if not _ROM_PATHS.get(game_key) else _ROM_PATHS[game_key]
    if not path or gen4_maps._rom_title(path) != game_key:
        path = gen4_maps._find_rom(game_key, scan_dirs)
    if path is None:
        return None
    with open(path, "rb") as f:
        rom = f.read()
    raw = {k: gen4_maps._rom_file(rom, p) for k, p in GAMES[game_key]["narcs"].items()}
    sha = hashlib.sha1()
    for k in ("matrix", "blocks", "map_tex", "packs_ext", "packs_int"):
        sha.update(raw[k])
    data = {k: gen4_maps._narc_files(v) for k, v in raw.items()}
    data["zones"] = data["zones"][0]
    data["key"] = sha.hexdigest()[:10]
    data["lang"] = "fr" if rom[0x0F:0x10] == b"F" else "en"
    try:
        data["names"] = _decode_text_bank(data["text"][GAMES[game_key]["names_bank"]])
    except Exception:
        data["names"] = []
    data["models"], data["texsets"] = {}, {}
    _rom_data[game_key] = data
    return data


def zone_count(rom):
    return len(rom["zones"]) // 48


def _header(rom, zone):
    return rom["zones"][48 * zone: 48 * zone + 48]


def _matrix(rom, idx):
    m = rom["matrix"][idx]
    has_ids, w, h = struct.unpack_from("<IHH", m, 0)
    n = w * h
    blocks = struct.unpack_from(f"<{n}I", m, 8)
    zones = struct.unpack_from(f"<{n}I", m, 8 + 4 * n) if has_ids else None
    return w, h, blocks, zones


def _season(month):
    return (month - 1) % 4


def _texset(rom, kind, idx):
    import nitro3d
    key = (kind, idx)
    if key not in rom["texsets"]:
        try:
            rom["texsets"][key] = nitro3d.TexSet(rom[kind][idx])
        except Exception:
            rom["texsets"][key] = None
    return rom["texsets"][key]


def _pack(rom, kind, idx):
    key = ("pack", kind, idx)
    if key not in rom["models"]:
        f = rom[kind][idx]
        cnt = struct.unpack_from("<H", f, 2)[0]
        offs = struct.unpack_from(f"<{cnt + 1}I", f, 4)
        k = cnt // 2
        ids = [struct.unpack_from("<I", f, offs[i])[0] & 0xFFFF for i in range(k)]
        rom["models"][key] = (f, offs, k, ids)
    return rom["models"][key]


def _zone_building_ids(rom, blocks, zones, w, h, zone):
    need = set()
    for i in range(w * h):
        if (zones is not None and zones[i] != zone) or blocks[i] == 0xFFFFFFFF or blocks[i] >= len(rom["blocks"]):
            continue
        b = rom["blocks"][blocks[i]]
        if len(b) < 8:
            continue
        n = struct.unpack_from("<H", b, 2)[0]
        offs = struct.unpack_from(f"<{n + 1}I", b, 4)
        objs = b[offs[n - 1]:offs[n]]
        count = struct.unpack_from("<I", objs, 0)[0] if len(objs) >= 4 else 0
        need |= {(objs[18 + 16 * o] << 8) | objs[19 + 16 * o] for o in range(count) if 20 + 16 * o <= len(objs)}
    return need


def _choose_pack(rom, kind, hdr, need):
    n = len(rom[kind])

    def covers(p):
        return 0 <= p < n and need <= set(_pack(rom, kind, p)[3])
    for p in (hdr[1], hdr[1] + 35, hdr[0]):
        if covers(p):
            return p
    for p in range(n):
        if covers(p):
            return p
    return hdr[1] if hdr[1] < n else 0


def _render(rom, zone, month, out):
    import numpy as np
    import nitro3d
    from PIL import Image
    hdr = _header(rom, zone)
    pack_id = hdr[0]
    tex_base, matrix_id = struct.unpack_from("<HH", hdr, 2)
    w, h, blocks, zones = _matrix(rom, matrix_id)
    cells = [(i % w, i // w) for i in range(w * h)
             if (zones is None or zones[i] == zone) and blocks[i] != 0xFFFFFFFF]
    if not cells:
        return None
    x0, x1 = min(c[0] for c in cells), max(c[0] for c in cells)
    z0, z1 = min(c[1] for c in cells), max(c[1] for c in cells)
    indoor = zones is None
    pkind, tkind = ("packs_int", "btex_int") if indoor else ("packs_ext", "btex_ext")
    tw, th = (x1 - x0 + 1) * 32, (z1 - z0 + 1) * 32
    canvas = np.zeros((th * TILE_PX, tw * TILE_PX, 3), float)
    zbuf = np.full((th * TILE_PX, tw * TILE_PX), -1e9)
    base_ts = _texset(rom, "map_tex", tex_base)
    season_ts = _texset(rom, "map_tex", tex_base + _season(month)) if not indoor else None
    pack_id = _choose_pack(rom, pkind, hdr, _zone_building_ids(rom, blocks, zones, w, h, zone))
    try:
        f, poffs, k, ids = _pack(rom, pkind, pack_id)
    except Exception:
        f, poffs, k, ids = b"", [], 0, []
    bts = _texset(rom, tkind, pack_id)
    for cz in range(z0, z1 + 1):
        for cx in range(x0, x1 + 1):
            i = cz * w + cx
            bi = blocks[i]
            if bi == 0xFFFFFFFF or bi >= len(rom["blocks"]):
                continue
            cell_zone = zones[i] if zones else zone
            b = rom["blocks"][bi]
            n = struct.unpack_from("<H", b, 2)[0]
            offs = struct.unpack_from(f"<{n + 1}I", b, 4)
            ccx, ccz = ((cx - x0) * 32 + 16) * 16, ((cz - z0) * 32 + 16) * 16
            m = nitro3d.Model(b[offs[0]:offs[1]])
            needed = {mt["tex"] for mt in m.materials if mt["tex"]}
            ts = season_ts if season_ts is not None and needed <= set(season_ts.textures) else base_ts
            gen4_maps._draw_model(canvas, zbuf, m, [ts],
                                  lambda x, z, m=m, ccx=ccx, ccz=ccz: ((x * m.pos_scale + ccx) / 16 * TILE_PX,
                                                                      (z * m.pos_scale + ccz) / 16 * TILE_PX))
            objs = b[offs[n - 1]:offs[n]]
            count = struct.unpack_from("<I", objs, 0)[0] if len(objs) >= 4 else 0
            for o in range(count):
                if 4 + 16 * o + 16 > len(objs):
                    break
                bx, by, bz = struct.unpack_from("<3i", objs, 4 + 16 * o)
                rot = struct.unpack_from("<H", objs, 16 + 16 * o)[0]
                bid = (objs[18 + 16 * o] << 8) | objs[19 + 16 * o]
                if bid not in ids:
                    continue
                j = ids.index(bid)
                mkey = ("model", pkind, pack_id, bid)
                if mkey not in rom["models"]:
                    data = f[poffs[k + j]:poffs[k + j + 1]]
                    try:
                        pm = nitro3d.Model(data)
                    except Exception:
                        pm = None
                    try:
                        own = nitro3d.TexSet(data)
                    except Exception:
                        own = None
                    rom["models"][mkey] = (pm, own)
                pm, own = rom["models"][mkey]
                if pm is None:
                    continue
                a = rot / 65536 * 2 * math.pi
                c, s = math.cos(a), math.sin(a)

                def to(x, z, pm=pm, bx=bx, bz=bz, c=c, s=s, ccx=ccx, ccz=ccz):
                    X, Z = x * pm.pos_scale, z * pm.pos_scale
                    rx, rz = X * c + Z * s, -X * s + Z * c
                    return ((rx + bx / 4096 + ccx) / 16 * TILE_PX, (rz - bz / 4096 + ccz) / 16 * TILE_PX)
                gen4_maps._draw_model(canvas, zbuf, pm, [own, bts], to,
                                      height=lambda y, pm=pm, by=by: y * pm.pos_scale + by / 4096)
            if cell_zone != zone:
                ys, xs = (cz - z0) * 32 * TILE_PX, (cx - x0) * 32 * TILE_PX
                canvas[ys:ys + 32 * TILE_PX, xs:xs + 32 * TILE_PX] *= 0.45
    rows = np.where((zbuf > -1e8).any(1))[0]
    cols = np.where((zbuf > -1e8).any(0))[0]
    crop = [0, 0, tw, th]
    if len(rows) and len(cols):
        cx0, cx1 = cols[0] // TILE_PX, cols[-1] // TILE_PX + 1
        cy0, cy1 = rows[0] // TILE_PX, rows[-1] // TILE_PX + 1
        crop = [int(cx0), int(cy0), int(cx1 - cx0), int(cy1 - cy0)]
        canvas = canvas[cy0 * TILE_PX:cy1 * TILE_PX, cx0 * TILE_PX:cx1 * TILE_PX]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp.png"
    Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8)).save(tmp)
    with open(out + ".json", "w", encoding="utf-8") as fjs:
        json.dump({"crop": crop, "origin": [x0 * 32, z0 * 32]}, fjs)
    os.replace(tmp, out)
    return out


def zone_plan(game_key, zone, scan_dirs, month, progress=None):
    rom = _load_rom(game_key, scan_dirs)
    if rom is None or not 0 <= zone < zone_count(rom):
        return None
    hdr = _header(rom, zone)
    matrix_id = struct.unpack_from("<H", hdr, 4)[0]
    if matrix_id >= len(rom["matrix"]):
        return None
    season = _season(month) if _matrix(rom, matrix_id)[3] is not None else 0
    out = os.path.join(CACHE_DIR, "images", f"{rom['key']}_{RENDER_VERSION}_s{season}_zone_{zone}.png")
    if not os.path.exists(out):
        if progress:
            progress(f"[Carte N/B] rendu 3D de la zone {zone}")
        if _render(rom, zone, month, out) is None:
            return None
    with open(out + ".json", encoding="utf-8") as fjs:
        meta = json.load(fjs)
    cx, cy, cw, ch = meta["crop"]
    ox, oy = meta["origin"]
    rel = os.path.relpath(out, _BASE_DIR).replace(os.sep, "/")
    return "/" + rel, cw, ch, ox + cx, oy + cy


def _encounters(rom, table, month):
    table &= 0x1FFF
    if table == 0x1FFF or table >= len(rom["enc"]):
        return None
    e = rom["enc"][table]
    if len(e) >= 4 * 232:
        e = e[232 * _season(month): 232 * _season(month) + 232]

    def slots(off, n, rates):
        out = []
        for i, rate in enumerate(rates[:n]):
            sp, lo, hi = struct.unpack_from("<HBB", e, off + 4 * i)
            sp &= 0x7FF
            if sp and lo:
                out.append({"species": sp, "minLevel": lo, "maxLevel": max(lo, hi), "rate": rate})
        return out
    rates = e[:8]
    out = {}
    if rates[0]:
        out["land"] = slots(8, 12, GRASS_RATES)
    if rates[3]:
        out["water"] = slots(152, 5, SURF_RATES)
    if rates[5]:
        out["superRod"] = slots(192, 5, FISH_RATES)
    out = {k: v for k, v in out.items() if v}
    return out or None


GEN5_BUILDING_LABELS = [
    (r"^m_pc0\d", "Centre Pokémon", "Pokémon Center"),
    (r"^m_gym", "Arène", "Gym"),
    (r"^m_(w)?labo", "Laboratoire", "Lab"),
    (r"^m_siten", "Salle du Conseil 4", "Elite Four Room"),
    (r"^m_champ", "Salle du Maître", "Champion's Room"),
    (r"^m_dendo", "Panthéon", "Hall of Fame"),
    (r"^m_nschool", "Jardin d'enfants", "Preschool"),
    (r"^m_school", "École des Dresseurs", "Trainers' School"),
    (r"^m_grow", "Pension", "Day Care"),
    (r"^m_museum", "Musée", "Museum"),
    (r"^m_cafe", "Café", "Café"),
    (r"^m_market", "Marché", "Market"),
    (r"^m_airport", "Aéroport", "Airport"),
    (r"^m_mall", "Centre Commercial", "Shopping Mall"),
    (r"^m_(bsubway|gstation)", "Gare", "Station"),
    (r"^m_closseum", "Club Wi-Fi", "Wi-Fi Club"),
    (r"^m_union", "Salle Union", "Union Room"),
    (r"^m_theater", "Music-Hall", "Musical Theater"),
    (r"^m_(stadium|seat|football|baseball|soccer|tennis|basket)", "Stade", "Stadium"),
    (r"^m_villa", "Villa", "Villa"),
    (r"^m_cabin", "Cabine", "Cabin"),
    (r"^m_gate", "Porte", "Gate"),
    (r"^m_(h\d|hh|fh|whouse|thouse|ph\d|d12h|tryhouse)", "Maison", "House"),
    (r"^m_(b|bc|y|z)?buill", "Bâtiment", "Building"),
    (r"^m_atelier", "Atelier", "Workshop"),
    (r"^m_bcmall", "Marché", "Market"),
    (r"^m_furniture", "Magasin de meubles", "Furniture Shop"),
    (r"^m_live", "Salle de concert", "Concert Hall"),
    (r"^m_bar", "Bar", "Bar"),
    (r"^m_church", "Église", "Church"),
    (r"^m_(old)?(bw)?gym|^m_oldbwgy", "Arène", "Gym"),
    (r"^m_hotel", "Hôtel", "Hotel"),
    (r"^m_dining", "Restaurant", "Restaurant"),
    (r"^m_daisuki", "Fan Club", "Fan Club"),
    (r"^m_(swanhh|swanrh|seahous|oldh\d)", "Maison", "House"),
    (r"^m_oldscho", "École des Dresseurs", "Trainers' School"),
    (r"^m_oldbbui", "Bâtiment", "Building"),
    (r"^m_oldchur", "Église", "Church"),
    (r"^m_(un\d|ruin|container|ncastle|pal\d|dun|medal|Wbt|mugen|pwood|resonan|oldthea|olddun)", None, None),
]


def building_label(model_name, lang):
    import re
    for pattern, fr, en in GEN5_BUILDING_LABELS:
        if re.search(pattern, model_name or ""):
            return fr if lang == "fr" else en
    if (model_name or "").startswith("m_") and not model_name.startswith("m_dun"):
        return gen4_maps.INTERIOR_LABEL["fr" if lang == "fr" else "en"]
    return None


def _block_model_name(rom, block_id):
    import nitro3d
    if block_id == 0xFFFFFFFF or block_id >= len(rom["blocks"]):
        return ""
    key = ("name", block_id)
    if key not in rom["models"]:
        b = rom["blocks"][block_id]
        try:
            n = struct.unpack_from("<H", b, 2)[0]
            offs = struct.unpack_from(f"<{n + 1}I", b, 4)
            rom["models"][key] = nitro3d.Model(b[offs[0]:offs[1]]).name
        except Exception:
            rom["models"][key] = ""
    return rom["models"][key]


def get_zone_bundle(game_key, zone, progress=None, scan_dirs=(), month=None):
    import time
    if game_key not in GAMES:
        return None
    rom = _load_rom(game_key, scan_dirs)
    if rom is None or not 0 <= zone < zone_count(rom):
        return None
    month = month or time.localtime().tm_mon
    hdr = _header(rom, zone)
    name_idx = hdr[26]
    place = rom["names"][name_idx] if name_idx < len(rom["names"]) else ""
    w, h, blocks, zones = _matrix(rom, struct.unpack_from("<H", hdr, 4)[0])
    indoor = zones is None
    display = place or f"Zone {zone}"
    if indoor:
        model = _block_model_name(rom, blocks[0])
        label = building_label(model, rom["lang"])
        if label is None:
            display = place or f"Zone {zone}"
        elif not place:
            display = label
        elif label.lower() in place.lower():
            display = place
        else:
            display = f"{place} · {label}"
    if progress:
        progress(f"[Carte N/B] zone {zone} = {display}")
    bundle = {"name": f"G5_ZONE_{zone}", "displayName": display, "image": None, "width": None, "height": None,
              "encounters": _encounters(rom, struct.unpack_from("<H", hdr, 20)[0], month),
              "timeOfDay": SEASON_LABELS[rom["lang"]][_season(month)]}
    try:
        plan = zone_plan(game_key, zone, scan_dirs, month, progress)
    except Exception as e:
        plan = None
        if progress:
            progress(f"[Carte N/B] plan indisponible : {e}")
    if plan:
        bundle["image"], bundle["width"], bundle["height"], bundle["originX"], bundle["originY"] = plan
    return bundle
