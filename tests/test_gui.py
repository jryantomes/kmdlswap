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


@pytest.fixture(scope="module")
def scanned(install_path):
    """The install scan, done once for the whole module.

    Four tests need a populated host and donor list and the scan takes about
    thirty-five seconds, because it reads all 233 models. Doing it per test
    spent two minutes of every run re-deriving the same answer. The one test
    that is *about* the scan still runs it for real.
    """
    from kmdlfun import catalogue as kc
    from kmdlfun.library import ModelLibrary, character_models, kind_of
    from kmdlswap import layout as kl
    from kmdlswap import validate as kv

    lib = ModelLibrary(str(install_path))
    index = kc.ModelIndex()
    kinds = {}
    for name in character_models(str(install_path), lib):
        try:
            layout = kl.parse(*lib.read(name))
            if kv.check(layout).ok:
                index.add(kc.describe(layout, name))
                kinds[name] = kind_of(layout)
        except Exception:  # noqa: BLE001, S112
            continue
    return index, kinds


def apply_scan(a, scanned, install_path):
    """Hand an app the scan result, exactly as its own drain loop would."""
    index, kinds = scanned
    a.index = index
    a.models = index.names
    a.host_labels = {
        (f"{n}   [{kinds[n]}]" if n in kinds else n): n for n in a.models
    }
    a.host_box.config(values=list(a.host_labels))
    a.preview_box.config(values=a.models)
    a.head_host_box.config(values=a.models)
    a._kind_cache = {str(install_path): kinds}


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
    # A head model is drawn on its body: alone it is a head floating in space,
    # and size and placement are what a head swap most often gets wrong.
    assert app.viewport.labels == [
        "p_carthh on p_carthbb (now)",
        "p_carthh <- n_bith on p_carthbb",
    ]
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
    from kmdlfun.gui import WINDOW_H

    app.master.update_idletasks()
    needed = sum(app.grid_bbox(0, r)[3] for r in range(4))
    assert needed < WINDOW_H, (
        f"content needs {needed}px, taller than the {WINDOW_H}px window"
    )
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
    values = app.donor_choices()
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
    quarren = [v for v in app.donor_choices() if v.startswith("n_quarren")][0]

    app.host.set("p_carthh")
    app.donor.set(quarren)
    app.opt_texture.set(True)
    app.opt_hide.set(True)
    app.opt_reshape.set(False)
    app.opt_fit.set(False)
    app._start(preview=True)
    pump(app, seconds=6.0)

    assert len(app.viewport.scenes) == 2, app.log.get("1.0", "end")[-400:]
    before, result = app.viewport.scenes
    assert result.textured, "the K2 donor's texture did not resolve"

    # Both scenes carry the host's body texture, since a head is drawn on its
    # body. What proves the lookup crossed games is a texture in the result
    # that the untouched host does not have.
    def fingerprints(scene):
        return {hash(img.tobytes()) for img in scene.textures}

    brought = fingerprints(result) - fingerprints(before)
    assert brought, "the result uses no texture the host did not already have"

    donor_tex = next(img for img in result.textures
                     if hash(img.tobytes()) in brought)
    # and it is a real image, not a placeholder
    assert donor_tex.shape[:2] == (512, 512)
    assert len({tuple(px) for px in donor_tex.reshape(-1, 3)[::997]}) > 20


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


def pick_head_node(a):
    """Aim at the host's own head node, which needs no install scan."""
    a._refresh_donors()
    head = next(n for n in a.target_box.cget("values") if n.lower() == "head")
    a.target_node.set(head)
    a._refresh_donors()

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
    assert not app.donor_choices(), (
        "whole-model pairing should still find nothing - that rule is correct"
    )
    assert "head" in list(app.target_box.cget("values"))

    app.target_node.set("head")
    app._refresh_donors()
    offered = app.donor_choices()
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


def test_the_donor_list_can_be_filtered_by_who(app, scanned, install_path):
    """164 models in alphabetical order does not answer "show me the female
    heads". The filter has to narrow the list without breaking the mapping the
    build path relies on, and has to say it is on - a short list with no
    explanation reads as a bug."""
    from kmdlfun.gui import ANYONE, WHOLE_MODEL

    transplant_tab(app)
    apply_scan(app, scanned, install_path)
    app.host.set("p_carthh")

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


def test_the_donor_list_shows_faces(app):
    """A name does not tell you what a face looks like, and the list is a few
    hundred names. The faces arrive on a worker, so the rows have to survive
    being filled before the images exist - and Tk drops an image the moment
    nothing references it, which the widget does not count as.
    """
    transplant_tab(app)
    app.host.set("p_carthh")
    app.donor_look.set("female")
    pick_head_node(app)

    labels = app.donor_choices()
    assert labels, "no donors to draw"
    assert app.donor_tree.labels == labels, (
        "every choice should be a cell, image or not"
    )

    deadline = time.time() + 60
    while time.time() < deadline and len(app._donor_photos) < min(len(labels), 5):
        app.master.update()
        time.sleep(0.05)

    assert app._donor_photos, "no faces were drawn"
    drawn = [x for x in labels if app.donor_tree._images.get(x) is not None]
    assert drawn, "faces were drawn but never reached the gallery"


def test_picking_a_face_selects_that_model(app):
    """The tree writes into the variable the build path reads, so choosing by
    face and choosing by name end up in the same place."""
    transplant_tab(app)
    app.host.set("p_carthh")
    app.donor_look.set("female")
    pick_head_node(app)

    labels = app.donor_choices()
    wanted = next(x for x in labels if x.startswith("p_bastilah"))
    app.donor_tree.select(wanted)
    app._on_donor_pick(wanted)

    assert app.donor.get() == wanted
    assert app._selected_donor() == "p_bastilah"


def test_refiltering_does_not_leave_faces_behind(app):
    """Kept images are the only thing stopping Tk collecting them, so the dict
    has to be pruned or it grows by a whole list on every filter change."""
    from kmdlfun.gui import ANYONE

    transplant_tab(app)
    app.host.set("p_carthh")
    app.donor_look.set("female")
    pick_head_node(app)
    deadline = time.time() + 40
    while time.time() < deadline and len(app._donor_photos) < 3:
        app.master.update()
        time.sleep(0.05)
    assert app._donor_photos

    app.donor_look.set(ANYONE)
    app._refresh_donors()
    stale = set(app._donor_photos) - set(app.donor_choices())
    assert not stale, f"{len(stale)} images kept for rows that are gone"


def test_a_self_contained_host_is_previewed_on_its_own(app, tmp_path):
    """HK-47 has no separate body - it *is* the body - so there is nothing to
    put it on, and the preview must not go looking."""
    transplant_tab(app)
    app.out_dir.set(str(tmp_path))
    app.host.set("p_hk47")
    app._refresh_donors()
    head = next(n for n in app.target_box.cget("values") if n.lower() == "head")
    app.target_node.set(head)
    app._refresh_donors()
    app.donor.set(next(v for v in app.donor_choices() if v.startswith("p_carthh")))

    app._start(preview=True)
    pump(app, seconds=15.0)

    log = app.log.get("1.0", "end")
    assert "could not draw" not in log, log[-300:]
    assert app.viewport.labels == ["p_hk47 (now)", "p_hk47 <- p_carthh"], (
        "a self-contained model should be drawn as itself, with no ' on ...'"
    )


def test_a_cross_game_build_ships_only_what_the_host_lacks(app, tmp_path, k2_path):
    """A built model still names the host's own textures on the parts that did
    not change - Carth keeps `P_CarthH01` on his hair and teeth - and both games
    ship a file by that name. Copying the donor game's copy into Override puts a
    KOTOR 2 asset in front of the KOTOR 1 one for every model that uses it, not
    just this build.
    """
    transplant_tab(app)
    app.install2.set(str(k2_path))
    app.donor_game.set("K2")
    app._refresh_donors()
    mira = [v for v in app.donor_choices() if v.startswith("p_mirah")]
    if not mira:
        pytest.skip("p_mirah not offered from this K2 install")

    app.out_dir.set(str(tmp_path))
    app.host.set("p_carthh")
    app.donor.set(mira[0])
    app.opt_texture.set(True)
    app.opt_hide.set(True)
    app.opt_fit.set(False)
    app._start(preview=False)
    pump(app, seconds=20.0)

    log = app.log.get("1.0", "end")
    assert "ERROR" not in log, log[-400:]

    built = list(tmp_path.glob("*/p_carthh.mdl"))
    assert built, list(tmp_path.iterdir())
    shipped = {p.name.lower() for p in built[0].parent.iterdir()}

    assert "p_mirah.tpc" in shipped, f"the donor's texture is missing: {shipped}"
    assert not any(n.startswith("p_carthh01") for n in shipped), (
        f"shipped a KOTOR 2 copy of a KOTOR 1 texture: {shipped}"
    )


def test_the_host_list_says_what_each_model_is(app, scanned, install_path):
    """A head model and a creature take a swap very differently and their names
    do not say which is which - `p_hk47` carries its head inside its body,
    `p_carthh` is a head on its own. Knowing that after choosing is too late.
    """
    transplant_tab(app)
    apply_scan(app, scanned, install_path)

    values = list(app.host_box.cget("values"))
    assert values, "no hosts listed"
    labelled = {v.split()[0]: v for v in values}

    assert "[head]" in labelled["p_carthh"]
    assert "[creature]" in labelled["p_hk47"], labelled["p_hk47"]
    assert "[body]" in labelled["p_carthbb"], labelled["p_carthbb"]

    kinds = {v.split("[")[-1].rstrip("]") for v in values if "[" in v}
    assert {"head", "creature", "body"} <= kinds, kinds


def test_a_labelled_host_still_resolves_to_a_model(app, scanned, install_path):
    """Everything downstream wants the bare name, and a bare name typed in by
    hand has to keep working too."""
    transplant_tab(app)
    apply_scan(app, scanned, install_path)

    label = next(v for v in app.host_box.cget("values") if v.startswith("p_carthh "))
    app.host.set(label)
    assert app._selected_host() == "p_carthh"

    app.host.set("p_hk47")
    assert app._selected_host() == "p_hk47", "an unlabelled name must still work"

    app.host.set("")
    assert app._selected_host() == ""


def test_the_scan_classifies_on_its_way_past(app):
    """It parses every model to build the index, so classifying separately
    would read the whole install a second time - about ten seconds of it."""
    transplant_tab(app)
    app._scan()
    pump(app, seconds=30.0)

    install = app.install.get().strip()
    assert getattr(app, "_kind_cache", {}).get(install), (
        "the scan should have left its classification behind"
    )

    started = time.time()
    app.host.set("p_carthh")
    app._refresh_donors()
    assert time.time() - started < 5.0, "the donor list re-read the install"
    assert app.donor_choices()


def test_the_games_are_named(app):
    """"this game" tells you nothing when two are configured."""
    from tkinter import ttk

    transplant_tab(app)
    labels = []

    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, ttk.Radiobutton):
                labels.append(str(child.cget("text")))
            walk(child)

    walk(app)
    assert "KOTOR" in labels and "KOTOR II" in labels, labels
    assert "this game" not in labels


def test_the_preview_frames_the_head_it_swapped(app, tmp_path):
    """Drawing the head on its body gave the swap context and cost the detail.

    A head on a standing figure is a few dozen pixels, which is not enough to
    judge the thing that changed - so the camera frames the head by default and
    the whole figure is a click away.
    """
    transplant_tab(app)
    app.out_dir.set(str(tmp_path))
    app.host.set("p_carthh")
    app._refresh_donors()
    app.donor.set("n_dustilh")
    app.opt_fit.set(False)
    app._start(preview=True)
    pump(app, seconds=15.0)

    assert app._focus_bounds is not None, "no head framing was worked out"
    assert app._whole_bounds is not None
    assert app.preview_frame.get() == "head", "the head is the default"

    head_radius = float(app._focus_bounds[1])
    whole_radius = float(app._whole_bounds[1])
    assert head_radius < whole_radius / 3, (
        f"head framing is barely tighter: {head_radius:.3f} vs {whole_radius:.3f}"
    )
    assert app.viewport.bounds is app._focus_bounds

    app.preview_frame.set("whole")
    app._apply_framing()
    assert app.viewport.bounds is app._whole_bounds

    app.preview_frame.set("head")
    app._apply_framing()
    assert app.viewport.bounds is app._focus_bounds


def test_zoom_is_reachable_without_a_mouse_wheel(app):
    """The wheel already zoomed and nothing said so."""
    app.preview_zoom.set(2.5)
    app._apply_zoom()
    assert app.viewport.zoom == pytest.approx(2.5)
    assert "2.5" in app.zoom_label.cget("text")


def test_a_headless_creature_can_still_donate_a_part(app, tmp_path):
    """Two models that share no node names and have neither a head.

    A dewback and a bantha pair on nothing, so no automatic rule reaches them.
    Naming both sides is the escape hatch, and until now only the host's side
    could be named.
    """
    from kmdlfun.gui import AUTO_NODE

    transplant_tab(app)
    app.out_dir.set(str(tmp_path))
    app.host.set("c_dewback")
    app._refresh_donors()
    assert not app.donor_choices(), "nothing should pair with it whole-model"

    node = next(n for n in app.target_box.cget("values") if n.lower() == "uprbody")
    app.target_node.set(node)
    app._refresh_donors()

    offered = app.donor_choices()
    assert len(offered) > 100, "naming a node should offer anything with geometry"
    bantha = next(d for d in offered if d.startswith("c_bantha"))
    app.donor.set(bantha)
    app._refresh_donor_nodes()

    nodes = list(app.donor_node_box.cget("values"))
    assert nodes[0] == AUTO_NODE
    assert "btBody_front" in nodes, nodes[:6]

    # Automatic cannot guess here, and has to say so usefully.
    app.donor_node.set(AUTO_NODE)
    app.opt_hide.set(False)
    app._start(preview=True)
    pump(app, seconds=10.0)
    log = app.log.get("1.0", "end")
    assert "no head" in log and "'from' list" in log, log[-300:]

    # Named, it goes through.
    app.donor_node.set("btBody_front")
    app._start(preview=True)
    pump(app, seconds=15.0)
    log = app.log.get("1.0", "end")
    assert "c_dewback:UprBody from c_bantha:btBody_front" in log, log[-400:]
    assert "1/1 would transfer" in log
    assert len(app.viewport.scenes) == 2


def test_naming_the_donor_node_overrides_the_automatic_choice(app, tmp_path):
    """It has to win even when an automatic answer exists, or it is not a
    choice - a head swap that wanted the donor's hair could not ask for it."""
    transplant_tab(app)
    app.out_dir.set(str(tmp_path))
    app.host.set("p_carthh")
    app._refresh_donors()
    head = next(n for n in app.target_box.cget("values") if n.lower() == "head")
    app.target_node.set(head)
    app._refresh_donors()
    app.donor.set(next(d for d in app.donor_choices() if d.startswith("n_dustilh")))
    app._refresh_donor_nodes()

    app.donor_node.set("tongue")
    app._start(preview=True)
    pump(app, seconds=15.0)

    log = app.log.get("1.0", "end")
    assert "p_carthh:Head from n_dustilh:tongue" in log, log[-400:]


def test_saving_under_a_new_name_makes_a_new_model(app, tmp_path):
    """Every build until now overwrote a vanilla model, so two could not
    coexist and installing one replaced a character for the whole game.

    The filename alone is not enough: the model carries its own name and the
    engine reads that one, so they have to agree.
    """
    from kmdlswap import layout as kl
    from kmdlswap import validate as kv

    transplant_tab(app)
    app.out_dir.set(str(tmp_path))
    app.host.set("p_carthh")
    app._refresh_donors()
    app.donor.set("n_dustilh")
    app.opt_fit.set(False)
    app.save_as.set("p_mycustomhead")

    app._start(preview=False)
    pump(app, seconds=20.0)

    log = app.log.get("1.0", "end")
    assert "ERROR" not in log, log[-400:]
    assert "a new model rather than a replacement" in log

    built = list(tmp_path.glob("*/p_mycustomhead.mdl"))
    assert built, list(tmp_path.iterdir())
    assert not list(tmp_path.glob("*/p_carthh.mdl")), "it must not also write the host"

    mdl = built[0].read_bytes()
    mdx = built[0].with_suffix(".mdx").read_bytes()
    after = kl.parse(mdl, mdx)
    assert after.model_name == "p_mycustomhead", "the name inside must match the file"
    assert kv.check(after).ok


def test_a_name_the_engine_cannot_use_is_refused_before_building(app, tmp_path):
    transplant_tab(app)
    app.out_dir.set(str(tmp_path))
    app.host.set("p_carthh")
    app._refresh_donors()
    app.donor.set("n_dustilh")
    app.save_as.set("not a resref!")

    app._start(preview=False)
    pump(app, seconds=15.0)

    assert "not a usable model name" in app.log.get("1.0", "end")
    assert not list(tmp_path.glob("*/*.mdl")), "nothing should have been written"


def test_the_upcoming_tab_lists_what_is_coming(app):
    """A roadmap in the app rather than in a file nobody opens.

    The status on each line is the useful part: someone waiting for a feature
    that already runs on the command line is waiting for nothing.
    """
    from kmdlfun.gui import UPCOMING

    names = [app.tabs.tab(i, "text") for i in range(len(app.tabs.tabs()))]
    assert "Upcoming" in names
    assert names[-1] == "Upcoming", "it belongs at the end, after the working tabs"

    titles = [t for t, _status in app.upcoming_rows]
    assert len(titles) == len(UPCOMING)


def test_a_feature_with_a_tab_is_off_the_upcoming_list(app):
    """It graduated. Leaving it listed sends someone to the command line for
    something that now has a button, which is how a roadmap starts lying."""
    tabs = [app.tabs.tab(i, "text") for i in range(len(app.tabs.tabs()))]
    assert "Lips" in tabs

    titles = [row[0] for row in UPCOMING_ROWS()]
    assert not any("Lip files" in t for t in titles), titles


def test_every_command_on_the_tab_is_runnable_as_printed(app):
    for title, _status, _blurb, command in UPCOMING_ROWS():
        if not command:
            continue
        assert not command.startswith("kmdlfun"), f"{title}: assumes PATH"
        assert not command.rstrip().endswith("\\"), (
            f"{title}: a trailing separator before a space breaks the argument"
        )


def UPCOMING_ROWS():
    from kmdlfun.gui import UPCOMING

    return UPCOMING


def test_upcoming_promises_no_buttons(app):
    """It is a list, not a half-built feature. Nothing on it should look
    clickable, or it becomes a source of bug reports."""
    from tkinter import ttk

    page = None
    for i in range(len(app.tabs.tabs())):
        if app.tabs.tab(i, "text") == "Upcoming":
            page = app.tabs.nametowidget(app.tabs.tabs()[i])
    assert page is not None

    def buttons(widget):
        found = []
        for child in widget.winfo_children():
            if isinstance(child, (ttk.Button, ttk.Checkbutton, ttk.Radiobutton)):
                found.append(child)
            found.extend(buttons(child))
        return found

    assert not buttons(page), "the Upcoming tab should not offer controls"

    def entries(widget):
        found = []
        for child in widget.winfo_children():
            if isinstance(child, ttk.Entry):
                found.append(child)
            found.extend(entries(child))
        return found

    for entry in entries(page):
        assert str(entry.cget("state")) == "readonly", (
            "the command lines are for copying, not typing into"
        )


def test_a_donor_head_keeps_its_own_size_by_default(app):
    """Shrinking a head to the host's box detaches it from the neck.

    Measured on a Bith onto Carth: fitted it stands 0.242 tall and floats 0.019
    above the collar; left alone it stands 0.400 and overlaps by 0.060. The
    donor is the size it was authored at, and `to_host_space` was already
    arguing this about a Quarren while the default did the opposite.
    """
    transplant_tab(app)
    assert app.opt_fit.get() is False, "fitting should be opt-in"


# --- the lips tab -----------------------------------------------------------
#
# Confirmed in game on 2026-09-01: a .lip plays with no recording behind it,
# and 26 generated files drove the broker's conversation from end to end. The
# engine was proven before the button existed; these are about the button.


def test_the_lips_tab_needs_no_model(app):
    """The one feature here that is about a conversation rather than a mesh.
    It must not be gated behind scanning an install."""
    app.dlg_path.set("")
    app._say = lambda text: app.__dict__.setdefault("said", []).append(text)
    app._lips_start()

    assert any("choose a dialogue" in s for s in app.said)


def test_the_lips_worker_touches_no_tk_variable(app, tmp_path):
    """The bug this whole module exists for. A worker reading a Tk variable
    survives only while the main loop happens to be spinning."""
    import inspect

    from kmdlfun import gui as kgui

    body = inspect.getsource(kgui.App._lips_work)
    assert "self.lip_" not in body, body
    assert "self.dlg_path" not in body, body
    assert ".get()" not in body, body


def test_the_lips_tab_hands_over_plain_values(app, tmp_path):
    """Everything the worker needs is read on the main thread and passed."""
    source = tmp_path / "talk.dlg"
    source.write_bytes(_a_dialogue(["A line to say.", "And another."]))
    app.dlg_path.set(str(source))
    app.out_dir.set(str(tmp_path / "out"))
    app.lip_assign.set(True)
    app.lip_replies.set(False)
    app.lip_force_on.set(False)

    app._lips_start()
    app.worker.join(timeout=30)
    assert not app.worker.is_alive()

    kinds = _drain(app)
    assert "error" not in kinds, kinds.get("error")
    written = list((tmp_path / "out" / "lips_talk").glob("*.lip"))
    assert len(written) == 2


def test_a_lips_run_is_kept_as_a_build(app, tmp_path):
    """So it installs through the same guarded path as everything else, rather
    than being a folder the modder copies by hand."""
    from kmdlfun import builds as kbuilds

    source = tmp_path / "talk.dlg"
    source.write_bytes(_a_dialogue(["A line to say.", "And another."]))
    app.dlg_path.set(str(source))
    app.out_dir.set(str(tmp_path / "out"))
    app.lip_force_on.set(False)

    app._lips_start()
    app.worker.join(timeout=30)
    _drain(app)

    build = kbuilds.load(tmp_path / "out" / "lips_talk")
    assert build is not None, "not adopted"
    assert build.manifest["kind"] == "lips"
    assert build.manifest["lines"] == 2
    assert build.manifest["dialogue"] == "talk.dlg"


def test_forcing_a_length_reaches_the_job(app, tmp_path):
    from pykotor.resource.formats.lip import read_lip

    source = tmp_path / "talk.dlg"
    source.write_bytes(_a_dialogue(["Short."]))
    app.dlg_path.set(str(source))
    app.out_dir.set(str(tmp_path / "out"))
    app.lip_force_on.set(True)
    app.lip_seconds.set(6.5)

    app._lips_start()
    app.worker.join(timeout=30)
    _drain(app)

    lip = next((tmp_path / "out" / "lips_talk").glob("*.lip"))
    assert read_lip(lip.read_bytes()).length == pytest.approx(6.5)


def test_the_progress_it_reports_knows_its_own_total(app, tmp_path):
    """A bar counting towards zero divides by a guard and sits at 100%."""
    source = tmp_path / "talk.dlg"
    source.write_bytes(_a_dialogue(["One.", "Two.", "Three."]))
    app.dlg_path.set(str(source))
    app.out_dir.set(str(tmp_path / "out"))
    app.lip_force_on.set(False)

    app._lips_start()
    app.worker.join(timeout=30)

    seen = _drain(app)
    totals = {payload[1] for payload in seen.get("progress", [])}
    assert totals == {3}, totals


def _a_dialogue(texts):
    from pykotor.common.language import LocalizedString
    from pykotor.common.misc import ResRef
    from pykotor.resource.formats.gff import GFF, GFFList, bytes_gff

    gff = GFF()
    items = gff.root.set_list("EntryList", GFFList())
    for i, text in enumerate(texts):
        struct = items.add(i)
        struct.set_locstring("Text", LocalizedString.from_english(text))
        struct.set_resref("VO_ResRef", ResRef(""))
    return bytes_gff(gff)


def _drain(app):
    import queue as _queue

    seen: dict = {}
    while True:
        try:
            kind, payload = app.events.get_nowait()
        except _queue.Empty:
            return seen
        seen.setdefault(kind, []).append(payload)


# --- importing a .glb -------------------------------------------------------
#
# The route in for geometry the game never had. Confirmed in game: a
# Tripo-generated head on Carth turns with the neck and opens its mouth. It was
# command-line only, which meant the window could not do the thing the project
# was originally built to do.


def test_the_custom_head_tab_offers_an_import(app):
    from tkinter import ttk

    page = None
    for i in range(len(app.tabs.tabs())):
        if app.tabs.tab(i, "text") == "Custom head":
            page = app.tabs.nametowidget(app.tabs.tabs()[i])
    assert page is not None

    labels = [w.cget("text") for w in page.winfo_children()
              if isinstance(w, ttk.Button)]
    assert any("glb" in text.lower() for text in labels), labels


def test_importing_selects_the_pack_it_just_made(app, tmp_path):
    """The next thing anyone does with a pack is build it. Leaving the path to
    be retyped is the step that gets skipped and then blamed on the importer."""
    source = tmp_path / "head.glb"
    source.write_bytes(_a_glb())
    out = str(tmp_path / "pack")

    app.pack_dir.set("")
    app._import_work(str(source), out)
    from pathlib import Path

    kind, payload = app.events.get_nowait()
    assert kind == "imported", payload
    pack, lines = payload
    assert pack == out
    assert (Path(out) / "head.obj").is_file()
    assert any("vertices" in line for line in lines)


def test_a_bad_file_reaches_the_log_rather_than_the_console(app, tmp_path):
    bad = tmp_path / "bad.glb"
    bad.write_bytes(b"not a glb at all" * 8)

    app._import_work(str(bad), str(tmp_path / "pack"))

    kind, payload = app.events.get_nowait()
    assert kind == "error", payload


def test_the_import_worker_touches_no_tk_variable(app):
    import inspect

    from kmdlfun import gui as kgui

    body = inspect.getsource(kgui.App._import_work)
    assert ".get()" not in body, body
    assert "self.pack_dir" not in body, body


def _a_glb():
    from test_gltf import build_glb, simple

    doc, blob = simple([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                       [(0, 1, 2)],
                       uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])
    return build_glb(doc, blob)


# --- the character tab ------------------------------------------------------
#
# Pick a body, an outfit and a head. No geometry is written: a KOTOR humanoid
# is a base body, a clothed body per equipment slot and a row of heads.2da, and
# all three already exist for anything the game ships.


@pytest.fixture
def stocked(app, install_path):
    """The tab with a real catalogue in it, loaded synchronously."""
    from kmdlfun import wardrobe as kw
    from kmdlfun.library import ModelLibrary

    app.install.set(install_path)
    app._show_catalogue(kw.build(install_path,
                                 library=ModelLibrary(install_path)))
    return app


def test_the_tab_is_there_and_has_three_pickers(app):
    from kmdlfun.gui import PART_KINDS

    names = [app.tabs.tab(i, "text") for i in range(len(app.tabs.tabs()))]
    assert "Character" in names
    assert set(app.part_gallery) == set(PART_KINDS)


def test_the_pickers_fill_from_the_install(stocked):
    assert len(stocked.part_labels["body"]) > 20
    assert len(stocked.part_labels["outfit"]) > 80
    assert len(stocked.part_labels["head"]) > 90


def test_picking_a_body_dresses_it_and_gives_it_a_face(stocked):
    """Somebody who only picks a body should still end up with a character,
    not a naked headless one."""
    label = next(k for k, v in stocked.part_labels["body"].items()
                 if v == "P_CarthBB")
    stocked._on_part_pick("body", label)

    assert stocked.part_pick["body"].get() == "P_CarthBB"
    assert stocked.part_pick["outfit"].get(), "left undressed"
    assert stocked.part_pick["head"].get(), "left headless"


def test_what_the_game_already_pairs_is_marked_and_comes_first(stocked):
    from kmdlfun.gui import SEEN_IN_GAME

    label = next(k for k, v in stocked.part_labels["body"].items()
                 if v == "P_CarthBB")
    stocked._on_part_pick("body", label)

    heads = list(stocked.part_labels["head"])
    assert heads[0].startswith(SEEN_IN_GAME), heads[0]
    assert any(not h.startswith(SEEN_IN_GAME) for h in heads), (
        "everything was marked, so the mark says nothing"
    )


def test_a_combination_the_game_never_ships_is_still_offered(stocked):
    """Forbidding those would forbid the reason to open the tool."""
    body = next(k for k, v in stocked.part_labels["body"].items()
                if v == "N_TwilekF")
    stocked._on_part_pick("body", body)

    assert "p_CarthH" in stocked.part_labels["head"].values()


def test_an_odd_combination_says_so_rather_than_waiting_for_the_game(stocked):
    body = next(k for k, v in stocked.part_labels["body"].items()
                if v == "N_TwilekF")
    stocked._on_part_pick("body", body)
    head = next(k for k, v in stocked.part_labels["head"].items()
                if v == "p_CarthH")
    stocked._on_part_pick("head", head)

    assert "Nothing in the game pairs" in stocked.character_warn.cget("text")


def test_a_pairing_the_game_ships_is_not_warned_about(stocked):
    body = next(k for k, v in stocked.part_labels["body"].items()
                if v == "P_CarthBB")
    stocked._on_part_pick("body", body)
    head = next(k for k, v in stocked.part_labels["head"].items()
                if v == "p_CarthH")
    stocked._on_part_pick("head", head)

    assert stocked.character_warn.cget("text") == ""


def test_the_wardrobe_can_be_filtered_by_sex(stocked):
    """An outfit is a body model and has a sex the same way a body does. This
    is the filter that silently emptied before the catalogue classified them."""
    stocked.part_filter_outfit.set("female")
    stocked._refresh_parts("outfit")
    female = len(stocked.part_labels["outfit"])

    stocked.part_filter_outfit.set(ANYONE_LABEL())
    stocked._refresh_parts("outfit")
    everyone = len(stocked.part_labels["outfit"])

    assert 0 < female < everyone


def ANYONE_LABEL():
    from kmdlfun.gui import ANYONE

    return ANYONE


def test_creating_needs_a_body_and_a_resref(stocked):
    stocked.said = []
    stocked._say = lambda text: stocked.said.append(text)

    stocked.part_pick["body"].set("")
    stocked._character_start()
    assert any("body" in s for s in stocked.said)

    stocked.part_pick["body"].set("N_CommM")
    stocked.new_resref.set("")
    stocked.new_name.set("")
    stocked.said = []
    stocked._character_start()
    assert any("resref" in s for s in stocked.said)


def test_creating_writes_the_rows_and_the_blueprint(stocked, tmp_path):
    from kmdlfun import builds as kbuilds

    stocked._character_work(stocked.install.get(), str(tmp_path), dict(
        resref="vex", name="Vex", kind="talker",
        body="N_CommM", outfit="N_CzerkaOff", head="p_carthh"))

    kinds = {}
    while True:
        try:
            kind, payload = stocked.events.get_nowait()
        except Exception:
            break
        kinds.setdefault(kind, []).append(payload)
    assert "error" not in kinds, kinds.get("error")

    folder = tmp_path / "character_vex"
    assert (folder / "appearance.2da").is_file()
    assert (folder / "vex.utc").is_file()

    build = kbuilds.load(folder)
    assert build is not None and build.manifest["kind"] == "character"
    assert build.manifest["body"] == "N_CommM"


def test_the_character_workers_touch_no_tk_variable(app):
    """Tkinter is not thread-safe, and a worker reading a Tk variable survives
    only while the main loop happens to be spinning."""
    import inspect

    from kmdlfun import gui as kgui

    body = inspect.getsource(kgui.App._character_work)
    assert ".get()" not in body, body

    # The drawing worker reads its inputs before the thread starts.
    drawn = inspect.getsource(kgui.App._draw_character)
    worker = drawn[drawn.index("def work()"):]
    assert ".get()" not in worker, worker
