"""Export QA must inspect encoded output, and reject missing/silent/peaking audio."""

import json
from pathlib import Path

import pytest

from app.render.quality import inspect_export


@pytest.mark.parametrize(
    "lufs,peak,passed",
    [(-14.2, -1.8, True), (-14.2, -0.3, False), (-22, -3, False), ("-inf", "-inf", False)],
)
def test_export_quality_uses_encoded_audio_measurement(
    lufs: float | str, peak: float | str, passed: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.render import quality

    facts = {
        "format": {"duration": "60"},
        "streams": [
            {
                "codec_type": "video",
                "width": 1080,
                "height": 1920,
                "pix_fmt": "yuv420p",
                "avg_frame_rate": "30/1",
                "duration": "60",
            },
            {"codec_type": "audio", "duration": "60"},
        ],
    }
    monkeypatch.setattr(quality, "run_capture", lambda _: json.dumps(facts).encode())
    monkeypatch.setattr(
        quality,
        "run_get_stderr",
        lambda _: json.dumps({"input_i": str(lufs), "input_tp": str(peak)}),
    )
    report = inspect_export(Path("encoded.mp4"), 60, 1080, 1920)
    assert report["passed"] is passed
    json.dumps(report, allow_nan=False)


def test_contain_filter_preserves_screen_content() -> None:
    from app.render.edl_to_ffmpeg import PREVIEW, build_video_filter
    from app.timeline.schema import CaptionConfig
    from tests.unit.timeline.test_ops import _timeline

    tl = _timeline().model_copy(
        update={"reframe": "contain", "captions": CaptionConfig(mode="off")}
    )
    script, _ = build_video_filter(tl, PREVIEW)
    assert "force_original_aspect_ratio=decrease" in script and "pad=540:960" in script
    assert "crop=" not in script


def test_proof_frame_preserves_subtitle_band_and_uses_global_motion_phase() -> None:
    from app.render.graph import ProofFrame

    frame = ProofFrame("[0:v]", 1080, 1920, 5, 2, "pull_out", "slide_up").render("[out]")
    assert "t+2.000" in frame and "/5.000" in frame
    assert "color=c=black:s=1080x1920" in frame and "shortest=1" in frame
    assert "force_original_aspect_ratio=decrease" in frame


def test_fractional_segment_frame_counts_sum_to_global_target() -> None:
    from app.render.graph import FrameCount

    points = [0, 0.017, 0.373, 1.019, 2.614, 3.151, 5.817, 8.01]
    counts = [round(b * 30) - round(a * 30) for a, b in zip(points[:-1], points[1:], strict=True)]
    assert sum(counts) == round(points[-1] * 30)
    assert "trim=end_frame=" in FrameCount("[v]", counts[-1]).render("[out]")
