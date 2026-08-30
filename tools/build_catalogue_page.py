"""Build the browsable parts-bin page from the catalogue and the rendered previews.

Thumbnails are embedded as data URIs so the page is one self-contained file.

    python tools/build_catalogue_page.py --out catalogue/parts_bin.html
"""

from __future__ import annotations

import argparse
import base64
import html
import json
from collections import defaultdict
from pathlib import Path

PART_LABEL = {
    "head": "head",
    "neck": "neck",
    "torso": "torso",
    "limb": "limb",
    "hand": "hand",
    "foot": "foot",
}


def thumb_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def build(catalogue: dict, thumbs: Path) -> str:
    models = {m["name"]: m for m in catalogue["models"]}

    families = defaultdict(list)
    for m in catalogue["models"]:
        families[m["supermodel"]].append(m)

    # Case-insensitive donor pools: a swap never renames, so matching is a
    # pairing heuristic and casing should not split a pool.
    pools: dict[str, dict[str, set[str]]] = {}
    for fam, members in families.items():
        pool: dict[str, set[str]] = defaultdict(set)
        for m in members:
            for p in m["parts"]:
                if p["visible"] and p["swappable"]:
                    pool[p["node"].lower()].add(m["name"])
        pools[fam] = pool

    ordered = sorted(families.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    total_models = len(models)
    total_parts = sum(
        1 for m in catalogue["models"] for p in m["parts"] if p["visible"] and p["swappable"]
    )

    cards = []
    for fam, members in ordered:
        members = sorted(members, key=lambda m: -sum(
            p["triangles"] for p in m["parts"] if p["visible"]
        ))
        pool = pools[fam]
        shared = {k: v for k, v in pool.items() if len(v) >= 2}

        items = []
        for m in members:
            vis = [p for p in m["parts"] if p["visible"]]
            tris = sum(p["triangles"] for p in vis)
            swappable = [p for p in vis if p["swappable"]]
            classes = sorted({p["part"] for p in swappable if p["part"]})
            interchangeable = sum(
                1 for p in swappable if len(pool.get(p["node"].lower(), ())) >= 2
            )
            png = thumbs / f"{m['name']}.png"
            img = (
                f'<img src="{thumb_uri(png)}" alt="{html.escape(m["name"])}" loading="lazy">'
                if png.is_file()
                else '<div class="missing">no preview</div>'
            )
            chips = "".join(
                f'<span class="chip chip--{c}">{PART_LABEL.get(c, c)}</span>' for c in classes
            )
            skinned = sum(1 for p in vis if p["skinned"])
            items.append(f"""
        <article class="card" data-name="{html.escape(m['name'])}" data-parts="{' '.join(classes)}">
          <div class="thumb">{img}</div>
          <div class="meta">
            <h3>{html.escape(m['name'])}</h3>
            <dl class="stats">
              <div><dt>tris</dt><dd>{tris:,}</dd></div>
              <div><dt>meshes</dt><dd>{len(vis)}</dd></div>
              <div><dt>skinned</dt><dd>{skinned}</dd></div>
              <div><dt>shared</dt><dd>{interchangeable}</dd></div>
            </dl>
            <div class="chips">{chips or '<span class="chip chip--none">unclassified</span>'}</div>
          </div>
        </article>""")

        top = sorted(shared.items(), key=lambda kv: -len(kv[1]))[:8]
        bin_rows = "".join(
            f'<li><code>{html.escape(node)}</code><span>{len(who)}</span></li>'
            for node, who in top
        )
        cards.append(f"""
    <section class="family" data-family="{html.escape(fam)}">
      <header class="family-head">
        <div>
          <p class="eyebrow">supermodel</p>
          <h2>{html.escape(fam)}</h2>
        </div>
        <p class="family-count"><strong>{len(members)}</strong> models &middot;
           <strong>{len(shared)}</strong> interchangeable parts</p>
      </header>
      {'<ul class="parts-bin">' + bin_rows + '</ul>' if bin_rows else
       '<p class="empty">No part appears in two or more of these models — nothing to swap between them.</p>'}
      <div class="grid">{''.join(items)}</div>
    </section>""")

    return PAGE.replace("{{TOTAL_MODELS}}", str(total_models)) \
               .replace("{{TOTAL_PARTS}}", f"{total_parts:,}") \
               .replace("{{FAMILIES}}", str(len(families))) \
               .replace("{{CARDS}}", "".join(cards))


PAGE = """<title>KOTOR Parts Bin</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
  :root {
    --ground: #EDEFF3;
    --panel: #FFFFFF;
    --tile: #DFE3EA;
    --line: #CDD3DD;
    --ink: #141A21;
    --ink-soft: #5A6472;
    --ink-faint: #838D9C;
    --amber: #A96A0C;
    --amber-soft: #F0E0C4;
    --cyan: #1E7C92;
    --cyan-soft: #D6EAEF;
    --shadow: 0 1px 2px rgba(20, 26, 33, .06), 0 8px 24px rgba(20, 26, 33, .05);
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --ground: #0F1419;
      --panel: #161D26;
      --tile: #1F2833;
      --line: #2B3644;
      --ink: #E6EBF2;
      --ink-soft: #9AA6B6;
      --ink-faint: #6E7B8C;
      --amber: #E8A33D;
      --amber-soft: #3A2C14;
      --cyan: #4FB3C7;
      --cyan-soft: #14303A;
      --shadow: 0 1px 2px rgba(0, 0, 0, .4), 0 10px 28px rgba(0, 0, 0, .35);
    }
  }
  :root[data-theme="dark"] {
    --ground: #0F1419;
    --panel: #161D26;
    --tile: #1F2833;
    --line: #2B3644;
    --ink: #E6EBF2;
    --ink-soft: #9AA6B6;
    --ink-faint: #6E7B8C;
    --amber: #E8A33D;
    --amber-soft: #3A2C14;
    --cyan: #4FB3C7;
    --cyan-soft: #14303A;
    --shadow: 0 1px 2px rgba(0, 0, 0, .4), 0 10px 28px rgba(0, 0, 0, .35);
  }

  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--ground);
    color: var(--ink);
    font-family: "IBM Plex Sans", ui-sans-serif, system-ui, sans-serif;
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 40px 24px 96px; }

  header.top { border-bottom: 1px solid var(--line); padding-bottom: 28px; margin-bottom: 32px; }
  .eyebrow {
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-size: .72rem; letter-spacing: .14em; text-transform: uppercase;
    color: var(--amber); margin: 0 0 6px;
  }
  h1 {
    font-family: "Chakra Petch", ui-sans-serif, sans-serif;
    font-weight: 700; font-size: clamp(1.9rem, 4vw, 2.7rem);
    margin: 0 0 10px; letter-spacing: -.01em; text-wrap: balance;
  }
  .lede { margin: 0; max-width: 62ch; color: var(--ink-soft); font-size: 1.02rem; }

  .summary { display: flex; flex-wrap: wrap; gap: 28px; margin-top: 24px; }
  .summary div { display: flex; flex-direction: column; }
  .summary dt, .summary .k {
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-size: .7rem; letter-spacing: .12em; text-transform: uppercase; color: var(--ink-faint);
  }
  .summary .v {
    font-family: "Chakra Petch", sans-serif; font-weight: 600;
    font-size: 1.7rem; font-variant-numeric: tabular-nums; line-height: 1.1;
  }

  .controls {
    position: sticky; top: 0; z-index: 5;
    display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
    padding: 14px 0; margin-bottom: 8px;
    background: var(--ground); border-bottom: 1px solid var(--line);
  }
  .controls input {
    flex: 1 1 220px; min-width: 180px;
    padding: 9px 12px; border-radius: 7px;
    border: 1px solid var(--line); background: var(--panel); color: var(--ink);
    font-family: "IBM Plex Mono", monospace; font-size: .86rem;
  }
  .controls input:focus-visible, .filter:focus-visible {
    outline: 2px solid var(--amber); outline-offset: 2px;
  }
  .filter {
    padding: 7px 13px; border-radius: 999px; cursor: pointer;
    border: 1px solid var(--line); background: var(--panel); color: var(--ink-soft);
    font-family: "IBM Plex Mono", monospace; font-size: .76rem;
    letter-spacing: .04em; transition: background .15s, color .15s, border-color .15s;
  }
  .filter:hover { border-color: var(--amber); color: var(--ink); }
  .filter[aria-pressed="true"] {
    background: var(--amber); border-color: var(--amber); color: var(--ground); font-weight: 500;
  }

  .family { margin-top: 44px; }
  .family-head {
    display: flex; flex-wrap: wrap; gap: 12px;
    align-items: flex-end; justify-content: space-between;
    padding-bottom: 12px; border-bottom: 2px solid var(--ink);
  }
  .family-head h2 {
    font-family: "Chakra Petch", sans-serif; font-weight: 600;
    font-size: 1.45rem; margin: 0; letter-spacing: -.005em;
  }
  .family-count { margin: 0; color: var(--ink-soft); font-size: .9rem; }
  .family-count strong { color: var(--ink); font-variant-numeric: tabular-nums; }

  .parts-bin {
    list-style: none; display: flex; flex-wrap: wrap; gap: 6px;
    padding: 14px 0 0; margin: 0 0 18px;
  }
  .parts-bin li {
    display: flex; align-items: baseline; gap: 7px;
    padding: 4px 9px; border-radius: 6px;
    background: var(--cyan-soft); border: 1px solid var(--line);
  }
  .parts-bin code {
    font-family: "IBM Plex Mono", monospace; font-size: .78rem; color: var(--ink);
  }
  .parts-bin span {
    font-family: "IBM Plex Mono", monospace; font-size: .72rem;
    color: var(--cyan); font-weight: 500; font-variant-numeric: tabular-nums;
  }
  .empty { color: var(--ink-faint); font-size: .9rem; margin: 12px 0 18px; }

  .grid {
    display: grid; gap: 14px;
    grid-template-columns: repeat(auto-fill, minmax(184px, 1fr));
  }
  .card {
    background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
    overflow: hidden; box-shadow: var(--shadow);
    display: flex; flex-direction: column;
    transition: transform .16s ease, border-color .16s ease;
  }
  .card:hover { transform: translateY(-2px); border-color: var(--amber); }
  .thumb {
    background: var(--tile); display: grid; place-items: center;
    aspect-ratio: 2 / 3; border-bottom: 1px solid var(--line);
  }
  .thumb img { max-width: 100%; max-height: 100%; display: block; }
  .missing { color: var(--ink-faint); font-size: .78rem; font-family: "IBM Plex Mono", monospace; }
  .meta { padding: 11px 12px 13px; display: flex; flex-direction: column; gap: 9px; }
  .meta h3 {
    margin: 0; font-family: "IBM Plex Mono", monospace;
    font-size: .84rem; font-weight: 500; color: var(--ink); word-break: break-all;
  }
  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; margin: 0; }
  .stats div { display: flex; flex-direction: column; }
  .stats dt {
    font-family: "IBM Plex Mono", monospace; font-size: .6rem;
    letter-spacing: .08em; text-transform: uppercase; color: var(--ink-faint);
  }
  .stats dd {
    margin: 0; font-family: "IBM Plex Mono", monospace; font-size: .82rem;
    font-variant-numeric: tabular-nums; color: var(--ink);
  }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip {
    font-family: "IBM Plex Mono", monospace; font-size: .64rem;
    padding: 2px 7px; border-radius: 4px;
    background: var(--amber-soft); color: var(--amber); border: 1px solid transparent;
  }
  .chip--none { background: transparent; color: var(--ink-faint); border-color: var(--line); }

  .note {
    margin-top: 56px; padding: 20px 22px; border-radius: 10px;
    background: var(--panel); border: 1px solid var(--line);
    border-left: 3px solid var(--amber);
  }
  .note h2 {
    font-family: "Chakra Petch", sans-serif; font-size: 1.05rem; margin: 0 0 8px; font-weight: 600;
  }
  .note p { margin: 0 0 8px; color: var(--ink-soft); font-size: .93rem; max-width: 68ch; }
  .note p:last-child { margin-bottom: 0; }
  .note strong { color: var(--ink); }

  .hidden { display: none !important; }
  @media (prefers-reduced-motion: reduce) {
    * { transition: none !important; }
  }
</style>

<div class="wrap">
  <header class="top">
    <p class="eyebrow">kmdlswap &middot; vanilla K1 corpus</p>
    <h1>KOTOR Parts Bin</h1>
    <p class="lede">Every character model in the game, grouped by the skeleton it inherits.
      Models sharing a supermodel already agree on most node names, which is what lets geometry
      move between them without touching the hierarchy.</p>
    <div class="summary">
      <div><span class="k">models</span><span class="v">{{TOTAL_MODELS}}</span></div>
      <div><span class="k">supermodel families</span><span class="v">{{FAMILIES}}</span></div>
      <div><span class="k">swappable meshes</span><span class="v">{{TOTAL_PARTS}}</span></div>
    </div>
  </header>

  <div class="controls">
    <input id="search" type="search" placeholder="filter by model name, e.g. bastila" aria-label="Filter by model name">
    <button class="filter" data-part="head" aria-pressed="false">head</button>
    <button class="filter" data-part="torso" aria-pressed="false">torso</button>
    <button class="filter" data-part="limb" aria-pressed="false">limb</button>
    <button class="filter" data-part="hand" aria-pressed="false">hand</button>
    <button class="filter" data-part="foot" aria-pressed="false">foot</button>
  </div>

  {{CARDS}}

  <div class="note">
    <h2>What this does and does not prove</h2>
    <p>Counts cover <strong>visible, swappable</strong> meshes only — invisible skeleton boxes and
      meshes carrying MDX columns an OBJ cannot express are excluded. <em>Shared</em> is the number of
      a model's parts that at least one other model in the family also has.</p>
    <p>Sharing a node name and a skeleton is <strong>not</strong> sharing a silhouette. These families
      mix humans, Wookiees, Rodians and droids. Weight transfer would be correct, because a recipient
      keeps its own weights, but whether a donated part looks right on a different body — or meets its
      neighbours at the seams — is untested.</p>
    <p>Previews are flat grey, orthographic, front view, in rest pose. No textures: the question here is
      shape and proportion, and colour would only get in the way.</p>
  </div>
</div>

<script>
  (function () {
    const search = document.getElementById('search');
    const filters = Array.from(document.querySelectorAll('.filter'));
    const cards = Array.from(document.querySelectorAll('.card'));
    const families = Array.from(document.querySelectorAll('.family'));

    function apply() {
      const q = search.value.trim().toLowerCase();
      const wanted = filters.filter(f => f.getAttribute('aria-pressed') === 'true')
                            .map(f => f.dataset.part);
      cards.forEach(card => {
        const parts = (card.dataset.parts || '').split(' ').filter(Boolean);
        const nameOk = !q || card.dataset.name.toLowerCase().includes(q);
        const partOk = wanted.every(w => parts.includes(w));
        card.classList.toggle('hidden', !(nameOk && partOk));
      });
      families.forEach(fam => {
        const any = Array.from(fam.querySelectorAll('.card')).some(c => !c.classList.contains('hidden'));
        fam.classList.toggle('hidden', !any);
      });
    }

    search.addEventListener('input', apply);
    filters.forEach(f => f.addEventListener('click', () => {
      f.setAttribute('aria-pressed', f.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
      apply();
    }));
  })();
</script>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", default="reports/catalogue.json")
    ap.add_argument("--thumbs", default="catalogue/thumb")
    ap.add_argument("--out", default="catalogue/parts_bin.html")
    args = ap.parse_args()

    data = json.loads(Path(args.catalogue).read_text(encoding="utf-8"))
    page = build(data, Path(args.thumbs))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"{out}  ({out.stat().st_size / 1024 / 1024:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
