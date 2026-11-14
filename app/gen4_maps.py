import hashlib
import json
import os
import re
import struct
import urllib.error
import urllib.request

try:
    from PIL import Image
except ImportError:
    Image = None

_PT_NARCS = {
    "matrix": "fielddata/mapmatrix/map_matrix.narc",
    "land": "fielddata/land_data/land_data.narc",
    "area": "fielddata/areadata/area_data.narc",
    "map_tex": "fielddata/areadata/area_map_tex/map_tex_set.narc",
    "build": "fielddata/build_model/build_model.narc",
    "build_tex": "fielddata/areadata/area_build_model/areabm_texset.narc",
}
_HGSS_NARCS = {"matrix": "a/0/4/1", "land": "a/0/6/5", "area": "a/0/4/2",
               "map_tex": "a/0/4/4", "build": "a/0/4/0", "build_tex": "a/0/7/0",
               "build_room": "fielddata/build_model/bm_room.narc"}
GAMES = {
    "POKEMON PL": {"repo": "pokeplatinum", "branch": "main", "kind": "pt",
                   "narcs": dict(_PT_NARCS, enc="fielddata/encountdata/pl_enc_data.narc"),
                   "names": ("msgdata/pl_msg.narc", 433)},
    "POKEMON D": {"repo": "pokediamond", "branch": "master", "kind": "dp", "version": "dia",
                  "narcs": dict(_PT_NARCS, land="fielddata/land_data/land_data_release.narc",
                                enc="fielddata/encountdata/d_enc_data.narc"),
                  "names": ("msgdata/msg.narc", 382)},
    "POKEMON P": {"repo": "pokediamond", "branch": "master", "kind": "dp", "version": "pea",
                  "narcs": dict(_PT_NARCS, land="fielddata/land_data/land_data_release.narc",
                                enc="fielddata/encountdata/p_enc_data.narc"),
                  "names": ("msgdata/msg.narc", 382)},
    "POKEMON HG": {"repo": "pokeheartgold", "branch": "master", "kind": "hgss", "version": "HEARTGOLD",
                   "narcs": dict(_HGSS_NARCS, enc="a/0/3/7"),
                   "names": ("a/0/2/7", 279)},
    "POKEMON SS": {"repo": "pokeheartgold", "branch": "master", "kind": "hgss", "version": "SOULSILVER",
                   "narcs": dict(_HGSS_NARCS, enc="a/1/3/6"),
                   "names": ("a/0/2/7", 279)},
}
_E4 = {"AARON": "Aaron", "BERTHA": "Terry", "FLINT": "Adrien", "LUCIAN": "Lucio", "CYNTHIA": "Cynthia",
       "WILL": "Clément", "KOGA": "Koga", "BRUNO": "Aldo", "KAREN": "Marion", "LANCE": "Peter",
       "SIDNEY": "Damien", "PHOEBE": "Spectra", "GLACIA": "Glacia", "DRAKE": "Aragon",
       "LORELEI": "Olga", "AGATHA": "Agatha"}
BUILDING_LABELS = [
    (r"POKE_?CENTER|POKEMON_CENTER", "Centre Pokémon", "Pokémon Center"),
    (r"ELEVATOR_TO", "Ascenseur", "Elevator"),
    (r"LEAGUE_CHAMPION_ROOM|LEAGUE_(CYNTHIA|LANCE)_ROOM|CHAMPIONS?_ROOM", "Salle du Maître", "Champion's Room"),
    (r"LEAGUE_(AARON|BERTHA|FLINT|LUCIAN|WILL|KOGA|BRUNO|KAREN)_ROOM|(SIDNEY|PHOEBE|GLACIA|DRAKE|LORELEI|AGATHA|BRUNO|LANCE)S_ROOM",
     "Salle de {e4}", "{e4_en}'s Room"),
    (r"CORRIDOR|_HALL_?\d", "Couloir", "Corridor"),
    (r"POKEMON_LEAGUE(_\d+F)?$", "Ligue Pokémon", "Pokémon League"),
    (r"TRADE_CENTER|RECORD_CORNER|BATTLE_COLOSSEUM", "Salle de connexion", "Link Room"),
    (r"BATTLE_TENT", "Tente de Combat", "Battle Tent"),
    (r"(^|_)HARBOR$", "Port", "Harbor"),
    (r"SPACE_CENTER", "Centre Spatial", "Space Center"),
    (r"WEATHER_INSTITUTE", "Institut Météo", "Weather Institute"),
    (r"DEVON_CORP", "Société Devon", "Devon Corp."),
    (r"SHIPYARD", "Chantier naval", "Shipyard"),
    (r"GLASS_WORKSHOP", "Atelier de verre", "Glass Workshop"),
    (r"CABLE_CAR", "Téléphérique", "Cable Car"),
    (r"REST_STOP", "Halte", "Rest Stop"),
    (r"HALL_OF_FAME_CORRIDOR|HALLWAY_TO_HALL_OF_FAME", "Couloir", "Corridor"),
    (r"HALL_OF_FAME", "Panthéon", "Hall of Fame"),
    (r"LEAGUE_.*_LINK", "Couloir", "Corridor"),
    (r"LEAGUE_(LOBBY|ENTRANCE)|LEAGUE_RECEPTION_GATE", "Hall d'entrée", "Lobby"),
    (r"POKE_?MART|(^|_)MART(_|$)", "Boutique", "Poké Mart"),
    (r"(^|_)GYM(_|$)", "Arène", "Gym"),
    (r"DEPARTMENT_STORE|VEILSTONE_STORE", "Centre Commercial", "Department Store"),
    (r"GAME_CORNER", "Casino", "Game Corner"),
    (r"PRIZE_(EXCHANGE|CORNER)", "Échange de lots", "Prize Exchange"),
    (r"RADIO_(TOWER|STATION)", "Tour Radio", "Radio Tower"),
    (r"(^|_)TV(_|$)", "Télévision", "TV Station"),
    (r"GALACTIC_(HQ|HEADQUARTERS)", "QG Team Galaxie", "Galactic HQ"),
    (r"GALACTIC_(ETERNA_)?BUILDING|ETERNA_GALACTIC", "Bâtiment Team Galaxie", "Galactic Building"),
    (r"(^|_)LAB(ORATORY)?(_|$)|RESEARCH_CENTER", "Laboratoire", "Lab"),
    (r"SCHOOL", "École des Dresseurs", "Trainers' School"),
    (r"DAY_?CARE", "Pension", "Day Care"),
    (r"LIGHTHOUSE", "Phare", "Lighthouse"),
    (r"MUSEUM", "Musée", "Museum"),
    (r"LIBRARY", "Bibliothèque", "Library"),
    (r"CONTEST_(HALL|LOBBY)", "Salle des Concours", "Contest Hall"),
    (r"BIKE_SHOP|CYCLE_SHOP", "Magasin de vélos", "Bike Shop"),
    (r"FLOWER_SHOP", "Fleuriste", "Flower Shop"),
    (r"HERB_SHOP", "Herboristerie", "Herb Shop"),
    (r"PHARMACY", "Pharmacie", "Pharmacy"),
    (r"(^|_)MARKET(_|$)", "Marché", "Market"),
    (r"_SHOP(_|$)", "Magasin", "Shop"),
    (r"RESTAURANT", "Restaurant", "Restaurant"),
    (r"(^|_)CAFE(_|$)", "Café", "Café"),
    (r"POKETCH_CO", "Société Pokétch", "Pokétch Company"),
    (r"NEWS_PRESS", "Presse", "News Press"),
    (r"SILPH_CO", "Sylphe SARL", "Silph Co."),
    (r"FAN_CLUB", "Fan Club", "Fan Club"),
    (r"RIBBON_SYNDICATE", "Ruban Club", "Ribbon Syndicate"),
    (r"GLOBAL_(TERMINAL|TRADE_STATION)", "Échanges mondiaux (GTS)", "Global Terminal"),
    (r"MAGNET_TRAIN_STATION", "Gare", "Train Station"),
    (r"POWER_PLANT", "Centrale", "Power Plant"),
    (r"BATTLE_TOWER", "Tour de Combat", "Battle Tower"),
    (r"BATTLE_(HALL|CASTLE|ARCADE|FACTORY|FRONTIER|PARK)", "Zone de Combat", "Battle Frontier"),
    (r"BATTLEGROUND|DOJO", "Salle de combat", "Battle Hall"),
    (r"UNION", "Salle Union", "Union Room"),
    (r"WIFI|COMMUNICATION_CLUB|COLOSSEUM|RECORD_MIXING", "Club Wi-Fi", "Wi-Fi Club"),
    (r"GATE_?HOUSE|GATEOUSE|BARRIER_STATION", "Poste de passage", "Gate"),
    (r"_PORT_INTERIOR", "Port", "Port"),
    (r"POKEATHLON", "Dôme Pokéathlon", "Pokéathlon Dome"),
    (r"PAL_PARK", "Parc des Amis", "Pal Park"),
    (r"SAFARI_ZONE", "Parc Safari", "Safari Zone"),
    (r"GREAT_MARSH", "Grand Marais", "Great Marsh"),
    (r"POKEMON_MANSION", "Manoir Pokémon", "Pokémon Mansion"),
    (r"GRAND_LAKE|HOTEL|MOTEL", "Hôtel", "Hotel"),
    (r"(^|_)INN(_|$)|LODGE|COTTAGE|VILLA|CABIN", "Gîte", "Lodge"),
    (r"CONDO|(^|_)FLAT", "Résidence", "Condominiums"),
    (r"PLAYER_HOUSE", "Maison du joueur", "Player's House"),
    (r"RIVAL_HOUSE", "Maison du rival", "Rival's House"),
    (r"HOUSE|NAME_RATER", "Maison", "House"),
    (r"OBSERVATORY", "Observatoire", "Observatory"),
    (r"DANCE_THEATER", "Théâtre", "Dance Theater"),
    (r"KILN", "Four à charbon", "Charcoal Kiln"),
    (r"FARM|STABLE", "Ferme", "Farm"),
    (r"SHRINE", "Sanctuaire", "Shrine"),
    (r"SS_AQUA", "Aquaria", "S.S. Aqua"),
    (r"TUNNEL|UNDERGROUND_PATH", "Souterrain", "Underground Path"),
    (r"(^|_)GATE|_ENTRANCE(_|$)", "Poste de passage", "Gate"),
    (r"LOST_TOWER", "Tour Perdue", "Lost Tower"),
    (r"TOWER", "Tour", "Tower"),
    (r"RUINS", "Ruines", "Ruins"),
    (r"(^|_)CAVE(_|$)", "Grotte", "Cave"),
    (r"FOREIGN_BUILDING|(^|_)BUILDING(_|$)", "Bâtiment", "Building"),
]
INTERIOR_LABEL = {"fr": "intérieur", "en": "interior"}


def _floor(header, lang):
    fr = lang == "fr"
    if re.search(r"ELEVATOR", header):
        return "ascenseur" if fr else "elevator"
    if re.search(r"ROOF", header):
        return "toit" if fr else "roof"
    if re.search(r"BASEMENT", header):
        return "sous-sol" if fr else "basement"
    m = re.search(r"_(B?)(\d+)F(?=_|$)", header)
    if not m:
        return ""
    n = int(m.group(2))
    if m.group(1):
        return (f"sous-sol {n}" if n > 1 else "sous-sol") if fr else f"B{n}F"
    if n <= 1:
        return ""
    return ("1er étage" if n == 2 else f"{n - 1}e étage") if fr else f"{n}F"


def building_label(header, lang):
    if not re.search(r"UNUSED|UNKNOWN", header):
        for pattern, fr, en in BUILDING_LABELS:
            m = re.search(pattern, header)
            if m:
                label = fr if lang == "fr" else en
                if "{e4" in label:
                    who = next((k for k in _E4 if re.search(rf"_{k}S?_ROOM", header)), "")
                    label = label.format(e4=_E4.get(who, who.title()), e4_en=who.title())
                    label = re.sub(r"\bde ([AEIOUÉ])", r"d'\1", label)
                floor = _floor(header, lang)
                if floor and floor.lower() in label.lower():
                    floor = ""
                return label, floor
    return INTERIOR_LABEL["fr" if lang == "fr" else "en"], _floor(header, lang)
REPO_BY_GAME = {k: v["repo"] for k, v in GAMES.items()}

from paths import BASE_DIR as _BASE_DIR
CACHE_DIR_ROOT = os.path.join(_BASE_DIR, "map_cache")

PT_LAND_RATES = [20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1]
PT_SURF_RATES = [60, 30, 5, 4, 1]
PT_OLD_ROD_RATES = [60, 30, 5, 4, 1]
PT_GOOD_SUPER_ROD_RATES = [40, 40, 15, 4, 1]
HG_LAND_RATES = [20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1]
HG_SURF_RATES = [60, 30, 5, 4, 1]
HG_ROD_RATES = [40, 30, 15, 10, 5]
HG_ROCK_SMASH_RATES = [80, 20]


def time_of_day(hour):
    if 4 <= hour <= 9:
        return "morning"
    if 10 <= hour <= 16:
        return "day"
    if 17 <= hour <= 19:
        return "twilight"
    return "night"


TIME_OF_DAY_LABELS = {"morning": "Matin", "day": "Jour", "twilight": "Crépuscule", "night": "Nuit"}

_mem_cache = {}


def _cache_dir(repo):
    return os.path.join(CACHE_DIR_ROOT, repo)


def _fetch_cached(repo, rel_path, local_name):
    local = os.path.join(_cache_dir(repo), local_name)
    if os.path.exists(local):
        with open(local, "rb") as f:
            return f.read()
    if os.path.exists(local + ".none"):
        return None
    branch = next(g["branch"] for g in GAMES.values() if g["repo"] == repo)
    url = f"https://raw.githubusercontent.com/pret/{repo}/{branch}/{rel_path}"
    req = urllib.request.Request(url, headers={"User-Agent": "PKLab"})
    os.makedirs(os.path.dirname(local), exist_ok=True)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            open(local + ".none", "w").close()
            return None
        raise
    with open(local, "wb") as f:
        f.write(data)
    return data


def _lines(repo, rel_path, local_name):
    key = (repo, local_name)
    if key not in _mem_cache:
        data = _fetch_cached(repo, rel_path, local_name)
        _mem_cache[key] = [l.strip() for l in data.decode("utf-8").splitlines()
                           if l.strip() and "=" not in l and not l.strip().endswith("_COUNT")] if data else []
    return _mem_cache[key]


def _defines(repo, rel_path, local_name, prefix):
    key = (repo, local_name, "defines")
    if key not in _mem_cache:
        data = _fetch_cached(repo, rel_path, local_name)
        text = data.decode("utf-8") if data else ""
        _mem_cache[key] = {m.group(1): int(m.group(2))
                           for m in re.finditer(rf"#define\s+({prefix}\w+)\s+(\d+)\b", text)}
    return _mem_cache[key]


def _hg_map_names(repo):
    key = (repo, "map_names")
    if key not in _mem_cache:
        defs = _defines(repo, "include/constants/maps.h", "maps.h", "MAP_")
        _mem_cache[key] = {v: k.removeprefix("MAP_") for k, v in defs.items()}
    return _mem_cache[key]


def _hg_headers(repo):
    key = (repo, "map_headers")
    if key not in _mem_cache:
        data = _fetch_cached(repo, "src/data/map_headers.h", "map_headers.h")
        text = data.decode("utf-8") if data else ""
        defs = _defines(repo, "include/constants/maps.h", "maps.h", "MAP_")
        out = {}
        for m in re.finditer(r"\[(MAP_\w+)\]\s*=\s*\{(.*?)\n\s*\},", text, re.S):
            if m.group(1) in defs:
                out[defs[m.group(1)]] = dict(re.findall(r"\.(\w+)\s*=\s*([^,\n]+),", m.group(2)))
        _mem_cache[key] = out
    return _mem_cache[key]


def _dp_headers(repo):
    key = (repo, "dp_headers")
    if key not in _mem_cache:
        data = _fetch_cached(repo, "arm9/src/map_header.c", "map_header.c")
        text = data.decode("utf-8") if data else ""
        out = {}
        for zone, m in enumerate(re.finditer(r"^\s*\{(.*)\},\s*//\s*(MAP_\w+)\s*$", text, re.M)):
            body = m.group(1)
            area = re.search(r"NARC_area_data_narc_(\d+)_bin", body)
            matrix = re.search(r"NARC_map_matrix_narc_(\d+)_bin", body)
            enc = re.search(r"ENCDATA\(NARC_d_enc_data_narc_(\d+)_bin,\s*NARC_p_enc_data_narc_(\d+)_bin\)", body)
            mapsec = re.search(r"\b(MAPSEC_\w+)", body)
            after = body[mapsec.end():].split(",") if mapsec else []
            map_type = after[3].strip() if len(after) > 3 else ""
            out[zone] = {"area": int(area.group(1)) if area else None,
                         "matrix": int(matrix.group(1)) if matrix else None,
                         "enc_dia": int(enc.group(1)) if enc else None,
                         "enc_pea": int(enc.group(2)) if enc else None,
                         "mapsec": mapsec.group(1) if mapsec else None,
                         "interior": map_type == "4"}
        _mem_cache[key] = out
    return _mem_cache[key]


def _dp_raw_encounters(data):
    land_rate = struct.unpack_from("<i", data, 0)[0]
    land = [{"level": struct.unpack_from("<b", data, 4 + 8 * i)[0],
             "species": struct.unpack_from("<i", data, 8 + 8 * i)[0]} for i in range(12)]
    ints = lambda off, n: list(struct.unpack_from(f"<{n}i", data, off))
    out = {"land_rate": land_rate, "land_encounters": land,
           "swarms": ints(100, 2), "day": ints(108, 2), "night": ints(116, 2), "radar": ints(124, 4)}
    for name, off in (("surf", 204), ("old_rod", 292), ("good_rod", 336), ("super_rod", 380)):
        out[f"{name}_rate"] = struct.unpack_from("<i", data, off)[0]
        out[f"{name}_encounters"] = [
            {"level_max": struct.unpack_from("<b", data, off + 4 + 8 * i)[0],
             "level_min": struct.unpack_from("<b", data, off + 5 + 8 * i)[0],
             "species": struct.unpack_from("<i", data, off + 8 + 8 * i)[0]} for i in range(5)]
    return out


def zone_header(game_key, zone_id):
    g = GAMES[game_key]
    if g["kind"] in ("hgss", "dp"):
        return _hg_map_names(g["repo"]).get(zone_id)
    headers = _lines(g["repo"], "generated/map_headers.txt", "map_headers.txt")
    if not 0 <= zone_id < len(headers):
        return None
    return headers[zone_id].removeprefix("MAP_HEADER_")


def display_name(header):
    return " ".join(w if any(c.isdigit() for c in w) and w[-1].isalpha() and w[0].isdigit() else w.capitalize()
                    for w in header.split("_"))


def _species_id(game_key, name):
    if isinstance(name, int):
        return name if 0 < name <= 493 else 0
    g = GAMES[game_key]
    if g["kind"] in ("hgss", "dp"):
        return _defines(g["repo"], "include/constants/species.h", "species.h", "SPECIES_").get(name, 0)
    species = _lines(g["repo"], "generated/species.txt", "species.txt")
    try:
        return species.index(name)
    except ValueError:
        return 0


def _raw_encounters(game_key, zone_id, header, scan_dirs=()):
    g = GAMES[game_key]
    if g["kind"] == "dp":
        idx = _dp_headers(g["repo"]).get(zone_id, {}).get("enc_" + g["version"])
        rom = _load_rom(game_key, scan_dirs) if idx is not None else None
        if rom is None or idx >= len(rom["enc"]):
            return None
        return _dp_raw_encounters(rom["enc"][idx])
    if g["kind"] == "hgss":
        bank = _hg_headers(g["repo"]).get(zone_id, {}).get("wildEncounterBank", "ENCDATA_NA")
        if not bank.startswith("ENCDATA_") or bank == "ENCDATA_NA":
            return None
        key = (g["repo"], "enc_by_map")
        if key not in _mem_cache:
            data = _fetch_cached(g["repo"], "files/fielddata/encountdata/gs_enc_data.json", "gs_enc_data.json")
            entries = json.loads(data)["encounters"] if data else []
            _mem_cache[key] = {e["map"]: (i, e) for i, e in enumerate(entries)}
        idx, entry = _mem_cache[key].get(bank.removeprefix("ENCDATA_"), (None, None))
        rom = _load_rom(game_key, scan_dirs) if idx is not None else None
        if rom and idx < len(rom.get("enc", [])) and len(rom["enc"][idx]) >= 196:
            return _hg_raw_encounters(rom["enc"][idx])
        return entry
    rom = _load_rom(game_key, scan_dirs)
    ids = rom.get("pt_enc_ids") if rom else None
    if ids and 0 <= zone_id < len(ids):
        eid = ids[zone_id]
        if eid == 0xFFFF:
            return None
        if eid < len(rom["enc"]) and len(rom["enc"][eid]) >= 424:
            return _dp_raw_encounters(rom["enc"][eid])
    folder = header.lower()
    data = _fetch_cached(g["repo"], f"res/field/maps/{folder}/encounters.json", f"encounters/{folder}.json")
    return json.loads(data) if data else None


def _slots(game_key, entries, rates):
    out = []
    for e, rate in zip(entries, rates):
        sid = _species_id(game_key, e["species"])
        if sid <= 0:
            continue
        lo = e.get("level_min", e.get("level"))
        hi = e.get("level_max", e.get("level"))
        if not lo:
            continue
        out.append({"species": sid, "minLevel": lo, "maxLevel": hi, "rate": rate})
    return out


def _hg_value(v, version):
    return v.get(version, v) if isinstance(v, dict) and version in v else v


def _hg_entries(mons, version, tod=None):
    out = []
    for mon in mons:
        sp = _hg_value(mon["species"], version)
        if isinstance(sp, dict):
            sp = _hg_value(sp[{"morning": "morn", "night": "nite"}.get(tod, "day")], version)
        lvl = _hg_value(mon["level"], version)
        if isinstance(lvl, dict):
            lo, hi = _hg_value(lvl["min"], version), _hg_value(lvl["max"], version)
        else:
            lo = hi = lvl
        out.append({"species": sp, "level_min": lo, "level_max": hi})
    return out


def build_encounters(game_key, raw, hour):
    if not raw:
        return None
    g = GAMES[game_key]
    tod = time_of_day(hour)
    out = {}
    if g["kind"] == "hgss":
        v = g["version"]
        if raw.get("land", {}).get("rate"):
            out["land"] = _slots(game_key, _hg_entries(raw["land"]["mons"], v, tod), HG_LAND_RATES)
        if raw.get("surf", {}).get("rate"):
            out["water"] = _slots(game_key, _hg_entries(raw["surf"]["mons"], v), HG_SURF_RATES)
        if raw.get("rock_smash", {}).get("rate"):
            out["rockSmash"] = _slots(game_key, _hg_entries(raw["rock_smash"]["mons"], v), HG_ROCK_SMASH_RATES)
        for key, cat in (("old_rod", "oldRod"), ("good_rod", "goodRod"), ("super_rod", "superRod")):
            rod = raw.get("fishing", {}).get(key, {})
            if rod.get("rate"):
                out[cat] = _slots(game_key, _hg_entries(rod["mons"], v), HG_ROD_RATES)
    else:
        if raw.get("land_rate"):
            land = [dict(e) for e in raw.get("land_encounters", [])]
            repl = raw.get("day") if tod in ("day", "twilight") else raw.get("night") if tod == "night" else None
            if repl and len(land) >= 4:
                land[2]["species"], land[3]["species"] = repl[0], repl[1]
            out["land"] = _slots(game_key, land, PT_LAND_RATES)
        if raw.get("surf_rate"):
            out["water"] = _slots(game_key, raw.get("surf_encounters", []), PT_SURF_RATES)
        for key, cat, rates in (("old_rod", "oldRod", PT_OLD_ROD_RATES), ("good_rod", "goodRod", PT_GOOD_SUPER_ROD_RATES),
                                ("super_rod", "superRod", PT_GOOD_SUPER_ROD_RATES)):
            if raw.get(f"{key}_rate"):
                out[cat] = _slots(game_key, raw.get(f"{key}_encounters", []), rates)
    out = {k: v for k, v in out.items() if v}
    return out or None


TILE_PX = 16
RENDER_VERSION = "3d3"
_ROM_PATHS = {k: None for k in GAMES}
_rom_data = {}


def set_rom_path(game_key, path):
    if _ROM_PATHS.get(game_key) != path:
        _rom_data.pop(game_key, None)
    _ROM_PATHS[game_key] = path


def _rom_title(path):
    try:
        with open(path, "rb") as f:
            return f.read(12).split(b"\0")[0].rstrip(b" ").decode("latin-1")
    except OSError:
        return None


def _find_rom(game_key, scan_dirs):
    path = _ROM_PATHS.get(game_key)
    if path and _rom_title(path) == game_key:
        return path
    for d in scan_dirs:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            p = os.path.join(d, n)
            if n.lower().endswith(".nds") and _rom_title(p) == game_key:
                return p
    return None


def _narc_files(data):
    p = struct.unpack_from("<H", data, 0xC)[0]
    if data[:4] != b"NARC" or data[p:p + 4] != b"BTAF":
        raise ValueError("NARC invalide")
    btaf_size, count = struct.unpack_from("<IH", data, p + 4)
    entries = [struct.unpack_from("<II", data, p + 12 + 8 * i) for i in range(count)]
    p += btaf_size
    p += struct.unpack_from("<I", data, p + 4)[0]
    if data[p:p + 4] != b"GMIF":
        raise ValueError("NARC invalide")
    base = p + 8
    return [data[base + s: base + e] for s, e in entries]


def _rom_file(rom, path):
    fnt_off, _, fat_off, _ = struct.unpack_from("<IIII", rom, 0x40)
    d = 0xF000
    parts = path.split("/")
    for i, part in enumerate(parts):
        sub_off, fid, _ = struct.unpack_from("<IHH", rom, fnt_off + 8 * (d & 0xFFF))
        p = fnt_off + sub_off
        found = None
        while rom[p]:
            b = rom[p]
            n = b & 0x7F
            name = rom[p + 1:p + 1 + n].decode("latin-1")
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
            s, e = struct.unpack_from("<II", rom, fat_off + 8 * found)
            return rom[s:e]
        d = found


def _parse_matrix(m):
    w, h, has_hdr, has_alt, nlen = m[0], m[1], m[2], m[3], m[4]
    p = 5 + nlen
    hdrs = None
    if has_hdr:
        hdrs = struct.unpack_from(f"<{w * h}H", m, p)
        p += 2 * w * h
    if has_alt:
        p += w * h
    lands = struct.unpack_from(f"<{w * h}H", m, p)
    return w, h, hdrs, lands


def _load_rom(game_key, scan_dirs):
    if game_key in _rom_data:
        return _rom_data[game_key]
    path = _find_rom(game_key, scan_dirs)
    if path is None:
        return None
    with open(path, "rb") as f:
        rom = f.read()
    raw = {k: _rom_file(rom, p) for k, p in GAMES[game_key]["narcs"].items()}
    sha = hashlib.sha1()
    for k in sorted(raw):
        if k == "enc" and GAMES[game_key]["kind"] != "dp":
            continue
        sha.update(raw[k])
    data = {k: _narc_files(v) for k, v in raw.items()}
    data["key"] = sha.hexdigest()[:10]
    data["models"], data["texsets"] = {}, {}
    data["lang"] = "fr" if rom[0x0F:0x10] == b"F" else "en"
    try:
        names_path, names_bank = GAMES[game_key]["names"]
        data["location_names"] = _decode_messages(GAMES[game_key]["repo"], _narc_files(_rom_file(rom, names_path))[names_bank])
    except Exception:
        data["location_names"] = []
    if GAMES[game_key]["kind"] == "pt":
        data["pt_enc_ids"] = _pt_encounter_ids(rom, len(data["enc"]))
    _rom_data[game_key] = data
    return data


def _pt_encounter_ids(rom, n_enc):
    try:
        import nds_rebuild
        a9 = nds_rebuild.arm9_read(rom)[0]
        headers = _lines("pokeplatinum", "generated/map_headers.txt", "map_headers.txt")
        known = []
        for z in range(min(40, len(headers))):
            a = (_zone_header_json("POKEMON PL", z) or {}).get("areaData", "")
            if a.startswith("area_data_"):
                known.append((z, int(a.rsplit("_", 1)[1])))
        if len(known) < 20:
            return None
        n = len(headers)
        z0, a0 = known[0]
        for off in range(0, len(a9) - 24 * n):
            if a9[off + 24 * z0] == a0 and all(a9[off + 24 * z] == a for z, a in known):
                ids = [struct.unpack_from("<H", a9, off + 24 * z + 14)[0] for z in range(n)]
                if all(i == 0xFFFF or i < n_enc for i in ids):
                    return ids
    except Exception:
        pass
    return None


def _hg_raw_encounters(d):
    lv = list(d[8:20])
    morn, day, nite = (struct.unpack_from("<12H", d, o) for o in (20, 44, 68))
    land = [{"level": lv[i], "species": {"morn": morn[i], "day": day[i], "nite": nite[i]}} for i in range(12)]

    def pairs(o, n):
        return [{"level": {"min": d[o + 4 * i], "max": d[o + 4 * i + 1]},
                 "species": struct.unpack_from("<H", d, o + 4 * i + 2)[0]} for i in range(n)]
    return {"land": {"rate": d[0], "mons": land}, "surf": {"rate": d[1], "mons": pairs(100, 5)},
            "rock_smash": {"rate": d[2], "mons": pairs(120, 2)},
            "fishing": {"old_rod": {"rate": d[3], "mons": pairs(128, 5)}, "good_rod": {"rate": d[4], "mons": pairs(148, 5)},
                        "super_rod": {"rate": d[5], "mons": pairs(168, 5)}}}


def _charmap():
    key = ("pokeplatinum", "charmap")
    if key not in _mem_cache:
        data = _fetch_cached("pokeplatinum", "tools/msgenc/charmap.txt", "charmap.txt")
        cm = {}
        for line in (data.decode("utf-8") if data else "").splitlines():
            m = re.match(r"^\s*([0-9A-Fa-f]{4})=(.*)$", line)
            if m:
                cm[int(m.group(1), 16)] = m.group(2)
        _mem_cache[key] = cm
    return _mem_cache[key]


def _decode_messages(repo, data):
    cm = _charmap()
    count, key = struct.unpack_from("<HH", data, 0)
    out = []
    for i in range(1, count + 1):
        ak = (765 * i * key) & 0xFFFF
        ak |= ak << 16
        off, ln = struct.unpack_from("<II", data, 4 + 8 * (i - 1))
        off ^= ak
        ln ^= ak
        ck = (i * 596947) & 0xFFFF
        chars = []
        for j in range(ln):
            c = struct.unpack_from("<H", data, off + 2 * j)[0] ^ ck
            ck = (ck + 18749) & 0xFFFF
            if c == 0xFFFF:
                break
            ch = cm.get(c, "")
            chars.append("" if ch.startswith("{") else ch)
        out.append("".join(chars).strip())
    return out


def _zone_location(game_key, zone_id):
    g = GAMES[game_key]
    repo = g["repo"]
    if g["kind"] == "pt":
        hj = _zone_header_json(game_key, zone_id) or {}
        key = (repo, "location_ids")
        if key not in _mem_cache:
            raw = _fetch_cached(repo, "res/text/location_names.json", "location_names.json")
            _mem_cache[key] = [m["id"] for m in json.loads(raw)["messages"]] if raw else []
        ids = _mem_cache[key]
        idx = ids.index(hj["locationName"]) if hj.get("locationName") in ids else None
        return idx, hj.get("mapType") == "MAP_TYPE_INDOORS", hj.get("locationName", "")
    if g["kind"] == "dp":
        h = _dp_headers(repo).get(zone_id, {})
        mapsec, interior = h.get("mapsec"), h.get("interior", False)
    else:
        h = _hg_headers(repo).get(zone_id, {})
        mapsec, interior = h.get("mapsec", "").strip(), h.get("mapType", "").strip() == "MAP_TYPE_INTERIOR"
    secs = _defines(repo, "include/constants/map_sections.h", "map_sections.h", "MAPSEC_")
    return secs.get(mapsec), interior, mapsec or ""


def zone_display_name(game_key, zone_id, header, scan_dirs=()):
    try:
        idx, interior, loc_id = _zone_location(game_key, zone_id)
        rom = _load_rom(game_key, scan_dirs)
        names = rom["location_names"] if rom else []
        if idx is not None and 0 <= idx < len(names) and names[idx]:
            if not interior:
                return names[idx]
            label, floor = building_label(header, rom.get("lang", "en"))
            is_place = re.search(r"City|Town|Route|League|Area|Island|Lakefront|Village|Resort|Plateau"
                                 r"|CITY|TOWN|ROUTE|LEAGUE|AREA|ISLAND|LAKEFRONT|VILLAGE|RESORT|PLATEAU", loc_id)
            if not is_place or label.lower() in names[idx].lower():
                return f"{names[idx]} · {floor}" if floor else names[idx]
            return f"{names[idx]} · {label}" + (f" ({floor})" if floor else "")
    except Exception:
        pass
    return display_name(header)


def _zone_header_json(game_key, zone_id):
    header = zone_header(game_key, zone_id)
    if header is None:
        return None
    folder = header.lower()
    repo = GAMES[game_key]["repo"]
    raw = _fetch_cached(repo, f"res/field/maps/{folder}/header.json", f"headers/{folder}.json")
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def _zone_area_id(game_key, zone_id):
    g = GAMES[game_key]
    if g["kind"] == "dp":
        return _dp_headers(g["repo"]).get(zone_id, {}).get("area")
    if g["kind"] == "hgss":
        try:
            return int(_hg_headers(g["repo"])[zone_id]["areaDataBank"], 0)
        except (KeyError, ValueError):
            return None
    hj = _zone_header_json(game_key, zone_id)
    try:
        return int(hj["areaData"].rsplit("_", 1)[1])
    except (TypeError, KeyError, ValueError):
        return None


def _zone_matrix_id(game_key, zone_id):
    g = GAMES[game_key]
    repo = g["repo"]
    if g["kind"] == "dp":
        return _dp_headers(repo).get(zone_id, {}).get("matrix")
    if g["kind"] == "hgss":
        m = re.search(r"map_matrix_(\d{4})", _hg_headers(repo).get(zone_id, {}).get("matrixId", ""))
        return int(m.group(1)) if m else None
    hj = _zone_header_json(game_key, zone_id)
    if not hj or "mapGroup" not in hj:
        return None
    key = (repo, "groups")
    if key not in _mem_cache:
        raw = _fetch_cached(repo, "res/field/maps/groups.json", "groups.json")
        _mem_cache[key] = {gr["id"]: i for i, gr in enumerate(json.loads(raw))} if raw else {}
    return _mem_cache[key].get(hj["mapGroup"])


def _texset(rom, kind, idx):
    import nitro3d
    key = (kind, idx)
    if key not in rom["texsets"]:
        try:
            rom["texsets"][key] = nitro3d.TexSet(rom[kind][idx])
        except Exception:
            rom["texsets"][key] = None
    return rom["texsets"][key]


def _draw_model(canvas, zbuf, model, texsets, to_px, height=lambda y: y):
    import nitro3d
    for mi, si in model.draws:
        mat = model.materials[mi]
        da = mat["difAmb"]
        diffuse = [((da >> s) & 31) * 255 // 31 for s in (0, 5, 10)]
        tex = None
        if mat["tex"]:
            for ts in texsets:
                if ts is not None and mat["tex"] in ts.textures:
                    tex = ts.decode(mat["tex"], mat["pltt"])
                    break
        tris = nitro3d.run_display_list(model.shapes[si]["dl"])
        tris = [tuple(((v[0][0], height(v[0][1]), v[0][2]), v[1], v[2]) for v in t) for t in tris]
        nitro3d.render_top(canvas, zbuf, tris, tex, mat["texParam"], diffuse, to_px)


def _land_base(game_key, blk):
    if GAMES[game_key]["kind"] == "hgss" and struct.unpack_from("<H", blk, 0x10)[0] == 0x1234:
        return 0x14 + struct.unpack_from("<H", blk, 0x12)[0]
    return 0x10


def _render_zone(rom, game_key, cells_box, w, hdrs, lands, zone_id, out):
    import numpy as np
    import nitro3d
    x0, x1, z0, z1 = cells_box
    tw, th = (x1 - x0 + 1) * 32, (z1 - z0 + 1) * 32
    canvas = np.zeros((th * TILE_PX, tw * TILE_PX, 3), float)
    zbuf = np.full((th * TILE_PX, tw * TILE_PX), -1e9)
    area_cache = {}
    for cz in range(z0, z1 + 1):
        for cx in range(x0, x1 + 1):
            i = cz * w + cx
            lid = lands[i]
            if lid == 0xFFFF or lid >= len(rom["land"]):
                continue
            cell_zone = hdrs[i] if hdrs else zone_id
            if cell_zone not in area_cache:
                area_cache[cell_zone] = _zone_area_id(game_key, cell_zone)
            area_id = area_cache[cell_zone]
            if area_id is None or area_id >= len(rom["area"]):
                continue
            prop_set, tex_set = struct.unpack_from("<2H", rom["area"][area_id])
            builds = "build"
            if "build_room" in rom and rom["area"][area_id][6] == 0:
                builds = "build_room"
            map_tex = _texset(rom, "map_tex", tex_set)
            prop_tex = _texset(rom, "build_tex", prop_set)
            blk = rom["land"][lid]
            sa, sp, sm, _sb = struct.unpack_from("<4I", blk, 0)
            base = _land_base(game_key, blk)
            ccx, ccz = ((cx - x0) * 32 + 16) * 16, ((cz - z0) * 32 + 16) * 16
            m = nitro3d.Model(blk[base + sa + sp: base + sa + sp + sm])
            _draw_model(canvas, zbuf, m, [map_tex],
                        lambda x, z, m=m, ccx=ccx, ccz=ccz: ((x * m.pos_scale + ccx) / 16 * TILE_PX,
                                                            (z * m.pos_scale + ccz) / 16 * TILE_PX))
            for k in range(sp // 0x30):
                mid, px_, py_, pz_, _rx, _ry, _rz, sx, sy, sz = struct.unpack_from("<10i", blk, base + sa + 0x30 * k)
                if not 0 <= mid < len(rom[builds]):
                    continue
                if (builds, mid) not in rom["models"]:
                    try:
                        pm = nitro3d.Model(rom[builds][mid])
                    except Exception:
                        pm = None
                    try:
                        own = nitro3d.TexSet(rom[builds][mid])
                    except Exception:
                        own = None
                    rom["models"][(builds, mid)] = (pm, own)
                pm, own_tex = rom["models"][(builds, mid)]
                if pm is None:
                    continue
                sxf, syf, szf = sx / 4096, sy / 4096, sz / 4096
                _draw_model(canvas, zbuf, pm, [prop_tex, own_tex],
                            lambda x, z, pm=pm, px_=px_, pz_=pz_, sxf=sxf, szf=szf, ccx=ccx, ccz=ccz: (
                                (x * pm.pos_scale * sxf + px_ / 4096 + ccx) / 16 * TILE_PX,
                                (z * pm.pos_scale * szf + pz_ / 4096 + ccz) / 16 * TILE_PX),
                            height=lambda y, pm=pm, syf=syf, py_=py_: y * pm.pos_scale * syf + py_ / 4096)
            if cell_zone != zone_id:
                ys, xs = (cz - z0) * 32 * TILE_PX, (cx - x0) * 32 * TILE_PX
                canvas[ys:ys + 32 * TILE_PX, xs:xs + 32 * TILE_PX] *= 0.45
    drawn_rows = np.where((zbuf > -1e8).any(1))[0]
    drawn_cols = np.where((zbuf > -1e8).any(0))[0]
    crop = [0, 0, tw, th]
    if len(drawn_rows) and len(drawn_cols):
        cx0, cx1 = drawn_cols[0] // TILE_PX, drawn_cols[-1] // TILE_PX + 1
        cy0, cy1 = drawn_rows[0] // TILE_PX, drawn_rows[-1] // TILE_PX + 1
        crop = [int(cx0), int(cy0), int(cx1 - cx0), int(cy1 - cy0)]
        canvas = canvas[cy0 * TILE_PX:cy1 * TILE_PX, cx0 * TILE_PX:cx1 * TILE_PX]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp.png"
    Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8)).save(tmp)
    with open(out + ".json", "w", encoding="utf-8") as f:
        json.dump({"crop": crop}, f)
    os.replace(tmp, out)


def zone_plan(game_key, zone_id, scan_dirs, progress=None):
    if Image is None:
        return None
    rom = _load_rom(game_key, scan_dirs)
    if rom is None:
        return None
    repo = GAMES[game_key]["repo"]
    mid = _zone_matrix_id(game_key, zone_id)
    if mid is None or mid >= len(rom["matrix"]):
        return None
    w, h, hdrs, lands = _parse_matrix(rom["matrix"][mid])
    cells = [(i % w, i // w) for i in range(w * h)
             if (hdrs is None or hdrs[i] == zone_id) and lands[i] != 0xFFFF]
    if not cells:
        return None
    x0, x1 = min(c[0] for c in cells), max(c[0] for c in cells)
    z0, z1 = min(c[1] for c in cells), max(c[1] for c in cells)
    out = os.path.join(_cache_dir(repo), "images", f"{rom['key']}_{RENDER_VERSION}_zone_{zone_id}.png")
    if not os.path.exists(out):
        if progress:
            progress(f"[Carte DS] rendu 3D de la zone {zone_id} ({len(cells)} bloc(s))")
        _render_zone(rom, game_key, (x0, x1, z0, z1), w, hdrs, lands, zone_id, out)
    try:
        with open(out + ".json", encoding="utf-8") as f:
            cx, cy, cw, ch = json.load(f)["crop"]
    except (OSError, ValueError, KeyError):
        cx, cy, cw, ch = 0, 0, (x1 - x0 + 1) * 32, (z1 - z0 + 1) * 32
    rel = os.path.relpath(out, _BASE_DIR).replace(os.sep, "/")
    return "/" + rel, cw, ch, x0 * 32 + cx, z0 * 32 + cy


def get_zone_bundle(game_key, zone_id, progress=None, scan_dirs=()):
    if game_key not in GAMES:
        return None
    header = zone_header(game_key, zone_id)
    if header is None:
        return None
    if progress:
        progress(f"[Carte DS] zone {zone_id} = {header}")
    bundle = {
        "name": header,
        "displayName": zone_display_name(game_key, zone_id, header, scan_dirs),
        "image": None,
        "width": None,
        "height": None,
        "gen4Game": game_key,
        "gen4Raw": _raw_encounters(game_key, zone_id, header, scan_dirs),
    }
    try:
        plan = zone_plan(game_key, zone_id, scan_dirs, progress)
    except Exception as e:
        plan = None
        if progress:
            progress(f"[Carte DS] plan indisponible : {e}")
    if plan:
        bundle["image"], bundle["width"], bundle["height"], bundle["originX"], bundle["originY"] = plan
    return bundle
