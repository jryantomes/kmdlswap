"""Checking and building a custom head pack, for any caller.

This was written inside the CLI, interleaved with `print`, which meant the
desktop app had no way to offer custom heads at all - the whole capability was
reachable only from a terminal. The work is the same either way, so it lives
here and both surfaces render the same lines.

The order of operations is not arbitrary and is the reason this is one function
rather than a handful the caller strings together:

* **crop, then decimate, then repair** - cropping first so a bust's shoulders
  are not spending triangle budget, decimating before repair so winding is
  fixed on the mesh that will actually ship, and repair last because a
  simplifier can reintroduce mixed winding.
* **fit before checking against the target**, since "is this the right size for
  the node" is a question about the fitted mesh, not the raw export.
* **every check runs before anything is written**, so a rejected pack costs
  nothing.

`hide` deserves its own note. A custom head replaces one node, and the host's
own hair, eyes, lids, teeth and tongue were shaped for the face that is now
gone, so they float in the middle of the new one. Hiding them is usually right
and occasionally not - a head authored without eyes wants the host's - so it is
a choice, with "everything else visible in this model" as the default meaning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kmdlswap import obj as kobj


@dataclass
class HeadResult:
    """What happened, in the order it happened."""

    lines: list[str] = field(default_factory=list)
    failures: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    error: str | None = None
    mdl: bytes | None = None
    mdx: bytes | None = None
    texture_path: Path | None = None
    pack = None
    node_name: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None and not self.failures

    @property
    def built(self) -> bool:
        return self.mdl is not None

    @property
    def verdict(self) -> str:
        if self.error:
            return self.error
        if self.failures:
            return (f"REJECTED: {len(self.failures)} blocking problem(s), "
                    f"{len(self.warnings)} warning(s)")
        return f"ACCEPTED with {len(self.warnings)} warning(s)"


def fit_mesh(mesh, pack, layout, node, lines: list[str], *, resize: bool = True):
    """Orient a foreign mesh, put it on the node, and optionally resize it.

    Placing is unconditional: nothing outside KOTOR knows where a head node
    sits, so a mesh always has to be moved onto it or it floats at its own
    origin, a unit and a half from the neck.

    Resizing is not. `fit_to` scales by the *tightest* axis, which keeps the
    head inside the node's box and shrinks it whenever the proportions differ -
    a Jade head onto Carth is fractionally wider, so the width ratio binds and
    costs 9% of its height. A mesh converted from a game whose scale is known
    already arrives the right size, and resizing can only take it away from
    that. A sculpt or a scan arriving at an arbitrary size still needs it.
    """
    from kmdlswap import edit as ke

    from . import headgen

    host = ke.extract(layout, node)
    hlo = [min(p[i] for p in host.positions) for i in range(3)]
    hhi = [max(p[i] for p in host.positions) for i in range(3)]
    size = [hhi[i] - hlo[i] for i in range(3)]
    centre = [(hhi[i] + hlo[i]) / 2 for i in range(3)]

    positions = headgen.orient(mesh.positions, facing=pack.facing, up=pack.up)
    if pack.scale != 1.0:
        size = [s * pack.scale for s in size]
    move = headgen.fit_to if resize else headgen.place_at
    positions = move(positions, size, centre, anchor=pack.anchor)

    before = mesh.positions
    mesh.positions = positions
    mesh.normals = headgen.vertex_normals(positions, mesh.faces) if mesh.normals else []
    b_lo = [min(p[i] for p in before) for i in range(3)]
    b_hi = [max(p[i] for p in before) for i in range(3)]
    a_lo = [min(p[i] for p in positions) for i in range(3)]
    a_hi = [max(p[i] for p in positions) for i in range(3)]

    def fmt(s):
        return "x".join(f"{c:.3f}" for c in s)

    lines.append(f"{'fitted' if resize else 'placed'}: "
                 f"{fmt([b_hi[i] - b_lo[i] for i in range(3)])} -> "
                 f"{fmt([a_hi[i] - a_lo[i] for i in range(3)])}"
                 f"   facing {pack.facing}, up {pack.up}, anchor {pack.anchor}")
    return mesh


def run(
    pack_dir,
    *,
    install: str | None = None,
    host: str | None = None,
    node: str | None = None,
    crop: float | None = None,
    decimate: int | None = None,
    repair: bool = False,
    fit: bool = False,
    reshape: bool = False,
    hide: list[str] | None = None,
    build: bool = False,
) -> HeadResult:
    """Check a head pack, and build it into a host model when asked.

    Returns everything the caller needs to report, rather than printing: the
    CLI and the desktop app both want the same lines in the same order.
    """
    from . import headpack, headspec

    r = HeadResult()

    pack = headpack.load(pack_dir)
    r.pack = pack
    r.lines.append(f"{pack.name}   ({pack.root})")
    for problem in pack.problems:
        r.lines.append(f"[FAIL] pack: {problem}")
    if pack.mesh_path is None:
        r.error = "the pack has no mesh"
        return r
    r.lines.append(f"mesh    {pack.mesh_path.name}")
    r.lines.append("texture " + (pack.texture_path.name if pack.texture_path
                                 else "(none - keeps the host texture)"))

    try:
        mesh = kobj.read_obj(pack.mesh_path)
    except kobj.ObjError as exc:
        r.error = f"mesh: {exc}"
        return r

    if crop:
        from . import repair as krepair

        axis = 1 if pack.up == "y" else 2
        mesh, cut = krepair.crop_below(mesh, crop, axis=axis)
        r.lines.append(f"cropped: {cut} face(s) below {crop:.0%} of the height removed"
                       if cut else "cropped: nothing was below the cut")

    if decimate:
        from . import decimate as kdecimate

        result = kdecimate.simplify(mesh, decimate)
        if result.after < result.before:
            mesh = result.mesh
            r.lines.append(f"decimated: {result.summary()}")
        else:
            r.lines.append(f"decimate: already {result.before} triangles, left alone")

    if repair:
        from . import repair as krepair

        mesh, flipped = krepair.unify_winding(mesh)
        r.lines.append(f"winding: {flipped} face(s) rewound to agree with their "
                       f"neighbours" if flipped else "winding: already consistent")
        r.lines.append(krepair.facing_report(mesh))

    verdict = headspec.check_mesh(mesh)
    r.lines.extend(verdict.lines())

    if pack.texture_path:
        tex = headspec.check_texture(pack.texture_path)
        r.lines.extend(tex.lines())
        verdict.findings.extend(tex.findings)

    layout = target = None
    if install and host:
        from kmdlswap import layout as kl

        from .library import ModelLibrary

        lib = ModelLibrary(install)
        if not lib.has(host):
            r.error = f"no model {host!r} in that install"
            return r
        layout = kl.parse(*lib.read(host))
        wanted = node or pack.target
        try:
            target = layout.node_by_name(wanted)
        except KeyError as exc:
            r.error = str(exc)
            return r
        r.node_name = target.name

        # Always placed; `fit` now decides only whether it is also resized.
        mesh = fit_mesh(mesh, pack, layout, target, r.lines, resize=fit)

        against = headspec.check_against_target(mesh, layout, target)
        r.lines.extend(against.lines())
        verdict.findings.extend(against.findings)

        placement = headspec.check_placement(mesh, layout, target)
        r.lines.extend(placement.lines())
        verdict.findings.extend(placement.findings)

    r.failures = list(verdict.failures)
    r.warnings = list(verdict.warnings)
    if r.failures:
        if not decimate and any(f.check == "density" for f in r.failures):
            r.lines.append("Too dense is the one failure the tool can fix itself: "
                           "turn on decimate")
        return r

    if not build:
        return r
    if layout is None or target is None:
        r.error = "building needs an install and a host model"
        return r

    r.mdl, r.mdx = _write_into(layout, target, mesh, pack, reshape, hide, r)
    r.texture_path = pack.texture_path
    return r


def _write_into(layout, node, mesh, pack, reshape, hide, r: HeadResult):
    """Put the mesh into the node and hand back the new file bytes."""
    from kmdlswap import edit as ke
    from kmdlswap import layout as kl
    from kmdlswap import validate as kv
    from kmdlswap.swap import build_replacement

    from . import reshape as kreshape

    host_geo = ke.extract(layout, node)

    if reshape:
        # Opt-in now. This used to be forced for every skinned head, because a
        # changing vertex count appeared to break facial animation; that was a
        # stale pointer in our own writer, since fixed and confirmed in game
        # (reports/SKIN_ROOT_POINTER_FINDINGS.md). It survives because keeping
        # the host's UVs and weights is sometimes what you actually want.
        moved = kreshape.snap_to_surface(host_geo.positions, mesh.positions, mesh.faces)
        shaped = kobj.ObjMesh(name=node.name)
        shaped.positions = moved
        shaped.faces = [f.vertices for f in host_geo.faces]
        shaped.materials = [f.material for f in host_geo.faces]
        if "uv1" in host_geo.columns:
            shaped.uvs = [tuple(u) for u in host_geo.columns["uv1"]]
        shaped.normals = kreshape.recompute_vertex_normals(moved, shaped.faces)
        geo, report = build_replacement(
            layout, node, shaped, influences=host_geo.influences or None
        )
        r.lines.append("reshaped onto the host's topology")
    else:
        geo, report = build_replacement(layout, node, mesh)
        if node.is_skin:
            r.lines.append(f"weights transferred from the host's "
                           f"{len(host_geo.positions)} vertices onto the pack's "
                           f"{mesh.vertex_count}")

    mdl, mdx = ke.replace_geometry(layout, node, geo, texture=pack.texture_resref)

    if hide is not None:
        from . import parts as kparts
        from . import visibility as kvis

        after = kl.parse(mdl, mdx)
        wanted = list(hide) if hide else [
            # Everything visible except the node just replaced. These are shaped
            # for the face that is gone, so they float.
            n.name for n in kparts.mesh_nodes(after)
            if n.name.lower() != node.name.lower()
        ]
        mdl, hidden = kvis.hide_nodes(after, mdl, wanted)
        if hidden:
            r.lines.append(f"hidden (host parts that no longer fit): "
                           f"{', '.join(hidden)}")

    if not kv.check(kl.parse(mdl, mdx)).ok:
        r.error = "result failed validation; nothing written"
        return None, None

    r.lines.extend(report.lines())
    return mdl, mdx


def write(result: HeadResult, out_dir, host: str) -> list[Path]:
    """Write a built head into a folder. Never touches the game install."""
    import shutil

    if not result.built:
        return []
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = [out / f"{host}.mdl", out / f"{host}.mdx"]
    written[0].write_bytes(result.mdl)
    written[1].write_bytes(result.mdx)
    if result.texture_path:
        shutil.copy2(result.texture_path, out / result.texture_path.name)
        written.append(out / result.texture_path.name)
    return written
