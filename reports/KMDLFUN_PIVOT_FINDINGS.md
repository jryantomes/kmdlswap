# kmdlfun: why the eyes vanished, and what a mesh-only effect can never do

Three reports from in-game testing of the first kmdlfun build:

1. big head — **the eyes are gone**;
2. big head on Mission — **her headband has gone see-through**;
3. chibi — **limbs shrank, but the character is the same height and the limbs
   are disconnected**.

(1) and (2) are the same bug and are fixed. (3) is not a bug in the same sense:
it is the ceiling of what an effect that only edits geometry can reach, and the
report below says what it would take to lift it.

## 1 & 2 — every node grew about a different point

A human head is not one mesh. `p_missionh` draws ten: the face skin, the lekku,
the skullcap, two eyeballs, two eyelids, two rows of teeth and a tongue. Each is
its own node, with its own origin, and node origins live in headers kmdlswap
does not move.

The first version scaled each node about the centre of its own bounding box.
That keeps a *single* mesh visually in place, which is why it looked right on
HK-47 — his head is one node. On a head made of ten it pins all ten centres
where they were while each grows independently, so the parts stop lining up.
Measured on `p_missionh` at 1.6x, in model space:

| node | centre before | centre after (old) | grew by |
|------|---------------|--------------------|---------|
| face skin `head` | (+0.000, +0.075, +0.106) | unchanged | 0.203 -> 0.324 |
| eyeball `eyeLA`  | (-0.030, +0.066, +0.148) | unchanged | 0.033 -> 0.053 |
| skullcap `HairCap` | (+0.001, +0.032, +0.166) | unchanged | 0.193 -> 0.310 |

The face skin gains 0.06 of reach in every direction; the eyeball, being small,
gains 0.01. The gap between the eyeball and the face skin it sits behind goes
from **0.0028 to 0.0236** - eight times vanilla.

"The eyes seem non-existent" is that gap, measured the way the eye sees it. The
face points along +y, so an eyeball vertex is visible exactly when no face-skin
triangle sits in front of it. Casting a ray from each of `eyeLA`'s 17 vertices:

| | eyeball vertices with a clear line out |
|---|---|
| vanilla | 11.8% (2 of 17 - the sliver of eye in the socket) |
| bighead 1.6x, old pivot | **0.0%** |
| bighead 1.6x, joint pivot | 11.8% |

The eyes were not shrunk or moved. They were swallowed. The skullcap is a thin
shell hugging the head; the same de-registration puts the forehead skin *through*
it, which is what "the headband went see-through" looks like from outside.

## The fix: one pivot for the group, converted into each node's space

For a node whose rest transform is `x -> R x + t`, scaling the whole model about
a point `C` is, inside that node:

    v  ->  f v + (1 - f) R^T (C - t)

a uniform scale plus a constant translation - exactly what the splice path can
already express, and exact for every node in the group at once.

`C` is the head joint, read from the skeleton rather than guessed: every human
head model in K1 carries `head_g` (the bone the head hangs from) and its parent
`Hturn_g` at the same point. The head then grows *out of the neck*, which is
what a big head is supposed to do.

Verified as properties, not impressions: every pairwise distance between the ten
node centres scales by 1.6 within 1e-4; the eyeball-to-skin clearance lands on
0.00451 = 0.00282 x 1.6 exactly; and the share of eyeball that shows through the
socket comes back identical to vanilla
(`test_a_head_made_of_many_nodes_stays_assembled`,
`test_eyes_keep_their_clearance_from_the_face`,
`test_the_eyeball_is_still_visible_through_the_socket`).

The joint pivot is also the least wrong choice for a *skinned* head. The face
skin's weights: `head_g` 57%, `f_jaw_g` 15%, the rest spread over small facial
bones. Vertices weighted to `head_g` are rigid with respect to the pivot, so
they animate exactly as before, only bigger. Only the vertices driven by the
small facial bones over-swing, by `(f - 1)` times their distance from the bone.

## The mesh you scaled might not be one the game draws

Byte 313 of the trimesh subheader is a render flag. Corpus-wide it is only ever
0 or 1, and **18,058 of the 76,767 vanilla mesh nodes are 0**.

A human body model draws exactly three meshes - `torso` (which is the whole
body, legs included), `LArm` and `RArm`. Everything else, forty-odd `_g` boxes,
is skeleton. The old build reported "45 nodes changed" for chibi on
`p_missionbb` when 42 of them were invisible. Effects now target visible meshes
only, so `hand` and `foot` correctly report *nothing matches* on a human body
instead of quietly scaling bone boxes.

## Stored per-mesh bounds have to follow the geometry

The trimesh subheader carries a bounding box, a radius and an average point, and
the engine culls and sorts by them. A resize left them describing the old mesh.

They are now transported under the same map the geometry took, rather than
recomputed, because vanilla's are not tight. Over all 76,703 mesh nodes
(`tools/mesh_bounds_census.py`):

| | count |
|---|---|
| box strictly larger than the geometry | 40,063 |
| box tight to the geometry | 36,640 |
| box too small for the geometry | **0** |
| radius = max distance from `average` | 76,337 |
| `average` = vertex centroid | 28,776 |

A stored box is always a valid bound but often a padded one, and `average` is
not the centroid two times in three. Under `v -> f v + d` with `f > 0` the
transported box is exactly the image of the stored one, so vanilla's slack is
preserved instead of being invented anew.

## 3 — chibi, and the wall it is standing against

Chibi shrinks the body and grows the head. Two things happen that it cannot fix
from inside a mesh:

**The character stays the same height.** Height is where the bones are. The
visible body meshes shrink, but `head_g` on the body model stays at z = 1.475,
so the head model - a separate file, attached at that bone - hangs where it
always did, above a body that no longer reaches it.

**The limbs come apart.** The three visible body meshes are skinned across the
whole skeleton: `torso` draws weight from `torsoUpr_g` (33%), `pelvis_g` (12%),
both thighs, both shins; `LArm` from `lhand_g` (22%), `lforearm_g` (13%),
`lbicep_g`, the fingers. Shrinking those vertices while every bone stays put
means each vertex now rotates about a joint it is no longer near. At rest the
seams show as gaps; in motion the error grows with the swing - about
`(1 - f)` x distance-to-bone x angle - so an arm at 0.7x visibly leaves its
shoulder as it swings.

No pivot fixes this. A uniformly smaller animated character requires the rest
positions in the node headers, the position controllers inside the animations,
and the skin bind transforms to be scaled with the geometry - moving the rig,
not just the mesh. That is a milestone, not a parameter, and it is worth doing:
all three are same-size, in-place patches, so the splice engine would not even
have to move a byte. HK-47 and T3-M4 would be the place to start, because their
limbs are rigid meshes in a hierarchy with no skin bind data to keep consistent.

Until then chibi is honest about being a caricature that only bends geometry:
heads and extremities work, whole-body proportions do not.
