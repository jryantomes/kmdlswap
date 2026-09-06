"""A Jade body, written into a KOTOR body model.

A head becomes a head pack and is spliced into a host. A body cannot take that
route, because a KOTOR body is skinned: its geometry is weighted across many
bones rather than parented to one, and the engine will not skin a mesh to more
than seventeen. So the body is cut into the pieces KOTOR cuts its own into, and
each piece replaces the host node that does that job.

These tests need both installs, because the format is only worth testing
against the files it was reverse-engineered from.
"""

from __future__ import annotations

import pytest

from kmdlfun import bodybuild, installs, jade


@pytest.fixture(scope="module")
def jade_path():
    found = installs.detect().get(installs.JADE)
    if not found:
        pytest.skip("no Jade Empire install on this machine")
    return found


@pytest.fixture(scope="module")
def k1_path():
    found = installs.detect().get(installs.K1)
    if not found:
        pytest.skip("no KOTOR install on this machine")
    return found


@pytest.fixture(scope="module")
def bodies(jade_path):
    found = [e for e in jade.catalogue(jade_path)
             if jade.kind_of(e.resref) == jade.BODY]
    if not found:
        pytest.skip("no Jade bodies found")
    return found


@pytest.fixture(scope="module")
def a_body(bodies):
    found = next((e for e in bodies if e.resref.lower() == "n_bandit_"), None)
    return found or bodies[0]


@pytest.fixture(scope="module")
def built(a_body, k1_path, jade_path):
    return bodybuild.run(a_body, install=k1_path, jade_install=jade_path)


class TestNamingTheHostsNodes:
    """KOTOR is not consistent about what it calls a body's meshes. It is
    consistent about the words in them."""

    @staticmethod
    @pytest.mark.parametrize(("node", "limb"), [
        ("torso", "Torso"), ("Torso", "Torso"),
        ("armL", "LArm"), ("LArm", "LArm"),
        ("armR", "RArm"), ("RArm", "RArm"),
        ("Legs", "Legs"),
    ])
    def test_it_reads_the_names_both_games_use(node, limb):
        assert bodybuild.limb_for(node) == limb

    @staticmethod
    @pytest.mark.parametrize("node", ["head_g", "rootdummy", "lbicep_g", "neck_g"])
    def test_it_claims_nothing_that_is_not_a_body_mesh(node):
        assert bodybuild.limb_for(node) is None


class TestBuildingOne:
    @staticmethod
    def test_it_produces_a_model(built):
        assert built.ok
        assert built.mdl and built.mdx
        assert built.lines, "a build that says nothing about itself is not done"

    @staticmethod
    def test_it_replaces_every_body_mesh_the_host_has(built, k1_path):
        """Miss one and the host's own arm is still there, in its own pose."""
        from kmdlfun.library import ModelLibrary
        from kmdlswap import layout as kl

        host = kl.parse(*ModelLibrary(k1_path).read(built.host))
        wanted = {n.name for n in host.nodes
                  if n.in_animation is None and n.is_skin
                  and bodybuild.limb_for(n.name)}
        assert wanted, "the host has no body meshes - the fixture is wrong"
        said = {line.split(":")[0] for line in built.lines if ":" in line}
        assert wanted <= said, wanted - said

    @staticmethod
    def test_the_geometry_really_changed(built, k1_path):
        """The point of the exercise. A build that quietly kept the host's
        vertices would pass every structural check here."""
        from kmdlfun.library import ModelLibrary
        from kmdlswap import layout as kl

        before = kl.parse(*ModelLibrary(k1_path).read(built.host))
        after = kl.parse(built.mdl, built.mdx)
        moved = 0
        for node in after.nodes:
            if node.in_animation is not None or not node.is_skin:
                continue
            if not bodybuild.limb_for(node.name):
                continue
            was = before.node_by_name(node.name)
            if was.vertex_count != node.vertex_count:
                moved += 1
        assert moved >= 3, "the host's own meshes came through unchanged"

    @staticmethod
    def test_it_reads_back_the_way_the_game_reads_it(built):
        """Bytes that parse, with no hole and no overlap in the file, and that
        write back out exactly as they came in."""
        from kmdlswap import layout as kl
        from kmdlswap import validate

        lay = kl.parse(built.mdl, built.mdx)
        report = validate.check(lay)
        assert not report.gaps, report.gaps[:3]
        assert not report.overlaps, report.overlaps[:3]
        assert validate.serialize(lay) == (built.mdl, built.mdx)

    @staticmethod
    def test_every_weight_lands_on_a_bone_the_host_has(built):
        """Weights are resampled from the host's own surface, so they come out
        in the host's own bone slots. A slot outside that map drives nothing,
        and the vertex holding it never moves with the body."""
        from kmdlswap import layout as kl
        from kmdlswap import mdx as kmdx

        lay = kl.parse(built.mdl, built.mdx)
        checked = 0
        for node in lay.nodes:
            if node.in_animation is not None or not node.is_skin:
                continue
            if not bodybuild.limb_for(node.name):
                continue
            slots = set(kmdx.bone_slot_nodes(lay, node))
            assert slots, node.name
            per_vertex = kmdx.influences(lay, node)
            assert len(per_vertex) == node.vertex_count, node.name
            for i, infl in enumerate(per_vertex):
                assert infl, f"{node.name} vertex {i} is weighted to nothing"
                assert len(infl) <= 4, f"{node.name} vertex {i}: {len(infl)}"
                total = sum(x.weight for x in infl)
                assert abs(total - 1.0) < 1e-3, (node.name, i, total)
                for x in infl:
                    assert x.bone_slot in slots, (node.name, i, x.bone_slot)
            checked += 1
        assert checked >= 3

    @staticmethod
    def test_it_carries_the_jade_texture_and_names_it_for_kotor(built):
        """A resref is sixteen characters. Named from the model, because the
        folder is the caller's and truncating that puts the cut in the wrong
        place - all eight `h_bandit0*` come out alike."""
        assert built.texture, built.warnings
        assert len(built.texture) <= 16
        assert built.texture == built.texture.lower()
        assert built.texture_bytes

    @staticmethod
    def test_the_nodes_point_at_that_texture(built):
        from kmdlswap import layout as kl

        lay = kl.parse(built.mdl, built.mdx)
        seen = set()
        for node in lay.nodes:
            if node.in_animation is not None or not node.is_skin:
                continue
            if bodybuild.limb_for(node.name):
                seen.add((node.textures[0] or "").lower())
        assert seen, "no body meshes found to check"
        assert seen == {built.texture}, seen


class TestWhatItRefusesAndWhatItSaysOutLoud:
    @staticmethod
    def test_it_will_not_build_onto_a_host_that_is_not_there(a_body, k1_path,
                                                             jade_path):
        with pytest.raises(jade.JadeError):
            bodybuild.run(a_body, host="NoSuchBody", install=k1_path,
                          jade_install=jade_path)

    @staticmethod
    def test_it_says_when_two_textures_land_on_one_node(bodies, k1_path,
                                                        jade_path):
        """A KOTOR mesh node wears one texture and half the Jade bodies want
        two. That is a real loss and it gets counted, not hidden."""
        wearing_two = None
        for entry in bodies[:12]:
            try:
                built = bodybuild.run(entry, install=k1_path,
                                      jade_install=jade_path)
            except jade.JadeError:
                continue
            if any("wrong one" in w for w in built.warnings):
                wearing_two = built
                break
        if wearing_two is None:
            pytest.skip("no multi-texture body in the sample")
        said = [w for w in wearing_two.warnings if "wrong one" in w]
        assert any("triangles" in w for w in said), said


class TestWritingItOut:
    @staticmethod
    def test_it_writes_the_three_files(built, tmp_path):
        written = bodybuild.write(built, tmp_path)
        names = sorted(p.name for p in written)
        assert f"{built.host}.mdl" in names
        assert f"{built.host}.mdx" in names
        assert any(n.endswith(".tga") for n in names), names
        for path in written:
            assert path.is_file() and path.stat().st_size > 0

    @staticmethod
    def test_it_writes_nothing_into_the_game(built, tmp_path, k1_path):
        """Building is not installing. The one rule this module has."""
        from pathlib import Path

        override = Path(k1_path) / "Override"
        before = {p.name for p in override.iterdir()} if override.is_dir() else set()
        bodybuild.write(built, tmp_path)
        after = {p.name for p in override.iterdir()} if override.is_dir() else set()
        assert before == after


class TestTheHeadIsLeftBehind:
    """KOTOR hangs the head on `headhook` as its own model. A Jade body that
    brings its own gives the figure two, one inside the other, and the one you
    see is the wrong one - it sits a little higher and a little wider than the
    real face.
    """

    @staticmethod
    def a_body_with_a_head(bodies):
        return next((e for e in bodies if e.resref.lower() == "n_silk_"), None)

    def test_it_says_it_left_the_head_behind(self, bodies, k1_path, jade_path):
        entry = self.a_body_with_a_head(bodies)
        if entry is None:
            pytest.skip("n_silk_ not present")
        built = bodybuild.run(entry, install=k1_path, jade_install=jade_path)
        said = [line for line in built.lines if "headhook" in line]
        assert said, built.lines
        assert "triangles" in said[0]

    def test_none_of_it_reaches_the_model(self, bodies, k1_path, jade_path):
        """The check that matters: nothing above the neck in the built body."""
        import numpy as np

        from kmdlswap import layout as kl
        from kmdlswap import mdx as kmdx

        entry = self.a_body_with_a_head(bodies)
        if entry is None:
            pytest.skip("n_silk_ not present")
        built = bodybuild.run(entry, install=k1_path, jade_install=jade_path)
        parts = jade.partition(jade._parse(*jade.read(entry)))
        neck = max(np.asarray(p.positions)[:, 2].max()
                   for p in parts if p.limb == jade.TORSO)

        lay = kl.parse(built.mdl, built.mdx)
        for node in lay.nodes:
            if node.in_animation is not None or not node.is_skin:
                continue
            if not bodybuild.limb_for(node.name):
                continue
            z = [p[2] for p in kmdx.positions(lay, node)]
            if z:
                assert max(z) <= neck + 1e-6, (node.name, max(z), neck)

    def test_the_texture_is_chosen_without_counting_the_head(self, bodies,
                                                             k1_path, jade_path):
        """The head was most of the clash. Counting a texture we do not carry
        can pick it - and then the body wears the face's atlas."""
        entry = self.a_body_with_a_head(bodies)
        if entry is None:
            pytest.skip("n_silk_ not present")
        built = bodybuild.run(entry, install=k1_path, jade_install=jade_path)
        wrong = [w for w in built.warnings if "wrong one" in w]
        for line in wrong:
            got = [int(x) for x in line.replace(":", " ").split() if x.isdigit()]
            assert got and got[0] < got[1] / 2, line
