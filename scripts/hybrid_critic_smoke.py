"""Live smoke: only the authored synthetic demo, with a deliberately visible defect."""

import asyncio
import json
from pathlib import Path

from app.agent.critic import evaluate_preview
from app.media.ffmpeg import ffmpeg_path, run_ffmpeg
from app.providers.registry import provider_registry
from app.settings import get_settings
from app.timeline.schema import Timeline


async def main() -> None:
    root = Path("work/hybrid-demo")
    timeline = Timeline.model_validate_json(
        await asyncio.to_thread((root / "project.json").read_text)
    )
    source = Path("editedVideo/hybrid-demo-final.mp4")
    if not await asyncio.to_thread(source.exists):
        source = Path("editedVideo/hybrid-demo-preview.mp4")
    seeded = root / "seeded-defect.mp4"
    await asyncio.to_thread(
        run_ffmpeg,
        [
            ffmpeg_path(),
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-vf",
            "drawbox=x=0:y=0:w=iw:h=ih*0.65:color=red:t=fill",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "copy",
            str(seeded),
        ],
    )
    report = await evaluate_preview(
        provider_registry(get_settings()).llm,
        timeline,
        seeded,
        user_prompt=(
            "Review actual encoded frames. The intended storyboard contains readable "
            "diagrams, source details and changing UI states. "
            "Report obstruction or missing content."
        ),
    )
    await asyncio.to_thread(
        (root / "seeded-defect-review.json").write_text, report.model_dump_json(indent=2)
    )
    if report.evidence != "rendered_frames" or report.verdict != "needs_edits" or not report.issues:
        raise RuntimeError(
            "live critic did not identify the seeded visible defect; "
            "creative pass rollout stays disabled"
        )
    print(
        json.dumps(
            {
                "verdict": report.verdict,
                "reviewed_images": len(report.reviewed_frames),
                "issues": report.issues,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
