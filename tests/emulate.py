"""Emulator tests for the TCS Universal Patch (no game window, no input).

Maps the unwrapped LEGOStarWarsSaga.exe image and the test build of the patch (out/test/dinput8_test.dll)
into a Unicorn x86 emulator, stands in for the few Windows calls they make, and runs the GAME'S OWN code
through the patched sites: start-up hook, keyword parsing, behaviour assignment, projectile picker,
lever rule and the Geonosis arena picker.

usage: python tests/emulate.py [path to the unwrapped exe]
   (default: C:/LegoBatman/build/tcs_exe/LEGOStarWarsSaga.exe.unpacked.exe, or env TCS_EXE)
"""
import os, struct, sys
import pefile
from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ECX,
                                UC_X86_REG_EDX, UC_X86_REG_EBX, UC_X86_REG_EDI)

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
    "TCS_EXE", r"C:\LegoBatman\build\tcs_exe\LEGOStarWarsSaga.exe.unpacked.exe")
DLL = os.path.join(HERE, "..", "out", "test", "dinput8_test.dll")

THUNKS, STOP = 0x6F000000, 0x6FFF0000
STACK, STACK_SIZE = 0x08000000, 0x00100000
HEAP = 0x20000000
KERNEL32 = 0x7E000000
IAT_GETCOMMANDLINEA = 0x00751178
REAL_CMDLINE = b"LEGOStarWarsSaga.exe\0"

ROUTINE = {"standard": 0x4B4AC0, "jedi": 0x4B3390, "droid": 0x4B5EF0, "beast": 0x4B3000,
           "winged": 0x4B65F0, "variant0": 0x4B5820}


def align(n, a=0x1000):
    return (n + a - 1) & ~(a - 1)


class Machine:
    def __init__(self, ini, timestamp=None):
        self.ini = ini
        self.uc = uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.thunk_names, self.next_thunk = {}, THUNKS
        uc.mem_map(THUNKS, 0x100000)
        uc.mem_map(STOP & ~0xFFF, 0x1000)
        uc.mem_map(STACK, STACK_SIZE)
        uc.mem_map(HEAP, 0x01000000)
        uc.mem_map(KERNEL32, 0x1000)
        self.heap = HEAP
        self.loaded, self.di_calls = [], []
        self.cmdline = self.alloc(REAL_CMDLINE)
        self._load(EXE, 0x400000, timestamp)
        self._load(DLL, None, None)
        uc.hook_add(UC_HOOK_CODE, self._on_thunk, begin=THUNKS, end=THUNKS + 0xFFFFF)
        uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._on_unmapped)
        self.exports = {e.name.decode(): self.dll_base + e.address
                        for e in pefile.PE(DLL).DIRECTORY_ENTRY_EXPORT.symbols}

    # ---------------------------------------------------------------- loading
    def _load(self, path, base, timestamp):
        pe = pefile.PE(path)
        base = base or pe.OPTIONAL_HEADER.ImageBase
        img = bytearray(pe.get_memory_mapped_image())
        size = align(max(pe.OPTIONAL_HEADER.SizeOfImage, len(img)))
        self.uc.mem_map(base, size)
        if timestamp is not None:
            struct.pack_into("<I", img, pe.DOS_HEADER.e_lfanew + 8, timestamp)
        self.uc.mem_write(base, bytes(img))
        for entry in pe.DIRECTORY_ENTRY_IMPORT:
            for imp in entry.imports:
                name = imp.name.decode() if imp.name else f"ord{imp.ordinal}"
                self.w32(imp.address - pe.OPTIONAL_HEADER.ImageBase + base, self.thunk(name))
        if path == DLL:
            self.dll_base = base

    def thunk(self, name):
        for addr, n in self.thunk_names.items():
            if n == name:
                return addr
        addr = self.next_thunk
        self.next_thunk += 16
        self.thunk_names[addr] = name
        self.uc.mem_write(addr, b"\xC3")
        return addr

    # ---------------------------------------------------------------- memory helpers
    def r32(self, a):
        return struct.unpack("<I", self.uc.mem_read(a, 4))[0]

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def r16s(self, a):
        return struct.unpack("<h", self.uc.mem_read(a, 2))[0]

    def w16(self, a, v):
        self.uc.mem_write(a, struct.pack("<h", v))

    def rbytes(self, a, n):
        return bytes(self.uc.mem_read(a, n))

    def cstr(self, a, n=256):
        return self.rbytes(a, n).split(b"\0")[0].decode("latin1")

    def alloc(self, data_or_size):
        data = bytes(data_or_size) if not isinstance(data_or_size, int) else bytes(data_or_size)
        a = self.heap
        self.uc.mem_write(a, data)
        self.heap = align(a + len(data) + 16, 16)
        return a

    # ---------------------------------------------------------------- calling
    def call(self, addr, *args, regs=None):
        uc = self.uc
        sp = STACK + STACK_SIZE - 0x1000
        for v in reversed(args):
            sp -= 4
            self.w32(sp, v)
        sp -= 4
        self.w32(sp, STOP)
        uc.reg_write(UC_X86_REG_ESP, sp)
        for r, v in (regs or {}).items():
            uc.reg_write(r, v)
        uc.emu_start(addr, STOP, count=50_000_000)
        return uc.reg_read(UC_X86_REG_EAX)

    def run(self, begin, until, regs=None):
        uc = self.uc
        uc.reg_write(UC_X86_REG_ESP, STACK + STACK_SIZE - 0x1000)
        for r, v in (regs or {}).items():
            uc.reg_write(r, v)
        uc.emu_start(begin, until, count=50_000_000)

    def _on_unmapped(self, uc, access, address, size, value, user):
        eip = uc.reg_read(UC_X86_REG_EIP)
        raise RuntimeError(f"unmapped access {address:08X} at eip {eip:08X}")

    # ---------------------------------------------------------------- Windows stand-ins
    def _on_thunk(self, uc, address, size, user):
        name = self.thunk_names.get(address)
        sp = uc.reg_read(UC_X86_REG_ESP)
        arg = lambda i: self.r32(sp + 4 + 4 * i)
        handlers = {
            "VirtualProtect": (4, lambda: (self.w32(arg(3), 0x20), 1)[1]),
            "FlushInstructionCache": (3, lambda: 1),
            "GetCurrentProcess": (0, lambda: 0xFFFFFFFF),
            "GetModuleHandleA": (1, lambda: 0x400000 if arg(0) == 0 else KERNEL32),
            "GetProcAddress": (2, lambda: self.thunk(self.cstr(arg(1)))),
            "GetCommandLineA": (0, lambda: self.cmdline),
            "VirtualAlloc": (4, lambda: self.alloc(arg(1))),
            "GetPrivateProfileIntA": (4, lambda: self._ini_int(arg(0), arg(1), arg(2))),
            "GetPrivateProfileStringA": (6, lambda: self._ini_str(*[arg(i) for i in range(5)])),
            "LoadLibraryA": (1, lambda: (self.loaded.append(self.cstr(arg(0))), 0x10000000)[1]),
            "GetSystemDirectoryA": (2, lambda: (self.uc.mem_write(arg(0), b"C:\\Windows\\System32\0"), 19)[1]),
            "DirectInput8Create": (5, lambda: (self.di_calls.append([arg(i) for i in range(5)]), 0)[1]),
        }
        if name not in handlers:
            raise RuntimeError(f"unexpected call to {name}")
        nargs, fn = handlers[name]
        result = fn()
        ret = self.r32(sp)
        uc.reg_write(UC_X86_REG_EAX, result & 0xFFFFFFFF)
        uc.reg_write(UC_X86_REG_ESP, sp + 4 + 4 * nargs)
        uc.reg_write(UC_X86_REG_EIP, ret)

    def _ini_int(self, sec, key, default):
        v = self.ini.get(self.cstr(sec).lower(), {}).get(self.cstr(key).lower())
        return int(v) if v is not None else default

    def _ini_str(self, sec, key, default, buf, size):
        section = self.ini.get(self.cstr(sec).lower(), {})
        if key == 0:
            data = b"".join(k.encode() + b"\0" for k in section) + b"\0"
        else:
            v = section.get(self.cstr(key).lower())
            data = (v if v is not None else self.cstr(default)).encode() + b"\0"
        data = data[:size]
        self.uc.mem_write(buf, data)
        return max(0, len(data) - 1)

    # ---------------------------------------------------------------- game set-up
    def install(self, dirname="C:\\test"):
        return self.call(self.exports["TCSU_TestInstall"], self.alloc(dirname.encode() + b"\0"))

    def start_game_code(self):
        """What the game's start-up does first: call GetCommandLineA through its import table."""
        return self.call(self.r32(IAT_GETCOMMANDLINEA))

    def make_definitions(self, chars):
        """chars: list of (name, flagsA, flagsB90, flagsB94, variant); returns {name: index}."""
        n = len(chars)
        a = self.alloc(n * 0x4C)
        b = self.alloc(n * 0x120)
        self.w32(0x93B274, a)
        self.w32(0x93B278, n)
        self.w32(0x93B284, b)
        # every name -> ID global starts unset, as before a level loads them
        t = 0x7F1B50
        while self.r32(t):
            self.w16(self.r32(t + 4), -1)
            t += 8
        self.call(0x414340, 0)  # defaults: template into B, standard routine
        index = {}
        for i, (name, fa, f90, f94, variant) in enumerate(chars):
            da, db = a + i * 0x4C, b + i * 0x120
            self.w32(da + 0x04, fa)
            self.w32(da + 0x0C, self.alloc(name.encode() + b"\0"))
            self.w32(da + 0x24, db)
            self.w32(db + 0x90, f90)
            self.w32(db + 0x94, f94)
            self.uc.mem_write(db + 0x116, bytes([variant & 0xFF]))
            index[name] = i
        return index

    def set_id(self, name, value):
        t = 0x7F1B50
        while self.r32(t):
            if self.cstr(self.r32(t)).lower() == name.lower():
                self.w16(self.r32(t + 4), value)
                return
            t += 8
        raise KeyError(name)

    def routine(self, i):
        return self.r32(self.r32(0x93B274) + i * 0x4C + 0x18)

    def make_instance(self, index):
        inst = self.alloc(0x1200)
        self.w32(inst + 0x54, self.r32(0x93B274) + index * 0x4C)
        self.w16(inst + 0x1064, index)
        return inst


# ==================================================================== tests
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


DROID, BH, JEDI, BLASTER, TELEPORT, PROTOCOL = 0x10, 0x1000000, 0x8, 0x10000080, 0x40000, 0x30

CHARS = [
    ("lukeskywalker", JEDI, 0, 0, 0xFF),
    ("battledroid", DROID | BLASTER, 0, 0, 0xFF),
    ("ig88", DROID | BH | BLASTER, 0, 0, 0xFF),
    ("c3po", PROTOCOL, 0, 0, 0xFF),
    ("imperialguard", 0, 0, 0, 0xFF),
    ("ewok", BLASTER, 0, 0, 0xFF),
    ("hansolo", BLASTER, 0, 0, 0xFF),
    ("mydroid", DROID | BLASTER, 0, 0, 0xFF),
    ("myguard", 0, 0, 0, 0xFF),
    ("luminara", JEDI, 0, 0, 0xFF),
    ("shaakti", JEDI, 0, 0, 0xFF),
    ("kiadimundi", JEDI, 0, 0, 0xFF),
    ("kitfisto", JEDI, 0, 0, 0xFF),
    ("geonosian", BLASTER, 0, 0, 0xFF),
    ("battledroid_geonosian", DROID | BLASTER, 0, 0, 0xFF),
    ("bob", 0, 0, 0, 0xFF),
    ("mystery", BLASTER, 0, 0, 0xFF),
]

INI = {
    "characters": {"battledroid": "behaviour=standard bullet=ewokpebble pull_levers=on",
                   "c3po": "behaviour=jedi", "mystery": "acts_as=ewok"},
    "arena": {"enabled": "1", "jedi": "luminara,shaakti,kiadimundi,kitfisto",
              "max_jedi_at_once": "3", "respawn": "1", "in_freeplay": "0"},
}


def parse_keywords(m, index, text, table=None):
    """Run the game's own character tokenizer and keyword dispatch (FUN_00589410's loop) on text."""
    m.uc.mem_write(0x954400, bytes(0xFC8))  # the loader clears its parse state first
    m.w32(0x954400, m.r32(0x93B274) + index * 0x4C)
    m.w32(0x954404, m.r32(0x93B284) + index * 0x120)
    m.w16(0x95441C, index)
    m.w32(0x954418, m.alloc(0x6B4 * 2))
    m.w32(0x954408, m.alloc(0x400))
    table = table or m.r32(0x5896D7)
    buf = m.alloc(text.encode() + b"\0")
    m.call(0x54BE70, buf, buf, 1)  # the loader's own clean-up pass over the file text (= becomes a space)
    ctx = m.call(0x4FC900, m.alloc(b"character\0"), buf, 0xFFFF)
    if not ctx:
        raise RuntimeError("tokenizer did not open")
    m.call(0x4F1160, ctx, table, 0)
    while m.call(0x4FC5B0, ctx):
        if m.call(0x4F7FB0, ctx):
            m.call(0x4FA020, ctx)
    m.call(0x4FA300, ctx)


def main():
    if not os.path.exists(DLL):
        sys.exit("build the test DLL first: build_test.bat")

    # --- start-up path ---------------------------------------------------------------------------------------
    m = Machine(INI)
    stock = {a: m.rbytes(a, 5) for a in (0x5896D6, 0x48ABFD, 0x407E40, 0x55E470, 0x55F360, 0x4DEABD, 0x4DF8B9, 0x454593, 0x4B6100, 0x4B6052, 0x41EACD, 0x41EB4D, 0x42C72A, 0x4B1D99, 0x41A919, 0x41C0D3, 0x41CB0E, 0x429B8F, 0x4B3D51, 0x4CB2A2, 0x4B4B35, 0x4BFDCA)}
    real = m.r32(IAT_GETCOMMANDLINEA)
    check("installs on the supported build", m.install() == 1)
    hooked = m.r32(IAT_GETCOMMANDLINEA)
    check("redirects the GetCommandLineA import into the patch", hooked != real and hooked >= m.dll_base)

    m.uc.mem_write(0x5896D6, b"\x11\x22\x33\x44\x55")  # still encrypted: no patching yet
    got = m.start_game_code()
    check("encrypted code: passes through without patching",
          m.cstr(got) == "LEGOStarWarsSaga.exe" and m.rbytes(0x407E40, 5) == stock[0x407E40]
          and m.r32(IAT_GETCOMMANDLINEA) == hooked)
    m.uc.mem_write(0x5896D6, stock[0x5896D6])

    got = m.start_game_code()
    changed = [hex(a) for a, b in stock.items() if m.rbytes(a, 5) != b]
    check("decrypted code: patches every site", len(changed) == 22, ", ".join(changed))
    check("restores the real GetCommandLineA and returns its result",
          m.r32(IAT_GETCOMMANDLINEA) == real and m.cstr(got) == "LEGOStarWarsSaga.exe")

    table = m.r32(0x5896D7)
    names = []
    while m.r32(table + 8 * len(names)):
        names.append(m.cstr(m.r32(table + 8 * len(names))))
    check("keyword table: 207 stock keywords kept, 11 added, terminated",
          len(names) == 218 and names[:207] == [m.cstr(m.r32(0x804248 + 8 * i)) for i in range(207)]
          and names[207:] == ["behaviour", "behavior", "bullet", "pull_levers", "drive_vehicles", "can_jump", "enter_vehicles", "blade_style", "geonosian_variant", "weapon_always_out", "acts_as"], f"{len(names)} entries")

    other = Machine(INI, timestamp=0x12345678)
    check("refuses another build (timestamp)", other.install() == 0 and other.r32(IAT_GETCOMMANDLINEA) != 0
          and other.rbytes(0x407E40, 5) == stock[0x407E40])

    # --- keywords through the game's own parser ----------------------------------------------------------------
    idx = m.make_definitions(CHARS)
    for name in ("ewok", "imperialguard", "geonosian", "battledroid_geonosian", "bob", "luminara", "shaakti",
                 "battledroid"):
        try:
            m.set_id(name, idx[name])
        except KeyError:
            pass
    parse_keywords(m, idx["mydroid"], 'hit_points=4\nbehaviour="standard"\nbullet="geonosian"\npull_levers\ndrive_vehicles\ncan_jump\nenter_vehicles\nblade_style="double"\ngeonosian_variant\nweapon_always_out\n')
    parse_keywords(m, idx["myguard"], 'weapon_locator=0\nbehaviour="jedi"\nbullet=43\npull_levers off\ndrive_vehicles off\nblade_style=staff\n')
    hp = m.rbytes(m.r32(0x93B284) + idx["mydroid"] * 0x120 + 0xF4, 1)[0]
    check("stock keyword still parsed next to the new ones (hit_points=4)", hp == 4, f"hit_points {hp}")

    # --- behaviour assignment (the game's FUN_00414400 through the patched call) --------------------------------
    m.run(0x48ABFD, 0x48AC02)
    r = {n: m.routine(i) for n, i in idx.items()}
    check("stock rules unchanged: jedi, droid, droid+bounty hunter, Royal Guard",
          r["lukeskywalker"] == ROUTINE["jedi"] and r["battledroid_geonosian"] == ROUTINE["droid"]
          and r["ig88"] == ROUTINE["standard"] and r["imperialguard"] == ROUTINE["jedi"],
          ", ".join(f"{k} {r[k]:X}" for k in ("lukeskywalker", "battledroid_geonosian", "ig88", "imperialguard")))
    check("behaviour= from a character file: droid -> standard, non-jedi -> jedi",
          r["mydroid"] == ROUTINE["standard"] and r["myguard"] == ROUTINE["jedi"])
    check("[characters] in the INI: battledroid -> standard, c3po -> jedi",
          r["battledroid"] == ROUTINE["standard"] and r["c3po"] == ROUTINE["jedi"])

    # each further behaviour name gives exactly what the game's own rules give a character with that variant/flag
    kinds = {"cannon": (0, 0x800, 0xFF), "vehicle": (0x2000, 0, 0xFF), "battledroid": (0, 0, 4),
             "hoverdroid": (0, 0, 0x11), "walker2legs": (0, 0, 0xF), "walker4legs": (0, 0, 0x10),
             "critter": (0, 0, 0x12), "pod": (0, 0, 0x14), "weirdo": (0, 0, 0)}
    bm = Machine({"characters": {f"as_{k}": f"behaviour={k}" for k in kinds}})
    bm.install()
    bm.start_game_code()
    bidx = bm.make_definitions([(f"ref_{k}", fa, f90, 0, v) for k, (fa, f90, v) in kinds.items()]
                               + [(f"as_{k}", 0, 0, 0, 0xFF) for k in kinds])
    bm.run(0x48ABFD, 0x48AC02)
    a_base = bm.r32(0x93B274)
    triple = lambda i: tuple(bm.r32(a_base + i * 0x4C + o) for o in (0x18, 0x1C, 0x20))
    same = {k: triple(bidx[f"as_{k}"]) == triple(bidx[f"ref_{k}"]) for k in kinds}
    check("behaviour= cannon, vehicle, battledroid, hoverdroid, walker2legs/4legs, critter, pod, weirdo: "
          "routine, AI and extra equal the game's own assignment for that variant or flag",
          all(same.values()) and len({triple(bidx[f"ref_{k}"])[0] for k in kinds}) >= 8,
          ", ".join(k for k, ok in same.items() if not ok))

    # --- projectile picker ---------------------------------------------------------------------------------------
    pick = lambda name, default=0: m.call(0x407E40, m.make_instance(idx[name]), default)
    check("bullet= by name (geonosian = 0x13) and by number (43 = spear)",
          pick("mydroid") == 0x13 and pick("myguard") == 43, f"{pick('mydroid'):#x}, {pick('myguard')}")
    check("bullet from the INI (battledroid -> ewokpebble 0x1B)", pick("battledroid") == 0x1B)
    check("stock picker kept: ewok -> 0x1B, others -> the caller's default",
          pick("ewok") == 0x1B and pick("hansolo", 5) == 5 and m.call(0x407E40, 0, 7) == 7,
          f"ewok {pick('ewok'):#x}, hansolo {pick('hansolo', 5)}")

    # --- lever rule ----------------------------------------------------------------------------------------------
    lever = lambda name, fn=0x55E470: m.call(fn, idx[name])
    check("lever rule stock: jedi and blaster yes, droid+bounty hunter and protocol no",
          lever("lukeskywalker") == 1 and lever("hansolo") == 1 and lever("ig88") == 0 and lever("c3po") == 0)
    check("pull_levers / pull_levers off override both lever rules",
          lever("mydroid") == 1 and lever("myguard") == 0 and lever("myguard", 0x55F360) == 0
          and lever("battledroid", 0x55F360) == 1)

    # --- scripted vehicle take-over (FUN_004543E0's droid test) --------------------------------------------------
    def takeover(name):
        """Run the patched test; True when the take-over goes ahead."""
        stops = []

        def stop(uc, address, size, user):
            if address in (0x45459C, 0x4545C3):
                stops.append(address)
                uc.emu_stop()
        h = m.uc.hook_add(UC_HOOK_CODE, stop, begin=0x45459C, end=0x4545C3)
        m.run(0x454593, 0x4545CD, regs={UC_X86_REG_EDX: m.make_instance(idx[name])})
        m.uc.hook_del(h)
        return stops[:1] == [0x45459C]
    check("vehicle take-over: stock droid refused, others allowed",
          not takeover("battledroid_geonosian") and takeover("hansolo") and not takeover("ig88"))
    check("drive_vehicles / drive_vehicles off override the droid test",
          takeover("mydroid") and not takeover("myguard"))

    # --- droid routine: jump arguments and vehicle entry ---------------------------------------------------------
    def droid_jump_args(name):
        inst = m.make_instance(idx[name])
        m.run(0x4B6100, 0x4B6110, regs={UC_X86_REG_ESI: inst, UC_X86_REG_EBX: 0x11, UC_X86_REG_EDI: 0x22})
        sp = m.uc.reg_read(UC_X86_REG_ESP)
        return [m.r32(sp + 4 * k) for k in range(7)], inst
    args, inst = droid_jump_args("battledroid_geonosian")
    check("droid routine stock: jump called with no buttons and flag 0x80",
          args == [inst, 0, 0, 0x80, 0, 0, 0xFFFFFFFF], " ".join(f"{a:X}" for a in args))
    args, inst = droid_jump_args("mydroid")
    check("can_jump: the droid routine passes the jump buttons and the standard flag 8",
          args == [inst, 0x11, 0x22, 8, 0, 0, 0xFFFFFFFF], " ".join(f"{a:X}" for a in args))

    def droid_vehicle_entry(name):
        inst = m.make_instance(idx[name])
        ctl = m.alloc(0x40)
        m.w32(ctl + 8, 0xFFFFFFFF)  # every button pressed
        m.w32(inst + 0xCA4, ctl)
        seen = []

        def fake(uc, address, size, user):  # stand in for the two game calls; record their arguments
            sp = uc.reg_read(UC_X86_REG_ESP)
            seen.append((address, m.r32(sp + 4), m.r32(sp + 8)))
            uc.reg_write(UC_X86_REG_ESP, sp + 4)
            uc.reg_write(UC_X86_REG_EIP, m.r32(sp))
        hooks = [m.uc.hook_add(UC_HOOK_CODE, fake, begin=a, end=a) for a in (0x49D720, 0x488770)]
        sp0 = STACK + STACK_SIZE - 0x1000
        m.run(0x4B6052, 0x4B6058, regs={UC_X86_REG_ESI: inst})
        pushed = m.uc.reg_read(UC_X86_REG_ESP) == sp0 - 4 and m.r32(sp0 - 4) == inst
        for h in hooks:
            m.uc.hook_del(h)
        return seen, inst, pushed
    seen, inst, pushed = droid_vehicle_entry("battledroid_geonosian")
    check("droid routine stock: FUN_0049D720 still called, no vehicle entry, stack as before",
          [a for a, _, _ in seen] == [0x49D720] and seen[0][1] == inst and pushed)
    seen, inst, pushed = droid_vehicle_entry("mydroid")
    mask = m.r32(0x802284)
    check("enter_vehicles: the droid routine also calls vehicle entry with the standard button mask",
          [a for a, _, _ in seen] == [0x49D720, 0x488770] and seen[1][1:] == (inst, mask) and pushed,
          f"mask {mask:X}")

    # --- blade styles: the saber code sees the character under the stock name for one call ------------------------
    def saber_call(site, name, regs_char=False):
        """Run one patched call site with the game function replaced by a recorder."""
        inst = m.make_instance(idx[name])
        target = {0x41EACD: 0x41DAD0, 0x41EB4D: 0x41DAD0, 0x42C72A: 0x49F850, 0x4B1D99: 0x4A0900}[site]
        seen = {}

        def record(uc, address, size, user):
            sp = uc.reg_read(UC_X86_REG_ESP)
            seen["args"] = [m.r32(sp + 4 * k) for k in range(1, 4)]
            seen["eax"] = uc.reg_read(UC_X86_REG_EAX)
            seen["ids"] = {g: m.r16s(g) for g in (0x7F1880, 0x7F187C, 0x7F1968, 0x7F1A08)}
            uc.reg_write(UC_X86_REG_EAX, 0x5A5A)
            uc.reg_write(UC_X86_REG_ESP, sp + 4)
            uc.reg_write(UC_X86_REG_EIP, m.r32(sp))
        h = m.uc.hook_add(UC_HOOK_CODE, record, begin=target, end=target)
        sp0 = STACK + STACK_SIZE - 0x1000
        m.w32(sp0 - 4, 0xA1)   # what the game pushed before the call: up to three arguments
        m.w32(sp0 - 8, 0xB2)
        m.w32(sp0 - 12, inst if not regs_char else 0xC3)
        m.uc.reg_write(UC_X86_REG_ESP, sp0 - 12)
        m.uc.reg_write(UC_X86_REG_EAX, inst if regs_char else 0)
        m.uc.emu_start(site, site + 5, count=1_000_000)
        m.uc.hook_del(h)
        after = {g: m.r16s(g) for g in (0x7F1880, 0x7F187C, 0x7F1968, 0x7F1A08)}
        return seen, inst, after, m.uc.reg_read(UC_X86_REG_EAX), m.uc.reg_read(UC_X86_REG_ESP) == sp0 - 12

    for g, v in ((0x7F1880, 300), (0x7F187C, 301), (0x7F1968, 302), (0x7F1A08, 303)):
        m.w16(g, v)
    stock_ids = {0x7F1880: 300, 0x7F187C: 301, 0x7F1968: 302, 0x7F1A08: 303}
    seen, inst, after, eax, sp_ok = saber_call(0x41EACD, "mydroid")
    check("saber draw: arguments passed through in order, Maul's name points at the character during the call",
          seen["args"] == [inst, 0xB2, 0xA1] and seen["ids"][0x7F1880] == idx["mydroid"], str(seen["args"]))
    check("saber draw: names restored, result and stack as the game expects",
          after == stock_ids and eax == 0x5A5A and sp_ok)
    seen, inst, after, eax, sp_ok = saber_call(0x4B1D99, "myguard", regs_char=True)
    check("saber streaks (character in EAX): MagnaGuard's name points at a staff character, then restored",
          seen["eax"] == inst and seen["args"][0] == 0xC3 and seen["ids"][0x7F187C] == idx["myguard"]
          and after == stock_ids and sp_ok)
    seen, inst, after, eax, sp_ok = saber_call(0x42C72A, "hansolo")
    check("saber glow: a character without blade_style changes nothing",
          seen["args"][0] == inst and seen["ids"] == stock_ids and after == stock_ids and sp_ok)

    # --- Geonosian checks: ZF as before for the Geonosian and others, set for an opted-in character -------------
    from unicorn.x86_const import UC_X86_REG_EFLAGS

    def geo_zf(site, ident):
        reg = UC_X86_REG_EAX if stock[site][2] == 0x05 else UC_X86_REG_ECX  # register of the original cmp
        regs = {UC_X86_REG_EAX: 0x11110000, UC_X86_REG_ECX: 0x22220000, UC_X86_REG_EDX: 0x33333333}
        regs[reg] = (regs[reg] & 0xFFFF0000) | (ident & 0xFFFF)
        m.run(site, site + 7, regs=regs)
        same = all(m.uc.reg_read(r) == v for r, v in regs.items())
        return bool(m.uc.reg_read(UC_X86_REG_EFLAGS) & 0x40), same
    geo_sites = [0x41A919, 0x41C0D3, 0x41CB0E, 0x429B8F, 0x4B3D51, 0x4CB2A2]
    results = {n: [geo_zf(a, idx[n]) for a in geo_sites] for n in ("geonosian", "mydroid", "hansolo")}
    check("all six Geonosian checks: the Geonosian still matches, others still do not, registers kept",
          all(z and k for z, k in results["geonosian"]) and all(not z and k for z, k in results["hansolo"]))
    check("geonosian_variant: an opted-in character matches at all six checks",
          all(z and k for z, k in results["mydroid"]))

    # --- weapon always out: the last name test before FUN_0058D8B0 ------------------------------------------------
    m.set_id("captaintarpals", idx["shaakti"])

    def weapon_out_zf(name):
        m.run(0x4B4B35, 0x4B4B3C, regs={UC_X86_REG_EAX: 0xABCD0000 | idx[name], UC_X86_REG_EDX: 0x1234})
        kept = m.uc.reg_read(UC_X86_REG_EAX) == 0xABCD0000 | idx[name] and m.uc.reg_read(UC_X86_REG_EDX) == 0x1234
        return bool(m.uc.reg_read(UC_X86_REG_EFLAGS) & 0x40) and kept, kept
    check("weapon always out: Tarpals still matches, others do not, an opted-in character does",
          weapon_out_zf("shaakti")[0] and not weapon_out_zf("hansolo")[0] and weapon_out_zf("hansolo")[1]
          and weapon_out_zf("mydroid")[0])

    # --- Ewok rock sounds in the level preload ---------------------------------------------------------------------
    def rock_sounds(name):
        stops = []

        def stop(uc, address, size, user):
            stops.append(address)
            uc.emu_stop()
        hs = [m.uc.hook_add(UC_HOOK_CODE, stop, begin=a, end=a) for a in (0x4BFDE0, 0x4BFE15)]
        m.run(0x4BFDCA, 0x4C0000, regs={UC_X86_REG_EBX: idx[name]})
        for h in hs:
            m.uc.hook_del(h)
        return stops[:1] == [0x4BFDE0]
    check("rock sounds: loaded for Ewok and for a character firing Ewok pebbles, not for others",
          rock_sounds("ewok") and rock_sounds("battledroid") and not rock_sounds("hansolo")
          and not rock_sounds("mydroid"))

    # --- Ewok projectile models: the owner's icon scene is loaded with the level ----------------------------------
    def level_icons(names):
        """Run the level load's icon call (0x0048B2EB) on a character list; return the icon indices loaded."""
        n = m.r32(0x93B278)
        for i in range(n):
            m.w16(m.r32(0x93B274) + i * 0x4C + 0x42, 100 + i)   # each character's icon index
        m.w32(0x93B270, m.alloc(4 * n))                         # icon scene table, nothing loaded yet
        lst = b"".join(struct.pack("<hh", idx[x], 1) for x in names) + struct.pack("<hh", -1, 0)
        loaded, scene = [], m.alloc(0x200)

        def icon_name(uc, address, size, user):   # FUN_0057A360(icon index) -> name
            sp = uc.reg_read(UC_X86_REG_ESP)
            loaded.append(m.r32(sp + 4))
            uc.reg_write(UC_X86_REG_EAX, m.alloc(b"icon\0"))
            uc.reg_write(UC_X86_REG_ESP, sp + 4)
            uc.reg_write(UC_X86_REG_EIP, m.r32(sp))

        def load_scene(uc, address, size, user):  # FUN_005EF7F0(heap, limit, path) -> a scene
            sp = uc.reg_read(UC_X86_REG_ESP)
            uc.reg_write(UC_X86_REG_EAX, scene)
            uc.reg_write(UC_X86_REG_ESP, sp + 4)
            uc.reg_write(UC_X86_REG_EIP, m.r32(sp))
        hs = [m.uc.hook_add(UC_HOOK_CODE, icon_name, begin=0x57A360, end=0x57A360),
              m.uc.hook_add(UC_HOOK_CODE, load_scene, begin=0x5EF7F0, end=0x5EF7F0)]
        m.run(0x48B2D8, 0x48B2F0, regs={UC_X86_REG_ESI: m.alloc(lst)})
        for h in hs:
            m.uc.hook_del(h)
        return [i - 100 for i in loaded]
    got = [level_icons(["battledroid"]), level_icons(["hansolo"]), level_icons(["ewok", "battledroid", "hansolo"])]
    check("projectile models: the Ewok's icon is loaded with a character firing Ewok pebbles, once, "
          "and nothing extra for others",
          got == [[idx["battledroid"], idx["ewok"]], [idx["hansolo"]], [idx["ewok"], idx["battledroid"], idx["hansolo"]]],
          f"{got}; ewok {idx['ewok']} battledroid {idx['battledroid']} hansolo {idx['hansolo']}")

    # --- Geonosis arena --------------------------------------------------------------------------------------------
    slots = 0x882BD0
    m.w16(0x888ED0, 8)
    m.w32(0x888FB8, 0)
    m.w32(0x93B2A4, 0)  # story mode
    jedi_ids = {idx[n] for n in ("luminara", "shaakti", "kiadimundi", "kitfisto")}

    def pick_slot(i, flag2=True):
        s = slots + i * 0x60
        m.w32(s + 0x5C, 2 if flag2 else 0)
        m.run(0x4DEABD, 0x4DEAC2, regs={UC_X86_REG_ESI: s, UC_X86_REG_ECX: 0x1111, UC_X86_REG_EDX: 0x2222})
        kept = m.uc.reg_read(UC_X86_REG_ESI) == s and m.uc.reg_read(UC_X86_REG_ECX) == 0x1111 \
            and m.uc.reg_read(UC_X86_REG_EDX) == 0x2222
        return m.r32(s + 0x10), kept

    for i in range(8):
        m.w32(slots + i * 0x60 + 0x10, 0xFFFFFFFF)
    picked = [pick_slot(i) for i in range(6)]
    types = [t for t, _ in picked]
    jedi_now = [t for t in types if t in jedi_ids]
    check("arena: at most max_jedi_at_once (3) Jedi, in list order, the rest Geonosians",
          [m.cstr(m.r32(m.r32(0x93B274) + t * 0x4C + 0x0C)) for t in jedi_now] == ["luminara", "shaakti", "kiadimundi"]
          and all(t in (idx["geonosian"], idx["battledroid_geonosian"]) for t in types[3:]),
          f"types {types}")
    check("arena stub keeps the caller's registers (esi, ecx, edx)", all(k for _, k in picked))
    m.w32(slots + 0 * 0x60 + 0x10, idx["geonosian"])  # luminara's slot became something else
    t, _ = pick_slot(6)
    check("arena: a freed Jedi place is refilled with the next Jedi (respawn on)", t == idx["kitfisto"],
          f"type {t}")
    t, _ = pick_slot(7, flag2=False)
    check("arena: slots without flag 2 still get bob", t == idx["bob"])
    m.w32(0x93B2A4, 1)  # free play, in_freeplay = 0
    for i in range(8):
        m.w32(slots + i * 0x60 + 0x10, idx["geonosian"])
    t, _ = pick_slot(0)
    check("arena: no Jedi in Free Play unless in_freeplay = 1", t not in jedi_ids)

    # --- every stock character file parses exactly as before ----------------------------------------------------
    chars_dir = os.environ.get("TCS_CHARS", r"C:\LegoBatman\extracted\starwars\game\CHARS")
    if os.path.isdir(chars_dir):
        files = sorted({os.path.join(d, f) for d, _, fs in os.walk(chars_dir) for f in fs
                        if f.lower().endswith(".txt") and f.lower() != "chars.txt"})
        same = differ = skipped = 0
        base_a, base_b = m.r32(0x93B274), m.r32(0x93B284)
        for f in files:
            text = open(f, "rb").read().decode("latin1")
            out = []
            try:
                for table in (0x804248, None):
                    sa, sb = m.alloc(0x4C), m.alloc(0x120)
                    m.uc.mem_write(sb, bytes(m.rbytes(0x802968, 0x120)))
                    m.w32(0x93B274, sa)
                    m.w32(0x93B284, sb)
                    m.w32(sa + 0x24, sb)
                    parse_keywords(m, 0, text, table)
                    out.append(m.rbytes(sa, 0x24) + m.rbytes(sa + 0x28, 0x24) + m.rbytes(sb + 8, 0x118))
            except (UcError, RuntimeError) as e:
                print("   not runnable here:", os.path.relpath(f, chars_dir), "-", e)
                skipped += 1
                continue
            if out[0] == out[1]:
                same += 1
            else:
                differ += 1
                print("   differs:", os.path.relpath(f, chars_dir))
        m.w32(0x93B274, base_a)
        m.w32(0x93B284, base_b)
        check("every stock character file gives the same definition with the patched keyword table",
              differ == 0 and same > 300, f"{same} same, {differ} different, {skipped} not runnable here")
    else:
        print(f"(skipped stock-file check: no {chars_dir})")

    # --- arena with an empty Jedi list: no Jedi, no crash ----------------------------------------------------------
    empty = Machine({"arena": {"enabled": "1", "jedi": ""}})
    empty.install()
    empty.start_game_code()
    eidx = empty.make_definitions(CHARS)
    empty.set_id("geonosian", eidx["geonosian"])
    empty.set_id("battledroid_geonosian", eidx["battledroid_geonosian"])
    empty.w16(0x888ED0, 1)
    empty.w32(0x882BD0 + 0x5C, 2)
    empty.run(0x4DEABD, 0x4DEAC2, regs={UC_X86_REG_ESI: 0x882BD0})
    t = empty.r32(0x882BD0 + 0x10)
    check("arena with an empty Jedi list only spawns Geonosians",
          t in (eidx["geonosian"], eidx["battledroid_geonosian"]), f"type {t}")

    # --- acts_as: the character also counts as a stock character at the game's name checks ---------------------
    sys.path.insert(0, os.path.join(HERE, "..", "tools"))
    sites = [int(l.split()[1].rstrip("u,"), 16) for l in open(os.path.join(HERE, "..", "src", "acts_as_table.h"))
             if l.strip().startswith("{ 0x")]
    patched = sum(1 for a in sites if m.rbytes(a, 1)[0] == 0xE8)
    check("acts_as: installed at every listed name check once a character uses it", patched == len(sites) == 528,
          f"{patched} of {len(sites)}")
    ewok_site = next(int(l.split()[1].rstrip("u,"), 16) for l in open(os.path.join(HERE, "..", "src", "acts_as_table.h"))
                     if "/* ewok */" in l and ", 0, " in l)

    def name_check(site, ident):
        regs = {UC_X86_REG_EAX: 0x7AB0000 | (ident & 0xFFFF), UC_X86_REG_ECX: 0x1234, UC_X86_REG_EDX: 0x5678}
        m.run(site, site + 7, regs=regs)
        kept = all(m.uc.reg_read(r) == v for r, v in regs.items())
        return bool(m.uc.reg_read(UC_X86_REG_EFLAGS) & 0x40), kept
    from unicorn.x86_const import UC_X86_REG_EFLAGS
    res = {n: name_check(ewok_site, idx[n]) for n in ("ewok", "mystery", "hansolo")}
    check("acts_as: an \"is it Ewok?\" check matches Ewok and the character acting as Ewok, not others; registers kept",
          res["ewok"] == (True, True) and res["mystery"] == (True, True) and res["hansolo"] == (False, True),
          str(res))
    check("acts_as through real game code: the projectile picker gives the Ewok pebble (0x1B) to the stand-in",
          m.call(0x407E40, m.make_instance(idx["mystery"]), 0) == 0x1B)

    # --- party size 12 (experimental) ----------------------------------------------------------------------------
    sys.path.insert(0, os.path.join(HERE, "..", "tools"))
    import party_reloc_gen as prg
    import capstone
    pm = Machine({"party": {"max": "12"}})
    relocs = prg.scan(EXE)
    pm.install()
    pm.start_game_code()
    n = 12
    bases, consistent, decodes = {}, True, True
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    stock_img = pefile.PE(EXE).get_memory_mapped_image()
    hook_sites = {0x41F971, 0x493011, 0x428796, 0x43FD12, 0x48FB63, 0x42C019, 0x42C10B, 0x4EBF43, 0x55C30A, 0x55C51B}
    for addr, off, old, r, kind, text in relocs:
        if addr in hook_sites:          # replaced by a jump to a follow-up stub (tested below)
            continue
        name, start, stride, slots, end = prg.REGIONS[r]
        new = pm.r32(addr + off)
        o = old - start
        if r == 0 and o >= 32:
            o += (n - 8) * 4
        base = (new - o) & 0xFFFFFFFF
        if bases.setdefault(r, base) != base:
            consistent = False
        ins_new = next(md.disasm(pm.rbytes(addr, 16), addr))
        ins_old = next(md.disasm(stock_img[addr - 0x400000:addr - 0x400000 + 16], addr))
        if ins_new.mnemonic != ins_old.mnemonic or ins_new.size != ins_old.size                 or ins_new.op_str.replace(hex(new), hex(old)) != ins_old.op_str:
            decodes = False
    check("no [party] setting: none of the address fields or hook sites changes",
          all(m.r32(a + o) == old for a, o, old, *_ in relocs)
          and all(m.rbytes(a, 10) == stock_img[a - 0x400000:a - 0x400000 + 10] for a in hook_sites | {0x4922C8}))
    sizes = {r: prg.REGIONS[r][4] - prg.REGIONS[r][1] + (n - 8) * prg.REGIONS[r][2] for r in bases}
    spans = sorted((bases[r], bases[r] + sizes[r]) for r in bases)
    apart = all(a2 >= b1 for (a1, b1), (a2, b2) in zip(spans, spans[1:]))
    check("party 12: every address field (1057) moved consistently into its own new region",
          consistent and apart and len(bases) == len(prg.REGIONS), f"{len(relocs)} fields, {len(bases)} regions")
    check("party 12: every rewritten instruction decodes as before, with only the address changed", decodes)
    bounds_ok = all(pm.rbytes(a + o, 1)[0] == v for a, o, v in (
        (0x40C637, 2, 12), (0x41FA95, 2, 12), (0x574426, 1, 12), (0x483B60, 2, 11), (0x43D469, 2, 12),
        (0x41B828, 1, 12))) and pm.r32(0x414E7D + 1) == 12 and pm.r32(0x404DCA + 1) == 12
    check("party 12: loop bounds raised (unlock list to 11)", bounds_ok)

    # the game's own party builder with a level list of 12 characters
    pidx = pm.make_definitions(CHARS)
    game = pm.alloc(0x3000)
    level = pm.alloc(0x200)
    pm.uc.mem_write(level + 100, bytes([2]))
    pm.w32(game + 0x128, level)
    pm.w32(0x802C54, game)
    loaded = pm.alloc(0x400)          # +0x1C: per-character "loaded" table (0 = loaded)
    defs_holder = pm.alloc(0x40)
    pm.w32(defs_holder + 0x1C, loaded)
    pm.w32(defs_holder + 0x20, pm.r32(0x93B274))
    pm.w32(0x29130E4, defs_holder)
    for a in (0x951B50, 0x93B2A4, 0x93D81C, 0x87B2D4):
        pm.w32(a, 0)
    ids = [pidx[c[0]] for c in CHARS[:12]]
    level_ids = bases[7]                # LEVEL_IDS region, moved
    for k, i in enumerate(ids + [-1]):
        pm.w16(level_ids + 2 * k, i)
    made = []

    def stub(uc, address, size, user):
        if address in (0x41C7C0, 0x498A40, 0x4B6B80, 0x4D22B0, 0x55C9F0):
            sp = uc.reg_read(UC_X86_REG_ESP)
            result = 0
            if address == 0x55C9F0:
                result = pm.alloc(0x1100)
                made.append(result)
            uc.reg_write(UC_X86_REG_EAX, result)
            uc.reg_write(UC_X86_REG_ESP, sp + 4)
            uc.reg_write(UC_X86_REG_EIP, pm.r32(sp))
    h = pm.uc.hook_add(UC_HOOK_CODE, stub, begin=0x41C7C0, end=0x55C9F0)
    pm.call(0x41F940)
    pm.uc.hook_del(h)
    party = [pm.r32(bases[0] + 4 * k) for k in range(12)]
    slots = [pm.rbytes(p_ + 0x280, 1)[0] for p_ in party if p_]
    check("party 12: the game's party builder fills 12 slots from a 12-character level list",
          party == made[:12] and len(made) == 12 and pm.r32(0x93D818) == 12 and slots == list(range(12)),
          f"{len(made)} made, count {pm.r32(0x93D818)}, slots {slots}")
    stock_party = [m.r32(0x93D7F0 + 4 * k) for k in range(8)]
    check("party 12: the stock array is no longer written (the moved one is used)",
          all(pm.r32(0x93D7F0 + 4 * k) == 0 for k in range(8)))

    # follow-ups for code written out once per slot: slots 8..11 get what slots 0..7 get
    extras = [pm.alloc(0x1100) for _ in range(4)]
    slot7 = pm.alloc(0x1100)

    def setup():
        pm.w32(bases[0] + 4 * 7, slot7)
        for k, e in enumerate(extras):
            pm.w32(bases[0] + 4 * (8 + k), e)

    def hook_run(site, length, regs=None):
        setup()
        r = {UC_X86_REG_EAX: 0x1111, UC_X86_REG_EBX: 0x80, UC_X86_REG_ECX: 0x3333, UC_X86_REG_EDX: 0x4444,
             UC_X86_REG_ESI: 0x5555, UC_X86_REG_EDI: 0x6666}
        r.update(regs or {})
        pm.uc.reg_write(UC_X86_REG_EFLAGS, 0x246)
        pm.run(site, site + length, regs=r)
        kept = {k: pm.uc.reg_read(k) for k in r}
        return r, kept, pm.uc.reg_read(UC_X86_REG_EFLAGS)

    from unicorn.x86_const import UC_X86_REG_EFLAGS
    r, kept, fl = hook_run(0x43FD12, 5, {UC_X86_REG_ECX: 0xFFFFBFFF})
    for e in extras + [slot7]:
        pass
    ok_and = all(pm.r32(e + 0x4B0) == 0 for e in extras)
    for e in extras:
        pm.w32(e + 0x4B0, 0xFFFFFFFF)
    r, kept, fl = hook_run(0x43FD12, 5, {UC_X86_REG_ECX: 0xFFFFBFFF})
    check("follow-up FUN_0043E530: extra members get +0x4B0 &= ecx; the moved slot 7 is loaded; registers kept",
          all(pm.r32(e + 0x4B0) == 0xFFFFBFFF for e in extras) and kept[UC_X86_REG_EAX] == slot7
          and all(kept[k] == v for k, v in r.items() if k != UC_X86_REG_EAX))
    for e in extras:
        pm.w32(e + 0xEF0, 0xFFFFFFFF)
    r, kept, fl = hook_run(0x428796, 7, {UC_X86_REG_EDX: 0xFFDFFFFF})
    check("follow-up FUN_00427EC0: +0xEF0 &= edx, and the slot 7 compare still sets the flags (non-zero)",
          all(pm.r32(e + 0xEF0) == 0xFFDFFFFF for e in extras) and not (fl & 0x40) and kept == r)
    r, kept, fl = hook_run(0x42C019, 5)
    check("follow-up FUN_0042B960 first block: +0xE39 = 4", all(pm.rbytes(e + 0xE39, 1)[0] == 4 for e in extras))
    pm.uc.mem_write(extras[0] + 0x1FC, bytes([0x80]))
    pm.uc.mem_write(extras[1] + 0x1FC, bytes([0x00]))
    pm.w32(extras[1] + 0x1000, 0x12345678)
    r, kept, fl = hook_run(0x42C10B, 5, {UC_X86_REG_EBX: 0x80})
    check("follow-up FUN_0042B960 second block: +0x1000 is the constant when bit 0x80 is set, else 0",
          pm.r32(extras[0] + 0x1000) == pm.r32(0x751C40) and pm.r32(extras[1] + 0x1000) == 0)
    for k, e in enumerate(extras):
        pm.uc.mem_write(e + 0x107E, bytes([3 + k]))
    pm.uc.mem_write(0x802BD4, bytes([4]))
    r, kept, fl = hook_run(0x48FB63, 5)
    check("follow-up FUN_0048F9B0: hearts copied (+0x107E to +0x107F) and each record's byte 8 set",
          all(pm.rbytes(e + 0x107F, 1)[0] == 3 + k for k, e in enumerate(extras))
          and all(pm.rbytes(bases[1] + 0x10 * k + 8, 1)[0] == 4 for k in range(8, 12)))
    mask_owner = pm.alloc(0x1000)
    pm.w32(0x87A7F0, mask_owner)
    for k, e in enumerate(extras):
        pm.uc.mem_write(e + 0x28D, bytes([30 + 2 * k]))
    r, kept, fl = hook_run(0x4EBF43, 5, {UC_X86_REG_EBX: 1})
    want = sum(1 << (30 + 2 * k) for k in range(4))
    got = pm.r32(mask_owner + 0xEB8) | (pm.r32(mask_owner + 0xEBC) << 32)
    check("follow-up FUN_004EBDA0: each extra member's pool bit set in the 64-bit mask", got == want, hex(got))
    for e in extras:
        pm.w32(e + 0xD60, 7)
        pm.w32(e + 0xEE8, 7)
    r, kept, fl = hook_run(0x55C30A, 5)
    r2, kept2, fl2 = hook_run(0x55C51B, 5)
    check("follow-ups FUN_0055C120 / FUN_0055C350: +0xD60 = 0, +0xDA4 = the constant, +0xEE8 = 0",
          all(pm.r32(e + 0xD60) == 0 and pm.r32(e + 0xEE8) == 0 and pm.r32(e + 0xDA4) == pm.r32(0x802BE8)
              for e in extras))
    r, kept, fl = hook_run(0x493011, 5, {UC_X86_REG_EAX: 0})
    check("follow-up FUN_00492B40: slots 8..11 cleared with slot 7",
          all(pm.r32(bases[0] + 4 * k) == 0 for k in range(7, 12)))

    # ambient effects: the game's own code from the DAT_00947BBC test through both routine calls
    def ambient(members, positions, view=(0.0, 0.0, 0.0)):
        for k in range(12):
            pm.w32(bases[0] + 4 * k, members[k] if k < len(members) else 0)
        for p_, pos in zip(members, positions):
            if p_:
                pm.uc.mem_write(p_ + 0x19C, struct.pack("<3f", *pos))
        pm.uc.mem_write(0x973718, struct.pack("<3f", *view))
        pm.w32(0x947BBC, 1)
        sp0 = STACK + STACK_SIZE - 0x1000
        original = [0xA0000000 + k for k in range(8)]  # the list as the game built it on the stack
        for k, v in enumerate(original):
            pm.w32(sp0 + 0x28 + 4 * k, v)
        seen = []

        def fake(uc, address, size, user):
            sp = uc.reg_read(UC_X86_REG_ESP)
            arg = pm.r32(sp + 4)
            seen.append((address, arg, [pm.r32(arg + 4 * k) for k in range(8)]))
            uc.reg_write(UC_X86_REG_ESP, sp + 4)
            uc.reg_write(UC_X86_REG_EIP, pm.r32(sp))
        hooks = [pm.uc.hook_add(UC_HOOK_CODE, fake, begin=a, end=a) for a in (0x546380, 0x545A80)]
        pm.run(0x4922BF, 0x4922DF)
        for h in hooks:
            pm.uc.hook_del(h)
        return seen, original, sp0 + 0x28
    people = [pm.alloc(0x1100) for _ in range(12)]
    seen, original, at = ambient(people[:6] + [0, 0], [(k, 0, 0) for k in range(6)])
    check("party 12, ambient effects: members only in slots 0-7 leave the game's list untouched",
          [a for a, _, _ in seen] == [0x546380, 0x545A80] and all(s[1] == at and s[2] == original for s in seen))
    far = [(100.0 + k, 0, 0) for k in range(8)] + [(k, 0, 0) for k in range(4)]  # slots 8-11 nearest
    far[1] = (0.5, 0, 0)
    seen, original, at = ambient(people, far)
    want = [people[k] + 0x19C for k in (0, 1, 2, 3, 8, 9, 10, 11)]  # 8 nearest, in slot order
    check("party 12, ambient effects: with members in slots 8-11 both routines get the 8 nearest, in slot order",
          [a for a, _, _ in seen] == [0x546380, 0x545A80] and all(s[2] == want for s in seen),
          str([hex(v) for v in seen[0][2]]) if seen else "no calls")

    # --- [chain] dll: another dinput8 proxy (for example the four-player patch) ------------------------------------
    cm = Machine({"chain": {"dll": "fourplayer.dll"}, "party": {"max": "12"}})
    cm.install()
    cm.start_game_code()
    check("[chain] dll: the experimental party size is refused (the other patch reads the stock arrays)",
          all(cm.r32(a + o) == old for a, o, old, *_ in relocs)
          and all(cm.rbytes(a, 10) == stock_img[a - 0x400000:a - 0x400000 + 10] for a in hook_sites | {0x4922C8}))
    cm.call(cm.exports["DirectInput8Create"], 0x400000, 0x800, 0x1234, 0x5678, 0)
    cm.call(cm.exports["DirectInput8Create"], 0x400000, 0x800, 0x1234, 0x5678, 0)
    check("[chain] dll: DirectInput8Create loads the named file from the game folder once and forwards every call",
          cm.loaded == ["C:\\test\\fourplayer.dll"] and cm.di_calls == [[0x400000, 0x800, 0x1234, 0x5678, 0]] * 2,
          f"{cm.loaded} {len(cm.di_calls)}")
    bad = Machine({"chain": {"dll": "..\\other\\dinput8.dll"}})
    bad.install()
    bad.call(bad.exports["DirectInput8Create"], 0x400000, 0x800, 0x1234, 0x5678, 0)
    check("[chain] dll with a path, or dinput8.dll itself: ignored, the system dinput8 is used",
          bad.loaded == ["C:\\Windows\\System32\\dinput8.dll"], str(bad.loaded))

    # --- arena off: stock function untouched ------------------------------------------------------------------------
    off = Machine({"arena": {"enabled": "0"}})
    off.install()
    off.start_game_code()
    check("arena disabled: both arena calls left as in the game",
          off.rbytes(0x4DEABD, 5) == stock[0x4DEABD] and off.rbytes(0x4DF8B9, 5) == stock[0x4DF8B9])

    print(f"\n{sum(RESULTS)} of {len(RESULTS)} passed")
    sys.exit(0 if all(RESULTS) else 1)


if __name__ == "__main__":
    main()
