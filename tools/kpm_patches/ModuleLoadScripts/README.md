# Module Load Scripts (KotOR I 1.03)

A Kotor Patch Manager patch, not tied to any mod. After a module's own load script
(`module.ifo` `Mod_OnModLoad`), it runs every script `modloadscripts.2da` names for that
module, with the module as `OBJECT_SELF`, the way the game runs the module's own.

| module      | script        |                         |
|-------------|---------------|-------------------------|
| `ebo_m12aa` | `hcw_work`    | one row per script      |
| `all`       | `some_script` | `all`: every module     |

**Why:** a save keeps the `module.ifo` (and `.git`, `.are`) of every module it has visited, and
loads that copy. A mod that points `Mod_OnModLoad` at its own script never reaches a game that
has already been to the module (harness, 2026-10-08). A module also has only one load script,
so two mods that both want it overwrite each other. Rows in this table work in old and new
games alike, and any number of mods can add them.

**For a mod:** ship an empty `modloadscripts.2da` (columns `module`, `script`; it's in the
patch's additional files) with an install-if-missing `FileN=` in `[InstallList]`. Then add your
row in `[2DAList]` with `AddRow` and `ExclusiveColumn=script`.

Notes:
- Not `*` for every module: K1 reads a 2DA cell that starts with `*` as blank, as with `****`.
  A blank module cell is skipped.
- Module names are compared case-insensitively.
- Logging: create an empty `modloadscripts.log` beside `swkotor.exe` and the patch appends what
  it ran. It also writes to the debug output (DebugView), which can drop lines.

Hook: `CSWSModule::EventHandler`, the module-load case (event 0x11) at `0x004C5215`
(`mov ecx,[esi+0x20]; add esi,0xC0`). The patch runs that `RunScript` itself, then the table's
rows, and continues at `0x004C5417`, where the game's own call returns.

Build: `python ../build.py ModuleLoadScripts` puts `builds/kpm/ModuleLoadScripts.kpatch` and its
additional files there. The DLL links the Patch Manager's GameAPI library (MIT,
`LICENSE-KotorPatchManager.txt`).

Tested in the harness mirror (flow plans `modloadkp`, `hubprobe`):
- a save whose stored Hawk had no hook;
- a missing table;
- a blank row;
- a row for another module;
- `all`;
- both a save load and a move into a stored module.
