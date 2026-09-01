# SPDX-License-Identifier: GPL-3.0-or-later
"""Jade Empire PC v7 animation-controller definitions.

The IDs in this module are not inferred from the retail corpus.  They were
recovered from the controller keyword dispatch in the shipped JadeEmpire.exe
PC executable.  Jade reuses several numeric IDs in different node-class
parsers, so controller identity is resolved against the corresponding static
hierarchy node type.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import Any, Iterable

# Numeric copies are kept here to avoid a circular import with ``mdl``.
NODE_LIGHT = 0x00000002
NODE_EMITTER = 0x00000004
NODE_MESH = 0x00000020
NODE_DANGLY_BONE = 0x00020000
NODE_CLOTH_EXACT = 0x00004021

CONTROLLER_TICKS_PER_SECOND = 256.0
CONTROLLER_DESCRIPTOR_SIZE = 0x10
CONTROLLER_HEADER_SIZE = 0x24

# Controller-storage tags accepted by Jade's binary controller loader.
DATA_SCALAR_LINEAR = 0x01
DATA_VECTOR3_LINEAR = 0x02
DATA_QUATERNION_PACKED_32 = 0x04
DATA_QUATERNION_PACKED_64 = 0x05
DATA_SCALAR_BEZIER = 0x11
DATA_VECTOR3_BEZIER = 0x12

# Compatibility aliases retained for 5.4-era callers.  Binary tracing showed
# that 0x05 is a higher-precision linear quaternion, not a Bezier row.
DATA_QUATERNION_PACKED_LINEAR = DATA_QUATERNION_PACKED_32
DATA_QUATERNION_PACKED_BEZIER = DATA_QUATERNION_PACKED_64

DATA_TYPE_NAMES = {
    DATA_SCALAR_LINEAR: "scalar_linear",
    DATA_VECTOR3_LINEAR: "vector3_linear",
    DATA_QUATERNION_PACKED_32: "quaternion_packed_32",
    DATA_QUATERNION_PACKED_64: "quaternion_packed_64",
    DATA_SCALAR_BEZIER: "scalar_bezier",
    DATA_VECTOR3_BEZIER: "vector3_bezier",
}

# Raw dwords consumed by one key row.  The 64-bit quaternion encoding consists
# of two packed dwords.  Scalar/vector Bézier rows store value, in-tangent and
# out-tangent groups.
DATA_TYPE_WORDS_PER_ROW = {
    DATA_SCALAR_LINEAR: 1,
    DATA_VECTOR3_LINEAR: 3,
    DATA_QUATERNION_PACKED_32: 1,
    DATA_QUATERNION_PACKED_64: 2,
    DATA_SCALAR_BEZIER: 3,
    DATA_VECTOR3_BEZIER: 9,
}


@dataclass(frozen=True)
class ControllerBinding:
    """Binding from a Jade semantic controller to a Blender curve channel."""

    label: str
    dimension: int
    data_path: str | None = None
    default: float | tuple[float, ...] = 0.0


# Most Jade controller names can reuse KotorBlender's existing controller
# labels and RNA properties.  Jade-only channels are exposed as Object custom
# properties so they are still visible and editable in Blender's Graph Editor.
CONTROLLER_BINDINGS: dict[str, ControllerBinding] = {
    "position": ControllerBinding("position", 3),
    "orientation": ControllerBinding("orientation", 4),
    "scale": ControllerBinding("scale", 1),
    "self_illumination_color": ControllerBinding("selfillumcolor", 3),
    "alpha": ControllerBinding("alpha", 1),
    "texture_w_coordinate": ControllerBinding(
        "jade_texture_w_coordinate", 1, '["jade_texture_w_coordinate"]'
    ),
    "color": ControllerBinding(
        "jade_light_color", 3, '["jade_light_color"]', (1.0, 1.0, 1.0)
    ),
    "radius": ControllerBinding("radius", 1),
    "shadow_radius": ControllerBinding("shadowradius", 1),
    "shadow_color": ControllerBinding(
        "jade_shadow_color", 3, '["jade_shadow_color"]', (0.0, 0.0, 0.0)
    ),
    "vertical_displacement": ControllerBinding("verticaldisplacement", 1),
    "multiplier": ControllerBinding("multiplier", 1),
    "rim_light_color": ControllerBinding(
        "jade_rim_light_color", 3, '["jade_rim_light_color"]', (0.0, 0.0, 0.0)
    ),
    "accuracy_multiplier": ControllerBinding(
        "jade_accuracy_multiplier", 1, '["jade_accuracy_multiplier"]', 1.0
    ),
    "gravity_multiplier": ControllerBinding(
        "jade_gravity_multiplier", 1, '["jade_gravity_multiplier"]', 1.0
    ),
    "friction_multiplier": ControllerBinding(
        "jade_friction_multiplier", 1, '["jade_friction_multiplier"]', 1.0
    ),
    "alpha_start": ControllerBinding("alphastart", 1),
    "alpha_mid": ControllerBinding("alphamid", 1),
    "alpha_end": ControllerBinding("alphaend", 1),
    "size_start": ControllerBinding("sizestart", 1),
    "size_mid": ControllerBinding("sizemid", 1),
    "size_end": ControllerBinding("sizeend", 1),
    "size_start_y": ControllerBinding("sizestart_y", 1),
    "size_mid_y": ControllerBinding("sizemid_y", 1),
    "size_end_y": ControllerBinding("sizeend_y", 1),
    "percent_start": ControllerBinding("percentstart", 1),
    "percent_mid": ControllerBinding("percentmid", 1),
    "percent_end": ControllerBinding("percentend", 1),
    "color_start": ControllerBinding("colorstart", 3),
    "color_mid": ControllerBinding("colormid", 3),
    "color_end": ControllerBinding("colorend", 3),
    "frame_start": ControllerBinding("framestart", 1),
    "frame_end": ControllerBinding("frameend", 1),
    "birthrate": ControllerBinding("birthrate", 1),
    "bounce_coefficient": ControllerBinding("bounce_co", 1),
    "combine_time": ControllerBinding("combinetime", 1),
    "drag": ControllerBinding("drag", 1),
    "fps": ControllerBinding("fps", 1),
    "mass": ControllerBinding("mass", 1),
    "gravity": ControllerBinding("grav", 1),
    "life_expectancy": ControllerBinding("lifeexp", 1),
    "p2p_bezier2": ControllerBinding("p2p_bezier2", 1),
    "p2p_bezier3": ControllerBinding("p2p_bezier3", 1),
    "particle_rotation": ControllerBinding("particlerot", 1),
    "random_velocity": ControllerBinding("randvel", 1),
    "spread": ControllerBinding("spread", 1),
    "threshold": ControllerBinding("threshold", 1),
    "velocity": ControllerBinding("velocity", 1),
    "x_size": ControllerBinding("xsize", 1),
    "y_size": ControllerBinding("ysize", 1),
    "blur_length": ControllerBinding("blurlength", 1),
    "lightning_delay": ControllerBinding("lightningdelay", 1),
    "lightning_radius": ControllerBinding("lightningradius", 1),
    "lightning_scale": ControllerBinding("lightningscale", 1),
    "lightning_subdivision": ControllerBinding("lightningsubdiv", 1),
    "lightning_zigzag": ControllerBinding("lightningzigzag", 1),
    "random_birthrate": ControllerBinding("randombirthrate", 1),
    "target_size": ControllerBinding("targetsize", 1),
    "control_point_count": ControllerBinding("numcontrolpts", 1),
    "control_point_radius": ControllerBinding("controlptradius", 1),
    "control_point_delay": ControllerBinding("controlptdelay", 1),
    "tangent_spread": ControllerBinding("tangentspread", 1),
    "tangent_length": ControllerBinding("tangentlength", 1),
    "detonate": ControllerBinding("detonate", 1),
}


CUSTOM_CONTROLLER_BINDINGS = {
    binding.label: binding
    for binding in CONTROLLER_BINDINGS.values()
    if binding.data_path is not None
}

COMMON_CONTROLLERS = {
    0x008: "position",
    0x014: "orientation",
    0x024: "scale",
}

# CClothNode/CPartDanglyBone parser dispatch.
DANGLY_CONTROLLERS = {
    0x044: "accuracy_multiplier",
    0x048: "gravity_multiplier",
    0x04C: "friction_multiplier",
}

# CPartLight parser dispatch.  These values supersede older public templates.
LIGHT_CONTROLLERS = {
    0x044: "color",
    0x050: "radius",
    0x058: "shadow_radius",
    0x05C: "shadow_color",
    0x06C: "vertical_displacement",
    0x090: "multiplier",
    0x0A4: "rim_light_color",
}

# CPartTriMesh/CPartSkin parser dispatch.
MESH_CONTROLLERS = {
    0x05C: "self_illumination_color",
    0x06C: "alpha",
    0x074: "texture_w_coordinate",
}

# CPartEmitter parser dispatch.  The executable accepts the complete sequence
# through controller 0x11C even though the supplied retail corpus exercises a
# subset of it.
EMITTER_CONTROLLERS = {
    0x048: "alpha_start",
    0x04C: "alpha_mid",
    0x050: "alpha_end",
    0x054: "size_start",
    0x058: "size_mid",
    0x05C: "size_end",
    0x060: "size_start_y",
    0x064: "size_mid_y",
    0x068: "size_end_y",
    0x06C: "percent_start",
    0x070: "percent_mid",
    0x074: "percent_end",
    0x078: "color_start",
    0x084: "color_end",
    0x090: "color_mid",
    0x09C: "frame_start",
    0x0A0: "frame_end",
    0x0A4: "birthrate",
    0x0A8: "bounce_coefficient",
    0x0AC: "combine_time",
    0x0B0: "drag",
    0x0B4: "fps",
    0x0B8: "mass",
    0x0BC: "gravity",
    0x0C0: "life_expectancy",
    0x0C4: "p2p_bezier2",
    0x0C8: "p2p_bezier3",
    0x0CC: "particle_rotation",
    0x0D0: "random_velocity",
    0x0D4: "spread",
    0x0D8: "threshold",
    0x0DC: "velocity",
    0x0E0: "x_size",
    0x0E4: "y_size",
    0x0E8: "blur_length",
    0x0EC: "lightning_delay",
    0x0F0: "lightning_radius",
    0x0F4: "lightning_scale",
    0x0F8: "lightning_subdivision",
    0x0FC: "lightning_zigzag",
    0x100: "random_birthrate",
    0x104: "target_size",
    0x108: "control_point_count",
    0x10C: "control_point_radius",
    0x110: "control_point_delay",
    0x114: "tangent_spread",
    0x118: "tangent_length",
    0x11C: "detonate",
}

# Binary controller descriptors use these auxiliary values for the two base
# transform tracks.  All other traced parser entries pass -1.
EXPECTED_AUXILIARY = {
    0x008: 0x10,
    0x014: 0x1C,
}


def controller_map_for_flags(node_flags: int) -> dict[int, str]:
    """Return all controller IDs accepted for a static-node context."""

    mapping = dict(COMMON_CONTROLLERS)
    flags = int(node_flags)
    if flags & NODE_EMITTER:
        mapping.update(EMITTER_CONTROLLERS)
    elif flags & NODE_LIGHT:
        mapping.update(LIGHT_CONTROLLERS)
    elif flags == NODE_CLOTH_EXACT or flags & NODE_DANGLY_BONE:
        mapping.update(DANGLY_CONTROLLERS)
    elif flags & NODE_MESH:
        mapping.update(MESH_CONTROLLERS)
    return mapping


def controller_name(controller_id: int, node_flags: int) -> str | None:
    return controller_map_for_flags(node_flags).get(int(controller_id))


def controller_context_name(node_flags: int) -> str:
    flags = int(node_flags)
    if flags & NODE_EMITTER:
        return "emitter"
    if flags & NODE_LIGHT:
        return "light"
    if flags == NODE_CLOTH_EXACT:
        return "cloth"
    if flags & NODE_DANGLY_BONE:
        return "dangly_bone"
    if flags & NODE_MESH:
        return "mesh"
    return "base"


def data_type_name(value: int) -> str | None:
    return DATA_TYPE_NAMES.get(int(value))


def words_per_row(data_type: int) -> int | None:
    return DATA_TYPE_WORDS_PER_ROW.get(int(data_type))


def word_to_float(word: int) -> float:
    return struct.unpack("<f", struct.pack("<I", int(word) & 0xFFFFFFFF))[0]


def float_to_word(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", float(value)))[0]


def _finite_float_words(words: Iterable[int]) -> tuple[float, ...]:
    return tuple(word_to_float(word) for word in words)


def _canonical_xyzw(values: Iterable[float]) -> tuple[float, float, float, float]:
    values = tuple(float(value) for value in values)
    if len(values) != 4:
        raise ValueError(f"Quaternion requires four components, got {len(values)}")
    if not all(math.isfinite(value) for value in values):
        return (0.0, 0.0, 0.0, 1.0)
    result = values
    if result[3] < 0.0:
        result = tuple(-value for value in result)
    return result  # type: ignore[return-value]


def decode_packed_quaternion_32(word: int) -> tuple[float, float, float, float]:
    """Decode Jade's traced 11:11:10 quaternion representation as x,y,z,w."""

    value = int(word) & 0xFFFFFFFF
    x = (value & 0x7FF) / 1023.0 - 1.0
    y = ((value >> 11) & 0x7FF) / 1023.0 - 1.0
    z = ((value >> 22) & 0x3FF) / 511.0 - 1.0
    w = math.sqrt(max(0.0, 1.0 - x * x - y * y - z * z))
    return (x, y, z, w)


def encode_packed_quaternion_32(values: Iterable[float]) -> int:
    x, y, z, _w = _canonical_xyzw(values)
    ix = max(0, min(0x7FF, int(round((x + 1.0) * 1023.0))))
    iy = max(0, min(0x7FF, int(round((y + 1.0) * 1023.0))))
    iz = max(0, min(0x3FF, int(round((z + 1.0) * 511.0))))
    return ix | (iy << 11) | (iz << 22)


def decode_packed_quaternion_64(words: Iterable[int]) -> tuple[float, float, float, float]:
    """Decode Jade's high-precision 21:21:22 quaternion representation.

    The controller stream stores the high dword first and the low dword
    second, matching the executable's copy order rather than integer endian
    notation.
    """

    raw = tuple(int(word) & 0xFFFFFFFF for word in words)
    if len(raw) != 2:
        raise ValueError(f"Packed 64-bit quaternion requires two words, got {len(raw)}")
    high, low = raw
    ix = low & 0x1FFFFF
    iy = ((low >> 21) & 0x7FF) | ((high & 0x3FF) << 11)
    iz = (high >> 10) & 0x3FFFFF
    x = ix / 1048576.0 - 1.0
    y = iy / 1048576.0 - 1.0
    z = iz / 2097152.0 - 1.0
    w = math.sqrt(max(0.0, 1.0 - x * x - y * y - z * z))
    return (x, y, z, w)


def encode_packed_quaternion_64(values: Iterable[float]) -> tuple[int, int]:
    x, y, z, _w = _canonical_xyzw(values)
    ix = max(0, min(0x1FFFFF, int(round((x + 1.0) * 1048576.0))))
    iy = max(0, min(0x1FFFFF, int(round((y + 1.0) * 1048576.0))))
    iz = max(0, min(0x3FFFFF, int(round((z + 1.0) * 2097152.0))))
    low = ix | ((iy & 0x7FF) << 21)
    high = (iy >> 11) | (iz << 10)
    return (high & 0xFFFFFFFF, low & 0xFFFFFFFF)


def decode_controller_row(data_type: int, words: Iterable[int]) -> Any:
    """Decode one fixed-width controller row into editable values."""

    raw = tuple(int(word) & 0xFFFFFFFF for word in words)
    data_type = int(data_type)
    if data_type == DATA_SCALAR_LINEAR:
        return word_to_float(raw[0])
    if data_type == DATA_VECTOR3_LINEAR:
        return _finite_float_words(raw[:3])
    if data_type == DATA_QUATERNION_PACKED_32:
        return decode_packed_quaternion_32(raw[0])
    if data_type == DATA_QUATERNION_PACKED_64:
        return decode_packed_quaternion_64(raw[:2])
    if data_type == DATA_SCALAR_BEZIER:
        values = _finite_float_words(raw[:3])
        return {"value": values[0], "in_tangent": values[1], "out_tangent": values[2]}
    if data_type == DATA_VECTOR3_BEZIER:
        values = _finite_float_words(raw[:9])
        return {
            "value": values[0:3],
            "in_tangent": values[3:6],
            "out_tangent": values[6:9],
        }
    raise ValueError(f"Unsupported Jade controller data type 0x{data_type:02X}")


def encode_controller_row(data_type: int, row: Any) -> tuple[int, ...]:
    """Encode one editable controller row using its original storage class."""

    data_type = int(data_type)
    if data_type == DATA_SCALAR_LINEAR:
        values = tuple(row) if isinstance(row, (tuple, list)) else (row,)
        return (float_to_word(values[0]),)
    if data_type == DATA_VECTOR3_LINEAR:
        values = tuple(row)
        if len(values) != 3:
            raise ValueError(f"Vector controller requires 3 values, got {len(values)}")
        return tuple(float_to_word(value) for value in values)
    if data_type == DATA_QUATERNION_PACKED_32:
        return (encode_packed_quaternion_32(row),)
    if data_type == DATA_QUATERNION_PACKED_64:
        return encode_packed_quaternion_64(row)
    if data_type == DATA_SCALAR_BEZIER:
        if isinstance(row, dict):
            values = (row["value"], row["in_tangent"], row["out_tangent"])
        else:
            values = tuple(row)
        if len(values) != 3:
            raise ValueError(f"Scalar Bezier controller requires 3 values, got {len(values)}")
        return tuple(float_to_word(value) for value in values)
    if data_type == DATA_VECTOR3_BEZIER:
        if isinstance(row, dict):
            values = (*row["value"], *row["in_tangent"], *row["out_tangent"])
        else:
            values = tuple(row)
        if len(values) != 9:
            raise ValueError(f"Vector Bezier controller requires 9 values, got {len(values)}")
        return tuple(float_to_word(value) for value in values)
    raise ValueError(f"Unsupported Jade controller data type 0x{data_type:02X}")


def controller_binding(semantic_name: str) -> ControllerBinding | None:
    return CONTROLLER_BINDINGS.get(str(semantic_name))


def controller_blender_label(semantic_name: str) -> str | None:
    binding = controller_binding(semantic_name)
    return binding.label if binding is not None else None


@dataclass
class JadeControllerDescriptor:
    controller_id: int
    auxiliary: int
    value_count: int
    timekey_start: int
    data_start: int
    data_type: int
    tail_bytes: bytes
    semantic_name: str
    context_flags: int
    raw_offset: int
    time_keys_raw: list[int] = field(default_factory=list)
    data_words: list[int] = field(default_factory=list)
    decoded_rows: list[Any] = field(default_factory=list)

    @property
    def context_name(self) -> str:
        return controller_context_name(self.context_flags)

    @property
    def storage_name(self) -> str:
        return DATA_TYPE_NAMES[self.data_type]

    @property
    def time_seconds(self) -> list[float]:
        return [value / CONTROLLER_TICKS_PER_SECOND for value in self.time_keys_raw]

    @property
    def expected_word_count(self) -> int:
        return self.value_count * DATA_TYPE_WORDS_PER_ROW[self.data_type]


@dataclass
class JadeControllerSet:
    header_offset: int
    controller_type: int
    descriptor_offset: int
    descriptor_count: int
    descriptor_capacity: int
    timekey_offset: int
    timekey_count: int
    data_offset: int
    data_count: int
    tail_value: int
    descriptors: list[JadeControllerDescriptor] = field(default_factory=list)
    time_keys_raw: list[int] = field(default_factory=list)
    data_words: list[int] = field(default_factory=list)
    raw_header: bytes = b""

    @property
    def recognized(self) -> bool:
        return all(
            descriptor.semantic_name
            and descriptor.data_type in DATA_TYPE_NAMES
            for descriptor in self.descriptors
        )

    def statistics(self) -> dict[str, int]:
        return {
            "descriptors": len(self.descriptors),
            "time_keys": len(self.time_keys_raw),
            "data_words": len(self.data_words),
        }


def validate_descriptor_auxiliary(descriptor: JadeControllerDescriptor) -> bool:
    expected = EXPECTED_AUXILIARY.get(descriptor.controller_id, -1)
    return descriptor.auxiliary == expected


def finite_decoded_row(row: Any) -> bool:
    """Best-effort finite check for decoded float-valued controller rows."""

    if isinstance(row, (float, int)):
        return not isinstance(row, float) or math.isfinite(row)
    if isinstance(row, tuple):
        return all(finite_decoded_row(value) for value in row)
    if isinstance(row, dict):
        return all(finite_decoded_row(value) for value in row.values())
    return True



def controller_descriptor_roundtrip_metadata(
    descriptor: JadeControllerDescriptor,
    *,
    label: str = "",
    editor_rows: list[list[float]] | None = None,
) -> dict[str, Any]:
    """Return the complete JSON-safe typed state for one Jade descriptor.

    Blender cannot retain Python parser objects across a saved scene.  The
    compact writer therefore stores every semantic descriptor field, the
    original packed key/data streams, and the editor-facing rows.  Allocation
    offsets and shared-array indices are deliberately omitted because every
    export rebuilds those values.  If the rows remain unchanged, the writer can
    reproduce the exact packed representation; edited rows are re-encoded using
    the retained storage type where possible.
    """

    return {
        "controller_id": int(descriptor.controller_id),
        "auxiliary": int(descriptor.auxiliary),
        "value_count": int(descriptor.value_count),
        "data_type": int(descriptor.data_type),
        "tail_bytes": [int(value) & 0xFF for value in bytes(descriptor.tail_bytes[:3])],
        "semantic_name": str(descriptor.semantic_name),
        "label": str(label),
        "context_flags": int(descriptor.context_flags),
        "time_keys_raw": [int(value) & 0xFFFF for value in descriptor.time_keys_raw],
        "data_words": [int(value) & 0xFFFFFFFF for value in descriptor.data_words],
        "editor_rows": [
            [float(value) for value in row]
            for row in list(editor_rows or [])
        ],
    }

def controller_set_metadata(controller_set: JadeControllerSet | None) -> dict[str, Any]:
    """Return a compact JSON-safe description of one serialized controller block.

    The metadata is intended for Blender UI and diagnostics. Raw controller
    words remain owned by the typed animation model and compact writer; copying
    them into object custom properties would be redundant and easy to corrupt
    through Blender's numeric RNA conversions.
    """

    if controller_set is None:
        return {}
    descriptors = []
    for descriptor in controller_set.descriptors:
        times = descriptor.time_seconds
        descriptors.append(
            {
                "controller_id": int(descriptor.controller_id),
                "semantic_name": str(descriptor.semantic_name or "unknown"),
                "context_name": str(descriptor.context_name),
                "storage_name": str(
                    DATA_TYPE_NAMES.get(
                        int(descriptor.data_type),
                        f"unknown_0x{int(descriptor.data_type):02X}",
                    )
                ),
                "data_type": int(descriptor.data_type),
                "auxiliary": int(descriptor.auxiliary),
                "value_count": int(descriptor.value_count),
                "word_count": int(len(descriptor.data_words)),
                "time_start": float(times[0]) if times else None,
                "time_end": float(times[-1]) if times else None,
                "auxiliary_valid": bool(validate_descriptor_auxiliary(descriptor)),
            }
        )
    return {
        "controller_type": int(controller_set.controller_type),
        "descriptor_count": int(len(controller_set.descriptors)),
        "timekey_count": int(len(controller_set.time_keys_raw)),
        "data_word_count": int(len(controller_set.data_words)),
        "tail_value": int(controller_set.tail_value),
        "recognized": bool(controller_set.recognized),
        "descriptors": descriptors,
    }
