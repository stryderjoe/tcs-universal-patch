# TCS Universal Patch

A small `dinput8.dll` for LEGO Star Wars: The Complete Saga (PC, Steam build) that turns behaviours the
game ties to particular characters into settings any character can use. Research: `docs/HARDCODED.md`.

**Status: experimental. Checked in an emulator against the game's own code (58 of 58 checks, below); not yet
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
| `behaviour="…"` (or `behavior`) | `standard`, `jedi`, `droid`, `protocol`, `astromech`, `beast`, `winged`, `superbattledroid`, `droideka`, `jawa`, `variant0` (also `weirdo`), `cannon`, `vehicle`, `battledroid`, `hoverdroid`, `walker2legs`, `walker4legs`, `critter` (womp rat, bat, snake), `pod` (podracers) | Which native behaviour and AI routine the character runs, instead of the one its categories or name pick |
| `bullet="…"` | a projectile name or number (list in `docs/HARDCODED.md`, e.g. `ewokpebble`, `geonosian`, `bullet`, `spear`, `blue`) | Projectile type for this character's shots |
| `pull_levers` / `pull_levers off` | | Allow or forbid levers, whatever the categories say |
| `drive_vehicles` / `drive_vehicles off` | | Allow or forbid the scripted vehicle take-over, which refuses droids in the stock game |
| `blade_style="…"` | `single`, `double` (Maul), `staff` (MagnaGuard), `four` (Grievous), `curved` (Dooku's hilt) | How the saber code draws, lights and streaks this character's blades; the game only does these for those four characters. Needs the matching `streak_N_locators` on the model and, for non-Jedi, `behaviour="jedi"` |
| `geonosian_variant` | | Treated as a Geonosian at the six places the game checks for one: 50/50 armed at spawn, the Geonosian bolt when armed, the armed/unarmed model layers (bits `0x20`/`0x40` of the layer mask, as on the Geonosian model), the unarmed attack, and no firing while flying |
| `weapon_always_out` | | Keep the weapon drawn all the time, as the game does by name for the Gamorrean guard, Ewoks and Tarpals |
| `acts_as="…"` | a stock character's file name, e.g. `ewok`, `geonosian`, `gamorreanguard` | The character also counts as that character at the game's 528 "is this <name>?" checks (`docs/IDENTITY_CHECKS.md` lists them all): every name-tied behaviour at once. Assets that character needs (models, clips, sounds) must still be loaded |
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
  The pebble, torpedo and boulder models are stored in the Ewok's, Wicket's and the catapult's icon scenes
  (`STUFF/ICONS/*_ICON_PC.GSC`), which a level loads only for its own characters; the patch also loads the
  owner's icon scene (108 or 29 KB) when a level character fires those projectiles. The rock sounds are
  preloaded the same way; the impact effect `EWOK_POP1` is global. Not yet seen in game.

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

Ambient effects: `FUN_00491D50` hands the two ambient-effect routines a fixed list of 8 member positions. With
members in slots 9 and up, that list holds the 8 members nearest the viewpoint the routines already cull by;
otherwise it is left exactly as the game builds it. Other arrays sized for 8 may exist that static analysis did
not find. **Never run in the game:** test with a copy of your save.

## With another dinput8.dll (four-player patch)

The TCS four-player patch (Loomirr/TTGames-Workshop, `games/tcs/four-player`, draft) is also a
`dinput8.dll`. To use both, rename that one (for example to `4p_dinput8.dll`) and name it here:

```ini
[chain]
dll = 4p_dinput8.dll   ; a file name in the game folder; paths and dinput8.dll itself are refused
```

This patch then loads it on the game's first `DirectInput8Create` call (outside the loader lock) and passes
that call and every later one to it instead of the system `dinput8.dll`. The four-player loader treats that
call as one of its two triggers and patches itself in then; its byte checks see unchanged code, because the
two patches never write the same bytes: `tools/compat_four_player.py <its src folder>` applies both to copies
of the game code and compares every changed byte (four-player v0.48: 828 bytes in 219 places; this patch 140
to 148 bytes in 20 to 22 places; none shared, none within 8 bytes).

`[party] max` is refused while `[chain]` is set: it moves the party arrays the four-player hooks read at
their stock addresses (26 references) and rewrites 9 address fields the four-player patch also hooks.
**Not run in the game together.**

## Checks

`tests/emulate.py` maps your unwrapped `LEGOStarWarsSaga.exe` image and the test build of the DLL
(`build_test.bat`) into the Unicorn x86 emulator and runs the game's own code through every patched site:
the start-up hook (including "code still encrypted" and "wrong build"), the extended keyword table, the
game's real tokenizer on character text, its behaviour assignment, projectile picker, both lever rules, the
scripted vehicle take-over, the droid routine's jump and vehicle entry, the three saber call sites, the six Geonosian checks, the weapon-out test, the rock-sound preload, the arena picker, `acts_as` at all 528 name checks (and through the game's projectile picker), and for `[party] max = 12` every moved address, the raised bounds, the game's own party builder filling 12 slots, each follow-up, and the ambient-effect list (untouched with 8 or fewer, the 8 nearest otherwise), and `[chain]` (the named file loaded once from the game folder, every `DirectInput8Create` passed on, bad names ignored, `[party]` refused). It also parses all 345 stock character files with the stock and the extended keyword
table and checks that the stored definitions are byte-identical. Needs `pip install unicorn pefile`; the
exe path comes from the command line or `TCS_EXE`, the character folder from `TCS_CHARS`. No game files are
included.

What the emulator cannot show: how the routines look and feel in play (animations, AI, camera), and
whether a character given a routine has the clips that routine expects.

## Build

`build.bat` (Visual Studio C++ tools, 32-bit). Licence MIT, credit Gibby.
