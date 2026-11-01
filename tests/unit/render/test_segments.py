"""Segment cache key: must change when the renderer's output for a slice can change."""

import pytest

from app.render import segments
from tests.unit.timeline.test_ops import _timeline


def test_slice_hash_changes_with_renderer_version(monkeypatch: pytest.MonkeyPatch) -> None:
    seg = segments.split_segments(_timeline())[0]
    before = segments.slice_hash(seg, "preview", "", {})
    assert segments.slice_hash(seg, "preview", "", {}) == before  # deterministic
    monkeypatch.setattr(segments, "RENDER_VERSION", "test-bump")
    assert segments.slice_hash(seg, "preview", "", {}) != before


def test_showcase_motion_keeps_its_phase_across_clip_boundaries() -> None:
    from app.timeline.schema import Overlay, VideoClip

    tl = _timeline().model_copy(
        update={
            "video_clips": [
                VideoClip(id="a", asset="a1", src_in=0, src_out=1.5),
                VideoClip(id="b", asset="a1", src_in=1.5, src_out=3),
            ],
            "overlays": [
                Overlay(
                    id="card",
                    type="image",
                    asset="showcase:test",
                    anchor_word="w1",
                    offset_ms=0,
                    duration_ms=2600,
                    layout="showcase",
                    license="user-content",
                )
            ],
        }
    )
    first, second = segments.split_segments(tl)
    assert first.overlay_motion["card"] == (0.0, 2.6)
    assert second.overlay_motion["card"] == (1.5, 2.6)
    altered = second.model_copy(update={"overlay_motion": {"card": (1.5, 3.0)}})
    assert segments.slice_hash(second, "preview", "", {}) != segments.slice_hash(
        altered, "preview", "", {}
    )


def test_captions_are_hidden_under_memes() -> None:
    from app.timeline.schema import Overlay

    meme = Overlay(
        id="m1",
        type="meme",
        asset="memes:x:0123456789abcdef",
        anchor_word="w2",
        offset_ms=0,
        duration_ms=800,
        layout="blur_bg_contain",
        license="unknown",
        commercial_use=False,
    )
    tl = _timeline().model_copy(update={"overlays": [meme]})
    cues = [c.id for seg in segments.split_segments(tl) for c in seg.cues]
    # w2 ends at 0.9 s; the meme covers 0.9-1.7 s, hiding w3 (1.0-1.4) and w4 (1.5-1.9)
    assert cues == ["w1", "w2", "w5", "w6"]


def test_proof_boundaries_protect_caption_placement_and_cache_camera() -> None:
    from app.timeline.schema import Overlay

    shot = Overlay(
        id="proof",
        type="image",
        asset="page",
        anchor_word="w2",
        offset_ms=0,
        duration_ms=1200,
        layout="proof",
        license="user-content",
    )
    tl = _timeline().model_copy(update={"overlays": [shot]})
    parts = segments.split_segments(tl)
    assert [(s.start, s.end) for s in parts] == [(0, 0.5), (0.5, 1.7), (1.7, 3)]
    assert not parts[0].overlays and not parts[-1].overlays
    middle = parts[1]
    moved = middle.model_copy(
        update={"overlays": [(shot.model_copy(update={"motion": "pan_up"}), 0, 1.2)]}
    )
    assert segments.slice_hash(middle, "preview", "", {}) != segments.slice_hash(
        moved, "preview", "", {}
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_page_shot_interrupts_chained_split_independent_of_insertion_order(reverse: bool) -> None:
    from app.timeline.schema import Overlay

    shots = [
        Overlay(
            id="intro",
            type="image",
            asset="intro",
            anchor_word="w1",
            offset_ms=0,
            duration_ms=500,
            layout="split_top",
            license="user-content",
        ),
        Overlay(
            id="page",
            type="image",
            asset="page",
            anchor_word="w2",
            offset_ms=0,
            duration_ms=1500,
            layout="proof",
            license="user-content",
        ),
        Overlay(
            id="outro",
            type="image",
            asset="outro",
            anchor_word="w5",
            offset_ms=0,
            duration_ms=1000,
            layout="split_top",
            license="user-content",
        ),
    ]
    tl = _timeline().model_copy(
        update={"reframe": "split_bottom", "overlays": shots[::-1] if reverse else shots}
    )
    assert segments._chained_split_overlay_windows(tl, [(0, 3)]) == {
        "intro": (0, 0.5),
        "outro": (2, 3),
    }
    page = next(s for s in segments.split_segments(tl) if s.start == 0.5)
    assert [o.id for o, _, _ in page.overlays] == ["page"]
