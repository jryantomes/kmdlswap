"""Repair the broken f-string and the apply() call."""
from pathlib import Path

p = Path("src/kmdlfun/gui.py")
t = p.read_text(encoding="utf-8")

broken = '        self._say(f"\ninstalling build \'{build.name}\'")\n'
fixed = "        self._say(f\"\\ninstalling build '{build.name}'\")\n"
assert broken in t, "the damaged line moved"
t = t.replace(broken, fixed, 1)

# the earlier replacement left the argument list unbalanced
bad = "kinstall.apply(install, source))"
if bad in t:
    t = t.replace(bad, "kinstall.apply(install, source)", 1)
p.write_text(t, encoding="utf-8", newline="\n")

import ast
ast.parse(t)
print("syntax ok")

import re
for m in re.finditer(r"kinstall\.(apply|plan)\([^\n]*", t):
    print("  ", m.group(0))
