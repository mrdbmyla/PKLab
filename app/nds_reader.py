import struct

import engine
from games import GAMES, DETECT_ORDER, NUM_SLOTS

NDS_RAM = 0x02000000
NDS_RAM_SIZE = 0x400000
TITLE_NDS = 0x023FFE00
SEARCH = 0x2000

NDS_KEYS = [k for k in DETECT_ORDER if GAMES.get(k, {}).get("gen") in (4, 5)]


class _NdsView:

    def __init__(self, reader):
        self.r = reader

    def read_u32(self, a):
        return self.r.pm.read_uint(self.r.host(a))

    def read_u16(self, a):
        return self.r.pm.read_ushort(self.r.host(a))

    def read_bytes(self, a, n):
        return self.r.pm.read_bytes(self.r.host(a), n)


class NdsReader:
    def __init__(self, mem, base, key):
        self.mem = mem
        self.pm = mem.pm
        self.base = base
        self.key = key
        self.game = GAMES[key]
        self.gen = self.game["gen"]
        self.ptr_addr = None
        self.delta = None
        self._view = _NdsView(self)

    def host(self, nds_addr):
        return self.base + (nds_addr - NDS_RAM)

    @staticmethod
    def in_ram(a):
        return NDS_RAM <= a < NDS_RAM + NDS_RAM_SIZE

    def u32(self, nds_addr):
        return self.pm.read_uint(self.host(nds_addr))

    @staticmethod
    def find_main_ram(mem):
        for region, size in mem._big_readable_regions():
            if size < NDS_RAM_SIZE:
                continue
            try:
                title = mem.pm.read_bytes(region + (TITLE_NDS - NDS_RAM), 12).split(b"\0")[0].rstrip(b" ")
            except Exception:
                continue
            key = next((k for k in NDS_KEYS if title == k.encode()), None)
            if key is not None:
                return region, key
        return None

    @classmethod
    def locate(cls, mem, found=None):
        found = found or cls.find_main_ram(mem)
        if found is None:
            return None
        r = cls(mem, *found)
        if r.gen == 4:
            r.ptr_addr = r._search(r.game["pointer_addr"], lambda value, a: value + r.game["player_offset"])
            return r if r.ptr_addr is not None else None
        doc = r.game["addrs"]["player"]
        hit = r._search(doc, lambda value, a: a)
        if hit is None:
            return None
        r.delta = hit - doc
        return r

    def _search(self, center, party_of):
        lo = center - SEARCH
        try:
            words = struct.unpack(f"<{2 * SEARCH // 4}I", self.pm.read_bytes(self.host(lo), 2 * SEARCH))
        except Exception:
            return None
        for i in sorted(range(len(words)), key=lambda i: abs(lo + 4 * i - center)):
            party = party_of(words[i], lo + 4 * i)
            if self._party_at(party) and self._save_data_plausible(party):
                return lo + 4 * i
        return None

    def _party_at(self, party):
        if not self.in_ram(party):
            return False
        try:
            count = self.u32(party - 4)
        except Exception:
            return False
        if not 1 <= count <= NUM_SLOTS:
            return False
        mon = self.decode(party)
        return mon is not None and mon["hpMax"] is not None and mon["level"] is not None

    def save_addr(self, party, field):
        if self.gen == 4:
            off = self.game.get("live_offsets", {}).get(field)
        else:
            addrs = self.game["addrs"]
            off = addrs[field] - addrs["player"] if field in addrs else None
        return None if off is None else party + off

    def _save_data_plausible(self, party):
        try:
            money = self.save_addr(party, "money")
            if money is not None and self.u32(money) > 999999:
                return False
            for pocket in ("bag_items", "bag_balls", "bag_medicine"):
                a = self.save_addr(party, pocket)
                if a is None:
                    continue
                item, qty = struct.unpack("<HH", self.pm.read_bytes(self.host(a), 4))
                if item > 700 or qty > 999 or (item == 0) != (qty == 0):
                    return False
        except Exception:
            return False
        return True

    def read_location(self, party):
        offs = self.game.get("location_offsets")
        if not offs:
            return None
        try:
            zone = self.pm.read_ushort(self.host(party + offs["zone"]))
            x = self.pm.read_ushort(self.host(party + offs["x"]))
            y = self.pm.read_ushort(self.host(party + offs["y"]))
        except Exception:
            return None
        if not 2 <= zone < self.game.get("zone_count", 0xFFFF):
            return None
        return {"zone": zone, "x": x, "y": y}

    def decode(self, nds_addr):
        return engine.decode_pokemon(self._view, nds_addr, self.gen)

    def read_party(self, party):
        count = self.u32(party - 4)
        if not 0 <= count <= NUM_SLOTS:
            return None
        mons = []
        for i in range(count):
            mon = self.decode(party + i * self.game["slot_size"])
            if mon is None or mon["hpMax"] is None or mon["level"] is None:
                return None
            mons.append(mon)
        return mons

    def _battle_state(self, ptr):
        g = self.game
        if self.gen == 4:
            in_battle = self.u32(ptr + g["battle_flag_offset"]) != 0 if "battle_flag_offset" in g else None
            enemy_ptr = self.u32(ptr + g["enemy_ptr_offset"])
            enemy = enemy_ptr + g["enemy_sub_offset"] if self.in_ram(enemy_ptr) else None
            return in_battle, enemy
        in_battle = None
        if "battle_flag_addr" in g:
            flag = self.u32(g["battle_flag_addr"])
            in_battle = flag == 1 if flag in (0, 1) else None
        return in_battle, g["addrs"]["trainer"] + self.delta

    def snapshot(self):
        if self.gen == 4:
            ptr = self.u32(self.ptr_addr)
            if not self.in_ram(ptr):
                return None
            party_addr = ptr + self.game["player_offset"]
        else:
            ptr = None
            party_addr = self.game["addrs"]["player"] + self.delta
        party = self.read_party(party_addr)
        if not party:
            return None
        in_battle, enemy = self._battle_state(ptr)
        opponents = []
        if (in_battle or in_battle is None) and enemy is not None:
            opponents = self.read_party(enemy) or []
        if in_battle is None:
            in_battle = bool(opponents)
        return party_addr, party, opponents, in_battle
