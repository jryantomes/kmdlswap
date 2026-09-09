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
    positions = move(positions, size, centre, anchor=pack.anchor,
                     drop=pack.drop)

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
                 f"   facing {pack.facing}, up {pack.up}, anchor {pack.anchor}"
                 + (f", dropped {pack.drop:.0%} of a head" if pack.drop else ""))
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
    # Off. Removing whole faces cannot make a mouth line at this resolution:
    # triangles near the mouth average 0.0067 tall against an aperture of
    # 0.0020, so the slit is a third of a triangle and cutting one leaves a
    # jagged hole three times too big. In game that read as the top lip being
    # cut into triangles with the teeth showing through them. Kept for a mesh
    # dense enough for it to mean something.
    mouth: bool = False,
    mouth_scale: float = 1.0,
    mouth_height: float | None = None,
    fit: bool = False,
    reshape: bool = False,
    hide: list[str] | None = None,
    build: bool = False,
    force: bool = False,
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

        # A head whose lips are separate pieces has no mouth: the face shell is
        # a continuous sheet of skin in front of the lips, the teeth and the
        # tongue, so none of them can ever be seen. Open it. No-op on a head
        # built the way KOTOR builds one.
        if mouth:
            from kmdlswap import aperture as kaperture

            mesh.faces, opened = kaperture.cut(
                mesh.positions, mesh.faces,
                scale=mouth_scale, scale_height=mouth_height,
            )
            r.lines.extend(opened)

        # Part the face along its lip line so the head's own teeth and mouth
        # interior - modelled behind a closed shell - can be seen once the two
        # halves are weighted apart. Nothing is removed, so this is invisible
        # until it moves.
        from kmdlswap import lips as klips
        from kmdlswap import mouthsplit as ksplit

        pieces = klips.find_lips(mesh.positions, [tuple(f)[:3] for f in mesh.faces])
        if pieces is not None:
            # The head's own teeth clear the lip by a hair - 0.0030 against the
            # 0.0085 the host's get - which holds at rest and fails the moment
            # the upper lip lifts, putting a white bar through the lip.
            from kmdlswap import edit as kedit

            from . import mouthparts as kmouth3

            host_geo = kedit.extract(layout, target)
            want = kmouth3.teeth_clearance(host_geo.positions, layout, target)
            if want:
                shell = klips.islands(
                    __import__("numpy").asarray(
                        [q[:3] for q in mesh.positions], dtype=float),
                    [tuple(f)[:3] for f in mesh.faces],
                )[0]
                r.lines.extend(kmouth3.seat_islands(
                    mesh,
                    [("upper teeth", pieces[0]), ("lower teeth", pieces[1])],
                    shell, want,
                ))

            # This head has its own teeth and interior, so the host's are not
            # wanted: two sets of teeth end up in one small space and the
            # host's, being sized for the host, sit furthest forward and show
            # through the lip as a white bar.
            mesh.has_own_mouth = True

            # The replacement's own eyeballs, seated the way its teeth are.
            # Measured on `h_common01_` they cleared the face by -0.0017 at
            # their tightest - through it - against the 0.0153 the host keeps.
            # In game, eyes sitting on the surface rather than behind the
            # eyeline.
            eye_want = kmouth3.eye_clearance(layout, target)
            eyes = kmouth3.find_eyes(mesh.positions, [tuple(f)[:3] for f in mesh.faces])
            if eyes and eye_want:
                r.lines.extend(kmouth3.seat_islands(
                    mesh,
                    [(f"eye {i + 1}", g) for i, g in enumerate(eyes)],
                    shell, eye_want, "the eyeline",
                ))

            upper, lower, parted = ksplit.split(mesh, pieces[0], pieces[1])
            if upper:
                mesh.mouth_split = (upper, lower)
                r.lines.extend(parted)
                # `ksplit.seal_cavity` would bridge the upper lip to the
                # interior and close the hole an open mouth otherwise shows.
                # Not called: the bridge spans the whole opening and draws in
                # front of the teeth and tongue, so the mouth seals but stops
                # having anything in it. Sealing needs a strip that follows the
                # palate rather than a flat span, which is more geometry than
                # this has any business inventing.

        against = headspec.check_against_target(mesh, layout, target)
        r.lines.extend(against.lines())
        verdict.findings.extend(against.findings)

        placement = headspec.check_placement(mesh, layout, target)
        r.lines.extend(placement.lines())
        verdict.findings.extend(placement.findings)

    r.failures = list(verdict.failures)
    r.warnings = list(verdict.warnings)
    if r.failures and force:
        # Build it anyway, and say so. The spec is written for heads - vanilla's
        # 440-796 triangles, its solidity, the size of a head node - and every
        # one of those is the wrong question for a body: a whole Jade body into
        # a torso node reads as 1.5x too big and twice too dense while the
        # whole-model budget it actually has to fit is not close to full.
        #
        # Not a way to ignore the checks in general. It exists so a thing the
        # spec has no opinion about can be put in front of the game, which is
        # the only place some of these questions get answered.
        r.lines.append("forced: built despite " + ", ".join(
            f.check for f in r.failures) + " - the spec's limits are a head's")
        r.failures = []
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

        from . import mouthparts as kmouth

        # Keep the host's mouth interior only when the replacement has none of
        # its own. A head that brought its own teeth does not want a second set.
        keep_mouth = not getattr(mesh, "has_own_mouth", False)

        after = kl.parse(mdl, mdx)
        # Only worth keeping the lids if they can actually be put somewhere.
        blinks = kmouth.can_seat_eyelids(after, node, layout)
        wanted = list(hide) if hide else [
            # Everything visible except the node just replaced. These are shaped
            # for the face that is gone, so they float.
            #
            # The mouth interior is the exception, and hiding it was a real bug:
            # teeth and a tongue sit *inside* the head rather than on its
            # surface, so they still belong there, and without them the mouth
            # opens onto nothing. Reported from the game as lips that move on a
            # mouth that looks taped shut.
            n.name for n in kparts.mesh_nodes(after)
            if n.name.lower() != node.name.lower()
            and not (keep_mouth and kmouth.is_mouth_part(n.name))
            # The host's eyelids are kept. They are the only thing that
            # blinks - a Jade head brings eyeballs but no lids, and the face
            # does not deform to blink either (the host's eye region is 88%
            # head_g), so hiding them hides blinking altogether.
            #
            # Two earlier attempts at keeping them failed, and that was read as
            # proof that a lid built for one face cannot fit another. It was an
            # over-reading. Both seated the lid against the *face*, which
            # corrects depth and nothing else, and both predate the local
            # clearance measurement they would have needed. A lid belongs to an
            # eye, not to a face - see `kmouth.seat_eyelids`.
            and not (blinks and kmouth.is_eyelid(n.name))
        ]
        mdl, hidden = kvis.hide_nodes(after, mdl, wanted)
        if hidden:
            r.lines.append(f"hidden (host parts that no longer fit): "
                           f"{', '.join(hidden)}")

        # Kept, but positioned for the host's face. A shallower replacement puts
        # the host's teeth in front of the new lips.
        if keep_mouth:
            mdl, mdx, seated = kmouth.seat(kl.parse(mdl, mdx), mdl, mdx, node, layout)
            r.lines.extend(seated)

        # The lids are the host's, and sit over the host's eyes. Carried onto
        # the eyes this head brought with it, or they blink inside the skull.
        mdl, mdx, lidded = kmouth.seat_eyelids(kl.parse(mdl, mdx), mdl, mdx, node, layout)
        r.lines.extend(lidded)

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
