"""The desktop app, driven without a window.

The app is where most of this project actually gets used, so it is worth
testing that its buttons do what the command line does - and specifically that
its worker threads never touch Tk. Tkinter is not thread-safe; reading a Tk
variable from a worker survives only while the main loop happens to be
spinning, so the bug is invisible in normal use and fatal the moment it is not.
That is exactly how it shipped: `_transplant_work` read seven of them.
"""

from __future__ import annotations

import hashlib
import re
import time

import pytest

tk = pytest.importorskip("tkinter", reason="the app needs Tk")


@pytest.fixture(scope="module")
def root():
    """One Tk interpreter for the whole module.

    Creating and destroying a root per test is flaky: Tk variables are collected
    later than the interpreter that owns them, and their __del__ then raises
    against a dead one. It failed about two runs in three, which is worse than
    having no test at all.
    """
    r = tk.Tk()
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture
def app(root, install_path):
    from kmdlfun.gui import App

    a = App(root)
    a.install.set(str(install_path))
    yield a
    a.destroy()


def pump(a, seconds=3.0):
    """Drain the worker's queue the way the running app would."""
    a.worker.join(300)
    deadline = time.time() + seconds
    while time.time() < deadline:
        a.master.update()
        time.sleep(0.02)


def transplant_tab(a):
    for i in range(len(a.tabs.tabs())):
        if a.tabs.tab(i, "text") == "Transplant":
            a.tabs.select(i)
            return
    raise AssertionError("no Transplant tab")


def test_one_preview_run(app, tmp_path):
    """Everything a Preview should do, asserted from a single run.

    Preview writes nothing and shows the result: the host as it is beside the
    host as it would be, framed by one shared ruler.

    Split across three tests this cost three full model-library scans for the
    same work. The assertions are independent; the setup is not.

    **Never reads Tk from the worker.** Tkinter is not thread-safe, and reading
    a Tk variable off the main thread survives only while the main loop happens
    to be spinning - invisible in normal use, fatal the moment it is not. That
    is how it shipped: `_transplant_work` read seven of them. The fixture never
    calls mainloop, so a repeat raises "main thread is not in main loop".

    **Reports the donor's solidity.** The best predictor of whether a swap will
    look right, and the one thing no viewer can show, since a two-sided preview
    draws an inside-out mesh as perfect.

    **Drives the status line.** The Preview button looked like it did nothing:
    it was working, and its output went to a log pushed off the bottom of the
    window when the Preview tab's viewport inflated the notebook.
    """
    transplant_tab(app)
    app.out_dir.set(str(tmp_path))
    app.host.set("p_carthh")
    app.donor.set("n_bith")
    app.opt_fit.set(True)
    app.opt_scale.set(1.15)
    app.opt_texture.set(True)
    app.opt_hide.set(True)
    app.opt_reshape.set(False)
    assert app.status.cget("text") == "Ready"

    app._start(preview=True)
    pump(app)
    log = app.log.get("1.0", "end")

    assert "main thread is not in main loop" not in log
    assert "ERROR" not in log, log[-400:]
    assert "1/1 would transfer" in log
    assert "solid 99%" in log and "good" in log
    assert app.status.cget("text") == "preview only: 1/1 would transfer"

    # It draws the result rather than only describing it. Preview used to
    # report to the log and stop, so the only way to see a swap was to build it
    # first - which is not a preview.
    assert len(app.viewport.scenes) == 2, "should show the host before and after"
    assert app.viewport.labels == ["p_carthh (now)", "p_carthh <- n_bith"]
    assert app.tabs.tab(app.tabs.select(), "text") == "Preview", (
        "the viewport lives on the Preview tab, so it has to come forward"
    )

    # The two must be framed by one ruler, or a part that changed size looks
    # unchanged. shared_bounds gives every scene the same centre and radius.
    assert app.viewport.bounds is not None

    # And nothing was written.
    assert not list(tmp_path.iterdir()), "preview must not write files"


@pytest.mark.slow
def test_the_app_builds_what_the_library_builds(app, tmp_path):
    """Same settings through the app and through `transplant_node` must give the
    same bytes, or the app is a second implementation with its own bugs."""
    from kmdlswap import layout as kl

    from kmdlfun import transplant as ktp
    from kmdlfun import visibility as kvis
    from kmdlfun.library import ModelLibrary

    transplant_tab(app)
    app.out_dir.set(str(tmp_path))
    app.host.set("p_carthh")
    app.donor.set("n_bith")
    app.opt_fit.set(True)
    app.opt_scale.set(1.15)
    app.opt_texture.set(True)
    app.opt_hide.set(True)
    app.opt_reshape.set(False)
    app._start(preview=False)
    pump(app, seconds=5.0)

    built = tmp_path / "p_carthh.mdl"
    assert built.is_file(), app.log.get("1.0", "end")[-400:]

    lib = ModelLibrary(str(app.install.get()))
    mdl, mdx = lib.read("p_carthh")
    donor = kl.parse(*lib.read("n_bith"))
    mdl, mdx, result = ktp.transplant_node(
        mdl, mdx, donor, "n_bith", "Head", "Head",
        fit=True, scale=1.15, with_texture=True,
    )
    assert result.ok, result.error
    layout = kl.parse(mdl, mdx)
    from kmdlfun import parts as kparts

    left = [n.name for n in kparts.mesh_nodes(layout) if n.name != "Head"]
    mdl, _ = kvis.hide_nodes(layout, mdl, left)

    assert hashlib.md5(built.read_bytes()).hexdigest() == hashlib.md5(mdl).hexdigest()


def test_reshape_is_no_longer_forced_on(app):
    """It used to default on and be forced by the texture option, because a
    head's vertex count was thought to be fixed. It is not."""
    assert app.opt_reshape.get() is False
    assert app.opt_texture.get() is True


def test_the_viewport_can_cull(app):
    """The previewer is two-sided by default, which is right for judging shape
    and blind to an inside-out mesh. The toggle is the only way to see one."""
    assert app.preview_cull.get() is False
    assert app.viewport.cull is False
    app.preview_cull.set(True)
    app._repaint_viewport()
    assert app.viewport.cull is True


def test_the_log_and_buttons_fit_in_the_default_window(app):
    """The regression that hid the log.

    The notebook now absorbs spare height and the log keeps a fixed size, so a
    taller tab cannot push it out of sight again.
    """
    app.master.update_idletasks()
    needed = sum(app.grid_bbox(0, r)[3] for r in range(4))
    assert needed < 940, f"content needs {needed}px, taller than the window"
    assert app.log.winfo_reqheight() > 60, "the log must keep a usable height"


def test_the_app_can_take_a_donor_from_the_second_game(app, tmp_path):
    """Cross-game swaps used to be command line only."""
    k2 = None
    for candidate in (
        r"E:\SteamLibrary\steamapps\common\Knights of the Old Republic II",
        r"C:\Program Files (x86)\Steam\steamapps\common\Knights of the Old Republic II",
    ):
        import pathlib

        if (pathlib.Path(candidate) / "chitin.key").is_file():
            k2 = candidate
            break
    if k2 is None:
        pytest.skip("no KOTOR 2 install")

    transplant_tab(app)
    app.install2.set(k2)
    app.donor_game.set("K2")
    app._refresh_donors()
    # Entries carry what they are, so a body is not offered as a head donor.
    values = list(app.donor_box.cget("values"))
    quarren = [v for v in values if v.startswith("n_quarren")]
    assert quarren, values[:6]
    assert "[creature]" in quarren[0], quarren[0]
    assert not [v for v in values if v.startswith("p_carthbb")], "a body was offered"

    app.out_dir.set(str(tmp_path))
    app.host.set("p_carthh")
    app.donor.set(quarren[0])
    assert app._selected_donor() == "n_quarren", "the label must resolve to the model"
    app.opt_texture.set(True)
    app.opt_hide.set(True)
    app.opt_reshape.set(False)
    app.opt_fit.set(False)
    app.opt_automerge.set(True)
    app._start(preview=False)
    pump(app, seconds=6.0)

    log = app.log.get("1.0", "end")
    assert "ERROR" not in log, log[-400:]
    assert "geometry only" in log, "it should say the games differ"
    # The parts the host has no node for are found without being named.
    assert "tent01" in log and "tent04" in log
    # Not fitting still places it, rather than leaving it inside the chest.
    assert "drift 0.000" in log
    # Builds are kept in their own named folder rather than overwriting the
    # output directory, so the texture lives beside the model it belongs to.
    from kmdlfun import builds as kbuilds

    found = kbuilds.find(tmp_path)
    assert len(found) == 1, [b.name for b in found]
    build = found[0]
    assert "quarren" in build.name.lower()
    names = {f["name"] for f in build.manifest["files"]}
    assert names == {"p_carthh.mdl", "p_carthh.mdx", "N_QuarrenH01.tpc"}, names
    assert not build.check(), build.check()

    # The manifest has to say what it is, or a good result cannot be repeated.
    assert build.manifest["donor"]["game"] == "K2"
    assert build.manifest["host"]["game"] == "K1"
    assert set(build.manifest["merged"]) == {"tent01", "tent02", "tent03", "tent04"}


def test_the_anchor_is_the_biggest_part_not_the_first(pair):
    """Carth's `tongue` sorts before his `Head` and has 22 vertices to its 565.
    Anchoring on it looked for a Quarren's tentacles among the tongue's bones,
    found none, and quietly folded nothing in."""
    from kmdlfun import transplant as ktp
    from kmdlswap import layout as kl

    host = kl.parse(*pair("p_carthh"))
    pairs = [("tongue", "tongue"), ("Head", "head")]
    assert ktp.anchor_pair(pairs, host) == ("Head", "head")
    assert ktp.anchor_pair(list(reversed(pairs)), host) == ("Head", "head")


def test_the_effects_tab_previews_a_whole_character(app):
    """A body model alone renders headless and a head model alone renders as a
    floating head, so neither shows what bighead did. The body's `headhook`
    says where the head goes; together is the only view that answers it."""
    for i in range(len(app.tabs.tabs())):
        if app.tabs.tab(i, "text") == "Effects":
            app.tabs.select(i)
            break

    app.effect.set("bighead")
    app.intensity.set(1.6)
    for key, var in app.selected.items():
        var.set(key == "carth")

    app._preview_effect()
    pump(app, seconds=5.0)

    assert len(app.viewport.scenes) == 2, app.log.get("1.0", "end")[-400:]
    before, after = app.viewport.scenes
    assert app.viewport.labels[1] == "Big Head"

    # Both must be a whole person, not a body or a head on its own.
    assert before.triangles > 2000, "a composed character has body and head"
    assert "Head" in before.groups or "head" in before.groups
    assert any(g.lower() in ("torso", "body") or "torso" in g.lower()
               for g in before.groups), before.groups[:12]

    # The effect has to actually change something, and only the head.
    assert after.triangles == before.triangles, "scaling must not add geometry"
    import numpy as np

    moved = ~np.all(np.isclose(before.positions, after.positions), axis=1)
    assert moved.any(), "the preview shows no difference at all"
    assert not moved.all(), "bighead should leave the body alone"

    assert "nothing written" in app.preview_status.cget("text")


def test_the_preview_shows_the_companion_as_normally_seen(app):
    """Carth ships an underwear body and a spare head; a preview of those
    answers a question nobody asked."""
    from kmdlfun import roster

    models = ("p_carthba", "p_carthbb", "p_carthbbh", "p_carthh")
    heads = {"p_carthbbh", "p_carthh"}
    body, head = roster.default_look(models, lambda m: m in heads)
    assert (body, head) == ("p_carthbb", "p_carthh")

    # A self-contained companion has no separate head, and needs none.
    body, head = roster.default_look(("p_hk47",), lambda m: False)
    assert (body, head) == ("p_hk47", None)


def test_a_cross_game_preview_finds_the_donors_texture(app):
    """A K2 donor names a texture the host game has never heard of.

    Looking it up in the host install alone draws it grey - which is what a
    missing texture looks like, and the wrong thing to show someone deciding
    whether a head is worth building. Nothing is written at preview time, so
    there is no file to fall back on either; it has to come from the other game.
    """
    import pathlib

    k2 = next(
        (c for c in (
            r"E:\SteamLibrary\steamapps\common\Knights of the Old Republic II",
            r"C:\Program Files (x86)\Steam\steamapps\common\Knights of the Old Republic II",
        ) if (pathlib.Path(c) / "chitin.key").is_file()),
        None,
    )
    if k2 is None:
        pytest.skip("no KOTOR 2 install")

    transplant_tab(app)
    app.install2.set(k2)
    app.donor_game.set("K2")
    app._refresh_donors()
    quarren = [v for v in app.donor_box.cget("values") if v.startswith("n_quarren")][0]

    app.host.set("p_carthh")
    app.donor.set(quarren)
    app.opt_texture.set(True)
    app.opt_hide.set(True)
    app.opt_reshape.set(False)
    app.opt_fit.set(False)
    app._start(preview=True)
    pump(app, seconds=6.0)

    assert len(app.viewport.scenes) == 2, app.log.get("1.0", "end")[-400:]
    result = app.viewport.scenes[1]
    assert result.textured, "the K2 donor's texture did not resolve"
    assert len(result.textures) == 1
    # and it is a real image, not a placeholder
    assert result.textures[0].shape[:2] == (512, 512)
    assert len({tuple(px) for px in result.textures[0].reshape(-1, 3)[::997]}) > 20


def test_the_lookup_prefers_the_host_game(install_path):
    """Order matters: a name the host game does have must come from the host,
    or a swap would silently pick up the other game's version of it."""
    import numpy as np

    from kmdlfun import textures as ktextures

    look = ktextures.lookup_across([str(install_path), str(install_path)])
    direct = ktextures.TextureCache(str(install_path)).get("P_CarthH01")
    assert direct is not None
    assert np.array_equal(look("P_CarthH01"), direct)
    assert look("no_such_texture_at_all") is None


def test_the_donor_list_can_be_sorted_by_measured_fit(app, k2_path):
    """Alphabetical order says nothing about which donors are worth building.

    Ranking reads every donor model, so it runs on a worker - and like every
    other worker here it must not touch Tk. The list it produces has to stay a
    list the rest of the tab can still use: same names, same mapping back to
    model names, only the order and the labels change.
    """
    transplant_tab(app)
    app.install2.set(str(k2_path))
    app.donor_game.set("K2")
    app.host.set("p_carthh")
    app._refresh_donors()

    before = list(app.donor_labels.values())
    assert before, "no donors offered to rank"
    first = list(app.donor_labels)[0]
    assert re.search(r"\[(head|creature)\]$", first), (
        f"unranked labels should say the kind, got {first!r}"
    )

    app._rank_donors()
    pump(app, seconds=20.0)
    log = app.log.get("1.0", "end")

    assert "main thread is not in main loop" not in log
    assert "could not rank donors" not in log, log[-400:]
    assert "donors measured" in log
    assert "best fits:" in log

    after = list(app.donor_labels.values())
    assert set(after) == set(before), "ranking must not lose or invent donors"
    assert after != before, "the order should now reflect measured fit"

    # The label carries the grade, or the sort is invisible.
    labels = list(app.donor_labels)
    assert any("clean" in x for x in labels), labels[:5]
    assert app.donor_labels[labels[0]] == after[0], "labels must still resolve"

    # The one donor with real in-game experience behind it stays honest.
    quarren = [x for x in labels if x.startswith("n_quarren")]
    assert quarren and "rough" in quarren[0], quarren
    assert "+parts" in quarren[0], "its four tentacles have to be flagged"

    # And picking one still resolves to a model name the build path accepts.
    app.donor.set(labels[0])
    assert app._selected_donor() == after[0]


def test_ranking_without_a_host_says_so_rather_than_failing(app):
    transplant_tab(app)
    app.host.set("")
    app._rank_donors()
    assert "choose a host first" in app.log.get("1.0", "end")
    assert str(app.rank_btn.cget("state")) == "normal", (
        "the button must not be left disabled after a refusal"
    )


def head_tab(a):
    for i in range(len(a.tabs.tabs())):
        if a.tabs.tab(i, "text") == "Custom head":
            a.tabs.select(i)
            return
    raise AssertionError("no Custom head tab")


def test_a_unified_body_can_be_given_a_head_by_naming_the_node(app, tmp_path):
    """HK-47's donor list was empty and the app offered no way in.

    Whole-model pairing is right for two models of the same kind and useless
    here, so a single host node can be named instead. The list then asks only
    "does this donor have a head worth taking".
    """
    from kmdlfun.gui import WHOLE_MODEL

    transplant_tab(app)
    app.out_dir.set(str(tmp_path))
    app.host.set("p_hk47")
    app._refresh_donors()

    assert app.target_node.get() == WHOLE_MODEL
    assert not list(app.donor_box.cget("values")), (
        "whole-model pairing should still find nothing - that rule is correct"
    )
    assert "head" in list(app.target_box.cget("values"))

    app.target_node.set("head")
    app._refresh_donors()
    offered = list(app.donor_box.cget("values"))
    assert len(offered) > 20, "naming the node should offer every head donor"
    assert "one node of" in app.target_note.cget("text")

    carth = [v for v in offered if v.startswith("p_carthh")]
    assert carth, offered[:5]
    app.donor.set(carth[0])
    # Deliberately on: on a unified body this would hide the whole droid.
    app.opt_hide.set(True)
    app.opt_fit.set(True)
    app._start(preview=False)
    pump(app, seconds=12.0)

    log = app.log.get("1.0", "end")
    assert "main thread is not in main loop" not in log
    assert "ERROR" not in log, log[-500:]
    assert "the rest of p_hk47 is untouched" in log
    assert "donor has no:" not in log, (
        "listing 44 unmatched body meshes is noise when filling one node"
    )

    built = list(tmp_path.glob("*/p_hk47.mdl"))
    assert built, list(tmp_path.iterdir())

    # The body survived: hiding was suppressed for a node-targeted build.
    from kmdlswap import layout as kl
    from kmdlfun import parts as kparts

    mdl = built[0].read_bytes()
    mdx = built[0].with_suffix(".mdx").read_bytes()
    assert len(kparts.mesh_nodes(kl.parse(mdl, mdx))) > 40, (
        "HK-47 came out as a floating head - hide was not suppressed"
    )


def test_the_app_can_check_a_custom_head_pack(app):
    """Head packs were command line only, so the app could not do the thing the
    project was built to do. Checking must write nothing and refuse a bad pack
    with the reason."""
    import os

    if not os.path.isdir("packs/scanhead"):
        pytest.skip("the scanned head pack is not in this checkout")

    head_tab(app)
    app.pack_dir.set("packs/scanhead")
    app.head_host.set("p_hk47")
    app._refresh_head_nodes()

    assert app.head_node.get() == "head", "the head node should be picked for you"
    assert "not skinned" in app.head_node_note.cget("text")

    app._head_check()
    pump(app, seconds=30.0)
    log = app.log.get("1.0", "end")

    assert "main thread is not in main loop" not in log
    assert "REJECTED" in log
    assert "solid" in log, "it must say which check failed"


def test_the_donor_list_can_be_filtered_by_who(app):
    """164 models in alphabetical order does not answer "show me the female
    heads". The filter has to narrow the list without breaking the mapping the
    build path relies on, and has to say it is on - a short list with no
    explanation reads as a bug."""
    from kmdlfun.gui import ANYONE, WHOLE_MODEL

    transplant_tab(app)
    app.host.set("p_carthh")
    app._scan()
    pump(app, seconds=20.0)

    app.donor_look.set(ANYONE)
    app._refresh_donors()
    everyone = list(app.donor_labels.values())
    assert everyone, "no donors offered at all"

    app.donor_look.set("female")
    app._refresh_donors()
    female = list(app.donor_labels.values())

    assert female, "no female donors offered"
    assert len(female) < len(everyone), "the filter did not narrow anything"
    assert set(female) <= set(everyone), "the filter invented donors"
    assert "p_bastilah" in female
    assert "p_carthh" not in female and "p_hk47" not in female

    app.donor_look.set("droid")
    app._refresh_donors()
    assert not list(app.donor_labels.values()), (
        "no droid pairs with Carth whole-model, and the filter should not "
        "pretend otherwise"
    )

    # Droids are offered where they can actually go: into one named node.
    # Carth's node is `Head`, capitalised - the selector offers the real names.
    head = next(n for n in app.target_box.cget("values") if n.lower() == "head")
    app.target_node.set(head)
    app._refresh_donors()
    droids = list(app.donor_labels.values())
    assert "p_hk47" in droids, droids[:6]
    assert not set(droids) & set(female), "nothing is both"
    assert "showing droid only" in app.donor_game_note.cget("text")

    # Back to everyone, and nothing was lost on the way.
    app.target_node.set(WHOLE_MODEL)
    app.donor_look.set(ANYONE)
    app._refresh_donors()
    assert set(app.donor_labels.values()) == set(everyone)
