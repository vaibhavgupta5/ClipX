"""Regression coverage for cue truth, layer ownership, review evidence and revisions."""

import base64
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from pydantic import ValidationError

from app.agent.critic import evaluate_preview, evaluate_timeline_heuristic
from app.providers.base import ChatMessage, ChatRequest, ImagePart
from app.providers.gemini import GeminiLLM
from app.render.segments import split_segments
from app.scenes.compiler import compile_scenes
from app.scenes.models import ScenePlacement, SceneSpec
from app.scenes.timing import StalePlanError, TimingMap, timing_hash
from app.storage import MemoryStorage
from app.storyboard.models import CreativeBrief, StoryboardBeat
from app.storyboard.planner import (
    attach_storyboard,
    draft_storyboard,
    materialize_draft,
    update_scene,
)
from app.storyboard.store import content_hash, get_artifact, put_artifact
from app.timeline.schema import OutputSpec, Overlay, VideoClip
from app.timeline.versions import VersionLog
from app.tools.executor import ToolFailure, ToolState, execute
from app.visuals.evidence import freeze_image
from app.visuals.rank import rank_visuals
from app.workers.visual_review import ModelBudget
from tests.unit.timeline.test_ops import _timeline


def pixels(color: str = "white", size: tuple[int, int] = (640, 640)) -> bytes:
    image = Image.new("RGB", size, color)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def planned():  # type: ignore[no-untyped-def]
    tl = _timeline()
    board = draft_storyboard(
        tl,
        CreativeBrief(audience="Developers", promise="Show the mechanism", takeaway="Verify first"),
    )
    return materialize_draft(attach_storyboard(tl, board, expected_version=tl.version))


def test_old_snapshots_default_to_no_scenes() -> None:
    tl = _timeline()
    doc = tl.model_dump(mode="json")
    for key in ("storyboard", "storyboard_hash", "scenes", "scene_placements"):
        doc.pop(key)
    assert not type(tl).model_validate(doc).scenes
    assert compile_scenes(tl) == []


def test_half_open_frames_and_real_word_cues() -> None:
    tl = planned()
    scene = tl.scenes[0]
    scene = scene.model_copy(update={"events": []})
    compiled = compile_scenes(tl)[0]
    assert (
        compiled.start_frame
        == TimingMap.from_timeline(tl).words[tl.scene_placements[0].start_word][0]
    )
    assert compiled.end_frame > compiled.start_frame
    assert compiled.frame_count == compiled.end_frame - compiled.start_frame


def test_trim_invalidation_and_expected_version() -> None:
    tl = planned()
    trimmed = tl.model_copy(
        update={"video_clips": [VideoClip(id="trim", asset="a1", src_in=1, src_out=3)]}
    )
    with pytest.raises(StalePlanError, match="changed"):
        compile_scenes(trimmed)
    with pytest.raises(ValueError, match="stale revision"):
        update_scene(tl, tl.scenes[0], tl.scene_placements[0], expected_version=tl.version + 1)


def test_partial_word_and_reorder_cannot_silently_retime() -> None:
    tl = _timeline().model_copy(
        update={"video_clips": [VideoClip(id="trim", asset="a1", src_in=0.1, src_out=3)]}
    )
    with pytest.raises(StalePlanError, match="removed or split"):
        TimingMap.from_timeline(tl).interval("w1", "w1")


def test_unsupported_fps_is_explicit() -> None:
    with pytest.raises(ValueError, match="30 FPS"):
        TimingMap.from_timeline(_timeline().model_copy(update={"output": OutputSpec(fps=60)}))


def test_unknown_targets_executable_fields_and_graph_edges_rejected() -> None:
    with pytest.raises(ValidationError, match="event target"):
        SceneSpec(
            id="s",
            title="Demo",
            content={"template": "speaker_bridge", "headline": "Hello"},
            events=[{"target": "missing", "word": "w1", "action": "reveal"}],
        )
    with pytest.raises(ValidationError):
        SceneSpec(
            id="s",
            title="Demo",
            content={"template": "speaker_bridge", "headline": "Hello", "javascript": "alert(1)"},
        )
    with pytest.raises(ValidationError, match="endpoints"):
        SceneSpec(
            id="s",
            title="Demo",
            content={
                "template": "architecture_flow",
                "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                "edges": [{"id": "edge", "source": "a", "target": "missing"}],
            },
        )


def test_scene_edit_keeps_neighbor_and_undo_sources() -> None:
    tl = planned()
    old = tl.scenes[0]
    edited = old.model_copy(update={"title": "Revised focus"})
    result = update_scene(tl, edited, tl.scene_placements[0], expected_version=tl.version)
    assert tl.scenes[0].title != result.scenes[-1].title
    log = VersionLog().append(tl).append(result).undo()
    assert log.get(log.current).edl["scenes"][0]["title"] == old.title


def test_storyboard_hash_and_grounding_verified() -> None:
    tl = planned()
    with pytest.raises(ValueError, match="hash"):
        compile_scenes(tl.model_copy(update={"storyboard_hash": "0" * 64}))
    with pytest.raises(ValidationError, match="evidence"):
        StoryboardBeat(
            id="b",
            start_word="w1",
            end_word="w2",
            role="mechanism",
            family="architecture_flow",
            understanding="A relation",
            claim_ids=["claim"],
        )


def test_full_scene_ownership_suppresses_legacy_overlays() -> None:
    tl = planned()
    p = tl.scene_placements[0].model_copy(update={"slot": "full"})
    tl = tl.model_copy(
        update={
            "scene_placements": [p],
            "overlays": [
                Overlay(
                    id="old",
                    type="image",
                    asset="old",
                    anchor_word="w1",
                    offset_ms=0,
                    duration_ms=2000,
                    layout="split_top",
                    license="CC0",
                )
            ],
        }
    )
    scenes = [s for s in split_segments(tl) if s.scenes]
    assert scenes and all(not s.overlays for s in scenes)


def test_scene_phase_continues_across_cuts() -> None:
    tl = planned()
    clips = [
        VideoClip(id="a", asset="a1", src_in=0, src_out=1.5),
        VideoClip(id="b", asset="a1", src_in=1.5, src_out=3),
    ]
    board = tl.storyboard.model_copy(
        update={"timing_hash": timing_hash(tl.model_copy(update={"video_clips": clips}))}
    )
    tl = tl.model_copy(
        update={"video_clips": clips, "storyboard": board, "storyboard_hash": content_hash(board)}
    )
    segments = [s for s in split_segments(tl) if s.scenes]
    assert len(segments) >= 2
    assert segments[1].scenes[0][3] > segments[0].scenes[0][3]


def test_immutable_artifact_checksum() -> None:
    store = MemoryStorage()
    board = planned().storyboard
    digest = put_artifact(store, board)
    assert get_artifact(store, digest, type(board)) == board
    store.put_bytes(
        f"artifacts/{digest}.json",
        board.model_copy(update={"timing_hash": "0" * 64}).model_dump_json().encode(),
        "application/json",
    )
    with pytest.raises(ValueError, match="checksum"):
        get_artifact(store, digest, type(board))


def test_evidence_rank_provenance_dedupe_and_error_page() -> None:
    store = MemoryStorage()
    data = pixels()
    asset = freeze_image(
        store,
        data,
        asset_id="a",
        source="authored:demo",
        entity="Exact Product",
        role="proof_focus",
        license="CC0",
        kind="illustrative",
        commercial_use=False,
    )
    assert not asset.commercial_use
    result = rank_visuals(
        [asset, asset.model_copy(update={"id": "b"})], "Exact Product", "proof_focus"
    )
    assert len(result.selected) == 1 and "b" in result.rejected
    assert not rank_visuals([asset], "Wrong entity", "proof_focus").selected
    assert not rank_visuals([asset], "Exact Product", "proof_focus", require_observed=True).selected
    with pytest.raises(ValueError, match="error/interstitial"):
        freeze_image(
            store,
            data,
            asset_id="bad",
            source="https://example.com",
            entity="Demo",
            role="proof_focus",
            license="CC0",
            text="404 Not Found",
        )


def test_commercial_guard_carries_evidence_restrictions() -> None:
    tl = planned()
    store = MemoryStorage()
    asset = freeze_image(
        store,
        pixels(),
        asset_id="restricted",
        source="authored:demo",
        entity="Demo",
        role="proof_focus",
        license="personal",
        commercial_use=False,
    )
    board = tl.storyboard.model_copy(update={"evidence": [asset]})
    tl = tl.model_copy(update={"storyboard": board, "storyboard_hash": content_hash(board)})
    outcome = execute("export", {"monetized": True, "profile": "final"}, ToolState(tl))
    assert isinstance(outcome, ToolFailure)
    assert "restricted" in outcome.message()


def test_heurstic_never_claims_creative_pass() -> None:
    report = evaluate_timeline_heuristic(planned())
    assert report.verdict == "not_evaluated" and not report.reviewed_frames
    assert report.evidence == "timeline_only"


async def test_actual_image_bytes_reach_gemini_adapter() -> None:
    data = pixels()
    create = AsyncMock(
        return_value={
            "status": "completed",
            "steps": [{"type": "model_output", "content": [{"type": "text", "text": "visible"}]}],
        }
    )
    client = SimpleNamespace(aio=SimpleNamespace(interactions=SimpleNamespace(create=create)))
    llm = GeminiLLM("dummy", client=client)
    await llm.complete(
        ChatRequest(
            messages=[
                ChatMessage(
                    role="user",
                    content="Inspect",
                    images=[ImagePart(data=data, mime_type="image/png")],
                )
            ]
        )
    )
    parts = create.call_args.kwargs["input"][0]["content"]
    assert parts[1]["type"] == "image" and base64.b64decode(parts[1]["data"]) == data
    assert create.call_args.kwargs["store"] is False


async def test_unrendered_review_never_calls_model() -> None:
    llm = SimpleNamespace(complete=AsyncMock())
    result = await evaluate_preview(llm, planned())
    assert result.verdict == "not_evaluated"
    llm.complete.assert_not_called()


def test_media_payload_and_cumulative_failed_attempt_budget() -> None:
    with pytest.raises(ValidationError):
        ImagePart(data=b"not an image", mime_type="image/png")
    with pytest.raises(ValidationError):
        ChatRequest(
            messages=[
                ChatMessage(
                    role="system",
                    content="x",
                    images=[ImagePart(data=pixels(), mime_type="image/png")],
                )
            ]
        )
    body = {
        "input": [{"content": [{"type": "image", "data": base64.b64encode(pixels()).decode()}]}]
    }
    ledger = ModelBudget()
    for _ in range(6):
        ledger = ledger.reserve(body)
    assert ledger.requests == 6 and ledger.images == 6
    with pytest.raises(ValidationError):
        ledger.reserve(body)


def test_scene_tools_create_persistent_draft_and_inspect() -> None:
    tl = _timeline()
    outcome = execute(
        "plan_storyboard",
        {
            "expected_version": tl.version,
            "brief": {"audience": "Devs", "promise": "Explain", "takeaway": "Verify"},
            "create_draft_scenes": True,
        },
        ToolState(tl),
    )
    assert not isinstance(outcome, ToolFailure)
    assert outcome.timeline.storyboard and outcome.timeline.scenes
    inspected = execute(
        "inspect_scene", {"scene_id": outcome.timeline.scenes[0].id}, ToolState(outcome.timeline)
    )
    assert not isinstance(inspected, ToolFailure)
    assert inspected.output(version=1).end_frame > 0


def test_full_scene_captions_override_split_speaker_layout() -> None:
    from app.render.render import caption_position_for
    from app.timeline.schema import CaptionConfig

    tl = planned()
    placement = tl.scene_placements[0].model_copy(update={"slot": "full"})
    tl = tl.model_copy(
        update={
            "scene_placements": [placement],
            "reframe": "split_bottom",
            "captions": CaptionConfig(position="showcase"),
        }
    )
    segment = next(s for s in split_segments(tl) if s.scenes)
    assert caption_position_for(tl, segment, "split_bottom") == "showcase"
    panel = tl.model_copy(
        update={"scene_placements": [placement.model_copy(update={"slot": "panel"})]}
    )
    segment = next(s for s in split_segments(panel) if s.scenes)
    assert caption_position_for(panel, segment, "split_bottom") == "center"


def test_review_repair_is_bounded_and_does_not_accept_stale_reviews() -> None:
    from app.storyboard.models import QualityAssessment, QualityFinding
    from app.storyboard.repair import apply_review_repair

    tl = planned()
    spec = tl.scenes[0].model_copy(update={"title": "Readable focus"})
    review = QualityAssessment(
        timeline_hash="snapshot",
        render_hash="a" * 64,
        version=tl.version,
        technical_pass=True,
        creative_status="needs_edits",
        reviewed_frames=[0],
        findings=[
            QualityFinding(
                scene_id=spec.id, frame=0, severity="warning", observation="Title overflow"
            )
        ],
    )
    updated = apply_review_repair(
        tl,
        review,
        spec,
        tl.scene_placements[0],
        expected_version=tl.version,
        assessment_hash="b" * 64,
    )
    assert updated.scene_repair_count == 1 and tl.scene_repair_count == 0
    with pytest.raises(ValueError, match="already used"):
        apply_review_repair(
            updated,
            review,
            spec,
            tl.scene_placements[0],
            expected_version=tl.version,
            assessment_hash="b" * 64,
        )
    with pytest.raises(ValueError, match="stale"):
        apply_review_repair(
            tl,
            review.model_copy(update={"version": tl.version + 1}),
            spec,
            tl.scene_placements[0],
            expected_version=tl.version,
            assessment_hash="b" * 64,
        )


def test_same_frame_raster_check_rejects_visible_differences() -> None:
    from app.scenes.renderer import equivalent_pixels

    first = pixels("white")
    assert equivalent_pixels(first, first)
    assert not equivalent_pixels(first, pixels("black"))
    assert not equivalent_pixels(first, pixels("white", (320, 320)))


def test_proof_crop_annotation_permissions_and_bounds() -> None:
    with pytest.raises(ValidationError, match="inside"):
        SceneSpec(
            id="proof",
            title="Source",
            content={
                "template": "proof_focus",
                "asset_id": "source",
                "excerpt": "Evidence",
                "source_label": "Official documentation",
                "focus_crop": [0.9, 0, 0.5, 1],
            },
        )
    with pytest.raises(ValidationError, match="inside"):
        SceneSpec(
            id="proof",
            title="Source",
            content={
                "template": "proof_focus",
                "asset_id": "source",
                "excerpt": "Evidence",
                "source_label": "Official documentation",
                "annotations": [{"id": "highlight", "x": 0.9, "y": 0, "width": 0.5, "height": 0.2}],
            },
        )


def test_review_tool_does_not_invent_missing_evidence() -> None:
    result = execute("review_render", {}, ToolState(_timeline()))
    assert not isinstance(result, ToolFailure)
    assert result.output(version=1).creative_status == "not_evaluated"


def test_consecutive_scenes_share_an_exact_half_open_word_boundary() -> None:
    tl = planned()
    first = tl.scenes[0]
    second = first.model_copy(update={"id": "second"})
    beat = tl.storyboard.beats[0]
    board = tl.storyboard.model_copy(
        update={
            "beats": [
                beat.model_copy(update={"end_word": "w3", "scene_id": first.id}),
                beat.model_copy(
                    update={"id": "second_beat", "start_word": "w4", "scene_id": "second"}
                ),
            ]
        }
    )
    tl = tl.model_copy(
        update={
            "storyboard": board,
            "storyboard_hash": content_hash(board),
            "scenes": [second, first],
            "scene_placements": [
                ScenePlacement(scene_id="second", start_word="w4", end_word="w6"),
                ScenePlacement(
                    scene_id=first.id, start_word="w1", end_word="w4", end_boundary="start"
                ),
            ],
        }
    )
    schedule = compile_scenes(tl)
    assert schedule[0].end_frame == schedule[1].start_frame
    reversed_tl = tl.model_copy(
        update={
            "scenes": list(reversed(tl.scenes)),
            "scene_placements": list(reversed(tl.scene_placements)),
        }
    )
    assert compile_scenes(reversed_tl) == schedule


async def test_review_rejects_a_real_frame_attributed_to_the_wrong_scene(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from app.agent import critic
    from app.providers.base import ChatReply

    tl = planned()
    placement = tl.scene_placements[0].model_copy(update={"end_word": "w2"})
    tl = tl.model_copy(update={"scene_placements": [placement]})
    buffer = io.BytesIO()
    Image.new("RGB", (320, 480), "white").save(buffer, format="JPEG")
    monkeypatch.setattr(critic, "sample_review_frames", lambda *_: [(60, buffer.getvalue())])
    llm = SimpleNamespace(
        complete=AsyncMock(
            return_value=ChatReply(
                text=json.dumps(
                    {
                        "overall_score": 6,
                        "verdict": "needs_edits",
                        "findings": [
                            {
                                "scene_id": tl.scenes[0].id,
                                "frame": 60,
                                "severity": "warning",
                                "observation": "Crowded text",
                            }
                        ],
                    }
                )
            )
        )
    )
    result = await evaluate_preview(llm, tl, Path("encoded.mp4"))
    assert result.verdict == "not_evaluated"


def test_storyboard_edits_cannot_launder_frozen_evidence_permissions() -> None:
    from app.visuals.evidence import resolve_evidence

    store = MemoryStorage()
    asset = freeze_image(
        store,
        pixels(),
        asset_id="restricted",
        source="authored:test",
        entity="Demo",
        role="proof_focus",
        license="personal",
        commercial_use=False,
    )
    with pytest.raises(ValueError, match="permissions changed"):
        resolve_evidence(store, [asset.model_copy(update={"commercial_use": True})])


def test_clear_storyboard_restores_the_structural_edit_path() -> None:
    tl = planned()
    outcome = execute("clear_storyboard", {"expected_version": tl.version}, ToolState(tl))
    assert not isinstance(outcome, ToolFailure)
    assert outcome.timeline.storyboard is None and not outcome.timeline.scenes
    assert tl.storyboard is not None
