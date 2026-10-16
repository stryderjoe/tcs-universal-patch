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
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ECX, UC_X86_REG_EDX

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
            "GetPrivateProfileIntA": (4, lambda: self._ini_int(arg(0), arg(1), arg(2))),
            "GetPrivateProfileStringA": (6, lambda: self._ini_str(*[arg(i) for i in range(5)])),
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
]

INI = {
    "characters": {"battledroid": "behaviour=standard bullet=ewokpebble pull_levers=on",
                   "c3po": "behaviour=jedi"},
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
    stock = {a: m.rbytes(a, 5) for a in (0x5896D6, 0x48ABFD, 0x407E40, 0x55E470, 0x55F360, 0x4DEABD, 0x4DF8B9)}
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
    check("decrypted code: patches every site", len(changed) == 7, ", ".join(changed))
    check("restores the real GetCommandLineA and returns its result",
          m.r32(IAT_GETCOMMANDLINEA) == real and m.cstr(got) == "LEGOStarWarsSaga.exe")

    table = m.r32(0x5896D7)
    names = []
    while m.r32(table + 8 * len(names)):
        names.append(m.cstr(m.r32(table + 8 * len(names))))
    check("keyword table: 207 stock keywords kept, 4 added, terminated",
          len(names) == 211 and names[:207] == [m.cstr(m.r32(0x804248 + 8 * i)) for i in range(207)]
          and names[207:] == ["behaviour", "behavior", "bullet", "pull_levers"], f"{len(names)} entries")

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
    parse_keywords(m, idx["mydroid"], 'hit_points=4\nbehaviour="standard"\nbullet="geonosian"\npull_levers\n')
    parse_keywords(m, idx["myguard"], 'weapon_locator=0\nbehaviour="jedi"\nbullet=43\npull_levers off\n')
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
