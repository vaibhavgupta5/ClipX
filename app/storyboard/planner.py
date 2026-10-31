"""Grounded drafts and revision-aware scene mutations, shared by tools and API."""

from app.scenes.compiler import compile_scenes
from app.scenes.models import BridgeScene, ScenePlacement, SceneSpec
from app.scenes.timing import TimingMap, timing_hash
from app.storyboard.models import Claim, CreativeBrief, Storyboard, StoryboardBeat
from app.storyboard.store import content_hash
from app.timeline.schema import Timeline
from app.timeline.transcript import Word


def draft_storyboard(timeline: Timeline, brief: CreativeBrief) -> Storyboard:
    """Conservative local draft: quote the speaker and explicitly request missing evidence."""
    timing = TimingMap.from_timeline(timeline)
    words = sorted(
        (w for w in timeline.transcript.words if w.id in timing.words),
        key=lambda w: timing.words[w.id][0],
    )
    if not words:
        raise ValueError("no fully retained words; choose a spoken source range first")
    # A local draft never invents mechanism, measurements or executed results.
    groups = []
    chunk: list[Word] = []
    for word in words:
        if chunk and (timing.words[word.id][1] - timing.words[chunk[0].id][0] > 240):
            groups.append(chunk)
            chunk = []
        chunk.append(word)
    if chunk:
        groups.append(chunk)
    claims, beats = [], []
    for index, group in enumerate(groups):
        cid, bid = f"claim{index + 1}", f"beat{index + 1}"
        assertion = " ".join(w.text for w in group)[:1000]
        claims.append(
            Claim(
                id=cid,
                start_word=group[0].id,
                end_word=group[-1].id,
                entity="Speaker",
                assertion=assertion,
                caveat="Quoted narration; external claims are unverified.",
            )
        )
        beats.append(
            StoryboardBeat(
                id=bid,
                start_word=group[0].id,
                end_word=group[-1].id,
                role="promise" if index == 0 else "transition",
                family="speaker_bridge",
                understanding=assertion[:500],
                claim_ids=[cid],
                scene_id=f"scene{index + 1}",
                unresolved_needs=["Choose evidence or an explicitly illustrative demonstration."],
            )
        )
    return Storyboard(brief=brief, timing_hash=timing_hash(timeline), claims=claims, beats=beats)


def attach_storyboard(timeline: Timeline, board: Storyboard, *, expected_version: int) -> Timeline:
    """Attach a reviewed plan to this exact narration revision."""
    check_version(timeline, expected_version)
    if board.timing_hash != timing_hash(timeline):
        raise ValueError("stale storyboard: re-plan against the current retained transcript")
    timing = TimingMap.from_timeline(timeline)
    anchored: list[Claim | StoryboardBeat] = [*board.claims, *board.beats]
    for item in anchored:
        timing.interval(item.start_word, item.end_word)
    families = {beat.scene_id: beat.family for beat in board.beats if beat.scene_id}
    retained = [
        scene for scene in timeline.scenes if families.get(scene.id) == scene.content.template
    ]
    retained_ids = {scene.id for scene in retained}
    return timeline.model_copy(
        update={
            "storyboard": board,
            "storyboard_hash": content_hash(board),
            "scenes": retained,
            "scene_placements": [
                p for p in timeline.scene_placements if p.scene_id in retained_ids
            ],
        }
    )


def check_version(timeline: Timeline, expected: int) -> None:
    """Reject patches produced against an earlier user revision."""
    if timeline.version != expected:
        raise ValueError(
            f"stale revision {expected}; current version is {timeline.version}; inspect again"
        )


def update_scene(
    timeline: Timeline,
    spec: SceneSpec,
    placement: ScenePlacement,
    *,
    expected_version: int,
) -> Timeline:
    """Upsert one named scene without changing its neighbors; all invariants recompile."""
    check_version(timeline, expected_version)
    if spec.id != placement.scene_id:
        raise ValueError("spec and placement IDs differ")
    updated = timeline.model_copy(
        update={
            "scenes": [s for s in timeline.scenes if s.id != spec.id] + [spec],
            "scene_placements": [p for p in timeline.scene_placements if p.scene_id != spec.id]
            + [placement],
        }
    )
    compile_scenes(updated)
    return updated


def materialize_draft(timeline: Timeline) -> Timeline:
    """Turn a conservative local draft into editable speaker/title scenes."""
    if timeline.storyboard is None:
        raise ValueError("plan a storyboard first")
    result = timeline
    for beat in timeline.storyboard.beats:
        if beat.scene_id is None:
            continue
        spec = SceneSpec(
            id=beat.scene_id,
            title=(
                beat.understanding[:64].rsplit(" ", 1)[0]
                if len(beat.understanding) > 64
                else beat.understanding
            ),
            content=BridgeScene(
                headline=timeline.storyboard.brief.takeaway[:90],
                supporting="Illustration · verify source claims",
            ),
        )
        result = update_scene(
            result,
            spec,
            ScenePlacement(
                scene_id=spec.id, start_word=beat.start_word, end_word=beat.end_word, slot="panel"
            ),
            expected_version=result.version,
        )
    return result
