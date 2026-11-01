"""Reproducible original visual explainer. No copied reference claims or imagery.

Run: python -m scripts.hybrid_demo [--profile preview|final] [--live-review]
Uses local macOS speech when available, otherwise the explicitly labelled tone fixture.
Word timing in the synthetic fixture is authored; real uploads use the ASR transcript.
"""

import argparse
import asyncio
import hashlib
import io
import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.agent.critic import evaluate_preview, extract_frame_bytes
from app.media.ffmpeg import ffmpeg_path, run_capture, run_ffmpeg
from app.media.probe import ffprobe_path
from app.providers.registry import provider_registry
from app.render.edl_to_ffmpeg import FINAL, PREVIEW
from app.render.quality import inspect_export
from app.render.render import render_timeline
from app.scenes.models import ScenePlacement, SceneSpec
from app.scenes.timing import timing_hash
from app.settings import get_settings
from app.storage import LocalStorage
from app.storyboard.models import Claim, CreativeBrief, Storyboard, StoryboardBeat
from app.storyboard.planner import attach_storyboard
from app.storyboard.store import put_artifact
from app.timeline.schema import CaptionConfig, Timeline, VideoClip
from app.timeline.transcript import Transcript, Word
from app.visuals.evidence import freeze_image

NARRATION = [
    "A strong technical video should show how an idea works. Here is a small "
    "editing pipeline, built as an illustrative demo.",
    "Start with a grounded source. This sample project keeps the original "
    "narration, word anchors, and an editable storyboard together.",
    "The narration enters a timing map. The map connects spoken words to scene "
    "events. The renderer then builds the visual sequence.",
    "Now watch the checks change state. One candidate passes. Another is "
    "rejected. An unknown result stays unknown until evidence arrives.",
    "Before, a static card repeated the explanation. After, staged reveals show "
    "what changed, and why it matters.",
    "Each scene stays editable. Change one parameter, reuse the other scenes, and"
    " assemble the original voice only once.",
    "Review the encoded video, not just the plan. Check the frames, listen to the"
    " mix, and keep unsupported claims out of the final story.",
]


def _duration(path: Path) -> float:
    return float(
        json.loads(
            run_capture([ffprobe_path(), "-v", "error", "-show_format", "-of", "json", str(path)])
        )["format"]["duration"]
    )


def source_fixture(root: Path) -> tuple[Path, Transcript, list[tuple[str, str]]]:
    """Create original dummy narration with sentence-aligned authored word intervals."""
    words = []
    ranges = []
    offset = 0.0
    audios = []
    for index, text in enumerate(NARRATION):
        audio = root / f"speech-{index}.wav"
        if not audio.exists():
            if shutil.which("say"):
                aiff = root / f"speech-{index}.aiff"
                subprocess.run(
                    ["say", "-v", "Samantha", "-r", "185", "-o", str(aiff), text], check=True
                )  # noqa: S603,S607
                run_ffmpeg(
                    [
                        ffmpeg_path(),
                        "-v",
                        "error",
                        "-y",
                        "-i",
                        str(aiff),
                        "-ar",
                        "48000",
                        "-ac",
                        "2",
                        str(audio),
                    ]
                )
            else:
                run_ffmpeg(
                    [
                        ffmpeg_path(),
                        "-v",
                        "error",
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        f"sine=frequency=220:duration={len(text.split()) / 3}",
                        "-ar",
                        "48000",
                        "-ac",
                        "2",
                        str(audio),
                    ]
                )
        # Round each sentence to complete output frames for exact scene boundaries.
        duration = round(_duration(audio) * 30) / 30
        tokens = text.split()
        start_id = f"w{len(words) + 1}"
        for i, token in enumerate(tokens):
            words.append(
                Word(
                    id=f"w{len(words) + 1}",
                    start=offset + i * duration / len(tokens),
                    end=offset + (i + 1) * duration / len(tokens),
                    text=token,
                    display_text=token,
                    lang="en",
                )
            )
        ranges.append((start_id, words[-1].id))
        offset += duration
        audios.append(audio)
    image = Image.new("RGB", (1080, 1920), "#141d2c")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 48)
    draw.text((90, 1160), "ORIGINAL DUMMY SOURCE", font=font, fill="#72eac1")
    draw.text((90, 1250), "Synthetic narration fixture", font=font, fill="white")
    draw.text((90, 1340), "Word-anchored visual editing", font=font, fill="#b8c4d5")
    image.save(root / "source.png")
    master = root / "dummy-source.mp4"
    if not master.exists():
        inputs = [arg for path in audios for arg in ("-i", str(path))]
        filters = (
            "".join(f"[{i}:a]" for i in range(len(audios))) + f"concat=n={len(audios)}:v=0:a=1[a]"
        )
        joined = root / "narration.wav"
        run_ffmpeg(
            [
                ffmpeg_path(),
                "-v",
                "error",
                "-y",
                *inputs,
                "-filter_complex",
                filters,
                "-map",
                "[a]",
                str(joined),
            ]
        )
        run_ffmpeg(
            [
                ffmpeg_path(),
                "-v",
                "error",
                "-y",
                "-loop",
                "1",
                "-i",
                str(root / "source.png"),
                "-i",
                str(joined),
                "-t",
                f"{offset:.6f}",
                "-r",
                "30",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                str(master),
            ]
        )
    return master, Transcript(words=words, language="en"), ranges


def build_project(root: Path, store: LocalStorage) -> tuple[Timeline, Path]:
    master, transcript, ranges = source_fixture(root)
    tl = Timeline(
        project_id=uuid.UUID("87a6a1e2-13e9-408b-8f46-50ab4512b26a"),
        transcript=transcript,
        video_clips=[
            VideoClip(id="source", asset="dummy", src_in=0, src_out=transcript.words[-1].end)
        ],
        captions=CaptionConfig(
            mode="word_highlight",
            position="showcase",
            size_px=58,
            words_per_line=3,
            highlight_color="#70F1BD",
        ),
    )
    # One original frozen proof document, clearly labelled as an authored fixture.
    image = Image.new("RGB", (1100, 1000), "#f5f5ef")
    draw = ImageDraw.Draw(image)
    bold = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 55)
    regular = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 40)
    draw.text((70, 80), "ClipZ / sample project", font=bold, fill="#142333")
    draw.text((70, 200), "Source of truth", font=bold, fill="#142333")
    for y, line in zip(
        (330, 440, 550, 660),
        (
            "Original narration retained",
            "Stable word anchors",
            "Immutable edit history",
            "Editable visual scenes",
        ),
        strict=True,
    ):
        draw.rounded_rectangle((60, y - 12, 1040, y + 65), radius=10, fill="#dce9de")
        draw.text((90, y), line, font=regular, fill="#213b34")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    evidence = freeze_image(
        store,
        buf.getvalue(),
        asset_id="sample_doc",
        source="authored:hybrid-demo",
        entity="ClipZ",
        role="proof_focus",
        license="CC0-1.0",
        commercial_use=True,
    )
    contents = [
        dict(
            template="speaker_bridge",
            headline="Make the idea visible.",
            supporting="One original voice. A visual story that changes with it.",
        ),
        dict(
            template="proof_focus",
            asset_id="sample_doc",
            source_label="AUTHORED PROJECT FIXTURE",
            excerpt="Narration, word anchors and scene parameters remain together.",
        ),
        dict(
            template="architecture_flow",
            nodes=[
                dict(id="voice", label="Narration", detail="The original speaker"),
                dict(id="timing", label="Timing map", detail="Words → output frames"),
                dict(id="events", label="Visual events", detail="Reveal · connect · update"),
                dict(id="render", label="Scene renderer", detail="Deterministic local pixels"),
            ],
            edges=[
                dict(id="e1", source="voice", target="timing"),
                dict(id="e2", source="timing", target="events"),
                dict(id="e3", source="events", target="render"),
            ],
        ),
        dict(
            template="verification_pipeline",
            nodes=[
                dict(id="candidate", label="Candidates", detail="Illustrative test cases"),
                dict(id="check", label="Verification", detail="Evidence is required"),
                dict(id="pass", label="Candidate A", detail="Meets the demo check"),
                dict(id="reject", label="Candidate B", detail="Fails the demo check"),
                dict(id="unknown", label="Candidate C", detail="Evidence not yet available"),
                dict(id="report", label="Report", detail="Preserve uncertainty"),
            ],
            edges=[
                dict(id="v1", source="candidate", target="check"),
                dict(id="v2", source="check", target="pass"),
                dict(id="v3", source="check", target="reject"),
            ],
        ),
        dict(
            template="before_after",
            before="A static card repeats what the speaker says.",
            after="Staged events demonstrate the relationships.",
            change="A new visual state adds new understanding.",
        ),
        dict(
            template="product_walkthrough",
            product="ClipZ · scene editor",
            steps=[
                dict(id="select", label="Select a scene", detail="Keep neighboring scenes"),
                dict(id="edit", label="Change the focus", detail="Typed editable parameters"),
                dict(id="reuse", label="Reuse cached scenes", detail="Mix the original voice once"),
            ],
        ),
        dict(
            template="metric_or_code",
            value="01",
            label="Final encoded master to review",
            code=[
                "compile(word_anchors)",
                "render(local_scenes)",
                "mix(original_voice)",
                "review(encoded_frames)",
            ],
        ),
    ]
    titles = [
        "From explanation\nto demonstration.",
        "Ground the story.",
        "Show the mechanism.",
        "Let the evidence\nchange the state.",
        "Show what changed.",
        "Keep every scene\neditable.",
        "Review what\nactually rendered.",
    ]
    roles = [
        "promise",
        "evidence",
        "mechanism",
        "demonstration",
        "demonstration",
        "transition",
        "result",
    ]
    claims = []
    beats = []
    specs = []
    placements = []
    for i, (content, (start, end)) in enumerate(zip(contents, ranges, strict=True)):
        sid = f"scene{i + 1}"
        cid = f"claim{i + 1}"
        claims.append(
            Claim(
                id=cid,
                start_word=start,
                end_word=end,
                entity="ClipZ demo",
                assertion=NARRATION[i],
                caveat="Authored illustrative sequence; no third-party execution claim.",
            )
        )
        beats.append(
            StoryboardBeat(
                id=f"beat{i + 1}",
                start_word=start,
                end_word=end,
                role=roles[i],
                family=content["template"],
                understanding=titles[i].replace("\n", " "),
                claim_ids=[cid],
                scene_id=sid,
                evidence_ids=["sample_doc"] if i == 1 else [],
                unresolved_needs=[]
                if i == 1
                else ["Authored illustration; no observed execution evidence."],
            )
        )
        group = [w for w in transcript.words if int(start[1:]) <= int(w.id[1:]) <= int(end[1:])]

        def cue(text: str, occurrence: int = 0, words: list[Word] = group) -> str:
            matches = [w for w in words if w.text.strip(".,").lower() == text.lower()]
            if len(matches) <= occurrence:
                raise ValueError(f"dummy cue word {text!r} missing from sentence")
            return matches[occurrence].id

        # Content-specific cues, rather than distributing animation by item count.
        authored = [
            [],
            [],
            [
                ("voice", "reveal", cue("narration"), "active"),
                ("timing", "reveal", cue("timing"), "active"),
                ("e1", "connect", cue("timing"), "active"),
                ("events", "reveal", cue("scene"), "active"),
                ("e2", "connect", cue("scene"), "active"),
                ("render", "reveal", cue("renderer"), "active"),
                ("e3", "connect", cue("builds"), "active"),
            ]
            if i == 2
            else [],
            [
                ("candidate", "reveal", group[0].id, "active"),
                ("check", "reveal", cue("checks"), "active"),
                ("v1", "connect", cue("checks"), "active"),
                ("pass", "reveal", cue("One"), "active"),
                ("v2", "connect", cue("passes"), "active"),
                ("pass", "update", cue("passes"), "accepted"),
                ("reject", "reveal", cue("Another"), "active"),
                ("reject", "update", cue("rejected"), "rejected"),
                ("v3", "connect", cue("rejected"), "active"),
                ("unknown", "reveal", cue("unknown"), "active"),
                ("unknown", "update", cue("unknown"), "unknown"),
                ("report", "reveal", cue("evidence"), "active"),
            ]
            if i == 3
            else [],
            [
                ("before", "reveal", group[0].id, "active"),
                ("after", "reveal", cue("After"), "active"),
                ("after", "highlight", cue("reveals"), "active"),
            ]
            if i == 4
            else [],
            [
                ("select", "reveal", cue("scene"), "active"),
                ("edit", "reveal", cue("Change"), "active"),
                ("edit", "highlight", cue("parameter"), "active"),
                ("reuse", "reveal", cue("reuse"), "active"),
            ]
            if i == 5
            else [],
            [
                ("title", "reveal", group[0].id, "active"),
                ("body", "reveal", cue("encoded"), "active"),
            ]
            if i == 6
            else [],
        ]
        # The first two cue lists also need their own source sentence.
        if i in (0, 1):
            entries = [
                ("title", "reveal", group[0].id, "active"),
                ("body", "reveal", cue("idea" if i == 0 else "source"), "active"),
            ]
        else:
            entries = authored[i]
        events = [
            dict(target=t, action=action, word=word, state=state, preset="gentle")
            for t, action, word, state in entries
        ]
        specs.append(
            SceneSpec(
                id=sid,
                title=titles[i],
                eyebrow=f"CLIPZ DEMO  /  {i + 1:02d}",
                content=content,
                events=events,
                evidence_ids=["sample_doc"] if i == 1 else [],
            )
        )
        placements.append(
            ScenePlacement(
                scene_id=sid, start_word=start, end_word=end, slot="panel" if i == 0 else "full"
            )
        )
    board = Storyboard(
        brief=CreativeBrief(
            audience="Technical creators",
            promise="Make a mechanism visible",
            takeaway="Use changing visual states grounded in narration",
            source_limitations=[
                "Synthetic speech; authored word intervals, not an ASR accuracy benchmark."
            ],
        ),
        timing_hash=timing_hash(tl),
        claims=claims,
        beats=beats,
        evidence=[evidence],
    )
    tl = attach_storyboard(tl, board, expected_version=1).model_copy(
        update={"scenes": specs, "scene_placements": placements}
    )
    put_artifact(store, board)
    (root / "project.json").write_text(tl.model_dump_json(indent=2))
    return tl, master


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["preview", "final"], default="preview")
    parser.add_argument("--live-review", action="store_true")
    args = parser.parse_args()
    root = Path("work/hybrid-demo")
    root.mkdir(parents=True, exist_ok=True)
    store = LocalStorage("upload", "work", "editedVideo")
    store.ensure_dirs()
    tl, master = await asyncio.to_thread(build_project, root, store)
    profile = FINAL if args.profile == "final" else PREVIEW
    started = time.monotonic()
    work = root / args.profile
    work.mkdir(exist_ok=True)
    result = await render_timeline(tl, str(master), {}, profile, store, str(work), lambda f: None)
    output = store.path_for(str(result["key"]))
    target = Path("editedVideo") / f"hybrid-demo-{args.profile}.mp4"
    shutil.copyfile(output, target)
    technical = await asyncio.to_thread(
        inspect_export, target, tl.duration_s, profile.width, profile.height
    )
    llm = provider_registry(get_settings()).llm if args.live_review else None
    review = await evaluate_preview(
        llm,
        tl,
        target,
        user_prompt=(
            "Technical explainer inspired by reference visual grammar; "
            "inspect overflow and changing states."
        ),
    )
    report = {
        "artifact": str(target.resolve()),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "technical": technical,
        "review": review.model_dump(mode="json"),
        "render": result,
        "elapsed_s": round(time.monotonic() - started, 2),
        "limitations": [
            "Authored synthetic word timing; real cue accuracy requires ASR alignment.",
            "Human benchmark and full audio review are separate.",
        ],
    }
    (root / f"{args.profile}-report.json").write_text(json.dumps(report, indent=2))
    # Full-export contact sheet for inspection, not a substitute for playback.
    sheet = Image.new("RGB", (4 * 270, 2 * 520), "#111820")
    draw = ImageDraw.Draw(sheet)
    for i, placement in enumerate(tl.scene_placements):
        a = tl.transcript.word_index[placement.start_word].start
        b = tl.transcript.word_index[placement.end_word].end
        frame = extract_frame_bytes(target, (a + b) / 2)
        image = Image.open(io.BytesIO(frame))
        image.thumbnail((270, 480))
        x = (i % 4) * 270
        y = (i // 4) * 520
        sheet.paste(image, (x, y))
        draw.text((x + 10, y + 490), placement.scene_id, fill="white")
    sheet.save(root / f"{args.profile}-contact-sheet.jpg")
    print(
        json.dumps(
            {
                "artifact": str(target.resolve()),
                "technical_pass": technical["passed"],
                "errors": technical["errors"],
                "elapsed_s": report["elapsed_s"],
                "review_status": review.verdict,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
