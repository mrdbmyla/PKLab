import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ctr_rom

DATA = "C:/pkmn/data"
LAST = {"SM": 802, "USUM": 807}
MOVES = {"SM": 719, "USUM": 728}


def read(rom_path, *names):
    fs = ctr_rom.RomFS(rom_path)
    try:
        return [ctr_rom.garc(fs.read(n)) for n in names]
    finally:
        fs.close()


def personal(files, last):
    blob = files[-1]
    out = {}
    for nat in range(1, last + 1):
        p = blob[0x54 * nat:0x54 * (nat + 1)]
        out[nat] = list(p[0:6]) + [p[0x15], p[0x12], p[0x14], p[0x18], p[0x19], p[0x1A]]
    return out


def move_pp(files, last):
    mini = files[0]
    count = struct.unpack_from("<H", mini, 2)[0]
    offs = struct.unpack_from(f"<{count + 1}I", mini, 4)
    return {str(m): mini[offs[m] + 5] for m in range(1, min(last, count - 1) + 1)}


def pockets(files, names):
    out = {}
    for i, d in enumerate(files):
        if i and str(i) in names and len(d) >= 0x0A:
            code = struct.unpack_from("<H", d, 8)[0] >> 7 & 0xF
            if code <= 6:
                out[str(i)] = code
    return out


if __name__ == "__main__":
    rom_sm, rom_usum = sys.argv[1], sys.argv[2]
    base = json.load(open(os.path.join(DATA, "base_stats.json"), encoding="utf-8"))
    pp = json.load(open(os.path.join(DATA, "move_pp.json"), encoding="utf-8"))
    ip = json.load(open(os.path.join(DATA, "item_pockets.json"), encoding="utf-8"))
    for fam, rom, vg in (("SM", rom_sm, 17), ("USUM", rom_usum, 18)):
        pers, mv, items = read(rom, "a/0/1/7", "a/0/1/1", "a/0/1/9")
        names = json.load(open(os.path.join(DATA, "fiche", f"vg_{vg}.json"), encoding="utf-8"))["items"]
        ip[fam] = pockets(items, names)
        if fam == "USUM":
            base["7"] = {str(k): v for k, v in personal(pers, LAST[fam]).items()}
            pp["7"] = move_pp(mv, MOVES[fam])
    json.dump(base, open(os.path.join(DATA, "base_stats.json"), "w", encoding="utf-8"), separators=(",", ":"))
    json.dump(pp, open(os.path.join(DATA, "move_pp.json"), "w", encoding="utf-8"), separators=(",", ":"))
    json.dump(ip, open(os.path.join(DATA, "item_pockets.json"), "w", encoding="utf-8"), separators=(",", ":"))
    print(base["7"]["1"], base["7"]["745"], base["7"]["807"], pp["7"]["33"], pp["7"]["728"], len(ip["SM"]), len(ip["USUM"]),
          {c: sum(1 for v in ip["USUM"].values() if v == c) for c in range(7)})
