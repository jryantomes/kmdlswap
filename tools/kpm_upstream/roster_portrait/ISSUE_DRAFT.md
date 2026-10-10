> **Posted 2026-10-10:** https://github.com/LaneDibello/Kotor-Patch-Manager/issues/329

**Title:** Party Roster Limit 32 (K1): party selection portraits are blank - calls CSWSObject::GetPortrait instead of the creature's

**Version:** 0.7.3 release; also current master (aa65324). KotOR 1.03 (GOG-identical exe), Windows.

**What happens:** on the party selection screen every *available* companion's portrait is blank.
Unavailable slots still show their silhouettes (those come from the GUI's `LBL_NA` images).
Selecting members still works, and hovering shows the 3D model, so the slots themselves are fine.
Reproduces on any save with an available companion, e.g. Carth in the Taris apartment.

**Cause:** `SetAvailableViewRecord` gets the portrait with

```cpp
nativeObjectGetPortrait = RequireFunctionAddress<ObjectGetPortraitFn>("CSWSObject", "GetPortrait");   // line 331
...
nativeObjectGetPortrait(creature, &portrait);                                                         // line 855
```

`CSWSObject::GetPortrait` (0x004D01C0) is the base implementation: it copies the object's own
portrait resref at `this + 0x20`, which party creatures leave empty. The game's own
`CSWGuiPartySelection::OnPanelAdded` calls it through the vtable instead (0x006BF010:
`call dword ptr [edx+0xC8]`), and `CSWSCreature` overrides that slot with
`CSWSCreature::GetPortrait` (0x004F8370, already in `kotor1_0_3.db`), which reads the portrait
from the creature's stats.

**Fix:** use the creature's version (same signature, `__thiscall`, one `CResRef*` out-param):

```diff
-        nativeObjectGetPortrait = RequireFunctionAddress<ObjectGetPortraitFn>("CSWSObject", "GetPortrait");
+        nativeObjectGetPortrait = RequireFunctionAddress<ObjectGetPortraitFn>("CSWSCreature", "GetPortrait");
```

(or call through the vtable slot, as the game does). The rest of the record setup matches the
game's: the fill image at record + 0x378, the flags at 0x448 and the selection alpha at 0x384 line
up with `OnPanelAdded`'s own offsets.
