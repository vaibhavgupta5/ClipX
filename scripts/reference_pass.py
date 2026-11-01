"""Build the inspected reference's page-led treatment using existing typed tools.

This is a deterministic edit recipe, not a fresh LLM run. The user's actual consent
message is supplied to the same Director export guard. No database/queue is needed.
"""

import argparse
import asyncio
import json
import math
from pathlib import Path

from app.agent.director import DirectorResult, Event, _Turn
from app.analysis.fillers import FillerFinder
from app.analysis.vad import EnergyVad
from app.providers.local import AssetCatalog
from app.providers.tools import ToolCall
from app.timeline import snap
from app.timeline.schema import Diff, Timeline
from app.tools.executor import Effect, ToolOutcome
from app.tools.registry import get_tool
from scripts.prompt_demo import FileWorkspace

CONSENT_MESSAGE = "Yes—use real screenshots for this non-commercial test"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="work/reference-output")
    parser.add_argument(
        "--refine-from", type=Path, help="Refine a saved reference pass without recapturing pages"
    )
    args = parser.parse_args()
    root = Path(args.out).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / "events.jsonl").exists():
        raise ValueError(
            "reference-output already contains a run; preserve it and choose a new path"
        )
    checkpoint = args.refine_from or Path("work/pro-final/timeline.json")
    tl = Timeline.model_validate_json(checkpoint.read_text())
    master = Path("work/coding-demo/master.mp4").resolve()
    speech = await asyncio.to_thread(EnergyVad().detect, str(master))
    catalog = AssetCatalog(Path("assets").resolve(), root / "cards")
    ws = FileWorkspace(tl, master, root, catalog, speech, FillerFinder("en").find(tl.transcript))
    events: list[dict] = []

    def emit(event: Event) -> None:
        record = {"type": event.type, "data": event.data}
        events.append(record)
        with (root / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(record) + "\n")
        if event.type in ("tool_call", "tool_result", "error"):
            print(event.type, event.data.get("name", ""), event.data.get("ok", ""), flush=True)

    result = DirectorResult(model="deterministic-reference-recipe")
    turn = _Turn(ws, emit, result, message=CONSENT_MESSAGE)
    index = 0

    async def call(name: str, **args: object) -> None:
        nonlocal index
        index += 1
        response = await turn.call(ToolCall(id=f"reference-{index}", name=name, args=args))
        if response.is_error:
            raise ValueError(response.content)

    (root / "consent.txt").write_text(CONSENT_MESSAGE)
    if args.refine_from:
        await call("reframe_9x16", mode="split_bottom", speaker_zoom=2.4)
        # Repository listing requests can fail independently of the README. Use the
        # successfully captured source detail for bookends, preserving its license.
        readme = next(o for o in tl.overlays if o.anchor_word == "w77")
        for wid in ("w27", "w131"):
            bookend = next(o for o in tl.overlays if o.anchor_word == wid)
            await call("remove_insert", insert_id=bookend.id)
            await call(
                "insert_asset",
                asset_id=readme.asset,
                at_word=wid,
                duration_ms=bookend.duration_ms,
                layout="split_top",
                motion="none",
                entrance="cut",
            )
        # Replace one repeated page with a clearly labelled explanatory diagram.
        shot = next(o for o in tl.overlays if o.anchor_word == "w59")
        await call("remove_insert", insert_id=shot.id)
        await call(
            "generate_infographic",
            at_word="w59",
            duration_ms=shot.duration_ms,
            layout="proof",
            motion="pull_out",
            entrance="slide_up",
            variant="flow",
            title="Load. Cache. Reuse.",
            stats=[
                {"value": "require()", "label": "Find the requested module"},
                {"value": "module.lua", "label": "Read and load its code"},
                {"value": "package.loaded", "label": "Keep the loaded result"},
            ],
            source_label="Illustration of Lua module loading",
        )
        await call("auto_sfx", gain_db=-27, on_cuts=False, on_inserts=True, on_zooms=False)
        await call("preview")
        await call("export", profile="final", monetized=False)
        await turn.finish()
        (root / "credits.txt").write_text((checkpoint.parent / "credits.txt").read_text())
        print("REFERENCE REFINEMENT COMPLETE", root, flush=True)
        return
    for overlay in list(tl.overlays):
        await call("remove_insert", insert_id=overlay.id)
    # The reference is editorial page footage, with quiet captions and hard cuts.
    await call("reframe_9x16", mode="split_bottom")
    await call(
        "set_caption_style",
        mode="line",
        position="showcase",
        size_px=48,
        words_per_line=4,
        base_color="#FFFFFF",
        uppercase=False,
        animation="none",
    )
    await call("set_transition", style="none")
    current = (await ws.state()).timeline
    if current.zooms:
        await ws.commit(
            ToolOutcome(
                get_tool("add_zooms"),
                Effect.NEW_VERSION,
                current.model_copy(update={"zooms": []}),
                Diff(op="reference_camera", details={"source_zooms": "removed"}),
            )
        )

    anchors = ["w27", "w36", "w59", "w77", "w84", "w103", "w112", "w125", "w131"]
    starts = [snap.output_time_of((await ws.state()).timeline, wid, "start") for wid in anchors]
    ends = starts[1:] + [(await ws.state()).timeline.duration_s]
    durations = [
        min(6000, math.floor((b - a) * 1000 + 1e-5)) for a, b in zip(starts, ends, strict=True)
    ]
    base = "https://www.lua.org/manual/5.1/manual.html"
    shots = [
        {"capture": "repo", "url": "https://github.com/neovim/neovim", "layout": "split_top"},
        {
            "capture": "require",
            "url": base + "#pdf-require",
            "reading_mode": True,
            "highlight_text": "Loads the given module.",
            "motion": "pull_out",
        },
        {"reuse": "require", "motion": "push_in"},
        {
            "capture": "nvim",
            "url": "https://github.com/neovim/neovim",
            "motion": "pan_up",
            "highlight_text": "Neovim is a project that seeks to aggressively refactor",
        },
        {
            "capture": "cache",
            "url": base + "#pdf-package.loaded",
            "reading_mode": True,
            "highlight_text": "to control which modules are already loaded.",
            "motion": "pull_out",
        },
        {"reuse": "cache", "motion": "pan_up"},
        {
            "capture": "clear",
            "url": base + "#pdf-package.loaded",
            "reading_mode": True,
            "highlight_text": "When you require a module",
            "motion": "push_in",
        },
        {"reuse": "require", "motion": "pull_out"},
        {"reuse": "repo", "layout": "split_top"},
    ]
    ids: dict[str, str] = {}
    plan = []
    for wid, duration, shot in zip(anchors, durations, shots, strict=True):
        layout = str(shot.get("layout", "proof"))
        common = {
            "at_word": wid,
            "duration_ms": duration,
            "layout": layout,
            "motion": shot.get("motion", "none"),
            "entrance": "slide_up",
        }
        if "capture" in shot:
            params = {k: v for k, v in shot.items() if k not in ("capture", "motion", "layout")}
            await call("capture_webpage", **params, viewport="portrait", **common)
            ids[str(shot["capture"])] = (await ws.state()).timeline.overlays[-1].asset
        else:
            await call("insert_asset", asset_id=ids[str(shot["reuse"])], **common)
        plan.append({"word": wid, "duration_ms": duration, **shot})
    (root / "shot-plan.json").write_text(json.dumps(plan, indent=2))
    await call("auto_sfx", gain_db=-27, on_cuts=False, on_inserts=True, on_zooms=False)
    await call("preview")
    await call("export", profile="final", monetized=False)
    await turn.finish()
    (root / "credits.txt").write_text(
        "Test excerpt: ThePrimeTime — https://www.youtube.com/watch?v=dBCLS8myarc\n"
        "Pages: Lua 5.1 Reference Manual and github.com/neovim/neovim\n"
        + (
            (await ws.state()).timeline.music.attribution_text
            if (await ws.state()).timeline.music
            else ""
        )
    )
    print("REFERENCE EXPORT COMPLETE", root, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
