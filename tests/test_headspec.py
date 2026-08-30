"""What we accept as a custom head, and why.

Every threshold in headspec is measured from the 33 head meshes the game ships,
so these tests check the rules behave as those measurements imply - including
the rule that vanilla itself must always pass.
"""

from __future__ import annotations

import json

import pytest

from kmdlfun import headpack, headspec
from kmdlswap import edit as ke
from kmdlswap import layout as kl
from kmdlswap import obj as kobj


def cube(scale=0.1, offset=(0.0, 0.0, 0.0), with_uv=True):
    """A closed box: one component, no boundary edges."""
    c = [
        (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
        (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
    ]
    quads = [
        (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
    ]
    m = kobj.ObjMesh(name="cube")
    m.positions = [
        tuple(offset[i] + p[i] * scale for i in range(3)) for p in c
    ]
    if with_uv:
        m.uvs = [(0.0, 0.0)] * len(m.positions)
    for q in quads:
        m.faces.append((q[0], q[1], q[2]))
        m.faces.append((q[0], q[2], q[3]))
    return m


def test_a_closed_single_piece_mesh_passes_topology():
    v = headspec.check_mesh(cube())
    levels = {f.check: f.level for f in v.findings}
    assert levels["one piece"] == "pass"
    assert levels["closed"] == "pass"
    assert v.accepted


def test_loose_fragments_are_rejected():
    """The first Tripo head had six islands and a fragment floating in-game."""
    m = cube()
    for i in range(5):
        piece = cube(scale=0.01, offset=(0.5 + i, 0.0, 0.0))
        base = len(m.positions)
        m.positions.extend(piece.positions)
        m.uvs.extend(piece.uvs)
        m.faces.extend((a + base, b + base, c + base) for a, b, c in piece.faces)

    v = headspec.check_mesh(m)
    assert not v.accepted
    fail = next(f for f in v.failures if f.check == "one piece")
    assert "6 disconnected pieces" in fail.detail


def test_an_open_shell_is_rejected():
    """22% of edges open is what "you can see inside the head" looked like."""
    m = cube()
    m.faces = m.faces[:4]  # tear most of the box away
    v = headspec.check_mesh(m)
    assert not v.accepted
    assert any(f.check == "closed" for f in v.failures)


def test_no_geometry_is_rejected():
    v = headspec.check_mesh(kobj.ObjMesh(name="empty"))
    assert not v.accepted
    assert v.failures[0].check == "geometry"


def test_a_huge_mesh_is_rejected_but_a_merely_dense_one_is_not():
    dense = cube()
    dense.faces = dense.faces * 60          # 720 triangles, vanilla's range
    assert headspec.check_mesh(dense).accepted

    huge = cube()
    huge.faces = huge.faces * 400           # 4,800 triangles
    v = headspec.check_mesh(huge)
    assert not v.accepted
    assert any(f.check == "density" for f in v.failures)


def test_missing_uvs_warn_but_do_not_reject():
    v = headspec.check_mesh(cube(with_uv=False))
    assert v.accepted
    assert any(f.check == "texture coordinates" and f.level == "warn" for f in v.findings)


def test_every_vanilla_head_passes_its_own_rules(pair):
    """A rule vanilla would fail is a wrong rule."""
    for model, node_name in (
        ("p_carthh", "Head"),
        ("p_bastilah", "head"),
        ("n_dustilh", "Head"),
    ):
        layout = kl.parse(*pair(model))
        node = layout.node_by_name(node_name)
        geo = ke.extract(layout, node)
        mesh = kobj.ObjMesh(name=node_name)
        mesh.positions = [tuple(p) for p in geo.positions]
        mesh.faces = [f.vertices for f in geo.faces]
        mesh.uvs = [tuple(u) for u in geo.columns.get("uv1", [])]
        mesh.normals = [tuple(n) for n in geo.columns.get("normal", [])]

        v = headspec.check_mesh(mesh)
        assert v.accepted, f"{model}:{node_name} rejected: {[str(f) for f in v.failures]}"


def test_a_skinned_head_is_no_longer_flagged(pair):
    """The warning here claimed a skinned head's vertex count could not change.
    It came from a stale pointer in our own writer, now fixed and confirmed in
    game, so the check reports a pass and says so."""
    layout = kl.parse(*pair("p_carthh"))
    node = layout.node_by_name("Head")
    v = headspec.check_against_target(cube(), layout, node)
    assert v.accepted
    finding = next(f for f in v.findings if f.check == "skinned head")
    assert finding.level == "pass"
    assert "free to change" in finding.detail


def test_target_check_refuses_unauthorable_columns(pair):
    layout = kl.parse(*pair("c_bmspecdiff"))
    node = layout.node_by_name("RLeg")  # carries tangent frames
    v = headspec.check_against_target(cube(), layout, node)
    assert not v.accepted
    assert any("tangent" in f.detail for f in v.failures)


# --- the pack format --------------------------------------------------------


def test_pack_finds_mesh_texture_and_manifest(tmp_path):
    (tmp_path / "head.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    (tmp_path / "skin.tga").write_bytes(b"\0" * 32)
    (tmp_path / "head.json").write_text(json.dumps({"name": "Test", "scale": 1.2}))

    pack = headpack.load(tmp_path)
    assert pack.ok
    assert pack.name == "Test"
    assert pack.scale == 1.2
    assert pack.texture_resref == "skin"
    assert pack.anchor == "chin"          # the default


def test_pack_without_a_manifest_is_still_valid(tmp_path):
    (tmp_path / "head.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    pack = headpack.load(tmp_path)
    assert pack.ok
    assert pack.name == tmp_path.name
    assert pack.texture_resref is None


def test_pack_reports_ambiguity_rather_than_guessing(tmp_path):
    (tmp_path / "one.obj").write_text("v 0 0 0\n")
    (tmp_path / "two.obj").write_text("v 0 0 0\n")
    pack = headpack.load(tmp_path)
    assert not pack.ok
    assert any("several .obj" in p for p in pack.problems)


def test_pack_rejects_nonsense_hints(tmp_path):
    (tmp_path / "head.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    (tmp_path / "head.json").write_text(json.dumps({"facing": "sideways", "scale": 500}))
    pack = headpack.load(tmp_path)
    assert not pack.ok
    assert any("facing" in p for p in pack.problems)
    assert any("scale" in p for p in pack.problems)


def test_template_round_trips(tmp_path):
    headpack.write_template(tmp_path, name="Demo")
    (tmp_path / "head.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    pack = headpack.load(tmp_path)
    assert pack.ok
    assert pack.name == "Demo"


def test_texture_name_too_long_is_rejected(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    p = tmp_path / ("a" * 20 + ".tga")
    Image.new("RGB", (256, 256)).save(p)
    v = headspec.check_texture(p)
    assert not v.accepted
    assert any(f.check == "texture name" for f in v.failures)


def test_texture_must_be_power_of_two(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    p = tmp_path / "skin.tga"
    Image.new("RGB", (300, 200)).save(p)
    v = headspec.check_texture(p)
    assert not v.accepted
    assert any(f.check == "texture size" for f in v.failures)


# --- placement --------------------------------------------------------------


def test_a_raw_foreign_export_is_rejected_on_placement(pair):
    """Topology checks say nothing about scale or position, and a raw export
    from any other tool has neither right - nothing outside KOTOR knows what
    units or origin a head node uses."""
    from kmdlfun import headgen

    layout = kl.parse(*pair("p_hk47"))
    node = layout.node_by_name("head")

    dirs, faces, uvs = headgen.uv_sphere(13, 22)
    raw = [headgen.shape(d) for d in dirs]
    # metres, Y-up, sitting at head height like a whole-body export
    raw = [(p[0] * 0.9, p[2] * 0.9, -p[1] * 0.9 + 1.7) for p in raw]
    mesh = kobj.ObjMesh(name="raw")
    mesh.positions = raw
    mesh.faces = faces
    mesh.uvs = uvs

    assert headspec.check_mesh(mesh).accepted, "topology is fine; only placement is wrong"

    v = headspec.check_placement(mesh, layout, node)
    assert not v.accepted
    checks = {f.check for f in v.failures}
    assert "size" in checks and "placement" in checks


def test_fitting_makes_it_acceptable(pair):
    from kmdlfun import headgen
    from kmdlswap import edit as ke

    layout = kl.parse(*pair("p_hk47"))
    node = layout.node_by_name("head")
    host = ke.extract(layout, node)
    hlo = [min(p[i] for p in host.positions) for i in range(3)]
    hhi = [max(p[i] for p in host.positions) for i in range(3)]
    size = [hhi[i] - hlo[i] for i in range(3)]
    centre = [(hhi[i] + hlo[i]) / 2 for i in range(3)]

    dirs, faces, uvs = headgen.uv_sphere(13, 22)
    raw = [headgen.shape(d) for d in dirs]
    raw = [(p[0] * 0.9, p[2] * 0.9, -p[1] * 0.9 + 1.7) for p in raw]

    oriented = headgen.orient(raw, facing="-y", up="y")
    fitted = headgen.fit_to(oriented, size, centre, anchor="chin")

    mesh = kobj.ObjMesh(name="fitted")
    mesh.positions = fitted
    mesh.faces = faces
    mesh.uvs = uvs
    v = headspec.check_placement(mesh, layout, node)
    assert v.accepted, [str(f) for f in v.failures]


def test_narrower_than_the_node_is_allowed_but_tiny_is_not(pair):
    """Uniform scaling under-fills the other axes when proportions differ; that
    is a proportion difference, not a placement error."""
    from kmdlswap import edit as ke

    layout = kl.parse(*pair("p_hk47"))
    node = layout.node_by_name("head")
    host = ke.extract(layout, node)
    centre = [
        (max(p[i] for p in host.positions) + min(p[i] for p in host.positions)) / 2
        for i in range(3)
    ]

    def box(scale):
        m = kobj.ObjMesh(name="b")
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    m.positions.append(
                        tuple(centre[i] + (sx, sy, sz)[i] * scale for i in range(3))
                    )
        m.faces = [(0, 1, 2)]
        return m

    # 0.24 across against a 0.30 x 0.33 x 0.27 node: narrower, but clearly there.
    ok = headspec.check_placement(box(0.12), layout, node)
    assert ok.accepted, [str(f) for f in ok.failures]

    # 0.10 across is a third of the node - it would be lost inside the model.
    tiny = headspec.check_placement(box(0.05), layout, node)
    assert not tiny.accepted
    assert any(f.check == "size" for f in tiny.failures)

    # And too big is rejected from the other side.
    huge = headspec.check_placement(box(0.40), layout, node)
    assert not huge.accepted
    assert any("too big" in f.detail for f in huge.failures)


def test_orient_brings_a_y_up_mesh_upright():
    from kmdlfun import headgen

    # A point that is "up" in a Y-up export.
    assert headgen.orient([(0.0, 1.0, 0.0)], up="y")[0] == pytest.approx((0.0, 0.0, 1.0))
    # Facing rotations bring the stated front round to +Y, which is where KOTOR
    # characters look (reports/FACING_FINDINGS.md). This asserted -Y until the
    # facing error was found, so a pack that correctly said "+x" was turned to
    # face backwards.
    assert headgen.orient([(1.0, 0.0, 0.0)], facing="+x")[0] == pytest.approx(
        (0.0, 1.0, 0.0), abs=1e-9
    )
    assert headgen.orient([(0.0, -1.0, 0.0)], facing="-y")[0] == pytest.approx(
        (0.0, 1.0, 0.0), abs=1e-9
    )
    # A mesh already facing the game's forward is left alone.
    assert headgen.orient([(0.0, 1.0, 0.0)], facing="+y")[0] == pytest.approx(
        (0.0, 1.0, 0.0), abs=1e-9
    )
