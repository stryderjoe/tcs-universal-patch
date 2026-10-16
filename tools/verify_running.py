"""Read a running LEGOStarWarsSaga.exe (no input sent) and report what the patch changed.

usage: python verify_running.py [character names...]
Prints each named character's behaviour and AI routine, and whether the patch sites are hooked.
"""
import ctypes, ctypes.wintypes as wt, struct, subprocess, sys

ROUTINES = {
    0x4B4AC0: "standard", 0x4B3390: "jedi", 0x4B5EF0: "droid/protocol/astromech", 0x4B3000: "beast",
    0x4B65F0: "winged", 0x4B5E10: "superbattledroid", 0x4B6520: "droideka", 0x4B3B80: "jawa",
    0x4B5820: "variant0", 0x4B30E0: "cannon", 0x4B5120: "vehicle",
}
SITES = {
    "keywords (push imm)": (0x5896D6, b"\x68\x48\x42\x80\x00"),
    "behaviour call": (0x48ABFD, b"\xe8\xfe\x97\xf8\xff"),
    "bullet picker": (0x407E40, b"\xe8\x0b\x76\x15\x00"),
    "lever rule": (0x55E470, b"\x8b\x44\x24\x04\x8b"),
    "lever rule 2": (0x55F360, b"\x8b\x44\x24\x04\x8b"),
    "arena call 1": (0x4DEABD, b"\xe8\xde\xf7\xff\xff"),
    "arena call 2": (0x4DF8B9, b"\xe8\xe2\xe9\xff\xff"),
}

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wt.HANDLE
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]


def pid_of(name):
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if parts and parts[0].lower() == name.lower():
            return int(parts[1])
    return None


def main():
    pid = pid_of("LEGOStarWarsSaga.exe")
    if not pid:
        sys.exit("LEGOStarWarsSaga.exe is not running")
    h = k32.OpenProcess(0x0010 | 0x0400, False, pid)  # VM_READ | QUERY_INFORMATION

    def read(addr, n):
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)):
            raise OSError(ctypes.get_last_error())
        return buf.raw

    u32 = lambda a: struct.unpack("<I", read(a, 4))[0]
    for what, (addr, stock) in SITES.items():
        now = read(addr, len(stock))
        print(f"{what:22s} {'stock' if now == stock else 'PATCHED'}  {now.hex(' ')}")
    base, count = u32(0x93B274), u32(0x93B278)
    print(f"definitions: {count}")
    want = {n.lower() for n in sys.argv[1:]}
    for i in range(count):
        rec = read(base + i * 0x4C, 0x4C)
        name_ptr = struct.unpack_from("<I", rec, 0x0C)[0]
        name = read(name_ptr, 48).split(b"\0")[0].decode("latin1") if name_ptr else "?"
        if want and name.lower() not in want:
            continue
        upd, ai = struct.unpack_from("<II", rec, 0x18)
        flags = struct.unpack_from("<I", rec, 4)[0]
        print(f"{i:4d} {name:28s} update {upd:08X} ({ROUTINES.get(upd, '?')})  ai {ai:08X}  flags {flags:08X}")


main()
