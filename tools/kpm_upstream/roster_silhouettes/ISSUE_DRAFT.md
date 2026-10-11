> **Posted 2026-10-10:** https://github.com/LaneDibello/Kotor-Patch-Manager/issues/331

**Title:** Party Roster Limit 32 (K1): silhouettes for companions in slots 9 to 31

@vrifftech

**What I'd like:** a way for a mod that adds a companion in slots 9 to 31 to give it a silhouette on the party screen while it isn't available, the way every vanilla companion has one, even the ones you can skip.

**What happens now:** an unavailable slot past 8 is an empty box. `SetUnavailableViewRecord` shows the silhouette label only for the stock slots (line 808):

```cpp
unavailable.SetControlBitFlag(1, logicalSlot < STOCK_NPC_SLOTS);
```

which makes sense today, since every `LBL_NA9` to `LBL_NA31` in the layout carries Bastila's silhouette (`po_pbastila2`), and on the second page the same controls stand for different slots anyway.

**A way to do it:** let mods register a silhouette for a slot, and set it per logical slot when the page is built, the same way the portraits are set with `SetFillImage` in `SetAvailableViewRecord`.

A small 2DA would do, something like `partysilhouettes.2da` that mods add rows to with HoloPatcher:

| slot | slotglobal | silhouette |
|---|---|---|
| 12 | **** | po_pmycompanion2 |
| **** | MYMOD_PARTY_SLOT | po_pothercomp2 |

* `slot` for a mod that uses a fixed slot.
* `slotglobal` for a mod that takes its slot at runtime: the slot is the value of that global number. This is how the [Party Slots](https://github.com/jryantomes/kotor-party-slots) include works (mods take the first free slot so they don't collide), so a mod using it would register its global here.
* `silhouette` is the texture, named the vanilla way (the portrait plus `2`).

When an unavailable record is built for a slot past 8 that has a row, set the label's fill to that texture and show it. Without a row, it stays an empty box as now. Unclaimed slots stay empty, so the screen doesn't fill up with outlines of nobody.

For companions who only get a slot at recruitment, the mod would reserve the slot when the game starts, so the silhouette can show before they join. That part is on the mods' side.

All that's needed is the mechanism: a way for a mod that adds a companion to register its silhouette when it's installed. The images and rows would come with each companion mod.
