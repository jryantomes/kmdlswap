"""What can this tool actually edit?

The design doc promised a support matrix and never produced one, so the refusals
lived scattered across the code: saber blades, meshes with MDX columns an OBJ
cannot express, models that fail validation. A user met them one model at a
time. This derives the whole picture from the corpus instead.

Every reason here is a real code path, not a guess:

* ``no_mdx``          - an MDL with no paired MDX; kmdlswap needs both.
* ``model_invalid``   - the parser cannot account for every byte or resolve every
                        pointer, so the model is refused outright.
* ``saber``           - lightsaber blade; geometry lives in MDL-side arrays
                        rather than the MDX stream.
* ``empty``           - a mesh node with no vertices.
* ``needs_uv2`` /
  ``needs_tangent`` /
  ``needs_colour``    - the stride carries a column an OBJ cannot author, so
                        ``build_replacement`` refuses rather than zero-fill it.
* ``swappable``       - everything else.

    python tools/support_matrix.py --install "<K1 root>"
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pykotor.extract.installation import Installation  # noqa: E402
from pykotor.resource.type import ResourceType  # noqa: E402

from kmdlfun import parts as kparts  # noqa: E402
from kmdlswap import layout as kl  # noqa: E402
from kmdlswap import mdx as kmdx  # noqa: E402
from kmdlswap import validate as kv  # noqa: E402
from kmdlswap.swap import AUTHORABLE  # noqa: E402

COLUMN_REASON = {
    "uv2": "needs_uv2",
    "uv3": "needs_uv2",
    "uv4": "needs_uv2",
    "tangent": "needs_tangent",
    "color": "needs_colour",
}


def classify_node(layout, node) -> str:
    if "saber" in node.flags:
        return "saber"
    if not node.vertex_count:
        return "empty"
    try:
        stride = kmdx.stride_layout(layout, node)
    except ValueError:
        return "stride_not_understood"
    extra = sorted(set(stride.columns) - AUTHORABLE)
    if extra:
        return COLUMN_REASON.get(extra[0], "needs_other_column")
    return "swappable"


def prefix_of(name: str) -> str:
    for p, label in (
        ("p_", "player/companion"),
        ("n_", "NPC"),
        ("c_", "creature"),
        ("w_", "weapon"),
        ("i_", "item"),
        ("plc_", "placeable"),
        ("d_", "door"),
        ("fx_", "effect"),
    ):
        if name.startswith(p):
            return label
    if name[:1] == "m" and name[1:3].isdigit():
        return "module/room"
    return "other"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", required=True)
    ap.add_argument("--report", default="reports/support_matrix.json")
    args = ap.parse_args(argv)

    inst = Installation(args.install)
    index: dict[str, dict] = {}
    for r in inst.chitin_resources():
        if r.restype() in (ResourceType.MDL, ResourceType.MDX):
            index.setdefault(r.resname().lower(), {})[r.restype()] = r

    node_reasons: Counter[str] = Counter()
    model_status: Counter[str] = Counter()
    by_category: dict[str, Counter] = {}
    visible_swappable = 0
    examples: dict[str, str] = {}

    names = sorted(index)
    for i, name in enumerate(names):
        entry = index[name]
        category = prefix_of(name)
        bucket = by_category.setdefault(category, Counter())

        if ResourceType.MDL not in entry or ResourceType.MDX not in entry:
            model_status["no_mdx"] += 1
            bucket["models_unusable"] += 1
            continue
        try:
            layout = kl.parse(entry[ResourceType.MDL].data(), entry[ResourceType.MDX].data())
            ok = kv.check(layout).ok
        except Exception:  # noqa: BLE001
            model_status["parse_failed"] += 1
            bucket["models_unusable"] += 1
            continue
        if not ok:
            model_status["model_invalid"] += 1
            bucket["models_unusable"] += 1
            continue

        model_status["usable"] += 1
        bucket["models_usable"] += 1
        for node in layout.nodes:
            if not node.is_mesh or node.in_animation is not None:
                continue
            reason = classify_node(layout, node)
            node_reasons[reason] += 1
            bucket[reason] += 1
            examples.setdefault(reason, f"{name}:{node.name}")
            if reason == "swappable" and kparts.renders(layout, node):
                visible_swappable += 1
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(names)} ...", file=sys.stderr)

    total_nodes = sum(node_reasons.values())
    summary = {
        "models": dict(model_status),
        "mesh_nodes_total": total_nodes,
        "mesh_nodes_by_reason": dict(node_reasons.most_common()),
        "mesh_nodes_swappable_pct": (
            round(100 * node_reasons["swappable"] / total_nodes, 2) if total_nodes else 0
        ),
        "swappable_and_visible": visible_swappable,
        "examples": examples,
        "by_category": {
            k: dict(v.most_common()) for k, v in sorted(by_category.items())
        },
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "by_category"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
