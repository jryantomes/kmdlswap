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
    assert "scale" not in source.lower()


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

        out, lines = mouthparts.seat(layout, mdl, head, layout)

        assert out == mdl
        assert lines == []
