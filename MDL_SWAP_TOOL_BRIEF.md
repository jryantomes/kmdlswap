# Project Brief — KOTOR MDL Geometry Swap Tool

A scoped Python tool that replaces the geometry of a single mesh node inside a vanilla KOTOR 1 model, leaving everything else byte-identical.

**This is deliberately NOT a character creator.** It does one thing well.

---

## The core insight (read this first)

KOTOR's Odyssey engine has **no separate skeleton**. An MDL is a node tree where "bones" and "meshes" are the same kind of object — a node that happens to carry geometry versus one that doesn't. Skinning references node *names* in that tree, with per-node `qbone`/`tbone` matrices.

This is why every modern pipeline (FBX, glTF, Mixamo, Unreal, Unity) fails on KOTOR: they all assume mesh and skeleton are distinct entities, so importing a foreign rig requires reinterpreting one model as the other, and that reinterpretation is where everything breaks.

**The workaround that makes this project tractable:** if you never change the node hierarchy, you never have to understand it. Copy the vanilla node tree verbatim and replace only the geometry arrays inside one mesh node. Node names, casing, parent paths, sockets, supermodel references, controller arrays — all pass through untouched.

That turns an engine-reverse-engineering project into a data-manipulation project.

---

## Scope

**In scope:**
- Read/write K1 MDL + MDX as an exact round-trip
- Inspect and report the node tree
- Replace one mesh node's vertices / faces / UVs / normals
- Transfer skin weights from the original geometry to the new geometry
- A thin CLI

**Out of scope (do not build):**
- Any UI
- Adding, removing, renaming, or reparenting nodes
- Authoring animations
- KOTOR 2 support (K1 and K2 model data are **not** interchangeable — pick K1 and stay there)
- Anything that writes to the game install (output to a directory; the user installs manually)

---

## Milestones

Work strictly in order. **Do not begin a milestone until the previous one's acceptance criteria pass.**

### Milestone 0 — Byte-exact round-trip ⚠️ THE FOUNDATION

Read an MDL/MDX pair into a data model and write it back out.

**Acceptance:** load and re-emit **every character model in a vanilla K1 install** and diff byte-for-byte. Report pass/fail per model. A high pass rate on a large corpus is the only real proof the reader/writer is correct — far stronger than any spec document.

If models don't round-trip, **that is the project** until they do. Do not paper over it with "close enough."

*Rationale: this exact discipline — round-trip, then byte-diff untouched regions — is what made GFF/dialogue editing on this project safe and repeatable.*

### Milestone 1 — Inspect

Dump the node tree for a given model:
- Node names with **exact casing** and parent paths
- Which nodes carry meshes; vertex/face counts per node
- Which meshes are skinned, and which bones each references
- Max influences per vertex actually observed
- Supermodel name
- Bounding box

**Acceptance:** produce a readable report for `p_hk47` (and a few others) that a human can use to choose a target node.

### Milestone 2 — No-op swap ⚠️ PROVES THE MECHANISM

Extract one mesh node's geometry, put **the same geometry** back, write the model.

**Acceptance:** output is byte-identical to input, **and** the model loads and animates correctly in-game. Zero new variables — this isolates the rewrite mechanism from any content change.

### Milestone 3 — Geometry replacement ⚠️ THE REAL UNKNOWN

Replace a node's geometry with a supplied mesh (OBJ is the simplest input format; FBX only if trivial), rebuilding the skin arrays.

Weight transfer: for each new vertex, find the nearest point on the original mesh and inherit its bone influences (barycentric interpolation across the containing triangle is better than nearest-vertex).

**Acceptance:** a modified model that loads, renders, and animates without visible deformation errors.

**Empirical sub-task — max influences per vertex.** This is genuinely unknown (see below). Build variants capped at 1, 2, 4, and 8 influences; test each in-game; document what the engine accepts. **This finding is worth publishing back to the community regardless of whether the tool ships.**

### Milestone 4 — CLI

```
kmdlswap inspect <model.mdl>
kmdlswap extract <model.mdl> --node <name> --out mesh.obj
kmdlswap replace <model.mdl> --node <name> --mesh new.obj --out <dir>
```

---

## Known unknowns

These are unresolved in the community's reverse-engineering of Odyssey. Treat them as empirical questions, not blockers:

1. **Max influences per vertex** — unknown; discover by testing (see Milestone 3).
2. **Whether the engine normalizes skin weights** — unknown; normalize to 1.0 defensively.
3. **MDL header layout / controller arrays / MDX offset handling** — partially documented; PyKotor's implementation is the best available reference.
4. **Supermodel name resolution and resref case behavior** — unknown; **preserve exact casing** rather than guessing.
5. **Vertex-count ceilings per mesh node** — unknown. Vanilla K1 character models run ~2,000–4,000 triangles *total across all nodes*, so treat that as the practical budget and warn above it.

**Rule: when a behavior is unknown, preserve the vanilla value exactly rather than inventing one.**

---

## Foundations

- **PyKotor** (`github.com/OpenKotOR/PyKotor`, or via the Holocron Toolset install) — already reads and writes most KOTOR formats including MDL/MDX. **Start here rather than writing a parser from scratch.** First task is evaluating whether its MDL round-trip is byte-exact; if it is, Milestone 0 is nearly free.
- **A vanilla K1 install** is both the test corpus and the oracle. Every shipped model is a known-good example of what the engine accepts.
- Ghost Studio (`github.com/CrispyW0nton/Ghost-Studio`) has related prior art. Its `docs/` contain useful engine findings. Note its own capability matrix marks custom-character export as *Partial/Experimental* with "game-safe KOTOR hierarchy conversion **not proven**" — which is precisely why this tool avoids touching the hierarchy at all.

---

## Engineering constraints

- **Python 3.11+**, standard library plus PyKotor and numpy. No GUI dependencies.
- **Never write into the game install.** Output to a target directory.
- **Deterministic output** — identical inputs must produce identical bytes.
- **Test-first on real data.** Golden-file tests against vanilla models beat unit tests on synthetic fixtures.
- **Preserve unknown fields verbatim.** If a field's purpose isn't understood, round-trip it unchanged rather than reconstructing it.
- Fail loudly. A silently-wrong model that crashes the game hours later is far worse than a hard error at write time.

---

## Definition of done (v1)

A user can take `p_hk47.mdl`, replace the head mesh node with custom geometry of similar density, and get a model that loads in KOTOR 1 and animates correctly using HK-47's inherited animations.

**A successful file build is not proof.** In-game verification is the only acceptance test that counts.
