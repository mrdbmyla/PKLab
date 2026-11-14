import csv
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen4_maps
import gen5_maps
import pokedata

SRC = sys.argv[1]
LANGS = sys.argv[2:] or ["en", "es"]
DATA = "C:/pkmn/data"
FR = "5"
LANG_ID = {"en": "9", "es": "7"}
NATURES_FR = ("Hardi Solo Brave Rigide Mauvais Assuré Docile Relax Malin Lâche Timide Pressé Sérieux Jovial Naïf "
              "Modeste Doux Discret Pudique Foufou Calme Gentil Malpoli Prudent Bizarre").split()
NATURES = {
    "en": ("Hardy Lonely Brave Adamant Naughty Bold Docile Relaxed Impish Lax Timid Hasty Serious Jolly Naive "
           "Modest Mild Quiet Bashful Rash Calm Gentle Sassy Careful Quirky").split(),
    "es": ("Fuerte Huraña Audaz Firme Pícara Osada Dócil Plácida Agitada Floja Miedosa Activa Seria Alegre Ingenua "
           "Modesta Afable Mansa Tímida Alocada Serena Amable Grosera Cauta Rara").split(),
}
E4_ES = {"AARON": "Alecrán", "BERTHA": "Gaia", "FLINT": "Fausto", "LUCIAN": "Delos", "CYNTHIA": "Cintia",
         "WILL": "Mento", "KOGA": "Koga", "BRUNO": "Bruno", "KAREN": "Karen", "LANCE": "Lance", "SIDNEY": "Sidney",
         "PHOEBE": "Fátima", "GLACIA": "Nívea", "DRAKE": "Dracón", "LORELEI": "Lorelei", "AGATHA": "Agatha"}
TIMES = {"en": ("Morning", "Day", "Twilight", "Night"), "es": ("Mañana", "Día", "Atardecer", "Noche")}
SEASONS_ES = ("Primavera", "Verano", "Otoño", "Invierno")
RULES = {"en": {"tm": "TM", "hm": "HM", "lv": "Lv"}, "es": {"tm": "MT", "hm": "MO", "lv": "Nv"}}


def rows(name):
    with open(os.path.join(SRC, name + ".csv"), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pair(name, key, lang, keep=lambda i: True):
    by = {FR: {}, "9": {}, "7": {}}
    for r in rows(name):
        i = int(r[key])
        if keep(i) and r["local_language_id"] in by and r["name"].strip():
            by[r["local_language_id"]][i] = r["name"].strip()
    tgt = {i: re.sub(r"^(Sea )?Route ", "Ruta ", n) for i, n in by["9"].items()} if lang == "es" else {}
    tgt.update(by[LANG_ID[lang]])
    return {i: (fr, tgt[i]) for i, fr in by[FR].items() if i in tgt}


def read_tsv(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            fr, tgt = line.split("\t")
            out.append((fr, tgt))
    return out


def plain(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


move_gen = {int(r["id"]): int(r["generation_id"]) for r in rows("moves")}
region = {int(r["id"]): int(r["region_id"] or 0) for r in rows("locations")}
site = open("C:/pkmn/pklab.html", encoding="utf-8").read()
fr_desc = json.loads(re.search(r"const ABILITY_DESCRIPTIONS = (\{.*?\});\n", site).group(1))
TYPE_KEYS = {13: "Electrik", 17: "Tenebres", 18: "Fee"}
TYPE_DISPLAY = {"Electrik": "Électrik", "Tenebres": "Ténèbres", "Fee": "Fée"}


def build(lang):
    cats = {
        "item": pair("item_names", "item_id", lang),
        "place": pair("location_names", "location_id", lang, lambda i: 1 <= region.get(i, 0) <= 5),
        "ability": pair("ability_names", "ability_id", lang),
        "move": pair("move_names", "move_id", lang, lambda i: move_gen.get(i, 99) <= 5),
        "species": pair("pokemon_species_names", "pokemon_species_id", lang, lambda i: i <= 649),
    }
    types = {TYPE_KEYS.get(i, fr): t for i, (fr, t) in pair("type_names", "type_id", lang, lambda i: i <= 18).items()}

    names, conflicts = {}, []
    for cat in ("item", "place", "ability", "move", "species"):
        for fr, t in cats[cat].values():
            if fr in names and names[fr] != t:
                conflicts.append((fr, names[fr], t, cat))
            names[fr] = t
    names.update(zip(NATURES_FR, NATURES[lang]))
    species_t = {i: t for i, (fr, t) in cats["species"].items()}
    for dex, (nm, *_rest) in pokedata.SPECIES.items():
        if dex in species_t:
            names.setdefault(nm, species_t[dex])

    ui = read_tsv(os.path.join(DATA, f"i18n_{lang}_ui.tsv"))
    ui_map = {fr.lstrip("~"): t for fr, t in ui}
    abil_desc = dict(read_tsv(os.path.join(DATA, f"i18n_{lang}_abilities.tsv")))
    missing = [k for k in fr_desc if k not in abil_desc]
    if missing:
        sys.exit(f"[{lang}] descriptions de talents manquantes : " + ", ".join(missing))

    exact, frag = dict(names), {}
    for k, v in fr_desc.items():
        exact[v] = abil_desc[k]
    for fr, t in types.items():
        exact.setdefault(fr, t)
    ui_words = set()
    for fr, t in ui:
        force = fr.startswith("~")
        fr = fr.lstrip("~")
        exact[fr] = t
        ui_words.update(re.findall(r"[A-Za-zÀ-ÿŒœ'’-]+", fr))
        if force or re.search(r"[^A-Za-zÀ-ÿŒœ0-9]", fr):
            frag[fr] = t
    species_fr = {fr for fr, t in cats["species"].values()} | {v[0] for v in pokedata.SPECIES.values()}
    for fr, t in names.items():
        single = not re.search(r"[ \-’']", fr)
        if (len(fr) < 4 and fr not in species_fr) or fr == t or fr in frag:
            continue
        if single and fr not in species_fr and (fr in ui_words or not fr[0].isupper()):
            continue
        frag[fr] = t
    for key, t in types.items():
        for fr in {key, TYPE_DISPLAY.get(key, key)}:
            frag[f"type {fr}"] = f"{t} type" if lang == "en" else f"tipo {t}"
            exact.setdefault(TYPE_DISPLAY.get(key, key), t)

    for _pat, fr, en in gen4_maps.BUILDING_LABELS + gen5_maps.GEN5_BUILDING_LABELS:
        if not fr or "{" in fr:
            continue
        t = en if lang == "en" else ui_map.get(fr)
        if t is None:
            sys.exit(f"[{lang}] étiquette de carte sans traduction : {fr}")
        if fr != t:
            frag.setdefault(fr, t)
            exact.setdefault(fr, t)
    for key, fr in gen4_maps._E4.items():
        t = key.title() + "'s Room" if lang == "en" else "Sala de " + E4_ES[key]
        frag["Salle d'" + fr if fr[0] in "AEIOUÉ" else "Salle de " + fr] = t
    if lang == "en":
        frag.update({"intérieur": "interior", "ascenseur": "elevator", "toit": "roof", "sous-sol": "basement",
                     "1er étage": "2F"})
        for n in range(2, 15):
            frag[f"{n}e étage"] = f"{n + 1}F"
            frag[f"sous-sol {n}"] = f"B{n}F"
        seasons = gen5_maps.SEASON_LABELS["en"]
    else:
        frag.update({"intérieur": "interior", "ascenseur": "ascensor", "toit": "azotea", "sous-sol": "sótano",
                     "1er étage": "1.ª planta"})
        for n in range(2, 15):
            frag[f"{n}e étage"] = f"{n}.ª planta"
            frag[f"sous-sol {n}"] = f"sótano {n}"
        seasons = SEASONS_ES
    for fr, t in zip(gen4_maps.TIME_OF_DAY_LABELS.values(), TIMES[lang]):
        frag[fr] = exact[fr] = t
    for fr, t in zip(gen5_maps.SEASON_LABELS["fr"], seasons):
        frag[fr] = exact[fr] = t

    for fr, t in cats["place"].values():
        t = exact.get(fr, t)
        for v in {fr, plain(fr)}:
            for form in (v, "Village " + v):
                if form != fr or v != fr:
                    exact.setdefault(form, t)
                    if len(v) >= 4:
                        frag.setdefault(form, t)

    clash = [(fr, names[fr], exact[fr]) for fr in names if exact.get(fr) != names[fr]]
    print(f"[{lang}] noms qui sont aussi un texte d'interface :", clash)
    out = {"lang": lang, "rules": RULES[lang], "exact": exact, "frag": frag, "types": types,
           "abilityDesc": abil_desc, "names": names}
    with open(os.path.join(DATA, f"i18n_{lang}.js"), "w", encoding="utf-8") as f:
        f.write(f"// Generated by app/build_i18n.py - edit data/i18n_{lang}_ui.tsv instead.\n")
        f.write(f"window.PKLAB_I18N_{lang.upper()} = "
                + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n")
    print(f"[{lang}] exact {len(exact)}, frag {len(frag)}, conflits de noms {len(conflicts)}")


for lang in LANGS:
    build(lang)
