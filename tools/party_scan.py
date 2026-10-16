"""Map every place the party limit of 8 touches, from your own unwrapped LEGOStarWarsSaga.exe.

Lists, per function (start found from the compiler's int3 padding), the instructions that address the
party arrays, the ones that hold an array address or end marker as a constant, and the compares with 7 or 8
in the same function: the starting point for anyone moving the arrays to raise the limit.
Writes CSV to stdout (address, function, kind, detail). Nothing from the game is stored in this repository.

usage: python tools/party_scan.py <unwrapped exe> > party_sites.csv
"""
import collections, sys
import capstone, pefile
from capstone.x86 import X86_OP_IMM, X86_OP_MEM

ARRAYS = {  # name: (start, end) ; the end is also checked as a loop end marker
    "party": (0x0093D7F0, 0x0093D810),
    "slots_38": (0x0093D630, 0x0093D7F0),
    "slots_b4": (0x00854898, 0x00854898 + 8 * 0xB4),
    "slots_10": (0x0093D510, 0x0093D590),
    "level_players": (0x00951258, 0x00951280),
}


def main(path):
    pe = pefile.PE(path)
    text = pe.sections[0]
    code, base = text.get_data(), pe.OPTIONAL_HEADER.ImageBase + text.VirtualAddress
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail, md.skipdata = True, True
    func, pad = base, 0
    rows, compares = [], collections.defaultdict(list)
    touched = set()
    for ins in md.disasm(code, base):
        if ins.id == 0:
            continue
        if ins.mnemonic == "int3":
            pad += 1
            continue
        if pad >= 1 and ins.address % 16 == 0:
            func = ins.address
        pad = 0
        for op in ins.operands:
            value = None
            if op.type == X86_OP_MEM and op.mem.base == 0 or op.type == X86_OP_MEM and op.mem.disp > 0x400000:
                value, kind = op.mem.disp & 0xFFFFFFFF, "memory"
            elif op.type == X86_OP_IMM:
                value, kind = op.imm & 0xFFFFFFFF, "constant"
            if value is None:
                continue
            inside = [(n, a) for n, (a, b) in ARRAYS.items() if a <= value < b]
            if inside:
                name, a = inside[0]
                rows.append((ins.address, func, f"{kind}:{name}", f"+{value - a:#x}"))
                touched.add(func)
            else:
                for name, (a, b) in ARRAYS.items():
                    # a constant equal to the end is a loop end marker; a memory access there is the next variable
                    if value == b and kind == "constant":
                        rows.append((ins.address, func, f"end:{name}", kind))
                        touched.add(func)
        if ins.mnemonic == "cmp" and len(ins.operands) == 2 and ins.operands[1].type == X86_OP_IMM \
                and ins.operands[1].imm in (7, 8):
            compares[func].append((ins.address, ins.operands[1].imm))
    for f in sorted(touched):
        for addr, value in compares.get(f, []):
            rows.append((addr, f, "compare", str(value)))
    rows.sort(key=lambda r: (r[1], r[0]))
    print("address,function,kind,detail")
    for r in rows:
        print(f"{r[0]:08X},{r[1]:08X},{r[2]},{r[3]}")
    kinds = collections.Counter(r[2].split(":")[0] for r in rows)
    print(f"# {len(touched)} functions; " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())), file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
