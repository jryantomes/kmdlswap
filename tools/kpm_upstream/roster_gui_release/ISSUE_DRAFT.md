**Title:** Release 0.7.3 leaves out Party Roster Limit 32's party screen (`Additional` vs `additional`)

**Version:** 0.7.3 (`KotorPatchManager-v0.7.3.zip`)

### What happens

`PartyRosterLimit32K1.kpatch` is in the release, but its party screen isn't, and its manifest says "The included .gui file must be installed to function." Without it the party screen keeps the vanilla nine slots. The K2 roster patch's `partyselect_p.gui` is missing the same way.

Every other patch with extra files ships them as a "<patch> additional files" folder: ExpandedVanillaOptions, FullPartySelect, K1GUITests, K2ClassMenuClothes, LevelUpLimit, ModOptions, ScriptExtender and Snake.

### Why

Those two patches keep their files in a folder named `Additional` with a capital A:

- `Patches/PartyRosterLimit32K1/Additional/partyselection.gui`
- `Patches/PartyRosterLimit32K2/Additional/partyselect_p.gui`

`publish-patches.py` looks for `patch_dir / "additional"` (`copy_additional`). The release workflow runs it on `ubuntu-22.04`, which is case-sensitive, so both folders are skipped. On Windows `publish.bat` and `publish-patches.ps1` would find them, because there the case doesn't matter.

### Fix

Either of these would do it:
- rename the two folders to `additional` (`git mv`, through a temporary name on Windows);
- or make `copy_additional` match the folder name case-insensitively, so a capitalised folder can't drop out silently again.

Thanks for the 0.7.3 roster update.
