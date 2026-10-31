"""Creator storyboard inspection and optimistic scene revisions."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.api.deps import DbDep, UserDep, owned_project
from app.api.timelines import _require_timeline
from app.scenes.compiler import compile_scenes
from app.scenes.models import Family
from app.scenes.renderer import scene_html
from app.settings import get_settings
from app.storage import get_storage
from app.storyboard.planner import (
    attach_storyboard,
    draft_storyboard,
    materialize_draft,
    update_scene,
)
from app.storyboard.store import put_artifact
from app.timeline.versions import get_current, load_version, save_version
from app.tools.storyboard import PlanStoryboardIn, SceneIn

router = APIRouter()


async def _current(project_id: uuid.UUID, db: DbDep, user_id: UserDep):  # type: ignore[no-untyped-def]
    project = await owned_project(db, user_id, project_id)
    row = await _require_timeline(db, project)
    tl = await load_version(db, row.id, await get_current(db, row.id))
    return row, tl


@router.get("/projects/{project_id}/storyboard")
async def get_storyboard(project_id: uuid.UUID, db: DbDep, user_id: UserDep) -> dict[str, object]:
    """Persistent intent and editable scene sources at the current pointer."""
    _, tl = await _current(project_id, db, user_id)
    try:
        compiled = compile_scenes(tl)
        error = None
    except ValueError as exc:
        compiled = []
        error = str(exc)
    return {
        "version": tl.version,
        "storyboard": tl.storyboard.model_dump(mode="json") if tl.storyboard else None,
        "storyboard_hash": tl.storyboard_hash,
        "scenes": [s.model_dump(mode="json") for s in tl.scenes],
        "placements": [p.model_dump(mode="json") for p in tl.scene_placements],
        "schedule": [
            {"scene_id": c.spec.id, "start_frame": c.start_frame, "end_frame": c.end_frame}
            for c in compiled
        ],
        "needs_replan": error,
    }


@router.post("/projects/{project_id}/storyboard")
async def plan_storyboard(
    project_id: uuid.UUID, body: PlanStoryboardIn, db: DbDep, user_id: UserDep
) -> dict[str, object]:
    """Create a grounded draft or save an authored plan; never silently rewrite speech."""
    row, tl = await _current(project_id, db, user_id)
    try:
        board = body.storyboard or draft_storyboard(tl, body.brief)
        if any(
            not e.storage_key.startswith(f"renders/{project_id}/evidence/") for e in board.evidence
        ):
            raise ValueError("import evidence into this project before planning")
        from app.visuals.evidence import resolve_evidence

        await asyncio.to_thread(resolve_evidence, get_storage(get_settings()), board.evidence)
        updated = attach_storyboard(tl, board, expected_version=body.expected_version)
        if body.create_draft_scenes:
            updated = materialize_draft(updated)
        digest = await asyncio.to_thread(put_artifact, get_storage(get_settings()), board)
        version, _ = await save_version(
            db, row.id, updated, parent=tl.version, expected_parent=tl.version
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"version": version, "storyboard_hash": digest, "status": "storyboard_ready"}


@router.put("/projects/{project_id}/scenes/{scene_id}")
async def edit_scene(
    project_id: uuid.UUID, scene_id: str, body: SceneIn, db: DbDep, user_id: UserDep
) -> dict[str, object]:
    """Save only one scene; immutable versions provide undo/redo."""
    row, tl = await _current(project_id, db, user_id)
    if scene_id != body.spec.id:
        raise HTTPException(status_code=422, detail="scene path and spec differ")
    try:
        updated = update_scene(
            tl, body.spec, body.placement, expected_version=body.expected_version
        )
        version, _ = await save_version(
            db, row.id, updated, parent=tl.version, expected_parent=tl.version
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"version": version, "scene_id": scene_id, "status": "scene_updated"}


class SceneFocusBody(BaseModel):
    expected_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=96)
    asset_id: str | None = None


@router.patch("/projects/{project_id}/scenes/{scene_id}/focus")
async def change_focus(
    project_id: uuid.UUID, scene_id: str, body: SceneFocusBody, db: DbDep, user_id: UserDep
) -> dict[str, object]:
    """Small creator control: change headline or replace a proof asset with project evidence."""
    row, tl = await _current(project_id, db, user_id)
    spec = next((s for s in tl.scenes if s.id == scene_id), None)
    placement = next((p for p in tl.scene_placements if p.scene_id == scene_id), None)
    if spec is None or placement is None:
        raise HTTPException(status_code=404, detail="scene not found")
    data = spec.model_dump(mode="json")
    data["title"] = body.title
    if body.asset_id is not None:
        if spec.content.template != "proof_focus":
            raise HTTPException(
                status_code=422, detail="only proof scenes can replace a frozen image"
            )
        data["content"]["asset_id"] = body.asset_id
        data["evidence_ids"] = [body.asset_id]
    from app.scenes.models import SceneSpec

    return await edit_scene(
        project_id,
        scene_id,
        SceneIn(
            expected_version=body.expected_version,
            spec=SceneSpec.model_validate(data),
            placement=placement,
        ),
        db,
        user_id,
    )


@router.get("/projects/{project_id}/scenes/{scene_id}/preview", response_class=HTMLResponse)
async def preview_scene(
    project_id: uuid.UUID, scene_id: str, db: DbDep, user_id: UserDep
) -> HTMLResponse:
    """Same scene runtime as export. A protected iframe never executes source content."""
    _, tl = await _current(project_id, db, user_id)
    try:
        scene = next((s for s in compile_scenes(tl) if s.spec.id == scene_id), None)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if scene is None:
        raise HTTPException(status_code=404, detail="scene not found")
    import base64
    import json

    from app.visuals.evidence import resolve_evidence

    store = get_storage(get_settings())
    assets = {}
    wanted = scene.spec.asset_ids
    if wanted and tl.storyboard:
        files = await asyncio.to_thread(
            resolve_evidence, store, [e for e in tl.storyboard.evidence if e.id in wanted]
        )
        assets = {
            k: "data:image/png;base64,"
            + base64.b64encode(await asyncio.to_thread(Path(v).read_bytes)).decode()
            for k, v in files.items()
        }
    doc = base64.b64encode(json.dumps([scene.model_dump(mode="json"), assets]).encode()).decode()
    html = scene_html(scene, 540, 960 if scene.placement.slot == "full" else 480)
    # Base64 protects the trusted script context from text containing closing script tags.
    html += (
        "<script>(async()=>{const [doc,assets]=JSON.parse(new TextDecoder().decode("
        f"Uint8Array.from(atob('{doc}'),c=>c.charCodeAt(0))));"
        "await clipz.init(doc,assets);let f=0;"
        f"setInterval(()=>clipz.seek((f++)%{scene.frame_count}),1000/30)"
        "})().catch(e=>document.body.textContent='Preview unavailable: '+e.message)</script>"
    )
    return HTMLResponse(
        html,
        headers={
            "Content-Security-Policy": (
                "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                "img-src data:; font-src data:; connect-src 'none'"
            )
        },
    )


@router.post("/projects/{project_id}/explainer")
async def create_explainer(
    project_id: uuid.UUID, body: PlanStoryboardIn, db: DbDep, user_id: UserDep
) -> dict[str, object]:
    """Queue the durable visual mode; existing authored scenes are reused."""
    from app import db as db_ops
    from app.models import Job
    from app.workers.queue import enqueue_job

    _, tl = await _current(project_id, db, user_id)
    if tl.version != body.expected_version:
        raise HTTPException(status_code=409, detail="stale revision; refresh the storyboard")
    rid = uuid.uuid4()
    job = await db_ops.insert(
        db,
        Job(
            project_id=project_id,
            type="visual_explainer",
            idempotency_key=f"explainer:{rid}",
            payload={
                "render_id": str(rid),
                "expected_version": tl.version,
                "brief": body.brief.model_dump(mode="json"),
                "stage": "queued",
            },
        ),
    )
    await enqueue_job(get_settings().REDIS_URL, "hybrid_task", {"job_id": str(job.id)})
    return {"job_id": str(job.id), "render_id": str(rid), "status": "queued"}


@router.get("/projects/{project_id}/explainer/{job_id}")
async def explainer_status(
    project_id: uuid.UUID, job_id: uuid.UUID, db: DbDep, user_id: UserDep
) -> dict[str, object]:
    """Recoverable job checkpoints for creator progress and SSE."""
    from app import db as db_ops
    from app.models import Job

    await owned_project(db, user_id, project_id)
    job = await db_ops.get(db, Job, job_id)
    if job is None or job.project_id != project_id:
        raise HTTPException(status_code=404, detail="job not found")
    return {"status": job.status, "progress": job.progress, "error": job.error, **job.payload}


@router.get("/projects/{project_id}/explainer/{job_id}/events")
async def explainer_events(project_id: uuid.UUID, job_id: uuid.UUID, db: DbDep, user_id: UserDep):  # type: ignore[no-untyped-def]
    """Stream persisted stage changes; reconnecting reads the latest checkpoint."""
    import json

    from sse_starlette.sse import EventSourceResponse

    await owned_project(db, user_id, project_id)

    async def events() -> AsyncIterator[dict[str, str]]:
        previous = ""
        for _ in range(1800):
            data = await explainer_status(project_id, job_id, db, user_id)
            encoded = json.dumps(data, sort_keys=True)
            if encoded != previous:
                yield {"event": "explainer_progress", "data": encoded}
                previous = encoded
            if data["status"] in ("done", "failed"):
                return
            await asyncio.sleep(1)

    return EventSourceResponse(events())


class RepairBody(SceneIn):
    assessment_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.post("/projects/{project_id}/scenes/{scene_id}/repair")
async def repair_scene(
    project_id: uuid.UUID, scene_id: str, body: RepairBody, db: DbDep, user_id: UserDep
) -> dict[str, object]:
    """Apply one evidence-backed scene patch, then queue its verification preview."""
    from app import db as db_ops
    from app.models import Render
    from app.services.renders import request_render
    from app.storyboard.models import QualityAssessment
    from app.storyboard.repair import apply_review_repair
    from app.storyboard.store import get_artifact

    row, tl = await _current(project_id, db, user_id)
    if scene_id != body.spec.id:
        raise HTTPException(status_code=422, detail="repair scene ID differs")
    try:
        assessment = await asyncio.to_thread(
            get_artifact, get_storage(get_settings()), body.assessment_hash, QualityAssessment
        )
        # The review must belong to this project and exact Timeline version.
        renders = await db_ops.find(db, Render, {"project_id": project_id})
        if not any(r.quality.get("render_hash") == assessment.render_hash for r in renders):
            raise ValueError("review does not belong to this project")
        updated = apply_review_repair(
            tl,
            assessment,
            body.spec,
            body.placement,
            expected_version=body.expected_version,
            assessment_hash=body.assessment_hash,
        )
        version, _ = await save_version(
            db, row.id, updated, parent=tl.version, expected_parent=tl.version
        )
        render, job = await request_render(db, project_id, row.id, version, "preview")
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {
        "version": version,
        "render_id": str(render.id),
        "job_id": str(job.id),
        "status": "verification_queued",
    }


class ImportEvidenceBody(BaseModel):
    source_asset: str
    entity: str = Field(min_length=1, max_length=200)
    role: Family = "proof_focus"


@router.post("/projects/{project_id}/evidence")
async def import_evidence(
    project_id: uuid.UUID, body: ImportEvidenceBody, db: DbDep, user_id: UserDep
) -> dict[str, object]:
    """Freeze a project-owned image or licensed catalog asset, inheriting its provenance."""
    from app import db as db_ops
    from app.models import Asset
    from app.providers.local import AssetCatalog, resolve_asset_file
    from app.visuals.evidence import freeze_image

    await owned_project(db, user_id, project_id)
    settings = get_settings()
    store = get_storage(settings)
    try:
        aid = uuid.UUID(body.source_asset)
    except ValueError:
        aid = None
    if aid is not None:
        source = await db_ops.get(db, Asset, aid)
        if source is None or source.project_id != project_id:
            raise HTTPException(status_code=404, detail="source image not found")
        data = await asyncio.to_thread(store.get_bytes, source.storage_key)
        url = source.source
        license = source.license
        commercial = source.commercial_use
        attribution = source.attribution_text or ""
    else:
        cache = Path(settings.WORK_DIR) / "cache" / "memes"
        catalog = AssetCatalog(settings.ASSETS_DIR, cache)
        found = catalog.get(body.source_asset)
        item = found[1] if found is not None else None
        path = resolve_asset_file(settings.ASSETS_DIR, cache, body.source_asset)
        if item is None or path is None:
            raise HTTPException(status_code=404, detail="licensed image not found")
        data = await asyncio.to_thread(path.read_bytes)
        url = item.source_url or item.source
        license = item.license
        commercial = item.commercial_use
        attribution = item.attribution_text
    try:
        evidence = await asyncio.to_thread(
            freeze_image,
            store,
            data,
            asset_id="evidence_" + uuid.uuid4().hex[:16],
            source=url,
            entity=body.entity,
            role=body.role,
            license=license,
            commercial_use=commercial,
            attribution=attribution,
            project_id=project_id,
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return evidence.model_dump(mode="json")


@router.get("/projects/{project_id}/scenes/{scene_id}/thumbnail")
async def scene_thumbnail(project_id: uuid.UUID, scene_id: str, db: DbDep, user_id: UserDep):  # type: ignore[no-untyped-def]
    """Serve a thumbnail only from a current render belonging to this project."""
    from fastapi import Response

    from app import db as db_ops
    from app.agent.critic import extract_frame_bytes
    from app.models import Render

    _, tl = await _current(project_id, db, user_id)
    renders = await db_ops.find(db, Render, {"project_id": project_id}, sort=[("created_at", -1)])
    for render in renders:
        if render.quality.get("version") != tl.version:
            continue
        artifact = next(
            (a for a in render.quality.get("scene_artifacts", []) if a.get("scene_id") == scene_id),
            None,
        )
        if artifact is not None:
            path = get_storage(get_settings()).path_for(artifact["key"])
            data = await asyncio.to_thread(extract_frame_bytes, path, artifact["frame_count"] / 60)
            return Response(data, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="render a preview to create this scene thumbnail")


@router.delete("/projects/{project_id}/storyboard")
async def clear_storyboard(
    project_id: uuid.UUID, expected_version: int, db: DbDep, user_id: UserDep
) -> dict[str, object]:
    """Detach a visual plan for narration edits; undo restores its immutable version."""
    from app.storyboard.planner import check_version

    row, tl = await _current(project_id, db, user_id)
    try:
        check_version(tl, expected_version)
        updated = tl.model_copy(
            update={
                "storyboard": None,
                "storyboard_hash": None,
                "scenes": [],
                "scene_placements": [],
            }
        )
        version, _ = await save_version(
            db, row.id, updated, parent=tl.version, expected_parent=tl.version
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"version": version, "status": "visual_plan_detached"}
