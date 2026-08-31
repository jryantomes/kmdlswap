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
    assert "n_quarren" in app.donor_box.cget("values")

    app.out_dir.set(str(tmp_path))
    app.host.set("p_carthh")
    app.donor.set("n_quarren")
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
