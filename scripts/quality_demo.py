"""Render a real explanation through ClipZ, preserving EDL and measured export QA.

uv run --extra showcase --extra video-test python -m scripts.quality_demo INPUT.mp4
Optional --graphics JSON is a list of {tool, args} calls grounded in the source.
No LLM, database or paid API is needed. Whisper runs locally and caches its words.
"""

import argparse
import asyncio
import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from app.analysis.asr_whisper import FasterWhisperTranscriber
from app.media.ffmpeg import ffmpeg_path, run_capture, run_ffmpeg
from app.media.probe import probe_file
from app.providers.local import AssetCatalog, resolve_asset_file
from app.render.edl_to_ffmpeg import FINAL, PREVIEW
from app.render.quality import inspect_export
from app.render.render import render_timeline
from app.showcase.capture import capture_webpage
from app.showcase.images import GeneratedImageStore
from app.showcase.models import AnnotateIn, CaptureIn, InfographicIn
from app.storage import LocalStorage
from app.timeline.schema import Timeline, VideoClip
from app.timeline.transcript import Transcript
from app.tools.executor import ToolFailure, ToolState, execute


async def run(args: argparse.Namespace) -> None:
    """Normalize, transcribe once, apply typed edits, render both profiles and inspect."""
    source = Path(args.source).resolve()
    if not source.is_file():
        raise ValueError(f"missing source: {source}")
    output = Path(args.out).resolve()
    output.mkdir(parents=True, exist_ok=True)
    filters = run_capture([ffmpeg_path(), "-hide_banner", "-filters"]).decode()
    if " ass " not in filters:
        raise ValueError("FFmpeg needs libass; see docs/VIDEO-QUALITY.md for macOS setup")
    master = output / "master.mp4"
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    marker = output / "source.json"
    signature = {"sha256": source_sha, "seconds": args.seconds, "source": str(source)}
    if not marker.exists() or json.loads(marker.read_text()) != signature:
        await asyncio.to_thread(
            run_ffmpeg,
            [
                ffmpeg_path(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-t",
                str(args.seconds),
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
        marker.write_text(json.dumps(signature, indent=2))
    info = await asyncio.to_thread(probe_file, str(master))
    transcript_path = output / "transcript.json"
    transcript_key = output / "transcript-source.json"
    asr_signature = {**signature, "model": args.model, "language": args.language}
    if (
        transcript_path.exists()
        and transcript_key.exists()
        and json.loads(transcript_key.read_text()) == asr_signature
    ):
        transcript = Transcript.model_validate_json(transcript_path.read_text())
    else:
        print(f"Transcribing {info.duration_s:.1f}s locally ({args.model})...", flush=True)
        asr = await asyncio.to_thread(FasterWhisperTranscriber, args.model)
        transcript = await asr.transcribe(str(master), args.language)
        transcript_path.write_text(transcript.model_dump_json(indent=2))
        transcript_key.write_text(json.dumps(asr_signature))
    if not transcript.words:
        raise ValueError("no speech found; choose an explanatory section of the stream")
    print("Transcript: " + " ".join(w.text for w in transcript.words), flush=True)
    tl = Timeline(
        project_id=uuid.UUID(source_sha[:32]),
        transcript=transcript,
        video_clips=[VideoClip(id="c1", asset="source", src_in=0, src_out=info.duration_s)],
    )
    assets = output / "assets"
    catalog = AssetCatalog(assets, output / "cards")
    images = GeneratedImageStore(assets, output / "cards")
    calls: list[dict[str, Any]] = [
        {"tool": "apply_showcase_style", "args": {}},
        {"tool": "normalize_loudness", "args": {"target_lufs": -14}},
    ]
    if args.graphics:
        calls.extend(json.loads(Path(args.graphics).read_text()))
    log = []
    for call in calls:
        name, payload = call["tool"], call["args"]
        prepared = None
        if name == "generate_infographic":
            prepared = images.infographic(InfographicIn.model_validate(payload))
        elif name == "annotate_image":
            prepared = images.annotate(AnnotateIn.model_validate(payload))
        elif name == "capture_webpage":
            prepared = await capture_webpage(CaptureIn.model_validate(payload), images)
        catalog.reload("showcase")
        outcome = execute(name, payload, ToolState(tl, catalog=catalog, prepared=prepared))
        if isinstance(outcome, ToolFailure):
            raise ValueError(outcome.message())
        if outcome.timeline is not None:
            tl = outcome.timeline
        log.append({"tool": name, "args": payload, "asset_id": prepared.id if prepared else None})
    (output / "timeline.json").write_text(tl.model_dump_json(indent=2))
    (output / "tool-calls.json").write_text(json.dumps(log, indent=2))
    files = {}
    for overlay in tl.overlays:
        path = resolve_asset_file(assets, output / "cards", overlay.asset)
        if path is None:
            raise ValueError(f"unresolved graphic: {overlay.asset}")
        files[overlay.asset] = str(path)
    store = LocalStorage(str(output / "upload"), str(output / "cache"), str(output / "renders"))
    store.ensure_dirs()
    reports = {}
    for profile in (PREVIEW, FINAL):
        work = output / profile.name
        work.mkdir(exist_ok=True)
        print(f"Rendering {profile.name}...", flush=True)
        result = await render_timeline(
            tl, str(master), files, profile, store, str(work), lambda _: None
        )
        destination = output / f"{profile.name}.mp4"
        shutil.copyfile(store.path_for(str(result["key"])), destination)
        reports[profile.name] = await asyncio.to_thread(
            inspect_export,
            destination,
            tl.duration_s,
            profile.width,
            profile.height,
        )
        print(json.dumps(reports[profile.name]), flush=True)
    # A filmstrip is a review aid, not an automated aesthetic verdict.
    sheet = Image.new("RGB", (270 * 4, 480 * 2), "#111827")
    for i, fraction in enumerate((0.015, 0.12, 0.25, 0.38, 0.5, 0.65, 0.82, 0.98)):
        frame = output / f"frame-{i}.png"
        at = tl.duration_s * fraction
        await asyncio.to_thread(
            run_ffmpeg,
            [
                ffmpeg_path(),
                "-v",
                "error",
                "-y",
                "-ss",
                str(at),
                "-i",
                str(output / "final.mp4"),
                "-frames:v",
                "1",
                "-vf",
                "scale=270:480",
                str(frame),
            ],
        )
        with Image.open(frame) as im:
            sheet.paste(im, ((i % 4) * 270, (i // 4) * 480))
        ImageDraw.Draw(sheet).text(
            ((i % 4) * 270 + 8, (i // 4) * 480 + 8), f"{at:.1f}s", fill="white"
        )
    sheet.save(output / "filmstrip.jpg")
    (output / "quality.json").write_text(json.dumps(reports, indent=2, allow_nan=False))
    if not all(r["passed"] for r in reports.values()):
        raise SystemExit("export failed technical QA; inspect quality.json")


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--out", default="work/quality-demo")
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--model", default="base.en")
    parser.add_argument("--language", choices=("en", "hi", "auto"), default="en")
    parser.add_argument("--graphics", help="JSON list of grounded showcase tool calls")
    args = parser.parse_args()
    if not 1 <= args.seconds <= 90:
        parser.error("seconds must be in 1..90")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
