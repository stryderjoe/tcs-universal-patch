"""Check that this patch and the TCS four-player patch never change the same bytes.

The four-player patch (Loomirr/TTGames-Workshop, games/tcs/four-player) is also a dinput8.dll. This
applies both to copies of the game code and compares every changed byte:

- this patch: the test DLL, run in the emulator (tests/emulate.py), for several INI settings;
- the four-player patch: its own src/build.py patch routine with stand-in symbols, plus the two sites
  its loader writes itself (the XInput check call and the PeekMessageA import).

It also lists the four-player hooks' game-data addresses that fall inside the party arrays this patch's
experimental [party] option moves.

usage: python tools/compat_four_player.py <four-player src folder> [unpacked exe]
"""
import collections, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tests"))


def ranges(s):
    out = []
    for a in sorted(s):
        if out and a == out[-1][1] + 1:
            out[-1][1] = a
        else:
            out.append([a, a])
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    if len(sys.argv) > 2:
        os.environ["TCS_EXE"] = sys.argv[2]
    sys.argv[1:] = []
    import emulate
    import pefile
    sys.path.insert(0, src)
    import build as four

    exe = emulate.EXE
    size = pefile.PE(exe).OPTIONAL_HEADER.SizeOfImage

    d = bytearray(open(exe, "rb").read())
    _pe, _opt, _sect, secs, fo = four.check_input(d)
    orig = bytes(d)
    four.patch_code(d, fo, 0x2A8E000, collections.defaultdict(lambda: 0x2A8E100))
    theirs = {0x400000 + sva + i for _n, sva, vsz, rsz, roff in secs
              for i in range(min(vsz, rsz)) if d[roff + i] != orig[roff + i]}
    theirs |= set(range(0x6D9E11, 0x6D9E16)) | set(range(0x751238, 0x75123C))
    print(f"four-player patch: {len(theirs)} bytes in {len(ranges(theirs))} places")

    ok = True
    for name, ini, must_be_apart in (("no INI", {}, True), ("test INI", emulate.INI, True),
                                     ("[party] max=16", {"party": {"max": "16"}}, False),
                                     ("[party] max=16 with [chain]",
                                      {"party": {"max": "16"}, "chain": {"dll": "4p.dll"}}, True)):
        m = emulate.Machine(ini)
        before = m.rbytes(0x400000, size)
        m.install()
        m.start_game_code()
        after = m.rbytes(0x400000, size)
        mine = {0x400000 + i for i in range(size) if before[i] != after[i]}
        both = mine & theirs
        near = {a for a in mine for k in range(-8, 9) if a + k in theirs} - both
        verdict = "apart" if not both and not near else f"{len(both)} shared bytes, {len(near)} within 8 bytes"
        print(f"this patch, {name}: {len(mine)} bytes in {len(ranges(mine))} places; {verdict}")
        for a, b in ranges(both):
            print(f"    shared {a:08X}..{b:08X}")
        if must_be_apart and (both or near):
            ok = False

    regions = []
    for line in open(os.path.join(HERE, "..", "src", "party_table.h")):
        r = re.search(r"\{ 0x([0-9A-F]+)u, 0x[0-9A-F]+, \d+, 0x([0-9A-F]+)u \},\s*/\* (\w+)", line)
        if r:
            regions.append((int(r.group(1), 16), int(r.group(2), 16), r.group(3)))
    text = "".join(open(os.path.join(src, f), encoding="utf-8", errors="replace").read()
                   for f in ("hooks.s", os.path.join("dll", "loader.c")))
    hits = collections.Counter()
    for v in re.findall(r"0x([0-9A-Fa-f]{6,8})", text):
        for s, e, nm in regions:
            if s <= int(v, 16) < e:
                hits[nm] += 1
    print("four-player references into the arrays [party] moves:",
          ", ".join(f"{nm} x{n}" for nm, n in sorted(hits.items())) or "none")
    print("OK: the patches can run together (without [party])" if ok else "CONFLICT")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
