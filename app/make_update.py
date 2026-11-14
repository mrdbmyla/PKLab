import hashlib
import json
import os
import sys
import zipfile

import paths
from updater import ZIP_NAME, ALLOWED_FILES, allowed_path

ROOT = "C:/pkmn"
OUT_DIR = os.path.join(ROOT, "FINAL", "maj")


def resource_files():
    out = [f for f in ALLOWED_FILES if os.path.isfile(os.path.join(ROOT, f))]
    for top in ("data", "boxart"):
        for d, dirs, files in os.walk(os.path.join(ROOT, top)):
            dirs[:] = sorted(x for x in dirs if ".bak" not in x and "avant" not in x)
            for f in sorted(files):
                if ".bak" in f or "avant" in f or f.endswith(".tsv"):
                    continue
                out.append(os.path.relpath(os.path.join(d, f), ROOT).replace(os.sep, "/"))
    return out


def main():
    if len(sys.argv) != 2:
        print("Usage : python make_update.py <version>   (ex. 1.0.1)")
        return 1
    version = sys.argv[1].lstrip("vV")
    if paths.ver_tuple(version) <= paths.ver_tuple(paths.APP_VERSION):
        print(f"La version {version} doit être plus grande que celle de l'exe ({paths.APP_VERSION}).")
        return 1
    files = resource_files()
    bad = [f for f in files if not allowed_path(f)]
    if bad:
        print("Chemins refusés :", bad[:5])
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, ZIP_NAME)
    hashes = {}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            with open(os.path.join(ROOT, rel), "rb") as f:
                data = f.read()
            hashes[rel] = hashlib.sha256(data).hexdigest()
            z.writestr(rel, data)
        man = {"version": version, "min_exe": paths.APP_VERSION, "files": hashes}
        z.writestr("manifest.json", json.dumps(man, ensure_ascii=False, indent=1))
    print(f"{out} : version {version}, exe minimum {paths.APP_VERSION}, {len(files)} fichiers, "
          f"{os.path.getsize(out) // 1024} Ko")
    print(f"Tag GitHub à créer : v{version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
