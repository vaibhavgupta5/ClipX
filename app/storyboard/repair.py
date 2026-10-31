"""A review may request one targeted repair; stale user revisions are never replaced."""

from app.scenes.models import ScenePlacement, SceneSpec
from app.storyboard.models import QualityAssessment
from app.storyboard.planner import update_scene
from app.timeline.schema import Timeline


def apply_review_repair(
    timeline: Timeline,
    assessment: QualityAssessment,
    spec: SceneSpec,
    placement: ScenePlacement,
    *,
    expected_version: int,
    assessment_hash: str,
) -> Timeline:
    """Only a reviewed existing scene can be changed, once, against its exact version."""
    if timeline.scene_repair_count >= 1:
        raise ValueError("one automatic scene repair already used; human review is required")
    if assessment.version != expected_version or timeline.version != expected_version:
        raise ValueError(
            "stale review: user edited after this render; inspect the current revision"
        )
    if assessment.creative_status != "needs_edits":
        raise ValueError("repair requires a rendered-media finding, not an unevaluated plan")
    if spec.id not in {s.id for s in timeline.scenes}:
        raise ValueError("repair may only update an existing identified scene")
    if not any(
        f.scene_id == spec.id and f.severity in ("critical", "warning") for f in assessment.findings
    ):
        raise ValueError("no rendered finding identifies this scene")
    result = update_scene(timeline, spec, placement, expected_version=expected_version)
    return result.model_copy(
        update={"scene_repair_count": 1, "repair_assessment_hash": assessment_hash}
    )
