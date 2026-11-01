"""Register the real showcase in the local Studio and enqueue an actual Arq render.

Local development database only. Never changes a cloud project or publishes media.
"""

import asyncio
import hashlib
import json
from pathlib import Path

from app import db as db_ops
from app.api.deps import get_or_create_user_id
from app.models import Asset, Project, Render, TimelineVersion
from app.models import Timeline as TimelineRow
from app.services.renders import request_render
from app.settings import get_settings
from app.storage import get_storage
from app.storyboard.models import QualityAssessment
from app.storyboard.store import put_artifact
from app.timeline.schema import Timeline
from app.timeline.versions import save_version

ROOT = Path("work/livestream-impact")


async def main() -> None:
    settings = get_settings()
    if "localhost:5433" not in settings.TIGER_DATABASE_URL:
        raise ValueError("demo registration only targets the local development database")
    db = db_ops.get_db(settings)
    await db_ops.migrate(db)
    store = get_storage(settings)
    tl = Timeline.model_validate_json(await asyncio.to_thread((ROOT / "timeline.json").read_text))
    report = json.loads(await asyncio.to_thread((ROOT / "final-report.json").read_text))
    user = await get_or_create_user_id(db, "clipz-demo")
    project = await db_ops.get(db, Project, tl.project_id)
    if project is None:
        project = await db_ops.insert(
            db,
            Project(
                _id=tl.project_id,
                user_id=user,
                name="Livestream → visual story · Phase 7c",
                language="en",
            ),
        )
        row = await db_ops.insert(db, TimelineRow(project_id=project.id, current_version=0))
        first = Timeline.model_validate_json(
            await asyncio.to_thread((ROOT / "timeline-v1.json").read_text)
        )
        await save_version(db, row.id, first, parent=None, expected_parent=0)
        await save_version(db, row.id, tl, parent=1, expected_parent=1)
    else:
        if project.user_id != user:
            raise ValueError("demo project ID belongs to another workspace")
        row = await db_ops.find_one(db, TimelineRow, {"project_id": project.id})
    master = await asyncio.to_thread((ROOT / "master.mp4").read_bytes)
    key = f"projects/{project.id}/master.mp4"
    await asyncio.to_thread(store.put_bytes, key, master, "video/mp4")
    source = await db_ops.find_one(db, Asset, {"project_id": project.id, "kind": "master"})
    if source is None:
        await db_ops.insert(
            db,
            Asset(
                project_id=project.id,
                kind="master",
                storage_key=key,
                sha256=hashlib.sha256(master).hexdigest(),
                source=report["source"],
                license="youtube-standard-test-excerpt",
                commercial_use=False,
                width=1920,
                height=1080,
                duration_ms=60000,
            ),
        )
    if tl.storyboard:
        await asyncio.to_thread(put_artifact, store, tl.storyboard)
    approved = await asyncio.to_thread(Path(report["artifact"]).read_bytes)
    if hashlib.sha256(approved).hexdigest() != report["sha256"]:
        raise ValueError("approved final bytes no longer match the actual reviewed artifact")
    approved_key = f"renders/{project.id}/showcase-reviewed.mp4"
    await asyncio.to_thread(store.put_bytes, approved_key, approved, "video/mp4")
    version_row = await db_ops.find_one(
        db, TimelineVersion, {"timeline_id": row.id, "version": tl.version}
    )
    assessment = QualityAssessment(
        timeline_hash=report["render"]["timeline_hash"],
        render_hash=report["sha256"],
        version=tl.version,
        technical_pass=report["technical"]["passed"],
        creative_status="reviewed" if report["review"]["verdict"] == "pass" else "needs_edits",
        checks=[
            "full_decode",
            "dimensions",
            "fps",
            "av_duration_agreement",
            "encoded_loudness",
            "true_peak",
            "all_frame_scene_visibility",
        ],
        reviewed_frames=report["review"]["reviewed_frames"],
        limitations=["Sparse actual-frame review; human full-playback benchmark remains separate."],
    )
    await asyncio.to_thread(put_artifact, store, assessment)
    row_render = await db_ops.find_one(
        db, Render, {"project_id": project.id, "output_key": approved_key}
    )
    if row_render is None:
        row_render = await db_ops.insert(
            db,
            Render(
                project_id=project.id,
                timeline_version_id=version_row.id,
                profile="final",
                status="done",
                timeline_hash=report["render"]["timeline_hash"],
                output_key=approved_key,
                output_url=store.public_url(approved_key),
                attributions=(ROOT / "credits.txt").read_text().splitlines(),
                quality={
                    **assessment.model_dump(mode="json"),
                    "scene_artifacts": report["render"]["scenes"],
                },
            ),
        )
    render, job = await request_render(db, project.id, row.id, tl.version, "preview")
    result = {
        "project_id": str(project.id),
        "approved_render_id": str(row_render.id),
        "worker_render_id": str(render.id),
        "worker_job_id": str(job.id),
        "workspace_key": "clipz-demo",
        "studio": "http://127.0.0.1:8000/app",
    }
    await asyncio.to_thread((ROOT / "studio-demo.json").write_text, json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
