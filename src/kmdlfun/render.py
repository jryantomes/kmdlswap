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

Z is up and **KOTOR characters face +Y**, so the default camera sits on +Y
looking towards -Y. That direction was wrong here until textures went in: the
project had inherited "characters face -Y" from `tools/blender_render.py`, and
an untextured low-poly head looks equally plausible from either side, so nothing
contradicted it. Four textured models settled it at once - Carth, Bastila,
Dustil and Mission all show a face only from +Y. `tools/blender_render.py` still
has the old direction and its catalogue renders every character from behind.

Three decisions worth stating, because they are not the obvious ones:

* **No backface culling, and two-sided lighting.** Our own head spec tolerates
  up to 5% of faces winding against their normals, so culling by winding would
  punch holes in meshes we consider acceptable. The depth buffer decides what is
  visible; shading uses ``|n.l|`` so a back-facing triangle is lit, not black.
* **Framing comes from the unrotated bounding sphere.** Fitting the projected
  silhouette each frame would make the model breathe in and out as you turn it.
  A sphere is rotation-invariant, so the framing holds still. Passing the same
  `bounds` to two renders also makes them directly comparable, which is the
  whole point of a before-and-after.

* **Texturing is affine, with no perspective correction.** That is exact rather
  than approximate here, because the projection is orthographic.

It draws geometry and one diffuse texture. There is no animation, no lightmap
and no transparency - so it still says nothing about the one failure this
project knows is real, that a skinned head's vertex count must not change. A
preview is not proof either.
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

# Characters face +Y, so the camera's home position is opposite a bare yaw of 0.
# Measured from textured models, not assumed - see the module docstring.
FRONT_YAW = np.pi

LIGHT = np.array([-0.35, 0.80, 0.48], dtype=np.float64)
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
    uvs: np.ndarray | None = None              # (N, 2) float64, or None
    face_texture: np.ndarray | None = None     # (M,) int, index into `textures`
    textures: list = field(default_factory=list)   # each (H, W, 3) uint8

    @property
    def textured(self) -> bool:
        return bool(self.textures) and self.uvs is not None

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


def node_texture(layout: Layout, node) -> str:
    """The texture name in a node's trimesh header, as the engine reads it."""
    at = node.trimesh_at + ke.TEXTURE_AT
    raw = bytes(layout.mdl[at : at + ke.TEXTURE_FIELD])
    return raw.split(b"\0")[0].decode("ascii", "replace").strip()


def from_layout(
    layout: Layout,
    *,
    highlight: frozenset[str] = frozenset(),
    include_hidden: bool = False,
    texture_lookup=None,
) -> Scene:
    """Build a scene from a parsed model.

    `highlight` names nodes to draw in the accent colour - the ones an operation
    touched. With `include_hidden`, meshes the render flag turns off are drawn in
    a muted grey instead of skipped, which is how you see what `--hide` did.

    `texture_lookup` maps a texture name to an (H, W, 3) uint8 array, or None if
    it cannot be found. Passing one switches the scene to textured drawing. It is
    a callable rather than a path so this module needs neither PyKotor nor PIL -
    the format knowledge stays in `textures.py`, the same way Blender is only
    ever a renderer here and never the format engine.
    """
    pose = space.rest_pose(layout)
    chunks_v: list[np.ndarray] = []
    chunks_f: list[np.ndarray] = []
    chunks_c: list[np.ndarray] = []
    chunks_uv: list[np.ndarray] = []
    chunks_tex: list[np.ndarray] = []
    names: list[str] = []
    images: list[np.ndarray] = []
    by_name: dict[str, int] = {}
    base = 0
    any_uv = False

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

        uv1 = geo.columns.get("uv1")
        if uv1:
            chunks_uv.append(np.asarray(uv1, dtype=np.float64))
            any_uv = True
        else:
            chunks_uv.append(np.zeros((len(world), 2)))

        slot = -1
        if texture_lookup is not None and uv1 and node.name not in highlight:
            name = node_texture(layout, node)
            if name:
                if name not in by_name:
                    image = texture_lookup(name)
                    by_name[name] = -1 if image is None else len(images)
                    if image is not None:
                        images.append(np.asarray(image, dtype=np.uint8))
                slot = by_name[name]
        chunks_tex.append(np.full(len(f), slot, dtype=np.int32))

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
        uvs=np.concatenate(chunks_uv) if any_uv else None,
        face_texture=np.concatenate(chunks_tex) if images else None,
        textures=images,
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
    """World to view. Yaw turns about the model's up axis, pitch tips the camera.

    This is bare rotation. `render` adds `FRONT_YAW` so that a caller's yaw of 0
    means "facing the camera" rather than "aligned with +Y".
    """
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
    cull: bool = False,
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
    view = view @ view_matrix(yaw + FRONT_YAW, pitch).T

    # Orthographic: the bounding sphere fills the frame, less a small margin.
    scale = (dim / 2.0) * 0.92 * zoom / radius
    px = view[:, 0] * scale + dim / 2.0
    py = dim / 2.0 - view[:, 2] * scale      # screen y grows downwards
    depth = view[:, 1]                        # camera on -Y, so smaller is nearer

    faces = scene.faces
    face_colour = scene.face_colour
    face_texture = scene.face_texture
    if cull:
        # Draw only what the engine would. Normally this renderer is two-sided,
        # because our own head spec tolerates 5% of faces winding against their
        # normals - but that tolerance also makes an inside-out mesh look
        # perfect here and full of holes in game, which is exactly how one got
        # there. `cull` is the preview that can see that class of bug.
        p0 = view[faces[:, 0]]
        n = np.cross(view[faces[:, 1]] - p0, view[faces[:, 2]] - p0)
        front = n[:, 1] < 0.0            # camera looks along +Y in view space
        faces = faces[front]
        face_colour = face_colour[front]
        if face_texture is not None:
            face_texture = face_texture[front]
        if len(faces) == 0:
            return _to_uint8(img, size, ss)

    shade = _shading(view, faces)
    colours = np.clip(face_colour * shade[:, None], 0.0, 1.0)

    uv = tex_ids = None
    if scene.textured and face_texture is not None:
        uv = scene.uvs
        tex_ids = face_texture.tolist()

    _rasterise(px, py, depth, faces, colours, img, dim,
               uv=uv, tex_ids=tex_ids, textures=scene.textures, shade=shade)
    return _to_uint8(img, size, ss)


def _shading(view: np.ndarray, faces: np.ndarray) -> np.ndarray:
    p0 = view[faces[:, 0]]
    n = np.cross(view[faces[:, 1]] - p0, view[faces[:, 2]] - p0)
    length = np.linalg.norm(n, axis=1)
    length[length < 1e-15] = 1.0
    n /= length[:, None]
    # Two-sided: winding is not reliable enough to decide which face is lit.
    return AMBIENT + (1.0 - AMBIENT) * np.abs(n @ LIGHT)


def _rasterise(px, py, depth, faces, colours, img, dim,
               *, uv=None, tex_ids=None, textures=(), shade=None):
    """Half-space rasteriser with a z-buffer, one triangle at a time.

    Normalising the barycentrics by the *signed* area makes the inside test work
    for either winding, which is what lets us skip culling entirely.

    Texturing is affine in the barycentrics with no perspective correction, which
    is not an approximation here: the projection is orthographic, so affine
    interpolation across a triangle is exact.
    """
    zbuf = np.full((dim, dim), np.inf)
    x0, x1, x2 = (px[faces[:, i]].tolist() for i in range(3))
    y0, y1, y2 = (py[faces[:, i]].tolist() for i in range(3))
    d0, d1, d2 = (depth[faces[:, i]].tolist() for i in range(3))
    cols = colours.tolist()

    if uv is not None and tex_ids is not None:
        u0, u1, u2 = (uv[faces[:, i], 0].tolist() for i in range(3))
        v0, v1, v2 = (uv[faces[:, i], 1].tolist() for i in range(3))
        lighting = shade.tolist()
    else:
        tex_ids = None

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

        slot = tex_ids[i] if tex_ids is not None else -1
        if slot < 0:
            img[lo_y:hi_y, lo_x:hi_x][hit] = cols[i]
            continue

        tex = textures[slot]
        th, tw = tex.shape[0], tex.shape[1]
        u = (l0 * u0[i] + l1 * u1[i] + l2 * u2[i])[hit]
        v = (l0 * v0[i] + l1 * v1[i] + l2 * v2[i])[hit]
        # Measured, not assumed: V runs down the image the same way the rows do,
        # so no flip. Flipping it puts a head's hair below its eyes.
        # `% 1` wraps, which is what a tiling UV outside [0, 1] expects.
        cu = np.minimum((u % 1.0) * tw, tw - 1).astype(np.int32)
        cv = np.minimum((v % 1.0) * th, th - 1).astype(np.int32)
        texel = tex[cv, cu].astype(np.float64) / 255.0
        img[lo_y:hi_y, lo_x:hi_x][hit] = texel * lighting[i]


def join(scenes) -> Scene:
    """One scene from several, keeping each one's textures."""
    scenes = [s for s in scenes if s.triangles]
    if not scenes:
        return Scene(np.zeros((0, 3)), np.zeros((0, 3), np.int32), np.zeros((0, 3)))
    if len(scenes) == 1:
        return scenes[0]

    positions, faces, colours, uvs, tex, images, groups = [], [], [], [], [], [], []
    vertex_base = 0
    texture_base = 0
    for s in scenes:
        positions.append(s.positions)
        faces.append(s.faces + vertex_base)
        colours.append(s.face_colour)
        uvs.append(s.uvs if s.uvs is not None else np.zeros((len(s.positions), 2)))
        if s.face_texture is None:
            tex.append(np.full(len(s.faces), -1, dtype=np.int32))
        else:
            shifted = s.face_texture.copy()
            shifted[shifted >= 0] += texture_base
            tex.append(shifted)
        images.extend(s.textures)
        texture_base += len(s.textures)
        groups.extend(s.groups)
        vertex_base += len(s.positions)

    faces_all = np.vstack(faces)
    return Scene(
        positions=np.vstack(positions),
        faces=faces_all,
        face_colour=np.vstack(colours),
        groups=groups,
        triangles=len(faces_all),
        uvs=np.vstack(uvs) if images else None,
        face_texture=np.concatenate(tex) if images else None,
        textures=images,
    )


def character(body: Layout, head: Layout | None = None, **kwargs) -> Scene:
    """A whole character: the body, with its head model set on the head hook.

    Human companions keep the head in a separate model, so rendering the body
    alone shows a decapitated figure and rendering the head alone shows a
    floating head. Neither tells you what an effect did. The body carries a
    `headhook` node whose rest transform is where the head model's origin goes.
    """
    scene = from_layout(body, **kwargs)
    if head is None:
        return scene
    try:
        hook = space.rest_pose(body)[body.node_by_name("headhook").index]
    except KeyError:
        return scene              # a self-contained model has no hook and needs none

    on_head = place_head(body, head, **kwargs)
    return scene if on_head is None else join([scene, on_head])


def place_head(body: Layout, head: Layout, **kwargs) -> Scene | None:
    """Just the head, moved onto the body's hook - or None if there is no hook.

    Split out of `character` so a caller can frame the head without drawing the
    body alone to find it. A head swap is judged on the face, and on a whole
    standing figure the face is a few dozen pixels.
    """
    try:
        hook = space.rest_pose(body)[body.node_by_name("headhook").index]
    except KeyError:
        return None
    on_head = from_layout(head, **kwargs)
    rotation = np.asarray(hook.rotation, dtype=np.float64)
    on_head.positions = on_head.positions @ rotation.T + np.asarray(hook.position)
    return on_head


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
