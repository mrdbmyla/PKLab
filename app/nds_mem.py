import osdep

if osdep.IS_WIN:
    import pymem
    import pymem.memory


class NdsEmulatorNotFound(Exception):
    pass


class NdsMemory:
    def __init__(self, proc_name, root_pid=None):
        self.proc_name = proc_name
        self.root_pid = root_pid
        self.pm = None

    def attach(self):
        if not osdep.IS_WIN:
            pid = osdep.find_process(osdep.LINUX_EMU_NAMES["melonds"], self.root_pid) if self.root_pid else None
            try:
                self.pm = osdep.ProcMem(pid) if pid else None
            except OSError as e:
                raise NdsEmulatorNotFound(f"melonDS inaccessible : {e}")
            if self.pm is None:
                raise NdsEmulatorNotFound("melonDS process not found")
            return
        try:
            self.pm = pymem.Pymem(self.proc_name)
        except Exception as e:
            raise NdsEmulatorNotFound(f"{self.proc_name} process not found: {e}")

    def process_alive(self):
        if not self.pm:
            return False
        if not osdep.IS_WIN:
            return self.pm.alive()
        try:
            pymem.memory.virtual_query(self.pm.process_handle, self.pm.base_address)
            return True
        except Exception:
            return False

    def _big_readable_regions(self, min_size=1024 * 1024, max_size=256 * 1024 * 1024):
        if not osdep.IS_WIN:
            return self.pm.rw_regions(min_size, max_size)
        regions = []
        address = 0x10000
        while address < 0x7FFFFFFF0000:
            try:
                mbi = pymem.memory.virtual_query(self.pm.process_handle, address)
                region_addr, region_size, state, protect = mbi.BaseAddress, mbi.RegionSize, mbi.State, mbi.Protect
            except Exception:
                break
            if region_size <= 0:
                break
            if state == 0x1000 and (protect & 0x100) == 0 and (protect & 0xFF) in {0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80}:
                if min_size <= region_size <= max_size:
                    regions.append((region_addr, region_size))
            nxt = region_addr + region_size
            if nxt <= address:
                break
            address = nxt
        return regions
