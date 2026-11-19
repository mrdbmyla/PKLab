import ctypes
import random
import socket
import struct

import osdep
from pokedata import ABILITIES, NATURES

RPC_PORT = 45987
RPC_VERSION = 2
REQ_READ, REQ_WRITE, REQ_PROCESSES = 1, 2, 3
MAX_CHUNK = 32 * 1024

GAMES = {
    0x0004000000055E00: {"key": "POKEMON Y", "party": 0x08C79DA8, "stride": 260, "stats": 0xE8,
                         "battle": (0x081F0000, 0x08220000), "money": 0x08C6A69C,
                         "pockets": {1: (0x08C67554, 400), 50: (0x08C67EBC, 64)}, "pos": (0x08C67180, 0x08C67190)},
    0x000400000011C400: {"key": "POKEMON OR", "party": 0x08CF727C, "stride": 0x1E4, "stats": 0x158,
                         "battle": (0x081F0000, 0x08220000), "money": 0x08C6DDD0,
                         "pockets": {1: (0x08C6AC80, 400), 50: (0x08C6B5F0, 64)}, "pos": (0x08C6A7B2, 0x08C6A7C0)},
    0x00040000001B5000: {"key": "POKEMON US", "party": 0x33F7FA44, "stride": 0x1E4, "stats": 0x158,
                         "battle": (0x30000000, 0x30020000), "money": 0x33015210,
                         "pockets": {1: (0x33011934, 427, 7), 50: (0x330124A8, 60, 7)}, "pos": (0x300019CC, None)},
    0x0004000000164800: {"key": "POKEMON S", "party": 0x34195E10, "stride": 0x1E4, "stats": 0x158,
                         "battle": (0x30000000, 0x30020000), "money": 0x330D8FC0,
                         "pockets": {1: (0x330D5934, 430, 7), 50: (0x330D647C, 64, 7)}, "pos": (0x3038244A, None)},
}
for _tid, _twin, _key in ((0x0004000000055D00, 0x0004000000055E00, "POKEMON X"),
                          (0x000400000011C500, 0x000400000011C400, "POKEMON AS"),
                          (0x00040000001B5100, 0x00040000001B5000, "POKEMON UM"),
                          (0x0004000000175E00, 0x0004000000164800, "POKEMON M")):
    GAMES[_tid] = dict(GAMES[_twin], key=_key)

ORDER = ["ABCD", "ABDC", "ACBD", "ACDB", "ADBC", "ADCB", "BACD", "BADC", "BCAD", "BCDA", "BDAC", "BDCA",
         "CABD", "CADB", "CBAD", "CBDA", "CDAB", "CDBA", "DABC", "DACB", "DBAC", "DBCA", "DCAB", "DCBA"]
SHINY_THRESHOLD = 16


class Rpc:
    def __init__(self, port=RPC_PORT, timeout=0.3):
        self.addr = ("127.0.0.1", port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _request(self, kind, payload, tries=2):
        for _ in range(tries):
            rid = random.getrandbits(32)
            self.sock.sendto(struct.pack("<IIII", RPC_VERSION, rid, kind, len(payload)) + payload, self.addr)
            try:
                while True:
                    reply = self.sock.recv(MAX_CHUNK + 0x10)
                    if len(reply) < 0x10:
                        continue
                    ver, got, rkind, size = struct.unpack_from("<IIII", reply)
                    if ver == RPC_VERSION and got == rid and rkind == kind and size == len(reply) - 0x10:
                        return reply[0x10:]
            except socket.timeout:
                continue
            except OSError:
                return None
        return None

    def read(self, addr, size):
        out = bytearray()
        while size > 0:
            n = min(size, MAX_CHUNK)
            data = self._request(REQ_READ, struct.pack("<II", addr, n))
            if not data:
                return None
            out += data
            addr += len(data)
            size -= len(data)
        return bytes(out)

    def write(self, addr, data):
        return self._request(REQ_WRITE, struct.pack("<II", addr, len(data)) + data) is not None

    def title_ids(self):
        data = self._request(REQ_PROCESSES, struct.pack("<II", 0, 0x7FFFFFFF))
        if not data or len(data) < 4:
            return []
        count = struct.unpack_from("<I", data)[0]
        ids = []
        for i in range(count):
            off = 4 + 0x14 * i
            if off + 0x14 > len(data):
                break
            ids.append(struct.unpack_from("<IQ", data, off)[1])
        return ids


class _MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", ctypes.c_ulong), ("PartitionId", ctypes.c_ushort),
                ("RegionSize", ctypes.c_size_t), ("State", ctypes.c_ulong),
                ("Protect", ctypes.c_ulong), ("Type", ctypes.c_ulong)]


class HostMem:
    def __init__(self, pid):
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k.OpenProcess.restype = ctypes.c_void_p
        self.k.VirtualQueryEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_MBI), ctypes.c_size_t]
        self.k.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                             ctypes.POINTER(ctypes.c_size_t)]
        self.k.WriteProcessMemory.argtypes = self.k.ReadProcessMemory.argtypes
        self.h = self.k.OpenProcess(0x0438, False, pid)
        if not self.h:
            raise OSError("processus Azahar inaccessible")

    def close(self):
        self.k.CloseHandle.argtypes = [ctypes.c_void_p]
        self.k.CloseHandle(self.h)

    def read(self, addr, size):
        buf = ctypes.create_string_buffer(size)
        n = ctypes.c_size_t()
        if not self.k.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, size, ctypes.byref(n)):
            return None
        return buf.raw[:n.value]

    def write(self, addr, data):
        n = ctypes.c_size_t()
        return bool(self.k.WriteProcessMemory(self.h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(n)))

    def find(self, needle):
        addr, mbi, hits = 0, _MBI(), []
        while self.k.VirtualQueryEx(self.h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            base, size = mbi.BaseAddress or 0, mbi.RegionSize
            if mbi.State == 0x1000 and mbi.Type == 0x20000 and mbi.Protect == 0x04:
                off = 0
                while off < size:
                    data = self.read(base + off, min(size - off, (4 << 20) + len(needle)))
                    if data:
                        i = data.find(needle)
                        while i != -1:
                            hits.append(base + off + i)
                            if len(hits) > 8:
                                return hits
                            i = data.find(needle, i + 1)
                    off += 4 << 20
            addr = base + size
            if not size or addr >= 0x7FFFFFFF0000:
                break
        return hits


def _keys(seed, count):
    out = []
    for _ in range(count):
        seed = (seed * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        out.append(seed >> 16)
    return out


def _xor(data, keys):
    words = struct.unpack(f"<{len(data) // 2}H", data)
    return struct.pack(f"<{len(words)}H", *(w ^ k for w, k in zip(words, keys)))


def decrypt_pk6(raw):
    ec = struct.unpack_from("<I", raw)[0]
    body = _xor(raw[8:232], _keys(ec, 112))
    order = ORDER[((ec >> 13) & 31) % 24]
    blocks = [body[56 * i:56 * (i + 1)] for i in range(4)]
    return raw[:8] + b"".join(blocks[order.index(c)] for c in "ABCD")


def checksum_ok(pk):
    return sum(struct.unpack_from("<112H", pk, 8)) & 0xFFFF == struct.unpack_from("<H", pk, 6)[0]


def decode_mon(raw, stats_off):
    ec = struct.unpack_from("<I", raw)[0]
    if not any(raw[:232]):
        return None
    pk = decrypt_pk6(raw[:232])
    if not checksum_ok(pk):
        return None
    species = struct.unpack_from("<H", pk, 0x08)[0]
    if not 1 <= species <= 807:
        return None
    stats = _xor(raw[stats_off:stats_off + 28], _keys(ec, 14))
    level, hp_cur, hp_max = stats[4], *struct.unpack_from("<HH", stats, 8)
    if not (1 <= level <= 100 and 1 <= hp_max <= 999 and hp_cur <= hp_max):
        return None
    tid, sid = struct.unpack_from("<HH", pk, 0x0C)
    pid = struct.unpack_from("<I", pk, 0x18)[0]
    ab_num = pk[0x15]
    a1, a2, hidden = ABILITIES.get(species, (None, None, None))
    ability = {1: a1, 2: a2 or a1, 4: hidden or a1}.get(ab_num, a1)
    iv = struct.unpack_from("<I", pk, 0x74)[0]
    ivs = {k: (iv >> (5 * i)) & 31 for i, k in enumerate(("hp", "atk", "def", "spe", "spa", "spd"))}
    return {
        "species": species, "form": pk[0x1D] >> 3, "hpCur": hp_cur, "hpMax": hp_max, "level": level,
        "ability": ability, "nature": NATURES.get(pk[0x1C] + 1), "ivs": ivs, "pid": pid,
        "shiny": (tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF)) < SHINY_THRESHOLD,
    }


BATTLE_PK_STATS = 0x158
MAX_MONEY = 9999999
ITEM_CAP = 999


class AzaharReader:
    def __init__(self, port=RPC_PORT, pid=None):
        self.rpc = Rpc(port)
        self.pid = pid
        self.host = None
        self.host_delta = {}
        self.game = None
        self.title = None
        self.battle_slots = []
        self.battle_scan_at = 0.0

    def close(self):
        self.rpc.close()
        if self.host is not None:
            self.host.close()
            self.host = None

    def detect(self):
        for tid in self.rpc.title_ids():
            base = tid & 0xFFFFFFFF00FFFFFF if tid & 0x80000000 else tid
            if base in GAMES:
                self.title, self.game = tid, GAMES[base]
                return self.game["key"]
        self.title, self.game = None, None
        return None

    def party(self):
        g = self.game
        if not g:
            return None
        size = g["stride"] * 5 + max(232, g["stats"] + 28)
        raw = self.rpc.read(g["party"], size)
        if raw is None:
            return None
        mons = []
        for i in range(6):
            m = decode_mon(raw[g["stride"] * i:g["stride"] * i + max(232, g["stats"] + 28)], g["stats"])
            if m is None:
                break
            mons.append(m)
        return mons

    def _battle_mon(self, x, head=None):
        head = head or self.rpc.read(x, 0x14)
        if not head or len(head) < 0x12:
            return None
        holder, zero, _, sp, mx, cur = struct.unpack_from("<IIIHHH", head)
        if zero or not (0x08000000 <= holder < 0x40000000) or not (1 <= sp <= 807) or not (1 <= mx <= 999) or cur > mx:
            return None
        ptr = self.rpc.read(holder + 4, 4)
        if not ptr:
            return None
        pk_addr = struct.unpack("<I", ptr)[0]
        if not 0x08000000 <= pk_addr < 0x40000000:
            return None
        raw = self.rpc.read(pk_addr, BATTLE_PK_STATS + 28)
        m = decode_mon(raw, BATTLE_PK_STATS) if raw else None
        if not m or m["species"] != sp or m["hpMax"] != mx:
            return None
        m["hpCur"] = cur
        return m

    def _scan_battle(self, lo, hi):
        found = []
        for base in range(lo, hi, MAX_CHUNK):
            buf = self.rpc.read(base, MAX_CHUNK)
            if not buf:
                continue
            for off in range(0, len(buf) - 0x14, 4):
                holder, zero = struct.unpack_from("<II", buf, off)
                if zero or not (0x08000000 <= holder < 0x40000000):
                    continue
                sp, mx, cur = struct.unpack_from("<HHH", buf, off + 0xC)
                if 1 <= sp <= 721 and 1 <= mx <= 999 and cur <= mx:
                    m = self._battle_mon(base + off, buf[off:off + 0x14])
                    if m:
                        found.append((base + off, m))
        return found

    def opponents(self, party, now):
        window = (self.game or {}).get("battle")
        if not window:
            return []
        mine = {m["pid"] for m in party or []}
        if self.battle_slots:
            mons = [self._battle_mon(x) for x in self.battle_slots]
            if all(mons):
                return self._unique(mons, mine)
            self.battle_slots = []
        if now - self.battle_scan_at < 1.0:
            return []
        self.battle_scan_at = now
        found = [(x, m) for x, m in self._scan_battle(*window) if m["pid"] not in mine]
        self.battle_slots = [x for x, _ in found]
        return self._unique([m for _, m in found], mine)

    def position(self):
        pos = (self.game or {}).get("pos")
        if not pos:
            return None
        z = self.rpc.read(pos[0], 2)
        if not z:
            return None
        out = {"zone": struct.unpack("<H", z)[0], "x": None, "y": None, "h": None}
        c = self.rpc.read(pos[1], 12) if pos[1] else None
        if c:
            x, h, y = struct.unpack("<3f", c)
            out.update(x=round(x / 18), y=round(y / 18), h=h)
        return out

    def _delta(self, addr):
        key = addr & 0xF0000000
        cmp = self.rpc.read(addr & ~0xF, 0x40)
        if not cmp:
            return None
        if key in self.host_delta and self.host.read((addr & ~0xF) + self.host_delta[key], 0x40) == cmp:
            return self.host_delta[key]
        anchors = []
        g = self.game or {}
        if g.get("party") and g["party"] & 0xF0000000 == key:
            anchors.append(g["party"])
        anchors += [(addr & ~0xFF) + d for d in range(0, 0x800, 0x100)] + [(addr & ~0xFF) - d for d in range(0x100, 0x800, 0x100)]
        tries = 0
        for probe in anchors:
            needle = self.rpc.read(probe, 0x100)
            if not needle or needle.count(0) > 0xC0 or len(set(needle)) < 24:
                continue
            tries += 1
            for found in self.host.find(needle):
                delta = found - probe
                if self.host.read((addr & ~0xF) + delta, 0x40) == cmp:
                    self.host_delta[key] = delta
                    return delta
            if tries >= 4:
                break
        return None

    def write(self, addr, data):
        if self.rpc.write(addr, data) and self.rpc.read(addr, len(data)) == data:
            return True
        if not self.pid:
            return False
        try:
            if self.host is None:
                self.host = HostMem(self.pid) if osdep.IS_WIN else osdep.ProcMem(
                    osdep.find_process(osdep.LINUX_EMU_NAMES["azahar"], self.pid) or self.pid)
            delta = self._delta(addr)
            if delta is None:
                return False
            return self.host.write(addr + delta, data) and self.rpc.read(addr, len(data)) == data
        except OSError:
            return False

    def cheats(self):
        g = self.game or {}
        out = []
        if g.get("pockets"):
            out += [k for k, item in (("master_ball", 1), ("rare_candy", 50)) if item in g["pockets"]]
        if g.get("money"):
            out.append("money")
        return out

    def set_max_money(self):
        addr = (self.game or {}).get("money")
        if not addr:
            return False, "Argent non configuré pour ce jeu"
        cur = self.rpc.read(addr, 4)
        if not cur or struct.unpack("<I", cur)[0] > MAX_MONEY:
            return False, "Adresse argent non confirmée (valeur actuelle improbable)"
        ok = self.write(addr, struct.pack("<I", MAX_MONEY))
        return ok, None if ok else "Écriture impossible"

    def give_item(self, item_id, qty):
        pocket = (self.game or {}).get("pockets", {}).get(item_id)
        if not pocket:
            return False, "Objet non configuré pour ce jeu"
        start, count = pocket[0], pocket[1]
        packed = len(pocket) > 2
        raw = self.rpc.read(start, count * 4)
        if not raw:
            return False, "Lecture mémoire impossible"
        words = [w for (w,) in struct.iter_unpack("<I", raw)]
        if packed:
            slots = [(w & 0x3FF, (w >> 10) & 0x3FF) for w in words]
        else:
            slots = [(w & 0xFFFF, w >> 16) for w in words]
        if any(q > ITEM_CAP or (i == 0 and q) for i, q in slots):
            return False, "Sac non reconnu (valeurs improbables)"
        n = next((k for k, (i, _) in enumerate(slots) if i == item_id), None)
        if n is None:
            n = next((k for k, (i, _) in enumerate(slots) if i == 0), None)
        if n is None:
            return False, "Poche pleine (aucun emplacement libre)"
        have = slots[n][1] if slots[n][0] == item_id else 0
        q = min(have + qty, ITEM_CAP)
        if packed:
            keep = words[n] & ~0xFFFFF if slots[n][0] == item_id else 0
            data = struct.pack("<I", keep | item_id | (q << 10))
        else:
            data = struct.pack("<HH", item_id, q)
        ok = self.write(start + 4 * n, data)
        return ok, None if ok else "Écriture impossible"

    @staticmethod
    def _unique(mons, mine):
        seen, out = set(), []
        for m in mons:
            if m["pid"] in mine or m["pid"] in seen:
                continue
            seen.add(m["pid"])
            out.append(m)
        return out
