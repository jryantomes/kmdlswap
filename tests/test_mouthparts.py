"""Teeth and a tongue, kept when a head is replaced and seated behind its lips.

Hiding them was a real bug and a quiet one: the mouth animated correctly and
opened onto nothing, described from the game as lips moving on a mouth that
looks taped shut. Keeping them naively is also wrong, because they are placed
for the host's face and a shallower replacement puts them in front of the new
lips - which is what an early attempt looked like, and why the idea was
abandoned once before it was right.
"""

from __future__ import annotations

import pytest

from kmdlfun import mouthparts


class TestNaming:
    """K1 ships three schemes for these node names across 106 head models, and
    a mod is free to invent a fourth."""

    @pytest.mark.parametrize(
        "name",
        [
            "teethua", "teethla",             # 54 heads
            "teethupper", "teethlower",       # 44 heads
            "teethUa01", "teethLa01",         # 3 heads, Carth among them
            "TEETHUPPER", "Teeth_Upper",      # case and a plausible fourth
            "tongue", "Tongue",               # 104 heads
        ],
    )
    def test_mouth_interior_is_recognised(self, name):
        assert mouthparts.is_mouth_part(name)

    @pytest.mark.parametrize(
        "name",
        ["Head", "hair", "eyeLA", "eyeRA", "eyeLlid", "eyeRlid", "torso", "hairalpha"],
    )
    def test_facial_surface_is_not(self, name):
        """These are shaped for the face that is gone and must still be hidden.
        Sparing `hair` or an eyelid would leave it floating over the new head."""
        assert not mouthparts.is_mouth_part(name)

    def test_a_node_merely_containing_the_word_is_not_matched(self):
        """`teeth` is a prefix test, not a substring one, or a node called
        something like `nteethgrindfx` would be spared by accident."""
        assert not mouthparts.is_mouth_part("nteethgrind")
        assert not mouthparts.is_mouth_part("mytongue")


def test_the_seat_is_measured_from_both_heads_not_chosen():
    """The correction has to follow the geometry: a deeper replacement pulls the
    teeth forward, a shallower one pushes them back. A fixed nudge would be
    right on one head and wrong on the next."""
    import inspect

    source = inspect.getsource(mouthparts.seat)
    assert "old_depth" in source and "new_depth" in source
    # The clearance comes from the host, not a constant.
    assert "want = old_depth - front" in source


def test_only_depth_is_corrected():
    """The teeth already bracket the mouth vertically and are narrow enough to
    fit. Moving them in z, or scaling them, would be inventing a correction for
    a problem that was never measured."""
    import inspect

    source = inspect.getsource(mouthparts.seat)
    assert "np.array([0.0, shift, 0.0])" in source, "the shift must be depth only"
    # UniformScale is how the stored bounds are transported with the vertices;
    # the factor must be exactly 1, so it is carrying a translation and nothing
    # else.
    assert "UniformScale(1.0, local)" in source


class TestAgainstTheGame:
    """Against the real install, so the numbers in the docstring stay honest."""

    @staticmethod
    @pytest.fixture(scope="class")
    def k1():
        from kmdlfun import installs

        path = installs.detect().get(installs.K1)
        if not path:
            pytest.skip("no K1 install detected")
        return path

    def test_a_vanilla_head_carries_its_mouth_interior(self, k1):
        from kmdlfun.library import ModelLibrary
        from kmdlswap import layout as kl

        layout = kl.parse(*ModelLibrary(k1).read("p_carthh"))
        found = {n.name.lower() for n in mouthparts.mouth_parts(layout)}

        assert "tongue" in found
        assert any(n.startswith("teeth") for n in found)

    def test_seating_a_head_in_its_own_model_changes_nothing(self, k1):
        """The clearance is already correct, so the shift must be zero. A pass
        that drifted here would walk the teeth backwards on every rebuild."""
        from kmdlfun import parts as kparts
        from kmdlfun.library import ModelLibrary
        from kmdlswap import layout as kl

        mdl, mdx = ModelLibrary(k1).read("p_carthh")
        layout = kl.parse(mdl, mdx)
        head = next(n for n in kparts.mesh_nodes(layout) if n.name.lower() == "head")

        out_mdl, out_mdx, lines = mouthparts.seat(layout, mdl, mdx, head, layout)

        assert out_mdl == mdl
        assert out_mdx == mdx
        assert lines == []

    def test_the_node_headers_are_left_alone(self, k1):
        """The move goes into the geometry, not the node transform. Editing the
        header measured correct in the file and did nothing in game, because
        the teeth carry a position controller the engine reads instead."""
        import struct

        from kmdlfun import parts as kparts
        from kmdlfun.library import ModelLibrary
        from kmdlswap import layout as kl
        from kmdlswap._io import MDL_BASE

        mdl, mdx = ModelLibrary(k1).read("p_carthh")
        layout = kl.parse(mdl, mdx)
        head = next(n for n in kparts.mesh_nodes(layout) if n.name.lower() == "head")
        before = {
            n.name: struct.unpack_from("<3f", mdl, MDL_BASE + n.offset + 16)
            for n in mouthparts.mouth_parts(layout)
        }

        out_mdl, _, _ = mouthparts.seat(layout, mdl, mdx, head, layout)

        after_layout = kl.parse(out_mdl, mdx)
        after = {
            n.name: struct.unpack_from("<3f", out_mdl, MDL_BASE + n.offset + 16)
            for n in mouthparts.mouth_parts(after_layout)
        }
        assert after == before


class TestTheBlinkItself:
    """The blink is a fixed rotation authored for the host's eye opening.

    Decoded from `p_carthh`: 21 keys on each lid, orientation only, no position
    channel, turning through 38.47 degrees at the widest. A converted head's eye
    opening is a different size - measured as the boundary loop where the face
    skin parts, Carth's is 0.0180 tall against `h_mercf01_`'s 0.0271 - so the
    same sweep stops partway down hers.
    """

    @staticmethod
    def test_the_compressed_quaternion_round_trips():
        """Every blink key in the vanilla model, back to the exact same word.

        The format packs x and y in 11 bits and z in 10 and derives w, so a
        codec that is merely close would drift the animation a little on every
        rebuild.
        """
        from kmdlfun import mouthparts as km

        for word in (0x7FDFFBFF, 0x7FDFFBDC, 0x7FDFFB9A,
                     0x7FDFFAAE, 0x7FDFFB11, 0x7FDFFBD5):
            assert km._pack_quat(km._unpack_quat(word)) == word

    @staticmethod
    def test_resting_stays_resting():
        """The key that holds the eye open is identity, and scaling an angle by
        anything leaves it identity. If it did not, the lid would sit part-closed
        whenever the animation was not playing."""
        from kmdlfun import mouthparts as km

        assert km._pack_quat(km._unpack_quat(0x7FDFFBFF)) == 0x7FDFFBFF
        w, x, y, z = km._unpack_quat(0x7FDFFBFF)
        assert abs(w - 1.0) < 1e-6 and max(abs(x), abs(y), abs(z)) < 1e-6

    @staticmethod
    def test_deepening_by_one_changes_nothing():
        from kmdlfun import mouthparts as km

        out, lines = km.deepen_blink(b"not a model", b"", 1.0)
        assert out == b"not a model" and lines == []


class TestDeepeningAgainstTheGame:
    @staticmethod
    @pytest.fixture(scope="class")
    def k1_install():
        from kmdlfun import installs

        path = installs.detect().get(installs.K1)
        if not path:
            pytest.skip("no K1 install detected")
        return path

    @staticmethod
    def test_the_host_blink_reads_and_deepens(k1_install):
        from kmdlfun import mouthparts as km
        from kmdlfun.library import ModelLibrary
        from kmdlswap import layout as kl
        from kmdlswap import validate as kv

        mdl, mdx = ModelLibrary(k1_install).read("p_carthh")
        angle = km.blink_angle(mdl, mdx)
        assert angle is not None and 38.0 < angle < 39.0, angle

        deeper, lines = km.deepen_blink(mdl, mdx, 1.30)
        assert lines and "blink" in lines[0]
        assert len(deeper) == len(mdl), "an in-place key edit must not resize"
        assert kv.check(kl.parse(deeper, mdx)).ok
        after = km.blink_angle(deeper, mdx)
        assert abs(after - angle * 1.30) < 0.5, (angle, after)
