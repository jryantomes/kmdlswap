"""What a custom head has to be for this tool to accept it.

Every threshold here is measured from the 33 head meshes the game already ships,
not chosen by taste. A mesh the engine is known to render is the only honest
definition of acceptable, and a rule that vanilla itself would fail is a wrong
rule.

Measured over vanilla `head` meshes:

| property             | median | p90  | worst |
|----------------------|--------|------|-------|
| connected components | 1      | 1    | 2     |
| boundary-edge share  | 1.8%   | 4.4% | 6.2%  |
| triangles            | 690    | -    | 440-796 |

The first Tripo head this project produced had 6 components and 22% boundary
edges, and in-game it read as a hollow faceted shell with a fragment floating
beside it. These checks would have caught all of that before it was ever built.

Checks are graded rather than pass/fail, because "worse than any vanilla head"
and "impossible" are different things and the user should be told which.
"""

from __future__ import annotations

import collections
import math
from dataclasses import dataclass, field

from kmdlswap.obj import ObjMesh

# --- thresholds, from the vanilla corpus -----------------------------------

MAX_COMPONENTS_OK = 2          # vanilla's worst
MAX_COMPONENTS_WARN = 4
BOUNDARY_OK = 0.062            # vanilla's worst
BOUNDARY_WARN = 0.15
TRIANGLES_TYPICAL = (440, 796)  # vanilla's range
TRIANGLES_WARN = 1500          # our own Tripo head shipped at 1198 and rendered
MODEL_BUDGET = 4000            # the brief's practical whole-model ceiling
WINDING_WARN = 0.05

# Share of surface area that must face outward, measured across the 61 vanilla
# 'head' meshes: worst 76.6% (n_selkath), 5th percentile 82.8%, median 93.8%.
# The reject line sits at vanilla's worst, so vanilla always passes.
SOLID_PASS = 0.85
SOLID_REJECT = 0.76
TEXTURE_MAX = 512              # HK-47's body texture; heads ship at 256
RESREF_MAX = 16


@dataclass
class Finding:
    level: str      # "pass" | "warn" | "fail"
    check: str
    detail: str

    def __str__(self) -> str:
        mark = {"pass": "ok  ", "warn": "warn", "fail": "FAIL"}[self.level]
        return f"[{mark}] {self.check}: {self.detail}"


@dataclass
class Verdict:
    findings: list[Finding] = field(default_factory=list)

    def add(self, level, check, detail):
        self.findings.append(Finding(level, check, detail))

    @property
    def failures(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "fail"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warn"]

    @property
    def accepted(self) -> bool:
        return not self.failures

    def lines(self) -> list[str]:
        return [str(f) for f in self.findings]


# --- mesh topology ----------------------------------------------------------


def _weld(positions):
    first: dict = {}
    return [first.setdefault(p, i) for i, p in enumerate(positions)]


def topology(mesh: ObjMesh):
    """Connected components, boundary-edge share and degenerate faces."""
    weld = _weld(mesh.positions)
    adjacency = collections.defaultdict(set)
    edges: collections.Counter = collections.Counter()
    degenerate = 0
    for f in mesh.faces:
        a, b, c = (weld[i] for i in f)
        if a == b or b == c or a == c:
            degenerate += 1
            continue
        adjacency[a] |= {b, c}
        adjacency[b] |= {a, c}
        adjacency[c] |= {a, b}
        for e in ((a, b), (b, c), (c, a)):
            edges[frozenset(e)] += 1

    seen: set = set()
    components = 0
    for v in adjacency:
        if v in seen:
            continue
        stack = [v]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(adjacency[x] - seen)
        components += 1

    boundary = sum(1 for n in edges.values() if n == 1)
    share = boundary / len(edges) if edges else 1.0
    return components, share, degenerate, boundary, len(edges)


def winding_disagreement(mesh: ObjMesh) -> float:
    """How often face winding disagrees with the supplied vertex normals."""
    if not mesh.has_normals or not mesh.faces:
        return 0.0
    bad = 0
    for f in mesh.faces:
        p0, p1, p2 = (mesh.positions[i] for i in f)
        u = [p1[i] - p0[i] for i in range(3)]
        v = [p2[i] - p0[i] for i in range(3)]
        n = (
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        )
        vn = mesh.normals[f[0]]
        if sum(n[i] * vn[i] for i in range(3)) < 0:
            bad += 1
    return bad / len(mesh.faces)


# --- the check ---------------------------------------------------------------


def check_mesh(mesh: ObjMesh) -> Verdict:
    """Judge a candidate head on its own, before any target is chosen."""
    v = Verdict()

    if not mesh.positions or not mesh.faces:
        v.add("fail", "geometry", "the mesh has no vertices or no faces")
        return v

    components, share, degenerate, boundary, total_edges = topology(mesh)

    if components <= MAX_COMPONENTS_OK:
        v.add("pass", "one piece", f"{components} connected component(s)")
    elif components <= MAX_COMPONENTS_WARN:
        v.add("warn", "one piece",
              f"{components} components; vanilla heads have at most "
              f"{MAX_COMPONENTS_OK}. Loose fragments float beside the model")
    else:
        v.add("fail", "one piece",
              f"{components} disconnected pieces; vanilla heads have at most "
              f"{MAX_COMPONENTS_OK}. Delete loose geometry and keep the largest island")

    if share <= BOUNDARY_OK:
        v.add("pass", "closed", f"{share:.1%} of edges are open ({boundary}/{total_edges})")
    elif share <= BOUNDARY_WARN:
        v.add("warn", "closed",
              f"{share:.1%} of edges are open; vanilla heads reach {BOUNDARY_OK:.1%}. "
              f"You will see through the mesh where it is unclosed")
    else:
        v.add("fail", "closed",
              f"{share:.1%} of edges are open ({boundary}/{total_edges}); the mesh is "
              f"a shell rather than a solid. Fill holes before using it")

    if degenerate:
        v.add("warn", "degenerate faces",
              f"{degenerate} face(s) have two identical corners and cover no area")

    tris = len(mesh.faces)
    lo, hi = TRIANGLES_TYPICAL
    if lo <= tris <= hi:
        v.add("pass", "density", f"{tris} triangles, in vanilla's {lo}-{hi} range")
    elif tris < lo:
        v.add("warn", "density",
              f"{tris} triangles; vanilla heads use {lo}-{hi}, so this will look "
              f"coarse beside the rest of the model")
    elif tris <= TRIANGLES_WARN:
        v.add("warn", "density",
              f"{tris} triangles, above vanilla's {hi}. Workable - this project has "
              f"shipped {1198} - but it eats the whole-model budget")
    else:
        v.add("fail", "density",
              f"{tris} triangles is far beyond vanilla's {hi} and will not leave room "
              f"under the {MODEL_BUDGET}-triangle whole-model budget. Decimate it")

    if mesh.has_uvs:
        v.add("pass", "texture coordinates", f"{len(mesh.uvs)} UVs, one per vertex")
    else:
        v.add("warn", "texture coordinates",
              "none; the head will render untextured unless it keeps the host's UVs")

    if mesh.has_normals:
        bad = winding_disagreement(mesh)
        if bad <= WINDING_WARN:
            v.add("pass", "winding", f"{bad:.1%} of faces disagree with their normals")
        else:
            v.add("warn", "winding",
                  f"{bad:.1%} of faces are wound against their normals and will look "
                  f"inside-out. Recalculate normals outward")
    else:
        v.add("warn", "normals",
              "none supplied; they will be computed from the faces, which loses any "
              "smoothing the author intended")

    # How much of the surface actually faces out. The engine draws front faces
    # only, so a mesh that folds back on itself renders full of holes - which is
    # what a scanned head did after its individually modelled hair strands were
    # reduced to a KOTOR budget and collapsed into a self-intersecting tangle.
    # Consistent winding cannot fix that: every face can agree with its
    # neighbours while the surface as a whole is knotted.
    from .repair import outward_fraction

    solid = outward_fraction(mesh.positions, mesh.faces)
    if solid >= SOLID_PASS:
        v.add("pass", "solid", f"{solid:.0%} of the surface faces outward")
    elif solid >= SOLID_REJECT:
        v.add("warn", "solid",
              f"only {solid:.0%} of the surface faces outward. Vanilla heads run "
              f"77%-100%, so parts of this will be culled and read as holes")
    else:
        v.add("fail", "solid",
              f"only {solid:.0%} of the surface faces outward, below the worst "
              f"vanilla head (77%). The mesh folds back on itself and will render "
              f"full of holes. Usually a dense source - hair especially - reduced "
              f"too far to hold its shape")

    return v


def check_against_target(mesh: ObjMesh, layout, node) -> Verdict:
    """Judge a candidate against the node it is going into."""
    from kmdlswap import mdx as kmdx
    from kmdlswap.swap import AUTHORABLE

    from . import parts as kparts

    v = Verdict()

    if "saber" in node.flags:
        v.add("fail", "target", f"{node.name!r} is a saber blade and is out of scope")
        return v

    try:
        stride = kmdx.stride_layout(layout, node)
    except ValueError as exc:
        v.add("fail", "target", str(exc))
        return v

    extra = sorted(set(stride.columns) - AUTHORABLE)
    if extra:
        v.add("fail", "target columns",
              f"{node.name!r} needs {', '.join(extra)}, which an OBJ cannot express")
    else:
        v.add("pass", "target columns", "vertex, normal and one UV set - all authorable")

    from .apply import is_head_model

    if node.is_skin and is_head_model(layout):
        v.add("pass", "skinned head",
              f"{node.name!r} is skinned in a head model. Its vertex count is free "
              f"to change - the failure that used to make this a warning was a "
              f"stale pointer in our own writer, fixed and confirmed in game. "
              f"--reshape remains available for keeping the host's "
              f"{node.vertex_count} vertices, weights and UVs")
    elif node.is_skin:
        v.add("warn", "skinned",
              f"{node.name!r} is skinned; weights transfer from the mesh being "
              f"replaced, and a changed vertex count is only lightly tested on bodies")
    else:
        v.add("pass", "unskinned target",
              f"{node.name!r} is not skinned, so the mesh's own topology and UVs "
              f"can be used as they are")

    others = sum(
        n.face_count for n in kparts.mesh_nodes(layout) if n.index != node.index
    )
    total = others + len(mesh.faces)
    if total <= MODEL_BUDGET:
        v.add("pass", "model budget",
              f"{total} triangles for the whole model, under {MODEL_BUDGET}")
    else:
        v.add("warn", "model budget",
              f"{total} triangles for the whole model, over the {MODEL_BUDGET} "
              f"the brief calls practical")
    return v


OVERSIZE_LIMIT = 1.25     # bigger than the node's box on any axis clips the body
UNDERSIZE_LIMIT = 0.60    # smaller than this and the head is lost in the model
DRIFT_TOLERANCE = 0.5     # centre offset, as a fraction of the node's own size


def bounds(points):
    lo = [min(p[i] for p in points) for i in range(3)]
    hi = [max(p[i] for p in points) for i in range(3)]
    return lo, hi


def check_placement(mesh: ObjMesh, layout, node) -> Verdict:
    """Is the mesh anywhere near where the node expects geometry?

    The topology checks say nothing about this, and they should not - a mesh can
    be flawless and still be six times too big, on its side, and floating above
    the neck. That is exactly what a raw export from another tool looks like,
    because nothing outside KOTOR knows what scale or origin a head node uses.
    """
    from kmdlswap import edit as ke

    v = Verdict()
    host = ke.extract(layout, node)
    hlo, hhi = bounds(host.positions)
    mlo, mhi = bounds(mesh.positions)
    hsize = [hhi[i] - hlo[i] for i in range(3)]
    msize = [mhi[i] - mlo[i] for i in range(3)]

    # Too big is a real problem - it clips through the body. Being narrower is
    # not: a uniform scale into a box necessarily under-fills the other axes
    # whenever the proportions differ, and forcing a match would distort the
    # head. So the two directions are judged differently.
    fmt = lambda s: "x".join(f"{c:.3f}" for c in s)  # noqa: E731
    over = max(
        (msize[i] / hsize[i]) if hsize[i] > 1e-9 else 1.0 for i in range(3)
    )
    occupancy = (
        max(msize) / max(hsize) if max(hsize) > 1e-9 else 0.0
    )
    if over > OVERSIZE_LIMIT:
        v.add("fail", "size",
              f"{fmt(msize)} against the node's {fmt(hsize)} - {over:.1f}x too big "
              f"on its worst axis, so it will clip through the body. "
              f"Build with --fit to scale it onto the node")
    elif occupancy < UNDERSIZE_LIMIT:
        v.add("fail", "size",
              f"{fmt(msize)} against the node's {fmt(hsize)} - only "
              f"{occupancy:.0%} of its size, so it would be lost inside the model. "
              f"Build with --fit to scale it onto the node")
    else:
        v.add("pass", "size",
              f"{fmt(msize)} against the node's {fmt(hsize)} "
              f"({occupancy:.0%} of its largest dimension)")

    hmid = [(hhi[i] + hlo[i]) / 2 for i in range(3)]
    mmid = [(mhi[i] + mlo[i]) / 2 for i in range(3)]
    drift = max(abs(mmid[i] - hmid[i]) for i in range(3))
    span = max(max(hsize), 1e-9)
    if drift <= DRIFT_TOLERANCE * span:
        v.add("pass", "placement", f"centre within {drift:.3f} of the node's geometry")
    else:
        v.add("fail", "placement",
              f"centre is {drift:.3f} away from the node's geometry "
              f"({drift / span:.0%} of its size) - it would float. "
              f"Build with --fit to place it")
    return v


def check_texture(path) -> Verdict:
    """Judge a texture that ships with a custom head."""
    from pathlib import Path

    v = Verdict()
    p = Path(path)
    if not p.is_file():
        v.add("fail", "texture", f"{p} does not exist")
        return v

    resref = p.stem
    if len(resref) <= RESREF_MAX:
        v.add("pass", "texture name", f"{resref!r}, within {RESREF_MAX} characters")
    else:
        v.add("fail", "texture name",
              f"{resref!r} is {len(resref)} characters; a KOTOR resref is at most "
              f"{RESREF_MAX}, so the game will never find it")

    try:
        from PIL import Image

        with Image.open(p) as im:
            w, h = im.size
    except Exception as exc:  # noqa: BLE001
        v.add("warn", "texture", f"could not read the image: {exc}")
        return v

    pow2 = lambda n: n and (n & (n - 1)) == 0  # noqa: E731
    if pow2(w) and pow2(h):
        v.add("pass", "texture size", f"{w}x{h}, both powers of two")
    else:
        v.add("fail", "texture size",
              f"{w}x{h}; the engine expects powers of two, such as 256 or 512")

    if max(w, h) <= TEXTURE_MAX:
        v.add("pass", "texture budget", f"{w}x{h}, within {TEXTURE_MAX}")
    else:
        v.add("warn", "texture budget",
              f"{w}x{h} is larger than anything the game ships; heads are 256 and "
              f"HK-47's body is {TEXTURE_MAX}")

    if p.suffix.lower() not in (".tga", ".tpc"):
        v.add("fail", "texture format",
              f"{p.suffix} is not loadable; convert to an uncompressed .tga")
    else:
        v.add("pass", "texture format", f"{p.suffix} loads from Override")
    return v
