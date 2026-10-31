"""High-level scene tools: typed inputs, outputs and bounded parameter edits."""

from pydantic import BaseModel, Field

from app.scenes.models import Family, ScenePlacement, SceneSpec
from app.storyboard.models import (
    Claim,
    CreativeBrief,
    EvidenceAsset,
    ReferenceStyleRecipe,
    Storyboard,
    StoryboardBeat,
)


class PlanStoryboardIn(BaseModel):
    expected_version: int = Field(ge=1)
    brief: CreativeBrief
    storyboard: Storyboard | None = None
    create_draft_scenes: bool = False


class PlanStoryboardToolIn(BaseModel):
    """Director-facing plan: the model authors claims and beats only. The server stamps the
    timing hash and keeps the project's frozen evidence, so no internal field is guessed."""

    expected_version: int | None = Field(
        default=None, ge=1, description="Current timeline version (omit to use the latest)"
    )
    brief: CreativeBrief
    claims: list[Claim] = Field(
        default_factory=list, max_length=64, description="Spoken claims with word anchors"
    )
    beats: list[StoryboardBeat] = Field(
        default_factory=list,
        max_length=32,
        description="Visual beats; each cites claim_ids and evidence_ids or unresolved_needs",
    )
    create_draft_scenes: bool = False


class SceneIn(BaseModel):
    expected_version: int = Field(ge=1)
    spec: SceneSpec
    placement: ScenePlacement


class InspectSceneIn(BaseModel):
    scene_id: str


class InspectSceneOut(BaseModel):
    version: int
    spec: SceneSpec
    placement: ScenePlacement
    start_frame: int
    end_frame: int


class ResolveVisualsIn(BaseModel):
    entity: str = Field(min_length=1)
    role: Family
    observed_only: bool = False


class ResolveVisualsOut(BaseModel):
    selected: list[str]
    assets: list[EvidenceAsset] = Field(default_factory=list)
    rejected: dict[str, str]


class AnalyzeReferenceIn(BaseModel):
    recipe: ReferenceStyleRecipe
    expected_version: int = Field(ge=1)


class ReviewRenderOut(BaseModel):
    version: int
    creative_status: str
    assessment: dict[str, object] | None = None


class ClearStoryboardIn(BaseModel):
    expected_version: int = Field(ge=1)
