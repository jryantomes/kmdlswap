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

1. ~~**Offset-field table completeness**~~ — **RETIRED.** Offset closure holds on
   2832/2832 vanilla models, so no live pointer is unaccounted for, and the
   splice's shift logic is now confirmed by the engine itself: a resize probe
   that moved ~494 pointers loaded, rendered and animated correctly in-game
   (see [`reports/MILESTONE_2_FINDINGS.md`](../reports/MILESTONE_2_FINDINGS.md)).
   On closure failure we still *refuse* the model rather than guess.
2. ~~**`bonemap` semantics**~~ — **RESOLVED.** One float per *geometry node*, in
   node order, giving that node's slot in qbones/tbones (`-1` = not a bone).
   Indexed by node, not vertex, so it does **not** resize with a geometry swap;
   bonemap/qbones/tbones all pass through untouched. Also resolved: the skin
   subheader's 16-slot bone table is not the per-mesh limit and its unused
   entries are garbage — never read it. See
   [`reports/SKINNING_FINDINGS.md`](../reports/SKINNING_FINDINGS.md).
3. ~~**Array alignment rule**~~ — **RESOLVED.** MDL arrays have *no* alignment
   requirement: start offsets are uniform mod 16 and the corpus has zero coverage
   gaps, so arrays are packed contiguously with no padding. MDX is different -
   all 76,703 block starts are 8-byte aligned - so a resized block is zero-padded
   to preserve its size mod 8. Matters for strides 60/68/76/100 (4 mod 8).
4. ~~**MDX trailing dummy vertex**~~ — **RESOLVED.** Detected from block size vs
   `vertex_count x stride`; contents preserved verbatim (see item 11).
5. **`mdx_data_buffer_offset`** (model header 0xAC) — purpose unclear; shift
   conservatively, verify against corpus identity.
6. ~~**Shared array spans**~~ — **RESOLVED: none exist.** Zero overlaps across
   the whole corpus, so a splice never needs ref-counting.

8. **Positions are stored twice** — in the MDX stream *and* in an MDL-side `vec3`
   array. They agree byte-for-byte in vanilla; a swap must write both. *(Handled
   in `edit.replace_geometry`.)*

9. ~~**Face adjacency must be rebuilt for new geometry**~~ — **IMPLEMENTED** in
   `topology.build_adjacency`: edges `(v0,v1),(v1,v2),(v2,v0)`, vertices welded
   by position, matched as directed half-edges. Reproduces 96.3% of vanilla
   adjacency exactly; the residual is likely a weld tolerance in the original
   compiler. `check_adjacency` asserts every value is in range or `0xFFFF`.

10. **Face `material`** is a small integer (1, 2, 3, … — smoothing-group-like).
    Semantics still unknown. New geometry inherits the value from the first face
    of the node being replaced, overridable with `--material`.

11. **The MDX trailing sentinel vertex.** Every block carries 1-2 extra vertex
    rows past `vertex_count`: position `(1e7, 1e7, 1e7)` or `(1e6, 1e6, 1e6)`,
    rest zeroed, and on skinned meshes `weight[0] = 1.0` with bone slot 0.
    Purpose undocumented; it does not depend on the geometry, so it is preserved
    verbatim rather than regenerated.
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
