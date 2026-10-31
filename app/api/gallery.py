"""Dashboard of every edited video: GET /renders (all projects) and a cached poster frame."""

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app import db as db_ops
from app.api.deps import DbDep, UserDep, owned_project
from app.media.ffmpeg import ffmpeg_path, run_capture
from app.models import Project, Render
from app.settings import get_settings
from app.storage import get_storage

router = APIRouter()
QUALITY_FIELDS = (
    "imported", "technical_pass", "creative_status", "duration_s", "width", "height", "size_bytes"
)  # fmt: skip


@router.get("/renders")
async def list_all_renders(
    db: DbDep,
    user_id: UserDep,
    include_previews: bool = Query(default=False),
    limit: int = Query(default=120, ge=1, le=500),
) -> dict[str, object]:
    """Finished edits across the caller's projects, newest first (urls via GET /media/...)."""
    projects = await db_ops.find(db, Project, {"user_id": user_id})
    names = {p.id: p.name for p in projects}
    rows: list[Render] = []
    for pid in names:
        rows += await db_ops.find(db, Render, {"project_id": pid, "status": "done"})
    rows = [r for r in rows if r.output_url and (include_previews or r.profile != "preview")]
    rows.sort(key=lambda r: r.created_at, reverse=True)
    return {
        "renders": [
            {
                "render_id": str(r.id),
                "project_id": str(r.project_id),
                "project_name": names[r.project_id],
                "profile": r.profile,
                "url": r.output_url,
                "poster_url": f"/renders/{r.id}/poster",
                "credits": r.attributions,
                "quality": {k: r.quality[k] for k in QUALITY_FIELDS if k in r.quality},
                "created_at": r.created_at.isoformat(),
            }
            for r in rows[:limit]
        ],
        "total": len(rows),
    }


def _poster_frame(video: str) -> bytes:
    return run_capture(
        [
            ffmpeg_path(), "-v", "error", "-ss", "1", "-i", video, "-frames:v", "1",
            "-vf", "scale=360:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "4", "-",
        ]
    )  # fmt: skip


@router.get("/renders/{render_id}/poster")
async def render_poster(render_id: uuid.UUID, db: DbDep, user_id: UserDep) -> Response:
    """A small JPEG of the edit (made once, then served from storage)."""
    render = await db_ops.find_one(db, Render, {"_id": render_id})
    if render is None or not render.output_key:
        raise HTTPException(status_code=404, detail="not found")
    await owned_project(db, user_id, render.project_id)
    store = get_storage(get_settings())
    key = f"renders/{render.project_id}/posters/{render.id}.jpg"
    try:
        return Response(store.get_bytes(key), media_type="image/jpeg")
    except KeyError:
        pass
    path = store.path_for(render.output_key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="video file is missing")
    data = await asyncio.to_thread(_poster_frame, str(path))
    store.put_bytes(key, data, "image/jpeg")
    return Response(data, media_type="image/jpeg")
