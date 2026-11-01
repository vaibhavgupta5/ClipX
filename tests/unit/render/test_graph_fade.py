"""FadeIO never emits negative FFmpeg times for slivers left by segment boundaries."""

import re

from app.render.graph import FadeIO


def _times(filtergraph: str) -> list[float]:
    return [float(v) for v in re.findall(r"(?:st|d)=(-?[0-9.]+)", filtergraph)]


def test_sliver_shorter_than_fades_scales_fades_to_fit() -> None:
    out = FadeIO("[v]", fade_in=0.1, fade_out=0.1, duration=0.07, start=0.0).render("[o]")
    assert all(t >= 0 for t in _times(out))
    assert "d=0.035" in out


def test_normal_overlay_keeps_requested_fades() -> None:
    out = FadeIO("[v]", fade_in=0.1, fade_out=0.15, duration=2.0, start=1.0).render("[o]")
    assert "fade=t=in:st=1" in out and "fade=t=out:st=2.85" in out
