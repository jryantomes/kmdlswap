# Which way a KOTOR character faces

**KOTOR characters face +Y.** The project had it recorded as −Y, and every
render made before 2026-08-30 — including the whole 164-model catalogue — shows
characters from behind.

## What was wrong

`tools/blender_render.py` carried this, and the in-app previewer inherited it:

> KOTOR characters face -Y (measured: a head's largest front-back asymmetry is
> on Y, negative), so the camera sits on -Y looking towards +Y.

The asymmetry measurement was real. The sign was read the wrong way round.

## Why it survived so long

Because nothing contradicted it. An untextured low-poly KOTOR head looks
equally plausible from either side — the geometry is nearly flat at the face and
the detail lives entirely in the texture. Renders of the back of a head read as
"a low-poly head", not as an error.

It also survived a deliberate check. When the previewer was built I marked the
20 most −Y vertices of `p_carthh`, rendered the default view, and saw them fully
visible — and concluded the camera was right. The marking was correct and the
conclusion did not follow: it proved the camera was looking at the −Y side, and
assumed without evidence that −Y was the face. The test confirmed the thing that
was not in doubt.

## What settled it

Two independent lines, both decisive:

1. **Textures.** With the diffuse texture applied, `p_carthh`, `p_bastilah`,
   `n_dustilh` and `p_missionh` all show a face only from +Y. There is no
   ambiguity at all once a face is painted on.
2. **Anatomy.** Every `eye*`, `teeth*` and `tongue` node in a vanilla head sits
   at positive Y relative to the head's centre. The only facial-model node
   measured behind centre is Bastila's `HAIR`.

| model | eyes | teeth | tongue | hair |
|---|---|---|---|---|
| p_carthh | +0.087 | +0.104 | +0.091 | +0.106 |
| p_bastilah | +0.062 | +0.079 | +0.064 | −0.027 |
| n_dustilh | +0.087 | +0.104 | +0.091 | — |

(Mean Y per node; head centres are +0.020, −0.010 and +0.021.)

Anatomy is the better test of the two because it needs no texture decoding and
no eye, so it is the one now in the suite
(`tests/test_render.py::test_the_default_view_looks_at_the_face`).

## Fixed

- `src/kmdlfun/render.py` — `FRONT_YAW = pi`, so a caller's yaw of 0 faces the
  camera. The key light was mirrored to match.
- `tools/blender_render.py` — camera moved to +Y and turned round.

## Still stale

Any catalogue images rendered before this fix show the backs of heads and should
be regenerated (`python tools/render_catalogue.py --install "<K1 root>"`).

## The lesson worth keeping

A test that confirms what you already believe is not evidence. The marker check
felt like verification and was not, because it could not have come out the other
way — whatever the camera pointed at, the vertices nearest it would have been
visible. The question was never "which side is the camera on" but "which side is
the face on", and only data that knows what a face is could answer it.
