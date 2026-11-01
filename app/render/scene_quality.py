"""Actual-output visibility checks against rendered scene pixels, across every frame."""

import os
from pathlib import Path

import cv2
import numpy as np

from app.scenes.compiler import CompiledScene

SETTLE_FRAMES = 3  # the encoder needs a few frames to resolve a hard cut into a new scene


def exceeds_limits(mean_error: float, changed_fraction: float, frames_into_scene: int) -> bool:
    """True when a composite frame no longer shows its scene.

    Wrong or missing content measures ~60 mean error and ~97% changed pixels. Compression noise
    on the first frames after a hard cut (worst on high-contrast entrances such as a glitch or
    flash veil) is far smaller but can pass the steady-state limits, so those frames get looser
    ones. Mid-scene frames keep the strict limits.
    """
    settling = frames_into_scene < SETTLE_FRAMES
    return mean_error > (10 if settling else 6) or changed_fraction > (0.06 if settling else 0.02)


def _dump(
    name: str, frame: int, actual: np.ndarray, expected: np.ndarray, delta: np.ndarray
) -> None:
    """Debug aid: save composite / artifact / diff for a failing frame (VISIBILITY_DEBUG_DIR)."""
    out = Path(os.environ["VISIBILITY_DEBUG_DIR"])
    out.mkdir(parents=True, exist_ok=True)
    h = expected.shape[0]
    diff = np.clip(delta.max(axis=2) * 4, 0, 255).astype(np.uint8)
    cv2.imwrite(str(out / f"{name}-{frame}-actual.png"), actual[:h])
    cv2.imwrite(str(out / f"{name}-{frame}-expected.png"), expected)
    cv2.imwrite(str(out / f"{name}-{frame}-diff.png"), diff)


def inspect_scene_composition(
    path: Path,
    scenes: list[CompiledScene],
    scene_files: dict[str, str],
) -> dict[str, object]:
    """Check ownership in encoded pixels, excluding the protected caption region.

    Scene artifacts already passed local layout/readiness checks. Compare their content
    with the final composite to catch black frames, old split panels and wrong phases.
    Compression permits a small pixel error, not missing or replaced content.
    """
    capture = cv2.VideoCapture(str(path))
    readers = {s.spec.id: cv2.VideoCapture(scene_files[s.spec.id]) for s in scenes}
    positions = {s.spec.id: 0 for s in scenes}
    findings = []
    frame = 0
    checked = 0
    try:
        while True:
            ok, actual = capture.read()
            if not ok:
                break
            active = [s for s in scenes if s.start_frame <= frame < s.end_frame]
            full = [s for s in active if s.placement.slot == "full"]
            if full:
                active = full
            for scene in active:
                name = scene.spec.id
                reader = readers[name]
                at = frame - scene.start_frame
                if positions[name] != at:
                    reader.set(cv2.CAP_PROP_POS_FRAMES, at)
                valid, expected = reader.read()
                positions[name] = at + 1
                if not valid:
                    findings.append(
                        {"scene_id": name, "frame": frame, "error": "required scene frame missing"}
                    )
                    continue
                width, height = actual.shape[1], actual.shape[0]
                target_h = height if scene.placement.slot == "full" else height // 2
                expected = cv2.resize(expected, (width, target_h))
                # Captions are protected after visual layers. Compare the full scene's
                # content area; panel scenes are entirely above the caption/speaker.
                region_h = round(height * 0.73) if scene.placement.slot == "full" else target_h
                delta = np.abs(
                    actual[:region_h].astype(np.int16) - expected[:region_h].astype(np.int16)
                )
                error = float(delta.mean())
                bad = float((delta.max(axis=2) > 35).mean())
                checked += 1
                if exceeds_limits(error, bad, at):
                    if os.environ.get("VISIBILITY_DEBUG_DIR") and len(findings) < 6:
                        _dump(name, frame, actual, expected, delta)
                    if len(findings) < 100:
                        findings.append(
                            {
                                "scene_id": name,
                                "frame": frame,
                                "error": "scene visibility/phase differs from artifact",
                                "mean_pixel_error": round(error, 3),
                                "changed_fraction": round(bad, 4),
                            }
                        )
            frame += 1
    finally:
        capture.release()
        for reader in readers.values():
            reader.release()
    if frame == 0:
        findings.append({"scene_id": "export", "frame": 0, "error": "no decoded frames"})
    return {
        "passed": not findings,
        "frames_decoded": frame,
        "scene_frames_checked": checked,
        "findings": findings,
    }
