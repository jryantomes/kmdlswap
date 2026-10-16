"""Re-store GUI textures bottom row first, the order the party screens draw.

The engine ignores a TGA's origin flag and takes the rows in file order. For
the model texture the first row had to be the top of the image, because that is
how its UVs sample it. The GUI is the other way: every vanilla portrait TPC
stores its bottom row first, and the party selection screen draws the first
row at the bottom. A portrait written top row first, as these were, shows
upside down there.

This rewrites each named TGA with its rows reversed in the file and the header
flag set to the standard bottom-up origin, so Pillow and any other reader that
honours the flag still see the same upright image.

usage: gui_bottom_up.py <tga> [<tga> ...]
"""
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def main(paths):
    for path in map(Path, paths):
        before = np.asarray(Image.open(path).convert("RGBA"))
        h, w = before.shape[:2]
        with open(path, "wb") as fh:
            fh.write(struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, w, h, 32, 0x08))
            fh.write(before[::-1][:, :, [2, 1, 0, 3]].astype(np.uint8).tobytes())
        after = np.asarray(Image.open(path).convert("RGBA"))
        raw = path.read_bytes()
        first_row = np.frombuffer(raw, np.uint8, w * 4, 18).reshape(w, 4)[:, [2, 1, 0, 3]]
        print(f"{path.name:16s} {w}x{h} descriptor {raw[17]:#04x}  "
              f"reads back identical {np.array_equal(before, after)}  "
              f"first row in file is the image's bottom row {np.array_equal(first_row, before[-1])}")


if __name__ == "__main__":
    main(sys.argv[1:])
