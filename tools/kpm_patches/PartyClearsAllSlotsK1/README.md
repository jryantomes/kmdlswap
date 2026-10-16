# Party Clears Reach All Slots (KotOR I 1.03)

A Kotor Patch Manager patch, not tied to any mod. Requires **Party Roster Limit 32**.

**The problem.** The game clears the party in many places: boarding the Ebon Hawk, the Leviathan
capture, the Taris dueling ring, the Manaan arrest, Korriban, the Unknown World. Every one of those
scripts loops over party slots 0-8 (`UT_ClearAllPartyMembers` in k_inc_utility, or a script's own
copy of that loop). With the roster patch, a companion in slots 9-31 is never reached and stays in the
party. An audit of one install (2026-10-10) found 61 such scripts, the game's and other mods', many
inside `.mod` files that no Override file can replace.

**What this does.** As each script loads (`CVirtualMachineInternal::InitializeScript`, 0x005D16F0),
its party-clearing loops are widened: the bound `CONSTI 8; LEQII` (slot <= 8) becomes 31 when the
loop removes party members by a computed slot (`RemovePartyMember` with a non-constant argument).
A loop that only checks or counts members is left alone, and so is a removal of one named slot.
No game or mod file is changed; it works for every script, in saves already under way too.
The matching was checked offline against all 9,981 scripts of one install: every party-clearing loop
matched, and nothing else.

**Clears by name (0.2.0).** Some scripts remove slots 0 to 8 one by one instead of looping. On one
install that's three Star Forge scripts: `k_psta_door` (the door scenes), `k_psta_mlkparty` (Malak's
duel) and `k_psta_pc_j` (Bastila's light side scene). A second hook on the `RemovePartyMember` command
(0x00541C00) checks the running script: if it removes five or more different slots by constant, it's a
clear, and the members in slots 9 to 31 are removed too, through the game's own command handlers.
Scripts that take out one or two named companions (the Leviathan's split party) never reach five.
Tested in game: two named removals left a slot 10 companion in the party; nine removed him.

The debug output (DebugView) says how many loops each script had widened.

Build: `python ..\build.py PartyClearsAllSlotsK1` -> `builds/kpm/PartyClearsAllSlotsK1.kpatch`.
