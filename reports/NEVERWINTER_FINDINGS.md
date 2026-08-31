# Reading Neverwinter Nights

**Date:** 2026-08-31
**Question:** can we take assets from other Aurora/Odyssey games?
**Answer for NWN:** the container reads today with twenty lines of code. The
models do not, and the reason is more interesting than "different format".

Measured against Neverwinter Nights: Enhanced Edition, Steam, 12 GB.

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

## For the rest of the family

* **Jade Empire** is Odyssey, ships `.mdl`+`.mdx`, and is the only other game
  where our reader might genuinely be a few constants from working. Untested -
  not installed.
* **NWN2** (Electron, `.mdb`), **The Witcher 1** (`.mdb`), **Dragon Age**
  (Eclipse, `.mmh`/`.msh`) share no code path with any of this.
