"""Prepare a blinded, full-playback benchmark; never fabricate human scores.

Input JSON: {"cases":[{"id":"technical-en","kind":"talking_head","language":"en",
"baseline":"/absolute/baseline.mp4","hybrid":"/absolute/hybrid.mp4"}, ...]}.
Requires >=3 source cases across talking_head, screen_tutorial and product_walkthrough,
including Hindi. Produces a local HTML review sheet and a separate randomized key.
"""

import argparse
import html
import json
import random
from pathlib import Path

DIMENSIONS = [
    "Narrative clarity",
    "Asset relevance",
    "Demonstration quality",
    "Diagram readability",
    "Temporal and motion fit",
    "Audio and visual coherence",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", type=Path, default=Path("work/hybrid-benchmark"))
    args = parser.parse_args()
    cases = json.loads(args.manifest.read_text())["cases"]
    if len(cases) < 3 or {"talking_head", "screen_tutorial", "product_walkthrough"} - {
        c["kind"] for c in cases
    }:
        raise ValueError("benchmark needs all three source categories")
    if not {"en", "hi"} <= {c["language"] for c in cases}:
        raise ValueError("include English and Hindi before claiming both")
    entries = []
    for case in cases:
        for treatment in ("baseline", "hybrid"):
            path = Path(case[treatment]).resolve()
            if not path.is_file():
                raise ValueError(f"export missing: {path}")
            entries.append({"case": case["id"], "treatment": treatment, "path": str(path)})
    random.SystemRandom().shuffle(entries)
    args.out.mkdir(parents=True, exist_ok=True)
    markup = []
    for i, entry in enumerate(entries):
        options = "".join(f"<option>{v}</option>" for v in range(1, 6))
        scores = "".join(
            f'<label>{name}<select name="clip{i}-{j}">'
            f'<option value="">Select</option>{options}</select></label>'
            for j, name in enumerate(DIMENSIONS)
        )
        video_uri = html.escape(Path(entry["path"]).as_uri(), quote=True)
        markup.append(
            f'<section><h2>Clip {i + 1}</h2><video controls src="{video_uri}"></video>'
            f"{scores}<label>Factual or compositing defects"
            f'<textarea name="defects{i}"></textarea></label></section>'
        )
    page = """<!doctype html><meta charset="utf-8"><title>Visual explainer benchmark</title>
<style>
body{background:#111820;color:#eee;font:16px sans-serif;max-width:900px;margin:40px auto}
video{display:block;max-height:600px;max-width:100%;margin:20px 0}
label{display:block;margin:12px 0}select,textarea{margin-left:16px}
section{border-top:1px solid #456;padding:20px}
</style><h1>Full-playback video review</h1>
<p>Watch every video with sound before scoring. Rate each dimension 1–5.
Record factual/compositing defects. The acceptance gate requires no critical defects
and median ≥4 in every dimension; scores do not measure engagement.</p>
""" + "".join(markup)
    page += """<button id="save">Save review results</button><script>
document.getElementById('save').onclick=()=>{
 const scores=Object.fromEntries([...document.querySelectorAll('select,textarea')]
   .map(n=>[n.name,n.value]));
 const link=document.createElement('a');
 link.href=URL.createObjectURL(new Blob([JSON.stringify(scores,null,2)],
   {type:'application/json'}));link.download='benchmark-review.json';link.click();
};</script>"""
    (args.out / "review.html").write_text(page)
    (args.out / "randomization-key.json").write_text(json.dumps(entries, indent=2))
    print(args.out / "review.html")


if __name__ == "__main__":
    main()
