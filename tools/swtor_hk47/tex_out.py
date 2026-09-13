"""HK-47's diffuse out of the archive, with the reflection mask KOTOR wants.

The diffuse alone is not enough. Every vanilla droid texture is DXT5 and
declares `envmaptexture`, and the alpha channel is what says how much of that
environment map each pixel shows: bright is matte, dark is mirror. Shipped
without one, the engine reflects `mycube` at full strength over the whole
droid, which is what turned the head and every curved plate chrome grey in
game while the flat ones kept their colour.

The mask is built from The Old Republic's own gloss map, which shares the
diffuse's layout exactly, inverted because the two conventions run opposite
ways: bright gloss is a shiny pixel, and a shiny pixel wants dark alpha.
"""
import sys, io, struct
import numpy as np
from pathlib import Path
sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
from kmdlfun import swtor
from PIL import Image

ASSETS = Path(r"E:/SteamLibrary/steamapps/common/Star Wars - The Old Republic/Assets")
ARCHIVE = "swtor_main_art_creature_a_1.tor"
# Each asset is packed as model, material, three TextureObject files, then the
# small diffuse, normal and gloss, then the full sized three. The model sits at
# 200, so these are its own.
DIFFUSE_ENTRY = 208
GLOSS_ENTRY = 210


def read(index):
    arc = ASSETS / ARCHIVE
    with arc.open("rb") as fh:
        raw = swtor.read_block(fh, swtor.entries(arc)[index])
    if raw[:4] != b"DDS ":
        raise SystemExit(f"entry {index} is not a DDS")
    return Image.open(io.BytesIO(raw))


def write_tga(path, rgba):
    """A 32-bit TGA with its rows stored top down, and the header saying so.

    Pillow writes the other order, origin at the lower left, and the engine
    does not honour that flag: it takes the first row in the file as the top
    of the image whatever bit 5 says. A texture written Pillow's way therefore
    arrives in game mirrored top to bottom, which is what put a dark grey
    panel from the bottom of the atlas onto HK-47's head while the body, whose
    islands mirror onto other orange islands, stayed roughly the right colour.

    Written this way both readers agree: the flag is set for anything that
    respects it, and the row order already suits anything that does not.
    """
    h, w = rgba.shape[:2]
    header = struct.pack("<BBBHHBHHHHBB",
                         0,      # no image id
                         0,      # no colour map
                         2,      # uncompressed true colour
                         0, 0, 0,
                         0, 0,   # origin
                         w, h,
                         32,     # bits per pixel
                         0x28)   # 8 alpha bits, origin at the top left
    bgra = rgba[:, :, [2, 1, 0, 3]]
    with open(path, "wb") as fh:
        fh.write(header)
        fh.write(bgra.astype(np.uint8).tobytes())


def main(out):
    diffuse = read(DIFFUSE_ENTRY).convert("RGB")
    gloss = read(GLOSS_ENTRY).convert("RGB").resize(diffuse.size, Image.LANCZOS)
    rgb = np.asarray(diffuse)
    shine = np.asarray(gloss).astype(float).mean(axis=2)
    alpha = np.clip(255.0 - shine, 0, 255).astype(np.uint8)
    write_tga(out, np.dstack([rgb, alpha]))
    print(f"diffuse {diffuse.size}, gloss {gloss.size}")
    print(f"alpha min {alpha.min()} mean {alpha.mean():.1f} max {alpha.max()}")
    print("vanilla P_HK47_01 for comparison: min 0 mean 192.4 max 255")


main(sys.argv[1])
