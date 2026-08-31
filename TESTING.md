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

## 6. KOTOR 2 donors

Partly proven - the Quarren works - but only that one.

- [ ] A K2 head with its own weights (`n_duros`, `n_wookiem`) onto a K1 host.
- [ ] A K2 head needing `--fit` (`c_ithorian`, 1.7x).

## 7. Older work still unverified

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

## 8. The donor list of faces

Brand new. Open the Transplant tab and pick a host.

- [ ] Faces appear beside the names. **The first time is slow** - about a third
      of a second per face, so a list of 144 takes the better part of a minute,
      arriving gradually. After that it is instant, from a cache in
      `~/.kmdlfun/thumbs`.
- [ ] Clicking a face selects that donor, and Preview then builds *that* model.
- [ ] Change the **Show** filter to female, then droid. The list narrows and
      the faces still match their names - a face on the wrong row is the
      specific failure the background drawing could cause.
- [ ] Is seven rows enough to browse, or does the list want to be taller?

## 9. The rest of the Transplant tab

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

## 10. The Custom head tab

- [ ] Browse to a pack folder, **Check only**, and read the verdict. The
      scanned head in `packs/scanhead` should be REJECTED at 53% solid.
- [ ] Build one and confirm it lands in the output folder as a named build.

## 11. The Builds tab

- [ ] Builds are listed newest first and say what they came from.
- [ ] **Install to Override** and **Remove** do what they say. This is the only
      action that writes into the game - check it does not touch anything of
      yours.

## 12. The catalogue

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
