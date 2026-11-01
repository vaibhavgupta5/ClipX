"""Phase 7d reference-grade families: closed contracts, targets and asset permissions."""

import pytest
from pydantic import ValidationError

from app.scenes.models import DesignTokens, SceneSpec


def spec(content: dict, **kw: object) -> SceneSpec:
    return SceneSpec(id="s", title="Demo", content=content, **kw)  # type: ignore[arg-type]


def test_counter_targets_and_bounds() -> None:
    s = spec({"template": "counter", "value": 4000, "suffix": "+", "label": "apps", "cells": 64})
    assert {"value", "grid"} <= s.element_ids
    with pytest.raises(ValidationError):
        spec({"template": "counter", "value": 1, "label": "x", "cells": 65})
    with pytest.raises(ValidationError):
        spec({"template": "counter", "value": -1, "label": "x"})


def test_hub_collects_every_nested_asset_and_exposes_spokes() -> None:
    s = spec(
        {
            "template": "hub",
            "center": "Your dot",
            "center_asset_id": "logo",
            "spokes": [
                {"id": "a", "label": "A", "asset_id": "icon_a"},
                {"id": "b", "label": "B"},
                {"id": "c", "label": "C", "asset_id": "icon_c"},
            ],
        },
        events=[{"target": "b", "word": "w1", "action": "reveal"}],
    )
    assert s.asset_ids == {"logo", "icon_a", "icon_c"}
    assert {"hub", "a", "b", "c"} <= s.element_ids


def test_family_ids_must_be_unique_and_not_reserved() -> None:
    with pytest.raises(ValidationError, match="unique"):
        spec(
            {
                "template": "checklist",
                "items": [{"id": "x", "label": "A"}, {"id": "x", "label": "B"}],
            }
        )
    with pytest.raises(ValidationError, match="reserved"):
        spec(
            {
                "template": "hub",
                "center": "c",
                "spokes": [{"id": i, "label": "T"} for i in ("title", "b", "c")],
            }
        )


def test_multi_view_tile_needs_an_image_or_glyph_and_rejects_markup_fields() -> None:
    with pytest.raises(ValidationError, match="asset_id, a pictogram or a short glyph"):
        spec(
            {
                "template": "multi_view",
                "tiles": [{"id": "a", "label": "A"}, {"id": "b", "label": "B", "glyph": "?"}],
            }
        )
    with pytest.raises(ValidationError):
        spec(
            {
                "template": "multi_view",
                "tiles": [
                    {"id": "a", "label": "A", "glyph": "?", "html": "<b>x</b>"},
                    {"id": "b", "label": "B", "glyph": "?"},
                ],
            }
        )


def test_bar_targets_entrance_and_mono_tokens() -> None:
    s = spec(
        {
            "template": "bar_chart",
            "bars": [{"id": "a", "label": "A", "value": 1}, {"id": "b", "label": "B", "value": 2}],
        },
        entrance="glitch",
        tokens={"theme": "mono", "accent": "red"},
    )
    assert {"a", "b"} <= s.element_ids and s.entrance == "glitch"
    with pytest.raises(ValidationError):
        spec({"template": "impact_title", "headline": "x"}, entrance="spin")


def test_old_specs_keep_their_defaults() -> None:
    s = spec({"template": "speaker_bridge", "headline": "Hello"})
    assert s.entrance == "cut" and s.tokens == DesignTokens() and s.asset_ids == set()


def test_compiler_rejects_unpermitted_nested_asset() -> None:
    from app.scenes.compiler import compile_scenes
    from tests.unit.scenes.test_hybrid import planned

    tl = planned()
    placements = tl.scene_placements
    first = tl.scenes[0]
    hub = first.model_copy(
        update={
            "content": SceneSpec(
                id=first.id,
                title="t",
                content={
                    "template": "hub",
                    "center": "c",
                    "spokes": [{"id": f"s{i}", "label": "L", "asset_id": "nope"} for i in range(3)],
                },
            ).content
        }
    )
    beats = [
        b.model_copy(update={"family": "hub"}) if b.scene_id == first.id else b
        for b in tl.storyboard.beats  # type: ignore[union-attr]
    ]
    from app.storyboard.planner import attach_storyboard

    board = tl.storyboard.model_copy(update={"beats": beats})  # type: ignore[union-attr]
    tl = attach_storyboard(tl, board, expected_version=tl.version).model_copy(
        update={"scenes": [hub, *tl.scenes[1:]], "scene_placements": placements}
    )
    with pytest.raises(ValueError, match="image nope must reference permitted"):
        compile_scenes(tl)


def test_scenes_absorb_clip_padding_but_never_a_word() -> None:
    from app.scenes.timing import TimingMap

    timing = TimingMap(
        words={"w1": (3, 10), "w2": (12, 20), "w3": (40, 50)},
        frame_count=60,
        clips=((0, 24), (24, 60)),
    )
    assert timing.absorb_padding(3, 20) == (0, 24)  # whole first clip: no raw flash frames
    assert timing.absorb_padding(12, 20) == (12, 24)  # w1 stays with whatever precedes
    assert timing.absorb_padding(40, 50) == (24, 60)


def test_director_storyboard_needs_no_internal_fields() -> None:
    from app.tools.executor import ToolFailure, ToolState, execute
    from tests.unit.timeline.test_ops import _timeline

    tl = _timeline()
    w = [x.id for x in tl.transcript.words]
    out = execute(
        "plan_storyboard",
        {
            "brief": {"audience": "Judges", "promise": "Show it", "takeaway": "It works"},
            "claims": [
                {
                    "id": "c1",
                    "start_word": w[0],
                    "end_word": w[1],
                    "entity": "X",
                    "assertion": "X works",
                }
            ],
            "beats": [
                {
                    "id": "b1",
                    "start_word": w[0],
                    "end_word": w[1],
                    "role": "promise",
                    "family": "counter",
                    "understanding": "Hook",
                    "claim_ids": ["c1"],
                    "unresolved_needs": ["a source page"],
                }
            ],
        },
        ToolState(tl),
    )
    assert not isinstance(out, ToolFailure), out
    assert out.timeline is not None and out.timeline.storyboard is not None
    assert out.timeline.storyboard.claims[0].assertion == "X works"
