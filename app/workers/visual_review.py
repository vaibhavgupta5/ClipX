"""Durable review of completed exports, bounded provider attempts and honest status."""

import asyncio
import base64
import hashlib
import io
from typing import Any

from PIL import Image
from pydantic import Field

from app import db as db_ops
from app.agent.critic import evaluate_preview
from app.db import Database
from app.models import Job
from app.models import Render as RenderRow
from app.providers.registry import llm_enabled, make_llm
from app.render.quality import inspect_export
from app.scenes.models import StrictModel
from app.settings import Settings
from app.storage import Storage
from app.storyboard.models import QualityAssessment, QualityFinding
from app.storyboard.store import put_artifact
from app.timeline.schema import Timeline


class ModelBudget(StrictModel):
    """Attempts, including failed requests, share one project-level media budget."""

    requests: int = Field(default=0, ge=0, le=6)
    images: int = Field(default=0, ge=0, le=36)
    pixels: int = Field(default=0, ge=0, le=15_000_000)
    input_output_tokens: int = Field(default=0, ge=0)

    def reserve(self, body: dict[str, Any]) -> "ModelBudget":
        parts = [
            p
            for step in body.get("input", [])
            for p in step.get("content", [])
            if p.get("type") == "image"
        ]
        pixels = 0
        for part in parts:
            with Image.open(io.BytesIO(base64.b64decode(part["data"]))) as image:
                pixels += image.width * image.height
        return ModelBudget(
            requests=self.requests + 1,
            images=self.images + len(parts),
            pixels=self.pixels + pixels,
            input_output_tokens=self.input_output_tokens,
        )


async def checkpoint(db: Database, job: Job, stage: str, **facts: Any) -> None:
    """Persist recoverable stage output before proceeding to the next expensive operation."""
    job.payload = {**job.payload, "stage": stage, **facts}
    await db_ops.update(db, Job, job.id, {"payload": job.payload})


async def review_completed_render(
    db: Database,
    store: Storage,
    settings: Settings,
    job: Job,
    render: RenderRow,
    timeline: Timeline,
    key: str,
) -> QualityAssessment:
    """Technical checks precede visual review. Provider failure retains the rendered draft."""
    path = store.path_for(key)
    await checkpoint(db, job, "technical_checks", output_key=key)
    width, height = (540, 960) if render.profile == "preview" else (1080, 1920)
    technical = await asyncio.to_thread(inspect_export, path, timeline.duration_s, width, height)
    llm = None
    budget = ModelBudget.model_validate(job.payload.get("model_budget", {}))
    if llm_enabled(settings):

        async def on_attempt(body: dict[str, Any]) -> None:
            nonlocal budget
            budget = budget.reserve(body)
            await checkpoint(db, job, "visual_review", model_budget=budget.model_dump())

        # Shared ledger sees retries/fallbacks before they are sent.
        llm = make_llm(settings, on_attempt=on_attempt)
    await checkpoint(db, job, "visual_review", technical=technical)
    review = await evaluate_preview(
        llm,
        timeline,
        path,
        user_prompt="Review the encoded visual explainer. Identify exact scene/frame defects.",
    )
    budget = budget.model_copy(
        update={"input_output_tokens": budget.input_output_tokens + review.tokens_used}
    )
    await checkpoint(db, job, "visual_review", model_budget=budget.model_dump())
    findings = [
        QualityFinding(scene_id="export", frame=0, severity="critical", observation=e)
        for e in technical["errors"]
    ]
    findings += list(review.findings)
    findings += [
        QualityFinding(
            scene_id="export",
            frame=review.reviewed_frames[0] if review.reviewed_frames else 0,
            severity="warning",
            observation=e,
        )
        for e in review.issues
    ]
    assessment = QualityAssessment(
        timeline_hash=render.timeline_hash,
        render_hash=hashlib.sha256(await asyncio.to_thread(path.read_bytes)).hexdigest(),
        version=timeline.version,
        technical_pass=technical["passed"],
        creative_status="not_evaluated"
        if review.verdict == "not_evaluated"
        else "needs_edits"
        if review.verdict == "needs_edits"
        else "reviewed",
        checks=[
            "full_decode",
            "dimensions",
            "duration",
            "fps",
            "av_duration_agreement",
            "encoded_loudness",
            "true_peak",
        ],
        reviewed_frames=review.reviewed_frames,
        audio_reviewed=False,
        model_requests=budget.requests,
        image_inputs=budget.images,
        image_pixels=budget.pixels,
        findings=findings,
        limitations=[
            "Sparse visual review; full-playback human benchmark pending.",
            "Audio measured technically; listening and lip sync were not assessed.",
        ],
    )
    digest = await asyncio.to_thread(put_artifact, store, assessment)
    await checkpoint(
        db, job, "review_available", assessment_hash=digest, review=review.model_dump(mode="json")
    )
    await db_ops.update(db, RenderRow, render.id, {"quality": assessment.model_dump(mode="json")})
    return assessment
