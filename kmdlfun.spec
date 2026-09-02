# PyInstaller build. Run it with:  pyinstaller kmdlfun.spec
#
# One *folder*, not one file. A one-file build unpacks itself to a temporary
# directory on every launch, and with numpy and Tk inside that is several
# seconds of nothing happening before the window appears - which reads as a
# hang. A folder starts immediately and zips to about the same size.
#
# What this has to carry, and why it is the size it is:
#
#   numpy    the geometry and every render
#   pykotor  2DA, GFF, LIP and TPC - the four formats this project does not
#            read itself, and the one dependency out of proportion to its use
#   Pillow   textures in and PNG out
#   tkinter  the window
#
# `kmdlfun.vendor.jade` is pure Python and comes along as ordinary source.

from PyInstaller.utils.hooks import collect_submodules

# pykotor resolves formats by resource type at runtime rather than importing
# them by name, so the analysis cannot see them and they have to be named.
hidden = collect_submodules("pykotor") + collect_submodules("kmdlfun") + \
         collect_submodules("kmdlswap")

analysis = Analysis(
    ["tools/app.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    # Test and build machinery has no business in a shipped app.
    excludes=["pytest", "_pytest", "pip", "setuptools", "PyInstaller",
              "matplotlib", "scipy", "IPython", "pygments"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="kmdlfun",
    debug=False,
    strip=False,
    upx=False,
    # No console: this is a window, and a black terminal behind it looks like
    # something went wrong. `tools/app.py` catches anything that would have
    # gone to stderr and shows it instead.
    console=False,
)

COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="kmdlfun",
)
