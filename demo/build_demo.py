"""Build the ClipZ demo video: narrated explainer cards + the real devday impact preview render.

    uv run python demo/build_demo.py     # needs ELEVENLABS_API_KEY in .env, ffmpeg on PATH
Outputs demo/clipz-demo.mp4 (1920x1080, ~2 min). Intermediates go to demo/build/.
"""

import json
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "demo" / "build"
OUT = ROOT / "demo" / "clipz-demo.mp4"
PREVIEW = (
    ROOT / "editedVideo" / "d5ff19dc-04e7-4b15-abfa-f7cd87739cf6" / "devday-impact-preview.mp4"
)
FONT = "/usr/share/fonts/noto/NotoSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/noto/NotoSans-Regular.ttf"
VOICE = "JBFqnCBsd6RMkjVDRZzb"

# (slide id, on-screen title, subtitle, narration)
SCENES = [
    (
        "title",
        "ClipZ",
        "Edit a reel by chat. Built for hackCBS 9.0, Meko track.",
        "This is ClipZ. You edit short vertical reels by talking to an AI director, and it remembers your style.",
    ),
    (
        "problem",
        "Reel editing is slow",
        "Captions, cuts, zooms, music, timing. Hours for one 60-second reel.",
        "Making a short reel takes hours. Captions, cuts, zooms and music all need to line up with the words.",
    ),
    (
        "how",
        "Type what you want",
        "The Director plans a shot list, then edits with typed tools. It never writes FFmpeg.",
        "You upload a video up to 90 seconds and tell the Director what you want. It plans the edit and calls typed tools, so every change is a timeline version you can undo.",
    ),
    (
        "platform",
        "The Studio",
        "Reels, renders, script, original, and the Memory tab. Live from the app.",
        "This is the Studio. Pick a reel and check its renders, script and original. The Memory tab shows what the Director knows about each creator, and you can correct it.",
    ),
    (
        "meko",
        "Memory on Meko",
        "Each creator's style is remembered. Approved lessons reach the whole agency.",
        "Meko gives the Director memory. It recalls each creator's style before it edits, and a person decides which lessons become shared rules.",
    ),
    (
        "demo",
        "Real output",
        "The devday impact preview, rendered from one chat message.",
        "Here is a real preview from the Studio. Captions, cuts and music were placed by the Director, from one message.",
    ),
    (
        "trust",
        "Honest by design",
        "You see what was recalled, and can correct or forget any memory.",
        "Every recalled memory is shown in the chat and the Memory tab, with its source. You can correct or forget any of them, and memory can never change the renderer.",
    ),
    (
        "outro",
        "ClipZ",
        "Code, demo and setup in the repository README.",
        "ClipZ. Thanks for watching.",
    ),
]
W, H, FPS = 1920, 1080, 30


def run(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True)


def narrate(slide: str, text: str) -> Path:
    """ElevenLabs narration for one slide; cached per slide."""
    path = BUILD / f"{slide}.mp3"
    if path.exists():
        return path
    key = next(
        line.split("=", 1)[1].strip()
        for line in (ROOT / ".env").read_text().splitlines()
        if line.startswith("ELEVENLABS_API_KEY=")
    )
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}",
        json.dumps({"text": text, "model_id": "eleven_multilingual_v2"}).encode(),
        {"xi-api-key": key, "Content-Type": "application/json"},
    )
    path.write_bytes(urllib.request.urlopen(req, timeout=120).read())
    return path


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return float(out.strip())


def card(slide: str, title: str, sub: str, audio: Path, seconds: float) -> Path:
    """A 1080p title card with narration; text goes through files so no escaping is needed."""
    tf, sf = BUILD / f"{slide}.title.txt", BUILD / f"{slide}.sub.txt"
    tf.write_text(title)
    sf.write_text(sub)
    out = BUILD / f"{slide}.mp4"
    vf = (
        f"drawtext=fontfile={FONT}:textfile={tf}:fontcolor=#FFD400:fontsize=118:"
        "x=(w-text_w)/2:y=(h-text_h)/2-70,"
        f"drawtext=fontfile={FONT_REG}:textfile={sf}:fontcolor=#E8E8EE:fontsize=50:"
        "x=(w-text_w)/2:y=(h-text_h)/2+80"
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=#0B0C16:s={W}x{H}:r={FPS}:d={seconds}",
            "-i",
            str(audio),
            "-vf",
            vf,
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-t",
            f"{seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            str(out),
        ]
    )
    return out


def studio(audio: Path) -> Path:
    """Live Studio screen recording with narration; the last frame holds if narration is longer."""
    seconds = max(duration(BUILD / "studio.webm"), duration(audio) + 0.8)
    out = BUILD / "platform.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(BUILD / "studio.webm"),
            "-i",
            str(audio),
            "-filter_complex",
            f"[0:v]fps={FPS},scale={W}:{H},tpad=stop_mode=clone:stop_duration={seconds}[v];"
            "[1:a]apad,aformat=sample_rates=48000:channel_layouts=stereo[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            f"{seconds:.2f}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(out),
        ]
    )
    return out


def demo(audio_seconds: float) -> Path:
    """The real preview render, letterboxed to 1080p; its own audio is kept."""
    out = BUILD / "demo.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(PREVIEW),
            "-vf",
            f"scale=-2:{H},pad={W}:{H}:(ow-iw)/2:0:color=#0B0C16,fps={FPS}",
            "-map",
            "0:v",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(out),
        ]
    )
    return out


def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    segments: list[Path] = []
    for slide, title, sub, text in SCENES:
        audio = narrate(slide, text)
        if slide == "platform":
            segments.append(studio(audio))
            continue
        if slide == "demo":
            segments.append(demo(duration(audio)))
            continue
        seconds = round(duration(audio) + 0.8, 2)
        segments.append(card(slide, title, sub, audio, seconds))
    listing = BUILD / "list.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in segments))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(OUT)])
    total = duration(OUT)
    print(f"wrote {OUT} ({total:.1f} s)")


if __name__ == "__main__":
    main()
