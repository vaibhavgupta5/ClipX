"""Measure the exported file, independently of timeline intent."""

import json
import math
from fractions import Fraction
from pathlib import Path
from typing import Any

from app.media.ffmpeg import ffmpeg_path, run_capture, run_get_stderr
from app.media.probe import ffprobe_path
from app.render.audio import parse_loudnorm_json


def inspect_export(path: Path, expected_duration: float, width: int, height: int) -> dict[str, Any]:
    """Check dimensions, duration, A/V drift and measured loudness; decode all frames."""
    facts = json.loads(
        run_capture(
            [
                ffprobe_path(),
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ]
        )
    )
    video = next(s for s in facts["streams"] if s["codec_type"] == "video")
    audio = next((s for s in facts["streams"] if s["codec_type"] == "audio"), None)
    duration = float(facts["format"]["duration"])
    errors: list[str] = []
    if (video["width"], video["height"]) != (width, height):
        errors.append("wrong dimensions")
    if abs(duration - expected_duration) > 0.15:
        errors.append("duration differs from EDL by more than 150 ms")
    if video.get("pix_fmt") != "yuv420p":
        errors.append("pixel format is not broadly compatible yuv420p")
    fps = float(Fraction(video["avg_frame_rate"]))
    if abs(fps - 30) > 0.1:
        errors.append("export is not 30 fps")
    levels: dict[str, Any] = {}
    drift: float | None = None
    if audio is None:
        errors.append("missing audio")
    else:
        drift = abs(float(video.get("duration", duration)) - float(audio.get("duration", duration)))
        if drift > 0.15:
            errors.append("audio/video duration drift exceeds 150 ms")
        measured = parse_loudnorm_json(
            run_get_stderr(
                [
                    ffmpeg_path(),
                    "-hide_banner",
                    "-i",
                    str(path),
                    "-vn",
                    "-af",
                    "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
                    "-f",
                    "null",
                    "-",
                ]
            )
        )
        integrated, peak = float(measured["input_i"]), float(measured["input_tp"])
        levels = {
            "integrated_lufs": integrated if math.isfinite(integrated) else None,
            "true_peak_dbtp": peak if math.isfinite(peak) else None,
        }
        if not math.isfinite(integrated) or abs(integrated + 14) > 1:
            errors.append("loudness outside -14 +/- 1 LUFS")
        if not math.isfinite(peak) or peak > -1:
            errors.append("true peak exceeds -1 dBTP or audio is silent")
    # Full decode catches corrupt frames even when container metadata looks valid.
    run_get_stderr([ffmpeg_path(), "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"])
    return {
        "passed": not errors,
        "errors": errors,
        "duration_s": duration,
        "expected_duration_s": expected_duration,
        "width": video["width"],
        "height": video["height"],
        "fps": fps,
        "pixel_format": video.get("pix_fmt"),
        "av_drift_s": drift,
        "audio": levels,
        "decoded": True,
        "scope": "Technical checks only; reference fidelity and transcription need visual review.",
    }
