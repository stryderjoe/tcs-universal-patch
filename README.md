# TCS Universal Patch

A small `dinput8.dll` for LEGO Star Wars: The Complete Saga (PC, Steam build) that turns behaviours the
game ties to particular characters into settings any character can use. Research: `docs/HARDCODED.md`.

**Status: experimental. Checked in an emulator against the game's own code (26 of 26 checks, below); not yet
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
| `behaviour="…"` (or `behavior`) | `standard`, `jedi`, `droid`, `protocol`, `astromech`, `beast`, `winged`, `superbattledroid`, `droideka`, `jawa`, `variant0` | Which native behaviour and AI routine the character runs, instead of the one its categories or name pick |
| `bullet="…"` | a projectile name or number (list in `docs/HARDCODED.md`, e.g. `ewokpebble`, `geonosian`, `bullet`, `spear`, `blue`) | Projectile type for this character's shots |
| `pull_levers` / `pull_levers off` | | Allow or forbid levers, whatever the categories say |
| `drive_vehicles` / `drive_vehicles off` | | Allow or forbid the scripted vehicle take-over, which refuses droids in the stock game |

What this unlocks:

- A melee weapon with a streak on any character (not only MagnaGuard and Royal Guard):
  `weapon="spear" streak=red streak_1_locators=6,7 behaviour="jedi"`.
- A droid that jumps and drives vehicles (not only IG-88 and 4-LOM): `behaviour="standard"`, plus
  `drive_vehicles` for levels that hand vehicles over by script.
- Ewok rocks, Geonosian bolts or Indiana Jones bullets on anyone: `bullet="ewokpebble"`,
  `bullet="geonosian"`, `bullet="bullet"` (the character still needs `blaster` to shoot).

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

## Not covered

The party limit of 8 is a fixed array read in 401 places; this patch does not change it (details in
`docs/HARDCODED.md`).

## Checks

`tests/emulate.py` maps your unwrapped `LEGOStarWarsSaga.exe` image and the test build of the DLL
(`build_test.bat`) into the Unicorn x86 emulator and runs the game's own code through every patched site:
the start-up hook (including "code still encrypted" and "wrong build"), the extended keyword table, the
game's real tokenizer on character text, its behaviour assignment, projectile picker, both lever rules, the
scripted vehicle take-over and the arena picker. It also parses all 345 stock character files with the stock and the extended keyword
table and checks that the stored definitions are byte-identical. Needs `pip install unicorn pefile`; the
exe path comes from the command line or `TCS_EXE`, the character folder from `TCS_CHARS`. No game files are
included.

What the emulator cannot show: how the routines look and feel in play (animations, AI, camera), and
whether a character given a routine has the clips that routine expects.

## Build

`build.bat` (Visual Studio C++ tools, 32-bit). Licence MIT, credit Gibby.
