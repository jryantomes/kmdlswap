"""Cutting a mouth opening in a face that does not have one.

A head modelled with its lips as separate pieces has no mouth. Measured on Jade
Empire's ``h_common01_`` converted onto Carth, by how far forward each surface
reaches at the mouth (larger is nearer the viewer):

=====================  ==========
surface                front edge
=====================  ==========
face shell skin        **+0.1048**
lip pieces             +0.1005, +0.0962
teeth                  +0.0963, +0.0941
tongue                 +0.0923
mouth interior bag     +0.0883
=====================  ==========

The shell is an unbroken sheet of skin in front of everything else - its only
hole is the neck. The lips, the bag, the teeth and the tongue all sit behind it
and can never be seen, however they are weighted or animated. Reported from the
game as a mouth that looks like the texture is glued shut, which is exactly what
it is: painted lips on a continuous surface.

The texture is not the problem. The Jade atlas carries teeth along its top edge
and a mouth interior at the bottom right; the artwork is all there and nothing
uncovers it.

So the shell has to be opened. The lip rims say where: the aperture is the
ellipse they enclose, and only shell faces inside it, on the front of the head,
are removed. Every other island is left alone - the lips become the rim of the
opening they were already shaped to be.

**Why a KOTOR head needs none of this.** Carth's face is one surface across the
mouth as well, but his lips are *part of it*, weighted to bones that pull them
apart, and his mouth interior sits behind a mouth that opens because the skin
itself parts. Checked directly: none of the 126 duplicated positions in his
`Head` is split between an upward-driven and a downward-driven copy, so there is
no hidden seam - and there does not need to be, because there is no second
surface in the way. A converted head fails because it has *both* a solid shell
and separate lips, and the shell wins.

Nothing here fires unless a head is built that way, so a vanilla-style head, a
body, or anything without a pair of lip pieces passes through untouched.
"""

from __future__ import annotations

import numpy as np

from . import lips

# How far the opening reaches, as a multiple of the rims' own extent.
#
# Width and height are separate, and the height is the one that matters. At 1.0
# the cut takes the whole gap between the upper and lower rim, which is 0.0204
# on `h_common01_` - and a hole in geometry does not close, so that leaves the
# mouth hanging open with the teeth showing at rest. Rendered, it is a gape, not
# a mouth. What a resting mouth wants is a slit: a dark line that becomes an
# opening when the lips part.
# Rendered at rest across 0.25, 0.40 and 0.60: 0.40 and 0.60 both show teeth on
# a resting face, which is a snarl. 0.25 reads as an ordinary closed mouth with
# a dark lip line, and opens onto the interior once the lips part.
SCALE = 1.0
SCALE_HEIGHT = 0.25


def find(positions, faces, *, scale: float = SCALE, scale_height: float | None = None):
    """The shell faces covering the mouth, or None if there is no mouth to open.

    Returns ``(keep, removed, note)`` where ``keep`` is the face list without
    them.
    """
    found = lips.find_lips(positions, faces)
    if found is None:
        return None
    upper, lower, _bag = found

    P = np.asarray([p[:3] for p in positions], dtype=np.float64)
    rim = sorted(set(upper) | set(lower))
    R = P[rim]

    centre_x = (float(R[:, 0].min()) + float(R[:, 0].max())) / 2
    centre_z = (float(R[:, 2].min()) + float(R[:, 2].max())) / 2
    height = SCALE_HEIGHT if scale_height is None else scale_height
    semi_x = (float(R[:, 0].max()) - float(R[:, 0].min())) / 2 * scale
    semi_z = (float(R[:, 2].max()) - float(R[:, 2].min())) / 2 * height
    if semi_x <= 0 or semi_z <= 0:
        return None

    # Only the front. The back of the skull occupies the same x and z as the
    # mouth and would be cut open too without this.
    front = float(np.median(R[:, 1]))

    islands = lips.islands(P, faces)
    if not islands:
        return None
    shell = set(islands[0])

    keep, removed = [], 0
    for face in faces:
        triangle = tuple(face)[:3]
        if set(triangle) <= shell:
            c = P[list(triangle)].mean(axis=0)
            inside = ((c[0] - centre_x) / semi_x) ** 2 + ((c[2] - centre_z) / semi_z) ** 2
            if inside <= 1.0 and c[1] > front:
                removed += 1
                continue
        keep.append(face)

    if not removed:
        return None
    return keep, removed, (
        f"mouth opening: cut {removed} shell faces from an aperture "
        f"{semi_x * 2:.4f} wide by {semi_z * 2:.4f} tall, bounded by the lips"
    )


def cut(
    positions, faces, *, scale: float = SCALE, scale_height: float | None = None
) -> tuple[list, list[str]]:
    """Open the mouth if this head has lips but no opening. A no-op otherwise."""
    found = find(positions, faces, scale=scale, scale_height=scale_height)
    if found is None:
        return faces, []
    keep, _removed, note = found
    return keep, [note]
