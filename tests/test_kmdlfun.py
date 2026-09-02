"""kmdlfun: companion effects built on the kmdlswap engine."""

from __future__ import annotations

import pytest

from kmdlfun import apply as kapply
from kmdlfun import effects as keffects
from kmdlfun import parts, roster
from kmdlswap import layout as kl
from kmdlswap import validate as kv


def test_every_companion_model_exists(resources):
    missing = [
        m for c in roster.COMPANIONS for m in c.models if m.lower() not in resources
    ]
    assert not missing, f"not in install: {missing}"


def test_effect_intensity_blends_towards_no_change():
    e = keffects.resolve("bighead")
    assert e.scaled(1.0)["head"] == pytest.approx(1.6)
    assert e.scaled(0.0)["head"] == pytest.approx(1.0)
    assert e.scaled(0.5)["head"] == pytest.approx(1.3)


def test_head_models_are_recognised(pair):
    """Human companions keep their head in its own model; droids do not."""
    assert kapply.is_head_model(kl.parse(*pair("p_carthh")))
    assert not kapply.is_head_model(kl.parse(*pair("p_carthba")))
    assert not kapply.is_head_model(kl.parse(*pair("p_hk47")))


def test_head_model_scales_hair_and_eyes_too(pair):
    """Scaling only the node called 'head' would leave hair and eyes behind."""
    layout = kl.parse(*pair("p_carthh"))
    names = {layout.nodes[i].name.lower() for i in kapply.targets(layout, "head")}
    assert "head" in names
    assert any("hair" in n for n in names)
    assert any("eye" in n for n in names)
    # The neck joins the body and must stay put.
    assert not any(n.startswith("neck") for n in names)


def test_body_model_head_stub_is_not_a_head(pair):
    """p_carthbb has a small 'head_g' stub; it is not the real head."""
    layout = kl.parse(*pair("p_carthbb"))
    assert not kapply.is_head_model(layout)


def test_scaling_changes_size_but_not_topology(pair):
    from kmdlswap import edit as ke

    layout = kl.parse(*pair("p_hk47"))
    node = layout.node_by_name("head")
    geo = ke.extract(layout, node)
    before = [
        max(p[i] for p in geo.positions) - min(p[i] for p in geo.positions)
        for i in range(3)
    ]
    kapply.scale_geometry(geo, 2.0)
    after = [
        max(p[i] for p in geo.positions) - min(p[i] for p in geo.positions)
        for i in range(3)
    ]
    for b, a in zip(before, after):
        assert a == pytest.approx(b * 2.0, rel=1e-5)
    assert geo.vertex_count == node.vertex_count
    assert len(geo.faces) == node.face_count


def _model_space_nodes(layout) -> dict[str, list[tuple[float, ...]]]:
    """Every visible mesh's vertices in model space, keyed by node name."""
    from kmdlswap import edit as ke

    from kmdlfun import space

    pose = space.rest_pose(layout)
    out = {}
    for node in parts.mesh_nodes(layout):
        rest = pose[node.index]
        out[node.name] = [
            tuple(
                rest.position[i] + sum(rest.rotation[i][k] * v[k] for k in range(3))
                for i in range(3)
            )
            for v in ke.extract(layout, node).positions
        ]
    return out


def _centre(vs):
    return [sum(v[i] for v in vs) / len(vs) for i in range(3)]


def _spacing(world: dict) -> dict[tuple[str, str], float]:
    """Distance between every pair of node centres - the thing that has to scale
    with the group if the head is to stay assembled."""
    import math

    names = sorted(world)
    return {
        (a, b): math.dist(_centre(world[a]), _centre(world[b]))
        for i, a in enumerate(names)
        for b in names[i + 1 :]
    }


def test_a_head_made_of_many_nodes_stays_assembled(pair):
    """The bug this pivot exists for: with every node grown about its own centre
    the eyes stay where they were while the face skin grows past them, and they
    end up inside the skull. Under a shared joint pivot every distance inside
    the head scales by the same factor, so the head is the same head, bigger."""
    mdl, mdx = pair("p_missionh")
    before = _spacing(_model_space_nodes(kl.parse(mdl, mdx)))
    assert len(before) > 20, "expected a head model built from many nodes"

    joint_mdl, joint_mdx, res = kapply.apply_to_model(
        mdl, mdx, {"head": 1.6}, pivot="joint", model_name="p_missionh"
    )
    assert res.ok, res.error
    after = _spacing(_model_space_nodes(kl.parse(joint_mdl, joint_mdx)))
    for key, d in before.items():
        assert after[key] == pytest.approx(d * 1.6, rel=1e-4), f"{key} lost registration"


def test_the_old_per_node_pivot_pulls_a_head_apart(pair):
    """Kept as the counter-example: 'bounds' pins every node's centre where it
    was, so the parts of a head no longer line up once they change size."""
    mdl, mdx = pair("p_missionh")
    before = _spacing(_model_space_nodes(kl.parse(mdl, mdx)))
    bounds_mdl, bounds_mdx, res = kapply.apply_to_model(
        mdl, mdx, {"head": 1.6}, pivot="bounds", model_name="p_missionh"
    )
    assert res.ok, res.error
    after = _spacing(_model_space_nodes(kl.parse(bounds_mdl, bounds_mdx)))
    unchanged = [k for k, d in before.items() if after[k] == pytest.approx(d, rel=1e-3)]
    assert unchanged, "expected node spacing to be left behind by the bounds pivot"


def test_eyes_keep_their_clearance_from_the_face(pair):
    """The reported symptom, measured: an eyeball sits ~3mm off the face skin,
    and after a big head it should sit 1.6x that - not be swallowed."""
    import math

    mdl, mdx = pair("p_missionh")
    def clearance(layout):
        world = _model_space_nodes(layout)
        return min(min(math.dist(p, q) for q in world["head"]) for p in world["eyeLA"])

    vanilla = clearance(kl.parse(mdl, mdx))
    new_mdl, new_mdx, res = kapply.apply_to_model(
        mdl, mdx, {"head": 1.6}, pivot="joint", model_name="p_missionh"
    )
    assert res.ok, res.error
    assert clearance(kl.parse(new_mdl, new_mdx)) == pytest.approx(vanilla * 1.6, rel=1e-3)


def _ray_hits_mesh(origin, direction, triangles) -> bool:
    """Moller-Trumbore, forward hits only."""
    for a, b, c in triangles:
        e1 = [b[i] - a[i] for i in range(3)]
        e2 = [c[i] - a[i] for i in range(3)]
        p = [
            direction[1] * e2[2] - direction[2] * e2[1],
            direction[2] * e2[0] - direction[0] * e2[2],
            direction[0] * e2[1] - direction[1] * e2[0],
        ]
        det = sum(e1[i] * p[i] for i in range(3))
        if abs(det) < 1e-12:
            continue
        inv = 1.0 / det
        t0 = [origin[i] - a[i] for i in range(3)]
        u = sum(t0[i] * p[i] for i in range(3)) * inv
        if u < 0.0 or u > 1.0:
            continue
        q = [
            t0[1] * e1[2] - t0[2] * e1[1],
            t0[2] * e1[0] - t0[0] * e1[2],
            t0[0] * e1[1] - t0[1] * e1[0],
        ]
        v = sum(direction[i] * q[i] for i in range(3)) * inv
        if v < 0.0 or u + v > 1.0:
            continue
        if sum(e2[i] * q[i] for i in range(3)) * inv > 1e-6:
            return True
    return False


def _eyeball_visibility(layout) -> float:
    """Share of eyeball vertices with a clear line out through the eye socket.

    The reported symptom - "the eyes seem non-existent" - measured directly:
    the face points along +y, so an eyeball vertex is visible exactly when no
    face-skin triangle sits in front of it.
    """
    from kmdlswap import edit as ke

    world = _model_space_nodes(layout)
    skin_faces = ke.extract(layout, layout.node_by_name("head")).faces
    skin = world["head"]
    triangles = [tuple(skin[i] for i in f.vertices) for f in skin_faces]
    eye = world["eyeLA"]
    clear = sum(1 for p in eye if not _ray_hits_mesh(p, (0.0, 1.0, 0.0), triangles))
    return clear / len(eye)


def test_the_eyeball_is_still_visible_through_the_socket(pair):
    """Vanilla shows a sliver of eyeball through the socket. Growing the face
    skin about its own centre closed that sliver completely - the eyes went
    missing. Growing the whole head about its joint leaves it exactly as it was."""
    mdl, mdx = pair("p_missionh")
    vanilla = _eyeball_visibility(kl.parse(mdl, mdx))
    assert vanilla > 0.0, "expected some eyeball to show in vanilla"

    joint_mdl, joint_mdx, res = kapply.apply_to_model(
        mdl, mdx, {"head": 1.6}, pivot="joint", model_name="p_missionh"
    )
    assert res.ok, res.error
    assert _eyeball_visibility(kl.parse(joint_mdl, joint_mdx)) == pytest.approx(vanilla)

    old_mdl, old_mdx, res = kapply.apply_to_model(
        mdl, mdx, {"head": 1.6}, pivot="bounds", model_name="p_missionh"
    )
    assert res.ok, res.error
    assert _eyeball_visibility(kl.parse(old_mdl, old_mdx)) == 0.0


def test_stored_mesh_bounds_follow_the_geometry(pair):
    """The engine culls and sorts by the per-mesh box; a resized mesh whose box
    still describes the old geometry is a mesh the engine can get wrong."""
    from kmdlswap import edit as ke

    mdl, mdx = pair("p_missionh")
    new_mdl, new_mdx, res = kapply.apply_to_model(
        mdl, mdx, {"head": 1.6}, pivot="joint", model_name="p_missionh"
    )
    assert res.ok, res.error
    layout = kl.parse(new_mdl, new_mdx)
    for node in parts.mesh_nodes(layout):
        bmin, bmax, radius, _average = ke.bounds(layout, node)
        ps = ke.extract(layout, node).positions
        for i in range(3):
            assert bmin[i] <= min(p[i] for p in ps) + 1e-6
            assert bmax[i] >= max(p[i] for p in ps) - 1e-6
        assert radius > 0


def test_invisible_scaffolding_is_left_alone(pair):
    """A human body draws three meshes; the forty-odd `_g` boxes are skeleton.
    Scaling those was work with nothing to show for it."""
    layout = kl.parse(*pair("p_missionbb"))
    visible = {n.name for n in parts.mesh_nodes(layout)}
    assert visible == {"torso", "LArm", "RArm"}
    assert not any(n.name.endswith("_g") for n in parts.mesh_nodes(layout))
    # ... and the parts that only exist as bones now honestly match nothing.
    assert kapply.targets(layout, "hand") == []
    assert kapply.targets(layout, "foot") == []


@pytest.mark.parametrize("effect_key", [e.key for e in keffects.EFFECTS])
def test_every_effect_produces_a_valid_model(pair, effect_key):
    mdl, mdx = pair("p_hk47")
    scales = keffects.resolve(effect_key).scaled(1.0)
    new_mdl, new_mdx, result = kapply.apply_to_model(
        mdl, mdx, scales, model_name="p_hk47"
    )
    assert result.ok, result.error
    assert result.changes, "effect changed nothing"
    assert kv.check(kl.parse(new_mdl, new_mdx)).ok


def test_apply_leaves_the_hierarchy_untouched(pair):
    mdl, mdx = pair("p_hk47")
    before = kl.parse(mdl, mdx)
    new_mdl, new_mdx, _ = kapply.apply_to_model(
        mdl, mdx, {"head": 1.6}, model_name="p_hk47"
    )
    after = kl.parse(new_mdl, new_mdx)
    assert [n.name for n in after.nodes] == [n.name for n in before.nodes]
    assert [n.parent for n in after.nodes] == [n.parent for n in before.nodes]
    assert after.supermodel == before.supermodel
    assert after.animation_names == before.animation_names


def test_duplicate_node_names_are_handled_by_index(pair):
    """T3-M4 has two nodes called FootL, so names cannot address nodes."""
    layout = kl.parse(*pair("p_t3m3"))
    names = [n.name for n in parts.mesh_nodes(layout)]
    assert len(names) != len(set(names))
    indices = kapply.targets(layout, "foot")
    assert len(indices) == len(set(indices))
    mdl, mdx = pair("p_t3m3")
    _, _, result = kapply.apply_to_model(mdl, mdx, {"foot": 1.5}, model_name="p_t3m3")
    assert result.ok
    assert len(result.changes) == len(indices)


def test_unknown_names_are_rejected():
    with pytest.raises(KeyError):
        roster.resolve(["gandalf"])
    with pytest.raises(KeyError):
        keffects.resolve("explode")


def test_compatibility_rejects_a_wildly_different_donor(pair):
    """c_dewback shares a `head` node name with a human head model and nothing
    else. Name overlap alone is not compatibility."""
    from kmdlfun import catalogue as kc
    from kmdlswap import layout as kl

    idx = kc.ModelIndex()
    for name in ("p_carthh", "n_dustilh", "c_dewback"):
        idx.add(kc.describe(kl.parse(*pair(name)), name))

    good = idx.compare("p_carthh", "n_dustilh")
    assert good.tier == "good"
    assert good.shared >= 6
    assert good.same_supermodel

    bad = idx.compare("p_carthh", "c_dewback")
    assert bad.tier == "poor"
    assert not bad.usable
    assert bad.shared <= 1, "a dewback should not share human head parts"
    # A head model and a body model do not have the same parts, and the message
    # must say which is which rather than guess.
    why = bad.why_not("p_carthh", "c_dewback")
    assert "p_carthh is a head model" in why
    assert "c_dewback is a body model" in why


def test_donors_are_ranked_and_filtered(pair):
    from kmdlfun import catalogue as kc
    from kmdlswap import layout as kl

    idx = kc.ModelIndex()
    for name in ("p_carthh", "n_dustilh", "c_dewback"):
        idx.add(kc.describe(kl.parse(*pair(name)), name))

    usable = idx.donors_for("p_carthh")
    assert [n for _, n in usable] == ["n_dustilh"]
    everything = idx.donors_for("p_carthh", usable_only=False)
    assert {n for _, n in everything} == {"n_dustilh", "c_dewback"}
    # Best first.
    assert everything[0][1] == "n_dustilh"


def test_a_model_with_unique_node_names_has_no_donors(pair):
    """HK-47's node names are his own, so nothing vanilla can be moved into him.
    The app should say that rather than offer a list of junk."""
    from kmdlfun import catalogue as kc
    from kmdlswap import layout as kl

    idx = kc.ModelIndex()
    for name in ("p_hk47", "p_carthh", "c_dewback"):
        idx.add(kc.describe(kl.parse(*pair(name)), name))
    assert idx.donors_for("p_hk47") == []


# --- the standalone build ---------------------------------------------------
#
# A bundled app fails at *runtime*, not at build time: anything resolved by
# name rather than imported by name is invisible to PyInstaller's analysis, and
# pykotor picks its format readers by resource type. So the app carries a
# self-test, and these check the self-test itself is honest.


def _launcher():
    import sys
    from pathlib import Path

    tools = str(Path(__file__).resolve().parent.parent / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import app

    return app


def test_the_launcher_has_a_selftest():
    app = _launcher()
    assert callable(app.selftest)
    assert callable(app.main)


def test_the_selftest_exercises_every_bundled_dependency():
    """Naming them is the point. A build that starts and then cannot read a
    2DA is worse than one that does not start at all."""
    import inspect

    body = inspect.getsource(_launcher().selftest)
    for needed in ("numpy", "PIL", "tkinter", "twoda", "gff", "lip",
                   "kmdlswap", "jade", "installs"):
        assert needed in body, needed


def test_the_selftest_passes_here():
    """If it cannot pass unfrozen it will certainly not pass frozen."""
    assert _launcher().selftest() == 0


def test_a_failure_to_start_is_shown_rather_than_swallowed():
    """A windowed build has no console, so a traceback that reaches stderr is
    lost and the app looks like it silently refused to start."""
    import inspect

    body = inspect.getsource(_launcher().main)
    assert "format_exc" in body
    assert "crash" in body.lower()


def test_the_spec_ships_a_folder_not_a_single_file():
    """A one-file build unpacks itself on every launch; with numpy and Tk
    inside that is several seconds of nothing, which reads as a hang."""
    from pathlib import Path

    spec = (Path(__file__).resolve().parent.parent / "kmdlfun.spec").read_text()

    assert "COLLECT(" in spec, "not a one-folder build"
    assert "exclude_binaries=True" in spec
    assert "console=False" in spec, "a window should not drag a terminal behind it"
    assert 'collect_submodules("pykotor")' in spec, (
        "pykotor resolves formats at runtime and has to be named"
    )
    for unwanted in ("pytest", "pip", "PyInstaller"):
        assert unwanted in spec.split("excludes=")[1][:200], (
            f"{unwanted} should not ship inside the app"
        )


def test_the_build_tool_is_not_a_runtime_dependency():
    """Nobody should have to install PyInstaller to *use* the app."""
    import tomllib
    from pathlib import Path

    data = tomllib.loads(
        (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text())
    runtime = " ".join(data["project"]["dependencies"]).lower()

    assert "pyinstaller" not in runtime
    assert "pytest" not in runtime
    assert "pyinstaller" in " ".join(
        data["project"]["optional-dependencies"]["build"]).lower()
