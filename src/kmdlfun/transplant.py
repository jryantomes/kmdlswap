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


# Share of a donor's vertices allowed to sit further than a tenth of the host
# part's diagonal from its surface. Measured over the 61 vanilla heads fitted
# onto Carth: median 0%, 75th percentile 1.2%, 90th 4.8%, worst 11.5%
# (n_yoda). So it is a warning and never a refusal - vanilla itself reaches
# these numbers, and n_rodian at 10.9% is a donor this project has used.
FAR_FRACTION = 0.10
FAR_WARN = 0.05


def transfer_strain(host_geo, donor_positions) -> tuple[float, float]:
    """How far the donor sits from the host surface: (mean, fraction far).

    Weight transfer gives every new vertex the weights of the closest point on
    the *host's* surface. Where the two shapes agree that is exactly right.
    Where they do not - a Quarren's head lobes have no counterpart anywhere on
    a human head - the vertex inherits from whatever happened to be nearest and
    then swings with a bone that has nothing to do with it. In game that reads
    as a head that animates but is smashed about.

    Both numbers are relative to the host part's diagonal, so they mean the
    same thing whatever is being replaced.
    """
    import numpy as np

    from kmdlswap.weights import _closest_points_on_triangles

    H = np.asarray([p[:3] for p in host_geo.positions], dtype=np.float64)
    tri = np.asarray([f.vertices for f in host_geo.faces], dtype=np.int64)
    if not len(tri) or not len(donor_positions):
        return 0.0, 0.0
    extent = float(np.linalg.norm(H.max(axis=0) - H.min(axis=0))) or 1.0
    P = np.asarray([p[:3] for p in donor_positions], dtype=np.float64)
    d2, _ = _closest_points_on_triangles(P, H[tri[:, 0]], H[tri[:, 1]], H[tri[:, 2]])
    dist = np.sqrt(d2.min(axis=1)) / extent
    return float(dist.mean()), float((dist > FAR_FRACTION).mean())


def remap_influences(donor_layout, donor_node, host_layout, host_node, influences):
    """Re-express the donor's own skin weights in the host's bone slots.

    Far better than re-deriving them, when it is available. Transfer asks "what
    is the nearest point on the *host's* surface", which is meaningless wherever
    the two shapes disagree - a Quarren's head lobes have no counterpart on a
    human head, so they inherit from whatever happened to be closest and then
    swing with a bone that has nothing to do with them. The donor was rigged for
    its own shape by someone who could see it; those weights are simply right.

    Bone *slots* are per-model indices into that model's qbones/tbones, so they
    cannot be copied across. Bone *names* can: KOTOR 1 and KOTOR 2 share the
    same facial rig, and all 16 of Carth's bones appear by name on a KOTOR 2
    Quarren.

    Returns (influences, report) and never invents anything - if a donor bone
    has no counterpart in the host, its weight is dropped and the vertex
    renormalised, and the report says which.
    """
    donor_slot_to_name = {
        slot: donor_layout.nodes[i].name
        for i, slot in enumerate(donor_node.bonemap)
        if slot >= 0
    }
    host_name_to_slot = {
        host_layout.nodes[i].name.lower(): slot
        for i, slot in enumerate(host_node.bonemap)
        if slot >= 0
    }

    missing: set[str] = set()
    out: list[list[kmdx.Influence]] = []
    for infl in influences:
        pool: dict[int, float] = {}
        for one in infl:
            name = donor_slot_to_name.get(one.bone_slot)
            slot = host_name_to_slot.get((name or "").lower())
            if slot is None:
                missing.add(name or f"slot{one.bone_slot}")
                continue
            pool[slot] = pool.get(slot, 0.0) + one.weight
        total = sum(pool.values())
        if total <= 0.0:
            out.append([])
            continue
        out.append([kmdx.Influence(s, w / total) for s, w in
                    sorted(pool.items(), key=lambda kv: (-kv[1], kv[0]))])
    return out, sorted(missing)


def rigs_match(donor_layout, donor_node, host_layout, host_node) -> bool:
    """Does every bone the donor's weights use exist by name on the host?"""
    donor_names = {
        donor_layout.nodes[i].name.lower()
        for i, slot in enumerate(donor_node.bonemap) if slot >= 0
    }
    host_names = {
        host_layout.nodes[i].name.lower()
        for i, slot in enumerate(host_node.bonemap) if slot >= 0
    }
    return bool(donor_names) and donor_names <= host_names


def anchor_pair(pairs, host_layout):
    """Which pair the alignment and the folding-in should hang off.

    The biggest host part by vertex count, not whichever the node tree happened
    to list first. Carth's `tongue` sorts before his `Head` and has 22 vertices
    to its 565; anchoring there looked for a Quarren's mouth tentacles among the
    tongue's bones, found none, and quietly folded nothing in.
    """
    def size(pair):
        try:
            return host_layout.node_by_name(pair[0]).vertex_count
        except KeyError:
            return 0

    return max(pairs, key=size) if pairs else None


def auto_merge_candidates(donor_layout, donor_node, host_layout, host_node) -> list[str]:
    """Donor parts the host has no node for, that its skeleton can still drive.

    Naming `tent01` through `tent04` on the command line requires knowing that a
    Quarren's mouth is four separate meshes, which is exactly the kind of thing
    a tool should work out rather than ask. The rule is mechanical:

    * the part is actually drawn - skeleton stubs and hidden meshes are not
      geometry anyone wants;
    * no host node shares its name, so a normal pairing would not carry it;
    * it hangs from a bone the host also has, which is what makes it safe to
      merge and what keeps a body part out of a head swap.

    On `n_quarren` that selects exactly the four tentacles: the torso, arms and
    cape are drawn and unmatched too, but they hang from body bones a head model
    has no equivalent of, so they are left where they are.
    """
    host_names = {n.name.lower() for n in kparts.mesh_nodes(host_layout,
                                                            visible_only=False)}
    host_bones = {
        host_layout.nodes[i].name.lower()
        for i, slot in enumerate(host_node.bonemap) if slot >= 0
    }

    out = []
    for node in kparts.mesh_nodes(donor_layout):
        if node.index == donor_node.index or node.name.lower() in host_names:
            continue
        parent = (donor_layout.nodes[node.parent].name.lower()
                  if node.parent is not None else "")
        if parent in host_bones:
            out.append(node.name)
    # Sorted, so the same donor always produces the same bytes. The node tree's
    # own order is arbitrary and would silently change vertex numbering.
    return sorted(out)


def merge_into(donor_layout, donor_node, extra_names, host_layout, host_node):
    """Fold extra donor nodes into one mesh, each bound to the bone it hung from.

    Some parts of a face are separate nodes rather than part of the head: a
    Quarren's four mouth tentacles are rigid meshes parented to `f_lmc_g`,
    `f_Llm_g`, `f_rmc_g` and `f_Rlm_g` - the mouth-corner and lower-lip bones -
    so they swing when it talks.

    A host cannot gain nodes, and its spare ones hang off the wrong bone: all of
    Carth's facial meshes are parented to `head_g`, so a tentacle carried in his
    `hair` node follows his whole head instead of his mouth. That is not a
    placement problem and no amount of aligning fixes it.

    The way through is to stop treating them as separate parts. Their geometry
    is brought into the head's own space and appended to it, and every appended
    vertex is weighted **100% to the bone its node was parented to** - which is
    exactly the motion the rigid parenting gave it. One skinned mesh, the same
    deformation, and nothing added to the hierarchy.

    Returns (positions, faces, uvs, influences, report).
    """
    import numpy as np

    from . import space

    donor_pose = space.rest_pose(donor_layout)
    base_rest = donor_pose[donor_node.index]
    base_R = np.asarray(base_rest.rotation, dtype=np.float64)
    base_T = np.asarray(base_rest.position, dtype=np.float64)

    host_slot = {
        host_layout.nodes[i].name.lower(): slot
        for i, slot in enumerate(host_node.bonemap) if slot >= 0
    }

    geo = ke.extract(donor_layout, donor_node)
    positions = [tuple(p) for p in geo.positions]
    faces = [f.vertices for f in geo.faces]
    uvs = [tuple(u) for u in geo.columns.get("uv1", [])]
    notes: list[str] = []

    # The base mesh's weights have to be remapped as well, not just the parts
    # being folded in. Bone *slots* are per-model indices and the two models
    # order them completely differently - Carth's slot 1 is f_lns_g while the
    # Quarren's is head_g - so passing the donor's numbers straight through
    # drove Carth's nose bone with the Quarren's whole skull. In game the back
    # of the head moved with the mouth.
    influences, absent = remap_influences(
        donor_layout, donor_node, host_layout, host_node, geo.influences
    )
    if absent:
        notes.append(f"the host has no bone named: {', '.join(absent)}")

    for name in extra_names:
        try:
            extra = donor_layout.node_by_name(name)
        except KeyError:
            notes.append(f"{name!r} is not a node on the donor")
            continue
        bone = (donor_layout.nodes[extra.parent].name
                if extra.parent is not None else "")
        slot = host_slot.get(bone.lower())
        if slot is None:
            notes.append(
                f"{name} hangs from {bone!r}, which the host has no bone for; skipped"
            )
            continue

        eg = ke.extract(donor_layout, extra)
        rest = donor_pose[extra.index]
        R = np.asarray(rest.rotation, dtype=np.float64)
        T = np.asarray(rest.position, dtype=np.float64)
        # extra node space -> donor model space -> the head node's own space
        world = np.asarray(eg.positions, dtype=np.float64) @ R.T + T
        local = (world - base_T) @ base_R

        offset = len(positions)
        positions.extend(tuple(float(c) for c in v) for v in local)
        faces.extend(tuple(i + offset for i in f.vertices) for f in eg.faces)
        if uvs:
            uvs.extend(tuple(u) for u in eg.columns.get("uv1", [(0.0, 0.0)] * len(local)))
        influences.extend([[kmdx.Influence(slot, 1.0)]] * len(local))
        notes.append(f"merged {name} ({len(local)} verts) bound to {bone}")

    return positions, faces, uvs, influences, notes


def model_alignment(donor_layout, donor_node, host_layout, host_node):
    """The model-space shift that puts a donor part where the host's part sits.

    Worked out once from the anchor pair - the head - and then applied to every
    other part of the same transplant, so their relative positions survive.
    A full-body donor keeps its head near standing height while a head-only host
    keeps its geometry near the origin, and without this the two are about 1.5
    units apart.
    """
    import numpy as np

    from . import space

    def centre(layout, node):
        rest = space.rest_pose(layout)[node.index]
        R = np.asarray(rest.rotation, dtype=np.float64)
        T = np.asarray(rest.position, dtype=np.float64)
        P = np.asarray(ke.extract(layout, node).positions, dtype=np.float64) @ R.T + T
        return (P.min(axis=0) + P.max(axis=0)) / 2.0

    return tuple(centre(host_layout, host_node) - centre(donor_layout, donor_node))


def to_host_space(
    donor_layout: kl.Layout,
    donor_node,
    host_layout: kl.Layout,
    host_node,
    *,
    fit: bool = False,
    scale: float = 1.0,
    place: bool = False,
    model_offset: tuple[float, float, float] | None = None,
    override=None,
) -> tuple[ObjMesh, Alignment]:
    """Express a donor node's geometry in the host node's own frame.

    `override` supplies (positions, faces, uvs) already in the donor node's own
    space - what `merge_into` produces - so a mesh built from several donor
    nodes takes exactly the same route as one read straight off a single node.
    """
    donor_geo = ke.extract(donor_layout, donor_node)
    host_geo = ke.extract(host_layout, host_node)

    donor_rest = space.rest_pose(donor_layout)[donor_node.index]
    host_rest = space.rest_pose(host_layout)[host_node.index]

    def to_model(rest, v):
        return tuple(
            rest.position[i] + sum(rest.rotation[i][k] * v[k] for k in range(3))
            for i in range(3)
        )

    # Donor node space -> donor model space -> host node space. A shared
    # `model_offset` is applied in the middle, in *model* space, because that is
    # the only frame several nodes have in common: each host node has its own
    # local space, so one translation cannot be expressed in all of them.
    #
    # That is what lets a Quarren's four mouth tentacles land in their right
    # places relative to its head, rather than each being centred on whichever
    # unrelated node of Carth's is carrying it.
    shift = model_offset or (0.0, 0.0, 0.0)
    source_positions = override[0] if override else donor_geo.positions
    moved = [
        host_rest.to_local(
            tuple(c + shift[i] for i, c in enumerate(to_model(donor_rest, v)))
        )
        for v in source_positions
    ]

    host_lo, host_hi = _bounds(host_geo.positions)
    donor_lo, donor_hi = _bounds(moved)
    host_size = tuple(host_hi[i] - host_lo[i] for i in range(3))
    donor_size = tuple(donor_hi[i] - donor_lo[i] for i in range(3))
    host_mid = [(host_hi[i] + host_lo[i]) / 2 for i in range(3)]
    donor_mid = [(donor_hi[i] + donor_lo[i]) / 2 for i in range(3)]

    if place and not fit:
        # Move it, do not resize it. Fitting exists because a raw donor often
        # lands nowhere near the part it replaces, but the two jobs are
        # separate: a Quarren's head really is wider than a human's, and
        # shrinking it until the lobes fit inside Carth's box makes a Quarren
        # that is not Quarren-sized. Now that the donor's own weights can come
        # across, an oversized head deforms correctly - which is exactly why
        # bighead mode works.
        moved = [
            tuple(host_mid[i] + (v[i] - donor_mid[i]) * scale for i in range(3))
            for v in moved
        ]

    if fit:
        # Uniform, so the donor is not distorted: match the tightest axis and
        # re-centre on where the host part actually sits.
        # The tightest axis is the safe choice - nothing ends up wider than the
        # part it replaces and clips through the body - but it also means a donor
        # with different proportions comes out smaller than the host on its other
        # two axes. A Bith skull is tall and narrow against a human head, and in
        # game it read as noticeably small. `scale` is the knob for that, because
        # the right answer is a judgement this tool cannot make.
        factors = [
            host_size[i] / donor_size[i] for i in range(3) if donor_size[i] > 1e-9
        ]
        f = (min(factors) if factors else 1.0) * scale
        moved = [
            tuple(host_mid[i] + (v[i] - donor_mid[i]) * f for i in range(3)) for v in moved
        ]

    # Measured after any placing or fitting, so the reported drift is where the
    # part ends up rather than where it started. Reporting the raw offset was
    # actively misleading: a correctly placed merge still showed "drift 1.529".
    final_lo, final_hi = _bounds(moved)
    final_mid = [(final_hi[i] + final_lo[i]) / 2 for i in range(3)]
    alignment = Alignment(
        host_size=host_size,
        donor_size=tuple(final_hi[i] - final_lo[i] for i in range(3)),
        offset=tuple(final_mid[i] - host_mid[i] for i in range(3)),
    )

    mesh = ObjMesh(name=donor_node.name)
    mesh.positions = [tuple(v) for v in moved]
    if override:
        mesh.faces = list(override[1])
        mesh.uvs = list(override[2])
        mesh.materials = [donor_geo.faces[0].material if donor_geo.faces else 1] * len(
            mesh.faces
        )
    else:
        mesh.faces = [f.vertices for f in donor_geo.faces]
        mesh.materials = [f.material for f in donor_geo.faces]
        if "uv1" in donor_geo.columns:
            mesh.uvs = [tuple(t) for t in donor_geo.columns["uv1"]]
    if "normal" in donor_geo.columns and not override:
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
    """Always False. Kept so callers and tests have something to point at.

    This used to refuse any pairing that changed a skinned head mesh's vertex
    count, on the strength of five in-game probes. The rule was wrong. The cause
    was a node pointer at model header +168 that the parser never read and so
    never relocated; grow an array before its target and the engine loads the
    model rigid. Skinning was a coincidence - `hair` happened to sit after that
    target and `Head` and `tongue` before it.

    Fixed in `kmdlswap.layout`, and offset closure now proves the pointer
    resolves, so failing to move it is a build-time error rather than a silent
    in-game one. Confirmed in game 2026-08-30 with the probe that had broken
    every previous time. See reports/SKIN_ROOT_POINTER_FINDINGS.md.
    """
    return False


def resize_risk(host_layout, host_node, donor_node) -> str | None:
    """A caution for resizing a skinned mesh outside a head model.

    The head-model failures that made this look alarming turned out to be a
    stale pointer, now fixed, so the caution is much weaker than it was. It
    stays because the evidence for body meshes is still thin: one in-game case,
    HK-47's TorsoHoses going from 124 vertices to 24, and that only confirmed
    gross motion rather than fine deformation.
    """
    from .apply import is_head_model

    if (
        host_node.is_skin
        and not is_head_model(host_layout)
        and donor_node.vertex_count != host_node.vertex_count
    ):
        return (
            f"{host_node.name!r} is skinned and its vertex count changes "
            f"({host_node.vertex_count} -> {donor_node.vertex_count}). Body meshes "
            f"have only been checked once, "
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
    scale: float = 1.0,
    place: bool = False,
    model_offset: tuple[float, float, float] | None = None,
    merge: list[str] | None = None,
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

    # Extra donor nodes are folded in before anything is moved, so the whole
    # face travels as one mesh and carries the weights that go with it.
    override = None
    merged_influences = None
    if merge:
        positions, faces, uvs, merged_influences, notes = merge_into(
            donor_layout, donor_node, merge, host_layout, host_node
        )
        override = (positions, faces, uvs)
        result.warnings.extend(notes)

    try:
        mesh, alignment = to_host_space(
            donor_layout, donor_node, host_layout, host_node,
            fit=fit, scale=scale, place=place, model_offset=model_offset,
            override=override,
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
        elif with_texture:
            # Not reshaping, so the donor's own geometry arrives with its own
            # UVs already attached and its texture simply applies. This used to
            # be impossible: --with-texture forced a reshape, because a changing
            # vertex count was thought to break facial animation. It does not
            # (reports/SKIN_ROOT_POINTER_FINDINGS.md), so the donor can now be
            # taken whole - its shape, its mapping and its texture together.
            new_texture = donor_node.textures[0] or None
            if new_texture:
                result.warnings.append(
                    f"took the donor's geometry, UVs and texture {new_texture!r} whole"
                )

        if merged_influences is not None and len(merged_influences) == len(mesh.positions):
            # merge_into already expressed these in the host's slots.
            host_influences = merged_influences
            result.warnings.append(
                f"one skinned mesh of {len(mesh.positions)} vertices, "
                f"{len({i.bone_slot for f in host_influences for i in f})} bones"
            )
        elif (not reshape and host_node.is_skin and donor_node.is_skin
                and rigs_match(donor_layout, donor_node, host_layout, host_node)):
            donor_geo = ke.extract(donor_layout, donor_node)
            if len(donor_geo.influences) == len(mesh.positions):
                host_influences, absent = remap_influences(
                    donor_layout, donor_node, host_layout, host_node,
                    donor_geo.influences,
                )
                result.warnings.append(
                    f"kept the donor's own skin weights, remapped into the host's "
                    f"bone slots by name ({len({i.bone_slot for f in host_influences for i in f})} bones)"
                )
                if absent:
                    result.warnings.append(
                        f"the host has no bone named: {', '.join(absent)}"
                    )

        if not reshape and host_node.is_skin and host_influences is None:
            mean, far = transfer_strain(ke.extract(host_layout, host_node),
                                        mesh.positions)
            if far > FAR_WARN:
                result.warnings.append(
                    f"{far:.0%} of the donor's vertices sit more than "
                    f"{FAR_FRACTION:.0%} of the part's size away from the host's "
                    f"surface (mean {mean:.0%}). They will inherit weights from "
                    f"whatever is nearest and can swing with bones that have "
                    f"nothing to do with them. Use --reshape if it looks smashed "
                    f"in game"
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
