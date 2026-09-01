"""Jade Empire's model format, read by somebody else's code.

**Provenance.** These four modules are taken unmodified from JadeBlender 6.6.0
("KotorBlender Fork"), by the KotorBlender contributors and the Jade
integration contributors, supplied to this project by its author on 2026-09-02.
GPL-3.0-or-later, the same licence as this project - which is the reason the
code can be used here at all rather than only its findings.

Only the format layer is vendored: `mdl`, `binary`, `specialized` and
`controllers` reach no further than each other and import no `bpy`. The rest of
the add-on - its Blender operators, its writers, its texture and walkmesh
conversion - is not here.

Do not edit these files. Anything this project needs on top of them belongs in
`kmdlfun/jade.py`, which is where the format is turned into the conventions the
rest of the tool uses.
"""

from .mdl import JadeModel, is_jade_mdl, parse_jade_mdl   # noqa: F401
