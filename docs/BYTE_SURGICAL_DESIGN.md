# Byte-surgical MDL/MDX handling — design & plan

Follow-up to [`reports/MILESTONE_0_FINDINGS.md`](../reports/MILESTONE_0_FINDINGS.md)
(PyKotor round-trips 0 / 2832 vanilla K1 models). This is the plan for our own
reader/writer.

## Principle

The original `.mdl` / `.mdx` are held as **immutable `bytes`**. We parse only the
*navigation structure* — never re-interpret or regenerate geometry. "Writing"
with no edits returns the originals verbatim, so the Milestone 0 acceptance test
(`load → re-emit → byte-diff`) passes **by construction**. Editing is a single
splice-and-fixup transaction that touches only the bytes it must, then re-validates
the whole file before emitting.

This matches the brief's core insight: *if you never change the node hierarchy,
you never have to understand it.* We go one step further — if you never
regenerate a region, you never have to reproduce its exact byte layout.

## Format facts already confirmed (from PyKotor's `io_mdl.py` + probing `p_hk47`)

| Thing | Detail |
|---|---|
| File wrapper | 12 bytes: `u32 = 0`, `u32 mdl_data_size` (= filelen−12), `u32 mdx_size`. **All MDL-internal offsets are relative to byte 12.** |
| Model header | at byte 12, 196 bytes = geometry header (80) + model fields. Holds `root_node_offset`, `node_count`, `offset_to_name_offsets` (+count ×2), `offset_to_animations` (+count ×2), `supermodel` (32B), `mdx_size`, `mdx_offset`, bbox, radius. |
| Geometry-header padding | 3 bytes of **uninitialised garbage** (`p_hk47`: `eb 1f 3d`). PyKotor normalises these to `31 96 bd` — one of its round-trip breakers. We pass them through. |
| Name array | `name_offsets_count` × `u32`, each → a NUL-terminated node-name string. |
| Node header | 80 bytes: `type_id` (u16 flag bits), `node_id`, `name_id`, `offset_to_root/parent/children/controllers/controller_data` + counts. |
| Node type flags | HEADER 1, LIGHT 2, EMITTER 4, REFERENCE 0x10, MESH 0x20, SKIN 0x40, DANGLY 0x100, AABB 0x200, SABER 0x800 (combine, e.g. skin node = 0x21|0x40). |
| Trimesh subheader | K1 fixed size; holds `offset_to_faces` (+count), `offset_to_indices_counts`, `offset_to_indices_offset`, `offset_to_counters`, `vertex_count`, `mdx_data_bitmap`, per-component MDX column offsets, `mdx_data_offset` (**MDX-space**), `vertices_offset` (**MDL-space**, a plain `vec3` array duplicating MDX positions). |
| Face struct | 32 bytes: normal `vec3`, plane `f32`, material `u32`, adjacency `3×u16`, vertex indices `3×u16`. |
| Skin subheader | 100 bytes after trimesh header; holds `offset_to_mdx_weights` / `offset_to_mdx_bones` (byte offsets *within* the MDX vertex stride), `offset_to_bonemap` (+count), `offset_to_qbones` (+count), `offset_to_tbones` (+count), `offset_to_unknown0`, 16×`u16` bone node-index table. |
| MDX file | no header — concatenated per-mesh-node vertex blocks. Block = `vertex_count × stride`; `stride` from the bitmap / `mdx_data_size`. Some meshes carry a trailing dummy vertex. |
| Animations | array of (geometry header + own node sub-tree) at `offset_to_animations`. We never edit these, but their offset fields still shift under a splice. |

Unknowns to resolve empirically against the corpus — see *Risks* below.

## Module layout

```
src/kmdlswap/
  _io.py        struct primitives over bytes + cursor; BASE = 12 helper
  nodes.py      node-type flag constants; per-subheader field tables
  mdx.py        stride/bitmap decode; per-mesh block map
  layout.py     Layout / Span / OffsetField / CountField; parse_mdl_pair()
  validate.py   coverage, offset-closure, identity checks
  edit.py       replace_mesh_geometry() splice+fixup transaction
  inspect.py    Milestone 1 report
  obj.py        Milestone 3 OBJ read/write
  weights.py    Milestone 3 weight transfer (numpy)
  cli.py        (exists, stubbed)
tests/
  test_identity_corpus.py   parametrised over the install
  test_noop_swap.py
  fixtures/
```

## Layers

### 1. `_io.py` — primitives
LE `u8/u16/u32/i16/i32/f32/vec3/vec4/cstr(n)` over `bytes` with an explicit
cursor. `abs_off(v) = 12 + v` for MDL-internal offsets.

### 2. `layout.py` — structural parser
Produces a `Layout`:

- **`spans`** — ordered `Span(start, end, kind, owner_node)` covering *every*
  byte. `kind ∈ {file_header, model_header, name_array, name_string, node_header,
  children_array, controller_array, controller_data, trimesh_header,
  skin_header, dangly_header, aabb_tree, saber_data, light_data, emitter_data,
  reference_data, face_array, mdl_vertex_array, indices_counts, indices_offsets,
  vertexindices, counters, bonemap, qbones, tbones, skin_unknown0,
  anim_header, anim_node_*, padding, mdx_block, mdx_pad}`.
- **`offsets`** — `OffsetField(loc, space, value, expects_kind)` for *every*
  stored pointer, `space ∈ {MDL, MDX}`.
- **`counts`** — `CountField(loc, value, array_id)` (including the duplicate
  `_count2` fields).
- Indexes: `nodes_by_name`, `nodes_by_path` (exact casing, full parent path).

Parse order: file header → model header → name array + strings → node tree
(recursive: header, children array, subheaders by flag, then the node's data
arrays) → animation array. Subheader kinds we don't need yet are recorded as a
single opaque fixed-size span — identity still holds; we refine them later.

### 3. `validate.py` — the safety net
1. **Coverage** — every MDL byte in exactly one span; likewise MDX. Uncovered or
   overlapping ⇒ hard error (we refuse to edit a model we can't fully account for).
2. **Offset closure** — every `OffsetField` resolves to an exact span boundary of
   `expects_kind`.
3. **Identity** — re-serialising the span list equals the original bytes.

These run as the **Milestone 0 acceptance test** across the whole vanilla corpus
(`tools/roundtrip_eval.py --engine ours`). Target: 100% parse + identity on the
models we support (`p_* c_* n_*`); everything else classified in a support matrix,
not silently mishandled.

### 4. `edit.py` — the only mutation
`replace_mesh_geometry(pair, node_name, new_geo) -> MdlPair`:

1. Resolve the target node's spans + header fields.
2. Serialise replacement bytes: face array, MDL vertex array, vertexindices,
   MDX block (and, for skin nodes, the weight/bone columns inside the stride).
3. Ascending-offset splice. For each changed span record `(splice_point, delta)`,
   rebuild the buffer, then:
   - every `OffsetField(space=MDL)` with `abs_value > splice_point` `+= delta`;
   - `file_header[4] += Σ mdl_delta`;
   - re-pad to the original array's alignment (preserve original pad bytes on
     shrink; synthesise zeros on grow — documented, in-game tested).
4. MDX: target block delta `d`. Every later mesh node `mdx_data_offset += d`;
   `file_header[8]`, `model_header.mdx_size` (and `mdx_data_buffer_offset` if it
   tracks total) `+= d`.
5. Patch the target node's own counts (`vertex_count`, `faces_count`+`_count2`,
   `indices_counts[i]`, `counters`, skin counts if vertex-indexed).
6. Re-run **all Layer 3 validators** on the result. Never emit unvalidated.

No-op case (`new_geo` == current) ⇒ all deltas 0 ⇒ output byte-identical: that is
Milestone 2.

## Milestone mapping

| MS | Deliverable | Acceptance |
|----|-------------|-----------|
| 0 | Layers 1–3 + identity writer | corpus parse+identity report ≈100% on `p_/c_/n_` |
| 1 | `inspect.py` report off `Layout` | readable `p_hk47` tree: names w/ casing + paths, mesh/skin flags, vtx/face counts, bones referenced, max influences seen in MDX, supermodel, bbox |
| 2 | `edit.replace_mesh_geometry` no-op path | `replace(extract(x)) == x` byte-exact **and** loads/animates in-game |
| 3 | real geometry + `weights.py` + `obj.py` | modified model renders/animates; + influence-cap experiment (1/2/4/8) |
| 4 | `cli.py` wires `inspect`/`extract`/`replace` | brief's CLI synopsis works end to end |

## Risks / unknowns (flag, don't block)

1. **Offset-field table completeness** — a missed pointer corrupts files silently
   in-game. Mitigation: offset-closure check + no-op swap + full corpus. On
   closure failure we *refuse* the model rather than guess.
2. **`bonemap` semantics** — per-bone remap vs per-vertex. Decides whether it
   resizes with vertex count. Verify: correlate `bonemap_count` with `vertex_count`
   vs bone count across the corpus.
3. **Array alignment rule** — 16-byte? 4-byte? per-type? Derive from inter-span
   gaps across the corpus. Growing needs synthesised padding (brief's known
   unknown — zeros, documented, in-game tested).
4. **MDX trailing dummy vertex** — detect from block-size vs `vertex_count×stride`.
5. **`mdx_data_buffer_offset`** (model header 0xAC) — purpose unclear; shift
   conservatively, verify against corpus identity.
6. **Shared array spans** — do two nodes ever point at one array? Coverage check
   flags overlap; if real, splice needs ref-counting.
7. **44 unreadable models** in PyKotor's run (`fx_*`, `m12a*`) — check whether our
   parser handles them or they're genuinely out of scope (not character models).

## First implementation session

1. `_io.py` + `layout.py`: file header, model header, name array, node tree
   (headers + children arrays only; subheaders as opaque spans).
2. `validate.identity()`; add `--engine ours` to `tools/roundtrip_eval.py`; drive
   structure-only identity to 100%.
3. Refine opaque spans → typed spans (trimesh, skin, faces, arrays, MDX),
   keeping identity green at every step.
4. Add coverage + offset-closure validators; run the corpus; build the support
   matrix.
