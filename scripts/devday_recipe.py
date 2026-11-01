"""Authored judge demo: OpenAI DevDay 2026 livestream excerpt through ClipZ's typed contracts.

Every visual is anchored to a recognized word. Stage-screen stills are frozen as observed
evidence; diagrams are labelled illustrations; numbers come only from the speech.
Run after ``python -m scripts.livestream_impact --root work/devday-impact --prepare ...``.
"""

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from app.scenes.models import ScenePlacement, SceneSpec
from app.scenes.timing import timing_hash
from app.storage import LocalStorage
from app.storyboard.models import Claim, CreativeBrief, Storyboard, StoryboardBeat
from app.storyboard.planner import attach_storyboard
from app.storyboard.store import put_artifact
from app.timeline.schema import (
    AudioEffect,
    CaptionConfig,
    MusicBed,
    Overlay,
    SfxHit,
    Timeline,
    VideoClip,
    Zoom,
)
from app.timeline.transcript import Transcript
from app.timeline.validate import ensure_valid
from app.visuals.evidence import freeze_image

ROOT = Path("work/devday-impact").resolve()
SOURCE = "https://www.youtube.com/watch?v=Fls_onRviPM&t=378s"
PROJECT = uuid.UUID("5d1c7f9e-2a4b-4c11-9e0d-6f2b8a3c4d71")
SOURCE_LICENSE = "youtube-standard-demo-excerpt"

# Retained speech, as inclusive word ranges, with the effect on the cut INTO each clip.
# Cuts into a scene use "none" (the scene's own entrance carries the cut); cuts that land
# on the speaker use a face-anchored zoom_in; the comic beat enters on a whip.
CLIPS = [
    ("hook", "w9", "w31", "none"),
    ("mechanism", "w32", "w83", "none"),
    ("old_way", "w84", "w109", "whip"),
    ("onboard", "w140", "w163", "none"),  # the push below carries it
    ("scale", "w164", "w188", "none"),
    ("anywhere", "w189", "w202", "none"),
    ("call", "w237", "w248", "zoom_in"),
    ("apps", "w249", "w275", "none"),
    ("control", "w287", "w304", "zoom_in"),
]


def manifest(kind: str) -> dict[str, dict[str, Any]]:
    """Catalog entries by ID; each carries license metadata (rule 7)."""
    items = json.loads(Path(f"assets/{kind}/manifest.json").read_text())
    return {i["id"]: i for i in items}


def main() -> None:
    transcript = Transcript.model_validate_json((ROOT / "transcript.json").read_text())
    words = transcript.word_index
    store = LocalStorage("upload", "work", "editedVideo")
    store.ensure_dirs()
    files: dict[str, str] = {}
    credits = [f"Source: OpenAI DevDay 2026 keynote livestream, 06:18–07:46. {SOURCE}"]

    # --- Frozen evidence -------------------------------------------------------------
    evidence = []
    for asset_id, entity, role, text in (
        ("slide_checklist", "dots agent activity", "proof_focus", "Stage screen activity list"),
        ("phone_text", "dots messaging", "multi_view", "Stage screen: texting a dot"),
        ("phone_call", "dots calling", "multi_view", "Stage screen: calling a dot"),
        ("hook_stage", "OpenAI DevDay 2026", "impact_title", "Keynote stage, dots launch"),
    ):
        evidence.append(
            freeze_image(
                store,
                (ROOT / "evidence" / f"{asset_id}.png").read_bytes(),
                asset_id=asset_id,
                source=SOURCE,
                entity=entity,
                role=role,
                license=SOURCE_LICENSE,
                commercial_use=False,
                kind="observed",
                project_id=PROJECT,
                attribution="Frame from the OpenAI DevDay 2026 livestream; demonstration use.",
                text=text,
            )
        )
    # Public pages captured by scripts/devday_capture.py (guarded capture tool, highlighted
    # phrase). Screenshots are third-party pages: observed evidence, never commercial.
    captures = json.loads((ROOT / "captures.json").read_text())
    for asset_id, key, entity in (
        ("page_techcrunch", "page_techcrunch", "TechCrunch launch report"),
        ("page_apps", "page_dots_apps", "OpenAI: Introducing dots"),
        ("page_control", "page_dots_control", "OpenAI: Introducing dots"),
    ):
        cap = captures[key]
        evidence.append(
            freeze_image(
                store,
                (ROOT / "captures/showcase" / cap["file"]).read_bytes(),
                asset_id=asset_id,
                source=cap["url"],
                entity=entity,
                role="proof_focus",
                license=cap["license"],
                commercial_use=False,
                kind="observed",
                project_id=PROJECT,
                attribution=cap["url"],
                text=cap.get("title", entity),
            )
        )
        credits.append(cap["url"])
    videos = manifest("videos")
    neural = videos["videos:ai-neural-network"]
    evidence.append(
        freeze_image(
            store,
            (ROOT / "evidence/neural_still.png").read_bytes(),
            asset_id="neural_still",
            source=neural.get("source_url", "assets/videos"),
            entity="Neural network B-roll",
            role="impact_title",
            license=neural["license"],
            commercial_use=neural["commercial_use"],
            project_id=PROJECT,
            attribution=neural.get("attribution_text", ""),
        )
    )
    icons = manifest("icons")
    for name in ("openai", "github", "gmail", "notion", "figma", "google", "discord"):
        item = icons[f"icons:{name}"]
        evidence.append(
            freeze_image(
                store,
                (Path("assets/icons") / item["file"]).read_bytes(),
                asset_id=f"icon_{name}",
                source=item.get("source_url", "assets/icons"),
                entity=name,
                role="hub",
                license=item["license"],
                commercial_use=item["commercial_use"],
                project_id=PROJECT,
                attribution=item.get("attribution_text", ""),
            )
        )
        if item.get("attribution_text"):
            credits.append(item["attribution_text"])

    # --- Edit -----------------------------------------------------------------------
    clips = [
        VideoClip(
            id=cid,
            asset="devday",
            src_in=round(max(0.0, words[a].start - 0.08), 3),
            src_out=round(words[b].end + 0.14, 3),
            transition_in=fx,
        )
        for cid, a, b, fx in CLIPS
    ]
    music = manifest("music")["music:b8d9b313-2d4f-410c-a9d8-bd57d7cb4e1d"]
    files[music["id"]] = str((Path("assets/music") / music["file"]).resolve())
    credits.append(music["attribution_text"])
    tl = Timeline(
        project_id=PROJECT,
        version=1,
        transcript=transcript,
        video_clips=clips,
        reframe="face",
        speaker_zoom=1.6,
        transition="none",
        scene_exit="zoom_in",  # every return to the speaker after a scene gets a face punch
        speaker_drift=0.035,  # raw footage never sits dead still
        captions=CaptionConfig(
            mode="word_highlight",
            position="showcase",
            words_per_line=3,
            size_px=56,
            base_color="#F5F5F2",
            highlight_color="#F4E64A",
            animation="none",
        ),
        # Only where a tracked face is on screen (checked against face tracks), scaled about
        # the face. Slow push on the close-up releases on the broadcast's own camera cut.
        zooms=[
            # Continuous camera push from "They" INTO the B-roll cut; it releases unseen.
            Zoom(id="z_access", anchor_word="w140", scale=1.3, dur_ms=900, hold_ms=1500),
            Zoom(id="z_closeup", anchor_word="w287", scale=1.12, dur_ms=1200, hold_ms=150),
        ],
        audio_fx=[AudioEffect(type="loudnorm", params={"lufs": -14})],
        music=MusicBed(
            asset=music["id"],
            license=music["license"],
            attribution_required=True,
            attribution_text=music["attribution_text"],
            level_db=-23,
            commercial_use=music["commercial_use"],
        ),
    )

    def span_ms(a: str, b: str) -> int:
        """Output duration from the end of word a to the end of word b (same clip)."""
        return int((words[b].end - words[a].end) * 1000)

    overlays = []
    chip = videos["videos:microprocessor-chip"]
    gif = manifest("gifs")["gifs:noto-1f62c"]
    meme = manifest("memes")["memes:imgflip-4087833"]
    for item, kind, path, ov in (
        (
            chip,
            "videos",
            chip["file"],
            dict(
                id="broll_cloud_computer",
                type="video",
                anchor_word="w143",
                offset_ms=0,
                # Hand off straight to the next scene: no flat speaker blip in between.
                duration_ms=int((words["w152"].start - words["w143"].end) * 1000),
                layout="cutaway_full",
                motion="push_in",
            ),
        ),
        (
            gif,
            "gifs",
            gif["file"],
            dict(
                id="emoji_grimace",
                type="gif",
                anchor_word="w29",
                duration_ms=1600,
                layout="pip_pop",
            ),
        ),
        (
            meme,
            "memes",
            meme["file"],
            dict(
                id="meme_waiting",
                type="meme",
                anchor_word="w86",
                duration_ms=span_ms("w86", "w94") + 100,
                layout="pip_pop",
            ),
        ),
    ):
        files[item["id"]] = str((Path("assets") / kind / path).resolve())
        overlays.append(
            Overlay(
                asset=item["id"],
                license=item["license"],
                attribution_required=bool(item.get("attribution_required")),
                attribution_text=item.get("attribution_text", ""),
                commercial_use=item["commercial_use"],
                **ov,
            )
        )
        if item.get("attribution_text"):
            credits.append(item["attribution_text"])
    tl = tl.model_copy(update={"overlays": overlays})

    # --- Scenes: (id, start, end, boundary, slot, role, spec kwargs, evidence, events) ----
    mono_white = dict(theme="mono", accent="white")
    shots: list[dict[str, Any]] = [
        dict(
            id="hook",
            span=("w9", "w20", "end"),
            slot="panel",
            role="promise",
            title="OpenAI just launched dots.",
            eyebrow="BREAKING / DEVDAY 2026",
            content=dict(
                template="proof_focus",
                asset_id="page_techcrunch",
                source_label="TECHCRUNCH · SEP 29, 2026",
                excerpt="Always-on agents that work for you 24/7.",
                crop=[0.0, 0.3, 1.0, 0.42],
                focus_crop=[0.44, 0.44, 0.56, 0.24],
                annotations=[
                    dict(id="headline", x=0.47, y=0.52, width=0.5, height=0.1, label="LAUNCH")
                ],
            ),
            tokens=dict(theme="mono", accent="teal"),
            entrance="flash",
            evidence=["page_techcrunch"],
            observed=True,
            events=[
                ("body", "reveal", "w9"),
                ("headline", "reveal", "w13"),
                ("body", "focus", "w15"),
            ],
        ),
        dict(
            id="legacy",
            span=("w21", "w27", "start"),
            role="promise",
            title="Get off the\nlegacy API.",
            eyebrow="THE TASK / 00",
            content=dict(
                template="metric_or_code",
                value="EOL",
                label="The old API shuts down soon.",
                code=[
                    "// Illustrative migration",
                    "legacy.request(...)",
                    "  -> new_api.request(...)",
                ],
            ),
            tokens=dict(theme="mono", accent="red"),
            entrance="zoom",
            evidence=[],
            events=[("body", "reveal", "w21"), ("body", "highlight", "w25")],
        ),
        dict(
            id="codebase",
            span=("w32", "w54", "start"),
            role="mechanism",
            title="Used all over\nthe codebase.",
            eyebrow="THE PROBLEM / 01",
            content=dict(
                template="hub",
                center="Legacy API",
                center_pictogram="warning",
                spokes=[
                    dict(id="web", label="Web app", pictogram="browser"),
                    dict(id="mobile", label="Mobile", pictogram="mobile"),
                    dict(id="workers", label="Workers", pictogram="server"),
                    dict(id="billing", label="Billing", pictogram="card"),
                    dict(id="search", label="Search", pictogram="search"),
                    dict(id="admin", label="Admin", pictogram="user"),
                ],
            ),
            tokens=dict(theme="mono", accent="red"),
            entrance="glitch",
            evidence=[],
            events=[
                ("hub", "reveal", "w33"),
                ("web", "reveal", "w36"),
                ("mobile", "reveal", "w37"),
                ("workers", "reveal", "w38"),
                ("billing", "reveal", "w40"),
                ("search", "reveal", "w41"),
                ("admin", "reveal", "w43"),
                ("search", "update", "w45", "unknown"),
                ("billing", "update", "w48", "rejected"),
                ("mobile", "update", "w48", "rejected"),
            ],
        ),
        dict(
            id="stage_proof",
            span=("w54", "w68", "start"),
            role="evidence",
            title="On stage: the\nagent's activity.",
            eyebrow="SOURCE / DEVDAY",
            content=dict(
                template="proof_focus",
                asset_id="slide_checklist",
                source_label="OPENAI DEVDAY 2026 · STAGE SCREEN",
                excerpt=(
                    "Trace dependencies → read the migration docs → plan → "
                    "write code and run tests."
                ),
                focus_crop=[0, 0.12, 0.7, 0.52],
                annotations=[
                    dict(id="trace_box", x=0.05, y=0.27, width=0.42, height=0.11, label="STEP 1")
                ],
            ),
            tokens=dict(theme="mono", accent="teal"),
            entrance="rise",
            evidence=["slide_checklist"],
            observed=True,
            events=[
                ("body", "reveal", "w54"),
                ("trace_box", "reveal", "w57"),
                ("body", "focus", "w59"),
            ],
        ),
        dict(
            id="agent_steps",
            span=("w68", "w83", "end"),
            role="demonstration",
            title="Then it does\nthe work.",
            eyebrow="THE AGENT / 02",
            content=dict(
                template="checklist",
                items=[
                    dict(id="trace", label="Trace dependencies"),
                    dict(id="code", label="Write the code"),
                    dict(id="tests", label="Run the tests"),
                    dict(id="pr", label="Open pull requests"),
                ],
            ),
            tokens=dict(theme="mono", accent="teal"),
            evidence=["slide_checklist"],
            events=[
                ("trace", "reveal", "w68"),
                ("trace", "update", "w69", "accepted"),
                ("code", "reveal", "w70"),
                ("code", "update", "w72", "accepted"),
                ("tests", "reveal", "w73"),
                ("tests", "update", "w75", "accepted"),
                ("pr", "reveal", "w77"),
                ("pr", "update", "w81", "accepted"),
            ],
        ),
        dict(
            id="old_way",
            span=("w95", "w109", "end"),
            role="transition",
            title="The old way.",
            eyebrow="BEFORE DOTS / 03",
            content=dict(
                template="multi_view",
                tiles=[
                    dict(id="people", label="How many people?", glyph="?", pictogram="people"),
                    dict(id="time", label="How much time?", glyph="?", pictogram="clock"),
                ],
            ),
            tokens=dict(theme="mono", accent="red"),
            entrance="zoom",
            evidence=[],
            events=[
                ("people", "reveal", "w96"),
                ("people", "highlight", "w97"),
                ("time", "reveal", "w103"),
                ("time", "highlight", "w104"),
            ],
        ),
        dict(
            id="toolkit",
            span=("w152", "w163", "end"),
            role="mechanism",
            title="Everything it\nneeds to work.",
            eyebrow="ONBOARDING / 04",
            content=dict(
                template="hub",
                center="Your dot",
                center_asset_id="icon_openai",
                spokes=[
                    dict(id="access", label="Your access", pictogram="key"),
                    dict(id="computer", label="Cloud computer", pictogram="cloud"),
                    dict(id="browser", label="Own browser", pictogram="browser"),
                    dict(id="testing", label="Code + tests", pictogram="flask"),
                ],
            ),
            tokens=mono_white,
            entrance="rise",
            evidence=["icon_openai"],
            events=[
                ("hub", "reveal", "w152"),
                ("access", "reveal", "w152"),
                ("computer", "reveal", "w153"),
                ("browser", "reveal", "w154"),
                ("testing", "reveal", "w160"),
            ],
        ),
        dict(
            id="team",
            span=("w164", "w188", "end"),
            role="result",
            title="Start with one.\nScale to a team.",
            eyebrow="ROADMAP / 05",
            content=dict(
                template="counter",
                value=1,
                label="dot today, a whole team later",
                cells=48,
            ),
            tokens=dict(theme="mono", accent="yellow"),
            entrance="zoom",
            evidence=[],
            events=[("value", "reveal", "w170"), ("grid", "reveal", "w185")],
        ),
        dict(
            id="anywhere",
            span=("w189", "w248", "end"),
            slot="panel",
            role="demonstration",
            title="Text it. Call it.",
            eyebrow="ANYWHERE / 06",
            content=dict(
                template="multi_view",
                tiles=[
                    dict(id="text_tile", label="Talk outside ChatGPT", asset_id="phone_text"),
                    dict(id="call_tile", label="Or give it a call", asset_id="phone_call"),
                ],
            ),
            tokens=dict(theme="mono", accent="teal"),
            entrance="rise",
            evidence=["phone_text", "phone_call"],
            observed=True,
            events=[
                ("text_tile", "reveal", "w189"),
                ("text_tile", "highlight", "w199"),
                ("call_tile", "reveal", "w239"),
                ("call_tile", "highlight", "w243"),
            ],
        ),
        dict(
            id="apps_count",
            span=("w249", "w258", "start"),
            role="evidence",
            title="Works with\nyour apps.",
            eyebrow="INTEGRATIONS / 07",
            content=dict(
                template="counter",
                value=4000,
                suffix="+",
                label="apps across ChatGPT",
                cells=64,
            ),
            tokens=dict(theme="mono", accent="teal"),
            entrance="zoom",
            evidence=[],
            events=[("value", "reveal", "w253")],
        ),
        dict(
            id="apps_proof",
            span=("w258", "w263", "start"),
            role="evidence",
            title="Straight from\nOpenAI.",
            eyebrow="SOURCE / OPENAI",
            content=dict(
                template="proof_focus",
                asset_id="page_apps",
                source_label="OPENAI.COM · INTRODUCING DOTS",
                excerpt="Through plugins, dots readily connect to over 4,000 apps.",
                crop=[0.1, 0.02, 0.8, 0.96],
                focus_crop=[0.12, 0.34, 0.66, 0.3],
                annotations=[
                    dict(id="apps_hl", x=0.3, y=0.465, width=0.36, height=0.06, label="CLAIM")
                ],
            ),
            tokens=dict(theme="mono", accent="teal"),
            entrance="rise",
            evidence=["page_apps"],
            observed=True,
            events=[("apps_hl", "reveal", "w258"), ("body", "focus", "w259")],
        ),
        dict(
            id="plugins",
            span=("w263", "w275", "end"),
            role="mechanism",
            title="Same plugins you\nalready connected.",
            eyebrow="INTEGRATIONS / 08",
            content=dict(
                template="hub",
                center="Your dot",
                center_asset_id="icon_openai",
                spokes=[
                    dict(id=n, label=n.title(), asset_id=f"icon_{n}")
                    for n in ("github", "gmail", "notion", "figma", "google", "discord")
                ],
            ),
            tokens=mono_white,
            evidence=[
                f"icon_{n}"
                for n in ("openai", "github", "gmail", "notion", "figma", "google", "discord")
            ],
            events=[
                ("hub", "reveal", "w263"),
                ("github", "reveal", "w264"),
                ("gmail", "reveal", "w265"),
                ("notion", "reveal", "w267"),
                ("figma", "reveal", "w269"),
                ("google", "reveal", "w272"),
                ("discord", "reveal", "w274"),
            ],
        ),
        dict(
            id="control_proof",
            span=("w288", "w296", "start"),
            role="evidence",
            title="You stay\nin control.",
            eyebrow="SAFEGUARDS / OPENAI",
            content=dict(
                template="proof_focus",
                asset_id="page_control",
                source_label="OPENAI.COM · INTRODUCING DOTS",
                excerpt="Sensitive tasks, like changing a password, always stay with you.",
                crop=[0.1, 0.02, 0.8, 0.96],
                focus_crop=[0.12, 0.3, 0.66, 0.32],
                annotations=[
                    dict(id="control_hl", x=0.26, y=0.465, width=0.42, height=0.06, label="RULE")
                ],
            ),
            tokens=dict(theme="mono", accent="teal"),
            entrance="rise",
            evidence=["page_control"],
            observed=True,
            events=[
                ("body", "reveal", "w288"),
                ("control_hl", "reveal", "w293"),
                ("body", "focus", "w294"),
            ],
        ),
        dict(
            id="astra",
            span=("w296", "w304", "end"),
            role="result",
            title="Powered by Astra",
            content=dict(
                template="impact_title",
                kicker="OpenAI's most aligned model",
                headline="Powered by Astra",
                asset_id="neural_still",
            ),
            tokens=dict(theme="mono", accent="teal"),
            entrance="flash",
            evidence=["neural_still"],
            events=[("title", "reveal", "w296")],
        ),
    ]

    claims, beats, specs, placements = [], [], [], []
    for i, shot in enumerate(shots):
        start, end, boundary = shot["span"]
        last = end if boundary == "end" else f"w{int(end[1:]) - 1}"
        said = [
            w.text for w in transcript.words if int(start[1:]) <= int(w.id[1:]) <= int(last[1:])
        ]
        cid = "claim_" + shot["id"]
        claims.append(
            Claim(
                id=cid,
                start_word=start,
                end_word=last,
                entity="OpenAI dots",
                assertion=" ".join(said)[:400],
                caveat="Keynote claims; product behaviour is not independently verified here.",
                evidence_ids=shot["evidence"],
            )
        )
        beats.append(
            StoryboardBeat(
                id="beat_" + shot["id"],
                start_word=start,
                end_word=last,
                role=shot["role"],
                family=shot["content"]["template"],
                understanding=shot["title"].replace("\n", " "),
                claim_ids=[cid],
                evidence_ids=shot["evidence"],
                unresolved_needs=[]
                if shot.get("observed")
                else ["Illustration of the spoken claim, not captured product output."],
                scene_id=shot["id"],
            )
        )
        specs.append(
            SceneSpec(
                id=shot["id"],
                title=shot["title"],
                eyebrow=shot.get("eyebrow", f"DEVDAY / {i + 1:02d}"),
                content=shot["content"],
                tokens=shot["tokens"],
                entrance=shot.get("entrance", "cut"),
                evidence_ids=shot["evidence"],
                illustrative=not shot.get("observed", False),
                events=[
                    dict(
                        target=e[0],
                        action=e[1],
                        word=e[2],
                        state=e[3] if len(e) > 3 else "active",
                        preset="gentle",
                    )
                    for e in shot["events"]
                ],
            )
        )
        placements.append(
            ScenePlacement(
                scene_id=shot["id"],
                start_word=start,
                end_word=end,
                end_boundary=boundary,
                slot=shot.get("slot", "full"),
            )
        )
    board = Storyboard(
        brief=CreativeBrief(
            audience="Hackathon judges and AI builders",
            promise="Turn a real launch livestream into a reference-grade explainer short",
            takeaway="Dots are always-on agents that do multi-step engineering work",
            permitted_changes=[
                "Cut pauses and two tangents",
                "Add captions, diagrams, proof stills, B-roll, memes, music and SFX",
            ],
            source_limitations=[
                "Landscape stage footage reframed to vertical",
                "Keynote claims are presented as claims, not verified results",
                "Local ASR may contain recognition errors",
            ],
        ),
        timing_hash=timing_hash(tl),
        claims=claims,
        beats=beats,
        evidence=evidence,
    )
    tl = attach_storyboard(tl, board, expected_version=1).model_copy(
        update={"scenes": specs, "scene_placements": placements}
    )

    # --- Sound design: CC0 accents on reveals; never louder than the voice. ---------
    sfx_ids = {
        "boom": "sfx:210a2965-2408-40d4-a1fc-97caed05f251",
        "whoosh": "sfx:0453066f-9cb0-426e-b51f-539f0b2acabb",
        "swoosh": "sfx:d541f407-6b6d-4588-b54c-ed30e20b56b6",
        "pop": "sfx:6648e388-233f-44b7-9695-9f0b8ab3a588",
        "ding": "sfx:b3ccac7f-af65-4a18-8e1b-fad401935e25",
        "riser": "sfx:96a9062b-be8d-42ae-aacc-f64d3a34294a",
        "click": "sfx:31af539c-a760-411e-accc-f2017a490eca",
        "notify": "sfx:63ef9260-41de-44ee-822a-fe6e91af2fd5",
        "glitch": "sfx:52980dee-2005-4339-bae5-a4973947b054",
    }
    sfx_lib = manifest("sfx")
    cues = [
        ("boom", "w9", -16, -300, 900),
        ("whoosh", "w20", -20, 0, 700),
        ("pop", "w29", -22, 0, 300),
        ("glitch", "w32", -22, -250, 500),
        ("click", "w36", -26, 0, 200),
        ("click", "w40", -26, 0, 200),
        ("glitch", "w48", -20, -150, 500),
        ("swoosh", "w54", -22, -250, 600),
        ("click", "w57", -24, 0, 200),
        ("ding", "w69", -24, 0, 500),
        ("ding", "w72", -24, 0, 500),
        ("ding", "w75", -24, 0, 500),
        ("ding", "w81", -22, 0, 600),
        ("pop", "w86", -22, 0, 300),
        ("whoosh", "w95", -22, -250, 600),
        ("swoosh", "w152", -22, -250, 600),
        ("whoosh", "w143", -22, -200, 600),
        ("click", "w154", -26, 0, 200),
        ("click", "w160", -26, 0, 200),
        ("riser", "w164", -26, 0, 1500),
        ("boom", "w185", -22, 0, 700),
        ("notify", "w199", -22, 0, 600),
        ("notify", "w243", -22, 0, 600),
        ("riser", "w249", -26, -300, 1400),
        ("boom", "w255", -20, 0, 800),
        ("click", "w258", -22, 0, 200),
        ("swoosh", "w288", -22, -200, 600),
        ("click", "w293", -22, 0, 200),
        ("pop", "w264", -26, 0, 250),
        ("pop", "w267", -26, 0, 250),
        ("pop", "w272", -26, 0, 250),
        ("boom", "w296", -16, -300, 1000),
    ]
    hits = []
    for i, (kind, word, gain, offset, max_ms) in enumerate(cues):
        item = sfx_lib[sfx_ids[kind]]
        files[item["id"]] = str((Path("assets/sfx") / item["file"]).resolve())
        hits.append(
            SfxHit(
                id=f"sfx{i:02d}_{kind}",
                asset=item["id"],
                anchor_word=word,
                offset_ms=offset,
                gain_db=gain,
                max_ms=max_ms,
                license=item["license"],
                commercial_use=item["commercial_use"],
                attribution_text=item.get("attribution_text", ""),
            )
        )
    tl = tl.model_copy(update={"sfx": hits})
    ensure_valid(tl)
    put_artifact(store, board)
    (ROOT / "timeline.json").write_text(tl.model_dump_json(indent=2))
    (ROOT / "asset-files.json").write_text(json.dumps(files, indent=2))
    (ROOT / "credits.txt").write_text("\n".join(dict.fromkeys(filter(None, credits))) + "\n")
    (ROOT / "source-manifest.json").write_text(
        json.dumps(
            {
                "source": SOURCE,
                "source_range": "06:18–07:46 (master = source.mp4 + 3 s, 88 s)",
                "download_sha256": hashlib.sha256((ROOT / "source.mp4").read_bytes()).hexdigest(),
                "output_duration_s": tl.duration_s,
                "clips": len(clips),
                "scene_count": len(specs),
                "evidence_count": len(evidence),
                "overlays": [o.id for o in overlays],
                "sfx_count": len(hits),
                "monetized": False,
            },
            indent=2,
        )
    )
    print(
        f"Authored {len(specs)} scenes, {len(overlays)} overlays, {len(evidence)} evidence, "
        f"{len(hits)} SFX over {len(clips)} clips; {tl.duration_s}s"
    )


if __name__ == "__main__":
    main()
