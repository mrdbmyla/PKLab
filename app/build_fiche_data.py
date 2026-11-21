import csv
import json
import os
import sys
from collections import defaultdict

SRC = sys.argv[1]
OUT = os.environ.get("FICHE_OUT", "C:/pkmn/data/fiche")
FR = "5"
VGS = {3: 2, 4: 2, 5: 3, 6: 3, 7: 3, 8: 4, 9: 4, 10: 4, 11: 5, 14: 5, 15: 6, 16: 6, 17: 7, 18: 7}
ONLY = {int(x) for x in sys.argv[2:]}
LAST = {2: 251, 6: 721, 7: 807}
TYPE_KEYS = {13: "Electrik", 17: "Tenebres", 18: "Fee"}


def rows(name):
    with open(os.path.join(SRC, name + ".csv"), encoding="utf-8") as f:
        return list(csv.DictReader(f))


vg_order = {int(r["id"]): int(r["order"]) for r in rows("version_groups")}
type_fr = {}
for r in rows("type_names"):
    if r["local_language_id"] == FR:
        tid = int(r["type_id"])
        type_fr[tid] = TYPE_KEYS.get(tid, r["name"])
move_fr = {int(r["move_id"]): r["name"] for r in rows("move_names") if r["local_language_id"] == FR}
abil_fr = {int(r["ability_id"]): r["name"] for r in rows("ability_names") if r["local_language_id"] == FR}
species_fr = {int(r["pokemon_species_id"]): r["name"] for r in rows("pokemon_species_names") if r["local_language_id"] == FR}
moves = {int(r["id"]): r for r in rows("moves")}
changes = defaultdict(list)
for r in rows("move_changelog"):
    changes[int(r["move_id"])].append(r)
items = {int(r["id"]): r["identifier"] for r in rows("items")}
machines = defaultdict(dict)
for r in rows("machines"):
    vg = int(r["version_group_id"])
    if vg in VGS:
        ident = items.get(int(r["item_id"]), "")
        if ident.startswith("tm"):
            label = "CT" + ident[2:].zfill(2)
        elif ident.startswith("hm"):
            label = "CS" + ident[2:].zfill(2)
        else:
            continue
        machines[vg][int(r["move_id"])] = label

types_now = defaultdict(list)
for r in rows("pokemon_types"):
    types_now[int(r["pokemon_id"])].append((int(r["slot"]), int(r["type_id"])))
types_past = defaultdict(list)
for r in rows("pokemon_types_past"):
    types_past[int(r["pokemon_id"])].append((int(r["generation_id"]), int(r["slot"]), int(r["type_id"])))
abil_now = defaultdict(dict)
for r in rows("pokemon_abilities"):
    abil_now[int(r["pokemon_id"])][int(r["slot"])] = (int(r["ability_id"]), r["is_hidden"] == "1")
abil_past = defaultdict(list)
for r in rows("pokemon_abilities_past"):
    abil_past[int(r["pokemon_id"])].append(r)

learn = defaultdict(lambda: defaultdict(lambda: {"lv": [], "tm": set()}))
for r in rows("pokemon_moves"):
    vg = int(r["version_group_id"])
    pid = int(r["pokemon_id"])
    if vg not in VGS or pid > 807:
        continue
    method = r["pokemon_move_method_id"]
    mid = int(r["move_id"])
    if method == "1":
        learn[vg][pid]["lv"].append((int(r["level"] or 0), mid))
    elif method == "4":
        learn[vg][pid]["tm"].add(mid)


def move_at(mid, vg):
    m = moves[mid]
    t, power, acc = int(m["type_id"]), m["power"], m["accuracy"]
    later = sorted((c for c in changes.get(mid, []) if vg_order[int(c["changed_in_version_group_id"])] > vg_order[vg]),
                   key=lambda c: vg_order[int(c["changed_in_version_group_id"])])
    for c in reversed(later):
        if c["type_id"]:
            t = int(c["type_id"])
        if c["power"]:
            power = c["power"]
        if c["accuracy"]:
            acc = c["accuracy"]
    return [move_fr.get(mid, m["identifier"]), type_fr.get(t, "?"), int(power) if power else None, int(acc) if acc else None]


def types_at(pid, gen):
    past = [p for p in types_past.get(pid, []) if p[0] >= gen]
    if past:
        g = min(p[0] for p in past)
        return [type_fr[t] for _, s, t in sorted((p for p in past if p[0] == g), key=lambda p: p[1])]
    return [type_fr[t] for s, t in sorted(types_now[pid])]


def abilities_at(pid, gen):
    slots = dict(abil_now[pid])
    for g in sorted({int(r["generation_id"]) for r in abil_past.get(pid, []) if int(r["generation_id"]) >= gen}, reverse=True):
        for r in abil_past[pid]:
            if int(r["generation_id"]) == g:
                slot = int(r["slot"])
                if r["ability_id"]:
                    slots[slot] = (int(r["ability_id"]), r["is_hidden"] == "1")
                else:
                    slots.pop(slot, None)
    if gen < 3:
        return []
    if gen < 5:
        slots = {s: a for s, a in slots.items() if not a[1]}
    return [[abil_fr.get(a, "?"), hidden] for s, (a, hidden) in sorted(slots.items())]


item_fr = {int(r["item_id"]): r["name"] for r in rows("item_names") if r["local_language_id"] == FR}
loc_fr = {int(r["location_id"]): r["name"] for r in rows("location_names") if r["local_language_id"] == FR}
loc_region = {int(r["id"]): int(r["region_id"] or 0) for r in rows("locations")}
species_gen = {}
species_from = {}
for r in rows("pokemon_species"):
    sid = int(r["id"])
    species_gen[sid] = int(r["generation_id"])
    if r["evolves_from_species_id"]:
        species_from[sid] = int(r["evolves_from_species_id"])
VG_REGIONS = {3: {2, 1}, 4: {2, 1}, 5: {3}, 6: {3}, 7: {1}, 8: {4}, 9: {4}, 10: {2, 1}, 11: {5}, 14: {5}, 15: {6}, 16: {3}, 17: {7}, 18: {7}}
evo_rows = defaultdict(list)
for r in rows("pokemon_evolution"):
    sid = int(r["evolved_species_id"])
    if sid > 807 or r["region_id"]:
        continue
    if any(r[k] and int(r[k]) >= 10000 for k in ("required_pokemon_form_id", "evolved_pokemon_form_id")):
        continue
    evo_rows[sid].append(r)


def evo_text(r, vg):
    trig = r["evolution_trigger_id"]
    parts = []
    if trig == "2":
        if r["held_item_id"]:
            parts.append("Échange en tenant " + item_fr.get(int(r["held_item_id"]), "?"))
        elif r["trade_species_id"]:
            parts.append("Échange contre " + species_fr.get(int(r["trade_species_id"]), "?"))
        else:
            parts.append("Échange")
    elif trig == "3":
        parts.append(item_fr.get(int(r["trigger_item_id"]), "?"))
    elif trig == "4":
        return "Apparaît quand Ningale évolue (Nv. 20) s'il reste une place dans l'équipe et une Poké Ball"
    else:
        if r["minimum_level"]:
            parts.append("Nv. " + r["minimum_level"])
        if r["minimum_happiness"]:
            parts.append("Bonheur élevé + gain de niveau")
        if r["minimum_beauty"]:
            parts.append("Beauté au maximum + gain de niveau")
        if r["held_item_id"]:
            parts.append("Gain de niveau en tenant " + item_fr.get(int(r["held_item_id"]), "?"))
        if r["known_move_id"]:
            parts.append("Gain de niveau en connaissant " + move_fr.get(int(r["known_move_id"]), "?"))
        if r["party_species_id"]:
            parts.append("Gain de niveau avec " + species_fr.get(int(r["party_species_id"]), "?") + " dans l'équipe")
        if r["location_id"]:
            loc = int(r["location_id"])
            where = loc_fr.get(loc, "?")
            txt = ("Gain de niveau près de la pierre spéciale (" + where + ")") if r["near_special_rock"] == "1" \
                else ("Gain de niveau à : " + where)
            if loc_region.get(loc) not in VG_REGIONS[vg]:
                txt += " — impossible dans ce jeu"
            parts.append(txt)
        if not parts:
            parts.append("Gain de niveau")
    if r["relative_physical_stats"] != "":
        parts.append({"1": "Attaque > Défense", "-1": "Attaque < Défense", "0": "Attaque = Défense"}[r["relative_physical_stats"]])
    if r["gender_id"]:
        parts.append("femelle" if r["gender_id"] == "1" else "mâle")
    if r["time_of_day"]:
        parts.append({"day": "le jour", "night": "la nuit"}.get(r["time_of_day"], r["time_of_day"]))
    if r["percentage_chance"]:
        parts.append("selon la personnalité (aléatoire)")
    return ", ".join(parts)


def evo_methods(sid, vg):
    ok = [r for r in evo_rows.get(sid, []) if vg_order[int(r["version_group_id"])] <= vg_order[vg]]
    if not ok:
        return []
    last = max(vg_order[int(r["version_group_id"])] for r in ok)
    out = []
    for r in ok:
        if vg_order[int(r["version_group_id"])] == last:
            t = evo_text(r, vg)
            if t not in out:
                out.append(t)
    return out


os.makedirs(OUT, exist_ok=True)
for vg, gen in VGS.items():
    if ONLY and vg not in ONLY:
        continue
    used = set()
    species = {}
    last = LAST.get(gen, 649)
    for pid in range(1, last + 1):
        L = learn[vg].get(pid, {"lv": [], "tm": set()})
        lv = sorted(set(L["lv"]))
        tm = sorted(((machines[vg][m], m) for m in L["tm"] if m in machines[vg]), key=lambda x: (x[0][:2] == "CS", x[0]))
        used |= {m for _, m in lv} | {m for _, m in tm}
        species[pid] = {"name": species_fr.get(pid, str(pid)), "types": types_at(pid, gen),
                        "ab": abilities_at(pid, gen), "lv": [list(x) for x in lv], "tm": [list(x) for x in tm]}
        if species_gen[pid] > gen:
            continue
        pre = species_from.get(pid)
        if pre and species_gen[pre] <= gen:
            species[pid]["pre"] = pre
        evs = []
        for sid in sorted(s for s, f in species_from.items() if f == pid and s <= last and species_gen[s] <= gen):
            m = evo_methods(sid, vg)
            evs.append([sid, " ou ".join(m) if m else "Méthode inconnue"])
        if evs:
            species[pid]["ev"] = evs
    if gen >= 6:
        with open("C:/pkmn/data/base_stats.json", encoding="utf-8") as f:
            bst = json.load(f)[str(gen)]
        for pid, sp in species.items():
            v = bst.get(str(pid))
            if v:
                sp["st"] = [v[0], v[1], v[2], v[4], v[5], v[3]]
    max_move = {2: 251, 3: 354, 4: 467, 5: 559, 6: 621, 7: 728 if vg == 18 else 719}[gen]
    all_moves = sorted(used | set(range(1, max_move + 1)))
    data = {"vg": vg, "gen": gen, "moves": {m: move_at(m, vg) for m in all_moves if m in moves}, "species": species,
            "abilities": {a: n for a, n in abil_fr.items() if a <= {2: 0, 3: 76, 4: 123, 5: 164, 6: 191, 7: 233}[gen]},
            "typeNames": [type_fr[t] for t in range(1, 19 if gen >= 6 else 18)],
            "items": {int(r["game_index"]): item_fr[int(r["item_id"])] for r in rows("item_game_indices")
                      if r["generation_id"] == str(gen) and int(r["item_id"]) in item_fr}}
    with open(os.path.join(OUT, f"vg_{vg}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(vg, gen, len(used), "attaques", os.path.getsize(os.path.join(OUT, f"vg_{vg}.json")) // 1024, "Ko")
