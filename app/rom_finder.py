import ctypes
import json
import os
import threading
import time

NDS_TITLES = {"POKEMON D", "POKEMON P", "POKEMON PL", "POKEMON HG", "POKEMON SS",
              "POKEMON B", "POKEMON W", "POKEMON B2", "POKEMON W2"}
NDS_CODES = {"ADA": "POKEMON D", "APA": "POKEMON P", "CPU": "POKEMON PL", "IPK": "POKEMON HG", "IPG": "POKEMON SS",
             "IRB": "POKEMON B", "IRA": "POKEMON W", "IRE": "POKEMON B2", "IRD": "POKEMON W2"}
GBA_TITLES = {"POKEMON EMER": "EMERALD", "POKEMON FIRE": "FIRERED", "POKEMON LEAF": "LEAFGREEN",
              "POKEMON RUBY": "RUBY", "POKEMON SAPP": "SAPPHIRE"}
GBC_TITLES = {"PM_CRYSTAL": "CRYSTAL", "POKEMON_GLD": "GOLD", "POKEMON_SLV": "SILVER"}
GBA_CODES = {"BPE": "EMERALD", "BPR": "FIRERED", "BPG": "LEAFGREEN", "AXV": "RUBY", "AXP": "SAPPHIRE"}
CTR_TITLES = {0x0004000000055E00: "POKEMON Y", 0x000400000011C400: "POKEMON OR", 0x00040000001B5000: "POKEMON US", 0x0004000000164800: "POKEMON S", 0x0004000000175E00: "POKEMON M",
              0x0004000000055D00: "POKEMON X", 0x000400000011C500: "POKEMON AS", 0x00040000001B5100: "POKEMON UM"}
CTR_EXTS = {".3ds", ".cci", ".cxi"}
ROM_EXTS = {".nds", ".gba", ".gbc", ".gb", ".srl", ".dsi", ".agb", ".bin", ".rom"} | CTR_EXTS
SKIP_DIRS = {"windows", "windows.old", "program files", "program files (x86)", "programdata", "$recycle.bin",
             "system volume information", "$winreagent", "$windows.~bt", "$windows.~ws", "recovery", "perflogs",
             "config.msi", "msocache", "appdata", "node_modules", ".git", "__pycache__", "site-packages"}
MIN_SIZE = 0x40000
MAX_SIZE = 1 << 30
MAX_SIZE_CTR = 1 << 33
FULL_SCAN_MAX_AGE = 6 * 3600


def _text(b):
    return b.split(b"\0")[0].rstrip(b" ").decode("latin-1", "replace")


def identify(path):
    try:
        with open(path, "rb") as f:
            h = f.read(0x160)
    except OSError:
        return None
    if len(h) >= 0xC0 and h[0xB2] == 0x96:
        g = GBA_TITLES.get(_text(h[0xA0:0xAC])) or GBA_CODES.get(_text(h[0xAC:0xAF]))
        if g:
            return "mgba", g
    if len(h) >= 0x150 and h[0x104:0x108] == bytes([0xCE, 0xED, 0x66, 0x66]):
        g = GBC_TITLES.get(_text(h[0x134:0x13F]))
        if g:
            return "mgba", g
    if len(h) >= 0x160 and h[0x15C:0x15E] == b"\x56\xCF":
        t = _text(h[0:12])
        g = t if t in NDS_TITLES else NDS_CODES.get(_text(h[0x0C:0x0F]))
        if g:
            return "melonds", g
    if len(h) >= 0x120 and h[0x100:0x104] in (b"NCSD", b"NCCH"):
        tid = int.from_bytes(h[0x108:0x110] if h[0x100:0x104] == b"NCSD" else h[0x118:0x120], "little")
        g = CTR_TITLES.get(tid)
        if g:
            return "azahar", g
    return None


def _candidate(entry):
    ext = os.path.splitext(entry.name)[1].lower()
    if ext not in ROM_EXTS:
        return False
    try:
        st = entry.stat()
    except OSError:
        return False
    if getattr(st, "st_file_attributes", 0) & 0x441000:
        return False
    return MIN_SIZE <= st.st_size <= (MAX_SIZE_CTR if ext in CTR_EXTS else MAX_SIZE)


def _drives():
    try:
        k = ctypes.windll.kernel32
        mask = k.GetLogicalDrives()
    except Exception:
        return []
    out = []
    for i in range(26):
        if mask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            if k.GetDriveTypeW(root) in (2, 3):
                out.append(root)
    return out


def _background_thread():
    try:
        k = ctypes.windll.kernel32
        k.GetCurrentThread.restype = ctypes.c_void_p
        k.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
        k.SetThreadPriority(k.GetCurrentThread(), 0x00010000)
    except Exception:
        pass


class RomIndex:
    def __init__(self, cache_path, quick_dirs):
        self.cache_path = cache_path
        self.quick_dirs = list(quick_dirs)
        self.lock = threading.Lock()
        self.items = {}
        self.scanned_at = 0
        self.scanning = False
        self._load()

    def _load(self):
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                data = json.load(f)
            self.scanned_at = float(data.get("scannedAt", 0)) if data.get("exts") == sorted(ROM_EXTS) and data.get("ctr") == sorted(CTR_TITLES.values()) else 0
            for e in data.get("roms", []):
                self.items[os.path.normcase(e["path"])] = (e["path"], e["engine"], e["game"])
        except Exception:
            self.items, self.scanned_at = {}, 0

    def _save(self):
        with self.lock:
            roms = [{"path": p, "engine": eng, "game": g} for p, eng, g in self.items.values()]
        try:
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"scannedAt": self.scanned_at, "exts": sorted(ROM_EXTS), "ctr": sorted(CTR_TITLES.values()), "roms": roms}, f, ensure_ascii=False)
            os.replace(tmp, self.cache_path)
        except OSError:
            pass

    def _add(self, path, seen=None):
        hit = identify(path)
        key = os.path.normcase(path)
        if seen is not None:
            seen.add(key)
        with self.lock:
            if hit:
                self.items[key] = (path, hit[0], hit[1])
            else:
                self.items.pop(key, None)

    def _walk(self, root, seen, max_depth=None):
        stack = [(root, 0)]
        dirs_done = 0
        while stack:
            d, depth = stack.pop()
            try:
                it = os.scandir(d)
            except OSError:
                continue
            with it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if e.name.lower() in SKIP_DIRS or e.name.startswith("$"):
                                continue
                            if e.stat(follow_symlinks=False).st_file_attributes & 0x400:
                                continue
                            if max_depth is None or depth < max_depth:
                                stack.append((e.path, depth + 1))
                        elif _candidate(e):
                            self._add(e.path, seen)
                    except OSError:
                        continue
            dirs_done += 1
            if dirs_done % 200 == 0:
                time.sleep(0.005)

    def quick_refresh(self):
        seen = set()
        for d in self.quick_dirs:
            try:
                entries = list(os.scandir(d))
            except OSError:
                continue
            for e in entries:
                try:
                    if e.is_file() and _candidate(e):
                        key = os.path.normcase(e.path)
                        if key not in self.items:
                            self._add(e.path, seen)
                except OSError:
                    continue
        with self.lock:
            for key in [k for k, v in self.items.items() if not os.path.isfile(v[0])]:
                del self.items[key]

    def start(self, force=False):
        with self.lock:
            if self.scanning:
                return
            if not force and self.items and time.time() - self.scanned_at < FULL_SCAN_MAX_AGE:
                return
            self.scanning = True
        threading.Thread(target=self._full_scan, daemon=True).start()

    def _full_scan(self):
        _background_thread()
        seen = set()
        try:
            for d in self.quick_dirs:
                self._walk(d, seen, max_depth=4)
            for root in _drives():
                self._walk(root, seen)
            with self.lock:
                for key in [k for k in self.items if k not in seen]:
                    del self.items[key]
            self.scanned_at = time.time()
            self._save()
        finally:
            with self.lock:
                self.scanning = False

    def roms(self, engine=None):
        self.quick_refresh()
        quick = [os.path.normcase(d) + os.sep for d in self.quick_dirs]
        with self.lock:
            vals = [v for v in self.items.values() if engine is None or v[1] == engine]

        def rank(v):
            low = os.path.normcase(v[0])
            return next((i for i, q in enumerate(quick) if low.startswith(q)), len(quick)), low.count(os.sep), low

        vals.sort(key=rank)
        return [{"path": p, "engine": eng, "game": g, "modified": self._modified(p)} for p, eng, g in vals]

    @staticmethod
    def _modified(path):
        stem = os.path.splitext(path)[0]
        return any(os.path.isfile(stem + ext) for ext in (".pklab.json", ".pwh.json"))

    def dirs(self):
        with self.lock:
            extra = {os.path.dirname(v[0]) for v in self.items.values()}
        out = list(self.quick_dirs)
        out += sorted(d for d in extra if os.path.normcase(d) not in {os.path.normcase(q) for q in out})
        return out
