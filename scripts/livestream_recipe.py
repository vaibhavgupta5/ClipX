"""Authored, source-grounded judge demo using ClipZ's actual Phase 7c contracts."""

import hashlib
import io
import json
import uuid
from pathlib import Path

from PIL import Image

from app.scenes.models import ScenePlacement, SceneSpec
from app.scenes.timing import timing_hash
from app.storage import LocalStorage
from app.storyboard.models import Claim, CreativeBrief, Storyboard, StoryboardBeat
from app.storyboard.planner import attach_storyboard
from app.storyboard.store import put_artifact
from app.timeline.schema import AudioEffect, CaptionConfig, MusicBed, SfxHit, Timeline, VideoClip
from app.timeline.transcript import Transcript
from app.visuals.evidence import freeze_image

ROOT = Path("work/livestream-impact").resolve()
SOURCE = "https://www.youtube.com/watch?v=dBCLS8myarc&t=1200s"


def main() -> None:
    transcript = Transcript.model_validate_json((ROOT / "transcript.json").read_text())
    store = LocalStorage("upload", "work", "editedVideo")
    store.ensure_dirs()
    project_id = uuid.UUID("8e62e853-bb52-4b50-b278-7b47ff8bb532")
    evidence = []
    files = {}
    credits = [f"Source: ThePrimeTime livestream excerpt, 20:00–21:00. {SOURCE}"]
    for name in ("require", "loaded", "neovim_readme"):
        item = json.loads((ROOT / f"capture-{name}.json").read_text())
        data = (ROOT / "assets/showcase" / item["file"]).read_bytes()
        evidence.append(
            freeze_image(
                store,
                data,
                asset_id=name,
                source=item["source_url"],
                entity="Lua" if name != "neovim_readme" else "Neovim",
                role="proof_focus",
                license=item["license"],
                commercial_use=item["commercial_use"],
                kind="observed",
                project_id=project_id,
                attribution=item["source_url"],
                text="Official documentation or repository detail, not an executed result.",
            )
        )
        credits.append(item["source_url"])
    icons = json.loads(Path("assets/icons/manifest.json").read_text())
    logo = next(i for i in icons if i["id"] == "icons:neovim")
    evidence.append(
        freeze_image(
            store,
            (Path("assets/icons") / logo["file"]).read_bytes(),
            asset_id="neovim_logo",
            source=logo["source_url"],
            entity="Neovim",
            role="speaker_bridge",
            license=logo["license"],
            commercial_use=logo["commercial_use"],
            attribution=logo["attribution_text"],
            project_id=project_id,
        )
    )
    library = json.loads(Path("assets/images/manifest.json").read_text())
    photo = next(i for i in library if i["id"] == "images:595a4dbf-ede9-4f77-b5b5-54e164844fb1")
    evidence.append(
        freeze_image(
            store,
            (Path("assets/images") / photo["file"]).read_bytes(),
            asset_id="coding_broll",
            source=photo["source_url"],
            entity="Code",
            role="proof_focus",
            license=photo["license"],
            commercial_use=photo["commercial_use"],
            attribution=photo["attribution_text"],
            project_id=project_id,
        )
    )
    credits += [photo["attribution_text"], logo["attribution_text"]]
    # The same stream includes the actual correction. Preserve that evidence, including
    # its limited source detail, rather than fabricating a successful code execution.
    from app.agent.critic import extract_frame_bytes

    frame = Image.open(io.BytesIO(extract_frame_bytes(ROOT / "master.mp4", 55)))
    frame = frame.crop((0, 90, 1450, 875))
    buf = io.BytesIO()
    frame.save(buf, format="PNG")
    evidence.append(
        freeze_image(
            store,
            buf.getvalue(),
            asset_id="recorded_result",
            source=SOURCE,
            entity="Livestream result",
            role="proof_focus",
            license="youtube-standard-test-excerpt",
            commercial_use=False,
            kind="observed",
            project_id=project_id,
            attribution="Original livestream recording; demonstration use.",
        )
    )
    music = json.loads(Path("assets/music/manifest.json").read_text())
    track = next(i for i in music if i["id"] == "music:b386828e-b628-45f6-b900-6441a49cc977")
    files[track["id"]] = str((Path("assets/music") / track["file"]).resolve())
    credits.append(track["attribution_text"])
    tl = Timeline(
        project_id=project_id,
        version=1,
        transcript=transcript,
        video_clips=[VideoClip(id="original", asset="livestream", src_in=0.92, src_out=54.0)],
        reframe="split_bottom",
        speaker_zoom=3.0,
        captions=CaptionConfig(
            mode="word_highlight",
            position="showcase",
            words_per_line=3,
            size_px=58,
            base_color="#F7F6EF",
            highlight_color="#70F1BD",
            animation="none",
        ),
        audio_fx=[AudioEffect(type="loudnorm", params={"lufs": -14})],
        music=MusicBed(
            asset=track["id"],
            license=track["license"],
            attribution_required=True,
            attribution_text=track["attribution_text"],
            level_db=-26,
            commercial_use=track["commercial_use"],
        ),
    )
    # Every shot is anchored to actual recognized words. The last observation is a
    # negative result, exactly as the speaker says; diagrams are labelled illustrations.
    shots = [
        dict(
            id="hook",
            start="w3",
            last="w18",
            role="promise",
            slot="panel",
            title="Why your change\nisn't live.",
            content=dict(
                template="speaker_bridge",
                asset_id="neovim_logo",
                headline="Reload ≠ hot reload.",
                supporting="A live debugging question, visualized.",
            ),
            evidence=["neovim_logo"],
            events=[("title", "reveal", "w3", "active"), ("body", "reveal", "w7", "active")],
        ),
        dict(
            id="broll",
            start="w19",
            last="w22",
            role="transition",
            slot="panel",
            title="Change the code.\nWhat updates?",
            content=dict(
                template="proof_focus",
                asset_id="coding_broll",
                source_label="LICENSED CODE B-ROLL",
                excerpt="Illustration: a code change is not the same as a running update.",
            ),
            evidence=["coding_broll"],
            events=[("title", "reveal", "w19", "active")],
        ),
        dict(
            id="question",
            start="w23",
            last="w26",
            role="promise",
            slot="full",
            title="Can you skip\nthe reload?",
            content=dict(
                template="before_after",
                before="The file changes on disk.",
                after="Does the running plugin update?",
                change="This is the question being tested.",
            ),
            evidence=[],
            events=[
                ("before", "reveal", "w23", "active"),
                ("after", "reveal", "w24", "active"),
                ("after", "highlight", "w26", "active"),
            ],
        ),
        dict(
            id="hypothesis",
            start="w27",
            last="w34",
            role="mechanism",
            slot="full",
            title="The hypothesis.",
            content=dict(
                template="metric_or_code",
                value="nil?",
                label="Clear the Lua module reference?",
                code=[
                    "-- Hypothesis from the livestream",
                    "module = nil",
                    "-- Does that trigger a reload?",
                ],
            ),
            evidence=[],
            events=[("body", "reveal", "w27", "active"), ("body", "highlight", "w34", "active")],
        ),
        dict(
            id="architecture",
            start="w35",
            last="w54",
            role="mechanism",
            slot="full",
            title="How modules\nreach memory.",
            content=dict(
                template="architecture_flow",
                nodes=[
                    dict(id="request", label="require(module)", detail="Request a module"),
                    dict(id="loader", label="Module loader", detail="Find and run its loader"),
                    dict(id="cache", label="package.loaded", detail="Remember the returned value"),
                    dict(id="runtime", label="Running code", detail="Use the loaded module"),
                ],
                edges=[
                    dict(id="load", source="request", target="loader"),
                    dict(id="store", source="loader", target="cache"),
                    dict(id="use", source="cache", target="runtime"),
                ],
            ),
            evidence=["require", "loaded"],
            events=[
                ("request", "reveal", "w36", "active"),
                ("loader", "reveal", "w39", "active"),
                ("load", "connect", "w39", "active"),
                ("cache", "reveal", "w43", "active"),
                ("store", "connect", "w43", "active"),
                ("runtime", "reveal", "w48", "active"),
                ("use", "connect", "w54", "active"),
            ],
        ),
        dict(
            id="source_proof",
            start="w55",
            last="w76",
            role="evidence",
            slot="full",
            title="The actual\nLua contract.",
            content=dict(
                template="proof_focus",
                asset_id="require",
                source_label="LUA 5.1 REFERENCE MANUAL · REQUIRE",
                excerpt="The module cache is checked before a loader is used.",
                crop=[0, 0, 1, 1],
                focus_crop=[0, 0.18, 1, 0.58],
                annotations=[
                    dict(
                        id="cache_box",
                        x=0.35,
                        y=0.24,
                        width=0.23,
                        height=0.17,
                        label="CACHE LOOKUP",
                    )
                ],
            ),
            evidence=["require"],
            observed=True,
            events=[
                ("body", "reveal", "w55", "active"),
                ("cache_box", "reveal", "w59", "active"),
                ("body", "focus", "w61", "active"),
            ],
        ),
        dict(
            id="neovim",
            start="w77",
            last="w83",
            role="evidence",
            slot="panel",
            title="Inside the\nNeovim workflow.",
            content=dict(
                template="proof_focus",
                asset_id="neovim_readme",
                source_label="OFFICIAL NEOVIM REPOSITORY",
                excerpt="The speaker is describing a Lua-based plugin workflow.",
            ),
            evidence=["neovim_readme"],
            observed=True,
            events=[("body", "reveal", "w77", "active"), ("body", "highlight", "w78", "active")],
        ),
        dict(
            id="cache_proof",
            start="w84",
            last="w94",
            role="evidence",
            slot="full",
            title="A loaded module\nhas a cache entry.",
            content=dict(
                template="proof_focus",
                asset_id="loaded",
                source_label="LUA 5.1 · PACKAGE.LOADED",
                excerpt=(
                    "Changing a variable and invalidating the loader cache "
                    "are different operations."
                ),
                focus_crop=[0, 0, 1, 0.58],
                annotations=[
                    dict(
                        id="loaded_box",
                        x=0.44,
                        y=0.02,
                        width=0.55,
                        height=0.48,
                        label="LOADED MODULES",
                    )
                ],
            ),
            evidence=["loaded"],
            observed=True,
            events=[("loaded_box", "reveal", "w85", "active"), ("body", "focus", "w87", "active")],
        ),
        dict(
            id="verification",
            start="w95",
            last="w118",
            role="demonstration",
            slot="full",
            title="A plausible idea.\nStill unverified.",
            content=dict(
                template="verification_pipeline",
                nodes=[
                    dict(id="idea", label="Set module to nil", detail="The proposed change"),
                    dict(id="reload", label="Reload the code", detail="Requires a real trigger"),
                    dict(id="watch", label="Watch disk changes", detail="A separate capability"),
                    dict(
                        id="verdict", label="Hot reload?", detail="The speaker says “theoretically”"
                    ),
                ],
                edges=[
                    dict(id="attempt", source="idea", target="reload"),
                    dict(id="needs", source="reload", target="watch"),
                    dict(id="question_edge", source="watch", target="verdict"),
                ],
            ),
            evidence=["require", "loaded"],
            events=[
                ("idea", "reveal", "w95", "active"),
                ("reload", "reveal", "w102", "active"),
                ("attempt", "connect", "w103", "active"),
                ("watch", "reveal", "w109", "active"),
                ("needs", "connect", "w109", "active"),
                ("verdict", "reveal", "w113", "active"),
                ("question_edge", "connect", "w113", "active"),
                ("verdict", "update", "w116", "unknown"),
            ],
        ),
        dict(
            id="caveat",
            start="w119",
            last="w129",
            role="transition",
            slot="panel",
            title="Keep the caveat.",
            content=dict(
                template="speaker_bridge",
                headline="“The wrong tree.”",
                supporting="A hypothesis is not a confirmed result.",
            ),
            evidence=[],
            events=[("title", "reveal", "w119", "active"), ("body", "highlight", "w126", "active")],
        ),
        dict(
            id="observed_result",
            start="w130",
            last="w139",
            role="result",
            slot="full",
            title="Then the\nresult arrives.",
            content=dict(
                template="before_after",
                before="Maybe setting the module to nil is enough.",
                after="“It doesn’t do that.”",
                change="The correction stays in the edit.",
            ),
            evidence=["recorded_result"],
            events=[
                ("before", "reveal", "w130", "active"),
                ("after", "reveal", "w131", "active"),
                ("after", "update", "w132", "rejected"),
            ],
        ),
        dict(
            id="takeaway",
            start="w140",
            last="w146",
            role="result",
            slot="full",
            title="Cache reset\n≠ hot reload.",
            content=dict(
                template="metric_or_code",
                value="≠",
                label="A reload trigger still matters.",
                code=[
                    "-- Conceptual distinction",
                    "clear_cached_module()",
                    "-- is not the same as",
                    "watch_files_and_reload()",
                ],
            ),
            evidence=["require", "loaded"],
            events=[("body", "reveal", "w140", "active"), ("body", "highlight", "w144", "active")],
        ),
    ]
    claims = []
    beats = []
    specs = []
    placements = []
    for i, shot in enumerate(shots):
        words = [
            w
            for w in transcript.words
            if int(shot["start"][1:]) <= int(w.id[1:]) <= int(shot["last"][1:])
        ]
        cid = "claim_" + shot["id"]
        assertion = " ".join(w.text for w in words)
        claims.append(
            Claim(
                id=cid,
                start_word=shot["start"],
                end_word=shot["last"],
                entity="Lua reload discussion",
                assertion=assertion,
                caveat="Preserve the speaker’s uncertainty and final correction.",
                evidence_ids=shot["evidence"],
            )
        )
        beats.append(
            StoryboardBeat(
                id="beat_" + shot["id"],
                start_word=shot["start"],
                end_word=shot["last"],
                role=shot["role"],
                family=shot["content"]["template"],
                understanding=shot["title"].replace("\n", " "),
                claim_ids=[cid],
                evidence_ids=shot["evidence"],
                unresolved_needs=[]
                if shot["evidence"]
                else ["Illustration of the spoken hypothesis, not proof of execution."],
                scene_id=shot["id"],
            )
        )
        specs.append(
            SceneSpec(
                id=shot["id"],
                title=shot["title"],
                eyebrow=f"LIVE DEBUG  /  {i + 1:02d}",
                content=shot["content"],
                evidence_ids=shot["evidence"],
                illustrative=not shot.get("observed", False),
                events=[
                    dict(target=t, action=action, word=word, state=state, preset="gentle")
                    for t, action, word, state in shot["events"]
                ],
            )
        )
        if i + 1 < len(shots):
            end = shots[i + 1]["start"]
            boundary = "start"
        else:
            end = shot["last"]
            boundary = "end"
        placements.append(
            ScenePlacement(
                scene_id=shot["id"],
                start_word=shot["start"],
                end_word=end,
                end_boundary=boundary,
                slot=shot["slot"],
            )
        )
    board = Storyboard(
        brief=CreativeBrief(
            audience="Hackathon judges and technical creators",
            promise="Turn a real livestream explanation into a source-backed visual story",
            takeaway="Show the mechanism and preserve the actual result",
            permitted_changes=[
                "Trim dead ending",
                "Add subtitles, diagrams, evidence and restrained sound design",
            ],
            source_limitations=[
                "Small original webcam region",
                "Local ASR can contain recognition errors",
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
    sfx_library = json.loads(Path("assets/sfx/manifest.json").read_text())
    hits = []
    for i, (kind, word) in enumerate(
        [
            ("pop", "w7"),
            ("whoosh", "w27"),
            ("pop", "w39"),
            ("pop", "w59"),
            ("whoosh", "w84"),
            ("pop", "w116"),
            ("pop", "w132"),
        ]
    ):
        item = next(
            (x for x in sfx_library if x.get("sfx_type") == kind and x["commercial_use"]), None
        )
        if item:
            path = (Path("assets/sfx") / item["file"]).resolve()
            if path.exists():
                files[item["id"]] = str(path)
                hits.append(
                    SfxHit(
                        id=f"accent{i}",
                        asset=item["id"],
                        anchor_word=word,
                        offset_ms=0,
                        gain_db=-27,
                        max_ms=350,
                        license=item["license"],
                        commercial_use=item["commercial_use"],
                        attribution_text=item["attribution_text"],
                    )
                )
                if item["attribution_text"]:
                    credits.append(item["attribution_text"])
    tl = tl.model_copy(update={"sfx": hits})
    from app.timeline.validate import ensure_valid

    ensure_valid(tl)
    put_artifact(store, board)
    (ROOT / "timeline.json").write_text(tl.model_dump_json(indent=2))
    (ROOT / "asset-files.json").write_text(json.dumps(files, indent=2))
    (ROOT / "credits.txt").write_text("\n".join(dict.fromkeys(filter(None, credits))) + "\n")
    (ROOT / "source-manifest.json").write_text(
        json.dumps(
            {
                "source": SOURCE,
                "source_range_seconds": [1200, 1260],
                "download_sha256": hashlib.sha256((ROOT / "source.mp4").read_bytes()).hexdigest(),
                "retained_range_seconds": [0.92, 54],
                "output_duration_s": tl.duration_s,
                "scene_count": len(specs),
                "evidence_count": len(evidence),
                "sfx_count": len(hits),
                "monetized": False,
            },
            indent=2,
        )
    )
    print(
        f"Authored {len(specs)} scenes, {len(evidence)} evidence assets, "
        f"{len(hits)} sound accents; {tl.duration_s}s"
    )


if __name__ == "__main__":
    main()
