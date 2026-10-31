"""Local HyperFrames frame-adapter host. Strict readiness, no remote resources."""

import base64
import hashlib
import io
import json
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageStat

from app.media.ffmpeg import ffmpeg_path, run_capture
from app.media.probe import ffprobe_path
from app.render.edl_to_ffmpeg import RenderProfile
from app.scenes.compiler import CompiledScene
from app.scenes.models import SceneArtifact
from app.storage import Storage
from app.storyboard.store import content_hash

VISUALS = Path(__file__).resolve().parents[2] / "visuals"


def equivalent_pixels(a: bytes, b: bytes) -> bool:
    """Bound sparse Chromium SVG antialias noise; the host also requires identical DOM state."""
    with Image.open(io.BytesIO(a)) as first, Image.open(io.BytesIO(b)) as second:
        if first.size != second.size:
            return False
        delta = ImageChops.difference(first.convert("RGB"), second.convert("RGB"))
        pixels = np.asarray(delta)
        return bool(np.sqrt(np.square(pixels.astype(np.float64)).mean()) <= 0.1)


def scene_html(compiled: CompiledScene, width: int, height: int) -> str:
    """Reviewed local code + embedded pinned font bytes. No source-supplied code."""
    runtime = (VISUALS / "dist/runtime.js").read_text()
    fonts = json.loads((VISUALS / "dist/fonts.json").read_text())
    css = (VISUALS / "src/style.css").read_text()
    faces = "".join(
        f"@font-face{{font-family:{family};font-weight:{weight};src:url(data:font/woff2;base64,{fonts[key]})}}"
        for family, weight, key in (
            ("ClipZInter", 400, "inter"),
            ("ClipZInter", 700, "bold"),
            ("ClipZHindi", 400, "hindi"),
            ("ClipZDisplay", 400, "display"),
            ("ClipZMono", 400, "mono"),
            ("ClipZMono", 700, "monobold"),
        )
    )
    # Runtime never appears inside data. Compiled JSON is passed through Playwright's argument.
    logical_height = height * 1080 / width
    sizing = (
        f"#scene{{height:{logical_height}px;transform:scale({width / 1080});transform-origin:0 0}}"
    )
    return (
        f"<!doctype html><meta charset='utf-8'><style>{faces}{css}{sizing}</style>"
        f"<div id='scene'></div><script>{runtime}</script>"
    )


def _verify_clip(path: Path, frames: int, width: int, height: int) -> None:
    facts = json.loads(
        run_capture(
            [
                ffprobe_path(),
                "-v",
                "error",
                "-count_frames",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ]
        )
    )
    video = next(s for s in facts["streams"] if s["codec_type"] == "video")
    if (int(video["nb_read_frames"]), video["width"], video["height"]) != (frames, width, height):
        raise ValueError("scene encode has wrong dimensions or frame count")
    if any(s["codec_type"] == "audio" for s in facts["streams"]):
        raise ValueError("scene artifacts must be silent; FFmpeg owns the single audio mix")


def render_scene(
    compiled: CompiledScene,
    profile: RenderProfile,
    store: Storage,
    evidence_files: dict[str, str] | None = None,
) -> tuple[str, SceneArtifact]:
    """Render or reuse a verified silent scene; capture frames only after deterministic seeks."""
    from playwright.sync_api import sync_playwright

    width = profile.width
    height = profile.height if compiled.placement.slot == "full" else profile.height // 2
    started = time.monotonic()
    evidence_files = evidence_files or {}
    asset_bytes = {key: Path(path).read_bytes() for key, path in evidence_files.items()}
    assets = {}
    for key, data in asset_bytes.items():
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > 4_000_000:
                raise ValueError("scene evidence image exceeds four megapixels")
            if im.format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError(
                    "scene evidence must be a frozen PNG/JPEG/WebP, never active SVG/HTML"
                )
            assets[key] = f"data:image/{im.format.lower()};base64,{base64.b64encode(data).decode()}"
    runtime_hash = hashlib.sha256(
        (VISUALS / "dist/runtime.js").read_bytes()
        + (VISUALS / "dist/fonts.json").read_bytes()
        + (VISUALS / "src/style.css").read_bytes()
        + (VISUALS / "package-lock.json").read_bytes()
    ).hexdigest()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, args=["--disable-gpu", "--font-render-hinting=none"]
        )
        try:
            runtime = f"hyperframes-0.8.223/chromium-{browser.version}/{runtime_hash}"
            digest = content_hash(
                {
                    "scene": compiled.model_dump(mode="json"),
                    "width": width,
                    "height": height,
                    "runtime": runtime,
                    "assets": {k: hashlib.sha256(v).hexdigest() for k, v in asset_bytes.items()},
                }
            )
            key = f"scenes/{digest}.mp4"
            manifest_key = f"scenes/{digest}.json"
            try:
                manifest = SceneArtifact.model_validate_json(store.get_bytes(manifest_key))
                data = store.get_bytes(key)
                if hashlib.sha256(data).hexdigest() != manifest.output_hash:
                    raise ValueError("cached scene checksum mismatch")
                return str(store.path_for(key)), manifest.model_copy(
                    update={"cache_hit": True, "scene_id": compiled.spec.id}
                )
            except KeyError:
                pass
            page = browser.new_page(
                viewport={"width": width, "height": height}, device_scale_factor=1
            )
            page.route("**/*", lambda route: route.abort())
            exceptions: list[str] = []
            page.on("pageerror", lambda exc: exceptions.append(str(exc)))
            page.set_default_timeout(15000)
            page.set_content(scene_html(compiled, width, height), wait_until="load")
            ready = page.evaluate(
                """async ([doc,assets]) => {
                  let timer;
                  try { return await Promise.race([
                    window.clipz.init(doc,assets),
                    new Promise((_,reject)=>{
                      timer=setTimeout(()=>reject(new Error('Scene readiness timed out')),15000)
                    })
                  ]); } finally { clearTimeout(timer); }
                }""",
                [compiled.model_dump(mode="json"), assets],
            )
            if not ready.get("ready") or ready.get("frameCount") != compiled.frame_count:
                raise ValueError(
                    f"scene {compiled.spec.id}: readiness {ready}; "
                    f"expected {compiled.frame_count} frames"
                )
            # Random order seeks must match, including backwards state updates.
            probes = sorted({0, compiled.frame_count // 2, compiled.frame_count - 1})
            captures: dict[int, bytes] = {}
            states: dict[int, str] = {}
            for frame in [*probes, *reversed(probes)]:
                page.evaluate("async f => await window.clipz.seek(f)", frame)
                data = page.screenshot(type="png", animations="allow")
                state = page.evaluate(
                    "JSON.stringify([...document.querySelectorAll('[data-element]')].map(n=>[n.dataset.element,n.getAttribute('style'),n.textContent]))"
                )
                if frame in captures and (
                    states[frame] != state or not equivalent_pixels(captures[frame], data)
                ):
                    raise ValueError(
                        f"scene {compiled.spec.id}: nondeterministic seek at frame {frame}"
                    )
                captures[frame] = data
                states[frame] = state
                with Image.open(io.BytesIO(data)) as image:
                    if max(ImageStat.Stat(image.convert("RGB")).stddev) < 2:
                        raise ValueError("blank required scene")
            with tempfile.TemporaryDirectory(prefix="clipz-scene-") as tmp:
                output = Path(tmp) / "scene.mp4"
                # stderr goes to a file so the encoder cannot deadlock a full pipe.
                with tempfile.TemporaryFile() as errors:
                    proc = subprocess.Popen(  # noqa: S603 - reviewed executable and typed argv
                        [  # noqa: S603 - fixed executable, typed argv, no shell
                            ffmpeg_path(),
                            "-v",
                            "error",
                            "-y",
                            "-f",
                            "image2pipe",
                            "-framerate",
                            "30",
                            "-i",
                            "pipe:0",
                            "-an",
                            "-c:v",
                            "libx264",
                            "-preset",
                            profile.preset,
                            "-crf",
                            str(profile.crf),
                            "-pix_fmt",
                            "yuv420p",
                            "-threads",
                            "1",
                            str(output),
                        ],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=errors,
                    )
                    try:
                        assert proc.stdin is not None
                        for frame in range(compiled.frame_count):
                            if time.monotonic() - started > 600:
                                raise TimeoutError("scene render exceeded 600 seconds")
                            page.evaluate("async f => await window.clipz.seek(f)", frame)
                            proc.stdin.write(page.screenshot(type="png", animations="allow"))
                            if exceptions:
                                raise ValueError("scene runtime error: " + "; ".join(exceptions))
                        proc.stdin.close()
                        if proc.wait(timeout=60):
                            errors.seek(0)
                            raise ValueError(f"scene encode failed: {errors.read()[-1000:]!r}")
                    finally:
                        if proc.poll() is None:
                            proc.kill()
                            proc.wait()
                _verify_clip(output, compiled.frame_count, width, height)
                data = output.read_bytes()
            artifact = SceneArtifact(
                key=key,
                scene_id=compiled.spec.id,
                spec_hash=compiled.spec_hash,
                output_hash=hashlib.sha256(data).hexdigest(),
                width=width,
                height=height,
                frame_count=compiled.frame_count,
                runtime=runtime,
                render_ms=round((time.monotonic() - started) * 1000),
            )
            store.put_bytes(key, data, "video/mp4")
            store.put_bytes(manifest_key, artifact.model_dump_json().encode(), "application/json")
            return str(store.path_for(key)), artifact
        finally:
            browser.close()
