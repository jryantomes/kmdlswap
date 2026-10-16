"""A .gui scaled to another size of the same shape: every EXTENT (LEFT, TOP, WIDTH, HEIGHT) and
border/highlight DIMENSION and INNEROFFSET times a factor, rounded. KMRP 1.5.1 stores its party screen
at four sizes and blends the rest at run time; its 16:9 one (2880x1620) times 8/9 gives 2560x1440
(2026-10-16: KMRP 1.5.1 lets an Override .gui through, so a party screen made here is used as is).

    scale_gui.py <in gui> <out gui> <factor>
"""
import sys
from fractions import Fraction

from pykotor.resource.formats.gff import GFFList, GFFStruct, bytes_gff, read_gff

PIXELS = {"EXTENT": ("LEFT", "TOP", "WIDTH", "HEIGHT"),
          "BORDER": ("DIMENSION", "INNEROFFSET"), "HILIGHT": ("DIMENSION", "INNEROFFSET"),
          "HILIGHTSELECTED": ("DIMENSION", "INNEROFFSET"), "SELECTED": ("DIMENSION", "INNEROFFSET")}


def scale(s, f, name=""):
    for label, _ftype, val in list(s):
        if isinstance(val, GFFStruct):
            scale(val, f, label)
        elif isinstance(val, GFFList):
            for x in val:
                scale(x, f, label)
        elif label in PIXELS.get(name, ()) and isinstance(val, int):
            s.set_int32(label, int(round(val * f)))


def main(argv):
    g = read_gff(open(argv[0], "rb").read())
    scale(g.root, float(Fraction(argv[2])))
    open(argv[1], "wb").write(bytes_gff(g))


if __name__ == "__main__":
    main(sys.argv[1:])
