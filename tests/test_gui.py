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


def test_the_transplant_worker_never_reads_tk(app, tmp_path):
    """The regression test for the crash.

    With no main loop running, any Tk read from the worker raises "main thread
    is not in main loop". The fixture withdraws the window and never calls
    mainloop, so this fails if a setting is read across the boundary again.
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

    app._start(preview=True)
    pump(app)

    log = app.log.get("1.0", "end")
    assert "main thread is not in main loop" not in log
    assert "ERROR" not in log, log[-400:]
    assert "1/1 would transfer" in log


def test_the_preview_reports_donor_solidity(app, tmp_path):
    """Solidity is the single best predictor of whether a swap will look right,
    and nothing else in the preview can see it - a two-sided viewer shows an
    inside-out mesh as perfect."""
    transplant_tab(app)
    app.out_dir.set(str(tmp_path))
    app.host.set("p_carthh")
    app.donor.set("n_bith")
    app._start(preview=True)
    pump(app)

    log = app.log.get("1.0", "end")
    assert "solid 99%" in log
    assert "good" in log


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
