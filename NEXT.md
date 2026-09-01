# Start here

Written 2026-08-31. Everything below is committed and green: **311 tests**,
corpus 2,832/2,832 round-tripping.

## Where things stand

`kmdlswap` is complete against its brief - all five milestones, definition of
done met in-game. `kmdlfun` is the tool built on top of it, and is now the part
that gets used.

The engine constraint that shaped the early sessions is **gone**:

> ~~A skinned head mesh's vertex count cannot change, or the mouth and eyebrows
> stop moving.~~ **Wrong, resolved 2026-08-30.** The cause was a node pointer at
> MDL model header `+168` that our parser never read and so never relocated.
> Fixed, confirmed in game. Skinned head meshes may change vertex count freely,
> and `--reshape` is now an option rather than a requirement.
> [reports/SKIN_ROOT_POINTER_FINDINGS.md](reports/SKIN_ROOT_POINTER_FINDINGS.md)

## What the tool does now

Five tabs, all sharing the folder settings, log and build button.

* **Effects** - uniform scales of a part (bighead and friends), previewed as a
  whole character rather than a headless body.
* **Transplant** - move geometry between models. Donors are listed **as faces**,
  can be sorted by measured fit, filtered by male / female / droid, taken from
  KOTOR 2, and aimed at a single named node instead of whole-model pairing.
* **Custom head** - a mesh from outside the game into one node, with decimation,
  fitting, winding repair and cropping. Was command-line only until this
  session.
* **Preview** - draws the result. A head model is drawn **on its body**, before
  and after at one shared scale.
* **Builds** - named, kept folders with a manifest, and the only thing that
  writes into the game.

**Save as** turns a build into a *new* model rather than a replacement. Every
build before this overwrote a vanilla resref, so installing one replaced that
character for the whole game and two builds could not coexist. Naming a build
`p_myhead` rewrites the name inside the model to match the file, which is what
the engine reads. `--register` then writes the `heads.2da` and `appearance.2da`
rows that make the game offer it, appended to whatever is installed so other
mods survive.

How much a character needs depends on what it is for, and the three answers
differ enough to be a choice rather than a default. A plain **NPC** edits no
tables at all if it wears something already in the game - a blueprint and
nothing else. An **NPC that talks** is the same, wired for conversation. A
**companion** adds a portrait row, the henchman scripts and `NoPermDeath`. The
`.dlg` and the recruit plumbing are reported as still the modder's rather than
silently skipped.

What is still missing for a *distributable* mod is patching rather than
replacing: these tables are this install's, so handing them to someone else
overwrites their mods. A HoloPatcher/TSLPatcher `changes.ini` is the answer and
is not written yet.

Command line covers the same ground, plus `kmdlfun rank`, `import`, `render`,
`builds` and `lips`.

**`kmdlfun lips`** gives an unvoiced dialogue moving mouths: a `.lip` per line,
shapes taken from the line's own text at the density vanilla uses. It never
edits the dialogue in place - if lines need a `VO_ResRef` it writes an updated
copy beside the lips.

## What has never been seen running

**[TESTING.md](TESTING.md)** is the list, twelve sections, and none of it has
been watched by a person. The tests prove the wiring; they cannot see lighting,
facial animation, or whether a head sits on a neck.

The one with no offline substitute is **tangent lighting**: the basis was
reverse-engineered and its *sign* measured rather than derived, and a flipped
tangent looks identical in every viewer and wrong in game.

## Open work, roughly in order of value

- **In-game verification.** See above. A problem found there outranks
  everything below it.
- **Jade Empire.** Closest of the other engines by a distance: its wrapper is
  KOTOR's with eight bytes inserted, fully understood, and our parser gets
  through the wrapper *and* the model header before failing in the node walk.
  Whether that is another fixed-offset shift or a real restructure is unmeasured
  and answerable in about half an hour.
  [reports/OTHER_ENGINES_FINDINGS.md](reports/OTHER_ENGINES_FINDINGS.md)
- **Neverwinter Nights.** Container reads today; models are a second reader, and
  neverblender to `.glb` is the cheap path. NWN heads are KOTOR's contemporaries
  and built to comparable budgets, so unlike SWTOR the density problem mostly is
  not there.
- **SWTOR.** Feasible and proven by other people's ports. Extraction is
  community tooling, then Blender, then `kmdlfun import`.
  [reports/SWTOR_FEASIBILITY.md](reports/SWTOR_FEASIBILITY.md)
- **`uv2`.** The last MDX column this tool will not author. No head in either
  game carries one, so it unlocks nothing today.

## Things that are true and easy to forget

- **Generated lips work.** Confirmed in game 2026-09-01: a whole conversation
  driven by lip files derived from the text of each line, with no recording and
  no phoneme engine behind any of it.
- **A lip file plays without audio.** Confirmed in game 2026-09-01. Mouth
  movement comes from a `.lip` found by the line's `VO_ResRef`, and neither a
  `.wav` nor the CSLU toolkit the community treats as mandatory is needed when
  there is nothing to sync to.

- **Vanilla is the oracle.** Grades, thresholds and budgets come from measuring
  shipped content, not from judgement. "Rough" means no worse than a head the
  game ships and works.
- **Solidity is the best single predictor** of whether a swap looks right, and
  the one thing no viewer can show: a two-sided preview draws an inside-out mesh
  as perfect. Under 77% renders full of holes.
- **The camera faces +Y.** Every image this project made before
  `reports/FACING_FINDINGS.md` was of the back of someone's head.
- **Bone slots are per-model; bone names are portable.** That is what lets a
  donor keep its own weights across games.
- **16 is the size of the bone table, not a limit.** 21 vanilla meshes use 17.

## Housekeeping

Still in `Override/` from testing, both safe to delete:

- `p_carthh` — Carth reshaped onto Dustil's head
- `p_bastilabb` — Bastila's cap-1 armour body

**Never delete** the HK recruit mod files: `p_hkrfk.*`, `hkrfkjr.*`,
`c_rfk_hk47.*`, `po_phkrfk.tpc`, `recruit_hkrfkjr.*`, and anything matching
`rfk_*`, `c_rfk_*`, `q_rfk_*`.

## Where the detail lives

`reports/` holds the evidence for every claim above. The ones worth reading
first are `SKIN_ROOT_POINTER_FINDINGS.md` (the constraint that was not one),
`FACING_FINDINGS.md` (how a wrong camera survived a test), and
`DONOR_RANKING_FINDINGS.md` (how the grades were calibrated).
