import json
import os
import re
import struct
import urllib.request

try:
    from PIL import Image
except ImportError:
    Image = None

from games_gen3 import gen3_species_to_national

GEN3_REPO_BY_GAME = {
    "EMERALD": "pokeemerald",
    "FIRERED": "pokefirered",
    "LEAFGREEN": "pokefirered",
    "RUBY": "pokeruby",
    "SAPPHIRE": "pokeruby",
}

from paths import BASE_DIR as _BASE_DIR
CACHE_DIR_ROOT = os.path.join(_BASE_DIR, "map_cache")
TILE_PX = 8
METATILE_PX = 16


def _pret_base(repo):
    return f"https://raw.githubusercontent.com/pret/{repo}/master"


def _cache_dir(repo):
    return os.path.join(CACHE_DIR_ROOT, repo)


def _img_dir(repo):
    return os.path.join(_cache_dir(repo), "images")


def _asset_dir(repo):
    return os.path.join(_cache_dir(repo), "assets")


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "PKLab"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def _fetch_cached(url, local_path):
    if os.path.exists(local_path):
        with open(local_path, "rb") as f:
            return f.read()
    data = _fetch(url)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(data)
    return data


def _fetch_json_cached(url, local_path):
    return json.loads(_fetch_cached(url, local_path))


_map_groups = {}
_layouts_by_id = {}


def _load_map_groups(repo):
    if repo not in _map_groups:
        _map_groups[repo] = _fetch_json_cached(
            f"{_pret_base(repo)}/data/maps/map_groups.json",
            os.path.join(_cache_dir(repo), "map_groups.json"),
        )
    return _map_groups[repo]


def _load_layouts(repo):
    if repo not in _layouts_by_id:
        data = _fetch_json_cached(
            f"{_pret_base(repo)}/data/layouts/layouts.json",
            os.path.join(_cache_dir(repo), "layouts.json"),
        )
        _layouts_by_id[repo] = {entry["id"]: entry for entry in data["layouts"] if "id" in entry}
    return _layouts_by_id[repo]


def map_name_from_group_num(repo, map_group, map_num):
    groups = _load_map_groups(repo)
    order = groups["group_order"]
    if not (0 <= map_group < len(order)):
        return None
    names = groups.get(order[map_group], [])
    if not (0 <= map_num < len(names)):
        return None
    return names[map_num]


def _load_map_json(repo, map_name):
    return _fetch_json_cached(
        f"{_pret_base(repo)}/data/maps/{map_name}/map.json",
        os.path.join(_asset_dir(repo), "maps", f"{map_name}.json"),
    )


def _load_pal(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f]
    n = int(lines[2])
    return [tuple(int(v) for v in lines[3 + i].split()) for i in range(n)]


PRIMARY_SPLIT = {"pokeemerald": (512, 512, 6), "pokeruby": (512, 512, 6), "pokefirered": (640, 640, 7)}


def _load_tileset(repo, symbol_name):
    short = symbol_name[len("gTileset_"):]
    plain = "".join("_" + c.lower() if c.isupper() else c for c in short).lstrip("_")
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", short).lower()
    words = re.sub(r"(?<=[a-z])(?=\d)", "_", words)
    candidates = [words, words.replace("secret_base_", "secret_base/", 1), plain]
    for kind, folder_name in [(k, f) for f in dict.fromkeys(candidates) for k in ("primary", "secondary")]:
        remote_dir = f"{_pret_base(repo)}/data/tilesets/{kind}/{folder_name}"
        local_dir = os.path.join(_asset_dir(repo), "tilesets", kind, folder_name)
        metatiles_dir = remote_dir.rsplit("/", 1)[0] if "/" in folder_name else remote_dir
        try:
            _fetch_cached(f"{metatiles_dir}/metatiles.bin", os.path.join(local_dir, "metatiles.bin"))
        except Exception:
            continue
        tiles_png_path = os.path.join(local_dir, "tiles.png")
        _fetch_cached(f"{remote_dir}/tiles.png", tiles_png_path)
        pal_paths = []
        for i in range(16):
            p = os.path.join(local_dir, "palettes", f"{i:02d}.pal")
            _fetch_cached(f"{remote_dir}/palettes/{i:02d}.pal", p)
            pal_paths.append(p)
        ts = _build_tileset(local_dir, tiles_png_path, pal_paths)
        ts["split"] = PRIMARY_SPLIT.get(repo, (512, 512, 6))
        return ts
    raise FileNotFoundError(f"tileset folder not found in primary or secondary: {folder_name}")


_tileset_cache = {}


def _build_tileset(local_dir, tiles_png_path, pal_paths):
    if local_dir in _tileset_cache:
        return _tileset_cache[local_dir]
    im = Image.open(tiles_png_path)
    w, h = im.size
    tiles_per_row = w // TILE_PX
    n_tiles = tiles_per_row * (h // TILE_PX)
    px = im.load()
    tiles = []
    for t in range(n_tiles):
        tx = (t % tiles_per_row) * TILE_PX
        ty = (t // tiles_per_row) * TILE_PX
        tiles.append([[px[tx + x, ty + y] for x in range(TILE_PX)] for y in range(TILE_PX)])

    palettes = [_load_pal(p) for p in pal_paths]

    with open(os.path.join(local_dir, "metatiles.bin"), "rb") as f:
        mt_data = f.read()
    metatiles = [struct.unpack_from("<8H", mt_data, m * 16) for m in range(len(mt_data) // 16)]

    result = {"tiles": tiles, "n_tiles": n_tiles, "palettes": palettes, "metatiles": metatiles}
    _tileset_cache[local_dir] = result
    return result


def _draw_tile(canvas, px0, py0, tile_grid, palette, hflip, vflip, transparent_zero):
    for y in range(TILE_PX):
        for x in range(TILE_PX):
            idx = tile_grid[7 - y if vflip else y][7 - x if hflip else x]
            if transparent_zero and idx == 0:
                continue
            canvas.putpixel((px0 + x, py0 + y), palette[idx] if idx < len(palette) else (255, 0, 255))


_metatile_img_cache = {}


def _metatile_image(metatile_id, primary, secondary):
    cache_key = (id(primary), id(secondary), metatile_id)
    if cache_key in _metatile_img_cache:
        return _metatile_img_cache[cache_key]
    split_tiles, split_metatiles, split_pals = primary.get("split", (512, 512, 6))
    if metatile_id < split_metatiles:
        if metatile_id >= len(primary["metatiles"]):
            _metatile_img_cache[cache_key] = None
            return None
        entries = primary["metatiles"][metatile_id]
    else:
        local = metatile_id - split_metatiles
        if secondary is None or local >= len(secondary["metatiles"]):
            _metatile_img_cache[cache_key] = None
            return None
        entries = secondary["metatiles"][local]

    img = Image.new("RGB", (METATILE_PX, METATILE_PX), (0, 0, 0))
    quad_px = [(0, 0), (8, 0), (0, 8), (8, 8)]
    for layer in range(2):
        for q in range(4):
            word = entries[layer * 4 + q]
            tile_id = word & 0x3FF
            hflip = bool(word & 0x400)
            vflip = bool(word & 0x800)
            pal_num = (word >> 12) & 0xF
            if tile_id < split_tiles:
                src, local_id = primary, tile_id
            else:
                src, local_id = secondary, tile_id - split_tiles
            if src is None or local_id >= len(src["tiles"]):
                continue
            pal_src = primary if pal_num < split_pals or secondary is None else secondary
            palette = pal_src["palettes"][pal_num] if pal_num < len(pal_src["palettes"]) else primary["palettes"][0]
            px0, py0 = quad_px[q]
            _draw_tile(img, px0, py0, src["tiles"][local_id], palette, hflip, vflip, transparent_zero=(layer == 1))
    _metatile_img_cache[cache_key] = img
    return img


def get_map_image(repo, map_name, progress=None):
    img_dir = _img_dir(repo)
    out_path = os.path.join(img_dir, f"{map_name}.png")
    meta_path = os.path.join(img_dir, f"{map_name}.json")
    if os.path.exists(out_path) and os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return out_path, meta["width"], meta["height"]

    if progress: progress(f"Rendu de la carte {map_name}...")
    map_json = _load_map_json(repo, map_name)
    layout_id = map_json["layout"]
    layouts = _load_layouts(repo)
    layout = layouts[layout_id]
    width, height = layout["width"], layout["height"]

    primary = _load_tileset(repo, layout["primary_tileset"])
    secondary = _load_tileset(repo, layout["secondary_tileset"])

    blockdata_rel = layout["blockdata_filepath"]
    local_bin = os.path.join(_asset_dir(repo), blockdata_rel.replace("/", os.sep))
    data = _fetch_cached(f"{_pret_base(repo)}/{blockdata_rel}", local_bin)
    n_cells = width * height
    cells = struct.unpack_from(f"<{n_cells}H", data, 0)

    canvas = Image.new("RGB", (width * METATILE_PX, height * METATILE_PX), (0, 0, 0))
    for i, raw in enumerate(cells):
        metatile_id = raw & 0x3FF
        mt_img = _metatile_image(metatile_id, primary, secondary)
        if mt_img is not None:
            x, y = i % width, i // width
            canvas.paste(mt_img, (x * METATILE_PX, y * METATILE_PX))

    os.makedirs(img_dir, exist_ok=True)
    canvas.save(out_path)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"width": width, "height": height}, f)
    return out_path, width, height


LAND_RATES = [20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1]
WATER_RATES = [60, 30, 5, 4, 1]
ROCK_SMASH_RATES = [60, 30, 5, 4, 1]
FISHING_RATES = [70, 30, 60, 20, 20, 40, 40, 15, 4, 1]
FISHING_GROUPS = {"old_rod": (0, 2), "good_rod": (2, 5), "super_rod": (5, 10)}

_species_name_to_id = {}
_encounters_by_map = {}


def _load_species_ids(repo):
    if repo not in _species_name_to_id:
        path = os.path.join(_cache_dir(repo), "species.h")
        data = _fetch_cached(f"{_pret_base(repo)}/include/constants/species.h", path).decode("utf-8")
        ids = {}
        for m in re.finditer(r"#define\s+(SPECIES_\w+)\s+(\d+)", data):
            ids[m.group(1)] = int(m.group(2))
        _species_name_to_id[repo] = ids
    return _species_name_to_id[repo]


def _load_wild_encounters(repo):
    if repo not in _encounters_by_map:
        data = _fetch_json_cached(
            f"{_pret_base(repo)}/src/data/wild_encounters.json",
            os.path.join(_cache_dir(repo), "wild_encounters.json"),
        )
        by_map = {}
        for group in data["wild_encounter_groups"]:
            if not group.get("for_maps"):
                continue
            for entry in group.get("encounters", []):
                by_map[entry["map"]] = entry
        _encounters_by_map[repo] = by_map
    return _encounters_by_map[repo]


def _mons_with_rates(mons, rates, species_ids):
    out = []
    for mon, rate in zip(mons, rates):
        dex = gen3_species_to_national(species_ids.get(mon["species"]))
        if dex is None:
            continue
        out.append({
            "species": dex, "minLevel": mon["min_level"], "maxLevel": mon["max_level"], "rate": rate,
        })
    return out


def get_encounters(repo, map_id):
    by_map = _load_wild_encounters(repo)
    entry = by_map.get(map_id)
    if entry is None:
        return None
    species_ids = _load_species_ids(repo)
    out = {}
    if "land_mons" in entry:
        out["land"] = _mons_with_rates(entry["land_mons"]["mons"], LAND_RATES, species_ids)
    if "water_mons" in entry:
        out["water"] = _mons_with_rates(entry["water_mons"]["mons"], WATER_RATES, species_ids)
    if "rock_smash_mons" in entry:
        out["rockSmash"] = _mons_with_rates(entry["rock_smash_mons"]["mons"], ROCK_SMASH_RATES, species_ids)
    if "fishing_mons" in entry:
        mons = entry["fishing_mons"]["mons"]
        for rod, (lo, hi) in FISHING_GROUPS.items():
            key = {"old_rod": "oldRod", "good_rod": "goodRod", "super_rod": "superRod"}[rod]
            out[key] = _mons_with_rates(mons[lo:hi], FISHING_RATES[lo:hi], species_ids)
    return out or None


GEN3_ROM_TITLES = {"EMERALD": "POKEMON EMER", "FIRERED": "POKEMON FIRE", "LEAFGREEN": "POKEMON LEAF",
                   "RUBY": "POKEMON RUBY", "SAPPHIRE": "POKEMON SAPP"}
_ROM_PATH = {"path": None}
_place_names = {}
_SMALL_WORDS = {"de", "du", "des", "la", "le", "les", "en", "sur", "sous", "et", "au", "aux", "of", "the"}
_KEEP_UPPER = {"SARL", "SA", "PC", "CT", "TV"}


def set_rom_path(path):
    _ROM_PATH["path"] = path


def _gba_title(path):
    try:
        with open(path, "rb") as f:
            f.seek(0xA0)
            return f.read(12).decode("latin-1")
    except OSError:
        return None


def _find_gba_rom(game_key, scan_dirs):
    title = GEN3_ROM_TITLES.get(game_key)
    path = _ROM_PATH["path"]
    if path and _gba_title(path) == title:
        return path
    for d in scan_dirs:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            p = os.path.join(d, n)
            if n.lower().endswith(".gba") and _gba_title(p) == title:
                return p
    return None


def _gba_charmap():
    data = _fetch_cached(f"{_pret_base('pokeemerald')}/charmap.txt", os.path.join(_cache_dir("pokeemerald"), "charmap.txt"))
    cm = {}
    for line in data.decode("utf-8").splitlines():
        m = re.match(r"^'(.)'\s*=\s*([0-9A-Fa-f]{2})\s*$", line)
        if m and int(m.group(2), 16) not in cm:
            cm[int(m.group(2), 16)] = m.group(1)
    return cm


def _gba_string(rom, ptr, cm):
    off = ptr - 0x08000000
    out = []
    for i in range(64):
        if not 0 <= off + i < len(rom):
            break
        b = rom[off + i]
        if b == 0xFF:
            break
        out.append(" " if b == 0xFC else cm.get(b, ""))
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _nice_case(s):
    letters = re.sub(r"[^A-Za-z]", "", s or "")
    if not letters or not letters.isupper():
        return s
    parts = re.split(r"([ \-'’])", s)
    out = []
    for i, p in enumerate(parts):
        low = p.lower()
        if re.fullmatch(r"(?:[A-Z]\.)+", p) or p in _KEEP_UPPER:
            out.append(p)
        elif i > 0 and low in _SMALL_WORDS:
            out.append(low)
        else:
            out.append(p[:1] + p[1:].lower())
    return "".join(out)


def _load_sections(repo):
    return _fetch_json_cached(f"{_pret_base(repo)}/src/data/region_map/region_map_sections.json",
                              os.path.join(_asset_dir(repo), "region_map_sections.json"))["map_sections"]


def _rom_place_names(game_key, scan_dirs):
    if game_key in _place_names:
        return _place_names[game_key]
    result = None
    try:
        repo = GEN3_REPO_BY_GAME[game_key]
        path = _find_gba_rom(game_key, scan_dirs)
        if path:
            with open(path, "rb") as f:
                rom = f.read()
            secs = _load_sections(repo)
            cm = _gba_charmap()
            in_rom = lambda p: 0x08000000 <= p < 0x08000000 + len(rom)
            names = [""] * len(secs)
            if repo == "pokefirered":
                start = next(i for i, s in enumerate(secs) if "name" in s)
                named = secs[start:]
                corners = b"".join(struct.pack("<HH", s.get("x", 0), s.get("y", 0)) for s in named[:10])
                t = next((m.start() for m in re.finditer(re.escape(corners), rom) if m.start() % 4 == 0), None)
                if t is not None:
                    ptrs = struct.unpack_from(f"<{len(named)}I", rom, t - 4 * len(named))
                    if all(in_rom(p) for p in ptrs):
                        for i, p in enumerate(ptrs):
                            names[start + i] = _gba_string(rom, p, cm)
            else:
                key = lambda s: bytes([s.get("x", 0), s.get("y", 0), s.get("width", 0), s.get("height", 0)])
                for m in re.finditer(re.escape(key(secs[0])), rom):
                    t = m.start()
                    if t % 4 == 0 and all(rom[t + 8 * i: t + 8 * i + 4] == key(s)
                                          and in_rom(struct.unpack_from("<I", rom, t + 8 * i + 4)[0])
                                          for i, s in enumerate(secs[:12])):
                        for i in range(len(secs)):
                            names[i] = _gba_string(rom, struct.unpack_from("<I", rom, t + 8 * i + 4)[0], cm)
                        break
            if any(names):
                result = ([_nice_case(n) for n in names], "fr" if rom[0xAF:0xB0] == b"F" else "en")
    except Exception:
        result = None
    _place_names[game_key] = result
    return result


def zone_display_name(game_key, map_name, scan_dirs=()):
    try:
        import gen4_maps
        repo = GEN3_REPO_BY_GAME[game_key]
        mj = _load_map_json(repo, map_name)
        sec = mj.get("region_map_section", "")
        ids = [s["id"] for s in _load_sections(repo)]
        found = _rom_place_names(game_key, scan_dirs)
        if found and sec in ids:
            names, lang = found
            place = names[ids.index(sec)]
            if not place and mj.get("map_type") == "MAP_TYPE_INDOOR":
                header = re.sub(r"(?<=[a-z])(?=[A-Z0-9])", "_", map_name).upper()
                label, _floor = gen4_maps.building_label(header, lang)
                if label != gen4_maps.INTERIOR_LABEL["fr" if lang == "fr" else "en"]:
                    return label
            if place:
                if mj.get("map_type") != "MAP_TYPE_INDOOR":
                    return place
                header = re.sub(r"(?<=[a-z])(?=[A-Z0-9])", "_", map_name).upper()
                label, floor = gen4_maps.building_label(header, lang)
                generic = label == gen4_maps.INTERIOR_LABEL["fr" if lang == "fr" else "en"]
                if sec == "MAPSEC_SPECIAL_AREA" and not generic:
                    return label
                if generic:
                    return f"{place} · {floor}" if floor else place
                is_place = re.search(r"CITY|TOWN|ROUTE|ISLAND|AREA|PLATEAU|VILLAGE|LEAGUE", sec)
                if not is_place or label.lower() in place.lower():
                    return f"{place} · {floor}" if floor else place
                return f"{place} · {label}" + (f" ({floor})" if floor else "")
    except Exception:
        pass
    return display_name(map_name)


def get_map_bundle(game_key, map_group, map_num, progress=None, scan_dirs=()):
    repo = GEN3_REPO_BY_GAME.get(game_key)
    if repo is None:
        return None
    map_name = map_name_from_group_num(repo, map_group, map_num)
    if map_name is None:
        return None
    map_json = _load_map_json(repo, map_name)
    encounters = get_encounters(repo, map_json["id"])
    rom = _ROM_PATH["path"]
    if rom and _gba_title(rom) == GEN3_ROM_TITLES.get(game_key):
        try:
            import randomizer_gen3
            encounters = randomizer_gen3.wild_for_map(rom, map_group, map_num, (
                LAND_RATES, WATER_RATES, ROCK_SMASH_RATES, FISHING_RATES, FISHING_GROUPS))
        except Exception as e:
            if progress:
                progress(f"Rencontres de la ROM aléatoire illisibles : {e}")
    image, width, height = None, None, None
    try:
        img_path, width, height = get_map_image(repo, map_name, progress=progress)
        image = "/" + os.path.relpath(img_path, _BASE_DIR).replace(os.sep, "/")
    except Exception as e:
        if progress:
            progress(f"Erreur rendu minimap ({map_name}): {e}")
        width = height = None
    return {
        "name": map_name,
        "displayName": zone_display_name(game_key, map_name, scan_dirs),
        "image": image,
        "width": width,
        "height": height,
        "encounters": encounters,
    }


def display_name(internal_name):
    name = internal_name.replace("_", " ")
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    name = re.sub(r"(?<=[A-Za-z])(?=[0-9])", " ", name)
    return name
