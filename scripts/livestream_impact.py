"""Real livestream showcase: original speech, grounded screenshots and timed scenes."""

import argparse
import asyncio
import hashlib
import io
import json
import resource
import shutil
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

from app.agent.critic import evaluate_preview, extract_frame_bytes
from app.analysis.asr_whisper import FasterWhisperTranscriber
from app.analysis.faces_cv import track_cached
from app.media.ffmpeg import ffmpeg_path, run_ffmpeg
from app.providers.registry import provider_registry
from app.render.edl_to_ffmpeg import FINAL, PREVIEW
from app.render.quality import inspect_export
from app.render.render import render_timeline
from app.scenes.compiler import compile_scenes
from app.settings import get_settings
from app.storage import LocalStorage
from app.timeline.schema import Timeline
from app.timeline.transcript import Transcript

ROOT = Path("work/livestream-impact").resolve()
SOURCE_URL = "https://www.youtube.com/watch?v=dBCLS8myarc&t=1200s"


async def prepare(
    start: float = 0.0, seconds: float = 60.0, asr_model: str | None = None
) -> tuple[Path, Transcript]:
    """Normalize the excerpt (at most 90 s) and transcribe locally once, cached on disk."""
    if seconds > 90:
        raise ValueError("ClipZ sources are capped at 90 seconds")
    source = ROOT / "source.mp4"
    master = ROOT / "master.mp4"
    if not master.exists():
        await asyncio.to_thread(
            run_ffmpeg,
            [
                ffmpeg_path(),
                "-v",
                "error",
                "-y",
                "-ss",
                str(start),
                "-i",
                str(source),
                "-t",
                str(seconds),
                "-vf",
                "fps=30,format=yuv420p,setsar=1",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(master),
            ],
        )
    cache = ROOT / "transcript.json"
    if cache.exists():
        transcript = Transcript.model_validate_json(cache.read_text())
    else:
        print("Transcribing the original livestream locally...", flush=True)
        if asr_model is None:
            snapshots = ROOT.parent / "asr-models/models--Systran--faster-whisper-base.en/snapshots"
            asr_model = str(next(p for p in snapshots.iterdir() if (p / "model.bin").exists()))
        asr = await asyncio.to_thread(FasterWhisperTranscriber, asr_model)
        transcript = await asr.transcribe(str(master), "en")
        cache.write_text(transcript.model_dump_json(indent=2))
    # Source contact sheet establishes framing and evidence before art direction.
    sheet = Image.new("RGB", (3 * 480, 2 * 300), "#101820")
    draw = ImageDraw.Draw(sheet)
    for i, t in enumerate(round(seconds * f, 1) for f in (0.02, 0.18, 0.35, 0.52, 0.7, 0.9)):
        data = await asyncio.to_thread(extract_frame_bytes, master, t)
        im = Image.open(io.BytesIO(data))
        im.thumbnail((480, 270))
        x = (i % 3) * 480
        y = (i // 3) * 300
        sheet.paste(im, (x, y))
        draw.text((x + 10, y + 278), f"{t}s", fill="white")
    sheet.save(ROOT / "source-contact-sheet.jpg")
    return master, transcript


def set_root(path: Path) -> None:
    """Point the harness at one project's work directory."""
    global ROOT
    ROOT = path.resolve()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--profile", choices=["preview", "final"], default="preview")
    parser.add_argument("--live-review", action="store_true")
    parser.add_argument("--root", default=str(ROOT), help="Project work directory")
    parser.add_argument("--start", type=float, default=0.0, help="Offset into source.mp4")
    parser.add_argument("--seconds", type=float, default=60.0, help="Excerpt length (<= 90)")
    parser.add_argument("--asr-model", default=None, help="faster-whisper model name/path")
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--brief", default=None, help="Review brief for the visual critic")
    args = parser.parse_args()
    set_root(Path(args.root))
    ROOT.mkdir(parents=True, exist_ok=True)
    master, transcript = await prepare(args.start, args.seconds, args.asr_model)
    if args.prepare:
        for w in transcript.words:
            print(f"{w.id:>4} {w.start:5.2f}-{w.end:5.2f} {w.text}", flush=True)
        return
    timeline = Timeline.model_validate_json((ROOT / "timeline.json").read_text())
    store = LocalStorage("upload", "work", "editedVideo")
    store.ensure_dirs()
    files = json.loads((ROOT / "asset-files.json").read_text())
    faces = await asyncio.to_thread(
        track_cached,
        str(master),
        hashlib.sha256(master.read_bytes()).hexdigest(),
        ROOT / "face-cache",
    )
    profile = FINAL if args.profile == "final" else PREVIEW
    work = ROOT / args.profile
    work.mkdir(exist_ok=True)
    started = time.monotonic()
    cpu_started = resource.getrusage(resource.RUSAGE_CHILDREN)
    rendered = await render_timeline(
        timeline, str(master), files, profile, store, str(work), lambda f: None, faces
    )
    output = Path("editedVideo") / f"{ROOT.name}-{args.profile}.mp4"
    shutil.copyfile(store.path_for(str(rendered["key"])), output)
    technical = await asyncio.to_thread(
        inspect_export, output, timeline.duration_s, profile.width, profile.height
    )
    llm = provider_registry(get_settings()).llm if args.live_review else None
    review = await evaluate_preview(
        llm,
        timeline,
        output,
        user_prompt=args.brief
        or (
            "Match the focused page-led technical explainer reference. Look for mobile "
            "readability, incorrect or late states, blank panels, crowding, caption "
            "collisions and content relevance. Source is a public technical livestream; "
            "illustrations must not appear as executed results."
        ),
    )
    report = {
        "artifact": str(output.resolve()),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "technical": technical,
        "review": review.model_dump(mode="json"),
        "render": rendered,
        "elapsed_s": round(time.monotonic() - started, 2),
        "child_cpu_s": round(
            resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime
            + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime
            - cpu_started.ru_utime
            - cpu_started.ru_stime,
            3,
        ),
        "children_peak_rss_bytes": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        * (1 if sys.platform == "darwin" else 1024),
        "export_bytes": output.stat().st_size,
        "estimated_model_cost_usd": None,
        "source": args.source_url,
        "limitations": [
            "Source webcam detail is limited by the livestream recording.",
            "Sparse visual review does not replace full human playback.",
        ],
    }
    (ROOT / f"{args.profile}-report.json").write_text(json.dumps(report, indent=2))
    # Sample each scene at its output-time midpoint (source word times differ after cuts).
    scenes = compile_scenes(timeline)
    sheet = Image.new("RGB", (4 * 270, ((len(scenes) + 3) // 4) * 520), "#101820")
    draw = ImageDraw.Draw(sheet)
    for i, compiled in enumerate(scenes):
        a, b = compiled.start_frame / 30, compiled.end_frame / 30
        data = await asyncio.to_thread(extract_frame_bytes, output, a + 0.8 * (b - a))
        im = Image.open(io.BytesIO(data))
        im.thumbnail((270, 480))
        x = (i % 4) * 270
        y = (i // 4) * 520
        sheet.paste(im, (x, y))
        draw.text((x + 10, y + 490), f"{compiled.spec.id} · {a:.1f}-{b:.1f}s", fill="white")
    sheet.save(ROOT / f"{args.profile}-contact-sheet.jpg")
    print(json.dumps({k: report[k] for k in ("artifact", "technical", "elapsed_s")}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
