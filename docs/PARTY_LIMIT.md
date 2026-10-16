# Raising the party limit of 8: inventory and plan

Addresses are for the unwrapped Steam build (SHA-256 `6C9C2B35…`). Everything here is from static analysis
(Ghidra 12.1.4 plus our own scans); none of it has been tried in the game. Tools: `tools/party_scan.py`
(sites by function), `tools/party_reloc_gen.py` (relocation table).

## Where 8 (and 7) come from

| Limit | Where | What it does |
| --- | --- | --- |
| Level `player` list | `push 8` at `0x00574426`, `cmp edx, 8` at `0x00573E84` (`FUN_00573CA0`) | At most 8 `{id, flag}` pairs in `0x00951258` (count `0x00951078`); a listed character's pairing partner is appended too and takes a place |
| Party build | `cmp eax, 8` at `0x0041FA95` (`FUN_0041F940`) | Copies at most 8 from the level list (`0x0095107C`) or the Free Play list (`0x0093D590`) into the party |
| Unlocks at level end | `cmp edi, 7` at `0x00483B60` (`FUN_00483AF0`) | At most 7 of the level's characters are added to the "unlocked" list `0x0087A190` (7 + end marker), so a level with 8 player characters unlocks only 7 |

## What is sized for 8 party slots

The pointer block `0x0093D7F0` holds 8 slots, then two special pointers that the code uses constantly:
`0x0093D810` (137 reads; loops over "all slots" end there) and `0x0093D814` (loops that end there include
`0x0093D810`). Loops ending at `0x0093D7F8` cover only the two players (slots 0 and 1).

| Region | Start | Stride x slots | Notes |
| --- | --- | --- | --- |
| Party pointers | `0x0093D7F0` | 4 x 8 (+2 specials) | 857 address fields point into this block |
| Per-slot records | `0x0093D510` | 0x10 x 8 | fields also addressed one by one (`0x0093D516`, `0x0093D526`, ... `0x0093D588`) |
| Free Play list | `0x0093D590` | 2 x 8 | character IDs |
| Per-slot records | `0x0093D5A0` | 0x10 x 8 | indexed by a character's slot |
| Per-slot records | `0x0093D630` | 0x38 x 8 | a member's `+0xCA8` points here |
| Per-slot records | `0x00854898` | 0xB4 x 8 | a member's `+0xCC0` points here |
| Per-slot bytes | `0x00881258` | 1 x 8 | filled from `+0xCC4`, padded to 8 (`0x00414E6E`, `0x00414E7D`) |
| Per-slot floats | `0x00876C98` | 4 x 8 | written by slot in `FUN_0043E530` |
| Toggle floats | `0x00856934` | 4 x 8 | Free Play character toggling (`ToggleChar`), `FUN_00424810` |
| Level lists | `0x00951258` / `0x0095107C` | 4 x 10 / 2 x 10 | storage for 8 + partner + end marker |
| Unlock list | `0x0087A190` | 2 x 8 | 7 + end marker |

Not party data, although they loop 8 times: tow cables `0x00854E38` (0x1EC x 8), cantina tables `0x0087B49C`,
level effects `0x0088A570`. Arrays indexed by a character's slot but only 2 long (`0x0088A534`,
`0x0088A53C`, `0x00800214`, `0x0080021C`, ...) are per player and only ever see slots 0 and 1.

The character pool is not a limit: 64 instances of `0x10D8` bytes (`FUN_0062A7D0` / `FUN_0062A870`).

Code pointers into these regions are only in code (none in `.rdata` / `.data`). Every absolute reference
Ghidra knows is in the relocation table; its 268 other references are field accesses through a register
already holding a region address.

## Bounds that would change

Loops over all slots compare with 8 (or count down from 8):

`0x0040C637`, `0x00414E6E`, `0x00414E7D`, `0x00427F77`, `0x0043C35F`, `0x0043D673`, `0x0043EA04`,
`0x00447790`, `0x004C7E71`, `0x004CD9FA`, `0x004DE8C0`, `0x00553942`, `0x0058EB85`, `0x0058EB8C`,
`0x0059C260` / `0x0059C278` (unrolled by four: N must stay a multiple of 4), `0x00404DCA` (records at
`0x00854944`), `0x00424EA8` / `0x00424F4A` (toggle list), slot range checks `0x0041B828` and `0x0055E30E`
(`0 <= slot < 8`), plus the three limits above.

Not bounds although they compare with 8: `0x0040B053`, `0x00428657`, `0x0044A885` (struct copy),
`0x0046C597`, `0x004B92B7`, `0x004918A3`, `0x0047CEA3`, `0x004B1934`, `0x004BB171`, `0x005740E4`,
`0x005988E2`, and loops of 2 (`0x00489322`, `0x004B7939`).

Checked and not party data: `0x00950DB4` (a pool of 8 timed entries of 0x38 bytes, `FUN_0056EE80`) and a
loop of 8 over `+0xA0` inside another object (`FUN_00411980` / `0x004138E3`).

## Code written out once per slot

Some functions repeat a statement for slots 0 to 7 instead of looping (they read `0x0093D80C`, slot 7,
directly): `FUN_00415770`, `FUN_0041F940`, `FUN_00427EC0`, `FUN_0042B960`, `FUN_0043A910`, `FUN_0043E530`,
`FUN_004477C0`, `FUN_0048F9B0`, `FUN_00491D50`, `FUN_00492B40`, `FUN_004B0C80`, `FUN_0055C120`,
`FUN_00575C20`, `FUN_0059BD40`, and six blocks Ghidra does not mark as functions. Each would need a
follow-up that does the same for slots 8 and up. The ones read so far are simple ("if the member exists,
clear a flag / set a field"); for example `FUN_00427EC0` clears `+0xEF0 & 0x200000`, `FUN_0055C120` zeroes
`+0xD60` and `+0xEE8`, `FUN_0048F9B0` copies `+0x107E` to `+0x107F`.

## Status

Implemented as `[party] max = 12 | 16` in the patch (experimental). Added to the regions above after a
second search (arrays indexed alongside the party arrays): `0x00855E84` (saved `+0xCBC`, 4 x 8) and
`0x00876858` (up to 17 attackers per member, 0x88 x 8, range check `0x0043D469`). `0x0093D590` turned out
to be the party carried between a level's areas (`FUN_00414D40` saves up to 8 there), not only Free Play.
Not party data after all: `0x00856934` and the bounds `0x00424EA8` / `0x00424F4A` (character select grid),
`0x0087B6C4` (2 players), `0x0087A840` (a 48-entry list).

Follow-ups (stub after the relocated slot-7 instruction, same registers and flags): `0x0041F971` and
`0x00493011` clear slots 8+, `0x00428796` `+0xEF0 &= edx`, `0x0043FD12` `+0x4B0 &= ecx`, `0x0048FB63` hearts,
`0x0042C019` `+0xE39 = 4`, `0x0042C10B` `+0x1000`, `0x004EBF43` pool bit mask, `0x0055C30A` / `0x0055C51B`
`+0xD60`, `+0xDA4`, `+0xEE8`. Not covered: `FUN_00491D50` (8-entry local list).

## Plan

1. Allocate the regions above for N slots (N a multiple of 4, e.g. 12 or 16), keeping every stride, and
   copy their contents (they are empty at start-up). The two special pointers go right after slot N-1.
2. Rewrite every address field in the generated table to the same place in the new buffer (the patch can
   check each old value first, as it does elsewhere).
3. Change the bounds listed above to N (and the unlock limit to N-1).
4. Add follow-ups for each function that is written out once per slot.
5. Test in the game: a level listing 9 to N players, story and Free Play, swapping, level end.

Steps 1 to 3 are mechanical; step 4 needs each function read; step 5 cannot be skipped.
