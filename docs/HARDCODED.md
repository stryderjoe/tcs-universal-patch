# LEGO Star Wars: The Complete Saga (PC): where the reported hardcoded behaviours live

All addresses are virtual addresses in the image based at `0x00400000`. The analysed image is the Steam
executable after SteamStub removal: SHA-256 `6C9C2B35AA9452BA36C4F816A4AE50E3E8DE133971AE1899A20DE102D7E20ADB`
(the same build as the Workshop's existing TCS research). The Steam file itself is SHA-256
`085688E73561C61F4619FCF1F3006C56425CA365E80EA5FC0175BAB334CEC671`, SteamStub variant 2.1; both share the PE
timestamp `0x4AC4A20B`, the import directory and the import address table.

Method: Ghidra 12.1.4 headless decompilation plus our own scans. Everything below was read from the code.
Unless a line says "in game", nothing here was observed in a running game.

## Shared structures

| Thing | Where | Notes |
| --- | --- | --- |
| Definition A | array at `[0x0093B274]`, stride `0x4C`, count `[0x0093B278]` | `+0x04` category flags, `+0x0C` file name, `+0x18` behaviour routine, `+0x1C` AI routine, `+0x20` extra routine, `+0x24` -> definition B |
| Definition B | array at `[0x0093B284]`, stride `0x120` | `+0x90`, `+0x94` more flags, `+0xEC` weapon, `+0xF4` hit points, `+0x116` `variant`, `+0x117` `streak` |
| Instance | per character | `+0x54` -> definition A, `+0x1064` short ID (= definition index), `+0x1082` hat worn |
| Keyword table | `0x00804248`, 207 `{name, handler}` pairs, `{0,0}` ends it | passed once, by `push 0x00804248` at `0x005896D6` in the loader `FUN_00589410` |
| Parse state | `[0x00954400]` = A, `[0x00954404]` = B, `(short)[0x0095441C]` = index | handlers read tokens with `0x004F7FB0`, ints `0x004F9E70`, floats `0x004F8100`; the token is at `ctx+0x510` |
| Name -> ID globals | `{name, &short}` table at `0x007F1B50`, 216 entries, filled by `FUN_00414340` | every identity check in the code compares an instance's ID with one of these globals |

Selected flag bits in A`+4`: baddie `0x4`, jedi `0x8`, droid `0x10`, protocol `0x30`, astromech `0x50`,
blaster `0x10000080` (it also sets can_fire `0x10000000`), teleport `0x40000`, zipup `0x100000`,
bounty_hunter `0x1000000`, vehicle `0x2000`, beast `0x40000000`. B`+0x94`: no_jump `0x4`, no_shoot `0x8`.
`variant=` sets B`+0x116` (stormtrooper 1, fett 2, macewindu 3, battledroid 4, wookiee 5, obiwankenobi 6,
clone 8, rebel 9, ... hoverdroid 0x11, walker2legs 0xF, walker4legs 0x10; default 0xFF), `FUN_00413B80`.

The code reads those name -> ID globals 833 times in 156 functions.

## The behaviour routine table (root of items 1, 2 and 3)

`FUN_00414400` runs once after all character files are read. It walks the definitions with a rule
helper `FUN_0055BD00(maskA, valueA, maskB, valueB, variant, behaviour, ai, extra)` and then overrides
some characters by identity:

| Rule | Behaviour | AI |
| --- | --- | --- |
| everyone first (`FUN_00414340`) | `FUN_004B4AC0` "standard" | `FUN_004A8F20` |
| jedi | `FUN_004B3390` | `FUN_004A9B80` |
| droid AND NOT bounty_hunter (`A+4 & 0x1000010 == 0x10`) | `0x004B5EF0` "droid" | unchanged |
| protocol / astromech | `0x004B5EF0` | protocol / astromech AI |
| B`+0x90 & 0x800` (cannon) | `FUN_004B30E0` | `0x004A9900` |
| vehicle | `0x004B5120` | `0x004A9730` |
| beast | `FUN_004B3000` | `0x004A9800` |
| variant 4, 0x11, 0xF, 0x10, 0x12, 0x14, 0 | their own routines | |
| B`+0x94 & 0x10000000` (hover_wings) | `0x004B65F0` | `0x004AB100` |
| by identity | destroyer, mini_droideka, superbattledroid, barman, jawa, ugnaught, dragbomb, republicgunship(_green), speederbike, probedroid | |
| by identity | **bodyguard (MagnaGuard), imperialguard (Royal Guard) -> the Jedi routine** | Jedi AI |

What the routines do differently:

- Vehicle entry `FUN_00488770` is called from the standard, Jedi, variant-0, jawa and winged routines only.
  The droid routine never calls it.
- Jump `FUN_00562570` returns at once when its fourth argument's low byte is negative. The droid routine
  passes `0x80` (gonk droid `0x40`, astromech `4`); the standard routine passes `0x20` or `0x08`.
- The saber, hilt and streak code (`FUN_0041DAD0`, `FUN_004A0900`, `FUN_004A0BC0`) runs in the Jedi routine.

### 1. Melee weapons without saber streaks are tied to non-Jedi tags

A character that is not `jedi` gets the Jedi melee routine only by identity: `bodyguard` (MagnaGuard: a
`droid`, `streak=purple`) and `imperialguard` (Royal Guard: `weapon="spear"`, `streak=red`). Both are set in
`FUN_00414400` after the flag rules. With a weapon in B`+0xEC` the Jedi routine draws that weapon instead
of a saber (`FUN_0041DAD0`), and the streak is drawn from `streak` and `streak_N_locators`
(`FUN_004A0BC0`, skipped when `streak` is unset). `FUN_004A0900` adds MagnaGuard-only streak toggles on two
attack moves. Hilt choice in `FUN_00418FB0` is also by identity (Maul, Dooku).

How many blades are drawn, lit and streaked is decided by name in three functions: `FUN_0041DAD0` (hilt and
blades, called at `0x0041EACD` and `0x0041EB4D`), `FUN_0049F850` (per-blade glow, `0x0042C72A`) and
`FUN_004A0900` (streak bits, `0x004B1D99`, character in EAX): Grievous 4 blades, Maul 2, the MagnaGuard 2 with
per-end streaks on actions `0x0C`/`0x18` (animations `0x1A`/`0x1B`), everyone else 1. A character with
`streak_2_locators` but another name gets a streak on its first blade only.

### 2. Some categories cannot drive vehicles

Characters on the droid routine (droid without bounty_hunter, protocol, astromech) never call vehicle
entry. The script action at `FUN_004543E0` (take over a `can_take_over` target) also refuses any actor
with the droid bit. Related: the lever rule `FUN_0055E470` / `FUN_0055F360`, stored in instance
`+0xEF0 & 0x800000` and read by `CanPullLevers` / `PullLever`, allows jedi, blaster or teleport characters
and never a droid that is also a bounty hunter.

### 3. Droids jump only with the bounty_hunter tag

Exactly the droid rule above: `A+4 & 0x1000010 == 0x10` puts a droid on the droid routine, which passes
`0x80` to the jump routine. A droid that is also a bounty hunter (IG-88, 4-LOM) matches no droid rule and
keeps the standard routine, so it jumps, drives and pulls levers. MagnaGuard jumps for the same reason
(Jedi routine by identity). Separately, jumping needs a clip in the jump action slot (`DAT_00804C80`).

### 4. Firing bullets is tied to a few characters, 6. Ewok rocks, 7. Geonosian blasters

Projectile type is chosen by `FUN_00407E40(character, default)`, a chain of identity checks:

| Who | Type |
| --- | --- |
| ewok | `0x1B` ewokpebble (`0x1E` ewoktorpedo while extra `0x29` is on) |
| wicket | `0x1C` wicketpebble (`0x1F`) |
| bobafett, 4lom | `0x1A` bobafett |
| satipo and two IDs outside the name table | `0x2A` bullet, only while an unlock is set, else 0 |
| hovitostribesman | `0x2B` spear |
| catapult | `0x1D` boulder |
| variant 8 (clone) or weapon `0x16` | 2 blue |
| many vehicles | their own types |
| everyone else | the caller's default, normally 0 (red) |

The Geonosian is handled before the picker: `FUN_004B3D40` fires type `0x13` "geonosian" when the
character is `geonosian` and instance `+0xEF0 & 0x200` is set. That bit is rolled 50/50 at spawn
(`FUN_0041BC20`), and `FUN_0041A5B0` switches its model layers with it. Projectile table: 44 entries of
`0xA4` bytes at `0x007EF388`, name first (red, green, blue, trainingremote, walker, spaceship, xwing,
falcon, ..., geonosian `0x13`, cannon, ..., bobafett `0x1A`, ewokpebble, wicketpebble, boulder,
ewoktorpedo, wickettorpedo, jedistarfighter, ..., bullet `0x2A`, spear `0x2B`).

### 5. Party limit

The limit is 8, enforced twice:

- **Level file.** `FUN_00573CA0` reads `character "X" player` lines into a list of `{id, flag}` pairs at
  `0x00951258` (count `0x00951078`) through `FUN_00573BE0(capacity, id, flag, pairs)` with capacity 8
  (the call at `0x00574426`); the storage holds 10 pairs including the end marker. When the added character
  appears in the level's pairing list (the fourth argument), its partner is appended as well and takes one of
  the 8 places: that is why some levels top out at 7 of their own players.
- **Party build.** `FUN_0041F940` copies the level list (story, `0x0095107C`) or the Free Play selection
  (`0x0093D590`) into the party, stopping at 8: party pointers at `0x0093D7F0` (8 x 4 bytes, count
  `0x0093D818`), with parallel 8-slot arrays at `0x0093D630` (stride `0x38`), `0x00854898` (stride `0xB4`)
  and `0x0093D510` (stride `0x10`). A character's party slot is the byte at instance `+0x280` (-1 = none),
  used to index further per-player arrays.

Size of a change: 496 instructions address the pointer array and 103 more hold its address as a constant
(loop pointers and end markers such as `0x0093D810`); the three parallel arrays add 72 more; arrays indexed
by `+0x280` are not all found by a static scan. Raising the limit means moving every one of those arrays,
fixing every loop bound and checking each in play. The patch does not attempt it.

### 8. Generic Jedi in the Geonosis arena

The arena (`LEVELS/EPISODE_II/JEDI/JEDI_B`) has its own native module, `0x004DE2A0` to `0x004DFxxx`
(pillars, phases, RestrainPadme/Anakin/ObiWan). Ambient fighters live in up to 256 slots of `0x60` bytes at
`0x00882BD0` (count `(short)0x00888ED0`). When a slot needs a type, `FUN_004DE2A0` (slot in ESI) gives:

- slots without flag 2: `bob`;
- story mode only (`[0x0093B2A4] == 0`): `luminara` once, then `shaakti` once (one-time bits 1 and 2 of
  `0x00888FB8`, cleared on level/phase reset in `FUN_004DE740`);
- otherwise 50/50 `battledroid_geonosian` / `geonosian`.

So at most two Jedi appear, each once per reset, and none in Free Play. Phases 1 to 3 add up to 8 scripted
creatures (`DAT_00888ED2 < 8`); phases 4 to 6 pick 6 objective droids into `0x00888F94`.

## Not resolved

- The two projectile IDs `0x007F17D0` / `0x007F17D4` are not in the name table (probably Indiana Jones
  bonus characters).
- `bob` (arena slots without flag 2) was not identified.
- The meaning of the remaining variant routines (`0x12`, `0x14`).
