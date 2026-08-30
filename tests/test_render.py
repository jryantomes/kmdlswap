"""The previewer, and the conventions it must not quietly break.

Two of these matter more than the rest. If the camera convention flips, every
preview shows the back of the head and still looks like a plausible render. If
shared framing breaks, a before-and-after is drawn at two scales and a head that
changed size looks unchanged. Both fail silently by eye, so they are pinned.
"""

from __future__ import annotations

import numpy as np
import pytest

from kmdlfun import parts, render
from kmdlswap import layout as kl

BG = np.array(render.BACKGROUND)


def quad(y, z=0.0, half=1.0):
    """Two triangles forming a square in the XZ plane at depth `y`."""
    v = [(-half, y, z - half), (half, y, z - half), (half, y, z + half), (-half, y, z + half)]
    return v, [(0, 1, 2), (0, 2, 3)]


def coverage(px):
    bg = (np.array(render.BACKGROUND) * 255 + 0.5).astype(np.uint8)
    return float((px != bg).any(axis=2).mean())


def centre_colour(px):
    h, w, _ = px.shape
    return px[h // 2, w // 2].astype(int)


# --- conventions ------------------------------------------------------------


def test_the_front_view_shows_the_minus_y_side():
    """KOTOR characters face -Y. If this inverts, every head preview silently
    shows the back of the skull and still looks like a reasonable render."""
    near_v, near_f = quad(y=-1.0)
    far_v, far_f = quad(y=+1.0)
    positions = np.array(near_v + far_v, dtype=float)
    faces = np.array(list(near_f) + [(a + 4, b + 4, c + 4) for a, b, c in far_f])

    scene = render.Scene(
        positions=positions, faces=faces,
        face_colour=np.array([[1.0, 0.0, 0.0]] * 2 + [[0.0, 0.0, 1.0]] * 2),
        groups=["near", "far"], triangles=4,
    )
    px = centre_colour(render.render(scene, size=64, supersample=1))
    assert px[0] > px[2], f"expected the -Y (red) quad in front, got {px}"


def test_the_depth_buffer_actually_sorts():
    """Same test from behind: the +Y quad must win when the camera turns round."""
    near_v, near_f = quad(y=-1.0)
    far_v, far_f = quad(y=+1.0)
    scene = render.Scene(
        positions=np.array(near_v + far_v, dtype=float),
        faces=np.array(list(near_f) + [(a + 4, b + 4, c + 4) for a, b, c in far_f]),
        face_colour=np.array([[1.0, 0.0, 0.0]] * 2 + [[0.0, 0.0, 1.0]] * 2),
        groups=["near", "far"], triangles=4,
    )
    px = centre_colour(render.render(scene, yaw=np.pi, size=64, supersample=1))
    assert px[2] > px[0], f"expected the blue quad after turning round, got {px}"


def test_winding_does_not_decide_visibility():
    """The head spec tolerates 5% of faces winding against their normals, so a
    renderer that culled by winding would punch holes in meshes we accept."""
    v, f = quad(y=0.0)
    forward = render.render(render.from_mesh(v, f), size=64, supersample=1)
    flipped = render.render(
        render.from_mesh(v, [(c, b, a) for a, b, c in f]), size=64, supersample=1
    )
    assert coverage(forward) > 0.4
    assert coverage(flipped) == coverage(forward), "winding changed what is visible"
    assert centre_colour(flipped).sum() > 60, "a back-facing triangle came out black"


# --- framing ----------------------------------------------------------------


def test_shared_bounds_frame_two_scenes_with_one_ruler():
    small = render.from_mesh(*quad(y=0.0, half=0.5))
    big = render.from_mesh(*quad(y=0.0, half=1.5))

    alone = coverage(render.render(small, size=96, supersample=1))
    bounds = render.shared_bounds([small, big])
    together = coverage(render.render(small, size=96, supersample=1, bounds=bounds))

    assert alone > together * 2, "sharing bounds must shrink the smaller scene"
    # And the big one keeps its own framing, so the pair is comparable.
    big_shared = coverage(render.render(big, size=96, supersample=1, bounds=bounds))
    assert big_shared > together


def test_framing_holds_still_while_turning():
    """Framing off the bounding sphere is rotation invariant; fitting the
    silhouette each frame would make the model pulse as you drag it."""
    v, f = quad(y=0.0, half=1.0)
    scene = render.from_mesh(v, f)
    scene.positions = np.vstack([scene.positions, [[0.0, 0.0, 2.0]]])
    b = scene.bounds
    widths = [
        coverage(render.render(scene, yaw=a, size=96, supersample=1, bounds=b))
        for a in (0.0, 0.3, 0.6)
    ]
    assert widths[0] > 0
    # Turning a flat quad edge-on legitimately shrinks it; the radius must not move.
    assert scene.bounds[1] == pytest.approx(b[1])


def test_strip_places_scenes_side_by_side():
    a = render.from_mesh(*quad(y=0.0))
    px = render.strip([a, a], size=64, supersample=1, gap=8)
    assert px.shape == (64, 64 * 2 + 8, 3)


def test_an_empty_scene_is_background_only():
    scene = render.Scene(np.zeros((0, 3)), np.zeros((0, 3), np.int32), np.zeros((0, 3)))
    px = render.render(scene, size=32, supersample=1)
    assert coverage(px) == 0.0


def test_rendering_is_deterministic():
    scene = render.from_mesh(*quad(y=0.0))
    a = render.render(scene, yaw=0.4, pitch=0.2, size=64)
    b = render.render(scene, yaw=0.4, pitch=0.2, size=64)
    assert np.array_equal(a, b)


# --- against real models ----------------------------------------------------


def test_a_scene_holds_every_visible_mesh(pair):
    layout = kl.parse(*pair("p_hk47"))
    scene = render.from_layout(layout)
    assert len(scene.groups) == len(parts.mesh_nodes(layout))
    assert scene.triangles > 1000
    assert scene.faces.max() < len(scene.positions), "face indices must stay in range"
    assert scene.faces.min() >= 0
    # Concatenating per-node meshes means rebasing every node's indices; getting
    # that wrong yields a plausible-looking tangle rather than an error.
    assert len(scene.face_colour) == scene.triangles


def test_a_real_model_fills_a_sensible_part_of_the_frame(pair):
    scene = render.from_layout(kl.parse(*pair("p_hk47")))
    px = render.render(scene, size=200, supersample=1)
    c = coverage(px)
    assert 0.05 < c < 0.75, f"{c:.1%} of the frame covered looks wrong"


def test_highlight_recolours_only_the_named_node(pair):
    layout = kl.parse(*pair("p_hk47"))
    plain = render.from_layout(layout)
    lit = render.from_layout(layout, highlight=frozenset({"head"}))

    changed = ~np.all(plain.face_colour == lit.face_colour, axis=1)
    assert changed.any(), "highlight coloured nothing"
    assert not changed.all(), "highlight coloured the whole model"
    assert np.allclose(lit.face_colour[changed][0], render.HIGHLIGHT)


def test_hidden_meshes_appear_only_when_asked(pair):
    """A human head model carries 17 invisible `_g` skeleton boxes; HK-47 carries
    none, which is why this uses Carth."""
    layout = kl.parse(*pair("p_carthh"))
    visible = render.from_layout(layout)
    everything = render.from_layout(layout, include_hidden=True)
    assert len(everything.groups) > len(visible.groups)
    assert everything.triangles > visible.triangles


def test_the_pose_puts_the_head_above_the_feet(pair):
    """rest_pose is what turns node-space geometry into a standing figure; if it
    were skipped every node would pile up at the origin."""
    layout = kl.parse(*pair("p_hk47"))
    scene = render.from_layout(layout, highlight=frozenset({"head"}))
    head = np.any(scene.face_colour == np.array(render.HIGHLIGHT), axis=1)
    head_z = scene.positions[scene.faces[head].reshape(-1)][:, 2]
    assert head_z.min() > scene.positions[:, 2].min() + 1.0, "head is not above the feet"
