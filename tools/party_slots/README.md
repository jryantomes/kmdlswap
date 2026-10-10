# Party Slots for KotOR I companion mods

A small shared way for companion mods to take a party slot, so they never collide.

Kotor Patch Manager's **Party Roster Limit 32** gives KotOR I party slots 9 to 31 as well as the nine it ships with. If every companion mod picks its own fixed number, two of them will eventually pick the same one and overwrite each other's companion. And without the roster patch there are no slots past 8 at all.

With Party Slots, a mod asks for a slot instead of choosing one. It gets the first slot from 9 up that no companion holds and no other mod has reserved, and it keeps that slot for the rest of the game. On a game without the roster patch it gets a clear "no", so it can fall back to whatever it did before (sharing or swapping a vanilla slot, for example).

## What's in it

| File | What it is |
|---|---|
| `ps_slots.nss` | The include. Copy it next to your scripts and `#include "ps_slots"`. |
| `ps_example.nss` | A recruit script that uses it, with a fallback. |
| `changes_globalcat.ini` | The HoloPatcher (TSLPatcher) lines for the globals it needs. |

## Using it

1. **Pick a global name for your companion's slot,** for example `MYMOD_PARTY_SLOT`, and add it to `globalcat.2da` as a Number, together with the four shared globals `PS_SLOTS_A` to `PS_SLOTS_D`. `changes_globalcat.ini` has the lines. The shared ones are added only if they're missing, so any number of mods can ship them.
2. **Add your companion through Party Slots:**

```c
#include "ps_slots"

void main()
{
    int nSlot = PS_AddByTemplate("MYMOD_PARTY_SLOT", "my_companion");
    if (nSlot == -1)
    {
        // no roster patch, or every slot is taken: your mod's own fallback
        return;
    }
    SetNPCSelectability(nSlot, TRUE);
}
```

3. **Use the slot wherever the game wants an NPC number** (`AddPartyMember`, `IsNPCPartyMember`, `SetNPCSelectability`, `RemoveAvailableNPC` and so on). Later scripts get it back with `PS_SlotOf("MYMOD_PARTY_SLOT")`.

## The functions

| Function | What it does |
|---|---|
| `PS_AddByTemplate(sGlobal, sTemplate)` | Puts the companion in your slot from a template, claiming the first free slot if you have none yet. Returns the slot, or -1 with nothing changed. |
| `PS_AddByObject(sGlobal, oCreature)` | The same with an existing creature, keeping its levels, gear and choices. |
| `PS_SlotOf(sGlobal)` | Your slot, or -1. |
| `PS_Claim(sGlobal)` | Reserves a slot without adding anyone. A reservation only: it doesn't check for the roster patch. |
| `PS_Release(sGlobal)` | Gives your slot back, for a companion who has left the game for good. |
| `PS_FindFree()` | The first free slot, or -1. |
| `PS_IsClaimed(nSlot)` | Whether any mod has reserved a slot. |

## How it keeps mods apart

Each mod keeps its slot in its own global. The four shared globals hold one bit per slot from 9 to 31 (seven slots in each, since KotOR's global numbers are signed bytes), marking every slot some mod has claimed. A slot stays reserved even while its companion is out of the roster for a while, so another mod can't take it in the meantime.

## Safe without the roster patch

The game itself refuses slots past 8: they read as not available, and adding a companion to one fails. So `PS_AddByTemplate` and `PS_AddByObject` return -1 and change nothing, and your fallback runs.

## Also useful

**Party Clears Reach All Slots** (in this repo, `tools/kpm_patches/PartyClearsAllSlotsK1`) is a Kotor Patch Manager patch that makes the game's party clears (boarding the Ebon Hawk, the Leviathan capture and the rest) reach slots 9 to 31. Without it, a companion in those slots stays in the party where the game expects to be alone.

Free to use and to ship with any mod.
