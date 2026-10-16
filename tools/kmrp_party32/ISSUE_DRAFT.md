**Title:** Party selection screen: support KPM's Party Roster Limit 32 (16 slots per page)

**KMRP version:** 1.5.0 (Windows, applied through KOTOR Patch Manager 0.7.3)
**Other patch:** *Party Roster Limit 32 - KotOR I Beta* (Vriff), id `party-roster-limit-32-k1`, shipped with KPM 0.7.3

### What happens

KMRP serves its own `partyselection.gui` for each resolution, and the game reads it ahead of `Override`. That screen has the vanilla nine slots.

Party Roster Limit 32 expects a different party screen. Its own `partyselection.gui` goes in `Override`. At load, `CreatePartySelectionView` binds controls by tag:
- `BTN_NPC0-15`, `LBL_CHAR0-15` and `LBL_NA0-15`: a page of sixteen slots;
- `BTN_PAGE_PREV` and `BTN_PAGE_NEXT`.

See `InitializeViewRecord` and `InitializePageButton` in `Patches/PartyRosterLimit32K1/PartyRosterLimit32K1.cpp`.

With KMRP installed, KMRP's nine-slot screen replaces the roster's, so slots 9 and above have no controls. Any companion in those slots can't be picked on the party screen. Mods that give a companion a slot of their own past 8 need the roster patch, so they hit this.

I found this by reading both patches' files, not in play, so I haven't seen exactly how the screen fails.

### Suggestion

When `party-roster-limit-32-k1` is installed, serve a roster version of `partyselection.gui` at each size: KMRP's screen with the roster's page of sixteen and its two page buttons. Everything else stays as KMRP lays it out.

Generating that version looks cheap, because KMRP's own party screens follow a simple rule. Within a region, KMRP spreads the controls apart across the width but keeps their shape:
- each control's **centre** maps linearly from the 640x480 layout, per axis (`x' = a*x + b`);
- its **size** scales by one ratio per axis.

I fitted that per region from KMRP's own controls: the nine slots, then Accept/Done/Back. It rebuilds every one of those controls to 0 px at all four sizes the 1.5.0 bank stores (1280x1080, 1360x768, 2880x1620, 3440x1440).

Applying the same maps to the roster's 640x480 layout gives:
- a 4x4 page in KMRP's slot area;
- Previous/Next beside Done, where the roster puts them.

The new controls copy the look of KMRP's own `BTN_NPC0` / `LBL_CHAR0` / `LBL_NA0` / `BTN_DONE`: fonts, borders and fill. They take the roster's tags, text and positions.

[comparison image: KMRP 1.5 at 3440x1440, as shipped (9 slots) and with the roster page (16 slots + page buttons)]

The roster's 640x480 file is in the KPM source tree at `Patches/PartyRosterLimit32K1/Additional/partyselection.gui`. KPM 0.7.3's release zip doesn't include it, because that folder's capital-A `Additional` isn't picked up.

Since your build already derives every size from base layouts (`derive_resolution`), adding the roster screen as a second base might be simplest. KMRP's patch would then choose it when the roster patch is present.

I have a small Python script that does this fit-and-place on a GUI file, and I'm happy to share it or test a build.
