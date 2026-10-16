# Party Silhouettes (KotOR I 1.03), a stopgap

A Kotor Patch Manager patch, not tied to any mod. Requires **Party Roster Limit 32**. Asked for upstream as [LaneDibello/Kotor-Patch-Manager#331](https://github.com/LaneDibello/Kotor-Patch-Manager/issues/331); remove this once the roster patch does it.

Every vanilla companion has a silhouette on the party screen while they aren't available. A companion a mod adds in slots 9 to 31 has none: the roster patch shows the silhouette label only for slots 0 to 8 (its layout gives every later one Bastila's), so the slot is an empty box.

With this patch, mods register a silhouette in `partysilhouettes.2da` (the additional file; put it in Override and add rows with HoloPatcher):

| slot | slotglobal | silhouette |
|---|---|---|
| 12 | **** | po_pmycomp2 |
| **** | MYMOD_PARTY_SLOT | po_pother2 |

* `slot` for a mod that uses a fixed slot.
* `slotglobal` for a slot kept in a global number, as [Party Slots](https://github.com/jryantomes/kotor-party-slots) does.
* `silhouette` is the texture, named the vanilla way: the portrait plus `2`.

Slots without a row stay empty.

**How it works.** The roster patch builds each page of the party screen in the game's own slot records, adds every slot's button to the screen, then adds each slot's silhouette label if that label is visible. A hook on `CSWGuiPanel::AddControl` (0x0040B9A0) catches each slot button as it's added: for an unavailable slot 9 to 31 with a row, the slot's label gets that texture (`SetFillImage`) and is made visible, and the roster patch then adds it like the vanilla ones. Global numbers are read through the game's own `CSWGlobalVariableTable::GetValueNumber`, which writes a single signed byte.

Tested in game: a fixed slot (12) and a slot from a global (13) both showed their silhouettes; the vanilla ones, the available companions' portraits and unregistered slots were unchanged.

Build: `python ..\build.py PartySilhouettesK1` -> `builds/kpm/PartySilhouettesK1.kpatch`.
