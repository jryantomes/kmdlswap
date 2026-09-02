"""The generated head, used as a test fixture.

It is generated rather than committed: the generator is deterministic, so a
fixture built on demand cannot drift out of step with the code that makes it,
and no binaries end up in the repo.

Its real job is to be a known-good pack that exercises the whole path -
generate, load, judge against the criteria, build into a model, validate - so a
regression anywhere along it fails here rather than in-game.
"""

from __future__ import annotations

import pytest

from kmdlfun import headgen, headpack, headspec
from kmdlswap import edit as ke
from kmdlswap import layout as kl
from kmdlswap import obj as kobj
from kmdlswap import validate as kv


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    root = tmp_path_factory.mktemp("moldy_one")
    headgen.build_pack(root, name="Moldy One")
    return root


def test_the_generated_head_is_a_valid_pack(generated):
    pack = headpack.load(generated)
    assert pack.ok, pack.problems
    assert pack.name == "Moldy One"
    assert pack.texture_resref == "moldyone"
    assert pack.anchor == "chin"
    assert pack.facing == "-y"


def test_it_passes_every_criterion_with_no_warnings(generated):
    """A sphere shaped only by radial falloffs cannot fail the topology rules,
    which is the whole reason for building it that way."""
    mesh = kobj.read_obj(generated / "head.obj")
    verdict = headspec.check_mesh(mesh)
    assert verdict.accepted, [str(f) for f in verdict.failures]
    assert not verdict.warnings, [str(f) for f in verdict.warnings]

    levels = {f.check: f.level for f in verdict.findings}
    assert levels["one piece"] == "pass"
    assert levels["closed"] == "pass"
    assert levels["density"] == "pass"


def test_it_is_watertight(generated):
    mesh = kobj.read_obj(generated / "head.obj")
    components, boundary_share, degenerate, boundary, _ = headspec.topology(mesh)
    assert components == 1
    assert boundary == 0, "a closed sphere has no boundary edges"
    assert degenerate == 0


def test_its_texture_is_acceptable(generated):
    pytest.importorskip("PIL")
    verdict = headspec.check_texture(generated / "moldyone.tga")
    assert verdict.accepted, [str(f) for f in verdict.failures]


def test_shaping_actually_shapes(generated):
    """The first version returned a plain egg, because smoothstep refused
    descending ramps and silently disabled the snout, taper and sockets."""
    mesh = kobj.read_obj(generated / "head.obj")
    lo = [min(p[i] for p in mesh.positions) for i in range(3)]
    hi = [max(p[i] for p in mesh.positions) for i in range(3)]
    span = [hi[i] - lo[i] for i in range(3)]

    # A head is deeper than it is wide - a sphere would be neither.
    assert span[1] > span[0] * 1.3, f"not head-shaped: {span}"

    # The face (-Y) reaches further from the ORIGIN than the back of the skull.
    # Measuring against the bounding-box centre instead would be vacuous: the
    # two halves of a bounding box are equal by definition.
    assert abs(lo[1]) > hi[1] * 1.15, f"no muzzle: front {abs(lo[1]):.3f} vs back {hi[1]:.3f}"

    # The sockets cut inwards, so the widest point is not on the eyeline.
    assert span[2] > span[0], "the head is not taller than it is wide"


def test_descending_smoothstep_works():
    assert headgen.smoothstep(0.0, 1.0, 0.5) == pytest.approx(0.5)
    assert headgen.smoothstep(1.0, 0.0, 0.5) == pytest.approx(0.5)
    assert headgen.smoothstep(1.0, 0.0, 0.9) < 0.2, "descending ramp is inverted"
    assert headgen.smoothstep(0.5, 0.5, 0.5) == 0.0


def test_it_builds_into_a_model_that_validates(generated, pair):
    """End to end: a generated pack into HK-47's unskinned head node."""
    from kmdlswap.swap import build_replacement

    layout = kl.parse(*pair("p_hk47"))
    node = layout.node_by_name("head")
    mesh = kobj.read_obj(generated / "head.obj")

    target = headspec.check_against_target(mesh, layout, node)
    assert target.accepted, [str(f) for f in target.failures]

    geo, _ = build_replacement(layout, node, mesh)
    mdl, mdx = ke.replace_geometry(layout, node, geo, texture="moldyone")

    after = kl.parse(mdl, mdx)
    assert kv.check(after).ok
    new_node = after.node_by_name("head")
    assert new_node.vertex_count == mesh.vertex_count
    assert new_node.face_count == len(mesh.faces)

    raw = after.mdl[new_node.trimesh_at + 88 : new_node.trimesh_at + 120]
    assert raw.split(b"\x00")[0].decode("ascii") == "moldyone"

    # The hierarchy is untouched, as always.
    assert [n.name for n in after.nodes] == [n.name for n in layout.nodes]


def test_generation_is_deterministic(tmp_path):
    a = headgen.build_pack(tmp_path / "a")
    b = headgen.build_pack(tmp_path / "b")
    assert (a / "head.obj").read_bytes() == (b / "head.obj").read_bytes()


def test_every_up_axis_is_acted_on():
    """`x` used to fall through silently, so a pack declaring it was treated as
    already Z-up - the manifest accepted a value the code ignored, and the head
    merely came out the wrong size with nothing saying why."""
    from kmdlfun import headgen

    box = [(1.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 3.0)]

    assert headgen.orient(box, up="z") == box
    assert headgen.orient(box, up="y") != box
    assert headgen.orient(box, up="x") != box, "x was ignored"


def test_the_up_rotations_do_not_mirror():
    """A reflection maps the axis just as well and turns the head inside out."""
    import numpy as np

    from kmdlfun import headgen

    basis = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
    for up in ("y", "x"):
        moved = np.asarray(headgen.orient(basis, up=up), dtype=float)
        assert np.linalg.det(moved) == pytest.approx(1.0), up


def test_the_tallest_axis_ends_up_as_z():
    from kmdlfun import headgen

    # A head twice as tall as it is wide, lying along X.
    tall_x = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
    moved = headgen.orient(tall_x, up="x")
    span = [max(p[i] for p in moved) - min(p[i] for p in moved) for i in range(3)]

    assert span[2] == max(span), span
