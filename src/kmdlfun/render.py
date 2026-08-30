"""A small software renderer, so you can look at a model without leaving the app.

Deliberately not Blender. `tools/render_catalogue.py` shells out to Blender and
that is right for a 164-model batch, but starting Blender costs several seconds
and a preview you have to wait for is a preview you stop using. This rasterises
in numpy: a few thousand triangles at 480x480 in well under a tenth of a second,
which is fast enough to drag the model around with the mouse.

What it renders is the **posed model as the engine will read it** - parsed back
out of MDL/MDX bytes through the same `extract` path the rest of the tool uses,
posed into model space by `space.rest_pose`, and filtered to the meshes the
render flag says are actually drawn. So previewing a build is a real check on
the output bytes rather than a re-display of the input mesh.

Conventions match `tools/blender_render.py` so the two agree: Z is up, KOTOR
characters face -Y, so the default camera sits on -Y looking towards +Y.

Two decisions worth stating, because they are not the obvious ones:

* **No backface culling, and two-sided lighting.** Our own head spec tolerates
  up to 5% of faces winding against their normals, so culling by winding would
  punch holes in meshes we consider acceptable. The depth buffer decides what is
  visible; shading uses ``|n.l|`` so a back-facing triangle is lit, not black.
* **Framing comes from the unrotated bounding sphere.** Fitting the projected
  silhouette each frame would make the model breathe in and out as you turn it.
  A sphere is rotation-invariant, so the framing holds still. Passing the same
  `bounds` to two renders also makes them directly comparable, which is the
  whole point of a before-and-after.

It draws untextured flat-shaded geometry. It cannot show a texture, and it
cannot show animation - so it says nothing about the one failure this project
knows is real, that a skinned head's vertex count must not change. A preview is
not proof either.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from kmdlswap import edit as ke
from kmdlswap.layout import Layout

from . import parts, space

BASE = (0.62, 0.64, 0.70)          # neutral, slightly cool
HIGHLIGHT = (0.93, 0.58, 0.24)     # warm: a node the operation touched
MUTED = (0.34, 0.35, 0.39)         # present in the file but not drawn
BACKGROUND = (0.09, 0.10, 0.12)

LIGHT = np.array([-0.35, -0.80, 0.48], dtype=np.float64)
LIGHT /= np.linalg.norm(LIGHT)
AMBIENT = 0.30


@dataclass
class Scene:
    """Posed, flattened geometry ready to draw. Model space, Z up, facing -Y."""

    positions: np.ndarray                      # (N, 3) float64
    faces: np.ndarray                          # (M, 3) int32
    face_colour: np.ndarray                    # (M, 3) float64
    groups: list[str] = field(default_factory=list)
    triangles: int = 0

    @property
    def bounds(self) -> tuple[np.ndarray, float]:
        """Centre and radius of the bounding sphere used for framing."""
        if len(self.positions) == 0:
            return np.zeros(3), 1.0
        lo = self.positions.min(axis=0)
        hi = self.positions.max(axis=0)
        centre = (lo + hi) / 2.0
        radius = float(np.linalg.norm(self.positions - centre, axis=1).max())
        return centre, max(radius, 1e-6)


def from_layout(
    layout: Layout,
    *,
    highlight: frozenset[str] = frozenset(),
    include_hidden: bool = False,
) -> Scene:
    """Build a scene from a parsed model.

    `highlight` names nodes to draw in the accent colour - the ones an operation
    touched. With `include_hidden`, meshes the render flag turns off are drawn in
    a muted grey instead of skipped, which is how you see what `--hide` did.
    """
    pose = space.rest_pose(layout)
    chunks_v: list[np.ndarray] = []
    chunks_f: list[np.ndarray] = []
    chunks_c: list[np.ndarray] = []
    names: list[str] = []
    base = 0

    for node in parts.mesh_nodes(layout, visible_only=not include_hidden):
        geo = ke.extract(layout, node)
        if not geo.positions or not geo.faces:
            continue
        rest = pose[node.index]
        v = np.asarray(geo.positions, dtype=np.float64)
        rot = np.asarray(rest.rotation, dtype=np.float64)
        world = v @ rot.T + np.asarray(rest.position, dtype=np.float64)

        f = np.asarray([tri.vertices for tri in geo.faces], dtype=np.int32) + base
        if node.name in highlight:
            colour = HIGHLIGHT
        elif not parts.renders(layout, node):
            colour = MUTED
        else:
            colour = BASE

        chunks_v.append(world)
        chunks_f.append(f)
        chunks_c.append(np.tile(np.asarray(colour, dtype=np.float64), (len(f), 1)))
        names.append(node.name)
        base += len(world)

    if not chunks_v:
        return Scene(np.zeros((0, 3)), np.zeros((0, 3), np.int32), np.zeros((0, 3)))
    faces = np.concatenate(chunks_f)
    return Scene(
        positions=np.concatenate(chunks_v),
        faces=faces,
        face_colour=np.concatenate(chunks_c),
        groups=names,
        triangles=len(faces),
    )


def from_mesh(positions, faces, *, colour=BASE) -> Scene:
    """A scene from a bare OBJ-style mesh, for previewing a head pack on its own."""
    v = np.asarray(positions, dtype=np.float64)
    f = np.asarray(list(faces), dtype=np.int32).reshape(-1, 3)
    return Scene(
        positions=v,
        faces=f,
        face_colour=np.tile(np.asarray(colour, dtype=np.float64), (len(f), 1)),
        groups=["mesh"],
        triangles=len(f),
    )


def view_matrix(yaw: float, pitch: float) -> np.ndarray:
    """World to view. Yaw turns about the model's up axis, pitch tips the camera."""
    cy, sy = np.cos(yaw), np.sin(yaw)
    cp, sp = np.cos(pitch), np.sin(pitch)
    about_z = np.array([[cy, -sy, 0.0], [sy, cy, 0.0], [0.0, 0.0, 1.0]])
    about_x = np.array([[1.0, 0.0, 0.0], [0.0, cp, -sp], [0.0, sp, cp]])
    return about_x @ about_z


def render(
    scene: Scene,
    *,
    yaw: float = 0.0,
    pitch: float = 0.0,
    size: int = 480,
    bounds: tuple[np.ndarray, float] | None = None,
    zoom: float = 1.0,
    supersample: int = 2,
    background: tuple[float, float, float] = BACKGROUND,
) -> np.ndarray:
    """Rasterise to a (size, size, 3) uint8 array.

    Pass the same `bounds` to two calls to frame them identically - without that
    a before-and-after pair silently uses two different scales and the comparison
    is worthless.
    """
    ss = max(1, int(supersample))
    dim = size * ss
    img = np.empty((dim, dim, 3), dtype=np.float64)
    img[:] = background
    if scene.triangles == 0:
        return _to_uint8(img, size, ss)

    centre, radius = bounds if bounds is not None else scene.bounds
    view = scene.positions - centre
    view = view @ view_matrix(yaw, pitch).T

    # Orthographic: the bounding sphere fills the frame, less a small margin.
    scale = (dim / 2.0) * 0.92 * zoom / radius
    px = view[:, 0] * scale + dim / 2.0
    py = dim / 2.0 - view[:, 2] * scale      # screen y grows downwards
    depth = view[:, 1]                        # camera on -Y, so smaller is nearer

    shade = _shading(view, scene.faces)
    colours = np.clip(scene.face_colour * shade[:, None], 0.0, 1.0)

    _rasterise(px, py, depth, scene.faces, colours, img, dim)
    return _to_uint8(img, size, ss)


def _shading(view: np.ndarray, faces: np.ndarray) -> np.ndarray:
    p0 = view[faces[:, 0]]
    n = np.cross(view[faces[:, 1]] - p0, view[faces[:, 2]] - p0)
    length = np.linalg.norm(n, axis=1)
    length[length < 1e-15] = 1.0
    n /= length[:, None]
    # Two-sided: winding is not reliable enough to decide which face is lit.
    return AMBIENT + (1.0 - AMBIENT) * np.abs(n @ LIGHT)


def _rasterise(px, py, depth, faces, colours, img, dim):
    """Half-space rasteriser with a z-buffer, one triangle at a time.

    Normalising the barycentrics by the *signed* area makes the inside test work
    for either winding, which is what lets us skip culling entirely.
    """
    zbuf = np.full((dim, dim), np.inf)
    x0, x1, x2 = (px[faces[:, i]].tolist() for i in range(3))
    y0, y1, y2 = (py[faces[:, i]].tolist() for i in range(3))
    d0, d1, d2 = (depth[faces[:, i]].tolist() for i in range(3))
    cols = colours.tolist()

    for i in range(len(cols)):
        ax, bx, cx = x0[i], x1[i], x2[i]
        ay, by, cy = y0[i], y1[i], y2[i]

        lo_x = max(0, int(min(ax, bx, cx)))
        hi_x = min(dim, int(max(ax, bx, cx)) + 2)
        lo_y = max(0, int(min(ay, by, cy)))
        hi_y = min(dim, int(max(ay, by, cy)) + 2)
        if lo_x >= hi_x or lo_y >= hi_y:
            continue

        denom = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(denom) < 1e-12:
            continue

        gx = np.arange(lo_x, hi_x) + 0.5
        gy = (np.arange(lo_y, hi_y) + 0.5)[:, None]
        l0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / denom
        l1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / denom
        l2 = 1.0 - l0 - l1
        inside = (l0 >= 0.0) & (l1 >= 0.0) & (l2 >= 0.0)
        if not inside.any():
            continue

        z = l0 * d0[i] + l1 * d1[i] + l2 * d2[i]
        window = zbuf[lo_y:hi_y, lo_x:hi_x]
        hit = inside & (z < window)
        if not hit.any():
            continue
        window[hit] = z[hit]
        img[lo_y:hi_y, lo_x:hi_x][hit] = cols[i]


def shared_bounds(scenes) -> tuple[np.ndarray, float]:
    """One framing that fits every scene.

    A before-and-after rendered at two different scales is worse than no preview
    at all: a head that grew looks unchanged, and a head that stayed put looks
    like it moved. Both sides have to be measured with the same ruler.
    """
    scenes = [s for s in scenes if s.triangles]
    if not scenes:
        return np.zeros(3), 1.0
    lo = np.min([s.positions.min(axis=0) for s in scenes], axis=0)
    hi = np.max([s.positions.max(axis=0) for s in scenes], axis=0)
    centre = (lo + hi) / 2.0
    radius = max(
        float(np.linalg.norm(s.positions - centre, axis=1).max()) for s in scenes
    )
    return centre, max(radius, 1e-6)


def strip(scenes, *, gap: int = 8, **kwargs) -> np.ndarray:
    """Render several scenes side by side into one image."""
    frames = [render(s, **kwargs) for s in scenes]
    if len(frames) == 1:
        return frames[0]
    h = frames[0].shape[0]
    bg = np.array(kwargs.get("background", BACKGROUND))
    spacer = np.tile((bg * 255).astype(np.uint8), (h, gap, 1))
    out: list[np.ndarray] = []
    for i, f in enumerate(frames):
        if i:
            out.append(spacer)
        out.append(f)
    return np.concatenate(out, axis=1)


def _to_uint8(img: np.ndarray, size: int, ss: int) -> np.ndarray:
    if ss > 1:
        img = img.reshape(size, ss, size, ss, 3).mean(axis=(1, 3))
    return (np.clip(img, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def to_png(pixels: np.ndarray, path) -> None:
    from PIL import Image

    Image.fromarray(pixels, mode="RGB").save(path)
