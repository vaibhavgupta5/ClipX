"""Durable visual-explainer job. Each expensive stage records recoverable output."""

import asyncio
import uuid
from typing import Any

from app import db as db_ops
from app.models import Job, Render, TimelineVersion
from app.models import Timeline as TimelineRow
from app.providers.registry import llm_enabled, make_llm
from app.settings import Settings
from app.storage import get_storage
from app.storyboard.models import CreativeBrief
from app.storyboard.planner import attach_storyboard, draft_storyboard, materialize_draft
from app.storyboard.store import put_artifact
from app.timeline.versions import get_current, load_version, save_version
from app.workers.render import _run_render
from app.workers.visual_review import checkpoint


async def hybrid_task(ctx: dict[str, Any], *, job_id: str) -> dict[str, object]:
    """Resume plan -> resolve -> compile -> preview -> review from immutable checkpoints."""
    settings: Settings = ctx["settings"]
    db = db_ops.get_db(settings)
    store = get_storage(settings)
    job = await db_ops.get(db, Job, uuid.UUID(job_id))
    if job is None or job.project_id is None:
        raise ValueError("visual explainer job not found")
    if job.status == "done":
        return {"status": "done", "render_id": job.payload.get("render_id", "")}
    try:
        await db_ops.update(db, Job, job.id, {"status": "running"})
        row = await db_ops.find_one(db, TimelineRow, {"project_id": job.project_id})
        if row is None:
            raise ValueError("analysis incomplete; wait for the word transcript before planning")
        if "planned_version" in job.payload:
            tl = await load_version(db, row.id, int(job.payload["planned_version"]))
        else:
            version = await get_current(db, row.id)
            if version != job.payload["expected_version"]:
                raise ValueError("stale explainer request; user edited while this job was queued")
            tl = await load_version(db, row.id, version)
            await checkpoint(db, job, "plan")
            if tl.storyboard is None:
                brief = CreativeBrief.model_validate(job.payload["brief"])
                board = draft_storyboard(tl, brief)
                tl = attach_storyboard(tl, board, expected_version=version)
            if not tl.scenes:
                if llm_enabled(settings):
                    from app.storyboard.creative import author_scenes
                    from app.workers.visual_review import ModelBudget

                    budget = ModelBudget.model_validate(job.payload.get("model_budget", {}))

                    async def reserve(body: dict[str, Any]) -> None:
                        nonlocal budget
                        budget = budget.reserve(body)
                        await checkpoint(db, job, "plan", model_budget=budget.model_dump())

                    planner = make_llm(settings, on_attempt=reserve)
                    assert planner is not None
                    try:
                        tl = await author_scenes(tl, planner)
                    except Exception as exc:
                        await checkpoint(db, job, "plan", planning_warning=str(exc)[:400])
                        tl = materialize_draft(tl)
                else:
                    tl = materialize_draft(tl)
            assert tl.storyboard is not None
            digest = await asyncio.to_thread(put_artifact, store, tl.storyboard)
            version, tl = await save_version(
                db, row.id, tl, parent=version, expected_parent=version
            )
            await checkpoint(
                db, job, "storyboard_ready", planned_version=version, storyboard_hash=digest
            )
        from app.scenes.compiler import compile_scenes
        from app.services.renders import timeline_hash

        await checkpoint(db, job, "resolve")
        from app.visuals.evidence import resolve_evidence

        if tl.storyboard:
            await asyncio.to_thread(resolve_evidence, store, tl.storyboard.evidence)
        await checkpoint(db, job, "compile")
        compiled = compile_scenes(tl)
        version_row = await db_ops.find_one(
            db, TimelineVersion, {"timeline_id": row.id, "version": tl.version}
        )
        assert version_row is not None
        render_id = uuid.UUID(job.payload["render_id"])
        render = await db_ops.get(db, Render, render_id)
        if render is None:
            render = await db_ops.insert(
                db,
                Render(
                    _id=render_id,
                    project_id=job.project_id,
                    timeline_version_id=version_row.id,
                    profile="preview",
                    timeline_hash=timeline_hash(tl),
                ),
            )
        await checkpoint(db, job, "preview", scene_count=len(compiled))
        result = await _run_render(db, store, settings, job.id, render)
        completed_job = await db_ops.get(db, Job, job.id)
        await checkpoint(db, completed_job or job, "complete", output_key=result["output_key"])
        return result
    except Exception as exc:
        await db_ops.update(db, Job, job.id, {"status": "failed", "error": str(exc)[:1000]})
        # The current immutable draft and all successful scene artifacts remain usable.
        return {
            "status": "failed",
            "error": str(exc),
            "draft_version": job.payload.get("planned_version"),
        }
