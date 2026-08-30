"""Showing and hiding a mesh node, without touching the hierarchy.

Byte 313 of the trimesh subheader decides whether the engine draws a mesh.
Vanilla relies on it heavily - 18,058 of the 76,767 mesh nodes have it clear,
which is how a human body carries forty-odd invisible `_g` boxes that are really
the skeleton. Corpus-wide the flag is only ever 0 or 1.

That makes it the right way to deal with a node a donor does not have. Carth has
`hair` and Dustil does not; the hair cannot be removed, because removing a node
would mean rewriting the hierarchy, which this project never does. But it can be
told not to draw, which is what the game itself does to meshes it does not want
on screen.

A one-byte patch: nothing moves, no offset needs fixing, and the vertex count is
untouched - which matters, since changing a head's vertex count breaks facial
animation (reports/HEAD_ANIMATION_FINDINGS.md).
"""

from __future__ import annotations

import struct

from kmdlswap.layout import Layout, NodeInfo

from .parts import RENDER_FLAG_AT


def set_rendered(mdl: bytes, node: NodeInfo, rendered: bool) -> bytes:
    """Return ``mdl`` with this node's render flag set or cleared."""
    if not node.trimesh_at:
        raise ValueError(f"{node.name!r} has no trimesh header")
    out = bytearray(mdl)
    struct.pack_into("<B", out, node.trimesh_at + RENDER_FLAG_AT, 1 if rendered else 0)
    return bytes(out)


def hide_nodes(layout: Layout, mdl: bytes, names: list[str]) -> tuple[bytes, list[str]]:
    """Stop drawing the named nodes. Returns the new MDL and what was hidden."""
    hidden: list[str] = []
    for node in layout.nodes:
        if node.in_animation is not None or not node.is_mesh:
            continue
        if node.name in names:
            mdl = set_rendered(mdl, node, False)
            hidden.append(node.name)
    return mdl, hidden
