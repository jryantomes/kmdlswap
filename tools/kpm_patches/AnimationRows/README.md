# Animation Rows (KotOR I 1.03) - prototype

A Kotor Patch Manager patch, not tied to any mod. With it, `PlayAnimation` and
`ActionPlayAnimation` on a creature can play **any `animations.2da` row**: pass
`20000 + row`.

```
ActionPlayAnimation(20079, 1.0, 15.0);   // "prone" (row 79): no ANIMATION_* constant reaches it
ActionPlayAnimation(20394, 1.0, 30.0);   // a row a mod added: its own animation name, in its own models
```

**Why.** K1 scripts can only reach the animations its `ANIMATION_*` constants map to. A mod
that needs a new pose has to hide it under one of those names (`dance`, `dance1`, `weld`...)
in shared body models. Every creature on those bodies then gets the new pose wherever the game
plays that name. Example: Jolee's bed pose under `dance` replaced the player's dance in the
Star Forge easter egg. With this patch, the new pose takes a name of its own and nothing
vanilla changes.

**How it works.**
- The engine path, mapped 2026-10-08:
  - `ExecuteCommandPlayAnimation` (0x540550) turns a script constant into a server animation
    id with a jump table: constants 0..0x78 become 10000 + n, and anything else becomes 10000.
  - `CSWSCreature::SetAnimation` passes other ids through.
  - The server asks the client for the length and fire-and-forget flag; both are table-driven.
  - The client's `CSWCAnimBase::ServerToClientAnimation` (0x69f650) returns an id its switch
    doesn't know unchanged, as the `animations.2da` row.
  - `GetAnimationName` reads that row's `name`, and the model plays the animation with that name.
- So the patch only touches the first switch: a replace hook at 0x5406F6 sends 20000..20999
  past it as id `value - 20000`.
- Rows stay below 1000: the client gives server ids 1000..1527 other meanings.
- `animations.2da` is loaded as an ordinary 2DA (`CTwoDimArrays+0x3c`), so rows appended in
  Override are found.

**For a mod:**
- Add a row to `animations.2da` with HoloPatcher `AddRow`. Copy the flags of a similar vanilla
  row: `dance` (53) is stationary + looping.
- Store the row with `2DAMEMORY#` and compile the script with that token. The row number
  differs between installs.
- Put an animation with that name into the models that should play it.
- Without the patch, `20000+row` falls to the default (10000) and nothing visible happens.
  That is a safe failure.

**Tested in the harness mirror** (flow plans `animrow`, `animrowbed`):
- Carth played `prone` (79), `meditate` by row (24, the control), and `sitdown` (20) followed
  by the seated loop `animloop01` (316).
- Jolee lay back on the medical bed with a new row 394, `hcw_bedlie`, while the same models'
  `dance` stayed vanilla. `ANIMATION_LOOPING_DANCE` made him dance standing.

**Not covered (yet):**
- Placeables and doors (their own switch at 0x540a28).
- Dialogue animations (DLG `Animation` fields go through `dialoganimations.2da`).
- Saves taken mid-animation.
- Checking a row against the table: an out-of-range row plays nothing.

**Related upstream:** Vriff's Aurora Animation Bank (KotOR II Aspyr only). It lets creatures
find animations in extra "stunt" models listed in `stuntmodel.2da`. A K1 equivalent would let
a new animation ship in one model instead of copies of every body that plays it.
