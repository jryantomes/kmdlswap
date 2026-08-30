"""Reading .glb, and refusing what a head pack cannot represent.

Everything here builds a GLB in memory rather than shipping a fixture, so the
expected answer is known exactly and the tests say what the format is.
"""

from __future__ import annotations

import json
import struct

import numpy as np
import pytest

from kmdlfun import gltf


def build_glb(doc: dict, blob: bytes = b"", *, magic=gltf.MAGIC, version=2) -> bytes:
    js = json.dumps(doc).encode("utf-8")
    js += b" " * (-len(js) % 4)
    blob = blob + b"\0" * (-len(blob) % 4)
    total = 12 + 8 + len(js) + (8 + len(blob) if blob else 0)
    out = struct.pack("<III", magic, version, total)
    out += struct.pack("<II", len(js), gltf.CHUNK_JSON) + js
    if blob:
        out += struct.pack("<II", len(blob), gltf.CHUNK_BIN) + blob
    return out


def simple(positions, faces, uvs=None, node=None, extra=None):
    pos = np.asarray(positions, dtype=np.float32)
    idx = np.asarray(faces, dtype=np.uint32).reshape(-1)
    blob = pos.tobytes() + idx.tobytes()
    views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": pos.nbytes},
        {"buffer": 0, "byteOffset": pos.nbytes, "byteLength": idx.nbytes},
    ]
    accessors = [
        {"bufferView": 0, "componentType": 5126, "count": len(pos), "type": "VEC3"},
        {"bufferView": 1, "componentType": 5125, "count": len(idx), "type": "SCALAR"},
    ]
    attrs = {"POSITION": 0}
    if uvs is not None:
        uv = np.asarray(uvs, dtype=np.float32)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": uv.nbytes})
        accessors.append(
            {"bufferView": 2, "componentType": 5126, "count": len(uv), "type": "VEC2"}
        )
        attrs["TEXCOORD_0"] = 2
        blob += uv.tobytes()

    prim = {"attributes": attrs, "indices": 1, "mode": 4}
    if extra:
        prim.update(extra)
    doc = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [dict({"mesh": 0}, **(node or {}))],
        "meshes": [{"primitives": [prim]}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": views,
        "accessors": accessors,
    }
    return doc, blob


TRI = ([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], [(0, 1, 2)])


def test_reads_a_triangle(tmp_path):
    doc, blob = simple(*TRI, uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])
    path = tmp_path / "t.glb"
    path.write_bytes(build_glb(doc, blob))

    got = gltf.read_glb(path)
    assert len(got.positions) == 3
    assert got.faces == [(0, 1, 2)]
    assert got.uvs[1] == pytest.approx((1.0, 0.0))
    assert got.positions[1] == pytest.approx((1.0, 0.0, 0.0))


def test_node_translation_and_scale_are_applied(tmp_path):
    """A generator often leaves the head scaled or offset at the node rather
    than in the vertex data; ignoring that imports a head in the wrong place."""
    doc, blob = simple(*TRI, node={"translation": [10.0, 0.0, 0.0], "scale": [2, 2, 2]})
    path = tmp_path / "t.glb"
    path.write_bytes(build_glb(doc, blob))

    got = gltf.read_glb(path)
    assert got.positions[0] == pytest.approx((10.0, 0.0, 0.0))
    assert got.positions[1] == pytest.approx((12.0, 0.0, 0.0))


def test_a_parent_node_transform_reaches_its_children(tmp_path):
    doc, blob = simple(*TRI)
    doc["nodes"] = [
        {"children": [1], "translation": [5.0, 0.0, 0.0]},
        {"mesh": 0, "translation": [0.0, 3.0, 0.0]},
    ]
    doc["scenes"] = [{"nodes": [0]}]
    path = tmp_path / "t.glb"
    path.write_bytes(build_glb(doc, blob))

    got = gltf.read_glb(path)
    assert got.positions[0] == pytest.approx((5.0, 3.0, 0.0))


def test_interleaved_accessors_are_read(tmp_path):
    """byteStride packs several attributes into one buffer view; reading it as
    tightly packed would return interleaved nonsense that still looks like a
    mesh."""
    data = np.zeros(3, dtype=[("pos", "<3f4"), ("pad", "<2f4")])
    data["pos"] = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    idx = np.asarray([0, 1, 2], dtype=np.uint32)
    blob = data.tobytes() + idx.tobytes()
    doc = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1,
                                    "mode": 4}]}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": data.nbytes, "byteStride": 20},
            {"buffer": 0, "byteOffset": data.nbytes, "byteLength": idx.nbytes},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5125, "count": 3, "type": "SCALAR"},
        ],
    }
    path = tmp_path / "t.glb"
    path.write_bytes(build_glb(doc, blob))
    got = gltf.read_glb(path)
    assert got.positions[1] == pytest.approx((1.0, 0.0, 0.0))


def test_an_embedded_texture_comes_out(tmp_path):
    png = pytest.importorskip("PIL.Image")
    import io

    buf = io.BytesIO()
    png.new("RGB", (4, 4), (10, 20, 30)).save(buf, format="PNG")
    image = buf.getvalue()

    doc, blob = simple(*TRI)
    offset = len(blob)
    blob += image
    doc["buffers"][0]["byteLength"] = len(blob)
    doc["bufferViews"].append(
        {"buffer": 0, "byteOffset": offset, "byteLength": len(image)}
    )
    doc["images"] = [{"bufferView": len(doc["bufferViews"]) - 1, "mimeType": "image/png"}]
    doc["textures"] = [{"source": 0}]
    doc["materials"] = [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]
    doc["meshes"][0]["primitives"][0]["material"] = 0

    path = tmp_path / "t.glb"
    path.write_bytes(build_glb(doc, blob))
    got = gltf.read_glb(path)
    assert got.image == image
    assert got.image_mime == "image/png"


# --- refusals ----------------------------------------------------------------


def test_a_text_gltf_is_refused(tmp_path):
    path = tmp_path / "t.glb"
    path.write_text('{"asset": {"version": "2.0"}}')
    with pytest.raises(gltf.GltfError, match="binary glTF"):
        gltf.read_glb(path)


def test_draco_compression_is_refused_not_ignored(tmp_path):
    """Silently skipping the primitive would import an empty head."""
    doc, blob = simple(*TRI, extra={"extensions": {"KHR_draco_mesh_compression": {}}})
    path = tmp_path / "t.glb"
    path.write_bytes(build_glb(doc, blob))
    with pytest.raises(gltf.GltfError, match="Draco"):
        gltf.read_glb(path)


def test_an_external_buffer_is_refused(tmp_path):
    doc, blob = simple(*TRI)
    doc["buffers"][0]["uri"] = "mesh.bin"
    path = tmp_path / "t.glb"
    path.write_bytes(build_glb(doc, blob))
    with pytest.raises(gltf.GltfError, match="separate file"):
        gltf.read_glb(path)


def test_a_file_with_no_triangles_is_refused(tmp_path):
    doc, blob = simple(*TRI, extra={"mode": 1})   # lines
    path = tmp_path / "t.glb"
    path.write_bytes(build_glb(doc, blob))
    with pytest.raises(gltf.GltfError, match="no triangles"):
        gltf.read_glb(path)


def test_a_wrong_version_is_refused(tmp_path):
    doc, blob = simple(*TRI)
    path = tmp_path / "t.glb"
    path.write_bytes(build_glb(doc, blob, version=1))
    with pytest.raises(gltf.GltfError, match="version"):
        gltf.read_glb(path)


def test_skinning_is_noted_rather_than_silently_dropped(tmp_path):
    doc, blob = simple(*TRI)
    doc["skins"] = [{"joints": [0]}]
    path = tmp_path / "t.glb"
    path.write_bytes(build_glb(doc, blob))
    got = gltf.read_glb(path)
    assert any("skinning" in n for n in got.notes)
