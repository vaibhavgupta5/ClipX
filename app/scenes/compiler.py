"""Pure schedule compilation with explicit ownership and global animation phase."""

from typing import TYPE_CHECKING

from pydantic import Field

from app.scenes.models import ScenePlacement, SceneSpec, StrictModel
from app.scenes.timing import StalePlanError, TimingMap, timing_hash
from app.storyboard.models import Claim, StoryboardBeat
from app.storyboard.store import content_hash

if TYPE_CHECKING:
    from app.timeline.schema import Timeline

MOTION_FRAMES = {"snap": 1, "gentle": 12, "emphasis": 18}


class CompiledEvent(StrictModel):
    target: str
    action: str
    frame: int
    duration_frames: int
    state: str


class CompiledScene(StrictModel):
    spec: SceneSpec
    placement: ScenePlacement
    start_frame: int
    end_frame: int
    events: list[CompiledEvent] = Field(default_factory=list)

    @property
    def frame_count(self) -> int:
        return self.end_frame - self.start_frame

    @property
    def spec_hash(self) -> str:
        return content_hash(self)


def compile_scenes(timeline: "Timeline") -> list[CompiledScene]:
    """Validate grounding, cues and same-slot occupancy before rendering any pixels."""
    if not timeline.scenes and not timeline.scene_placements:
        return []
    timing = TimingMap.from_timeline(timeline)
    if timeline.storyboard is None:
        raise ValueError("scenes require a persistent grounded storyboard")
    board = timeline.storyboard
    if board.timing_hash != timing_hash(timeline):
        raise StalePlanError(
            "narration/retained clips changed; re-plan storyboard before rendering"
        )
    if timeline.storyboard_hash != content_hash(board):
        raise ValueError("storyboard hash does not match its immutable content")
    anchored: list[Claim | StoryboardBeat] = [*board.claims, *board.beats]
    for item in anchored:
        timing.interval(item.start_word, item.end_word)
    specs = {s.id: s for s in timeline.scenes}
    if len(specs) != len(timeline.scenes):
        raise ValueError("duplicate scene IDs")
    if len({p.scene_id for p in timeline.scene_placements}) != len(timeline.scene_placements):
        raise ValueError("a scene may only be placed once; clone its spec to reuse it")
    evidence = {e.id: e for e in board.evidence}
    result = []
    for p in timeline.scene_placements:
        if p.scene_id not in specs:
            raise ValueError(f"missing spec {p.scene_id}")
        spec = specs[p.scene_id]
        beats = [b for b in board.beats if b.scene_id == spec.id]
        if not beats:
            raise ValueError(f"scene {spec.id} needs a grounded storyboard beat")
        if any(b.family != spec.content.template for b in beats):
            raise ValueError(f"scene {spec.id} family differs from storyboard")
        if set(spec.evidence_ids) - evidence.keys():
            raise ValueError(f"scene {spec.id} references unknown evidence")
        if not spec.illustrative and any(evidence[i].kind != "observed" for i in spec.evidence_ids):
            raise ValueError("illustrative assets cannot be presented as observed proof")
        if spec.content.template == "proof_focus":
            asset = evidence.get(spec.content.asset_id)
            if asset is None or "display" not in asset.allowed_uses:
                raise ValueError("proof needs an evidence asset permitted for display")
            if (
                spec.content.crop != (0, 0, 1, 1) or spec.content.focus_crop
            ) and "crop" not in asset.allowed_uses:
                raise ValueError("evidence source does not permit cropping")
            if spec.content.annotations and "annotate" not in asset.allowed_uses:
                raise ValueError("evidence source does not permit annotation")
        for required_asset in sorted(spec.asset_ids):
            asset = evidence.get(required_asset)
            if asset is None or "display" not in asset.allowed_uses:
                raise ValueError(
                    f"scene {spec.id}: image {required_asset} must reference permitted "
                    "project evidence"
                )
        a, b = timing.interval(p.start_word, p.end_word)
        if p.end_boundary == "start":
            b = timing.words[p.end_word][0]
        if b <= a:
            raise ValueError("scene interval must contain at least one frame")
        a, b = timing.absorb_padding(a, b)
        events = []
        for event in spec.events:
            at, _ = timing.interval(event.word, event.word)
            if not a <= at < b:
                raise StalePlanError(f"scene {spec.id}: cue {event.word} is outside placement")
            events.append(
                CompiledEvent(
                    target=event.target,
                    action=event.action,
                    frame=at - a,
                    duration_frames=min(MOTION_FRAMES[event.preset], b - at),
                    state=event.state,
                )
            )
        events.sort(key=lambda e: (e.frame, e.target, e.action))
        result.append(
            CompiledScene(
                spec=spec,
                placement=p,
                start_frame=a,
                end_frame=b,
                events=events,
            )
        )
    result.sort(key=lambda s: (s.start_frame, s.placement.layer, s.spec.id))
    # Absorbing clip padding can pull a scene's start back across the previous scene's end
    # (hand-over on a word). The later scene owns the overlap; same-slot only.
    for i, first in enumerate(result[:-1]):
        for later in result[i + 1 :]:
            if later.start_frame >= first.end_frame:
                break
            if (
                first.placement.slot == later.placement.slot
                and later.start_frame > first.start_frame
            ):
                result[i] = first = first.model_copy(update={"end_frame": later.start_frame})
    for i, a_scene in enumerate(result):
        for b_scene in result[i + 1 :]:
            if b_scene.start_frame >= a_scene.end_frame:
                break
            if a_scene.placement.slot == b_scene.placement.slot:
                raise ValueError(f"scene ownership collision: {a_scene.spec.id}, {b_scene.spec.id}")
    return result
