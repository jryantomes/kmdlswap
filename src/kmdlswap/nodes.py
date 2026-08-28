"""Node type flags and fixed subheader sizes for K1 binary MDL.

Sizes cross-checked against PyKotor's ``io_mdl.py`` field-by-field reads. They
are asserted empirically by the coverage validator against the vanilla corpus -
if a size is wrong, spans overlap or leave a gap and the model is refused.
"""

from __future__ import annotations

from typing import Final


class NodeFlag:
    HEADER: Final = 0x0001
    LIGHT: Final = 0x0002
    EMITTER: Final = 0x0004
    CAMERA: Final = 0x0008
    REFERENCE: Final = 0x0010
    MESH: Final = 0x0020
    SKIN: Final = 0x0040
    ANIM: Final = 0x0080
    DANGLY: Final = 0x0100
    AABB: Final = 0x0200
    SABER: Final = 0x0800


_FLAG_NAMES: Final = [
    (NodeFlag.HEADER, "header"),
    (NodeFlag.LIGHT, "light"),
    (NodeFlag.EMITTER, "emitter"),
    (NodeFlag.CAMERA, "camera"),
    (NodeFlag.REFERENCE, "reference"),
    (NodeFlag.MESH, "mesh"),
    (NodeFlag.SKIN, "skin"),
    (NodeFlag.ANIM, "anim"),
    (NodeFlag.DANGLY, "dangly"),
    (NodeFlag.AABB, "aabb"),
    (NodeFlag.SABER, "saber"),
]


def flag_names(type_id: int) -> list[str]:
    return [name for bit, name in _FLAG_NAMES if type_id & bit]


# --- fixed-size structures -------------------------------------------------

FILE_HEADER_SIZE: Final = 12
GEOMETRY_HEADER_SIZE: Final = 80
MODEL_HEADER_SIZE: Final = 196  # geometry header included
ANIM_HEADER_SIZE: Final = 136  # geometry header included
NODE_HEADER_SIZE: Final = 80

# Order in which subheaders follow the node header, when their flag is set.
LIGHT_HEADER_SIZE: Final = 92
EMITTER_HEADER_SIZE: Final = 224
REFERENCE_HEADER_SIZE: Final = 36
TRIMESH_HEADER_SIZE_K1: Final = 332
TRIMESH_HEADER_SIZE_K2: Final = 340
SKIN_HEADER_SIZE: Final = 100
DANGLY_HEADER_SIZE: Final = 28
AABB_HEADER_SIZE: Final = 4
SABER_HEADER_SIZE: Final = 20

FACE_SIZE: Final = 32
CONTROLLER_SIZE: Final = 16
AABB_NODE_SIZE: Final = 40
EVENT_SIZE: Final = 36
