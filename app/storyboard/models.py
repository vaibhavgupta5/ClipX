"""Grounding, editorial intent, reference observations and review provenance."""

from typing import Literal

from pydantic import Field, model_validator

from app.scenes.models import ID, SHA, Family, StrictModel


class StyleObservation(StrictModel):
    value: str = Field(min_length=1, max_length=500)
    origin: Literal["measured", "interpretation", "user"]
    confidence: float = Field(ge=0, le=1)
    frame_refs: list[str] = Field(default_factory=list)


class ReferenceStyleRecipe(StrictModel):
    schema_version: Literal[1] = 1
    source: str
    source_hash: str = Field(pattern=SHA)
    observations: list[StyleObservation]
    reviewed_frames: list[int] = Field(default_factory=list)


class CreativeBrief(StrictModel):
    audience: str = Field(min_length=1, max_length=300)
    promise: str = Field(min_length=1, max_length=400)
    takeaway: str = Field(min_length=1, max_length=400)
    permitted_changes: list[str] = Field(default_factory=list)
    source_limitations: list[str] = Field(default_factory=list)
    fps: Literal[30] = 30
    aspect: Literal["9:16"] = "9:16"
    max_model_requests: int = Field(default=6, ge=0, le=6)
    max_images: int = Field(default=36, ge=0, le=36)
    max_megapixels: float = Field(default=15, ge=0, le=15)


class EvidenceAsset(StrictModel):
    id: str = Field(pattern=ID)
    source: str = Field(min_length=1)
    captured_at: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA)
    storage_key: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    license: str = Field(min_length=1)
    attribution: str = ""
    commercial_use: bool = False
    allowed_uses: list[Literal["display", "crop", "annotate"]] = Field(min_length=1)
    kind: Literal["observed", "illustrative"]
    entity: str = Field(min_length=1)
    role: Family
    text: str = Field(default="", max_length=6000)


class Claim(StrictModel):
    id: str = Field(pattern=ID)
    start_word: str = Field(pattern=r"^w\d+$")
    end_word: str = Field(pattern=r"^w\d+$")
    entity: str = Field(min_length=1, max_length=200)
    assertion: str = Field(min_length=1, max_length=1000)
    caveat: str = Field(default="", max_length=1000)
    evidence_ids: list[str] = Field(default_factory=list)


class StoryboardBeat(StrictModel):
    id: str = Field(pattern=ID)
    start_word: str = Field(pattern=r"^w\d+$")
    end_word: str = Field(pattern=r"^w\d+$")
    role: Literal["promise", "evidence", "demonstration", "mechanism", "result", "transition"]
    family: Family
    understanding: str = Field(min_length=1, max_length=500)
    claim_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    unresolved_needs: list[str] = Field(default_factory=list)
    scene_id: str | None = Field(default=None, pattern=ID)

    @model_validator(mode="after")
    def evidence_need(self) -> "StoryboardBeat":
        if not self.evidence_ids and not self.unresolved_needs:
            raise ValueError("beat needs evidence or an explicit unresolved evidence need")
        return self


class Storyboard(StrictModel):
    schema_version: Literal[1] = 1
    brief: CreativeBrief
    timing_hash: str = Field(pattern=SHA)
    reference: ReferenceStyleRecipe | None = None
    claims: list[Claim] = Field(min_length=1, max_length=64)
    beats: list[StoryboardBeat] = Field(min_length=1, max_length=32)
    evidence: list[EvidenceAsset] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def grounding(self) -> "Storyboard":
        for items in (self.claims, self.beats, self.evidence):
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError("storyboard IDs must be unique within each collection")
        evidence = {e.id for e in self.evidence}
        claims = {c.id for c in self.claims}
        grounded: list[Claim | StoryboardBeat] = [*self.claims, *self.beats]
        for item in grounded:
            if set(item.evidence_ids) - evidence:
                raise ValueError("unknown evidence reference")
        for beat in self.beats:
            if set(beat.claim_ids) - claims:
                raise ValueError("unknown grounded claim reference")
            if not beat.evidence_ids and not beat.unresolved_needs:
                raise ValueError("beat needs evidence or an explicit unresolved evidence need")
        return self


class QualityFinding(StrictModel):
    scene_id: str
    frame: int = Field(ge=0)
    severity: Literal["critical", "warning", "note"]
    observation: str
    repair: str = ""


class QualityAssessment(StrictModel):
    timeline_hash: str
    render_hash: str = Field(pattern=SHA)
    version: int
    technical_pass: bool
    creative_status: Literal["not_evaluated", "needs_edits", "reviewed"] = "not_evaluated"
    checks: list[str] = Field(default_factory=list)
    reviewed_frames: list[int] = Field(default_factory=list)
    audio_reviewed: bool = False
    model_requests: int = Field(default=0, ge=0, le=6)
    image_inputs: int = Field(default=0, ge=0, le=36)
    image_pixels: int = Field(default=0, ge=0, le=15_000_000)
    findings: list[QualityFinding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
