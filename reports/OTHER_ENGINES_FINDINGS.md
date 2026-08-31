# Reading other Aurora and Odyssey games

**Date:** 2026-08-31
**Question:** can we take assets from the other games built on this engine?
**Answer:** both containers open with twenty lines of code, both model formats
stop in the same place - the node structures - and Jade Empire gets much
further than Neverwinter Nights before it does.

Measured against Neverwinter Nights: Enhanced Edition (Steam, 12 GB) and Jade
Empire: Special Edition (Steam). Nothing here is reasoned from memory.

---

# Neverwinter Nights

## The container is not a problem

`data/nwn_base.key` is Aurora KEY V1 - the same family KOTOR uses - and parses
straight off, with no library:

| | |
|---|---|
| BIF archives | 60 |
| resources | 113,489 |
| **models (type 2002)** | **32,832** |
| player head models (`pfh0_head001`…) | 106 |
| body part models (`pfh0_chest001`…) | 128 |

Pulling one out of its BIF works too (`BIFF V1`, 16-byte variable table). So
"get the files out" is solved, and was never the hard part.

## The models are two formats, not one

**Tilesets are ASCII.** `dag01_a01_01` opens as text - "Exported from NWmax",
then `newmodel`, `node dummy`, `parent`, `position`. Readable with a text
parser and no format knowledge at all.

**Character models are binary.** `pfh0_head001` has not a keyword in it.

That split matters: a survey that sampled one tileset would conclude NWN is
trivially readable, and be wrong about every model anyone actually wants.

## The binary header is KOTOR's, exactly

This is the surprising part. `pfh0_head001`, 14,948 bytes:

```
leading word        0
model data size     8388
raw data size       6548
12 + 8388 + 6548 =  14948   <- the file size, exactly
function pointers   (4242368, 4242384)   at +12
model name          'pfh0_head001'       at +20
```

Every structural check our parser makes on the wrapper passes. The function
pointers sit where K1's `(4273776, 4216096)` and K2's `(4285200, 4216320)` sit,
in the same shape. The name is in the same place.

And the third field is the punchline: KOTOR's wrapper says how big the
*separate* MDX file is, while NWN's says how big the raw block appended to
**this** file is. NWN is KOTOR with the MDX inlined. Splitting the file at
`12 + model_size` produces an MDL and an MDX whose sizes our wrapper check
accepts without complaint.

## Where it stops

Registering the pointer pair gets past the game check and straight into
nonsense - a node offset of 1,056,964,620 in an 8,400-byte buffer. The wrapper
and model header are shared ancestry; the node and geometry structures are not.
Three years separate NWN from KOTOR and that is where they went.

So this is a reader project, not a table entry. K2 cost three constants because
K2 *is* Odyssey; NWN is Aurora, and only the outermost layer survived intact.

## What to do instead

**Neverblender** imports `.mdl` into Blender, including Enhanced Edition
models. Export `.glb`, hand it to `kmdlfun import`, and the existing pipeline
takes it from there - the same route as SWTOR, and no new code here.

Worth trying before any of it: NWN heads are the right *size* for KOTOR in a
way SWTOR heads are not. They are contemporaries, built to comparable budgets,
so decimation should have little to do - and 106 shipped player heads plus two
decades of community content is a lot of material.

The thing to check first is proportion rather than density. NWN faces are more
stylised than KOTOR's, and `kmdlfun rank` will say by how much once one is
through Blender.

---

# Jade Empire

Odyssey, three years after KOTOR, and it shows: this is the closest thing to
our own format that is not our own format.

## Containers, both of them

`chitin.key` is KEY V1 and opens exactly like KOTOR's - but holds only effects:
1,164 models, 1,163 of them named `v_*`. The characters and areas live in **928
`RIM V1.0` archives** under `data/`, whose header keeps the resource count at
+12 and the table at +16, with 32-byte entries. `global-a.rim` alone holds 332
models.

One thing worth writing down: **MDX is resource type 3016 here, not KOTOR's
3008.** Looking for 3008 finds zero MDX files and invites the conclusion that
Jade Empire has none. It has exactly as many as it has models.

## The wrapper is KOTOR's, eight bytes longer

```
+0   00 00 87 00   version stamp        (KOTOR: zero)
+4   mdl size                           (KOTOR: +4)
+8   mdx size                           (KOTOR: +8)
+12  0             ] two fields KOTOR does not have
+16  0             ]
+20  function pointers                  (KOTOR: +12)
+28  model name                         (KOTOR: +20)
```

`mdl size` is **exactly the file size minus 20** on every model measured, so
the 20-byte wrapper is not a guess. All 41 models tried carry the same function
pointer pair, `(4521744, 4388016)`, which is a game signature in the same way
K1's `(4273776, 4216096)` and K2's `(4285200, 4216320)` are.

The MDX is a separate file whose size the wrapper declares, exactly like
KOTOR - except the file is often *larger* than the declared size. It matches to
the byte on simple models (480/480, 456/456, 3000/3000) and runs over on
complex ones, by amounts that follow no ratio. Something is appended that the
model header does not account for.

## How far it gets

Re-expressing the 20-byte wrapper as KOTOR's 12 - zero the version word, drop
the two spare fields, and keep the body from byte 20 - produces a buffer our
parser accepts through the wrapper *and* the model header. It then fails inside
the node walk, on a controller array whose span lands out of bounds.

So the outer format is a small, fully-understood delta, and the node structures
are not. That is the same wall Neverwinter hits, reached from much closer.

## Verdict for both

Neither is the "three constants" job K2 was, and both are worth doing through
Blender rather than through a new reader. What the measurements do settle is
*why*: it is never the container, and never the file header. It is always the
node and geometry structures, which are the part that actually changed between
these games.

## The rest of the family

**NWN2** (Electron, `.mdb`), **The Witcher 1** (`.mdb`) and **Dragon Age**
(Eclipse, `.mmh`/`.msh`) share no code path with any of this. Not measured -
not installed - and not close enough to be worth installing on this evidence.
