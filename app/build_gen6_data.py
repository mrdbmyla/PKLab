import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ctr_rom

DATA = "C:/pkmn/data"
PERSONAL = {"XY": ("a/2/1/8", 0x40), "ORAS": ("a/1/9/5", 0x50)}
POCKET_CODE = {2: 1, 4: 2, 5: 3, 8: 4}
FIXES = {"216": 4, "504": 1, **{str(i): 1 for i in range(565, 572)}}


def personal(rom_path, fam):
    fs = ctr_rom.RomFS(rom_path)
    try:
        files = ctr_rom.garc(fs.read(PERSONAL[fam][0]))
    finally:
        fs.close()
    size = PERSONAL[fam][1]
    blob = files[-1] if len(files[-1]) > size * 700 else None
    rec = (lambda n: blob[size * n:size * (n + 1)]) if blob else (lambda n: files[n])
    out = {}
    for nat in range(1, 722):
        p = rec(nat)
        out[nat] = list(p[0:6]) + [p[0x15], p[0x12], p[0x14], p[0x18], p[0x19], p[0x1A]]
    return out


def rows(src, name):
    with open(os.path.join(src, name + ".csv"), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def move_pp(src):
    order = {int(r["id"]): int(r["order"]) for r in rows(src, "version_groups")}
    pp = {int(r["id"]): int(r["pp"] or 0) for r in rows(src, "moves") if int(r["id"]) <= 621}
    later = [r for r in rows(src, "move_changelog") if r["pp"] and order[int(r["changed_in_version_group_id"])] > order[16]]
    for r in sorted(later, key=lambda r: -order[int(r["changed_in_version_group_id"])]):
        if int(r["move_id"]) in pp:
            pp[int(r["move_id"])] = int(r["pp"])
    return {str(k): v for k, v in sorted(pp.items())}


def pockets(src):
    cat = {int(r["id"]): int(r["pocket_id"]) for r in rows(src, "item_categories")}
    item_cat = {int(r["id"]): int(r["category_id"]) for r in rows(src, "items")}
    out = {}
    for r in rows(src, "item_game_indices"):
        if r["generation_id"] == "6" and int(r["item_id"]) in item_cat:
            out[str(int(r["game_index"]))] = POCKET_CODE.get(cat.get(item_cat[int(r["item_id"])]), 0)
    out.update(FIXES)
    return out


if __name__ == "__main__":
    rom_xy, src = sys.argv[1], sys.argv[2]
    base = json.load(open(os.path.join(DATA, "base_stats.json"), encoding="utf-8"))
    base["6"] = {str(k): v for k, v in personal(rom_xy, "XY").items()}
    json.dump(base, open(os.path.join(DATA, "base_stats.json"), "w", encoding="utf-8"), separators=(",", ":"))
    pp = json.load(open(os.path.join(DATA, "move_pp.json"), encoding="utf-8"))
    pp["6"] = move_pp(src)
    json.dump(pp, open(os.path.join(DATA, "move_pp.json"), "w", encoding="utf-8"), separators=(",", ":"))
    ip = json.load(open(os.path.join(DATA, "item_pockets.json"), encoding="utf-8"))
    ip["XY"] = ip["ORAS"] = pockets(src)
    json.dump(ip, open(os.path.join(DATA, "item_pockets.json"), "w", encoding="utf-8"), separators=(",", ":"))
    print(base["6"]["1"], base["6"]["35"], base["6"]["700"], pp["6"]["33"], pp["6"]["617"], len(ip["XY"]))
