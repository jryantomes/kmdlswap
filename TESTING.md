# Testing owed

Everything here has been built and passes its tests, and none of it has been
watched by a person. Two kinds of thing are on the list and they fail
differently:

* **In the game** - a build that validates is not a build that works. Lighting,
  facial animation and whether a head sits on a neck are exactly what a
  validator cannot check.
* **In the app** - the tests drive the widgets headlessly, which proves the
  wiring and says nothing about whether the thing is usable: how it looks, how
  long it makes you wait, whether the layout survives your window size.

Copy a build's `.mdl`/`.mdx` into `Override/`, load a save, and look. Delete
them afterwards; vanilla lives in the BIFs.

**Never delete these from Override.** They are the HK recruit mod, not ours:
`p_hkrfk.*`, `hkrfkjr.*`, `c_rfk_hk47.*`, `po_phkrfk.tpc`, `recruit_hkrfkjr.*`,
and anything matching `rfk_*`, `c_rfk_*`, `q_rfk_*`.

---

# Part one: in the game

## 1. Tangent lighting — the one with no substitute

**Why it matters.** The tangent basis was reverse-engineered this session and
its *sign* was measured, not derived. A flipped tangent looks identical in every
viewer and renders wrongly in game. Nothing offline can tell the difference.

```bash
kmdlfun transplant --install "<K1>" --host n_selkath --donor p_carthh --fit --out out_fun/
```

- [ ] **Selkath host, human head.** Load and look at the face under a moving
      light. Bump detail should look *lit*, not inverted - highlights where the
      light is, not opposite it.
- [ ] **A second tangent host** (`n_rakata`, `n_xorh`, `twilek_m`,
      `c_rakghoul`) to confirm it is not one model's quirk.

**Failure looks like:** surface detail that seems inside-out or lit from the
wrong side; a face that reads flat or oddly greasy as the camera moves.

## 2. The heads that were unreachable until now

Eleven K1 and ten K2 heads were refused outright before this session.

```bash
kmdlfun transplant --install "<K1>" --host p_carthh --donor twilek_m --out out_fun/
```

- [ ] **`twilek_m` onto Carth.** Measured clean at 0.2% with its own weights,
      so this should be near-perfect. Check the head turns and the mouth moves.
- [ ] **`n_selkath` onto Carth** — 4.8%, needs `--fit`, brings six extra parts
      (eyes, lids, teeth). Check the eyes land in the sockets.

## 3. Heads onto a unified body (HK-47)

New this session: naming a single host node instead of pairing whole models.

- [ ] **Carth's head into `p_hk47:head`.** Built and validating. Check the
      **droid body is still there** - if HK-47 is a floating head, the
      hide-suppression regressed.
- [ ] Does the head animate with the droid's own animations, or sit rigid?
      Either is informative; HK-47's head node is unskinned, so rigid is the
      expected answer.

## 4. Custom head packs from the app

The Custom head tab is new; the underlying path is the one that put a Tripo
head on HK-47 months ago, so this is checking the tab rather than the format.

- [ ] Build a pack onto `p_hk47` from the app and load it.
- [ ] Build one onto a **skinned** host (`p_carthh`) and check the face still
      animates.

## 5. The 42 heads the app could not see

Player-creation and commoner heads have never been built as donors by this
tool, because until this session they were not offered.

- [ ] **`pfhc01` or `pmhc01` onto a companion.** These pair whole-model at
      seven parts, so they should be the *easiest* swaps in the game. If one of
      these looks wrong, something systematic is wrong.
- [ ] A `comm_*` head, which are lower-detail and may sit differently.

## 6. Body swaps

New, and never seen running. A body host now offers body donors, and arms
transfer where only the torso used to.

```bash
kmdlfun transplant --install "<K1>" --host p_carthbb --donor p_bastilabb --out out_fun/
```

- [ ] **Bastila's outfit on Carth.** Torso and both arms should move. In the
      preview the arms sit on the shoulders; the thing to check in game is that
      they still do once the character *animates*, since nothing offline poses
      the model.
- [ ] Watch for **left and right**. Aliasing pairs `LArm` with `ArmL`, and the
      failure mode if that ever goes wrong is a mirrored arm - elbows bending
      the wrong way - which reads as a broken rig rather than a naming bug.
- [ ] The torso solidity warning is real: Bastila's outfit reports 70%, below
      the 77% floor, so expect some see-through around the thin flaps.

## 7. KOTOR 2 donors

Partly proven - the Quarren works - but only that one.

- [ ] A K2 head with its own weights (`n_duros`, `n_wookiem`) onto a K1 host.
- [ ] A K2 head needing `--fit` (`c_ithorian`, 1.7x).

## 8. Older work still unverified

From `NEXT.md`, predating this session:

- [ ] **The five effects.** Only `bighead` on HK-47 has ever been seen running.
      `chibi` is expected to look wrong - shrinking a body cannot shorten a
      character, since height lives in the bones - so confirming that is
      confirming the caution is honest.
- [ ] `bigmitts` writes only two models. A human draws hands as part of the
      torso and arm meshes, so only droids have a hand node to scale.

---

# Part two: in the app

Faster to check and worth doing first, since a broken list makes the in-game
tests harder to set up.

## 9. The donor list of faces

Brand new, and already revised twice from your feedback: the faces were being
clipped to a fifth of their height by a Treeview row, and a list of them showed
four at a time out of a hundred and forty-four. It is a grid now.

Open the Transplant tab and pick a host.

- [ ] Faces appear beside the names. **The first time is slow** - about a third
      of a second per face, so a list of 144 takes the better part of a minute,
      arriving gradually. After that it is instant, from a cache in
      `~/.kmdlfun/thumbs`.
- [ ] Clicking a face selects that donor, and Preview then builds *that* model.
- [ ] Change the **Show** filter to female, then droid. The list narrows and
      the faces still match their names - a face on the wrong row is the
      specific failure the background drawing could cause.
- [ ] Is seven rows enough to browse, or does the list want to be taller?

## 10. The rest of the Transplant tab

- [ ] **Rank for this host** - reorders best-first and labels each entry with a
      grade. Takes about ten seconds; the log says what it found.
- [ ] **Into** - with `p_hk47` as host it should say "pairs with nothing
      whole-model, choose 'head'". Choosing `head` fills the list.
- [ ] **Donor from: KOTOR 2** - the list should repopulate from K2, with faces.
- [ ] **Preview** with a head-model host draws the head **on its body**, before
      and after, at one shared scale. That is the view that shows whether a
      head is the right size and sits on the neck, so it is worth a look before
      any of the in-game tests above - a head that is obviously wrong here does
      not need loading to find out.
- [ ] Preview with `p_hk47` as host draws HK-47 alone. It *is* its own body, so
      there is nothing to put it on.

## 11. The Custom head tab

- [ ] Browse to a pack folder, **Check only**, and read the verdict. The
      scanned head in `packs/scanhead` should be REJECTED at 53% solid.
- [ ] Build one and confirm it lands in the output folder as a named build.

## 12. The Builds tab

- [ ] Builds are listed newest first and say what they came from.
- [ ] **Install to Override** and **Remove** do what they say. This is the only
      action that writes into the game - check it does not touch anything of
      yours.

## 13. Making a new character

All new, and the part with the most riding on it: this is the difference
between replacing a vanilla character and adding one.

- [x] **The whole chain works, 2026-09-01.** `rfk_broker` was replaced with a
      new character: new model, new `heads.2da` row, new `appearance.2da` row,
      new blueprint. He spawned, kept his conversation, and his lips moved.

      Two things learned by doing it. **The build has to be installed** - the
      first attempt looked like a failure and was simply five files still
      sitting in the output folder, which the chain diagnosis found in seconds
      by walking utc -> appearance -> heads -> model against what was actually
      in Override. And **`--with-texture` is not optional** when the donor is a
      different species: without it the model keeps the *host's* texture name,
      so Bith geometry came out wearing Carth's hair smeared over the skull. It
      read as a broken model and was a correct model with the wrong texture.

- [ ] **Save as.** Build with `Save as: p_myhead` and confirm the folder holds
      `p_myhead.mdl/.mdx` and *not* `p_carthh.mdl`. Install it and check Carth
      is still Carth - the whole point is that nothing was replaced.
- [ ] **Make it a: NPC.** No tables should be written, just a `.utc`.
- [ ] **Make it a: NPC that talks.** Then write the `.dlg` and see whether the
      conversation starts.
- [ ] **Make it a: companion.** Check the portrait row appears; the recruit
      script is still yours, so this one cannot be finished by the tool alone.
- [ ] Installing now touches `appearance.2da`, which is **yours**. The install
      planner should report it as *foreign* and ask before replacing it. Say no
      once and confirm it does not write.

## 14. The broker's animation — a specific hypothesis

`rfk_broker.utc` has `ScriptSpawn = k_def_ambmob`. Across all 205 vanilla
creature blueprints, 52 use that script and **none of them hold a
conversation**; its company is `c_bantha`, `c_brith` and `c_dewback`. Every
vanilla NPC that talks uses `k_def_spawn01`.

- [x] **Confirmed in game, 2026-09-01: his head animates.** The diagnosis
      holds - `k_def_ambmob` was making a conversational NPC run the wandering
      -animal behaviour - and the same mistake is designed out of the
      generator, which now uses `k_def_spawn01` for NPCs and `k_hen_spawn01`
      for companions.

## 15. Does a lip file play without audio?

Set up 2026-09-01. **This is the only thing in this project that has written
into the game install**, so exactly what changed is recorded here.

Mouth movement comes from a `.lip` file, not from the model or the dialog, and
the engine finds it by the line's `VO_ResRef`. Every line in `rfk_broker.dlg`
had that field empty, so there was nothing for a lip to be named after.

**Changed in `Override/`:**

| file | what |
|---|---|
| `rfk_broker.dlg.backup-before-lip-test` | **new** - byte copy of the dialog as it was (14,350 bytes, 19 Jul) |
| `rfk_broker.dlg` | `EntryList[0].VO_ResRef` set from `''` to `rfk_brk_01`. One field, one entry; the other ten still have it empty |
| `rfk_brk_01.lip` | **new** - 151 bytes, 3.90s, 27 keyframes. A byte copy of `nm35aacarth2002_` out of `lips/korr_m35aa_loc.mod` |

Nothing else was touched. `rfk_broker.utc` also has today's date because of
your own `ScriptSpawn` fix.

Entry 0 is his opening line, *"Hold on. Before you run off..."*.

- [x] **Confirmed in game, 2026-09-01: his mouth moved.**

**So the engine plays a lip file with no `.wav` behind it.** That was the open
question and it could not be answered offline. Mouth movement does not need
recorded audio - it needs a `.lip` and a `VO_ResRef` to hang it on.

It also means the community's blocker does not apply here. The usual tool needs
the CSLU toolkit to derive phonemes from a recording, and CSLU is effectively
unobtainable; but with no audio to sync to, there is nothing to derive. A lip
file is a duration and a list of mouth shapes, and PyKotor writes the format.

If the timing looks wrong, that is expected and not the point: it is Carth's
mouth shapes for a different sentence.

**To undo:** delete `rfk_brk_01.lip` and rename the backup back over
`rfk_broker.dlg`.

## 16. Generated lips

Built on the result above. `kmdlfun lips <dlg> --out <dir> --assign --replies`
writes a `.lip` per line and, where a line had no `VO_ResRef`, an updated copy
of the dialogue beside them. **The original dialogue is never edited.**

**Already installed for you, 2026-09-01.** What is in `Override/` now:

| file | what |
|---|---|
| `rfk_broker.dlg.backup-before-generated-lips` | **new** - the dialogue as it was a moment before (14,360 bytes, with only entry 0 named) |
| `rfk_broker.dlg` | replaced, 14,360 → 14,685 bytes. All 26 spoken lines now have a `VO_ResRef` |
| 26 × `rfk_brok*.lip` | **new** (25) and replaced (1 - `rfk_brk_01.lip`, which was the borrowed Carth one and is now generated like the rest) |

Verified after copying: all 26 spoken lines have a `VO_ResRef` *and* a lip file
on disk. Your other 19 `rfk_*` files were not touched.

- [x] Installed and ready - just talk to him.
- [x] **Confirmed in game, 2026-09-01: his lips move throughout the
      conversation**, not just on the one line that had a borrowed lip.

So the whole path works: shapes derived from a line's own text, a `VO_ResRef`
assigned where there was none, and 26 generated files driving a conversation
nobody recorded. Nothing here came from a phoneme engine or a recording.

If you record the lines, pass `--audio <folder>` and each lip is made exactly
as long as its own recording - name the files after the line's `VO_ResRef`.
Audio headers here are not honest, in three different ways. **The one that
matters for your own recordings** is the decoy the modding guide has you
prepend: the real WAV ends up nested inside it, so `rfk_carth_a1.wav` opens
claiming 8-bit 22 kHz with a data chunk of zero while 58 bytes in sits the
truth - 16-bit 32 kHz, 5.76 seconds. Shipped ambient sound nests the same way
behind a 470-byte preamble. Shipped *voice* is different again - a WAV header
over MP3 - and is refused rather than guessed at, since a confident wrong
length silently makes a lip that does not match. Run those through SithCodec
first and they read like anything else.

Without recordings, timing is estimated from word count at two and a half words
a second, so a long line gets a long lip: `rfk_brokere01.lip` runs 13.6 seconds over 110 keyframes.
If you click past it the mouth stops with the line; if you linger, it stops
moving before you do. Watch whether that reads as natural or as him running
out. That rate is the single number to change.

**To undo everything:** delete `Override/rfk_brok*.lip`, then rename
`rfk_broker.dlg.backup-before-lip-test` back over `rfk_broker.dlg` - that one
is the dialogue as it was before any of this, with no VO_ResRefs at all.

## 17. The catalogue

- [ ] `python tools/render_catalogue.py --install "<K1 root>"` - 233 models in
      about a minute. Spot-check a few faces are the right way round.

---

## Housekeeping

Still in `Override/` from earlier testing, both safe to delete:

- `p_carthh` — Carth reshaped onto Dustil's head
- `p_bastilabb` — Bastila's cap-1 armour body

## Already verified, for contrast

Not owed, recorded so the list above is not read as "nothing works":

- The splice engine and a no-op swap, 76,703/76,703 mesh nodes identical.
- The resize probe, in game.
- **The `+168` node pointer fix** (2026-08-30) - the probe that had broken every
  previous time. This is the one that unlocked skinned heads.
- A Quarren head on Carth: animates, own weights carried, two of four tentacles
  hung wrong.
- A Tripo-generated head on Carth: head turns, mouth moves, brows do not.
- `bighead` on HK-47.
