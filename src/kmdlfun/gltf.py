"""Reading a .glb (binary glTF) into a head pack.

glTF is the format most modern generators and asset sites hand out, and it
carries the texture inside the same file, so one download is a whole head. This
reads it directly rather than shelling out to Blender: the subset we need is a
JSON chunk, a binary chunk, and some strided accessors, and owning the reader
means the failure modes are ours to report rather than something to infer from a
converter's exit code.

It reads only what a head pack can express - positions, normals, the first UV
set, triangle indices, and the base-colour image - and **refuses loudly** on
anything else rather than silently dropping it. Skins, morph targets, animation
and second UV sets are all things a KOTOR head cannot carry anyway; a quiet drop
would leave someone wondering why their model came out wrong.

Axis convention: glTF is Y-up with -Z forward, KOTOR is Z-up facing +Y. Turning
the first into the second is exactly the `up: "y"` conversion in `headgen`, and
-Z then lands on +Y, so an imported head needs `facing: "+y"` and nothing else.
Those hints are written into the pack's manifest rather than baked into the
geometry, so they stay visible and adjustable.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

MAGIC = 0x46546C67          # "glTF"
CHUNK_JSON = 0x4E4F534A     # "JSON"
CHUNK_BIN = 0x004E4942      # "BIN\0"

COMPONENT = {
    5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2),
    5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4),
}
COUNTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
TRIANGLES = 4


class GltfError(Exception):
    """The file is not something a head pack can represent. Never guess."""


@dataclass
class ImportedMesh:
    positions: list = field(default_factory=list)
    normals: list = field(default_factory=list)
    uvs: list = field(default_factory=list)
    faces: list = field(default_factory=list)
    image: bytes | None = None          # the base-colour image, as stored
    image_mime: str = ""
    notes: list = field(default_factory=list)


def _chunks(raw: bytes):
    if len(raw) < 12:
        raise GltfError("file is too short to be a GLB")
    magic, version, total = struct.unpack_from("<III", raw, 0)
    if magic != MAGIC:
        raise GltfError(
            "not a binary glTF (.glb). A .gltf text file with separate buffers "
            "is not supported - re-export as .glb"
        )
    if version != 2:
        raise GltfError(f"glTF version {version}; only version 2 is supported")
    if total != len(raw):
        raise GltfError(f"header says {total} bytes, file is {len(raw)}")

    at, out = 12, {}
    while at + 8 <= len(raw):
        length, kind = struct.unpack_from("<II", raw, at)
        at += 8
        out.setdefault(kind, raw[at : at + length])
        at += length + (-length % 4)
    if CHUNK_JSON not in out:
        raise GltfError("no JSON chunk")
    return json.loads(out[CHUNK_JSON].decode("utf-8")), out.get(CHUNK_BIN, b"")


def _accessor(doc, blob: bytes, index: int) -> np.ndarray:
    acc = doc["accessors"][index]
    if "sparse" in acc:
        raise GltfError("sparse accessors are not supported")
    fmt, size = COMPONENT[acc["componentType"]]
    per = COUNTS[acc["type"]]
    count = acc["count"]

    if "bufferView" not in acc:
        return np.zeros((count, per), dtype=np.float64)
    view = doc["bufferViews"][acc["bufferView"]]
    if doc["buffers"][view.get("buffer", 0)].get("uri"):
        raise GltfError(
            "the mesh data lives in a separate file, not inside the .glb. "
            "Re-export with buffers embedded"
        )
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride") or size * per

    out = np.empty((count, per), dtype=np.float64)
    for i in range(count):
        at = start + i * stride
        out[i] = struct.unpack_from("<" + fmt * per, blob, at)
    return out


def _node_matrix(node) -> np.ndarray:
    if "matrix" in node:
        return np.asarray(node["matrix"], dtype=np.float64).reshape(4, 4).T
    m = np.eye(4)
    if "scale" in node:
        m[:3, :3] = np.diag(node["scale"]) @ m[:3, :3]
    if "rotation" in node:
        x, y, z, w = node["rotation"]          # glTF stores xyzw
        r = np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ])
        m[:3, :3] = r @ m[:3, :3]
    if "translation" in node:
        m[:3, 3] = node["translation"]
    return m


def _base_colour_image(doc, blob: bytes, material_index: int | None):
    """The base-colour texture, as stored bytes plus its mime type."""
    if material_index is None or "materials" not in doc:
        return None, ""
    mat = doc["materials"][material_index]
    pbr = mat.get("pbrMetallicRoughness", {})
    tex_ref = pbr.get("baseColorTexture")
    if not tex_ref:
        return None, ""
    tex = doc["textures"][tex_ref["index"]]
    if "source" not in tex:
        return None, ""
    image = doc["images"][tex["source"]]
    if "bufferView" not in image:
        return None, ""
    view = doc["bufferViews"][image["bufferView"]]
    start = view.get("byteOffset", 0)
    return blob[start : start + view["byteLength"]], image.get("mimeType", "")


def read_glb(path: str | Path) -> ImportedMesh:
    """Read every triangle primitive in a .glb into one mesh, posed."""
    raw = Path(path).read_bytes()
    doc, blob = _chunks(raw)
    out = ImportedMesh()

    # Walk the scene so node transforms are applied; a generator often exports
    # the head rotated or scaled at the node rather than in the vertex data.
    world: list[tuple[int, np.ndarray]] = []
    nodes = doc.get("nodes", [])
    scene = doc.get("scenes", [{}])[doc.get("scene", 0)]
    stack = [(i, np.eye(4)) for i in scene.get("nodes", range(len(nodes)))]
    while stack:
        index, parent = stack.pop()
        node = nodes[index]
        matrix = parent @ _node_matrix(node)
        if "mesh" in node:
            world.append((node["mesh"], matrix))
        for child in node.get("children", []):
            stack.append((child, matrix))
    if not world:
        raise GltfError("no mesh in the file's scene")

    material_index = None
    skipped = 0
    for mesh_index, matrix in world:
        for prim in doc["meshes"][mesh_index].get("primitives", []):
            if prim.get("mode", TRIANGLES) != TRIANGLES:
                skipped += 1
                continue
            if "extensions" in prim and "KHR_draco_mesh_compression" in prim["extensions"]:
                raise GltfError(
                    "the mesh is Draco-compressed; re-export without compression"
                )
            attrs = prim["attributes"]
            if "POSITION" not in attrs:
                continue
            base = len(out.positions)

            pos = _accessor(doc, blob, attrs["POSITION"])
            homogeneous = np.hstack([pos, np.ones((len(pos), 1))])
            out.positions.extend(
                tuple(float(c) for c in p) for p in (homogeneous @ matrix.T)[:, :3]
            )

            if "NORMAL" in attrs:
                normal_matrix = np.linalg.inv(matrix[:3, :3]).T
                n = _accessor(doc, blob, attrs["NORMAL"]) @ normal_matrix.T
                lengths = np.linalg.norm(n, axis=1)
                lengths[lengths < 1e-12] = 1.0
                out.normals.extend(tuple(float(c) for c in v) for v in n / lengths[:, None])
            elif out.normals:
                out.normals.extend([(0.0, 0.0, 1.0)] * len(pos))

            if "TEXCOORD_0" in attrs:
                out.uvs.extend(
                    tuple(float(c) for c in uv)
                    for uv in _accessor(doc, blob, attrs["TEXCOORD_0"])
                )
            elif out.uvs:
                out.uvs.extend([(0.0, 0.0)] * len(pos))

            if "indices" in prim:
                idx = _accessor(doc, blob, prim["indices"]).reshape(-1).astype(np.int64)
            else:
                idx = np.arange(len(pos), dtype=np.int64)
            for i in range(0, len(idx) - 2, 3):
                out.faces.append(
                    (base + int(idx[i]), base + int(idx[i + 1]), base + int(idx[i + 2]))
                )

            if material_index is None:
                material_index = prim.get("material")

    if not out.faces:
        raise GltfError("no triangles found")
    if skipped:
        out.notes.append(f"{skipped} non-triangle primitive(s) skipped")
    if out.normals and len(out.normals) != len(out.positions):
        out.normals = []
        out.notes.append("normals were incomplete and have been dropped")
    if out.uvs and len(out.uvs) != len(out.positions):
        out.uvs = []
        out.notes.append("texture coordinates were incomplete and have been dropped")

    for present, what in (
        ("skins", "skinning"), ("animations", "animation"),
    ):
        if doc.get(present):
            out.notes.append(f"the file's {what} was ignored; a head pack has none")

    out.image, out.image_mime = _base_colour_image(doc, blob, material_index)
    return out
