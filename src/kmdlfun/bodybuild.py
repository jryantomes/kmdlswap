"""A Jade Empire body, written into a KOTOR body model.

A head has a route into KOTOR already: it becomes a head pack, and the pack is
spliced into a host. A body could not take that route, because a KOTOR body is
skinned and a head is not. Its geometry is not parented to a bone - it is
weighted across many, four influences to a vertex, and the engine will not skin
one mesh to more than seventeen of them. Jade ships a body as a single mesh
weighted to forty-five.

So the body arrives in pieces. `jade.partition` cuts it where KOTOR cuts its
own - Torso, LArm, RArm, Legs - and each piece replaces the host node that does
that job. The host keeps its skeleton, its bone tables, its animations and its
hooks; what changes is the geometry hanging off them, and the weights, which
are resampled from the host's own surface so that every one of them lands on a
bone the host actually has.

Nothing here writes into the game. The result is bytes, and installing them is
a separate, deliberate act.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import jade
from .library import ModelLibrary

# The bodies worth building onto. All four-node bodies: a three-node host like
# `PMBBM` keeps its legs inside the torso, which works, but it puts a Jade
# figure's legs and trunk under one texture and one bone map for no gain.
HOSTS = ("P_CarthBB",)

# A KOTOR texture reference is a 32-byte field and the resref that fills it is
# 16 characters. Named from the model rather than the folder: the folder is the
# caller's choice and truncating it puts the cut in the wrong place.
RESREF_STEM = 14


@dataclass
class Built:
    """What came out, and what it cost."""

    resref: str = ""
    host: str = ""
    mdl: bytes = b""
    mdx: bytes = b""
    texture: str = ""
    texture_bytes: bytes = b""
    lines: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.mdl and self.mdx)


def limb_for(node_name: str) -> str | None:
    """Which of `jade.partition`'s limbs a host node wants, or None.

    KOTOR is not consistent about the names: `PMBBM` calls them torso, armL and
    armR, `PFBBM` Torso, LArm and RArm, `P_CarthBB` those plus Legs. They are
    consistent about the words in them.
    """
    name = node_name.lower()
    if "torso" in name:
        return jade.TORSO
    if "leg" in name:
        return "Legs"
    if "arm" in name:
        side = name.replace("arm", "")
        if "l" in side:
            return "LArm"
        if "r" in side:
            return "RArm"
    return None


def _merge(parts: list):
    """Every part of one limb, joined into a single mesh for one host node.

    A body can arrive as several Jade meshes - a figure, a chestplate, a vein
    of trim - and each contributes to the same limbs. A host node is one node
    and takes one mesh, so they are joined here rather than fighting over it.
    """
    positions: list = []
    faces: list = []
    uvs: list = []
    normals: list = []
    weight: dict = {}
    for part in parts:
        base = len(positions)
        positions.extend(part.positions)
        faces.extend((a + base, b + base, c + base) for a, b, c in part.faces)
        # UVs and normals are per vertex, so a part missing them would shift
        # every later part's. Pad rather than let that happen.
        uvs.extend(part.uvs if len(part.uvs) == len(part.positions)
                   else [(0.0, 0.0)] * len(part.positions))
        normals.extend(part.normals if len(part.normals) == len(part.positions)
                       else [(0.0, 0.0, 1.0)] * len(part.positions))
        if part.material:
            weight[part.material] = weight.get(part.material, 0) + len(part.faces)
    material = max(weight, key=lambda m: weight[m]) if weight else None
    return positions, faces, uvs, normals, material, weight


def run(entry, *, host: str = HOSTS[0], install=None, jade_install=None,
        pose: float | None = jade.KOTOR_ARM_REST) -> Built:
    """Build one Jade body onto one KOTOR host. Returns the bytes, not a file."""
    from kmdlswap import edit as kedit
    from kmdlswap import layout as kl
    from kmdlswap import obj as kobj
    from kmdlswap import swap as kswap

    out = Built(resref=entry.resref, host=host)
    lib = ModelLibrary(install)
    if not lib.has(host):
        raise jade.JadeError(f"the install has no {host} to build onto")
    mdl, mdx = lib.read(host)

    model = jade._parse(*jade.read(entry))
    parts = jade.partition(model, pose=pose)
    by_limb: dict = {}
    for part in parts:
        by_limb.setdefault(part.limb, []).append(part)

    # Jade builds 49 of its 112 people with a head on the body, sometimes with
    # a mask over that. KOTOR hangs the head on `headhook` as its own model, so
    # a body that brings its own wears two - and the one you see is the wrong
    # one, sitting a little higher and a little wider than the real face.
    head = by_limb.pop(jade.HEAD_LIMB, None)
    if head:
        out.lines.append(
            f"left the Jade head behind ({sum(len(p.faces) for p in head)} "
            f"triangles) - KOTOR hangs its own on headhook")

    # The texture is found before the splice, because each node's reference to
    # it is written as part of that node's rewrite.
    _dress(out, entry, parts, jade_install)

    layout = kl.parse(mdl, mdx)
    wanted = [n.name for n in layout.nodes
              if n.in_animation is None and n.is_skin and limb_for(n.name)]
    if not wanted:
        raise jade.JadeError(f"{host} has no skinned body meshes to replace")

    spare = sorted(set(by_limb) - {limb_for(n) for n in wanted})
    if spare:
        out.warnings.append(
            f"{host} has no node for " + ", ".join(spare)
            + " - that geometry is not carried over")

    for node_name in wanted:
        limb = limb_for(node_name)
        group = by_limb.get(limb)
        if not group:
            out.warnings.append(f"nothing to put in {node_name}")
            continue
        positions, faces, uvs, normals, material, spread = _merge(group)
        if len(spread) > 1:
            kept = sum(n for m, n in spread.items() if m == material)
            total = sum(spread.values())
            out.warnings.append(
                f"{node_name} draws {len(spread)} Jade textures but a KOTOR "
                f"node wears one: {total - kept} of {total} triangles will "
                f"take the wrong one")

        layout = kl.parse(mdl, mdx)
        node = layout.node_by_name(node_name)
        mesh = kobj.ObjMesh(name=node_name, positions=positions, faces=faces,
                            uvs=uvs, normals=normals)
        # `facial_rig=False` matters: those two passes look for a brow band and
        # for lips, and on a torso they find something and rebind it.
        geo, report = kswap.build_replacement(layout, node, mesh,
                                              facial_rig=False)
        mdl, mdx = kedit.replace_geometry(layout, node, geo,
                                          texture=out.texture or None)
        out.lines.append(
            f"{node_name}: {report.old_vertices} vertices and "
            f"{report.old_triangles} triangles became {report.new_vertices} "
            f"and {report.new_triangles}, on {report.bones_used} bones")

    out.mdl, out.mdx = mdl, mdx
    return out


def _dress(out: Built, entry, parts: list, jade_install) -> None:
    """Find the body's texture and give it a name KOTOR can hold."""
    root = jade_install or jade._install_of(entry)
    if root is None:
        out.warnings.append("no Jade install to read the texture from - "
                            "it will wear the host's")
        return
    seen: dict = {}
    for part in parts:
        if part.material and part.limb != jade.HEAD_LIMB:
            seen[part.material] = seen.get(part.material, 0) + len(part.faces)
    for material in sorted(seen, key=lambda m: -seen[m]):
        name = jade.texture_name(root, material)
        data = jade.texture(root, name) if name else None
        if data:
            stem = (entry.resref.strip("_").lower() or "jadebody")
            out.texture = stem[:RESREF_STEM] + "01"
            out.texture_bytes = data
            out.lines.append(f"texture {name} decoded from .txb")
            return
    out.warnings.append("no texture found - it will wear the host's")


def write(out: Built, folder) -> list:
    """Put a build on disk. Never inside the game - that is a separate act."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    written = [folder / f"{out.host}.mdl", folder / f"{out.host}.mdx"]
    written[0].write_bytes(out.mdl)
    written[1].write_bytes(out.mdx)
    if out.texture_bytes:
        skin = folder / f"{out.texture}.tga"
        skin.write_bytes(out.texture_bytes)
        written.append(skin)
    return written
