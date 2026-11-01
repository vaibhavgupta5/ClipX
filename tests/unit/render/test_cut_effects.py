"""Face-anchored zooms, per-clip cut effects and the segment cache key."""

from app.render.edl_to_ffmpeg import cut_style, face_anchor
from app.render.graph import StaticZoom, TransitionIn, ZoomPunch
from app.render.segments import Segment, slice_hash
from app.timeline.schema import VideoClip, Zoom
from tests.unit.timeline.test_ops import _timeline


def test_face_anchor_uses_tracked_face_and_clamps() -> None:
    assert face_anchor(None) == (0.5, 0.42)
    assert face_anchor(((0.0, 0.3, 0.31), (1.0, 0.4, 0.33), (2.0, 0.4, 0.35))) == (0.5, 0.33)
    assert face_anchor(((0.0, 0.5, 0.95),)) == (0.5, 0.7)


def test_zoom_and_transition_scale_about_the_anchor() -> None:
    punch = ZoomPunch("[a]", at=1, dur_s=0.2, scale=1.2, width=1080, height=1920, anchor=(0.5, 0.3))
    assert "x=(iw-ow)*0.500:y=(ih-oh)*0.300" in punch.render("[b]")
    cut = TransitionIn("[a]", "zoom_in", 1080, 1920, (0.5, 0.3)).render("[b]")
    assert "pow(" in cut and "y=(ih-oh)*0.300" in cut
    assert StaticZoom("[a]", 1.0, 1080, 1920).render("[b]") == "[a]null[b]"
    hold = StaticZoom("[a]", 1.15, 1080, 1920, (0.5, 0.3)).render("[b]")
    assert "scale=1242:2208" in hold and "crop=1080:1920" in hold


def test_clip_transition_overrides_timeline_default() -> None:
    tl = _timeline().model_copy(update={"transition": "zoom_in"})
    clip = tl.video_clips[0]
    assert cut_style(tl, clip) == "zoom_in"
    assert cut_style(tl, clip.model_copy(update={"transition_in": "whip"})) == "whip"
    assert cut_style(tl, clip.model_copy(update={"transition_in": "none"})) == "none"


def test_zoom_parameters_change_the_segment_cache_key() -> None:
    clip = VideoClip(id="c", asset="a", src_in=0, src_out=2)
    seg = Segment(index=0, start=0, end=2, clips=[clip], overlays=[], cues=[], zooms=[])
    a = seg.model_copy(update={"zooms": [(Zoom(id="z", anchor_word="w1", scale=1.1), 0.5)]})
    b = seg.model_copy(update={"zooms": [(Zoom(id="z", anchor_word="w1", scale=1.3), 0.5)]})
    assert slice_hash(a, "v", "", {}) != slice_hash(b, "v", "", {})


def test_visual_clip_fields_do_not_stale_the_storyboard_timing() -> None:
    from app.scenes.timing import timing_hash

    tl = _timeline()
    clip = tl.video_clips[0].model_copy(update={"transition_in": "whip", "framing_zoom": 1.2})
    styled = tl.model_copy(update={"video_clips": [clip, *tl.video_clips[1:]]})
    assert timing_hash(styled) == timing_hash(tl)
    trimmed = tl.video_clips[0].model_copy(update={"src_out": tl.video_clips[0].src_out - 0.1})
    assert timing_hash(tl.model_copy(update={"video_clips": [trimmed, *tl.video_clips[1:]]})) != (
        timing_hash(tl)
    )


def test_segments_keep_per_clip_cut_effects() -> None:
    from app.render.segments import split_segments

    tl = _timeline()
    clips = [
        c.model_copy(update={"transition_in": "whip", "framing_zoom": 1.1}) for c in tl.video_clips
    ]
    segments = split_segments(tl.model_copy(update={"video_clips": clips}))
    assert segments and all(
        s.clips[0].transition_in == "whip" and s.clips[0].framing_zoom == 1.1 for s in segments
    )


def test_drift_uses_source_time_so_slices_stay_continuous() -> None:
    from app.render.graph import Drift

    assert Drift("[a]", 0.0, 3.0, 1080, 1920).render("[b]") == "[a]null[b]"
    out = Drift("[a]", 0.04, 12.5, 1080, 1920, (0.5, 0.3)).render("[b]")
    assert "(t+12.500)" in out and "y=(ih-oh)*0.300" in out


def test_scene_exit_applies_when_raw_footage_returns_after_a_scene() -> None:
    from app.render.render import segment_cut_effect

    tl = _timeline().model_copy(update={"scene_exit": "zoom_in"})
    clip = tl.video_clips[0]
    seg = Segment(index=1, start=1, end=2, clips=[clip], overlays=[], cues=[], zooms=[])
    assert segment_cut_effect(tl, seg) == "none"
    assert segment_cut_effect(tl, seg.model_copy(update={"after_scene": True})) == "zoom_in"
    whip = seg.model_copy(
        update={"is_real_cut": True, "clips": [clip.model_copy(update={"transition_in": "whip"})]}
    )
    assert segment_cut_effect(tl, whip) == "whip"


def test_set_transition_tool_overrides_clips_and_rejects_unknown_ids() -> None:
    from app.tools.executor import ToolFailure, ToolState, execute

    tl = _timeline()
    first = tl.video_clips[0].id
    out = execute(
        "set_transition",
        {"style": "whip", "clip_ids": [first], "scene_exit": "zoom_in", "speaker_drift": 0.04},
        ToolState(tl),
    )
    assert not isinstance(out, ToolFailure) and out.timeline is not None
    assert out.timeline.video_clips[0].transition_in == "whip"
    assert out.timeline.transition == tl.transition
    assert (out.timeline.scene_exit, out.timeline.speaker_drift) == ("zoom_in", 0.04)
    bad = execute("set_transition", {"style": "whip", "clip_ids": ["nope"]}, ToolState(tl))
    assert isinstance(bad, ToolFailure) and "unknown_clip" in bad.message()


def test_add_zooms_skips_words_without_a_face() -> None:
    from app.analysis.models import FaceBox
    from app.tools.executor import ToolFailure, ToolState, execute

    tl = _timeline()
    words = [w.id for w in tl.transcript.words]
    far = tl.transcript.words[-1].start + 50
    out = execute(
        "add_zooms",
        {"word_ids": words[:1]},
        ToolState(tl, faces=[FaceBox(t=far, x=0.4, y=0.2, w=0.2, h=0.3)]),
    )
    assert not isinstance(out, ToolFailure)
    assert "no face on screen" in str(out.fields)


def test_failed_capture_reason_reaches_the_model() -> None:
    from app.tools.executor import ToolFailure, ToolState, execute

    state = ToolState(_timeline(), preparation_error="highlight_text 'x' was not found on the page")
    out = execute(
        "capture_webpage",
        {"url": "https://example.com", "at_word": _timeline().transcript.words[0].id},
        state,
    )
    assert isinstance(out, ToolFailure)
    assert "was not found on the page" in out.message() and "stock" in out.message()


def test_scene_frame_limits_tolerate_cut_noise_but_not_wrong_content() -> None:
    from app.render.scene_quality import exceeds_limits

    assert not exceeds_limits(2.2, 0.025, frames_into_scene=0)  # encoder noise after a cut
    assert exceeds_limits(2.2, 0.025, frames_into_scene=10)  # same noise mid-scene: strict
    assert exceeds_limits(67.9, 0.97, frames_into_scene=0)  # the scene is not on screen
    assert not exceeds_limits(6.2, 0.02, frames_into_scene=0)  # glitch/flash entrance noise
    assert exceeds_limits(6.2, 0.02, frames_into_scene=10)  # same numbers mid-scene: strict
    assert exceeds_limits(10.5, 0.0, frames_into_scene=0)  # the settle allowance is bounded
