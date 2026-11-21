import os
import re
import shutil
import struct
import subprocess
import tempfile
import sys
import time

IS_WIN = sys.platform == "win32"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
DETACHED = 0x00000008 | 0x00000200 if IS_WIN else 0

LINUX_EMU_NAMES = {
    "mgba": ("mgba-qt", "mgba", "mGBA"),
    "melonds": ("melonDS", "melonds"),
    "azahar": ("azahar", "azahar-qt"),
}


def _executable(p):
    return os.path.isfile(p) and os.access(p, os.X_OK)


_HELP_CACHE = {}


def _has_script_option(path):
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return False
    if key not in _HELP_CACHE:
        try:
            r = subprocess.run([path, "--help"], capture_output=True, text=True, timeout=30, env=_emu_env(),
                               stdin=subprocess.DEVNULL)
            _HELP_CACHE[key] = "--script" in (r.stdout or "") + (r.stderr or "")
        except (OSError, subprocess.TimeoutExpired):
            _HELP_CACHE[key] = False
    return _HELP_CACHE[key]


def find_linux_emulator(engine_key, local_dir):
    names = LINUX_EMU_NAMES.get(engine_key, ())
    low = [n.lower() for n in names]
    try:
        entries = sorted(os.listdir(local_dir))
    except OSError:
        entries = []
    found = [os.path.join(local_dir, n) for n in entries
             if n.lower().split(".")[0].split("-")[0].split("_")[0] in low
             and (n.lower().endswith(".appimage") or "." not in n) and _executable(os.path.join(local_dir, n))]
    found += [p for p in (shutil.which(n) for n in names) if p]
    for p in found:
        if engine_key != "mgba" or _has_script_option(p):
            return p
    return None


def install_hint(engine_key, local_dir):
    if engine_key == "mgba":
        return f"mGBA 0.11 ou plus récent introuvable : place son AppImage dans {local_dir}"
    pkg = {"melonds": "melonDS", "azahar": "Azahar"}.get(engine_key, engine_key)
    return f"{pkg} introuvable : installe-le ou place son AppImage dans {local_dir}"


def _emu_env():
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "xcb")
    for k in ("PKLAB_BASE_DIR", "PKLAB_RES_DIR", "PYWEBVIEW_GUI", "QTWEBENGINE_CHROMIUM_FLAGS", "QTWEBENGINE_DISABLE_SANDBOX"):
        env.pop(k, None)
    if not _HAS_FUSE2:
        env.setdefault("APPIMAGE_EXTRACT_AND_RUN", "1")
    return env


def _fuse2():
    if IS_WIN:
        return True
    import ctypes.util
    return bool(ctypes.util.find_library("fuse"))


_HAS_FUSE2 = _fuse2()


EMU_LOG_PATH = os.path.join(tempfile.gettempdir(), f"pklab_emulator_{os.getuid() if hasattr(os, 'getuid') else 0}.log")


def popen_emulator(args, cwd=None):
    if IS_WIN:
        return subprocess.Popen(args, creationflags=NO_WINDOW, cwd=cwd)
    env = _emu_env()
    try:
        log = open(EMU_LOG_PATH, "wb")
    except OSError:
        log = subprocess.DEVNULL
    try:
        return subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True, preexec_fn=_unblock_signals)
    finally:
        if log is not subprocess.DEVNULL:
            log.close()


def emulator_failure():
    try:
        with open(EMU_LOG_PATH, "rb") as f:
            lines = [l.strip() for l in f.read()[-4000:].decode("utf-8", "replace").splitlines() if l.strip()]
    except OSError:
        lines = []
    for l in lines:
        m = re.search(r"error while loading shared libraries: ([^:]+)", l)
        if m:
            return "Bibliothèque système manquante : " + m.group(1)
    return "L'émulateur s'est fermé au démarrage" + (" : " + lines[-1][:200] if lines else "")


def _unblock_signals():
    import signal
    signal.pthread_sigmask(signal.SIG_SETMASK, set())


def _signal_all(pgid, pids, sig):
    try:
        os.killpg(pgid, sig)
    except OSError:
        pass
    for p in pids:
        try:
            os.kill(p, sig)
        except OSError:
            pass


def _running(pid):
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            st = f.read()
        return st[st.rindex(b")") + 2:st.rindex(b")") + 3] != b"Z"
    except (OSError, ValueError):
        return False


def stop_tree(proc, timeout=3.0):
    if IS_WIN:
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
        return
    pids = [p for p in descendants(proc.pid) if p != proc.pid]
    _signal_all(proc.pid, [proc.pid] + pids, 15)
    t0 = time.time()
    while time.time() - t0 < timeout:
        proc.poll()
        if not _running(proc.pid) and not any(_running(p) for p in pids):
            break
        time.sleep(0.1)
    else:
        _signal_all(proc.pid, [proc.pid] + pids, 9)
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def kill_pid(pid, exe_name):
    if IS_WIN:
        subprocess.run(["taskkill", "/F", "/FI", f"PID eq {pid}", "/FI", f"IMAGENAME eq {exe_name}"],
                       creationflags=NO_WINDOW, capture_output=True, timeout=5)
        return
    try:
        pid = int(pid)
        with open(f"/proc/{pid}/comm", encoding="utf-8", errors="replace") as f:
            comm = f.read().strip()
    except (OSError, ValueError):
        return
    if exe_name and comm.lower()[:15] == os.path.basename(exe_name).lower()[:15]:
        _signal_all(pid, descendants(pid), 9)


def wait_pid(pid, timeout=30.0):
    if IS_WIN:
        import ctypes
        k = ctypes.windll.kernel32
        hp = k.OpenProcess(0x00100000, False, int(pid))
        if hp:
            k.WaitForSingleObject(hp, int(timeout * 1000))
            k.CloseHandle(hp)
        return
    end = time.time() + timeout
    while time.time() < end and os.path.exists(f"/proc/{int(pid)}"):
        time.sleep(0.2)


def _trash_win(paths):
    import ctypes
    import ctypes.wintypes as wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", ctypes.c_uint), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    op = SHFILEOPSTRUCTW()
    op.wFunc = 3
    op.pFrom = "\0".join(paths) + "\0\0"
    op.fFlags = 0x0040 | 0x0010 | 0x0400 | 0x0004
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not op.fAnyOperationsAborted


def _trash_linux(paths):
    gio = shutil.which("gio")
    if gio:
        try:
            if subprocess.run([gio, "trash", "--", *paths], capture_output=True, timeout=30).returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
    from urllib.parse import quote
    base = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "Trash")
    files, info = os.path.join(base, "files"), os.path.join(base, "info")
    try:
        os.makedirs(files, exist_ok=True)
        os.makedirs(info, exist_ok=True)
        for p in paths:
            if not os.path.lexists(p):
                continue
            name = os.path.basename(p.rstrip("/"))
            stem, ext = os.path.splitext(name)
            cand, i = name, 1
            while os.path.lexists(os.path.join(files, cand)) or os.path.lexists(os.path.join(info, cand + ".trashinfo")):
                i += 1
                cand = f"{stem}.{i}{ext}"
            with open(os.path.join(info, cand + ".trashinfo"), "w", encoding="utf-8") as f:
                f.write(f"[Trash Info]\nPath={quote(os.path.abspath(p))}\nDeletionDate={time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
            shutil.move(p, os.path.join(files, cand))
        return True
    except OSError:
        return False


def to_trash(paths):
    return _trash_win(paths) if IS_WIN else _trash_linux(paths)


def _xdg_open(target):
    try:
        subprocess.Popen(["xdg-open", target], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


def open_file(path):
    if IS_WIN:
        os.startfile(path)
        return True
    return _xdg_open(path)


def reveal(path):
    if IS_WIN:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        return True
    gdbus = shutil.which("gdbus")
    if gdbus:
        from urllib.parse import quote
        try:
            r = subprocess.run([gdbus, "call", "--session", "--dest", "org.freedesktop.FileManager1",
                                "--object-path", "/org/freedesktop/FileManager1",
                                "--method", "org.freedesktop.FileManager1.ShowItems",
                                "['file://" + quote(os.path.abspath(path)) + "']", ""],
                               capture_output=True, timeout=5)
            if r.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
    return _xdg_open(os.path.dirname(os.path.abspath(path)))


def _zenity(kind, text, title="PKLab", extra=()):
    exe = shutil.which("zenity") or shutil.which("kdialog")
    if not exe:
        return None
    if exe.endswith("kdialog"):
        flag = {"info": "--msgbox", "question": "--yesnocancel"}[kind]
        args = [exe, "--title", title, flag, text]
    else:
        args = [exe, "--" + kind, "--title", title, "--text", text, "--no-markup", *extra]
    try:
        return subprocess.run(args, capture_output=True, timeout=600).returncode
    except (OSError, subprocess.TimeoutExpired):
        return None


def message_box(text, title="PKLab"):
    if IS_WIN:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
        return
    if _zenity("info", text, title) is None:
        print(text, flush=True)


def ask_yes_no_cancel(text, yes, no, cancel, title="PKLab"):
    exe = shutil.which("zenity")
    if exe:
        try:
            r = subprocess.run([exe, "--question", "--title", title, "--text", text, "--no-markup",
                                "--ok-label", yes, "--cancel-label", cancel, "--extra-button", no],
                               capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.TimeoutExpired):
            return "no"
        if r.returncode == 0:
            return "yes"
        return "no" if r.stdout.strip() == no else "cancel"
    exe = shutil.which("kdialog")
    if exe:
        try:
            rc = subprocess.run([exe, "--title", title, "--yesnocancel", text, "--yes-label", yes,
                                 "--no-label", no, "--cancel-label", cancel], capture_output=True, timeout=600).returncode
        except (OSError, subprocess.TimeoutExpired):
            return "no"
        return {0: "yes", 1: "no"}.get(rc, "cancel")
    return "no"


def descendants(pid):
    kids = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/stat", "rb") as f:
                st = f.read()
            ppid = int(st[st.rindex(b")") + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        kids.setdefault(ppid, []).append(int(d))
    out, todo = [], [int(pid)]
    while todo:
        p = todo.pop()
        out.append(p)
        todo += kids.get(p, [])
    return out


def proc_name(pid):
    try:
        with open(f"/proc/{pid}/comm", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def _exe_name(pid):
    try:
        return os.path.basename(os.readlink(f"/proc/{pid}/exe"))
    except OSError:
        return ""


def find_process(names, root_pid=None):
    low = {n.lower() for n in names}
    pids = descendants(root_pid) if root_pid else [int(d) for d in os.listdir("/proc") if d.isdigit()]
    for p in pids:
        if proc_name(p).lower() in {n[:15] for n in low} or _exe_name(p).lower() in low:
            return p
    return None


def _anon_rw(perms, path):
    return perms.startswith("rw") and (not path or path.startswith(("[heap]", "[anon", "/memfd:", "/dev/shm/", "/SYSV"))
                                       or path.endswith("(deleted)"))


class ProcMem:
    def __init__(self, pid):
        self.pid = int(pid)
        self.process_handle = self.pid
        self.base_address = 0
        self.f = open(f"/proc/{self.pid}/mem", "r+b", buffering=0)

    def close_process(self):
        try:
            self.f.close()
        except OSError:
            pass

    close = close_process

    def alive(self):
        try:
            with open(f"/proc/{self.pid}/stat", "rb") as f:
                st = f.read()
            return st[st.rindex(b")") + 2:st.rindex(b")") + 3] not in (b"Z", b"X")
        except (OSError, ValueError):
            return False

    def regions(self):
        out = []
        try:
            with open(f"/proc/{self.pid}/maps", encoding="utf-8", errors="replace") as f:
                for line in f:
                    parts = line.split(None, 5)
                    if len(parts) < 5:
                        continue
                    lo, hi = (int(x, 16) for x in parts[0].split("-"))
                    out.append((lo, hi - lo, parts[1], parts[5].strip() if len(parts) > 5 else ""))
        except OSError:
            pass
        return out

    def rw_regions(self, min_size=0, max_size=1 << 62, files=False):
        return [(a, s) for a, s, perms, path in self.regions()
                if (_anon_rw(perms, path) or files and perms.startswith("rw") and path.startswith("/"))
                and min_size <= s <= max_size]

    def read_bytes(self, addr, size):
        self.f.seek(addr)
        data = self.f.read(size)
        if data is None or len(data) != size:
            raise OSError("lecture mémoire incomplète")
        return data

    def read(self, addr, size):
        try:
            return self.read_bytes(addr, size)
        except (OSError, ValueError, OverflowError):
            return None

    def write_bytes(self, addr, data, size=None):
        data = bytes(data[:size] if size is not None else data)
        self.f.seek(addr)
        if self.f.write(data) != len(data):
            raise OSError("écriture mémoire incomplète")

    def write(self, addr, data):
        try:
            self.write_bytes(addr, data)
            return True
        except (OSError, ValueError, OverflowError):
            return False

    def read_uchar(self, addr):
        return self.read_bytes(addr, 1)[0]

    def read_ushort(self, addr):
        return struct.unpack("<H", self.read_bytes(addr, 2))[0]

    def read_uint(self, addr):
        return struct.unpack("<I", self.read_bytes(addr, 4))[0]

    def write_ushort(self, addr, v):
        self.write_bytes(addr, struct.pack("<H", v))

    def write_uint(self, addr, v):
        self.write_bytes(addr, struct.pack("<I", v))

    def find(self, needle, limit=8, step=4 << 20):
        hits = []
        for base, size in self.rw_regions():
            off = 0
            while off < size:
                data = self.read(base + off, min(size - off, step + len(needle)))
                if data:
                    i = data.find(needle)
                    while i != -1:
                        hits.append(base + off + i)
                        if len(hits) > limit:
                            return hits
                        i = data.find(needle, i + 1)
                off += step
        return hits


class PulseVolume:
    def __init__(self, ids, volume, muted):
        self.ids, self.volume, self.muted = ids, volume, muted

    @staticmethod
    def _pactl(*args):
        exe = shutil.which("pactl")
        if not exe:
            return None
        env = dict(os.environ, LC_ALL="C")
        try:
            r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=3, env=env)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return r.stdout if r.returncode == 0 else None

    @classmethod
    def find(cls, pids):
        out = cls._pactl("list", "sink-inputs")
        if not out:
            return None
        pids = {str(p) for p in pids}
        ids, vol, muted = [], None, False
        for block in out.split("Sink Input #")[1:]:
            m = re.search(r'application\.process\.id = "(\d+)"', block)
            if not m or m.group(1) not in pids:
                continue
            ids.append(block.split(None, 1)[0])
            v = re.search(r"Volume:.*?(\d+)%", block)
            if v and vol is None:
                vol = int(v.group(1)) / 100.0
            muted = muted or bool(re.search(r"Mute: yes", block))
        return cls(ids, 1.0 if vol is None else vol, muted) if ids else None

    def GetMasterVolume(self):
        return self.volume

    def GetMute(self):
        return self.muted

    def SetMasterVolume(self, v, _ctx=None):
        for i in self.ids:
            self._pactl("set-sink-input-volume", i, f"{round(v * 100)}%")

    def SetMute(self, m, _ctx=None):
        for i in self.ids:
            self._pactl("set-sink-input-mute", i, "1" if m else "0")


def _xdotool(*args, timeout=3):
    exe = shutil.which("xdotool")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def x11_window(pids, title_contains):
    for p in pids:
        out = _xdotool("search", "--onlyvisible", "--pid", str(p), "--name", title_contains)
        if out:
            ids = [int(x) for x in out.split() if x.isdigit()]
            if ids:
                return ids[0]
    return None


def x11_title(wid):
    out = _xdotool("getwindowname", str(wid))
    return out.strip() if out else ""


def x11_keys(wid, keys, direct=False):
    if direct:
        return _xdotool("key", "--window", str(wid), *keys, timeout=5) is not None
    return _xdotool("windowactivate", "--sync", str(wid), "key", "--clearmodifiers", *keys, timeout=5) is not None
