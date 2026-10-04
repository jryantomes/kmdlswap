# Alt Tab Patch: movies stay full screen (proposed upstream fix, not yet sent)

For Lane's Kotor Patch Manager, `Patches/Alt Tab Patch` (1.8.1, by J0-o; checked against master
2026-10-04). Built from a separate working copy (`Patches/AltTabPatchMovieFix` in the KPM source
tree), never the original.

The problem (2026-10-04): movies played in the top-left corner of a 1600x1200 screen. KotOR plays a
movie in "SW Movie Player Window" and switches the display to 640x480; the patch's activation
handling forces the game's resolution back and re-forces it on a 3 s timer, so a movie that starts
while that runs, or an activation during one, is left drawn at 640x480 in the corner.

The fix (`alt_tab_patch.diff`): `moviePlaying()` - that window up, visible, ours. While it is, the
patch does not change the display mode or restore/realign the game window, and its timer waits
for the movie to end before restoring. Version 1.8.2.

Status: builds; the mirror comparison (moviepoll.py + flow plan movietest, overlay DLL) was spoiled
by overlapping runs while the user's game was open - rerun before proposing it upstream.
