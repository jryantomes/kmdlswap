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

Tested 2026-10-06 in the mirror (flow plans movietest / movietravel / moviearmed, the fixed DLL
swapped in through the harness overlay; moviepoll.py logs the display mode and the movie window
every 0.1 s; logs/):
- Unattended - a scripted movie, and LIVE_4a on travelling to the yacht as the galaxy map plays
  it: both versions play the whole movie full screen at 640x480 (A-2, B-2, A/B-travel).
- The game's MAIN window activated during a movie (moviedisturb.py): the original switches the
  display to 1600x1200 with the 640x480 movie window still up - the movie in the top-left corner
  (A-main.log, 03:04:53.4). The fix never changes the display while the movie window is up
  (B-main.log). In both the activation then ends the movie, as an alt-tab does in the game.
- An alt-tab just before a movie (moviearm.py): no corner in either - the 3 s timer theory is
  not confirmed.
- The harness itself took the foreground from the movie window (it only knew the main window):
  that ended every movie 4 s in and spoiled the first runs. Fixed in autotest.foreground_game.

Not known: what activates the main window during a movie in the user's game. Ask before
proposing this upstream (LaneDibello/Kotor-Patch-Manager, patch author J0-o).

## Root cause (2026-10-10) - and the fix is J's Movie Patch, not 1.8.2

1.8.2 was installed locally on 2026-10-09 and did not help: in a real launch through Steam the movies
still came out at different sizes. `focuswatch.py` (passive: foreground changes, minimise/restore,
other processes' windows, the display mode, KotOR's movie and main windows, every 0.1 s) showed why:

- The game taking the foreground at launch is a WM_ACTIVATEAPP, which arms the patch's restore timer.
- The patch always restores the GAME resolution, but KotOR keeps 640x480 across chained movies (the
  intro logos, cutscene chains). 1.8.1 restores 1 s into the first movie; 1.8.2 waits for it to end
  and restores in the gap - so the next movie opens a 640x480 window on a 1600x1200 screen (the
  corner), and the one after gets a 1600x1200 window.
- No other process took the foreground. The harness missed it: it skips the intro movies.

Fix: J's own Movie Patch (better-movie-playback-v1, 1.5.3, in the 0.7.3 release) with the unmodified
Alt Tab Patch 1.8.1. Movies play in the game window at the game resolution, so there is no mode
switch to fight. Checked the same way: the display stayed 1600x1200 and every movie window was
1600x1200. 1.8.2 stays here as a record; it is not installed. Not reported upstream.
