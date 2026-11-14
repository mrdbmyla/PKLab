import struct

from pokedata import SPECIES, ABILITIES, NATURES, HACK_SPECIES_OVERRIDE, EFF

TYPE_NAMES = [
    "Normal", "Combat", "Vol", "Poison", "Sol", "Roche", "Insecte", "Spectre",
    "Acier", "Feu", "Eau", "Plante", "Electrik", "Psy", "Glace", "Dragon", "Tenebres", "Fee",
]

MULT_I = 0x41C64E6D
ADD_I = 0x6073
MASK32 = 0xFFFFFFFF

GROWTH_SHIFT = [1,1,1,1,1,1, 2,2,3,4,3,4, 2,2,3,4,3,4, 2,2,3,4,3,4]
ATTACK_SHIFT = [2,2,3,4,3,4, 1,1,1,1,1,1, 3,4,2,2,4,3, 3,4,2,2,4,3]


TYPE_OVERRIDE = {}
SHINY_THRESHOLD = 8


def get_species_data(dex, hack_mode):
    base = SPECIES.get(dex)
    if not base:
        return None
    name, t1, t2 = base
    if dex in TYPE_OVERRIDE:
        o1, o2 = TYPE_OVERRIDE[dex]
        return name, o1, o2
    if hack_mode and dex in HACK_SPECIES_OVERRIDE:
        o1, o2 = HACK_SPECIES_OVERRIDE[dex]
        return name, o1, o2
    return name, t1, t2


def eff_lookup(atk, defn, hack_mode):
    if hack_mode and defn == 9 and atk in (8, 17):
        return 100
    return EFF[atk][defn - 1]


def single_type_eff(atk, def_t1, def_t2, hack_mode):
    f1 = eff_lookup(atk, def_t1, hack_mode)
    f2 = eff_lookup(atk, def_t2, hack_mode) if def_t2 else 100
    return (f1 * f2) / 100


def compute_matchups(t1, t2, hack_mode):
    weak4, weak2, resist, immune = [], [], [], []
    type_count = 18 if hack_mode else 17
    for atk in range(1, type_count + 1):
        combined = single_type_eff(atk, t1, t2, hack_mode)
        name = TYPE_NAMES[atk - 1]
        if combined == 0:
            immune.append(name)
        elif combined == 400:
            weak4.append(name)
        elif combined == 200:
            weak2.append(name)
        elif combined < 100:
            resist.append(name)
    return weak4, weak2, resist, immune


def threat_level(opp_t1, opp_t2, p_t1, p_t2, hack_mode):
    worst = single_type_eff(opp_t1, p_t1, p_t2, hack_mode)
    worst_type = opp_t1
    if opp_t2:
        e2 = single_type_eff(opp_t2, p_t1, p_t2, hack_mode)
        if e2 > worst:
            worst, worst_type = e2, opp_t2
    return worst, worst_type


def compute_threats(opp_t1, opp_t2, player_entries, hack_mode):
    threat4, threat2 = [], []
    for pe in player_entries:
        worst, worst_type = threat_level(opp_t1, opp_t2, pe["t1"], pe["t2"], hack_mode)
        label = f'{pe["name"]} ({TYPE_NAMES[worst_type - 1]})'
        if worst == 400:
            threat4.append(label)
        elif worst == 200:
            threat2.append(label)
    return threat4, threat2


def decode_pokemon(mem, nds_addr, gen=5):
    raw = mem.read_bytes(nds_addr, 0x94)
    pid, checksum = struct.unpack_from("<I2xH", raw, 0)
    if pid == 0:
        return None
    shift = ((pid & 0x3E000) >> 0xD) % 24
    offset_a = (GROWTH_SHIFT[shift] - 1) * 32
    offset_b = (ATTACK_SHIFT[shift] - 2) * 32
    species_offset = 0x08 + offset_a
    want = {species_offset: "species", species_offset + 4: "tid", species_offset + 6: "sid",
            0x38 + offset_b: "iv_low", 0x3A + offset_b: "iv_high", 0x40 + offset_b: "nature_word"}
    last = max(want)
    words = struct.unpack_from(f"<{(last - 6) // 2}H", raw, 0x08)
    got = {}
    prng = checksum
    for k, word in enumerate(words):
        prng = (prng * MULT_I + ADD_I) & MASK32
        name = want.get(0x08 + 2 * k)
        if name:
            got[name] = word ^ (prng >> 16)
    species, tid, sid = got.get("species"), got.get("tid"), got.get("sid")
    iv_low, iv_high, nature_word = got.get("iv_low"), got.get("iv_high"), got.get("nature_word")

    if species is None or not (1 <= species <= 649):
        return None

    shiny = (tid is not None and sid is not None
              and ((tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF)) < SHINY_THRESHOLD))

    ability = None
    ab = ABILITIES.get(species)
    if ab:
        a1, a2, _hidden = ab
        ability = a2 if (a2 and (pid % 2 == 1)) else a1

    if gen == 4:
        nature = NATURES.get((pid % 25) + 1)
    else:
        nature = NATURES.get(((nature_word >> 8) & 0xFF) + 1) if nature_word is not None else None

    prng = pid
    vals = []
    for word in struct.unpack_from("<5H", raw, 0x88):
        prng = (prng * MULT_I + ADD_I) & MASK32
        vals.append(word ^ (prng >> 16))
    level, hp_cur, hp_max = vals[2] % 256, vals[3], vals[4]
    if hp_max is not None and not (1 <= hp_max <= 2000):
        hp_max = None
    if level is not None and not (1 <= level <= 100):
        level = None

    ivs = None
    if iv_low is not None and iv_high is not None:
        iv_word = iv_low + iv_high * 0x10000
        hp_iv = iv_word & 0x1F
        atk_iv = (iv_word >> 5) & 0x1F
        def_iv = (iv_word >> 10) & 0x1F
        spe_iv = (iv_word >> 15) & 0x1F
        spa_iv = (iv_word >> 20) & 0x1F
        spd_iv = (iv_word >> 25) & 0x1F
        if max(hp_iv, atk_iv, def_iv, spe_iv, spa_iv, spd_iv) <= 31:
            ivs = {"hp": hp_iv, "atk": atk_iv, "def": def_iv, "spa": spa_iv, "spd": spd_iv, "spe": spe_iv}

    return {
        "species": species, "hpCur": hp_cur, "hpMax": hp_max, "level": level,
        "ability": ability, "nature": nature, "ivs": ivs,
        "pid": pid, "shiny": shiny,
    }


def serialize_mon(label, mon, hack_mode, opponent_player_entries=None):
    data = get_species_data(mon["species"], hack_mode)
    if not data:
        return None
    name, t1, t2 = data
    weak4, weak2, resist, immune = compute_matchups(t1, t2, hack_mode)

    out = {
        "label": label,
        "id": mon["species"],
        "name": name,
        "type1": TYPE_NAMES[t1 - 1],
        "type2": TYPE_NAMES[t2 - 1] if t2 else None,
        "level": mon["level"],
        "ability": mon["ability"],
        "nature": mon["nature"],
        "hpCur": mon["hpCur"],
        "hpMax": mon["hpMax"],
        "ivs": mon["ivs"],
        "pid": mon.get("pid"),
        "shiny": bool(mon.get("shiny")),
        "weak4": weak4, "weak2": weak2, "resist": resist, "immune": immune,
    }
    if opponent_player_entries is not None:
        threat4, threat2 = compute_threats(t1, t2, opponent_player_entries, hack_mode)
        out["threat4"] = threat4
        out["threat2"] = threat2
    return out
