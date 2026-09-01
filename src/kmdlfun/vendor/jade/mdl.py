# SPDX-License-Identifier: GPL-3.0-or-later
"""Jade Empire PC MDL/MDX parser.

The reader intentionally keeps file-format data separate from Blender.  It is
based on the shipped PC v7 layout, the JadeMDL.bt public-domain template, the
xoreos Jade loader, and cross-engine comparison with KotorBlender.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .binary import ArrayDefinition, BinaryBoundsError, BinaryView
from .specialized import (
    JADE_NODE_CLASS_NAMES,
    SpecializedPayload,
    parse_specialized_payload,
    payload_layout_for_flags,
)
from .controllers import (
    CONTROLLER_DESCRIPTOR_SIZE,
    CONTROLLER_HEADER_SIZE,
    DATA_TYPE_NAMES,
    JadeControllerDescriptor,
    JadeControllerSet,
    controller_context_name,
    controller_name,
    decode_controller_row,
    finite_decoded_row,
    validate_descriptor_auxiliary,
    words_per_row,
)

JADE_PC_V7_MAGIC = 0x00008700
MODEL_DATA_OFFSET = 20
MODEL_HEADER_SIZE = 0xDC
NODE_HEADER_SIZE = 0x3C
MESH_HEADER_SIZE = 0xE4
SKIN_HEADER_SIZE = 0xA0
FACE_RECORD_SIZE = 0x1C

# Node content flags.
NODE_HEADER = 0x00000001
NODE_LIGHT = 0x00000002
NODE_EMITTER = 0x00000004
NODE_CAMERA = 0x00000008
NODE_REFERENCE = 0x00000010
NODE_MESH = 0x00000020
NODE_SKIN = 0x00000040
NODE_ANIM = 0x00000080
NODE_DANGLY = 0x00000100
NODE_AABB = 0x00000200
# The Jade loader does not construct a trigger node, but this inherited
# Odyssey bit remains a recognized serialized slot.
NODE_LEGACY_TRIGGER = 0x00000400
NODE_WEAPON_TRAIL = 0x00000800
NODE_GOB = 0x00001000
NODE_COLLISION = 0x00002000
NODE_SPHERE = 0x00004000
NODE_CAPSULE = 0x00008000
# These two bits are reserved by the PC v7 layout.  No Jade loader class in
# the shipped executable emits them, and none occur in the supplied corpus.
NODE_RESERVED_10000 = 0x00010000
NODE_DANGLY_BONE = 0x00020000
NODE_CONTROLLERS = 0x00040000
NODE_RESERVED_80000 = 0x00080000

NODE_FLAG_NAMES = {
    NODE_HEADER: "header",
    NODE_LIGHT: "light",
    NODE_EMITTER: "emitter",
    NODE_CAMERA: "camera",
    NODE_REFERENCE: "reference",
    NODE_MESH: "mesh",
    NODE_SKIN: "skin",
    NODE_ANIM: "anim",
    NODE_DANGLY: "dangly",
    NODE_AABB: "aabb",
    NODE_LEGACY_TRIGGER: "legacy_trigger_slot",
    NODE_WEAPON_TRAIL: "weapon_trail_component",
    NODE_GOB: "gob",
    NODE_COLLISION: "collision",
    NODE_SPHERE: "sphere",
    NODE_CAPSULE: "capsule",
    NODE_RESERVED_10000: "reserved_10000",
    NODE_DANGLY_BONE: "dangly_bone",
    NODE_CONTROLLERS: "controllers",
    NODE_RESERVED_80000: "reserved_80000",
}

EXACT_NODE_TYPE_NAMES = dict(JADE_NODE_CLASS_NAMES)

KNOWN_SERIALIZED_NODE_BITS = 0
for _known_flag in NODE_FLAG_NAMES:
    KNOWN_SERIALIZED_NODE_BITS |= _known_flag

# Payload order is the order used by Jade's node loader and the public PC v7
# template.  Payload bytes are retained even where Blender has no editor UI.
NODE_PAYLOAD_LAYOUT = (
    ("light", NODE_LIGHT, 0x9C),
    ("emitter", NODE_EMITTER, 0x1AC),
    ("mesh", NODE_MESH, MESH_HEADER_SIZE),
    ("skin", NODE_SKIN, SKIN_HEADER_SIZE),
    ("aabb", NODE_AABB, 0x28),
    ("gob", NODE_GOB, 0x1C),
    ("dangly_bone", NODE_DANGLY_BONE, 0x48),
    ("controllers", NODE_CONTROLLERS, CONTROLLER_HEADER_SIZE),
)

MESH_FLAG_ANIMATED_UV = 0x01
MESH_FLAG_LIGHTMAPPED = 0x02
MESH_FLAG_BACKGROUND = 0x04
MESH_FLAG_BEAMING = 0x08
MESH_FLAG_RENDER = 0x10

PRIMITIVE_NAMES = {
    0: "point_list",
    1: "line_list",
    2: "line_strip",
    3: "triangle_list",
    4: "triangle_strip",
    5: "triangle_fan",
    6: "unknown_6",
}


@dataclass
class Diagnostic:
    severity: str
    message: str
    offset: int | None = None
    node: str | None = None

    def format(self) -> str:
        location = ""
        if self.offset is not None:
            location += f" @ 0x{self.offset:X}"
        if self.node:
            location += f" [{self.node}]"
        return f"{self.severity.upper()}: {self.message}{location}"


@dataclass
class JadeFaceRecord:
    normal: tuple[float, float, float]
    distance: float
    unknown1: int
    unknown2: int
    vertices: tuple[int, int, int]
    unknown3: int


@dataclass
class JadeSkin:
    mdx_bone_weights_offset: int = -1
    mdx_bone_mapping_id_offset: int = -1
    bone_mapping_offset: int = 0
    bone_mapping: list[int] = field(default_factory=list)
    bone_quats: ArrayDefinition = field(default_factory=lambda: ArrayDefinition(0, 0, 0))
    bone_vertices: ArrayDefinition = field(default_factory=lambda: ArrayDefinition(0, 0, 0))
    bone_constants: ArrayDefinition = field(default_factory=lambda: ArrayDefinition(0, 0, 0))
    bone_quat_values: list[tuple[float, float, float, float]] = field(default_factory=list)
    bone_vertex_values: list[tuple[float, float, float]] = field(default_factory=list)
    # The public format template calls the first 47 entries ``bone_parts`` and
    # the final short ``spare``.  Retail assets use all 48 shorts as the palette
    # addressed by the encoded per-vertex bone IDs, so keep the complete table.
    bone_palette: list[int] = field(default_factory=list)
    vertex_weights: list[list[tuple[int, float]]] = field(default_factory=list)
    raw_weight_values: list[tuple[float, float, float, float]] = field(
        default_factory=list
    )
    raw_bone_ids: list[tuple[int, int, int, int]] = field(default_factory=list)

    @property
    def bone_parts(self) -> list[int]:
        """Compatibility alias retained for early JadeBlender callers."""
        return self.bone_palette


@dataclass
class JadeMesh:
    header_offset: int
    face_array: ArrayDefinition
    bounding_min: tuple[float, float, float]
    bounding_max: tuple[float, float, float]
    radius: float
    average: tuple[float, float, float]
    transparency: int
    flags: int
    shadow: bool
    texture: str
    index_count_declared: int
    face_offset_mdl: int
    primitive_type: int
    mdx_stride: int
    vertex_flags: int
    position_offset: int
    normal_offset: int
    color_offset: int
    uv_offsets: list[int]
    tangent_offset: int
    extra_offsets: list[int]
    vertex_count_declared: int
    texture_count: int
    vertex_offset_mdx: int
    material_id: int
    material_group_id: int
    self_illumination: tuple[float, float, float]
    alpha: float
    texture_w: float
    face_offset_mdx: int
    mdx_face_size: int
    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    normals: list[tuple[float, float, float]] = field(default_factory=list)
    raw_normal_values: list[int] = field(default_factory=list)
    colors: list[tuple[float, float, float, float]] = field(default_factory=list)
    tangents: list[tuple[float, float, float]] = field(default_factory=list)
    uv_layers: list[list[tuple[float, float]]] = field(default_factory=list)
    raw_indices: list[int] = field(default_factory=list)
    triangles: list[tuple[int, int, int]] = field(default_factory=list)
    face_records: list[JadeFaceRecord] = field(default_factory=list)
    skin: JadeSkin | None = None
    runtime_generated: bool = False
    degenerate_triangle_count: int = 0
    invalid_triangle_count: int = 0
    empty_placeholder: bool = False

    @property
    def primitive_name(self) -> str:
        return PRIMITIVE_NAMES.get(self.primitive_type, f"unknown_{self.primitive_type}")

    @property
    def render(self) -> bool:
        return bool(self.flags & MESH_FLAG_RENDER)


@dataclass
class JadeNode:
    offset: int
    type_flags: int
    node_number_tree: int
    node_number_file: int
    name: str
    mdl_pointer: int
    parent_pointer: int
    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float]
    children_offset: int
    children_count_declared: int
    scale: float
    max_animation_distance: float
    mesh: JadeMesh | None = None
    payload_offsets: dict[str, int] = field(default_factory=dict)
    payload_bytes: dict[str, bytes] = field(default_factory=dict)
    controllers: JadeControllerSet | None = None
    specialized_payloads: dict[str, SpecializedPayload] = field(default_factory=dict)
    controller_context_flags: int = NODE_HEADER
    children: list["JadeNode"] = field(default_factory=list)

    @property
    def type_names(self) -> list[str]:
        names = [name for flag, name in NODE_FLAG_NAMES.items() if self.type_flags & flag]
        exact = EXACT_NODE_TYPE_NAMES.get(self.type_flags)
        if exact and exact not in names:
            names.append(exact)
        return names

    @property
    def class_name(self) -> str:
        return EXACT_NODE_TYPE_NAMES.get(self.type_flags, "compound_node")

    @property
    def controller_context_name(self) -> str:
        return controller_context_name(self.controller_context_flags)

    def iter_depth_first(self) -> Iterator["JadeNode"]:
        yield self
        for child in self.children:
            yield from child.iter_depth_first()


@dataclass
class JadeAnimationEvent:
    time: float
    name: str
    unknown: int


@dataclass
class JadeAnimation:
    offset: int
    geometry_name: str
    name: str
    length: float
    transition: float
    flag1: int
    flag2: int
    node_pointer: int
    node_count: int
    function_1: int = 0x0044ACA0
    function_2: int = 0x00495F40
    header_marker: int = 0
    animation_type: int = 5
    events: list[JadeAnimationEvent] = field(default_factory=list)
    root: JadeNode | None = None


@dataclass
class JadeModel:
    source_path: str
    mdx_path: str | None
    version: int
    mdl_size_declared: int
    mdx_vertices_size_declared: int
    mdx_faces_size_declared: int
    mdx_third_size_declared: int
    name: str
    root_node_offset: int
    node_count_declared: int
    model_type: int
    animation_array: ArrayDefinition
    bounding_min: tuple[float, float, float]
    bounding_max: tuple[float, float, float]
    radius: float
    scale: float
    supermodel: str
    names: list[str]
    root: JadeNode
    function_1: int = 0x0044FF10
    function_2: int = 0x0042F4B0
    header_marker: int = 0
    model_flags: int = 0x00010020
    model_marker: int = 1
    animations: list[JadeAnimation] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def iter_nodes(self) -> Iterator[JadeNode]:
        yield from self.root.iter_depth_first()

    def iter_animation_nodes(self) -> Iterator[JadeNode]:
        for animation in self.animations:
            if animation.root is not None:
                yield from animation.root.iter_depth_first()

    def statistics(self) -> dict[str, int]:
        nodes = list(self.iter_nodes())
        meshes = [node.mesh for node in nodes if node.mesh is not None]
        return {
            "nodes": len(nodes),
            "meshes": len(meshes),
            "skin_meshes": sum(1 for mesh in meshes if mesh and mesh.skin is not None),
            "vertices": sum(len(mesh.vertices) for mesh in meshes if mesh),
            "triangles": sum(len(mesh.triangles) for mesh in meshes if mesh),
            "animations": len(self.animations),
            "diagnostics": len(self.diagnostics),
        }

    def summary_dict(self, include_nodes: bool = True) -> dict:
        out = {
            "source_path": self.source_path,
            "mdx_path": self.mdx_path,
            "version": f"0x{self.version:08X}",
            "name": self.name,
            "supermodel": self.supermodel,
            "scale": self.scale,
            "bounds": {"min": self.bounding_min, "max": self.bounding_max, "radius": self.radius},
            "declared_sizes": {
                "mdl": self.mdl_size_declared,
                "mdx_vertices": self.mdx_vertices_size_declared,
                "mdx_faces": self.mdx_faces_size_declared,
                "mdx_third": self.mdx_third_size_declared,
            },
            "statistics": self.statistics(),
            "animations": [
                {
                    "name": anim.name,
                    "length": anim.length,
                    "transition": anim.transition,
                    "events": [asdict(event) for event in anim.events],
                    "nodes": 0 if anim.root is None else sum(1 for _ in anim.root.iter_depth_first()),
                    "controllers": 0
                    if anim.root is None
                    else sum(
                        len(node.controllers.descriptors)
                        for node in anim.root.iter_depth_first()
                        if node.controllers is not None
                    ),
                }
                for anim in self.animations
            ],
            "diagnostics": [asdict(diag) for diag in self.diagnostics],
        }
        if include_nodes:
            out["nodes"] = [
                {
                    "name": node.name,
                    "offset": f"0x{node.offset:X}",
                    "node_number_tree": node.node_number_tree,
                    "node_number_file": node.node_number_file,
                    "type_flags": f"0x{node.type_flags:08X}",
                    "types": node.type_names,
                    "position": node.position,
                    "orientation": node.orientation,
                    "scale": node.scale,
                    "children": len(node.children),
                    "mesh": None
                    if node.mesh is None
                    else {
                        "vertices": len(node.mesh.vertices),
                        "triangles": len(node.mesh.triangles),
                        "primitive": node.mesh.primitive_name,
                        "texture": node.mesh.texture,
                        "material_id": node.mesh.material_id,
                        "material_group_id": node.mesh.material_group_id,
                        "uv_layers": sum(bool(layer) for layer in node.mesh.uv_layers),
                        "skin": node.mesh.skin is not None,
                        "weighted_vertices": (
                            sum(bool(weights) for weights in node.mesh.skin.vertex_weights)
                            if node.mesh.skin is not None
                            else 0
                        ),
                        "degenerate_triangles": node.mesh.degenerate_triangle_count,
                        "invalid_triangles": node.mesh.invalid_triangle_count,
                    },
                }
                for node in self.iter_nodes()
            ]
        return out

    def summary_json(self, include_nodes: bool = True, indent: int = 2) -> str:
        return json.dumps(self.summary_dict(include_nodes=include_nodes), indent=indent)


class JadeMdlParser:
    """Parser for Jade Empire PC v7 binary MDL/MDX pairs."""

    def __init__(
        self,
        mdl_path: str | os.PathLike[str],
        mdx_path: str | os.PathLike[str] | None = None,
        *,
        strict: bool = False,
        max_nodes: int = 100_000,
    ):
        self.mdl_path = Path(mdl_path)
        self.mdx_path = Path(mdx_path) if mdx_path else self._find_mdx(self.mdl_path)
        self.strict = strict
        self.max_nodes = max_nodes
        self._mdl_bytes = self.mdl_path.read_bytes()
        self._mdx_bytes = (
            self.mdx_path.read_bytes()
            if self.mdx_path and self.mdx_path.exists()
            else b""
        )
        self.mdl = BinaryView(self._mdl_bytes, str(self.mdl_path))
        self.mdx = (
            BinaryView(self._mdx_bytes, str(self.mdx_path))
            if self._mdx_bytes
            else None
        )
        self.diagnostics: list[Diagnostic] = []
        self.names: list[str] = []
        self._visited: dict[int, JadeNode] = {}
        self._active_offsets: set[int] = set()
        self._static_context_by_name_index: dict[int, int] = {}
        self._expected_animation_node_count = 0

    @staticmethod
    def _find_mdx(mdl_path: Path) -> Path | None:
        # Retail RIM extraction uses resource type 0x0BC8 for Jade model
        # companion data.  JadeBlender extracts that as .mdx, but several
        # loose-file tools expose the same payload as .mdx2.  Treat both names
        # as aliases during import.
        for suffix in (".mdx", ".MDX", ".mdx2", ".MDX2"):
            candidate = mdl_path.with_suffix(suffix)
            if candidate.exists():
                return candidate
        try:
            stem = mdl_path.stem.casefold()
            for entry in mdl_path.parent.iterdir():
                if (
                    entry.is_file()
                    and entry.stem.casefold() == stem
                    and entry.suffix.casefold() in {".mdx", ".mdx2"}
                ):
                    return entry
        except OSError:
            pass
        return None

    def warn(self, message: str, *, offset: int | None = None, node: str | None = None) -> None:
        self.diagnostics.append(Diagnostic("warning", message, offset, node))

    def info(self, message: str, *, offset: int | None = None, node: str | None = None) -> None:
        self.diagnostics.append(Diagnostic("info", message, offset, node))

    def error(self, message: str, *, offset: int | None = None, node: str | None = None) -> None:
        diagnostic = Diagnostic("error", message, offset, node)
        self.diagnostics.append(diagnostic)
        if self.strict:
            raise ValueError(diagnostic.format())

    @staticmethod
    def _finite_tuple(values: Iterable[float]) -> bool:
        return all(math.isfinite(value) for value in values)

    def _abs(self, relative_offset: int, context: str) -> int:
        absolute = MODEL_DATA_OFFSET + relative_offset
        if relative_offset < 0 or absolute < MODEL_DATA_OFFSET or absolute > len(self.mdl):
            raise BinaryBoundsError(
                f"{self.mdl.label}: invalid relative pointer 0x{relative_offset:X} for {context}"
            )
        return absolute

    def _array_u32(self, definition: ArrayDefinition, context: str) -> list[int]:
        if definition.count == 0:
            return []
        if definition.count > self.max_nodes * 4:
            raise ValueError(f"Unreasonable {context} count: {definition.count}")
        absolute = self._abs(definition.offset, context)
        self.mdl.check(absolute, definition.count * 4, context)
        return [self.mdl.u32(absolute + i * 4, context) for i in range(definition.count)]

    def parse(self) -> JadeModel:
        if len(self.mdl) < MODEL_DATA_OFFSET + MODEL_HEADER_SIZE:
            raise ValueError("MDL is too short to contain a Jade model header")

        version = self.mdl.u32_be(0, "Jade MDL magic/version")
        if version != JADE_PC_V7_MAGIC:
            raise ValueError(
                f"Unsupported Jade MDL version 0x{version:08X}; expected PC v7 0x{JADE_PC_V7_MAGIC:08X}"
            )

        mdl_size = self.mdl.u32(4, "MDL size")
        mdx_vertices_size = self.mdl.u32(8, "MDX vertex size")
        mdx_faces_size = self.mdl.u32(12, "MDX face size")
        mdx_third_size = self.mdl.u32(16, "MDX third size")
        actual_mdl_size = len(self.mdl) - MODEL_DATA_OFFSET
        if mdl_size != actual_mdl_size:
            self.warn(
                f"Declared MDL data size {mdl_size} differs from actual {actual_mdl_size}",
                offset=4,
            )
        expected_mdx_size = mdx_vertices_size + mdx_faces_size + mdx_third_size
        if self.mdx is None:
            if expected_mdx_size:
                self.warn("Companion MDX was not found; hierarchy will load without vertex buffers")
        elif expected_mdx_size and expected_mdx_size != len(self.mdx):
            self.warn(
                f"Declared MDX parts total {expected_mdx_size}, actual MDX size is {len(self.mdx)}"
            )
        if mdx_third_size:
            self.warn(f"Non-zero third MDX section ({mdx_third_size} bytes) is not interpreted")

        header = MODEL_DATA_OFFSET
        function_1 = self.mdl.u32(header, "model function 1")
        function_2 = self.mdl.u32(header + 4, "model function 2")
        name = self.mdl.c_string_fixed(header + 0x08, 32, "model name")
        root_node_offset = self.mdl.u32(header + 0x28, "root node pointer")
        node_count = self.mdl.u32(header + 0x2C, "node count")
        if node_count > self.max_nodes:
            raise ValueError(f"Unreasonable model node count: {node_count}")
        header_marker = self.mdl.u32(header + 0x48, "model header marker")
        model_type = self.mdl.u8(header + 0x4C, "model type")
        model_flags = self.mdl.u32(header + 0x50, "model flags")
        animation_array = self.mdl.array_definition(header + 0x58, "animation array")
        bounding_min = self.mdl.f32_tuple(header + 0x68, 3, "model minimum bounds")
        bounding_max = self.mdl.f32_tuple(header + 0x74, 3, "model maximum bounds")
        radius = self.mdl.f32(header + 0x80, "model radius")
        model_marker = self.mdl.u32(header + 0x84, "model marker")
        scale = self.mdl.f32(header + 0x88, "model scale")
        supermodel = self.mdl.c_string_fixed(header + 0x8C, 32, "supermodel name")
        name_array = self.mdl.array_definition(header + 0xC0, "node name array")
        self.names = self._read_names(name_array)

        if model_type not in (0, 2):
            self.warn(f"Unexpected geometry type {model_type}; parsing as a model", offset=header + 0x4C)
        if not self._finite_tuple((*bounding_min, *bounding_max, radius, scale)):
            self.warn("Model bounds or scale contain non-finite values")

        root = self._parse_node(root_node_offset, parent=None, depth=0)
        parsed_count = len(self._visited)
        if node_count and parsed_count != node_count:
            self.warn(f"Header declares {node_count} nodes but hierarchy reached {parsed_count}")

        # Animation nodes carry only the controller-wrapper node flag.  Jade's
        # ASCII/binary parser selects a controller ID table by the corresponding
        # static hierarchy node class, keyed by the shared name-table index.
        static_nodes = list(root.iter_depth_first())
        self._static_context_by_name_index = {
            node.node_number_file: node.type_flags for node in static_nodes
        }
        # Reverse-engineered PC v7 semantics: animation-header node_count is
        # the size of a model-wide controller lookup table, not the number of
        # nodes reachable from that individual animation root.  Collision
        # nodes are omitted from that table.
        self._expected_animation_node_count = sum(
            1 for node in static_nodes if not (node.type_flags & NODE_COLLISION)
        )

        animations = self._parse_animations(animation_array)
        model = JadeModel(
            source_path=str(self.mdl_path),
            mdx_path=str(self.mdx_path) if self.mdx_path else None,
            version=version,
            mdl_size_declared=mdl_size,
            mdx_vertices_size_declared=mdx_vertices_size,
            mdx_faces_size_declared=mdx_faces_size,
            mdx_third_size_declared=mdx_third_size,
            name=name or self.mdl_path.stem,
            root_node_offset=root_node_offset,
            node_count_declared=node_count,
            model_type=model_type,
            animation_array=animation_array,
            bounding_min=bounding_min,
            bounding_max=bounding_max,
            radius=radius,
            scale=scale,
            supermodel=supermodel,
            names=self.names,
            root=root,
            function_1=function_1,
            function_2=function_2,
            header_marker=header_marker,
            model_flags=model_flags,
            model_marker=model_marker,
            animations=animations,
            diagnostics=self.diagnostics,
        )
        return model

    def _read_names(self, definition: ArrayDefinition) -> list[str]:
        offsets = self._array_u32(definition, "node name pointer array")
        names: list[str] = []
        for index, relative in enumerate(offsets):
            try:
                names.append(self.mdl.c_string(self._abs(relative, f"node name {index}"), 1024))
            except (BinaryBoundsError, ValueError) as exc:
                self.error(str(exc), offset=MODEL_DATA_OFFSET + relative)
                names.append(f"node_{index:04d}")
        return names

    def _parse_node(
        self,
        relative_offset: int,
        parent: JadeNode | None,
        depth: int,
        controller_context_by_name_index: dict[int, int] | None = None,
    ) -> JadeNode:
        if depth > 1024:
            raise ValueError("Node hierarchy exceeds the 1024-level safety limit")
        if relative_offset in self._active_offsets:
            raise ValueError(f"Cycle in node hierarchy at relative offset 0x{relative_offset:X}")
        if relative_offset in self._visited:
            existing = self._visited[relative_offset]
            self.warn(
                f"Node pointer 0x{relative_offset:X} is referenced more than once; reusing first instance",
                node=existing.name,
            )
            return existing
        if len(self._visited) >= self.max_nodes:
            raise ValueError(f"Node safety limit ({self.max_nodes}) exceeded")

        absolute = self._abs(relative_offset, "node")
        self.mdl.check(absolute, NODE_HEADER_SIZE, "node header")
        flags = self.mdl.u32(absolute, "node flags")
        invalid_bits = flags & ~KNOWN_SERIALIZED_NODE_BITS
        if invalid_bits:
            self.error(
                f"Node uses bits outside Jade PC v7's traced serialized mask: 0x{invalid_bits:08X}",
                offset=absolute,
            )
        node_number_tree = self.mdl.u16(absolute + 4, "tree node number")
        node_number_file = self.mdl.u16(absolute + 6, "file node number/name index")
        name = (
            self.names[node_number_file]
            if node_number_file < len(self.names)
            else f"node_{node_number_file:04d}"
        )
        if node_number_file >= len(self.names):
            self.warn(
                f"Node name index {node_number_file} is outside name table ({len(self.names)})",
                offset=absolute + 6,
                node=name,
            )
        mdl_pointer = self.mdl.u32(absolute + 8, "node MDL pointer")
        parent_pointer = self.mdl.u32(absolute + 12, "node parent pointer")
        position = self.mdl.f32_tuple(absolute + 16, 3, "node position")
        orientation = self.mdl.f32_tuple(absolute + 28, 4, "node quaternion")
        children_offset = self.mdl.u32(absolute + 44, "children pointer")
        children_count = self.mdl.u32(absolute + 48, "children count")
        scale = self.mdl.f32(absolute + 52, "node scale")
        max_anim_distance = self.mdl.f32(absolute + 56, "maximum animation distance")

        if not self._finite_tuple((*position, *orientation, scale, max_anim_distance)):
            self.warn("Node transform contains non-finite values", offset=absolute, node=name)
        quat_length = math.sqrt(sum(value * value for value in orientation if math.isfinite(value)))
        if quat_length == 0.0:
            self.warn("Zero-length node quaternion; importer will use identity", offset=absolute + 28, node=name)
        elif abs(quat_length - 1.0) > 0.05:
            self.warn(
                f"Node quaternion length is {quat_length:.4f}; importer will normalize it",
                offset=absolute + 28,
                node=name,
            )
        if children_count > self.max_nodes:
            raise ValueError(f"Unreasonable child count {children_count} in node {name}")

        controller_context_flags = flags
        if controller_context_by_name_index is not None:
            controller_context_flags = controller_context_by_name_index.get(
                node_number_file, NODE_HEADER
            )

        node = JadeNode(
            offset=relative_offset,
            type_flags=flags,
            node_number_tree=node_number_tree,
            node_number_file=node_number_file,
            name=name,
            mdl_pointer=mdl_pointer,
            parent_pointer=parent_pointer,
            position=position,
            orientation=orientation,
            children_offset=children_offset,
            children_count_declared=children_count,
            scale=scale,
            max_animation_distance=max_anim_distance,
            controller_context_flags=controller_context_flags,
        )
        self._visited[relative_offset] = node
        self._active_offsets.add(relative_offset)

        payload_absolute = absolute + NODE_HEADER_SIZE
        for payload_name, payload_size in payload_layout_for_flags(flags):
            try:
                self.mdl.check(
                    payload_absolute,
                    payload_size,
                    f"{payload_name} payload for {name}",
                )
                node.payload_offsets[payload_name] = payload_absolute - MODEL_DATA_OFFSET
                node.payload_bytes[payload_name] = self.mdl.bytes(
                    payload_absolute,
                    payload_size,
                    f"{payload_name} payload for {name}",
                )
                if payload_name == "mesh":
                    node.mesh = self._parse_mesh(payload_absolute, name, flags)
                elif payload_name == "controllers":
                    node.controllers = self._parse_controller_set(
                        payload_absolute,
                        name,
                        controller_context_flags,
                    )
                else:
                    semantic = parse_specialized_payload(
                        payload_name,
                        self.mdl,
                        payload_absolute,
                        self._abs,
                    )
                    if semantic is not None:
                        node.specialized_payloads[payload_name] = semantic
            except (BinaryBoundsError, ValueError) as exc:
                self.error(
                    f"Could not parse {payload_name} payload: {exc}",
                    offset=payload_absolute,
                    node=name,
                )
            payload_absolute += payload_size

        child_offsets: list[int] = []
        if children_count:
            try:
                child_array_absolute = self._abs(children_offset, f"children of {name}")
                self.mdl.check(child_array_absolute, children_count * 4, f"children of {name}")
                child_offsets = [
                    self.mdl.u32(child_array_absolute + index * 4, f"child pointer {index} of {name}")
                    for index in range(children_count)
                ]
            except (BinaryBoundsError, ValueError) as exc:
                self.error(str(exc), offset=MODEL_DATA_OFFSET + children_offset, node=name)

        for child_offset in child_offsets:
            try:
                child = self._parse_node(
                    child_offset,
                    node,
                    depth + 1,
                    controller_context_by_name_index,
                )
                if child not in node.children:
                    node.children.append(child)
            except (BinaryBoundsError, ValueError) as exc:
                self.error(str(exc), offset=MODEL_DATA_OFFSET + child_offset, node=name)

        self._active_offsets.discard(relative_offset)
        return node

    def _parse_controller_set(
        self,
        absolute: int,
        node_name: str,
        context_flags: int,
    ) -> JadeControllerSet:
        """Parse a complete PC v7 controller block using traced dispatch IDs."""

        self.mdl.check(absolute, CONTROLLER_HEADER_SIZE, "controller header")
        controller_type = self.mdl.u32(absolute, "controller header type")
        descriptor_array = self.mdl.array_definition(
            absolute + 4, "controller descriptor array"
        )
        timekey_offset = self.mdl.u32(absolute + 16, "controller time-key pointer")
        timekey_count = self.mdl.u32(absolute + 20, "controller time-key count")
        data_offset = self.mdl.u32(absolute + 24, "controller data pointer")
        data_count = self.mdl.u32(absolute + 28, "controller data dword count")
        tail_value = self.mdl.u32(absolute + 32, "controller header tail value")

        if descriptor_array.count > 100_000:
            raise ValueError(
                f"Unreasonable controller descriptor count {descriptor_array.count}"
            )
        if timekey_count > 10_000_000 or data_count > 100_000_000:
            raise ValueError(
                f"Unreasonable controller stream sizes ({timekey_count} keys, {data_count} dwords)"
            )
        # PC v7 controller blocks usually store 6 here, but retail facial
        # animation blocks use other small values for morph/face-channel
        # grouping.  Preserve the value for round-trip export instead of
        # treating it as a strict sentinel.
        if tail_value != 6:
            self.info(
                f"Controller header tail value is {tail_value}; preserving retail morph/controller group value",
                offset=absolute + 32,
                node=node_name,
            )

        descriptor_absolute = (
            self._abs(descriptor_array.offset, f"controller descriptors for {node_name}")
            if descriptor_array.count
            else 0
        )
        timekey_absolute = (
            self._abs(timekey_offset, f"controller time keys for {node_name}")
            if timekey_count
            else 0
        )
        data_absolute = (
            self._abs(data_offset, f"controller data for {node_name}")
            if data_count
            else 0
        )
        if descriptor_array.count:
            self.mdl.check(
                descriptor_absolute,
                descriptor_array.count * CONTROLLER_DESCRIPTOR_SIZE,
                f"controller descriptors for {node_name}",
            )
        if timekey_count:
            self.mdl.check(
                timekey_absolute,
                timekey_count * 2,
                f"controller time keys for {node_name}",
            )
        if data_count:
            self.mdl.check(
                data_absolute,
                data_count * 4,
                f"controller data for {node_name}",
            )

        time_keys = [
            self.mdl.u16(timekey_absolute + index * 2, "controller time key")
            for index in range(timekey_count)
        ]
        data_words = [
            self.mdl.u32(data_absolute + index * 4, "controller data word")
            for index in range(data_count)
        ]
        controller_set = JadeControllerSet(
            header_offset=absolute - MODEL_DATA_OFFSET,
            controller_type=controller_type,
            descriptor_offset=descriptor_array.offset,
            descriptor_count=descriptor_array.count,
            descriptor_capacity=descriptor_array.capacity,
            timekey_offset=timekey_offset,
            timekey_count=timekey_count,
            data_offset=data_offset,
            data_count=data_count,
            tail_value=tail_value,
            time_keys_raw=time_keys,
            data_words=data_words,
            raw_header=self.mdl.bytes(
                absolute, CONTROLLER_HEADER_SIZE, "controller header"
            ),
        )

        for index in range(descriptor_array.count):
            descriptor_absolute_entry = descriptor_absolute + index * CONTROLLER_DESCRIPTOR_SIZE
            controller_id = self.mdl.u32(
                descriptor_absolute_entry, "controller ID"
            )
            auxiliary = self.mdl.i16(
                descriptor_absolute_entry + 4, "controller auxiliary"
            )
            value_count = self.mdl.u16(
                descriptor_absolute_entry + 6, "controller value count"
            )
            timekey_start = self.mdl.u16(
                descriptor_absolute_entry + 8, "controller time-key start"
            )
            data_start = self.mdl.u16(
                descriptor_absolute_entry + 10, "controller data start"
            )
            data_type = self.mdl.u8(
                descriptor_absolute_entry + 12, "controller storage type"
            )
            tail = self.mdl.bytes(
                descriptor_absolute_entry + 13, 3, "controller descriptor tail"
            )

            semantic_name = controller_name(controller_id, context_flags)
            if semantic_name is None:
                context = controller_context_name(context_flags)
                self.error(
                    f"Controller ID 0x{controller_id:03X} is invalid for traced {context} dispatch",
                    offset=descriptor_absolute_entry,
                    node=node_name,
                )
                semantic_name = f"invalid_0x{controller_id:03X}"
            row_words = words_per_row(data_type)
            if row_words is None:
                self.error(
                    f"Controller storage tag 0x{data_type:02X} is not accepted by Jade's loader",
                    offset=descriptor_absolute_entry + 12,
                    node=node_name,
                )
                # Keep the descriptor structurally available in tolerant mode.
                row_words = 0

            descriptor = JadeControllerDescriptor(
                controller_id=controller_id,
                auxiliary=auxiliary,
                value_count=value_count,
                timekey_start=timekey_start,
                data_start=data_start,
                data_type=data_type,
                tail_bytes=tail,
                semantic_name=semantic_name,
                context_flags=context_flags,
                raw_offset=descriptor_absolute_entry - MODEL_DATA_OFFSET,
            )
            if data_type in DATA_TYPE_NAMES and not validate_descriptor_auxiliary(descriptor):
                self.error(
                    f"Controller {semantic_name} has auxiliary {auxiliary}, inconsistent with traced parser",
                    offset=descriptor_absolute_entry + 4,
                    node=node_name,
                )
            if timekey_start + value_count > len(time_keys):
                self.error(
                    f"Controller {semantic_name} time-key range exceeds the stream",
                    offset=descriptor_absolute_entry + 8,
                    node=node_name,
                )
            else:
                descriptor.time_keys_raw = time_keys[
                    timekey_start : timekey_start + value_count
                ]
            word_count = value_count * row_words
            if data_start + word_count > len(data_words):
                self.error(
                    f"Controller {semantic_name} data range exceeds the stream",
                    offset=descriptor_absolute_entry + 10,
                    node=node_name,
                )
            else:
                descriptor.data_words = data_words[data_start : data_start + word_count]
                if row_words:
                    descriptor.decoded_rows = [
                        decode_controller_row(
                            data_type,
                            descriptor.data_words[row : row + row_words],
                        )
                        for row in range(0, word_count, row_words)
                    ]
                    if not all(finite_decoded_row(row) for row in descriptor.decoded_rows):
                        self.warn(
                            f"Controller {semantic_name} contains non-finite float data",
                            offset=descriptor_absolute_entry,
                            node=node_name,
                        )
            controller_set.descriptors.append(descriptor)

        return controller_set

    def _parse_mesh(self, absolute: int, node_name: str, node_flags: int) -> JadeMesh:
        self.mdl.check(absolute, MESH_HEADER_SIZE, "mesh header")
        face_array = self.mdl.array_definition(absolute, "mesh face array")
        bounding_min = self.mdl.f32_tuple(absolute + 12, 3, "mesh minimum bounds")
        bounding_max = self.mdl.f32_tuple(absolute + 24, 3, "mesh maximum bounds")
        radius = self.mdl.f32(absolute + 36, "mesh radius")
        average = self.mdl.f32_tuple(absolute + 40, 3, "mesh average")
        transparency = self.mdl.u32(absolute + 52, "mesh transparency")
        flags = self.mdl.u16(absolute + 56, "mesh flags")
        shadow = bool(self.mdl.u16(absolute + 58, "mesh shadow"))
        texture = self.mdl.c_string_fixed(absolute + 60, 32, "mesh texture").strip()
        if texture.upper() == "NULL":
            texture = ""
        index_count = self.mdl.u32(absolute + 92, "mesh index count")
        face_offset_mdl = self.mdl.u32(absolute + 96, "mesh MDL index pointer")
        primitive_type = self.mdl.u32(absolute + 104, "mesh primitive type")
        mdx_stride = self.mdl.u32(absolute + 120, "MDX vertex stride")
        vertex_flags = self.mdl.u32(absolute + 124, "MDX vertex flags")
        position_offset = self.mdl.i32(absolute + 128, "MDX position offset")
        normal_offset = self.mdl.i32(absolute + 132, "MDX normal offset")
        color_offset = self.mdl.i32(absolute + 136, "MDX color offset")
        uv_offsets = [self.mdl.i32(absolute + 140 + i * 4, f"MDX UV{i + 1} offset") for i in range(4)]
        tangent_offset = self.mdl.i32(absolute + 156, "MDX tangent offset")
        extra_offsets = [self.mdl.i32(absolute + 160 + i * 4, f"MDX extra offset {i}") for i in range(4)]
        vertex_count = self.mdl.u16(absolute + 176, "mesh vertex count")
        texture_count = min(self.mdl.u16(absolute + 178, "mesh texture count"), 4)
        vertex_offset_mdx = self.mdl.u32(absolute + 180, "MDX vertex buffer pointer")
        material_id = self.mdl.i32(absolute + 188, "mesh material ID")
        material_group_id = self.mdl.u32(absolute + 192, "mesh material group ID")
        self_illumination = self.mdl.f32_tuple(absolute + 196, 3, "mesh self illumination")
        alpha = self.mdl.f32(absolute + 208, "mesh alpha")
        texture_w = self.mdl.f32(absolute + 212, "mesh texture W coordinate")
        face_offset_mdx = self.mdl.u32(absolute + 220, "mesh MDX face pointer")
        mdx_face_size = self.mdl.u32(absolute + 224, "mesh MDX face size")

        mesh = JadeMesh(
            header_offset=absolute - MODEL_DATA_OFFSET,
            face_array=face_array,
            bounding_min=bounding_min,
            bounding_max=bounding_max,
            radius=radius,
            average=average,
            transparency=transparency,
            flags=flags,
            shadow=shadow,
            texture=texture,
            index_count_declared=index_count,
            face_offset_mdl=face_offset_mdl,
            primitive_type=primitive_type,
            mdx_stride=mdx_stride,
            vertex_flags=vertex_flags,
            position_offset=position_offset,
            normal_offset=normal_offset,
            color_offset=color_offset,
            uv_offsets=uv_offsets,
            tangent_offset=tangent_offset,
            extra_offsets=extra_offsets,
            vertex_count_declared=vertex_count,
            texture_count=texture_count,
            vertex_offset_mdx=vertex_offset_mdx,
            material_id=material_id,
            material_group_id=material_group_id,
            self_illumination=self_illumination,
            alpha=alpha,
            texture_w=texture_w,
            face_offset_mdx=face_offset_mdx,
            mdx_face_size=mdx_face_size,
        )

        # Motion-trail nodes in retail Jade assets declare four logical
        # vertices but contain no static vertex/index buffers.  The renderer
        # generates their geometry at runtime.  They are valid special meshes,
        # not damaged zero-stride vertex streams.
        mesh.runtime_generated = bool(
            node_flags & NODE_WEAPON_TRAIL
            and vertex_count > 0
            and mdx_stride == 0
            and index_count == 0
            and face_offset_mdl == 0
            and face_offset_mdx == 0
        )
        # A small set of retail environment models contains empty mesh markers
        # whose absent MDX record is encoded as unsigned -1.  The zero vertex
        # and index counts make this an explicit tail_value, not a huge stride.
        mesh.empty_placeholder = bool(
            vertex_count == 0
            and index_count == 0
            and mdx_stride == 0xFFFFFFFF
            and vertex_offset_mdx == 0
            and face_offset_mdl == 0
            and face_offset_mdx == 0
        )

        if primitive_type not in PRIMITIVE_NAMES:
            self.warn(f"Unknown primitive type {primitive_type}", offset=absolute + 104, node=node_name)
        elif primitive_type not in (3, 4, 5):
            self.warn(
                f"Primitive type {PRIMITIVE_NAMES[primitive_type]} cannot be represented as Blender faces",
                offset=absolute + 104,
                node=node_name,
            )
        if mdx_stride > 4096 and not mesh.empty_placeholder:
            message = f"Unreasonable MDX vertex stride {mdx_stride}"
            if vertex_count == 0:
                self.warn(message, offset=absolute + 120, node=node_name)
            else:
                self.error(message, offset=absolute + 120, node=node_name)
        if vertex_count and mdx_stride == 0 and not mesh.runtime_generated:
            message = "Vertex count is non-zero but MDX stride is zero"
            if node_flags in EXACT_NODE_TYPE_NAMES:
                self.warn(message, offset=absolute + 120, node=node_name)
            else:
                self.error(message, offset=absolute + 120, node=node_name)

        self._read_face_records(mesh, node_name)
        self._read_vertices(mesh, node_name)
        self._read_indices(mesh, node_name)
        (
            mesh.triangles,
            mesh.degenerate_triangle_count,
            mesh.invalid_triangle_count,
        ) = self._triangulate(
            mesh.raw_indices, primitive_type, len(mesh.vertices), node_name
        )

        if node_flags & NODE_SKIN:
            skin_absolute = absolute + MESH_HEADER_SIZE
            try:
                mesh.skin = self._parse_skin(skin_absolute, node_name)
                self._read_skin_weights(mesh, node_name)
            except (BinaryBoundsError, ValueError) as exc:
                self.error(f"Could not parse skin header: {exc}", offset=skin_absolute, node=node_name)
        return mesh

    def _read_face_records(self, mesh: JadeMesh, node_name: str) -> None:
        if mesh.face_array.count == 0:
            return
        if mesh.face_array.count > 10_000_000:
            self.error(f"Unreasonable face-record count {mesh.face_array.count}", node=node_name)
            return
        try:
            absolute = self._abs(mesh.face_array.offset, f"face records for {node_name}")
            self.mdl.check(absolute, mesh.face_array.count * FACE_RECORD_SIZE, "mesh face records")
            records: list[JadeFaceRecord] = []
            for index in range(mesh.face_array.count):
                base = absolute + index * FACE_RECORD_SIZE
                records.append(
                    JadeFaceRecord(
                        normal=self.mdl.f32_tuple(base, 3, "face normal"),
                        distance=self.mdl.f32(base + 12, "face distance"),
                        unknown1=self.mdl.u16(base + 16, "face unknown1"),
                        unknown2=self.mdl.u16(base + 18, "face unknown2"),
                        vertices=(
                            self.mdl.u16(base + 20, "face vertex 0"),
                            self.mdl.u16(base + 22, "face vertex 1"),
                            self.mdl.u16(base + 24, "face vertex 2"),
                        ),
                        unknown3=self.mdl.u16(base + 26, "face unknown3"),
                    )
                )
            mesh.face_records = records
        except (BinaryBoundsError, ValueError) as exc:
            self.error(f"Could not read face records: {exc}", node=node_name)

    def _valid_vertex_field(self, offset: int, size: int, stride: int) -> bool:
        return offset >= 0 and stride > 0 and offset + size <= stride

    @staticmethod
    def _signed_packed_component(value: int, bits: int) -> int:
        mask = (1 << bits) - 1
        value &= mask
        sign = 1 << (bits - 1)
        return value - (1 << bits) if value & sign else value

    @classmethod
    def _decode_packed_normal(cls, packed: int) -> tuple[float, float, float]:
        """Decode Jade's signed-normalized 11:11:10 MDX normal."""

        x = cls._signed_packed_component(packed, 11) / 1023.0
        y = cls._signed_packed_component(packed >> 11, 11) / 1023.0
        z = cls._signed_packed_component(packed >> 22, 10) / 511.0
        length = math.sqrt(x * x + y * y + z * z)
        if not math.isfinite(length) or length <= 1e-12:
            return (0.0, 0.0, 1.0)
        return (x / length, y / length, z / length)

    def _read_vertices(self, mesh: JadeMesh, node_name: str) -> None:
        if mesh.vertex_count_declared == 0:
            return
        if self.mdx is None:
            self.warn("Mesh vertex data requires the companion MDX", node=node_name)
            return
        stride = mesh.mdx_stride
        if stride <= 0:
            return
        position_offset = mesh.position_offset
        if not self._valid_vertex_field(position_offset, 12, stride):
            if self._valid_vertex_field(0, 12, stride):
                self.warn(
                    "Invalid position offset "
                    f"{position_offset}; using record offset 0 as observed "
                    "in the engine loader",
                    node=node_name,
                )
                position_offset = 0
            else:
                self.error("MDX record has no valid 12-byte position field", node=node_name)
                return
        total_size = mesh.vertex_count_declared * stride
        try:
            self.mdx.check(mesh.vertex_offset_mdx, total_size, f"vertex buffer for {node_name}")
        except BinaryBoundsError as exc:
            self.error(str(exc), offset=mesh.vertex_offset_mdx, node=node_name)
            return

        valid_uv_offsets = [
            offset if self._valid_vertex_field(offset, 8, stride) else None
            for offset in mesh.uv_offsets
        ]
        # Preserve semantic UV slots.  Retail models can contain UV1 and UV3
        # while UV2 is absent; compacting valid offsets relabels UV3 as UV2.
        mesh.uv_layers = [[] for _ in range(4)]
        read_normals = self._valid_vertex_field(mesh.normal_offset, 4, stride)
        read_colors = self._valid_vertex_field(mesh.color_offset, 4, stride)
        read_tangents = self._valid_vertex_field(mesh.tangent_offset, 12, stride)
        non_finite = 0
        for index in range(mesh.vertex_count_declared):
            base = mesh.vertex_offset_mdx + index * stride
            position = self.mdx.f32_tuple(base + position_offset, 3, "MDX position")
            if not self._finite_tuple(position):
                non_finite += 1
                position = tuple(0.0 if not math.isfinite(v) else v for v in position)
            mesh.vertices.append(position)
            if read_normals:
                packed_normal = self.mdx.u32(base + mesh.normal_offset, "packed MDX normal")
                mesh.raw_normal_values.append(packed_normal)
                mesh.normals.append(self._decode_packed_normal(packed_normal))
            if read_colors:
                blue, green, red, alpha = self.mdx.bytes(base + mesh.color_offset, 4, "MDX color")
                mesh.colors.append((red / 255.0, green / 255.0, blue / 255.0, alpha / 255.0))
            if read_tangents:
                tangent = self.mdx.f32_tuple(base + mesh.tangent_offset, 3, "MDX tangent")
                if self._finite_tuple(tangent):
                    # Tangents are authored float32 payloads. Normalizing them in
                    # the parser made parse -> rebuild -> parse non-idempotent and
                    # discarded magnitude/sign information used by some shaders.
                    # Consumers that require a unit tangent normalize at use time.
                    mesh.tangents.append(tangent)
                else:
                    mesh.tangents.append((1.0, 0.0, 0.0))
            for layer_index, uv_offset in enumerate(valid_uv_offsets):
                if uv_offset is None:
                    continue
                uv = self.mdx.f32_tuple(base + uv_offset, 2, "MDX UV")
                mesh.uv_layers[layer_index].append(
                    uv if self._finite_tuple(uv) else (0.0, 0.0)
                )
        if non_finite:
            self.warn(f"Replaced non-finite coordinates in {non_finite} vertices", node=node_name)
        if mesh.normal_offset >= 0 and not read_normals:
            self.warn(
                f"Packed normal offset {mesh.normal_offset} does not fit stride {stride}",
                node=node_name,
            )
        for offset in mesh.uv_offsets:
            if offset >= 0 and not self._valid_vertex_field(offset, 8, stride):
                self.warn(f"UV offset {offset} does not fit stride {stride}", node=node_name)
        if mesh.tangent_offset >= 0 and not read_tangents:
            self.warn(
                f"Tangent offset {mesh.tangent_offset} does not fit stride {stride}",
                node=node_name,
            )

    def _read_indices(self, mesh: JadeMesh, node_name: str) -> None:
        indices: list[int] = []
        if mesh.index_count_declared and mesh.face_offset_mdl:
            try:
                absolute = self._abs(mesh.face_offset_mdl, f"MDL indices for {node_name}")
                self.mdl.check(absolute, mesh.index_count_declared * 2, "plain MDL indices")
                indices = [
                    self.mdl.u16(absolute + i * 2, "plain MDL index")
                    for i in range(mesh.index_count_declared)
                ]
            except (BinaryBoundsError, ValueError) as exc:
                self.error(f"Could not read MDL indices: {exc}", node=node_name)
        elif mesh.index_count_declared and mesh.face_offset_mdx and self.mdx is not None:
            indices = self._read_chunked_indices(
                self.mdx, mesh.face_offset_mdx, mesh.index_count_declared, node_name
            )
        elif mesh.face_records:
            indices = [vertex for face in mesh.face_records for vertex in face.vertices]
            if mesh.index_count_declared:
                self.warn("Using face-record vertex IDs because render index data was unavailable", node=node_name)
        elif mesh.index_count_declared:
            self.warn("Mesh declares indices but neither MDL nor MDX index storage is available", node=node_name)
        mesh.raw_indices = indices

    def _read_chunked_indices(
        self, view: BinaryView, offset: int, count: int, node_name: str
    ) -> list[int]:
        try:
            view.check(offset, 8, "chunked index header")
            stop_value = view.u32(offset, "chunk stop value")
            cursor = offset + 8
            remaining = count
            indices: list[int] = []
            iterations = 0
            while remaining > 0:
                iterations += 1
                if iterations > 1_000_000:
                    raise ValueError("Chunked index iteration safety limit exceeded")
                view.check(cursor, 4, "chunk header")
                chunk = view.u32(cursor, "chunk header")
                cursor += 4
                if chunk == stop_value:
                    break
                chunk_length = ((chunk >> 16) & 0x1FFF) // 2
                if chunk_length == 0:
                    raise ValueError(f"Zero-length index chunk 0x{chunk:08X}")
                view.check(cursor, chunk_length * 2, "chunk index payload")
                to_read = min(chunk_length, remaining)
                indices.extend(view.u16(cursor + i * 2, "chunked index") for i in range(to_read))
                cursor += chunk_length * 2
                remaining -= to_read
            if remaining:
                self.warn(
                    f"Chunked index stream ended with {remaining} of {count} indices unread",
                    offset=offset,
                    node=node_name,
                )
            return indices
        except (BinaryBoundsError, ValueError) as exc:
            self.error(f"Could not read chunked MDX indices: {exc}", offset=offset, node=node_name)
            return []

    def _triangulate(
        self, indices: list[int], primitive_type: int, vertex_count: int, node_name: str
    ) -> tuple[list[tuple[int, int, int]], int, int]:
        triangles: list[tuple[int, int, int]] = []
        if primitive_type == 3:
            if len(indices) % 3:
                self.warn(
                    f"Triangle-list index count {len(indices)} is not divisible by three; trailing indices ignored",
                    node=node_name,
                )
            triangles = [tuple(indices[i : i + 3]) for i in range(0, len(indices) - 2, 3)]
        elif primitive_type == 4:
            for index in range(len(indices) - 2):
                if index & 1:
                    triangles.append((indices[index], indices[index + 2], indices[index + 1]))
                else:
                    triangles.append((indices[index], indices[index + 1], indices[index + 2]))
        elif primitive_type == 5 and len(indices) >= 3:
            triangles = [(indices[0], indices[i], indices[i + 1]) for i in range(1, len(indices) - 1)]
        else:
            return [], 0, 0

        valid: list[tuple[int, int, int]] = []
        degenerate = 0
        invalid = 0
        for triangle in triangles:
            if len(set(triangle)) < 3:
                degenerate += 1
                continue
            if vertex_count and any(vertex < 0 or vertex >= vertex_count for vertex in triangle):
                invalid += 1
                continue
            valid.append(triangle)
        # Degenerate triangles are normal strip stitching/restart markers.
        # Diagnose them only in a literal triangle list while retaining the
        # count for all primitive modes.
        if degenerate and primitive_type == 3:
            self.warn(f"Discarded {degenerate} degenerate triangles", node=node_name)
        if invalid:
            self.warn(f"Discarded {invalid} triangles with out-of-range vertex indices", node=node_name)
        return valid, degenerate, invalid

    def _parse_skin(self, absolute: int, node_name: str) -> JadeSkin:
        self.mdl.check(absolute, SKIN_HEADER_SIZE, "skin header")
        weights_offset = self.mdl.i32(absolute + 12, "skin MDX weights offset")
        mapping_id_offset = self.mdl.i32(absolute + 16, "skin MDX mapping ID offset")
        mapping_pointer = self.mdl.u32(absolute + 20, "skin bone mapping pointer")
        mapping_count = self.mdl.u32(absolute + 24, "skin bone mapping count")
        if mapping_count > 65536:
            raise ValueError(f"Unreasonable skin bone mapping count {mapping_count}")
        quats = self.mdl.array_definition(absolute + 28, "skin bone quaternions")
        vertices = self.mdl.array_definition(absolute + 40, "skin bone vertices")
        constants = self.mdl.array_definition(absolute + 52, "skin bone constants")
        bone_palette = [
            self.mdl.i16(absolute + 64 + i * 2, "skin bone palette entry")
            for i in range(48)
        ]
        mapping: list[int] = []
        if mapping_count and mapping_pointer:
            mapping_absolute = self._abs(mapping_pointer, f"bone mapping for {node_name}")
            self.mdl.check(mapping_absolute, mapping_count * 2, "skin bone mapping")
            mapping = [self.mdl.i16(mapping_absolute + i * 2, "skin bone mapping") for i in range(mapping_count)]

        def read_float_rows(
            definition: ArrayDefinition,
            width: int,
            label: str,
        ) -> list[tuple[float, ...]]:
            if definition.count == 0:
                return []
            if definition.count > self.max_nodes * 4:
                raise ValueError(f"Unreasonable {label} count {definition.count}")
            values_absolute = self._abs(definition.offset, f"{label} for {node_name}")
            self.mdl.check(values_absolute, definition.count * width * 4, label)
            return [
                self.mdl.f32_tuple(
                    values_absolute + index * width * 4,
                    width,
                    label,
                )
                for index in range(definition.count)
            ]

        quat_values = read_float_rows(quats, 4, "skin bone quaternions")
        vertex_values = read_float_rows(vertices, 3, "skin bone vertices")
        return JadeSkin(
            mdx_bone_weights_offset=weights_offset,
            mdx_bone_mapping_id_offset=mapping_id_offset,
            bone_mapping_offset=mapping_pointer,
            bone_mapping=mapping,
            bone_quats=quats,
            bone_vertices=vertices,
            bone_constants=constants,
            bone_quat_values=[tuple(value) for value in quat_values],
            bone_vertex_values=[tuple(value) for value in vertex_values],
            bone_palette=bone_palette,
        )

    @staticmethod
    def _decode_skin_palette_slot(raw_bone_id: int) -> int | None:
        """Decode Jade's sparse 16-bit skin ID into a 0..47 palette slot.

        Retail files use two arithmetic ranges.  The second wraps through the
        unsigned 16-bit space; treating the IDs as byte indices or signed
        shorts loses palette slots 17 through 47.
        """

        if 0x0012 <= raw_bone_id <= 0x0042 and (raw_bone_id - 0x0012) % 3 == 0:
            return (raw_bone_id - 0x0012) // 3
        if 0xFFA2 <= raw_bone_id <= 0xFFFC and (raw_bone_id - 0xFFA2) % 3 == 0:
            return 17 + (raw_bone_id - 0xFFA2) // 3
        return None

    def _read_skin_weights(self, mesh: JadeMesh, node_name: str) -> None:
        skin = mesh.skin
        if skin is None or mesh.vertex_count_declared == 0:
            return
        if self.mdx is None:
            self.warn("Skin weights require the companion MDX", node=node_name)
            return

        stride = mesh.mdx_stride
        if not self._valid_vertex_field(skin.mdx_bone_weights_offset, 16, stride):
            self.error(
                f"Skin weight field at {skin.mdx_bone_weights_offset} does not fit stride {stride}",
                node=node_name,
            )
            return
        if not self._valid_vertex_field(skin.mdx_bone_mapping_id_offset, 8, stride):
            self.error(
                f"Skin bone-ID field at {skin.mdx_bone_mapping_id_offset} does not fit stride {stride}",
                node=node_name,
            )
            return

        try:
            self.mdx.check(
                mesh.vertex_offset_mdx,
                mesh.vertex_count_declared * stride,
                f"skin vertex buffer for {node_name}",
            )
        except BinaryBoundsError as exc:
            self.error(str(exc), offset=mesh.vertex_offset_mdx, node=node_name)
            return

        invalid_ids = 0
        invalid_palette_entries = 0
        invalid_weights = 0
        non_unit_weight_sums = 0
        vertices_without_weights = 0
        for vertex_index in range(mesh.vertex_count_declared):
            base = mesh.vertex_offset_mdx + vertex_index * stride
            raw_weights = self.mdx.f32_tuple(
                base + skin.mdx_bone_weights_offset, 4, "skin bone weights"
            )
            raw_ids = tuple(
                self.mdx.u16(
                    base + skin.mdx_bone_mapping_id_offset + influence * 2,
                    "skin bone ID",
                )
                for influence in range(4)
            )
            skin.raw_weight_values.append(tuple(float(value) for value in raw_weights))
            skin.raw_bone_ids.append(raw_ids)

            positive_finite_sum = sum(
                float(weight)
                for weight in raw_weights
                if math.isfinite(float(weight)) and float(weight) > 0.0
            )
            if positive_finite_sum > 0.0 and abs(positive_finite_sum - 1.0) > 1e-4:
                non_unit_weight_sums += 1

            merged: dict[int, float] = {}
            for raw_id, raw_weight in zip(raw_ids, raw_weights):
                weight = float(raw_weight)
                if not math.isfinite(weight):
                    invalid_weights += 1
                    continue
                if weight <= 0.0:
                    continue
                slot = self._decode_skin_palette_slot(raw_id)
                if slot is None:
                    invalid_ids += 1
                    continue
                node_index = skin.bone_palette[slot]
                if node_index < 0 or node_index >= len(self.names):
                    invalid_palette_entries += 1
                    continue
                merged[node_index] = merged.get(node_index, 0.0) + weight
            decoded = list(merged.items())
            if not decoded:
                vertices_without_weights += 1
            skin.vertex_weights.append(decoded)

        if invalid_ids:
            self.warn(
                f"Ignored {invalid_ids} weighted influences with unknown encoded bone IDs",
                node=node_name,
            )
        if invalid_palette_entries:
            self.warn(
                f"Ignored {invalid_palette_entries} weighted influences whose palette entries do not name model nodes",
                node=node_name,
            )
        if invalid_weights:
            self.warn(
                f"Ignored {invalid_weights} non-finite skin weights",
                node=node_name,
            )
        if non_unit_weight_sums:
            self.warn(
                f"{non_unit_weight_sums} skin vertices have positive weights that do not sum to one",
                node=node_name,
            )
        if vertices_without_weights:
            self.warn(
                f"{vertices_without_weights} skin vertices have no decodable non-zero influences",
                node=node_name,
            )

    def _parse_animations(self, definition: ArrayDefinition) -> list[JadeAnimation]:
        if definition.count == 0:
            return []
        try:
            pointers = self._array_u32(definition, "animation pointer array")
        except (BinaryBoundsError, ValueError) as exc:
            self.error(f"Could not read animation pointer array: {exc}")
            return []
        animations: list[JadeAnimation] = []
        for relative in pointers:
            try:
                absolute = self._abs(relative, "animation header")
                self.mdl.check(absolute, 0x8C, "animation header")
                function_1 = self.mdl.u32(absolute, "animation function 1")
                function_2 = self.mdl.u32(absolute + 4, "animation function 2")
                geometry_name = self.mdl.c_string_fixed(absolute + 8, 32, "animation geometry name")
                node_pointer = self.mdl.u32(absolute + 0x28, "animation node pointer")
                node_count = self.mdl.u32(absolute + 0x2C, "animation node count")
                header_marker = self.mdl.u32(absolute + 0x48, "animation header marker")
                animation_type = self.mdl.u8(absolute + 0x4C, "animation type")
                length = self.mdl.f32(absolute + 0x50, "animation length")
                transition = self.mdl.f32(absolute + 0x54, "animation transition")
                flag1 = self.mdl.u8(absolute + 0x58, "animation flag1")
                flag2 = self.mdl.u8(absolute + 0x59, "animation flag2")
                name = self.mdl.c_string_fixed(absolute + 0x5A, 32, "animation name")
                event_array = self.mdl.array_definition(absolute + 0x7C, "animation event array")
                events = self._parse_animation_events(event_array, name)
                animation_root = None
                saved_visited = self._visited
                saved_active = self._active_offsets
                self._visited = {}
                self._active_offsets = set()
                try:
                    animation_root = self._parse_node(
                        node_pointer,
                        parent=None,
                        depth=0,
                        controller_context_by_name_index=self._static_context_by_name_index,
                    )
                    if node_count != self._expected_animation_node_count:
                        self.warn(
                            f"Animation {name or geometry_name} declares lookup-table size "
                            f"{node_count}; model hierarchy requires "
                            f"{self._expected_animation_node_count} non-collision nodes",
                            offset=absolute + 0x2C,
                        )
                    for animation_node in self._visited.values():
                        context_flags = self._static_context_by_name_index.get(
                            animation_node.node_number_file
                        )
                        if context_flags is None:
                            self.warn(
                                f"Animation node {animation_node.name or animation_node.node_number_file} "
                                "does not map to the static hierarchy",
                                offset=MODEL_DATA_OFFSET + animation_node.offset,
                            )
                        elif context_flags & NODE_COLLISION:
                            self.warn(
                                f"Animation node {animation_node.name or animation_node.node_number_file} "
                                "maps to a collision node excluded from Jade controller streams",
                                offset=MODEL_DATA_OFFSET + animation_node.offset,
                            )
                finally:
                    self._visited = saved_visited
                    self._active_offsets = saved_active
                animations.append(
                    JadeAnimation(
                        offset=relative,
                        geometry_name=geometry_name,
                        name=name or geometry_name,
                        length=length,
                        transition=transition,
                        flag1=flag1,
                        flag2=flag2,
                        node_pointer=node_pointer,
                        node_count=node_count,
                        function_1=function_1,
                        function_2=function_2,
                        header_marker=header_marker,
                        animation_type=animation_type,
                        events=events,
                        root=animation_root,
                    )
                )
            except (BinaryBoundsError, ValueError) as exc:
                self.error(f"Could not parse animation at 0x{relative:X}: {exc}")
        if animations:
            controller_count = sum(
                len(node.controllers.descriptors)
                for animation in animations
                if animation.root is not None
                for node in animation.root.iter_depth_first()
                if node.controllers is not None
            )
            self.info(
                f"Parsed {len(animations)} animation trees and {controller_count} traced controller keyframes/records"
            )
        return animations

    def _parse_animation_events(
        self, definition: ArrayDefinition, animation_name: str
    ) -> list[JadeAnimationEvent]:
        if definition.count == 0:
            return []
        if definition.count > 100_000:
            self.error(f"Unreasonable event count {definition.count} in animation {animation_name}")
            return []
        try:
            absolute = self._abs(definition.offset, f"events for {animation_name}")
            self.mdl.check(absolute, definition.count * 40, "animation events")
            return [
                JadeAnimationEvent(
                    time=self.mdl.f32(absolute + index * 40, "animation event time"),
                    name=self.mdl.c_string_fixed(
                        absolute + index * 40 + 4, 32, "animation event name"
                    ),
                    unknown=self.mdl.u32(
                        absolute + index * 40 + 36, "animation event unknown"
                    ),
                )
                for index in range(definition.count)
            ]
        except (BinaryBoundsError, ValueError) as exc:
            self.error(f"Could not parse events for animation {animation_name}: {exc}")
            return []


def is_jade_mdl(path: str | os.PathLike[str]) -> bool:
    """Return True when *path* begins with the Jade Empire PC v7 signature."""
    try:
        with open(path, "rb") as stream:
            header = stream.read(4)
    except OSError:
        return False
    return len(header) == 4 and int.from_bytes(header, "big") == JADE_PC_V7_MAGIC


def parse_jade_mdl(
    mdl_path: str | os.PathLike[str],
    mdx_path: str | os.PathLike[str] | None = None,
    *,
    strict: bool = False,
) -> JadeModel:
    return JadeMdlParser(mdl_path, mdx_path, strict=strict).parse()
