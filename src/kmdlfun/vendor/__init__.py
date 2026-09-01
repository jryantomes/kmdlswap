"""Third-party code, kept separate from ours and unmodified.

Nothing in here was written for this project. It is vendored rather than
depended on because the upstream is a Blender add-on: importing it normally
would pull in `bpy`, which does not exist outside Blender.

Each subpackage carries its own provenance note. All of it is
GPL-3.0-or-later, which is why this project is too.
"""
