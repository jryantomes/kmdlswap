"""Moving one model's geometry into another model's node.

The rule that makes this safe is the same one the whole tool rests on: the
hierarchy is never touched. The host keeps its own nodes, names, skeleton,
supermodel and animations, and only the *geometry inside* a node is replaced.
A donor is a source of vertices, nothing more - none of its rig comes across.

Two things have to be got right.

**Space.** Donor geometry is stored in the donor node's own frame. Dropping it
straight into the host node would be right only if the two nodes happened to sit
identically. So it is lifted into the donor's model space by the donor's rest
pose, then expressed in the host node's frame by the inverse of the host's. When
the two models share a supermodel those frames nearly agree and the part lands
where it belongs; when they do not, the misfit shows up in the alignment report
rather than silently in-game.

**Weights.** Influences are always inherited from the mesh being *replaced*, by
nearest point on its surface - never from the donor. Bone slots index the host's
own bonemap, so a donor with a different skeleton, a different bone count or
foreign bone names cannot produce a broken binding. This is why a Mixamo-rigged
mesh and a vanilla KOTOR mesh are equally safe as donors.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kmdlswap import edit as ke
from kmdlswap import layout as kl
from kmdlswap import mdx as kmdx
from kmdlswap.obj import ObjMesh
from kmdlswap.swap import AUTHORABLE, SwapReport, build_replacement

from . import parts as kparts
from . import reshape as kreshape
from . import space


@dataclass
class Alignment:
    """How well a donor part fits the space it is going into."""

    host_size: tuple[float, float, float]
    donor_size: tuple[float, float, float]
    offset: tuple[float, float, float]

    @property
    def scale_ratio(self) -> tuple[float, float, float]:
        return tuple(
            (self.donor_size[i] / self.host_size[i]) if self.host_size[i] > 1e-9 else 0.0
            for i in range(3)
        )

    @property
    def worst_ratio(self) -> float:
        """How far off the donor is, as a factor >= 1 in the worst axis."""
        worst = 1.0
        for r in self.scale_ratio:
            if r <= 0:
                continue
            worst = max(worst, r if r >= 1 else 1 / r)
        return worst

    @property
    def drift(self) -> float:
        return max(abs(v) for v in self.offset)

    def notes(self) -> list[str]:
        out = []
        if self.worst_ratio > 1.5:
            out.append(
                f"donor is {self.worst_ratio:.1f}x the host part's size on its worst axis; "
                f"consider --fit"
            )
        span = max(max(self.host_size), 1e-9)
        if self.drift > 0.35 * span:
            out.append(
                f"donor sits {self.drift:.3f} away from where the host part sits "
                f"({self.drift / span:.0%} of the part's own size)"
            )
        return out


@dataclass
class TransplantResult:
    host_node: str
    donor_model: str
    donor_node: str
    alignment: Alignment | None = None
    swap: SwapReport | None = None
    error: str | None = None
    reshaped: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None


def _bounds(points):
    lo = [min(p[i] for p in points) for i in range(3)]
    hi = [max(p[i] for p in points) for i in range(3)]
    return lo, hi


def to_host_space(
    donor_layout: kl.Layout,
    donor_node,
    host_layout: kl.Layout,
    host_node,
    *,
    fit: bool = False,
) -> tuple[ObjMesh, Alignment]:
    """Express a donor node's geometry in the host node's own frame."""
    donor_geo = ke.extract(donor_layout, donor_node)
    host_geo = ke.extract(host_layout, host_node)

    donor_rest = space.rest_pose(donor_layout)[donor_node.index]
    host_rest = space.rest_pose(host_layout)[host_node.index]

    def to_model(rest, v):
        return tuple(
            rest.position[i] + sum(rest.rotation[i][k] * v[k] for k in range(3))
            for i in range(3)
        )

    moved = [host_rest.to_local(to_model(donor_rest, v)) for v in donor_geo.positions]

    host_lo, host_hi = _bounds(host_geo.positions)
    donor_lo, donor_hi = _bounds(moved)
    host_size = tuple(host_hi[i] - host_lo[i] for i in range(3))
    donor_size = tuple(donor_hi[i] - donor_lo[i] for i in range(3))
    host_mid = [(host_hi[i] + host_lo[i]) / 2 for i in range(3)]
    donor_mid = [(donor_hi[i] + donor_lo[i]) / 2 for i in range(3)]
    alignment = Alignment(
        host_size=host_size,
        donor_size=donor_size,
        offset=tuple(donor_mid[i] - host_mid[i] for i in range(3)),
    )

    if fit:
        # Uniform, so the donor is not distorted: match the tightest axis and
        # re-centre on where the host part actually sits.
        factors = [
            host_size[i] / donor_size[i] for i in range(3) if donor_size[i] > 1e-9
        ]
        f = min(factors) if factors else 1.0
        moved = [
            tuple(host_mid[i] + (v[i] - donor_mid[i]) * f for i in range(3)) for v in moved
        ]

    mesh = ObjMesh(name=donor_node.name)
    mesh.positions = [tuple(v) for v in moved]
    mesh.faces = [f.vertices for f in donor_geo.faces]
    mesh.materials = [f.material for f in donor_geo.faces]
    if "uv1" in donor_geo.columns:
        mesh.uvs = [tuple(t) for t in donor_geo.columns["uv1"]]
    if "normal" in donor_geo.columns:
        # Normals are directions: rotate, never translate.
        def rotate(rest, v, transpose=False):
            if transpose:
                return tuple(
                    sum(rest.rotation[k][i] * v[k] for k in range(3)) for i in range(3)
                )
            return tuple(
                sum(rest.rotation[i][k] * v[k] for k in range(3)) for i in range(3)
            )

        mesh.normals = [
            rotate(host_rest, rotate(donor_rest, n), transpose=True)
            for n in donor_geo.columns["normal"]
        ]
    return mesh, alignment


def would_break_facial_animation(host_layout, host_node, donor_node) -> bool:
    """Would this pairing change the vertex count of a *skinned* mesh in a head
    model?

    Established by bisection in-game (reports/HEAD_ANIMATION_FINDINGS.md).
    Growing `Head` by three unreferenced vertices breaks facial animation; so
    does growing `tongue`, a different skinned mesh that the facial bones do not
    deform and that is not even the last block in the MDX. Growing `hair`, which
    is *unskinned*, does not.

    So the discriminator is skinning, not which mesh or where it sits. Any
    skinned mesh in a head model is covered.
    """
    from .apply import is_head_model

    return (
        host_node.is_skin
        and is_head_model(host_layout)
        and donor_node.vertex_count != host_node.vertex_count
    )


def resize_risk(host_layout, host_node, donor_node) -> str | None:
    """A caution for resizing a skinned mesh outside a head model.

    Only one body case has ever been checked in-game - HK-47's TorsoHoses went
    from 124 vertices to 24 and still moved with his torso - and that test only
    confirmed gross motion, not fine deformation. Given that every skinned resize
    tried in a head model broke something, one weak positive is not enough to
    call body meshes safe, but it is also not enough to refuse them.
    """
    from .apply import is_head_model

    if (
        host_node.is_skin
        and not is_head_model(host_layout)
        and donor_node.vertex_count != host_node.vertex_count
    ):
        return (
            f"{host_node.name!r} is skinned and its vertex count changes "
            f"({host_node.vertex_count} -> {donor_node.vertex_count}). In head models "
            f"that breaks facial animation; body meshes have only been checked once, "
            f"and only for gross motion. Use --reshape if the result looks wrong."
        )
    return None


def check_pair(host_layout, host_node, donor_layout, donor_node) -> str | None:
    """Why this pairing cannot be done, or None."""
    for label, layout, node in (
        ("host", host_layout, host_node),
        ("donor", donor_layout, donor_node),
    ):
        if "saber" in node.flags:
            return f"{label} {node.name!r} is a saber blade"
        if not node.vertex_count:
            return f"{label} {node.name!r} has no vertices"
        try:
            stride = kmdx.stride_layout(layout, node)
        except ValueError as exc:
            return f"{label} {node.name!r}: {exc}"
        extra = sorted(set(stride.columns) - AUTHORABLE)
        if extra:
            return f"{label} {node.name!r} carries {', '.join(extra)}"
    return None


def transplant_node(
    host_mdl: bytes,
    host_mdx: bytes,
    donor_layout: kl.Layout,
    donor_name: str,
    host_node_name: str,
    donor_node_name: str,
    *,
    fit: bool = False,
    max_influences: int = 4,
    reshape: bool = False,
    with_texture: bool = False,
) -> tuple[bytes, bytes, TransplantResult]:
    """Replace one host node's geometry with a donor node's.

    With ``reshape=True`` the host's own vertices, faces and weights are kept and
    only *moved* onto the donor's surface. That leaves the vertex count alone,
    which is required for a skinned head: changing it breaks facial animation
    in-game (see reports/HEAD_ANIMATION_FINDINGS.md).
    """
    host_layout = kl.parse(host_mdl, host_mdx)
    result = TransplantResult(
        host_node=host_node_name, donor_model=donor_name, donor_node=donor_node_name
    )
    try:
        host_node = host_layout.node_by_name(host_node_name)
        donor_node = donor_layout.node_by_name(donor_node_name)
    except KeyError as exc:
        result.error = str(exc)
        return host_mdl, host_mdx, result

    problem = check_pair(host_layout, host_node, donor_layout, donor_node)
    if problem:
        result.error = problem
        return host_mdl, host_mdx, result

    if not reshape and would_break_facial_animation(host_layout, host_node, donor_node):
        result.error = (
            f"{host_node.name!r} is a skinned mesh in a head model and the donor has "
            f"{donor_node.vertex_count} vertices rather than {host_node.vertex_count}. "
            f"Changing a head's vertex count stops the mouth and eyebrows moving "
            f"in-game. Use --reshape to keep the host's topology and move its "
            f"vertices onto the donor's surface instead."
        )
        return host_mdl, host_mdx, result

    try:
        mesh, alignment = to_host_space(
            donor_layout, donor_node, host_layout, host_node, fit=fit
        )
        result.alignment = alignment
        result.warnings.extend(alignment.notes())
        if not reshape:
            risk = resize_risk(host_layout, host_node, donor_node)
            if risk:
                result.warnings.append(risk)

        host_influences = None
        new_texture = None
        if reshape:
            host_geo = ke.extract(host_layout, host_node)
            host_influences = host_geo.influences or None
            donor_uvs = mesh.uvs if (with_texture and mesh.has_uvs) else None
            snapped = kreshape.snap_to_surface(
                host_geo.positions, mesh.positions, mesh.faces, target_uvs=donor_uvs
            )
            moved, sampled_uvs = snapped if donor_uvs else (snapped, None)
            donor_mesh = mesh
            mesh = ObjMesh(name=host_node.name)
            mesh.positions = moved
            mesh.faces = [f.vertices for f in host_geo.faces]
            mesh.materials = [f.material for f in host_geo.faces]
            if sampled_uvs is not None:
                # The donor's mapping, sampled where each host vertex landed, so
                # the donor's texture can be used with the host's topology.
                mesh.uvs = sampled_uvs
                new_texture = donor_node.textures[0] or None
            elif "uv1" in host_geo.columns:
                mesh.uvs = [tuple(t) for t in host_geo.columns["uv1"]]
            mesh.normals = kreshape.recompute_vertex_normals(moved, mesh.faces)
            result.reshaped = True
            if new_texture:
                result.warnings.append(
                    f"reshaped onto the donor: kept the host's {len(moved)} vertices, "
                    f"took the donor's UVs and texture {new_texture!r}"
                )
            else:
                result.warnings.append(
                    f"reshaped onto the donor: kept the host's {len(moved)} vertices "
                    f"and its own UVs and texture"
                )
        geo, swap_report = build_replacement(
            host_layout, host_node, mesh, max_influences=max_influences,
            influences=host_influences,
        )
        result.swap = swap_report
        result.warnings.extend(swap_report.warnings)
        new_mdl, new_mdx = ke.replace_geometry(
            host_layout, host_node, geo, texture=new_texture
        )
    except Exception as exc:  # noqa: BLE001
        result.error = f"{type(exc).__name__}: {exc}"
        return host_mdl, host_mdx, result
    return new_mdl, new_mdx, result


def match_nodes(host_layout: kl.Layout, donor_layout: kl.Layout) -> list[tuple[str, str]]:
    """Pair host nodes with donor nodes by name, ignoring case.

    A swap never renames anything, so casing is only a pairing heuristic - the
    same part is `torso` in one model and `Torso` in another.
    """
    donors = {
        n.name.lower(): n.name
        for n in kparts.mesh_nodes(donor_layout)
    }
    pairs = []
    for node in kparts.mesh_nodes(host_layout):
        match = donors.get(node.name.lower())
        if match:
            pairs.append((node.name, match))
    return pairs
