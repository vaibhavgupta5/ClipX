"""Run the real Director prompt loop with local analysis, versions and actual renders.

Uses the configured Gemini provider; no database, Redis, Docker or test fakes.
Source/transcript may be reused from a previous quality_demo run.
"""

import argparse
import asyncio
import hashlib
import json
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.agent.context import project_data, system_prompt
from app.agent.director import Event, run_director
from app.analysis.fillers import FillerFinder
from app.analysis.models import FaceBox, FillerHit, SpeechRange
from app.analysis.vad import EnergyVad
from app.media.probe import probe_file
from app.providers.local import AssetCatalog, resolve_asset_file
from app.providers.registry import director_llm
from app.render.quality import inspect_export
from app.render.render import profile_for, render_timeline
from app.settings import Settings
from app.storage import LocalStorage
from app.timeline.schema import Timeline, VideoClip
from app.timeline.transcript import Transcript
from app.timeline.validate import ensure_valid
from app.timeline.versions import VersionLog
from app.tools.executor import Effect, ToolOutcome, ToolState


class FileWorkspace:
    """Director's real workspace contract, persisted in an isolated directory."""

    def __init__(
        self,
        timeline: Timeline,
        master: Path,
        output: Path,
        catalog: AssetCatalog,
        speech: list[SpeechRange],
        fillers: list[FillerHit],
    ) -> None:
        self.log = VersionLog().append(timeline)
        self.master, self.output, self.catalog = master, output, catalog
        self.speech, self.fillers = speech, fillers
        self.store = LocalStorage(
            str(output / "upload"), str(output / "cache"), str(output / "renders")
        )
        self.store.ensure_dirs()
        self.rendered: dict[tuple[int, str], str] = {}
        self.faces: list[FaceBox] | None = None
        self._save()

    def timeline(self) -> Timeline:
        """Immutable snapshot stamped with the version pointer."""
        entry = self.log.get(self.log.current)
        assert entry is not None
        return Timeline.model_validate(entry.edl).model_copy(update={"version": entry.version})

    def _save(self) -> None:
        versions = self.output / "versions"
        versions.mkdir(exist_ok=True)
        for entry in self.log.entries:
            destination = versions / f"v{entry.version:03d}.json"
            if not destination.exists():
                destination.write_text(
                    json.dumps({**entry.edl, "version": entry.version}, indent=2)
                )
        (self.output / "timeline.json").write_text(self.timeline().model_dump_json(indent=2))
        (self.output / "version-log.json").write_text(json.dumps(asdict(self.log), indent=2))

    async def state(self) -> ToolState:
        return ToolState(self.timeline(), self.speech, self.fillers, catalog=self.catalog)

    async def current_version(self) -> int:
        return self.log.current

    async def commit(self, outcome: ToolOutcome) -> int:
        assert outcome.timeline is not None
        ensure_valid(outcome.timeline)
        self.log = self.log.append(outcome.timeline)
        self._save()
        return self.log.current

    async def move(self, effect: Effect) -> int:
        self.log = self.log.undo() if effect == Effect.UNDO else self.log.redo()
        self._save()
        return self.log.current

    async def dub(self, language: str) -> str:
        raise ValueError(f"dubbing is not available in this local render workspace ({language})")

    async def render(self, profile: str) -> tuple[str, str]:
        """Execute, persist and inspect a real render of the exact current version."""
        tl = self.timeline()
        key = (tl.version, profile)
        if key in self.rendered:
            return self.rendered[key], self.rendered[key]
        spec = profile_for(profile)
        if self.faces is None and tl.reframe in ("split", "split_bottom", "face"):
            from app.analysis.faces_cv import track_cached

            with self.master.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            self.faces = await asyncio.to_thread(
                track_cached,
                str(self.master),
                digest,
                self.output / "faces",
            )
        files = {}
        ids = [o.asset for o in tl.overlays] + [s.asset for s in tl.sfx]
        ids += [v.asset for v in tl.voiceovers]
        if tl.music:
            ids.append(tl.music.asset)
        if tl.dub:
            ids.append(tl.dub.asset)
        for asset_id in ids:
            path = resolve_asset_file(self.catalog.root, self.catalog.meme_dir, asset_id)
            if path is None:
                raise ValueError(f"asset has no local file: {asset_id}")
            files[asset_id] = str(path)
        work = self.output / f"render-v{tl.version:03d}-{profile}"
        work.mkdir(exist_ok=True)
        print(f"RENDER {profile}, version {tl.version}, {tl.duration_s:.3f}s", flush=True)
        result = await render_timeline(
            tl,
            str(self.master),
            files,
            spec,
            self.store,
            str(work),
            lambda _: None,
            faces=self.faces,
        )
        destination = self.output / f"{profile}.mp4"
        shutil.copyfile(self.store.path_for(str(result["key"])), destination)
        report = await asyncio.to_thread(
            inspect_export, destination, tl.duration_s, spec.width, spec.height
        )
        (self.output / f"quality-{profile}.json").write_text(
            json.dumps(report, indent=2, allow_nan=False)
        )
        print("QUALITY " + json.dumps(report), flush=True)
        if not report["passed"]:
            raise ValueError(f"{profile} failed technical QA: {report['errors']}")
        render_id = f"v{tl.version}-{profile}"
        self.rendered[key] = render_id
        return render_id, render_id


async def run(args: argparse.Namespace) -> None:
    """Run one prompt and retain every real tool outcome and checkpoint."""
    output = Path(args.out).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "events.jsonl").exists():
        raise ValueError("choose a new --out directory; existing run evidence is preserved")
    master = Path(args.master).resolve()
    transcript = Transcript.model_validate_json(Path(args.transcript).read_text())
    info = await asyncio.to_thread(probe_file, str(master))
    speech = await asyncio.to_thread(EnergyVad().detect, str(master))
    fillers = FillerFinder(transcript.language).find(transcript)
    tl = Timeline(
        project_id=uuid.uuid5(uuid.NAMESPACE_URL, str(output)),
        transcript=transcript,
        video_clips=[VideoClip(id="c1", asset="source", src_in=0, src_out=info.duration_s)],
    )
    if args.timeline:
        tl = Timeline.model_validate_json(Path(args.timeline).read_text())
        (output / "input-checkpoint.json").write_text(tl.model_dump_json(indent=2))
    settings = Settings()
    if not settings.GEMINI_API_KEY and not args.render_only:
        raise ValueError("a configured Gemini key is required for the real prompt pipeline")
    catalog = AssetCatalog(Path(settings.ASSETS_DIR).resolve(), output / "cards")
    if args.timeline:
        checkpoint = Path(args.timeline).resolve()
        origin = (
            checkpoint.parent.parent if checkpoint.parent.name == "versions" else checkpoint.parent
        )
        original_cards = origin / "cards"
        if original_cards.is_dir():
            shutil.copytree(original_cards, output / "cards", dirs_exist_ok=True)
    ws = FileWorkspace(tl, master, output, catalog, speech, fillers)
    prompt = Path(args.prompt).read_text()
    (output / "prompt.txt").write_text(prompt)
    (output / "analysis.json").write_text(
        json.dumps(
            {
                "speech": [s.model_dump() for s in speech],
                "fillers": [f.model_dump() for f in fillers],
            },
            indent=2,
        )
    )
    events: list[dict[str, Any]] = []

    def emit(event: Event) -> None:
        record = {"type": event.type, "data": event.data}
        events.append(record)
        with (output / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        if event.type == "tool_call":
            print("CALL " + str(event.data.get("name")), flush=True)
        elif event.type == "tool_result":
            print(
                "RESULT " + str(event.data.get("name")) + " " + str(event.data.get("ok")),
                flush=True,
            )

    if args.render_only:
        for command in ("preview", "export"):
            await run_director(director_llm(settings), ws, "", command, emit=emit)
        return
    result = await run_director(
        director_llm(settings),
        ws,
        system_prompt(project_data(tl, speech, fillers)),
        prompt,
        emit=emit,
        max_iters=args.max_iters,
    )
    (output / "director-result.json").write_text(
        json.dumps(
            {
                "reply": result.reply,
                "stopped": result.stopped,
                "iterations": result.iterations,
                "model": result.model,
                "usage": result.usage.model_dump(),
                "tools": result.tools,
                "versions": result.versions,
                "question": result.question,
            },
            indent=2,
        )
    )
    successful = sorted(
        {
            str(e["data"]["name"])
            for e in events
            if e["type"] == "tool_result" and e["data"].get("ok")
        }
    )
    failed = [e for e in events if e["type"] == "tool_result" and not e["data"].get("ok")]
    (output / "tool-coverage.json").write_text(
        json.dumps(
            {
                "successful_tools": successful,
                "unique_successful": len(successful),
                "failed_calls": failed,
            },
            indent=2,
        )
    )
    print(f"DIRECTOR {result.stopped}: {result.reply}", flush=True)
    print("SUCCESSFUL TOOLS: " + ", ".join(successful), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", default="work/coding-demo/master.mp4")
    parser.add_argument("--transcript", default="work/coding-demo/transcript.json")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-iters", type=int, default=28)
    parser.add_argument("--timeline", help="Continue from a saved immutable EDL checkpoint")
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="Render checkpoint through direct preview/export tools; no model request",
    )
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
