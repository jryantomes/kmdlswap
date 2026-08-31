"""Give a model a new name, so a build can be added rather than substituted.

Every build this tool made until now overwrote a vanilla model: dropping
`p_carthh.mdl` into Override replaces Carth for the whole game, and two builds
cannot coexist. A modder adding a character wants a *new* resref that sits
beside the originals - and renaming the file is not enough, because the model
carries its own name inside it and the engine reads that one.

The name lives in three places, and a fourth string looks exactly like it:

* **The model header**, a fixed 32-byte field.
* **Each animation header at +88**, which names the node the animation is
  rooted at. That is usually the model's root node, and so usually the model
  name - but not always. Two of HK-47's seventy-five animations are rooted at
  `InnerTorso` and `talkdummy`, and two of T3-M4's at `Neck`. Those are *node*
  names sharing a field, so they are left alone; rewriting them would re-root
  the animation onto a node that no longer answers to that name.
* **The root node's entry in the name table**, a packed run of NUL-terminated
  strings addressed by an offset array. The only one whose length matters, and
  the reason this goes through the splice engine: a shorter name leaves dead
  bytes and a longer one will not fit, and both are exactly what `Rewriter`
  exists to handle - it moves the tail and shifts every pointer that pointed
  past the edit.
* **The texture**, which is not a name to change at all. Carth's model is
  `P_CarthH` and his texture is `P_CarthH01`, so a search-and-replace across
  the file renames eight texture references and produces an untextured
  character that passes every validator.
"""

from __future__ import annotations

import re
import struct

from ._io import MDL_BASE
from .layout import parse
from .rewrite import Rewriter

NAME_FIELD = 32
MODEL_NAME_AT = 8          # within the model header, which starts at MDL_BASE
ANIM_ROOT_AT = 88          # within an animation header
ANIM_ARRAY_AT = 88         # within the model header
NAME_ARRAY_AT = 184        # within the model header

VALID = re.compile(r"^[A-Za-z0-9_]{1,31}$")
NULL_OFFSETS = (0, 0xFFFFFFFF)


class RenameError(ValueError):
    pass


def check_name(name: str) -> None:
    """A resref the engine and the filesystem will both accept."""
    if not VALID.match(name or ""):
        raise RenameError(
            f"{name!r} is not a usable model name: letters, digits and "
            f"underscores only, 1 to 31 characters"
        )


def rename(mdl: bytes, mdx: bytes, new_name: str) -> tuple[bytes, bytes]:
    """Return the model under a new name. The MDX is untouched."""
    check_name(new_name)
    layout = parse(mdl, mdx)
    old = layout.model_name
    if not old:
        raise RenameError("this model has no name to change")
    if old.lower() == new_name.lower():
        return mdl, mdx

    field = new_name.encode("ascii").ljust(NAME_FIELD, b"\0")
    rw = Rewriter(layout)

    # 1. the model's own name
    rw.set_bytes(MDL_BASE + MODEL_NAME_AT, field)

    # 2. animations rooted at the model's root node, and only those
    for offset in _animation_offsets(mdl):
        at = MDL_BASE + offset + ANIM_ROOT_AT
        if _cstr(mdl, at, NAME_FIELD).lower() == old.lower():
            rw.set_bytes(at, field)

    # 3. the root node's entry in the name table, whose length may change
    span = _name_entry(mdl, old)
    if span is not None:
        start, end = span
        rw.replace_mdl(start, end, new_name.encode("ascii") + b"\0")

    return rw.apply()


def _cstr(data: bytes, at: int, limit: int) -> str:
    raw = data[at:at + limit].split(b"\0")[0]
    return raw.decode("ascii", "replace")


def _animation_offsets(mdl: bytes) -> list[int]:
    array_offset, count = struct.unpack_from("<II", mdl, MDL_BASE + ANIM_ARRAY_AT)
    if not count or array_offset in NULL_OFFSETS:
        return []
    return list(struct.unpack_from("<%dI" % count, mdl, MDL_BASE + array_offset))


def _name_entry(mdl: bytes, old: str) -> tuple[int, int] | None:
    """Where the name table's copy of the model name starts and ends.

    The end includes the terminator, because that is what is being replaced.
    """
    array_offset, count = struct.unpack_from("<II", mdl, MDL_BASE + NAME_ARRAY_AT)
    if not count or array_offset in NULL_OFFSETS:
        return None
    offsets = struct.unpack_from("<%dI" % count, mdl, MDL_BASE + array_offset)
    for offset in offsets:
        pos = MDL_BASE + offset
        end = mdl.index(b"\0", pos)
        if mdl[pos:end].decode("ascii", "replace").lower() == old.lower():
            return pos, end + 1
    return None
