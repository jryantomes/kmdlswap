# Party Portrait Fix (KotOR I 1.03) - stopgap

A Kotor Patch Manager patch, not tied to any mod. With **Party Roster Limit 32** from KPM 0.7.3,
the party selection screen shows blank portraits for every available member (unavailable ones
keep their silhouettes, which come from the GUI file).

**Why.** The roster patch rebuilds the screen's slots itself and fills each portrait with
`CSWSObject::GetPortrait` (0x004D01C0), found by name in the address database. That is the base
version: it copies the object's own portrait resref (`this + 0x20`), which party creatures leave
empty. The game's own `CSWGuiPartySelection::OnPanelAdded` calls the vtable slot (`+0xC8`), which
`CSWSCreature` overrides with `CSWSCreature::GetPortrait` (0x004F8370, the portrait from the
creature's stats). The fix upstream is one word: look up `"CSWSCreature", "GetPortrait"`.

**What this does.** Until then, the base function dispatches through the object's vtable first:
a creature gets its own override; anything else runs the original copy. Nothing in the game calls
the base directly (checked 2026-10-10: no `call 0x004D01C0`; it appears only in the vtables of
classes that do not override the slot), so only callers like the roster patch see a change. One
`simple` hook, 48 bytes, in the function and its padding; no DLL.

Remove it once Party Roster Limit 32 is fixed upstream.

Build: `python ..\build.py PartyPortraitFixK1` -> `builds/kpm/PartyPortraitFixK1.kpatch`.
