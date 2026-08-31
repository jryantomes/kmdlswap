# Pulling characters from The Old Republic

**Date:** 2026-08-31
**Question:** can SWTOR heads be brought into KOTOR, and what would it cost?
**Answer:** yes, it is proven, the extraction is already solved by other people,
and our approach happens to sidestep the blocker they hit.

## It has been done, repeatedly

There is a whole **TOR Ports** series on Deadly Stream - Kira Carsen, Jaesa
Willsaam, Meetra Surik, Pureblood Sith male and female - each shipped for both
K1 and TSL. Feasibility is not in question; the path exists and people have
walked it.

Worth reading before starting:
[Kira Carsen for K1](https://deadlystream.com/files/file/1303-tor-ports-kira-carsen-female-player-head-for-k1/),
[Meetra Surik for K1](https://deadlystream.com/files/file/1302-tor-ports-meetra-surik-aka-jedi-exile-female-player-head-for-k1/).

## The blocker they hit, and why it is not ours

The documented problem is the **16-bone limit**:

> KOTOR has a maximum bone limit per mesh of 16. Adding the eyelids to the face
> bone array pushes that to 18.

Their fix was to drop two bones - the nose corners, "as they seemed the least
important" - without knowing what it would do to facial animation.

**That constraint comes from bringing the TOR skeleton across.** We never do.
The host keeps its own hierarchy, bones and animations, and only geometry
crosses; weights are either remapped from the donor when the rigs share bone
names, or transferred from the host by proximity when they do not. A SWTOR head
shares no bone names with KOTOR, so it takes the second path - the same one the
Tripo head took, which worked.

Two things from our own corpus are worth handing back to that community:

* **16 is the size of the `bone_indices` table in the skin header, not a cap on
  what a mesh may use.** Twenty-one vanilla K1 meshes use **17** bones -
  `c_brith:Brith_mesh`, `c_ithorian:torso`, `c_iriaz:IriazUpr`,
  `c_terantanak:Torso`, `l_selkath:head` and a run of `m01aa_*` cutscene heads
  among them. The engine reads the bonemap, not the fixed table, so dropping two
  bones may not have been necessary.

  (An earlier draft of this said ten meshes and named Yoda, a Trandoshan and
  Juhani's torso. That was wrong on both the count and every example; the
  figure above is measured across all 2,832 models and agrees with the skinning
  census in `SKINNING_FINDINGS.md`.)
* The other reported symptoms - lips not moving, a seam down the middle of the
  face - are what a whole-model port produces when the K2/TOR skeleton meets a
  K1 supermodel. See `KOTOR2_FINDINGS.md`; the same class of problem, same cause.

## Getting the assets out

SWTOR ships 101 `.tor` archives totalling **55 GB**, in HeroEngine's `MYP`
container. Heads live in `swtor_main_art_dynamic_face_b_1.tor` (1.37 GB,
**11,001 files**).

The container is tractable: its file table parses on a first attempt, with a
sane block structure (1,000 entries per block, valid offsets, per-file
compression flags), and a few entries decompress to `DDS` textures. But a
partial reader is worse than none - most entries did not decompress, so the
entry layout guessed here is incomplete, and the payload of interest is `.gr2`
(Granny), a proprietary format that is a serious project on its own.

**Do not write this.** It is thoroughly solved:

| tool | does |
|---|---|
| [ExtracTOR / EasyMYP / Slicers GUI](https://github.com/SWTOR-Slicers) | unpack `.tor` archives |
| [ZG SWTOR Tools](https://github.com/SWTOR-Slicers/ZG-SWTOR-Tools) | Blender add-on: import `.gr2`, assemble and texture a character |
| [SWTOR-Slicers WikiPedia](https://github.com/SWTOR-Slicers/WikiPedia) | file formats and step-by-step guides |

## The pipeline, end to end

Nothing new is needed on our side. Our importer already takes `.glb`, which
Blender exports:

```
.tor  --(ExtracTOR)-->  .gr2 + DDS
      --(ZG SWTOR Tools in Blender)-->  assembled, textured character
      --(Blender export)-->  head.glb
      --(kmdlfun import)-->  head pack
      --(kmdlfun head --decimate --repair --fit)-->  a KOTOR head
```

Every step after Blender is built and tested: `.glb` reading with node
transforms, decimation with a clustering pass for dense input, winding repair,
solidity checking, alpha-preserving textures, fitting, weight transfer with the
orphan-bone rescue.

## What to expect, from what we already know

* **Density.** A SWTOR head is far past KOTOR's ~700-triangle budget, so
  decimation will do most of the work. It handled a 1.2-million-triangle scan;
  this is easier.
* **Solidity is the thing to watch.** The scanned head failed at 64% and read as
  full of holes. The build reports it before anything is installed.
* **Hair is the risk, not the face.** Individually modelled strands become a
  self-intersecting tangle when reduced to a KOTOR budget. A head with simple or
  no hair is the sensible first attempt.
* **The eyes.** Keep the texture's alpha channel. Dropping it is what cost a
  Quarren its eyes, and SWTOR textures are DDS with alpha throughout.

## Verdict

Feasible, and cheaper than it looks, because the hard parts belong to other
people's tools and the one documented blocker does not apply to how we do it.
The work on our side is a `.glb` away from what already runs.
