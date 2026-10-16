# TCS Universal Patch

A small `dinput8.dll` for LEGO Star Wars: The Complete Saga (PC, Steam build) that turns behaviours the
game ties to particular characters into settings any character can use. Research: `docs/HARDCODED.md`.

**Status: experimental. Checked in an emulator against the game's own code (52 of 52 checks, below); not yet
run in the game.** Every patch site is checked byte for byte first; anything that does not match is skipped
and logged. Please report what you see in game.

## Install

Put `dinput8.dll` (and, if wanted, `TCSUniversal.ini`) next to `LEGOStarWarsSaga.exe`. It works on the
normal Steam executable: the code is patched in memory after Steam's wrapper has decrypted it, and no game
file is changed. `TCSUniversal.log` in the same folder lists what was patched. Remove the DLL to undo.

## Character keywords

Use them in a character `.txt` like the stock keywords, or in `TCSUniversal.ini` (below).

| Keyword | Values | Effect |
| --- | --- | --- |
| `behaviour="â€¦"` (or `behavior`) | `standard`, `jedi`, `droid`, `protocol`, `astromech`, `beast`, `winged`, `superbattledroid`, `droideka`, `jawa`, `variant0` | Which native behaviour and AI routine the character runs, instead of the one its categories or name pick |
| `bullet="â€¦"` | a projectile name or number (list in `docs/HARDCODED.md`, e.g. `ewokpebble`, `geonosian`, `bullet`, `spear`, `blue`) | Projectile type for this character's shots |
| `pull_levers` / `pull_levers off` | | Allow or forbid levers, whatever the categories say |
| `drive_vehicles` / `drive_vehicles off` | | Allow or forbid the scripted vehicle take-over, which refuses droids in the stock game |
| `blade_style="…"` | `single`, `double` (Maul), `staff` (MagnaGuard), `four` (Grievous), `curved` (Dooku's hilt) | How the saber code draws, lights and streaks this character's blades; the game only does these for those four characters. Needs the matching `streak_N_locators` on the model and, for non-Jedi, `behaviour="jedi"` |
| `geonosian_variant` | | Treated as a Geonosian at the six places the game checks for one: 50/50 armed at spawn, the Geonosian bolt when armed, the armed/unarmed model layers (bits `0x20`/`0x40` of the layer mask, as on the Geonosian model), the unarmed attack, and no firing while flying |
| `weapon_always_out` | | Keep the weapon drawn all the time, as the game does by name for the Gamorrean guard, Ewoks and Tarpals |
| `can_jump` | | A character on the droid routine gets the jump the standard routine has (it still needs a jump animation) |
| `enter_vehicles` | | A character on the droid routine can get into vehicles like the standard routine |

What this unlocks:

- A melee weapon with a streak on any character (not only MagnaGuard and Royal Guard):
  `weapon="spear" streak=red streak_1_locators=6,7 behaviour="jedi"`. Streaks on both ends of a staff:
  add `streak_2_locators=…` and `blade_style="staff"`. A double-bladed saber: `blade_style="double"`.
- A droid that jumps and drives vehicles (not only IG-88 and 4-LOM) while staying a droid in every other
  way: `can_jump enter_vehicles`, plus `drive_vehicles` for levels that hand vehicles over by script. Or
  `behaviour="standard"` for the whole standard routine, as IG-88 has.
- Ewok rocks, Geonosian bolts or Indiana Jones bullets on anyone: `bullet="ewokpebble"`,
  `bullet="geonosian"`, `bullet="bullet"` (the character still needs `blaster` to shoot).
  **Ewok and catapult projectiles need their owner in the level:** the pebble, torpedo and boulder models are
  stored in the Ewok's, Wicket's and the catapult's icon scenes (`STUFF/ICONS/*_ICON_PC.GSC`), which a level
  loads only for characters it loads. Add e.g. `character "Ewok" resident` to the level's `.TXT`. (The
  impact effect `EWOK_POP1` is global; the rock sounds are also preloaded by the patch.) Not yet seen in game.

## TCSUniversal.ini

```ini
[characters]
; file name from CHARS.TXT = the same keywords
battledroid = behaviour=standard bullet=ewokpebble pull_levers=on

[arena]
; Geonosis arena: which Jedi join the ambient fight, and how many at once
enabled = 1
jedi = luminara,shaakti,kiadimundi,kitfisto
max_jedi_at_once = 4
respawn = 1        ; 0 = each Jedi at most once per reset, as in the stock game
in_freeplay = 1    ; the stock game spawns none in Free Play
```

Jedi named in `[arena]` must be loaded by the level: add them as `resident` in
`LEVELS/EPISODE_II/JEDI/JEDI.TXT` (stock: only Luminara and Shaak Ti).

## Party size (experimental)

```ini
[party]
max = 12     ; or 16; anything else leaves the game as it is
```

Moves every party-sized array to a larger buffer, rewrites the 1,057 places the code holds their addresses
(table `src/party_table.h`, generated from the exe by `tools/party_reloc_gen.py`), raises 24 loop bounds and
limits (including the level `player` list and the level-end unlock list, which stops at 7), and adds
follow-ups to the 10 places that handle slots 0 to 7 one by one. A level can then list up to `max` player
characters. Inventory and reasoning: `docs/PARTY_LIMIT.md`.

Known gap: `FUN_00491D50` gathers the 8 members' positions into a fixed local list used to switch nearby
ambient effects on, so members 9 and up do not trigger those (cosmetic). Other arrays sized for 8 may exist that static analysis
did not find. **Never run in the game:** test with a copy of your save.

## Checks

`tests/emulate.py` maps your unwrapped `LEGOStarWarsSaga.exe` image and the test build of the DLL
(`build_test.bat`) into the Unicorn x86 emulator and runs the game's own code through every patched site:
the start-up hook (including "code still encrypted" and "wrong build"), the extended keyword table, the
game's real tokenizer on character text, its behaviour assignment, projectile picker, both lever rules, the
scripted vehicle take-over, the droid routine's jump and vehicle entry, the three saber call sites, the six Geonosian checks, the weapon-out test, the rock-sound preload, the arena picker, and for `[party] max = 12` every moved address, the raised bounds, the game's own party builder filling 12 slots, and each follow-up. It also parses all 345 stock character files with the stock and the extended keyword
table and checks that the stored definitions are byte-identical. Needs `pip install unicorn pefile`; the
exe path comes from the command line or `TCS_EXE`, the character folder from `TCS_CHARS`. No game files are
included.

What the emulator cannot show: how the routines look and feel in play (animations, AI, camera), and
whether a character given a routine has the clips that routine expects.

## Build

`build.bat` (Visual Studio C++ tools, 32-bit). Licence MIT, credit Gibby.
