# KMRP's party screen with Party Roster Limit 32 (prototype, 2026-10-09)

KMRP 1.5 serves its own `partyselection.gui` for every resolution from a cache it registers
ahead of `Override`. It has the vanilla nine slots. KPM's *Party Roster Limit 32 - KotOR I*
binds sixteen (`BTN_NPC0-15`, `LBL_CHAR0-15`, `LBL_NA0-15`) and two page buttons
(`BTN_PAGE_PREV`, `BTN_PAGE_NEXT`), so with KMRP a companion in slot 9 or above cannot be
picked on the party screen.

- `kmrp_bank.py <KMRP.kpatch's windows_x86.dll> <out> [file ...]` reads KMRP's interface bank
  (resource 101; the format of `K1RuntimeAssets.cpp`) and writes a file of every size it
  stores. KMRP stores `partyselection.gui` at four sizes only (1280x1080, 1360x768, 2880x1620,
  3440x1440); the others it blends at run time from `gui-blend.bin`.
- `party32.py <vanilla gui> <roster-32 gui> <KMRP gui> <out>` makes KMRP's screen at that size
  with the roster's page of sixteen and its page buttons. KMRP moves a region's controls apart
  across the width but keeps their shape, so centres map linearly per axis and sizes by one
  ratio per axis; fitted from KMRP's own controls of the region (the nine slots; Accept, Done,
  Back), the map rebuilds every one of them to 0.00 px at all four sizes. New controls copy
  KMRP's look (BTN_NPC0 / LBL_CHAR0 / LBL_NA0 / BTN_DONE) with the roster's tag and words.

Not yet delivered into the game: KMRP's cache is a fresh `%TEMP%\KMR*.tmp` per launch, rebuilt
on every resolution change, and most sizes exist only after its blend. Ways to deliver: a KMRP
option (its build already derives every size from one base layout), or a small KPM patch that
applies this transform to whatever party screen KMRP serves, at run time.
