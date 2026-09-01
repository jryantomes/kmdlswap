# SPDX-License-Identifier: GPL-3.0-or-later
"""Jade Empire PC v7 specialized-node payloads.

The shipped executable constructs sixteen concrete serialized node classes.
Their tails are *class layouts*, not independent mix-and-match flag payloads.
This distinction matters for classes such as collision lozenges, whose type
word contains the dangling-bone bit but whose payload is a collision shape.

This module contains Blender-independent semantic records, bounds-checked
readers, and fixed-tail encoders.  Out-of-line arrays are allocated by the MDL
writer because their pointers are relative to the model-data base.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from .binary import ArrayDefinition, BinaryBoundsError, BinaryView

MODEL_DATA_OFFSET = 20

# Exact executable-defined node class words.
JADE_NODE_CLASS_FLAGS: dict[str, int] = {
    "node": 0x00000001,
    "light": 0x00000003,
    "emitter": 0x00000005,
    "camera": 0x00000009,
    "reference": 0x00000011,
    "trimesh": 0x00000021,
    "skin": 0x00000061,
    "aabb": 0x00000221,
    "weapon_trail": 0x00000821,
    "gob": 0x00001001,
    "cloth": 0x00004021,
    "collision_sphere": 0x00006001,
    "collision_capsule": 0x0000A001,
    "dangly_bone": 0x00020001,
    "collision_lozenge": 0x00022001,
    "controller_node": 0x00040001,
}
JADE_NODE_CLASS_NAMES = {value: key for key, value in JADE_NODE_CLASS_FLAGS.items()}

# (semantic name, fixed serialized tail size), in on-disk order.
EXACT_NODE_PAYLOAD_LAYOUTS: dict[int, tuple[tuple[str, int], ...]] = {
    0x00000001: (),
    0x00000003: (("light", 0x9C),),
    0x00000005: (("emitter", 0x1AC),),
    0x00000009: (),
    0x00000011: (("reference", 0x70),),
    0x00000021: (("mesh", 0xE4),),
    0x00000061: (("mesh", 0xE4), ("skin", 0xA0)),
    0x00000221: (("mesh", 0xE4), ("aabb", 0x28)),
    0x00000821: (("mesh", 0xE4), ("weapon_trail", 0x20)),
    0x00001001: (("gob", 0x1C),),
    0x00004021: (("mesh", 0xE4), ("cloth", 0x88)),
    0x00006001: (("collision_sphere", 0x18),),
    0x0000A001: (("collision_capsule", 0x24),),
    0x00020001: (("dangly_bone", 0x48),),
    0x00022001: (("collision_lozenge", 0x30),),
    0x00040001: (("controllers", 0x24),),
}

# Fallback for damaged/non-retail files.  The exact table above is always used
# for executable-defined classes; this only prevents tolerant parsing from
# losing recoverable bytes on an unusual combined type word.
_FALLBACK_COMPONENTS: tuple[tuple[str, int, int], ...] = (
    ("light", 0x00000002, 0x9C),
    ("emitter", 0x00000004, 0x1AC),
    ("reference", 0x00000010, 0x70),
    ("mesh", 0x00000020, 0xE4),
    ("skin", 0x00000040, 0xA0),
    ("aabb", 0x00000200, 0x28),
    ("weapon_trail", 0x00000800, 0x20),
    ("gob", 0x00001000, 0x1C),
    ("dangly_bone", 0x00020000, 0x48),
    ("controllers", 0x00040000, 0x24),
)


def payload_layout_for_flags(flags: int) -> tuple[tuple[str, int], ...]:
    """Return the serialized tail layout for a complete node type word."""
    exact = EXACT_NODE_PAYLOAD_LAYOUTS.get(int(flags))
    if exact is not None:
        return exact
    return tuple((name, size) for name, bit, size in _FALLBACK_COMPONENTS if flags & bit)


def payload_size_for_flags(flags: int) -> int:
    return sum(size for _name, size in payload_layout_for_flags(flags))


def node_class_name(flags: int) -> str:
    return JADE_NODE_CLASS_NAMES.get(int(flags), f"custom_0x{int(flags):08x}")


def node_class_flags(name: str, default: int = 0x00000001) -> int:
    return JADE_NODE_CLASS_FLAGS.get(str(name or "").strip().casefold(), int(default))


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _vec(values: Any, width: int, default: Sequence[float]) -> tuple[float, ...]:
    try:
        source = tuple(values)
    except TypeError:
        source = ()
    return tuple(
        _finite(source[index], default[index]) if index < len(source) else float(default[index])
        for index in range(width)
    )


def _vec2(values: Any) -> tuple[float, float]:
    return _vec(values, 2, (0.0, 0.0))  # type: ignore[return-value]


def _vec3(values: Any) -> tuple[float, float, float]:
    return _vec(values, 3, (0.0, 0.0, 0.0))  # type: ignore[return-value]


def _fixed_ascii(value: Any, size: int) -> bytes:
    data = str(value or "").encode("ascii", errors="replace")
    if size <= 0:
        return b""
    data = data[: size - 1]
    return data + b"\0" * (size - len(data))


def _array_abs(
    definition: ArrayDefinition,
    to_absolute: Callable[[int, str], int],
    context: str,
) -> int:
    if definition.count == 0:
        return 0
    return to_absolute(int(definition.offset), context)


def _bounded_count(definition: ArrayDefinition, context: str, maximum: int = 1_000_000) -> int:
    if definition.count > definition.capacity and definition.capacity:
        raise ValueError(
            f"{context} uses {definition.count} entries but capacity is {definition.capacity}"
        )
    if definition.count > maximum:
        raise ValueError(f"Unreasonable {context} count: {definition.count}")
    return int(definition.count)


def _read_records(
    view: BinaryView,
    definition: ArrayDefinition,
    stride: int,
    to_absolute: Callable[[int, str], int],
    context: str,
) -> tuple[int, int]:
    count = _bounded_count(definition, context)
    if not count:
        return 0, 0
    absolute = _array_abs(definition, to_absolute, context)
    view.check(absolute, count * stride, context)
    return absolute, count


def _read_pointer_strings(
    view: BinaryView,
    definition: ArrayDefinition,
    to_absolute: Callable[[int, str], int],
    context: str,
    max_string: int = 256,
) -> list[str]:
    absolute, count = _read_records(view, definition, 4, to_absolute, context)
    output: list[str] = []
    for index in range(count):
        pointer = view.u32(absolute + index * 4, f"{context} pointer {index}")
        if not pointer:
            output.append("")
            continue
        string_absolute = to_absolute(pointer, f"{context} string {index}")
        output.append(view.c_string(string_absolute, max_string, f"{context} string {index}"))
    return output


def _read_fixed_strings(
    view: BinaryView,
    definition: ArrayDefinition,
    stride: int,
    to_absolute: Callable[[int, str], int],
    context: str,
) -> list[str]:
    absolute, count = _read_records(view, definition, stride, to_absolute, context)
    return [
        view.c_string_fixed(absolute + index * stride, stride, f"{context} {index}")
        for index in range(count)
    ]


@dataclass
class JadeReferencePayload:
    model: str = ""
    reattachable: bool = False
    start_animation: str = ""
    random_speed: float = 0.0
    random_start_time: float = 0.0
    reference_scale: float = 1.0
    lightmap_prefix: str = ""


@dataclass
class JadeWeaponTrailPayload:
    positions: list[tuple[float, float, float]] = field(default_factory=list)
    uvs: list[tuple[float, float]] = field(default_factory=list)
    normals: list[tuple[float, float, float]] = field(default_factory=list)
    flags: int = 0x2
    taper: float = 0.4
    segment_interval: float = 0.007
    segment_life: float = 0.2
    minimum_delta_time: float = 0.01

    @property
    def additive_blend(self) -> bool:
        return bool(self.flags & 0x1)

    @additive_blend.setter
    def additive_blend(self, enabled: bool) -> None:
        self.flags = (self.flags | 0x1) if enabled else (self.flags & ~0x1)

    @property
    def splines(self) -> bool:
        return bool(self.flags & 0x2)

    @splines.setter
    def splines(self, enabled: bool) -> None:
        self.flags = (self.flags | 0x2) if enabled else (self.flags & ~0x2)


@dataclass
class JadeCollisionPayload:
    shape: str = "sphere"
    point_a: tuple[float, float, float] = (0.0, 0.0, 0.0)
    radius: float = 1.0
    cloth_radius: float = 1.0
    collide_with_rooms_only: bool = False
    block_lens_flares: bool = False
    point_b: tuple[float, float, float] | None = None
    point_c: tuple[float, float, float] | None = None
    reserved: bytes = b"\0\0"


@dataclass
class JadeClothConstraint:
    vertex_a: int
    vertex_b: int
    rest_length: float


@dataclass
class JadeClothAttachment:
    vertex: int
    offset: tuple[float, float, float]
    node_name: str


@dataclass
class JadeClothPayload:
    friction: float = 0.03
    gravity: tuple[float, float, float] = (0.0, 0.0, -5.0)
    movable_constraints: list[JadeClothConstraint] = field(default_factory=list)
    attachments: list[JadeClothAttachment] = field(default_factory=list)
    fixed_constraints: list[JadeClothConstraint] = field(default_factory=list)
    collision_volumes: list[str] = field(default_factory=list)
    working_arrays: list[ArrayDefinition] = field(default_factory=list)
    working_array_values: list[list[int]] = field(default_factory=list)
    accuracy: int = 1
    wind_multiplier: float = 0.1
    solver_iterations: int = 14
    topology: list[tuple[int, int, int]] = field(default_factory=list)
    face_vectors: list[tuple[float, float, float]] = field(default_factory=list)
    runtime_block: bytes = b"\0" * 16
    state: int = 1
    state_padding: bytes = b"\0\0\0"
    runtime_value: int = 0


# The 53 floats at serialized offsets 0xC4..0x194.  Names and order are
# executable-traced and match the existing KotorBlender emitter vocabulary.
EMITTER_FLOAT_FIELDS: tuple[str, ...] = (
    "alpha_start", "alpha_mid", "alpha_end",
    "size_start", "size_mid", "size_end",
    "size_start_y", "size_mid_y", "size_end_y",
    "percent_start", "percent_mid", "percent_end",
    "color_start_r", "color_start_g", "color_start_b",
    "color_end_r", "color_end_g", "color_end_b",
    "color_mid_r", "color_mid_g", "color_mid_b",
    "frame_start", "frame_end", "birth_rate", "bounce_coefficient",
    "combine_time", "drag", "fps", "mass", "gravity", "life_expectancy",
    "p2p_bezier2", "p2p_bezier3", "particle_rotation", "random_velocity",
    "spread", "threshold", "velocity", "x_size", "y_size", "blur_length",
    "lightning_delay", "lightning_radius", "lightning_scale",
    "lightning_subdivisions", "lightning_zigzag", "random_birth_rate",
    "target_size", "number_control_points", "control_point_radius",
    "control_point_delay", "tangent_spread", "tangent_length",
)
assert len(EMITTER_FLOAT_FIELDS) == 53

EMITTER_FLAG_FIELDS: tuple[tuple[str, int], ...] = (
    ("p2p", 0),
    ("p2p_bezier", 1),
    ("affected_by_wind", 2),
    ("tinted", 3),
    ("bounce", 4),
    ("random", 5),
    ("inherit", 6),
    ("inherit_velocity", 7),
    ("inherit_local", 8),
    ("splat", 9),
    ("inherit_particle", 10),
    ("depth_texture", 11),
    ("legacy_1000", 12),
    ("distortion", 13),
    ("always_animate", 14),
    ("sort_gob", 15),
    ("sort_particle", 16),
)


@dataclass
class JadeEmitterPayload:
    dead_space: float = 0.0
    blast_radius: float = 0.0
    blast_length: float = 0.0
    number_branches: int = 0
    control_point_smoothing: int = 0
    x_grid: int = 0
    y_grid: int = 0
    spawn_type: int = 0
    update: str = ""
    render: str = ""
    blend: str = ""
    texture: str = ""
    chunk_name: str = ""
    two_sided_texture: bool = False
    loop: bool = False
    render_order: int = 0
    frame_blending: bool = False
    detonate_code: int = -1
    initial_random_rotation: float = 0.0
    values: dict[str, float] = field(default_factory=dict)
    # The executable addresses this slot both as a byte flag and as a raw
    # 32-bit word.  Retail assets use the high three bytes as opaque storage;
    # thirty supplied emitters contain IEEE NaN bit-patterns here.  Keep the
    # complete word so a Blender round trip never canonicalizes those bits.
    detonate_word: int = 0
    batch_positions: list[tuple[float, float, float]] = field(default_factory=list)
    flags: int = 0

    @property
    def detonate(self) -> bool:
        return bool(int(self.detonate_word) & 0xFF)

    @detonate.setter
    def detonate(self, enabled: bool) -> None:
        self.detonate_word = (int(self.detonate_word) & 0xFFFFFF00) | int(bool(enabled))

    @property
    def detonate_padding(self) -> bytes:
        return int(self.detonate_word & 0xFFFFFFFF).to_bytes(4, "little")[1:]

    @detonate_padding.setter
    def detonate_padding(self, value: bytes) -> None:
        padding = bytes(value or b"")[:3].ljust(3, b"\0")
        self.detonate_word = (int.from_bytes(padding, "little") << 8) | (
            int(self.detonate_word) & 0xFF
        )

    def value(self, name: str, default: float = 0.0) -> float:
        return _finite(self.values.get(name, default), default)

    def set_flag(self, name: str, enabled: bool) -> None:
        bit = next((bit for field_name, bit in EMITTER_FLAG_FIELDS if field_name == name), None)
        if bit is None:
            raise KeyError(name)
        self.flags = (self.flags | (1 << bit)) if enabled else (self.flags & ~(1 << bit))

    def flag(self, name: str) -> bool:
        bit = next((bit for field_name, bit in EMITTER_FLAG_FIELDS if field_name == name), None)
        if bit is None:
            raise KeyError(name)
        return bool(self.flags & (1 << bit))


@dataclass
class JadeLightPayload:
    flare_radius: float = 1.0
    runtime_flare_cache: ArrayDefinition = field(
        default_factory=lambda: ArrayDefinition(0, 0, 0)
    )
    flare_sizes: list[float] = field(default_factory=list)
    flare_positions: list[float] = field(default_factory=list)
    flare_colors: list[tuple[float, float, float]] = field(default_factory=list)
    flare_textures: list[str] = field(default_factory=list)
    priority: int = 5
    ambient_only: bool = False
    affect_type: int = 0
    shadow: bool = True
    flare_hit_check: bool = False
    fading: bool = False
    scene_ambient_only: bool = False
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    shadow_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rim_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    radius: float = 5.0
    shadow_radius: float = 0.0
    vertical_displacement: float = 0.0
    multiplier: float = 1.0
    shadow_fade_start: float = 0.0
    shadow_fade_end: float = 0.0
    shadow_alpha: float = 1.0


@dataclass
class JadeGobPayload:
    move_gob: bool = False
    billboard_gob: bool = False
    reserved: bytes = b"\0\0"
    billboard_axis: tuple[float, float, float] = (0.0, 0.0, 1.0)
    friction_multiplier: float = 1.0
    accuracy_multiplier: float = 1.0
    gravity_multiplier: float = 1.0


@dataclass
class JadeDanglyBonePayload:
    length: float = 1.0
    mass: float = 1.0
    radius: float = 1.0
    dampening: float = 0.0
    constraint_angle: float = 180.0
    derived_length_term: float = 0.0
    dampening_variance: float = 0.0
    inverse_mass: float = 1.0
    local_collisions: bool = False
    local_collision_padding: bytes = b"\0\0\0"
    local_gravity: tuple[float, float, float] = (0.0, 0.0, 0.0)
    global_gravity: tuple[float, float, float] = (0.0, 0.0, 0.0)
    collision_volumes: list[str] = field(default_factory=list)


@dataclass
class JadeAabbEntry:
    minimum: tuple[float, float, float]
    maximum: tuple[float, float, float]
    face_index: int = -1
    plane: int = 0
    left: "JadeAabbEntry | None" = None
    right: "JadeAabbEntry | None" = None
    source_offset: int = 0


@dataclass
class JadeAabbPayload:
    root: JadeAabbEntry | None = None
    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    pairs: list[tuple[float, float]] = field(default_factory=list)
    secondary_root: JadeAabbEntry | None = None
    runtime_1: int = 0
    runtime_2: int = 0


SpecializedPayload = (
    JadeReferencePayload
    | JadeWeaponTrailPayload
    | JadeCollisionPayload
    | JadeClothPayload
    | JadeEmitterPayload
    | JadeLightPayload
    | JadeGobPayload
    | JadeDanglyBonePayload
    | JadeAabbPayload
)


def _parse_reference(view: BinaryView, offset: int) -> JadeReferencePayload:
    return JadeReferencePayload(
        model=view.c_string_fixed(offset, 32, "reference model"),
        reattachable=bool(view.u32(offset + 0x20, "reference reattachable")),
        start_animation=view.c_string_fixed(offset + 0x24, 32, "reference start animation"),
        random_speed=view.f32(offset + 0x44, "reference random speed"),
        random_start_time=view.f32(offset + 0x48, "reference random start time"),
        reference_scale=view.f32(offset + 0x4C, "reference scale"),
        lightmap_prefix=view.c_string_fixed(offset + 0x50, 32, "reference lightmap prefix"),
    )


def _parse_weapon_trail(
    view: BinaryView, offset: int, to_absolute: Callable[[int, str], int]
) -> JadeWeaponTrailPayload:
    position_pointer = view.u32(offset, "weapon trail position pointer")
    uv_pointer = view.u32(offset + 4, "weapon trail UV pointer")
    normal_pointer = view.u32(offset + 8, "weapon trail normal pointer")
    positions: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    normals: list[tuple[float, float, float]] = []
    if position_pointer:
        absolute = to_absolute(position_pointer, "weapon trail positions")
        view.check(absolute, 4 * 12, "weapon trail positions")
        positions = [view.f32_tuple(absolute + i * 12, 3, "weapon trail position") for i in range(4)]
    if uv_pointer:
        absolute = to_absolute(uv_pointer, "weapon trail UVs")
        view.check(absolute, 4 * 8, "weapon trail UVs")
        uvs = [view.f32_tuple(absolute + i * 8, 2, "weapon trail UV") for i in range(4)]
    if normal_pointer:
        absolute = to_absolute(normal_pointer, "weapon trail normals")
        view.check(absolute, 4 * 12, "weapon trail normals")
        normals = [view.f32_tuple(absolute + i * 12, 3, "weapon trail normal") for i in range(4)]
    return JadeWeaponTrailPayload(
        positions=positions,
        uvs=uvs,
        normals=normals,
        flags=view.u32(offset + 0x0C, "weapon trail flags"),
        taper=view.f32(offset + 0x10, "weapon trail taper"),
        segment_interval=view.f32(offset + 0x14, "weapon trail segment interval"),
        segment_life=view.f32(offset + 0x18, "weapon trail segment life"),
        minimum_delta_time=view.f32(offset + 0x1C, "weapon trail minimum delta time"),
    )


def _parse_collision(view: BinaryView, offset: int, shape: str) -> JadeCollisionPayload:
    size = {"sphere": 0x18, "capsule": 0x24, "lozenge": 0x30}[shape]
    view.check(offset, size, f"collision {shape}")
    return JadeCollisionPayload(
        shape=shape,
        point_a=view.f32_tuple(offset, 3, f"collision {shape} point A"),
        radius=view.f32(offset + 0x0C, f"collision {shape} radius"),
        cloth_radius=view.f32(offset + 0x10, f"collision {shape} cloth radius"),
        collide_with_rooms_only=bool(view.u8(offset + 0x14, "collision rooms-only flag")),
        block_lens_flares=bool(view.u8(offset + 0x15, "collision flare-block flag")),
        reserved=view.bytes(offset + 0x16, 2, "collision reserved bytes"),
        point_b=view.f32_tuple(offset + 0x18, 3, "collision point B") if size >= 0x24 else None,
        point_c=view.f32_tuple(offset + 0x24, 3, "collision point C") if size >= 0x30 else None,
    )


def _parse_constraint_array(
    view: BinaryView,
    definition: ArrayDefinition,
    to_absolute: Callable[[int, str], int],
    context: str,
) -> list[JadeClothConstraint]:
    absolute, count = _read_records(view, definition, 12, to_absolute, context)
    return [
        JadeClothConstraint(
            view.u32(absolute + i * 12, f"{context} vertex A"),
            view.u32(absolute + i * 12 + 4, f"{context} vertex B"),
            view.f32(absolute + i * 12 + 8, f"{context} rest length"),
        )
        for i in range(count)
    ]


def _parse_cloth(
    view: BinaryView, offset: int, to_absolute: Callable[[int, str], int]
) -> JadeClothPayload:
    movable_def = view.array_definition(offset + 0x10, "cloth movable constraints")
    attachment_def = view.array_definition(offset + 0x1C, "cloth attachments")
    fixed_def = view.array_definition(offset + 0x28, "cloth fixed constraints")
    collision_def = view.array_definition(offset + 0x34, "cloth collision volumes")
    working_def = view.array_definition(offset + 0x40, "cloth working arrays")
    topology_def = view.array_definition(offset + 0x58, "cloth topology")
    face_vector_def = view.array_definition(offset + 0x64, "cloth face vectors")

    attachment_absolute, attachment_count = _read_records(
        view, attachment_def, 48, to_absolute, "cloth attachments"
    )
    attachments = [
        JadeClothAttachment(
            vertex=view.u32(attachment_absolute + i * 48, "cloth attachment vertex"),
            offset=view.f32_tuple(attachment_absolute + i * 48 + 4, 3, "cloth attachment offset"),
            node_name=view.c_string_fixed(
                attachment_absolute + i * 48 + 16, 32, "cloth attachment node"
            ),
        )
        for i in range(attachment_count)
    ]

    working_absolute, working_count = _read_records(
        view, working_def, 12, to_absolute, "cloth working arrays"
    )
    serialized_working = [
        view.array_definition(working_absolute + i * 12, "cloth working array")
        for i in range(working_count)
    ]
    working_values: list[list[int]] = []
    for index, definition in enumerate(serialized_working):
        values_absolute, values_count = _read_records(
            view,
            definition,
            4,
            to_absolute,
            f"cloth working array {index}",
        )
        working_values.append(
            [
                view.u32(values_absolute + item * 4, f"cloth working array {index}")
                for item in range(values_count)
            ]
        )

    # The descriptor offsets are allocation details, not cloth semantics.
    # Each inner uint32 list is the ordered set of face-record indices touching
    # one mesh vertex.  Normalize the pointers to zero while retaining the
    # declared lengths; compact rebuilding allocates fresh arrays from
    # ``working_array_values``.
    working = [
        ArrayDefinition(0, definition.count, definition.capacity)
        for definition in serialized_working
    ]

    topology_absolute, topology_count = _read_records(
        view, topology_def, 12, to_absolute, "cloth topology"
    )
    topology = [
        (
            view.u32(topology_absolute + i * 12, "cloth topology A"),
            view.u32(topology_absolute + i * 12 + 4, "cloth topology B"),
            view.u32(topology_absolute + i * 12 + 8, "cloth topology C"),
        )
        for i in range(topology_count)
    ]

    face_absolute, face_count = _read_records(
        view, face_vector_def, 12, to_absolute, "cloth face vectors"
    )
    face_vectors = [
        view.f32_tuple(face_absolute + i * 12, 3, "cloth face vector")
        for i in range(face_count)
    ]

    return JadeClothPayload(
        friction=view.f32(offset, "cloth friction"),
        gravity=view.f32_tuple(offset + 4, 3, "cloth gravity"),
        movable_constraints=_parse_constraint_array(
            view, movable_def, to_absolute, "cloth movable constraints"
        ),
        attachments=attachments,
        fixed_constraints=_parse_constraint_array(
            view, fixed_def, to_absolute, "cloth fixed constraints"
        ),
        collision_volumes=_read_fixed_strings(
            view, collision_def, 32, to_absolute, "cloth collision volumes"
        ),
        working_arrays=working,
        working_array_values=working_values,
        accuracy=view.i32(offset + 0x4C, "cloth accuracy"),
        wind_multiplier=view.f32(offset + 0x50, "cloth wind multiplier"),
        solver_iterations=view.i32(offset + 0x54, "cloth solver iterations"),
        topology=topology,
        face_vectors=face_vectors,
        runtime_block=view.bytes(offset + 0x70, 16, "cloth runtime block"),
        state=view.u8(offset + 0x80, "cloth state"),
        state_padding=view.bytes(offset + 0x81, 3, "cloth state padding"),
        runtime_value=view.i32(offset + 0x84, "cloth runtime value"),
    )


def _parse_emitter(
    view: BinaryView, offset: int, to_absolute: Callable[[int, str], int]
) -> JadeEmitterPayload:
    values = {
        name: view.f32(offset + 0xC4 + index * 4, f"emitter {name}")
        for index, name in enumerate(EMITTER_FLOAT_FIELDS)
    }
    batch_definition = view.array_definition(offset + 0x19C, "emitter batch positions")
    batch_absolute, batch_count = _read_records(
        view, batch_definition, 12, to_absolute, "emitter batch positions"
    )
    return JadeEmitterPayload(
        dead_space=view.f32(offset, "emitter dead space"),
        blast_radius=view.f32(offset + 4, "emitter blast radius"),
        blast_length=view.f32(offset + 8, "emitter blast length"),
        number_branches=view.i32(offset + 0x0C, "emitter branch count"),
        control_point_smoothing=view.i32(offset + 0x10, "emitter control smoothing"),
        x_grid=view.i32(offset + 0x14, "emitter X grid"),
        y_grid=view.i32(offset + 0x18, "emitter Y grid"),
        spawn_type=view.i32(offset + 0x1C, "emitter spawn type"),
        update=view.c_string_fixed(offset + 0x20, 32, "emitter update"),
        render=view.c_string_fixed(offset + 0x40, 32, "emitter render"),
        blend=view.c_string_fixed(offset + 0x60, 32, "emitter blend"),
        texture=view.c_string_fixed(offset + 0x80, 32, "emitter texture"),
        chunk_name=view.c_string_fixed(offset + 0xA0, 16, "emitter chunk name"),
        two_sided_texture=bool(view.u32(offset + 0xB0, "emitter two-sided texture")),
        loop=bool(view.u32(offset + 0xB4, "emitter loop")),
        render_order=view.u16(offset + 0xB8, "emitter render order"),
        frame_blending=bool(view.u8(offset + 0xBA, "emitter frame blending")),
        detonate_code=view.i32(offset + 0xBC, "emitter detonate code"),
        initial_random_rotation=view.f32(offset + 0xC0, "emitter initial random rotation"),
        values=values,
        detonate_word=view.u32(offset + 0x198, "emitter detonate/reserved word"),
        batch_positions=[
            view.f32_tuple(batch_absolute + i * 12, 3, "emitter batch position")
            for i in range(batch_count)
        ],
        flags=view.u32(offset + 0x1A8, "emitter flags"),
    )


def _read_float_array(
    view: BinaryView,
    definition: ArrayDefinition,
    to_absolute: Callable[[int, str], int],
    context: str,
) -> list[float]:
    absolute, count = _read_records(view, definition, 4, to_absolute, context)
    return [view.f32(absolute + i * 4, context) for i in range(count)]


def _read_vec3_array(
    view: BinaryView,
    definition: ArrayDefinition,
    to_absolute: Callable[[int, str], int],
    context: str,
) -> list[tuple[float, float, float]]:
    absolute, count = _read_records(view, definition, 12, to_absolute, context)
    return [view.f32_tuple(absolute + i * 12, 3, context) for i in range(count)]


def _parse_light(
    view: BinaryView, offset: int, to_absolute: Callable[[int, str], int]
) -> JadeLightPayload:
    runtime = view.array_definition(offset + 0x04, "light runtime flare cache")
    sizes_def = view.array_definition(offset + 0x10, "light flare sizes")
    positions_def = view.array_definition(offset + 0x1C, "light flare positions")
    colors_def = view.array_definition(offset + 0x28, "light flare colors")
    textures_def = view.array_definition(offset + 0x34, "light flare textures")
    return JadeLightPayload(
        flare_radius=view.f32(offset, "light flare radius"),
        runtime_flare_cache=runtime,
        flare_sizes=_read_float_array(view, sizes_def, to_absolute, "light flare sizes"),
        flare_positions=_read_float_array(
            view, positions_def, to_absolute, "light flare positions"
        ),
        flare_colors=_read_vec3_array(view, colors_def, to_absolute, "light flare colors"),
        flare_textures=_read_pointer_strings(
            view, textures_def, to_absolute, "light flare textures"
        ),
        priority=view.u32(offset + 0x40, "light priority"),
        ambient_only=bool(view.u32(offset + 0x44, "light ambient only")),
        affect_type=view.u32(offset + 0x48, "light affect type"),
        shadow=bool(view.u32(offset + 0x4C, "light shadow")),
        flare_hit_check=bool(view.u32(offset + 0x50, "light flare hit check")),
        fading=bool(view.u32(offset + 0x54, "light fading")),
        scene_ambient_only=bool(view.u32(offset + 0x58, "light scene ambient only")),
        color=view.f32_tuple(offset + 0x5C, 3, "light color"),
        shadow_color=view.f32_tuple(offset + 0x68, 3, "light shadow color"),
        rim_color=view.f32_tuple(offset + 0x74, 3, "light rim color"),
        radius=view.f32(offset + 0x80, "light radius"),
        shadow_radius=view.f32(offset + 0x84, "light shadow radius"),
        vertical_displacement=view.f32(offset + 0x88, "light vertical displacement"),
        multiplier=view.f32(offset + 0x8C, "light multiplier"),
        shadow_fade_start=view.f32(offset + 0x90, "light shadow fade start"),
        shadow_fade_end=view.f32(offset + 0x94, "light shadow fade end"),
        shadow_alpha=view.f32(offset + 0x98, "light shadow alpha"),
    )


def _parse_gob(view: BinaryView, offset: int) -> JadeGobPayload:
    return JadeGobPayload(
        move_gob=bool(view.u8(offset, "GOB move flag")),
        billboard_gob=bool(view.u8(offset + 1, "GOB billboard flag")),
        reserved=view.bytes(offset + 2, 2, "GOB reserved bytes"),
        billboard_axis=view.f32_tuple(offset + 4, 3, "GOB billboard axis"),
        friction_multiplier=view.f32(offset + 0x10, "GOB friction multiplier"),
        accuracy_multiplier=view.f32(offset + 0x14, "GOB accuracy multiplier"),
        gravity_multiplier=view.f32(offset + 0x18, "GOB gravity multiplier"),
    )


def _parse_dangly_bone(
    view: BinaryView, offset: int, to_absolute: Callable[[int, str], int]
) -> JadeDanglyBonePayload:
    volumes_def = view.array_definition(offset + 0x3C, "dangly-bone collision volumes")
    return JadeDanglyBonePayload(
        length=view.f32(offset, "dangly-bone length"),
        mass=view.f32(offset + 4, "dangly-bone mass"),
        radius=view.f32(offset + 8, "dangly-bone radius"),
        dampening=view.f32(offset + 0x0C, "dangly-bone dampening"),
        constraint_angle=view.f32(offset + 0x10, "dangly-bone constraint angle"),
        derived_length_term=view.f32(offset + 0x14, "dangly-bone derived length term"),
        dampening_variance=view.f32(offset + 0x18, "dangly-bone dampening variance"),
        inverse_mass=view.f32(offset + 0x1C, "dangly-bone inverse mass"),
        local_collisions=bool(view.u8(offset + 0x20, "dangly-bone local collisions")),
        local_collision_padding=view.bytes(offset + 0x21, 3, "dangly-bone padding"),
        local_gravity=view.f32_tuple(offset + 0x24, 3, "dangly-bone local gravity"),
        global_gravity=view.f32_tuple(offset + 0x30, 3, "dangly-bone global gravity"),
        collision_volumes=_read_fixed_strings(
            view, volumes_def, 32, to_absolute, "dangly-bone collision volumes"
        ),
    )


def _parse_aabb_entry(
    view: BinaryView,
    relative_offset: int,
    to_absolute: Callable[[int, str], int],
    visited: set[int],
    depth: int,
) -> JadeAabbEntry | None:
    if not relative_offset:
        return None
    if depth > 256:
        raise ValueError("AABB tree depth exceeds 256")
    if relative_offset in visited:
        raise ValueError(f"AABB tree pointer cycle at 0x{relative_offset:X}")
    visited.add(relative_offset)
    absolute = to_absolute(relative_offset, "AABB tree entry")
    view.check(absolute, 0x28, "AABB tree entry")
    left_pointer = view.u32(absolute + 0x18, "AABB left pointer")
    right_pointer = view.u32(absolute + 0x1C, "AABB right pointer")
    entry = JadeAabbEntry(
        minimum=view.f32_tuple(absolute, 3, "AABB minimum"),
        maximum=view.f32_tuple(absolute + 0x0C, 3, "AABB maximum"),
        face_index=view.i32(absolute + 0x20, "AABB face index"),
        plane=view.i32(absolute + 0x24, "AABB plane"),
        source_offset=relative_offset,
    )
    entry.left = _parse_aabb_entry(view, left_pointer, to_absolute, visited, depth + 1)
    entry.right = _parse_aabb_entry(view, right_pointer, to_absolute, visited, depth + 1)
    return entry


def _parse_aabb(
    view: BinaryView, offset: int, to_absolute: Callable[[int, str], int]
) -> JadeAabbPayload:
    root_pointer = view.u32(offset, "AABB root pointer")
    vertices_def = view.array_definition(offset + 4, "AABB vertices")
    pairs_def = view.array_definition(offset + 0x10, "AABB pairs")
    secondary_pointer = view.u32(offset + 0x1C, "AABB secondary root pointer")
    pairs_absolute, pairs_count = _read_records(
        view, pairs_def, 8, to_absolute, "AABB pairs"
    )
    visited: set[int] = set()
    root = _parse_aabb_entry(view, root_pointer, to_absolute, visited, 0)
    secondary = (
        root
        if secondary_pointer and secondary_pointer == root_pointer
        else _parse_aabb_entry(view, secondary_pointer, to_absolute, visited, 0)
    )
    return JadeAabbPayload(
        root=root,
        vertices=_read_vec3_array(view, vertices_def, to_absolute, "AABB vertices"),
        pairs=[
            view.f32_tuple(pairs_absolute + i * 8, 2, "AABB pair")
            for i in range(pairs_count)
        ],
        secondary_root=secondary,
        runtime_1=view.u32(offset + 0x20, "AABB runtime field 1"),
        runtime_2=view.u32(offset + 0x24, "AABB runtime field 2"),
    )


def parse_specialized_payload(
    name: str,
    view: BinaryView,
    absolute_offset: int,
    to_absolute: Callable[[int, str], int],
) -> SpecializedPayload | None:
    """Parse one fixed specialized tail and its referenced arrays."""
    if name == "reference":
        return _parse_reference(view, absolute_offset)
    if name == "weapon_trail":
        return _parse_weapon_trail(view, absolute_offset, to_absolute)
    if name == "collision_sphere":
        return _parse_collision(view, absolute_offset, "sphere")
    if name == "collision_capsule":
        return _parse_collision(view, absolute_offset, "capsule")
    if name == "collision_lozenge":
        return _parse_collision(view, absolute_offset, "lozenge")
    if name == "cloth":
        return _parse_cloth(view, absolute_offset, to_absolute)
    if name == "emitter":
        return _parse_emitter(view, absolute_offset, to_absolute)
    if name == "light":
        return _parse_light(view, absolute_offset, to_absolute)
    if name == "gob":
        return _parse_gob(view, absolute_offset)
    if name == "dangly_bone":
        return _parse_dangly_bone(view, absolute_offset, to_absolute)
    if name == "aabb":
        return _parse_aabb(view, absolute_offset, to_absolute)
    return None


def _pack_array_definition(buffer: bytearray, offset: int, definition: ArrayDefinition) -> None:
    struct.pack_into(
        "<III",
        buffer,
        offset,
        int(definition.offset),
        int(definition.count),
        int(definition.capacity),
    )


def _payload_buffer(size: int, base: bytes | bytearray | None) -> bytearray:
    if base is None:
        return bytearray(size)
    raw = bytes(base)[:size]
    return bytearray(raw + b"\0" * (size - len(raw)))


def fixed_payload_bytes(
    name: str,
    payload: SpecializedPayload,
    base: bytes | bytearray | None = None,
) -> bytearray:
    """Encode scalar/fixed fields, leaving out-of-line pointers as zero.

    The writer fills array and tree pointers after allocating their records.
    """
    if name == "reference" and isinstance(payload, JadeReferencePayload):
        out = _payload_buffer(0x70, base)
        out[0:0x20] = _fixed_ascii(payload.model, 32)
        struct.pack_into("<I", out, 0x20, int(bool(payload.reattachable)))
        out[0x24:0x44] = _fixed_ascii(payload.start_animation, 32)
        struct.pack_into(
            "<fff",
            out,
            0x44,
            _finite(payload.random_speed),
            _finite(payload.random_start_time),
            _finite(payload.reference_scale, 1.0),
        )
        out[0x50:0x70] = _fixed_ascii(payload.lightmap_prefix, 32)
        return out

    if name == "weapon_trail" and isinstance(payload, JadeWeaponTrailPayload):
        out = _payload_buffer(0x20, base)
        struct.pack_into(
            "<Iffff",
            out,
            0x0C,
            int(payload.flags) & 0xFFFFFFFF,
            _finite(payload.taper, 0.4),
            _finite(payload.segment_interval, 0.007),
            _finite(payload.segment_life, 0.2),
            _finite(payload.minimum_delta_time, 0.01),
        )
        return out

    if name.startswith("collision_") and isinstance(payload, JadeCollisionPayload):
        size = {"sphere": 0x18, "capsule": 0x24, "lozenge": 0x30}[payload.shape]
        out = _payload_buffer(size, base)
        struct.pack_into("<3f", out, 0, *_vec3(payload.point_a))
        struct.pack_into(
            "<ffBB",
            out,
            0x0C,
            _finite(payload.radius, 1.0),
            _finite(payload.cloth_radius, 1.0),
            int(bool(payload.collide_with_rooms_only)),
            int(bool(payload.block_lens_flares)),
        )
        out[0x16:0x18] = bytes(payload.reserved or b"\0\0")[:2].ljust(2, b"\0")
        if size >= 0x24:
            struct.pack_into("<3f", out, 0x18, *_vec3(payload.point_b or (0, 0, 0)))
        if size >= 0x30:
            struct.pack_into("<3f", out, 0x24, *_vec3(payload.point_c or (0, 0, 0)))
        return out

    if name == "cloth" and isinstance(payload, JadeClothPayload):
        out = _payload_buffer(0x88, base)
        struct.pack_into("<f3f", out, 0, _finite(payload.friction, 0.03), *_vec3(payload.gravity))
        struct.pack_into("<ifi", out, 0x4C, int(payload.accuracy), _finite(payload.wind_multiplier), int(payload.solver_iterations))
        out[0x70:0x80] = bytes(payload.runtime_block or b"")[:16].ljust(16, b"\0")
        out[0x80] = int(payload.state) & 0xFF
        out[0x81:0x84] = bytes(payload.state_padding or b"")[:3].ljust(3, b"\0")
        struct.pack_into("<i", out, 0x84, int(payload.runtime_value))
        return out

    if name == "emitter" and isinstance(payload, JadeEmitterPayload):
        out = _payload_buffer(0x1AC, base)
        struct.pack_into(
            "<fffiiiii",
            out,
            0,
            _finite(payload.dead_space),
            _finite(payload.blast_radius),
            _finite(payload.blast_length),
            int(payload.number_branches),
            int(payload.control_point_smoothing),
            int(payload.x_grid),
            int(payload.y_grid),
            int(payload.spawn_type),
        )
        out[0x20:0x40] = _fixed_ascii(payload.update, 32)
        out[0x40:0x60] = _fixed_ascii(payload.render, 32)
        out[0x60:0x80] = _fixed_ascii(payload.blend, 32)
        out[0x80:0xA0] = _fixed_ascii(payload.texture, 32)
        out[0xA0:0xB0] = _fixed_ascii(payload.chunk_name, 16)
        struct.pack_into(
            "<IIHBBif",
            out,
            0xB0,
            int(bool(payload.two_sided_texture)),
            int(bool(payload.loop)),
            int(payload.render_order) & 0xFFFF,
            int(bool(payload.frame_blending)),
            0,
            int(payload.detonate_code),
            _finite(payload.initial_random_rotation),
        )
        for index, field_name in enumerate(EMITTER_FLOAT_FIELDS):
            struct.pack_into("<f", out, 0xC4 + index * 4, payload.value(field_name))
        struct.pack_into("<I", out, 0x198, int(payload.detonate_word) & 0xFFFFFFFF)
        struct.pack_into("<I", out, 0x1A8, int(payload.flags) & 0xFFFFFFFF)
        return out

    if name == "light" and isinstance(payload, JadeLightPayload):
        out = _payload_buffer(0x9C, base)
        struct.pack_into("<f", out, 0, _finite(payload.flare_radius, 1.0))
        # runtime cache and semantic array definitions are filled by the writer.
        struct.pack_into(
            "<IIIIIII",
            out,
            0x40,
            int(payload.priority),
            int(bool(payload.ambient_only)),
            int(payload.affect_type),
            int(bool(payload.shadow)),
            int(bool(payload.flare_hit_check)),
            int(bool(payload.fading)),
            int(bool(payload.scene_ambient_only)),
        )
        struct.pack_into("<3f", out, 0x5C, *_vec3(payload.color))
        struct.pack_into("<3f", out, 0x68, *_vec3(payload.shadow_color))
        struct.pack_into("<3f", out, 0x74, *_vec3(payload.rim_color))
        struct.pack_into(
            "<7f",
            out,
            0x80,
            _finite(payload.radius, 5.0),
            _finite(payload.shadow_radius),
            _finite(payload.vertical_displacement),
            _finite(payload.multiplier, 1.0),
            _finite(payload.shadow_fade_start),
            _finite(payload.shadow_fade_end),
            _finite(payload.shadow_alpha, 1.0),
        )
        return out

    if name == "gob" and isinstance(payload, JadeGobPayload):
        out = _payload_buffer(0x1C, base)
        out[0] = int(bool(payload.move_gob))
        out[1] = int(bool(payload.billboard_gob))
        out[2:4] = bytes(payload.reserved or b"")[:2].ljust(2, b"\0")
        struct.pack_into("<3f", out, 4, *_vec3(payload.billboard_axis))
        struct.pack_into(
            "<fff",
            out,
            0x10,
            _finite(payload.friction_multiplier, 1.0),
            _finite(payload.accuracy_multiplier, 1.0),
            _finite(payload.gravity_multiplier, 1.0),
        )
        return out

    if name == "dangly_bone" and isinstance(payload, JadeDanglyBonePayload):
        out = _payload_buffer(0x48, base)
        inverse_mass = _finite(payload.inverse_mass, 0.0)
        if inverse_mass <= 0.0 and _finite(payload.mass, 0.0) > 0.0:
            inverse_mass = 1.0 / _finite(payload.mass, 1.0)
        struct.pack_into(
            "<8f",
            out,
            0,
            _finite(payload.length, 1.0),
            _finite(payload.mass, 1.0),
            _finite(payload.radius, 1.0),
            _finite(payload.dampening),
            _finite(payload.constraint_angle, 180.0),
            _finite(payload.derived_length_term),
            _finite(payload.dampening_variance),
            inverse_mass,
        )
        out[0x20] = int(bool(payload.local_collisions))
        out[0x21:0x24] = bytes(payload.local_collision_padding or b"")[:3].ljust(3, b"\0")
        struct.pack_into("<3f", out, 0x24, *_vec3(payload.local_gravity))
        struct.pack_into("<3f", out, 0x30, *_vec3(payload.global_gravity))
        return out

    if name == "aabb" and isinstance(payload, JadeAabbPayload):
        out = _payload_buffer(0x28, base)
        struct.pack_into("<II", out, 0x20, int(payload.runtime_1), int(payload.runtime_2))
        return out

    raise TypeError(f"Payload {type(payload).__name__} cannot be encoded as {name}")


# Shared by the compact typed writer.
def write_array_definition(
    buffer: bytearray,
    offset: int,
    pointer: int,
    count: int,
    capacity: int | None = None,
) -> None:
    capacity = count if capacity is None else capacity
    struct.pack_into("<III", buffer, offset, int(pointer), int(count), int(capacity))


class SpecializedAllocator(Protocol):
    """Minimal allocator interface used by the Jade MDL writer."""

    data: bytearray

    def allocate(self, size: int, alignment: int = 4) -> int: ...

    def append(self, payload: bytes | bytearray, alignment: int = 4) -> int: ...


def _append_struct_rows(
    allocator: SpecializedAllocator,
    fmt: str,
    rows: Iterable[Sequence[Any]],
    *,
    alignment: int = 4,
) -> tuple[int, int]:
    rows = list(rows)
    if not rows:
        return 0, 0
    stride = struct.calcsize(fmt)
    pointer = allocator.allocate(stride * len(rows), alignment)
    for index, row in enumerate(rows):
        struct.pack_into(fmt, allocator.data, pointer + index * stride, *row)
    return pointer, len(rows)


def _append_pointer_strings(
    allocator: SpecializedAllocator,
    values: Iterable[str],
) -> tuple[int, int]:
    strings = [str(value or "") for value in values]
    if not strings:
        return 0, 0
    pointer = allocator.allocate(4 * len(strings), 4)
    for index, value in enumerate(strings):
        string_pointer = (
            allocator.append(value.encode("ascii", errors="replace") + b"\0", 1)
            if value
            else 0
        )
        struct.pack_into("<I", allocator.data, pointer + index * 4, string_pointer)
    return pointer, len(strings)


def _append_fixed_strings(
    allocator: SpecializedAllocator,
    values: Iterable[str],
    stride: int = 32,
) -> tuple[int, int]:
    strings = [str(value or "") for value in values]
    if not strings:
        return 0, 0
    pointer = allocator.allocate(stride * len(strings), 4)
    for index, value in enumerate(strings):
        allocator.data[pointer + index * stride : pointer + (index + 1) * stride] = (
            _fixed_ascii(value, stride)
        )
    return pointer, len(strings)


def _write_aabb_tree(
    allocator: SpecializedAllocator,
    entry: JadeAabbEntry | None,
    memo: dict[int, int],
) -> int:
    if entry is None:
        return 0
    identity = id(entry)
    if identity in memo:
        return memo[identity]
    pointer = allocator.allocate(0x28, 4)
    memo[identity] = pointer
    left = _write_aabb_tree(allocator, entry.left, memo)
    right = _write_aabb_tree(allocator, entry.right, memo)
    struct.pack_into("<3f", allocator.data, pointer, *_vec3(entry.minimum))
    struct.pack_into("<3f", allocator.data, pointer + 0x0C, *_vec3(entry.maximum))
    struct.pack_into(
        "<IIii",
        allocator.data,
        pointer + 0x18,
        left,
        right,
        int(entry.face_index),
        int(entry.plane),
    )
    return pointer


def write_specialized_payload(
    allocator: SpecializedAllocator,
    name: str,
    payload: SpecializedPayload,
    target_offset: int,
    *,
    base_fixed: bytes | bytearray | None = None,
) -> None:
    """Write a complete specialized payload and all of its reachable arrays.

    ``target_offset`` points at the fixed class tail already allocated directly
    after the node header (and mesh/skin headers where applicable).  Every
    pointer written here is relative to the Jade model-data base, matching the
    allocator's offsets.
    """

    fixed = fixed_payload_bytes(name, payload, base=base_fixed)

    if name == "weapon_trail" and isinstance(payload, JadeWeaponTrailPayload):
        positions, _ = _append_struct_rows(allocator, "<3f", payload.positions[:4])
        uvs, _ = _append_struct_rows(allocator, "<2f", payload.uvs[:4])
        normals, _ = _append_struct_rows(allocator, "<3f", payload.normals[:4])
        struct.pack_into("<III", fixed, 0, positions, uvs, normals)

    elif name == "cloth" and isinstance(payload, JadeClothPayload):
        movable, movable_count = _append_struct_rows(
            allocator,
            "<IIf",
            ((item.vertex_a, item.vertex_b, _finite(item.rest_length)) for item in payload.movable_constraints),
        )
        attachments, attachment_count = _append_struct_rows(
            allocator,
            "<I3f32s",
            (
                (
                    item.vertex,
                    *_vec3(item.offset),
                    _fixed_ascii(item.node_name, 32),
                )
                for item in payload.attachments
            ),
        )
        fixed_constraints, fixed_count = _append_struct_rows(
            allocator,
            "<IIf",
            ((item.vertex_a, item.vertex_b, _finite(item.rest_length)) for item in payload.fixed_constraints),
        )
        collision, collision_count = _append_fixed_strings(
            allocator, payload.collision_volumes
        )

        # This nested adjacency table is serialized model data, not process
        # scratch. Rebuild every inner uint32 array and then the descriptor
        # table so compact exports never retain stale file offsets.
        working_descriptors: list[tuple[int, int, int]] = []
        source_values = list(payload.working_array_values)
        if not source_values and payload.working_arrays:
            source_values = [[] for _definition in payload.working_arrays]
        for values in source_values:
            pointer, count = _append_struct_rows(
                allocator, "<I", ((int(value) & 0xFFFFFFFF,) for value in values)
            )
            working_descriptors.append((pointer, count, count))
        working, working_count = _append_struct_rows(
            allocator, "<III", working_descriptors
        )

        topology, topology_count = _append_struct_rows(
            allocator,
            "<III",
            ((int(a), int(b), int(c)) for a, b, c in payload.topology),
        )
        face_vectors, face_count = _append_struct_rows(
            allocator, "<3f", (_vec3(row) for row in payload.face_vectors)
        )
        write_array_definition(fixed, 0x10, movable, movable_count)
        write_array_definition(fixed, 0x1C, attachments, attachment_count)
        write_array_definition(fixed, 0x28, fixed_constraints, fixed_count)
        write_array_definition(fixed, 0x34, collision, collision_count)
        write_array_definition(fixed, 0x40, working, working_count)
        write_array_definition(fixed, 0x58, topology, topology_count)
        write_array_definition(fixed, 0x64, face_vectors, face_count)

    elif name == "emitter" and isinstance(payload, JadeEmitterPayload):
        batch, batch_count = _append_struct_rows(
            allocator, "<3f", (_vec3(row) for row in payload.batch_positions)
        )
        write_array_definition(fixed, 0x19C, batch, batch_count)

    elif name == "light" and isinstance(payload, JadeLightPayload):
        sizes, sizes_count = _append_struct_rows(
            allocator, "<f", ((_finite(value),) for value in payload.flare_sizes)
        )
        positions, positions_count = _append_struct_rows(
            allocator, "<f", ((_finite(value),) for value in payload.flare_positions)
        )
        colors, colors_count = _append_struct_rows(
            allocator, "<3f", (_vec3(value) for value in payload.flare_colors)
        )
        textures, textures_count = _append_pointer_strings(
            allocator, payload.flare_textures
        )
        # Runtime flare cache is never authored.  Preserve the original raw
        # descriptor only when a source tail was supplied; otherwise clear it.
        if base_fixed is None:
            write_array_definition(fixed, 0x04, 0, 0)
        write_array_definition(fixed, 0x10, sizes, sizes_count)
        write_array_definition(fixed, 0x1C, positions, positions_count)
        write_array_definition(fixed, 0x28, colors, colors_count)
        write_array_definition(fixed, 0x34, textures, textures_count)

    elif name == "dangly_bone" and isinstance(payload, JadeDanglyBonePayload):
        volumes, volume_count = _append_fixed_strings(
            allocator, payload.collision_volumes
        )
        write_array_definition(fixed, 0x3C, volumes, volume_count)

    elif name == "aabb" and isinstance(payload, JadeAabbPayload):
        memo: dict[int, int] = {}
        root = _write_aabb_tree(allocator, payload.root, memo)
        secondary = _write_aabb_tree(allocator, payload.secondary_root, memo)
        vertices, vertex_count = _append_struct_rows(
            allocator, "<3f", (_vec3(row) for row in payload.vertices)
        )
        pairs, pair_count = _append_struct_rows(
            allocator, "<2f", (_vec2(row) for row in payload.pairs)
        )
        struct.pack_into("<I", fixed, 0, root)
        write_array_definition(fixed, 0x04, vertices, vertex_count)
        write_array_definition(fixed, 0x10, pairs, pair_count)
        struct.pack_into("<I", fixed, 0x1C, secondary)

    allocator.data[target_offset : target_offset + len(fixed)] = fixed


def _float_to_json(value: float) -> float | dict[str, str]:
    value = float(value)
    if math.isfinite(value):
        return value
    return {"__float64_bits__": struct.pack("<d", value).hex()}


def _jsonify(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__bytes__": value.hex()}
    if isinstance(value, float):
        return _float_to_json(value)
    if isinstance(value, ArrayDefinition):
        return {
            "__array_definition__": [
                int(value.offset),
                int(value.count),
                int(value.capacity),
            ]
        }
    if isinstance(value, JadeAabbEntry):
        return {
            "minimum": _jsonify(value.minimum),
            "maximum": _jsonify(value.maximum),
            "face_index": int(value.face_index),
            "plane": int(value.plane),
            "left": _jsonify(value.left),
            "right": _jsonify(value.right),
            "source_offset": int(value.source_offset),
        }
    if is_dataclass(value):
        return {field_info.name: _jsonify(getattr(value, field_info.name)) for field_info in fields(value)}
    if isinstance(value, dict):
        return {str(key): _jsonify(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def _dejsonify(value: Any) -> Any:
    if isinstance(value, dict):
        if "__bytes__" in value:
            return bytes.fromhex(str(value["__bytes__"]))
        if "__float64_bits__" in value:
            return struct.unpack("<d", bytes.fromhex(str(value["__float64_bits__"])))[0]
        if "__array_definition__" in value:
            raw = list(value["__array_definition__"])
            return ArrayDefinition(int(raw[0]), int(raw[1]), int(raw[2]))
        return {key: _dejsonify(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_dejsonify(item) for item in value]
    return value


def _aabb_entry_from_mapping(value: Any) -> JadeAabbEntry | None:
    if not isinstance(value, Mapping):
        return None
    entry = JadeAabbEntry(
        minimum=_vec3(value.get("minimum", (0.0, 0.0, 0.0))),
        maximum=_vec3(value.get("maximum", (0.0, 0.0, 0.0))),
        face_index=int(value.get("face_index", -1)),
        plane=int(value.get("plane", 0)),
        source_offset=int(value.get("source_offset", 0)),
    )
    entry.left = _aabb_entry_from_mapping(value.get("left"))
    entry.right = _aabb_entry_from_mapping(value.get("right"))
    return entry


def payload_as_dict(payload: SpecializedPayload | None) -> dict[str, Any]:
    """Return a JSON-safe, bit-preserving payload representation."""
    if payload is None:
        return {}
    result = _jsonify(payload)
    assert isinstance(result, dict)
    result["__type__"] = type(payload).__name__
    return result


def payload_from_dict(name: str, raw: Mapping[str, Any]) -> SpecializedPayload:
    """Reconstruct a typed payload from a Blender custom-property mapping."""
    data = _dejsonify(dict(raw))
    data.pop("__type__", None)

    if name == "reference":
        return JadeReferencePayload(**data)
    if name == "weapon_trail":
        return JadeWeaponTrailPayload(
            positions=[tuple(row) for row in data.get("positions", [])],
            uvs=[tuple(row) for row in data.get("uvs", [])],
            normals=[tuple(row) for row in data.get("normals", [])],
            flags=int(data.get("flags", 0x2)),
            taper=float(data.get("taper", 0.4)),
            segment_interval=float(data.get("segment_interval", 0.007)),
            segment_life=float(data.get("segment_life", 0.2)),
            minimum_delta_time=float(data.get("minimum_delta_time", 0.01)),
        )
    if name.startswith("collision_"):
        return JadeCollisionPayload(
            shape=str(data.get("shape", name.removeprefix("collision_"))),
            point_a=_vec3(data.get("point_a", (0.0, 0.0, 0.0))),
            radius=float(data.get("radius", 1.0)),
            cloth_radius=float(data.get("cloth_radius", 1.0)),
            collide_with_rooms_only=bool(data.get("collide_with_rooms_only", False)),
            block_lens_flares=bool(data.get("block_lens_flares", False)),
            point_b=(
                _vec3(data.get("point_b")) if data.get("point_b") is not None else None
            ),
            point_c=(
                _vec3(data.get("point_c")) if data.get("point_c") is not None else None
            ),
            reserved=bytes(data.get("reserved", b"\0\0")),
        )
    if name == "cloth":
        return JadeClothPayload(
            friction=float(data.get("friction", 0.03)),
            gravity=_vec3(data.get("gravity", (0.0, 0.0, -5.0))),
            movable_constraints=[JadeClothConstraint(**item) for item in data.get("movable_constraints", [])],
            attachments=[
                JadeClothAttachment(
                    vertex=int(item.get("vertex", 0)),
                    offset=_vec3(item.get("offset", (0.0, 0.0, 0.0))),
                    node_name=str(item.get("node_name", "")),
                )
                for item in data.get("attachments", [])
            ],
            fixed_constraints=[JadeClothConstraint(**item) for item in data.get("fixed_constraints", [])],
            collision_volumes=[str(value) for value in data.get("collision_volumes", [])],
            working_arrays=[
                value if isinstance(value, ArrayDefinition) else ArrayDefinition(**value)
                for value in data.get("working_arrays", [])
            ],
            working_array_values=[
                [int(item) & 0xFFFFFFFF for item in values]
                for values in data.get("working_array_values", [])
            ],
            accuracy=int(data.get("accuracy", 1)),
            wind_multiplier=float(data.get("wind_multiplier", 0.1)),
            solver_iterations=int(data.get("solver_iterations", 14)),
            topology=[tuple(int(component) for component in row) for row in data.get("topology", [])],
            face_vectors=[_vec3(row) for row in data.get("face_vectors", [])],
            runtime_block=bytes(data.get("runtime_block", b"\0" * 16)),
            state=int(data.get("state", 1)),
            state_padding=bytes(data.get("state_padding", b"\0\0\0")),
            runtime_value=int(data.get("runtime_value", 0)),
        )
    if name == "emitter":
        return JadeEmitterPayload(
            dead_space=float(data.get("dead_space", 0.0)),
            blast_radius=float(data.get("blast_radius", 0.0)),
            blast_length=float(data.get("blast_length", 0.0)),
            number_branches=int(data.get("number_branches", 0)),
            control_point_smoothing=int(data.get("control_point_smoothing", 0)),
            x_grid=int(data.get("x_grid", 0)),
            y_grid=int(data.get("y_grid", 0)),
            spawn_type=int(data.get("spawn_type", 0)),
            update=str(data.get("update", "")),
            render=str(data.get("render", "")),
            blend=str(data.get("blend", "")),
            texture=str(data.get("texture", "")),
            chunk_name=str(data.get("chunk_name", "")),
            two_sided_texture=bool(data.get("two_sided_texture", False)),
            loop=bool(data.get("loop", False)),
            render_order=int(data.get("render_order", 0)),
            frame_blending=bool(data.get("frame_blending", False)),
            detonate_code=int(data.get("detonate_code", -1)),
            initial_random_rotation=float(data.get("initial_random_rotation", 0.0)),
            values={str(key): float(value) for key, value in dict(data.get("values", {})).items()},
            detonate_word=int(data.get("detonate_word", 0)),
            batch_positions=[_vec3(row) for row in data.get("batch_positions", [])],
            flags=int(data.get("flags", 0)),
        )
    if name == "light":
        runtime = data.get("runtime_flare_cache", ArrayDefinition(0, 0, 0))
        if not isinstance(runtime, ArrayDefinition):
            runtime = ArrayDefinition(**runtime)
        return JadeLightPayload(
            flare_radius=float(data.get("flare_radius", 1.0)),
            runtime_flare_cache=runtime,
            flare_sizes=[float(value) for value in data.get("flare_sizes", [])],
            flare_positions=[float(value) for value in data.get("flare_positions", [])],
            flare_colors=[_vec3(value) for value in data.get("flare_colors", [])],
            flare_textures=[str(value) for value in data.get("flare_textures", [])],
            priority=int(data.get("priority", 5)),
            ambient_only=bool(data.get("ambient_only", False)),
            affect_type=int(data.get("affect_type", 0)),
            shadow=bool(data.get("shadow", True)),
            flare_hit_check=bool(data.get("flare_hit_check", False)),
            fading=bool(data.get("fading", False)),
            scene_ambient_only=bool(data.get("scene_ambient_only", False)),
            color=_vec3(data.get("color", (1.0, 1.0, 1.0))),
            shadow_color=_vec3(data.get("shadow_color", (0.0, 0.0, 0.0))),
            rim_color=_vec3(data.get("rim_color", (0.0, 0.0, 0.0))),
            radius=float(data.get("radius", 5.0)),
            shadow_radius=float(data.get("shadow_radius", 0.0)),
            vertical_displacement=float(data.get("vertical_displacement", 0.0)),
            multiplier=float(data.get("multiplier", 1.0)),
            shadow_fade_start=float(data.get("shadow_fade_start", 0.0)),
            shadow_fade_end=float(data.get("shadow_fade_end", 0.0)),
            shadow_alpha=float(data.get("shadow_alpha", 1.0)),
        )
    if name == "gob":
        return JadeGobPayload(
            move_gob=bool(data.get("move_gob", False)),
            billboard_gob=bool(data.get("billboard_gob", False)),
            reserved=bytes(data.get("reserved", b"\0\0")),
            billboard_axis=_vec3(data.get("billboard_axis", (0.0, 0.0, 1.0))),
            friction_multiplier=float(data.get("friction_multiplier", 1.0)),
            accuracy_multiplier=float(data.get("accuracy_multiplier", 1.0)),
            gravity_multiplier=float(data.get("gravity_multiplier", 1.0)),
        )
    if name == "dangly_bone":
        return JadeDanglyBonePayload(
            length=float(data.get("length", 1.0)),
            mass=float(data.get("mass", 1.0)),
            radius=float(data.get("radius", 1.0)),
            dampening=float(data.get("dampening", 0.0)),
            constraint_angle=float(data.get("constraint_angle", 180.0)),
            derived_length_term=float(data.get("derived_length_term", 0.0)),
            dampening_variance=float(data.get("dampening_variance", 0.0)),
            inverse_mass=float(data.get("inverse_mass", 1.0)),
            local_collisions=bool(data.get("local_collisions", False)),
            local_collision_padding=bytes(data.get("local_collision_padding", b"\0\0\0")),
            local_gravity=_vec3(data.get("local_gravity", (0.0, 0.0, 0.0))),
            global_gravity=_vec3(data.get("global_gravity", (0.0, 0.0, 0.0))),
            collision_volumes=[str(value) for value in data.get("collision_volumes", [])],
        )
    if name == "aabb":
        return JadeAabbPayload(
            root=_aabb_entry_from_mapping(data.get("root")),
            vertices=[_vec3(row) for row in data.get("vertices", [])],
            pairs=[_vec2(row) for row in data.get("pairs", [])],
            secondary_root=_aabb_entry_from_mapping(data.get("secondary_root")),
            runtime_1=int(data.get("runtime_1", 0)),
            runtime_2=int(data.get("runtime_2", 0)),
        )
    raise ValueError(f"Unsupported Jade specialized payload name: {name}")


def payloads_to_json(payloads: Mapping[str, SpecializedPayload]) -> str:
    return json.dumps(
        {str(name): payload_as_dict(payload) for name, payload in payloads.items()},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def payloads_from_json(value: str | bytes | Mapping[str, Any] | None) -> dict[str, SpecializedPayload]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        raw = dict(value)
    else:
        try:
            raw = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    if not isinstance(raw, Mapping):
        return {}
    output: dict[str, SpecializedPayload] = {}
    for name, item in raw.items():
        if isinstance(item, Mapping):
            output[str(name)] = payload_from_dict(str(name), item)
    return output


def _semantic_payload_value(value: Any) -> Any:
    """Return allocation-independent specialized payload semantics.

    Pointer offsets and runtime cache descriptors are products of one concrete
    allocation graph.  They are intentionally rebuilt on every compact export
    and are not authoring state.  All actual fixed fields and reachable array
    contents remain in the signature.
    """

    if isinstance(value, bytes):
        return {"__bytes__": value.hex()}
    if isinstance(value, float):
        return _float_to_json(value)
    if isinstance(value, ArrayDefinition):
        return {
            "count": int(value.count),
            "capacity": int(value.capacity),
        }
    if isinstance(value, JadeAabbEntry):
        return {
            "minimum": _semantic_payload_value(value.minimum),
            "maximum": _semantic_payload_value(value.maximum),
            "face_index": int(value.face_index),
            "plane": int(value.plane),
            "left": _semantic_payload_value(value.left),
            "right": _semantic_payload_value(value.right),
        }
    if isinstance(value, JadeClothPayload):
        return {
            field_info.name: _semantic_payload_value(getattr(value, field_info.name))
            for field_info in fields(value)
            if field_info.name != "working_arrays"
        }
    if isinstance(value, JadeLightPayload):
        return {
            field_info.name: _semantic_payload_value(getattr(value, field_info.name))
            for field_info in fields(value)
            if field_info.name != "runtime_flare_cache"
        }
    if is_dataclass(value):
        return {
            field_info.name: _semantic_payload_value(getattr(value, field_info.name))
            for field_info in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _semantic_payload_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_semantic_payload_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def payload_semantic_dict(payload: SpecializedPayload | None) -> dict[str, Any]:
    """Return a JSON-safe signature that excludes allocation-only metadata."""

    if payload is None:
        return {}
    result = _semantic_payload_value(payload)
    assert isinstance(result, dict)
    result["__type__"] = type(payload).__name__
    return result


def payloads_equal(
    left: Mapping[str, SpecializedPayload],
    right: Mapping[str, SpecializedPayload],
) -> bool:
    """Allocation-independent semantic equality for compact rebuild validation."""

    left_value = {
        str(name): payload_semantic_dict(payload) for name, payload in left.items()
    }
    right_value = {
        str(name): payload_semantic_dict(payload) for name, payload in right.items()
    }
    return json.dumps(
        left_value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ) == json.dumps(
        right_value, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
