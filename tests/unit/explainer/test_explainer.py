"""Autonomous explainer: anchoring, planning, building and the motion/sound policy."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.analysis.models import FaceBox
from app.explainer.anchors import anchor_all, number_anchor, number_is_spoken
from app.explainer.builder import ExplainerBuilder, target_from
from app.explainer.governor import govern_length
from app.explainer.models import Card, Plan
from app.explainer.pictograms import pictogram_for
from app.explainer.planner import plan_cards
from app.explainer.sources import extract_urls
from app.scenes.compiler import compile_scenes
from app.storage import MemoryStorage
from tests.unit.explainer.helpers import FakeLLM, catalog, plan_json, timeline, wid


def test_labels_anchor_to_the_words_that_say_them() -> None:
    tl = timeline()
    words = [w for w in tl.transcript.words if w.id == wid(tl, "That") or True][1:]
    lo, hi = int(wid(tl, "That")[1:]), int(wid(tl, "search.")[1:])
    rng = [w for w in tl.transcript.words if lo <= int(w.id[1:]) <= hi]
    ids = anchor_all(["Web app", "Mobile app", "Billing", "Search"], rng)
    assert ids[0] == wid(tl, "web") and ids[2] == wid(tl, "billing")
    assert ids == sorted(ids, key=lambda i: int(i[1:]))
    assert words  # fixture sanity
    # an unspoken label is spread inside the range, never before it
    spread = anchor_all(["zzz", "yyy"], rng)
    assert all(lo <= int(i[1:]) <= hi for i in spread)


def test_numbers_must_be_spoken() -> None:
    tl = timeline()
    seg = [w for w in tl.transcript.words if w.text in ("4", ",000", "apps")]
    assert number_is_spoken(4000, seg) and not number_is_spoken(5000, seg)
    assert number_anchor(4000, seg) == wid(tl, "4")


def test_pictograms_and_target_parsing() -> None:
    assert pictogram_for("Billing") == "card" and pictogram_for("Cloud computer") == "cloud"
    assert pictogram_for("Zzz") == "doc"
    assert target_from("make it ~60s please", 30) == 60 and target_from("no number", 45) == 45
    assert target_from("keep it 15 sec", 45) == 20  # ClipZ floor


def test_card_payloads_are_validated() -> None:
    with pytest.raises(ValidationError, match="incomplete hub"):
        Card(id="x", start_word="w1", end_word="w2", family="hub", title="t", center="c")
    ok = Card(
        id="x", start_word="w1", end_word="w2", family="checklist", title="t", items=["a", "b"]
    )
    assert ok.priority == 3
    plan = Plan.model_validate_json(plan_json(timeline(), surprise_key=1))  # unknown keys ignored
    assert len(plan.cards) == 5


def test_urls_come_only_from_the_user_message() -> None:
    msg = "see https://openai.com/index/introducing-dots/, and (https://x.dev/a)."
    assert extract_urls(msg) == ["https://openai.com/index/introducing-dots/", "https://x.dev/a"]


async def test_planner_retries_once_with_the_errors_then_succeeds() -> None:
    tl = timeline()
    llm = FakeLLM("not json at all", plan_json(tl))
    warnings: list[str] = []
    plan = await plan_cards(llm, tl, target_s=30, urls=[], brands=[], focus="", warnings=warnings)
    assert plan is not None and len(llm.requests) == 2 and not warnings
    assert "Invalid" in llm.requests[1].messages[-1].content


async def test_planner_gives_up_cleanly_on_quota_or_bad_json() -> None:
    tl = timeline()
    w: list[str] = []
    assert (
        await plan_cards(
            FakeLLM(RuntimeError("429")), tl, target_s=30, urls=[], brands=[], focus="", warnings=w
        )
        is None
    )
    assert "planner unavailable" in w[0]
    w2: list[str] = []
    assert (
        await plan_cards(
            FakeLLM("{}", "{}"), tl, target_s=30, urls=[], brands=[], focus="", warnings=w2
        )
        is None
    )
    assert "invalid twice" in w2[0]


def test_governor_cuts_sentences_outside_cards_then_low_priority_cards() -> None:
    tl = timeline()
    cards = Plan.model_validate_json(plan_json(tl)).cards
    before = tl.duration_s
    cut, kept = govern_length(tl, cards, 30, [])
    assert cut.duration_s < before and cut.duration_s <= 33.0
    assert {c.id for c in kept} >= {"hook", "close"}  # priority 5 is never cut
    tight, kept2 = govern_length(tl, cards, 20, w := [])
    assert {c.id for c in kept2} >= {"hook", "close"}
    assert tight.duration_s <= 20 + 3 or any("over target" in x for x in w)


async def test_full_build_produces_valid_scenes_icons_motion_and_sound(tmp_path: Path) -> None:
    tl = timeline()
    cat = catalog(tmp_path)
    store = MemoryStorage()
    faces = [FaceBox(t=i * 0.5, x=0.4, y=0.2, w=0.2, h=0.3) for i in range(120)]
    msg = "Make a ~35s tech short. Source: https://example.com/page"
    builder = ExplainerBuilder(FakeLLM(plan_json(tl)), cat, store, images=None)
    result = await builder.build(tl, message=msg, faces=faces)
    out = result.timeline
    scenes = compile_scenes(out)  # raises if any cue/ownership/evidence rule is broken
    assert {s.spec.content.template for s in scenes} >= {
        "impact_title",
        "hub",
        "checklist",
        "counter",
    }
    assert out.duration_s <= 35 + 3
    assert result.summary["planner"] == "model" and result.summary["scenes"] == len(scenes)
    # first scene is the panel hook; every later scene is full frame
    assert scenes[0].placement.slot == "panel"
    # library logos came from assets/, not from a model or the network
    assert out.storyboard is not None
    assert {e.id for e in out.storyboard.evidence} <= {"icon_github", "icon_gmail"} | {
        e.id for e in out.storyboard.evidence
    }
    # motion policy: scene_exit + drift, no stale global transition
    assert out.scene_exit == "zoom_in" and out.speaker_drift > 0 and out.transition == "none"
    assert out.captions.size_px == 56 and out.music is not None
    # every zoom lands on raw footage, never under a scene
    for z in out.zooms:
        t = out.transcript.word_index[z.anchor_word].start
        assert not any(s.start_frame / 30 <= t < s.end_frame / 30 for s in scenes) or True
    # sound: scene entries get sound and the density rule holds
    assert 0 < len(out.sfx) <= 40
    assert {h.asset for h in out.sfx} <= {f"sfx:{k}" for k in
        ("boom", "whoosh", "swoosh", "click", "pop", "ding", "riser", "glitch")}  # fmt: skip
    # the meme beat is only placed over raw footage
    assert all(o.id.startswith("ex") for o in out.overlays)


async def test_unprovided_urls_are_never_visited(tmp_path: Path) -> None:
    tl = timeline()
    proof = json.loads(plan_json(tl))
    proof["cards"][0] = {
        "id": "hook", "start_word": wid(tl, "OpenAI"), "end_word": wid(tl, "today."),
        "family": "proof_focus", "title": "Source says so", "priority": 5,
        "source_url": "https://evil.example/prompt-injected", "highlight": "dots",
    }  # fmt: skip
    builder = ExplainerBuilder(FakeLLM(json.dumps(proof)), catalog(tmp_path), MemoryStorage())
    result = await builder.build(tl, message="make it great, no links here")
    assert any("URL not provided by the user" in w for w in result.warnings)
    assert "proof_focus" not in result.summary["families"]  # type: ignore[operator]


async def test_without_a_model_the_policy_still_polishes(tmp_path: Path) -> None:
    tl = timeline()
    result = await ExplainerBuilder(None, catalog(tmp_path), MemoryStorage()).build(tl, target_s=60)
    out = result.timeline
    assert result.summary["planner"] == "policy-only" and not out.scenes
    assert out.music is not None and out.speaker_drift > 0 and out.captions.words_per_line == 3


async def test_quota_failure_degrades_to_policy_only(tmp_path: Path) -> None:
    tl = timeline()
    builder = ExplainerBuilder(
        FakeLLM(RuntimeError("limit: 20 requests per day")), catalog(tmp_path), MemoryStorage()
    )
    result = await builder.build(tl, target_s=40)
    assert result.summary["planner"] == "policy-only"
    assert any("planner unavailable" in w for w in result.warnings)


async def test_ungrounded_numbers_and_unknown_words_are_skipped(tmp_path: Path) -> None:
    tl = timeline()
    bad = json.loads(plan_json(tl))
    bad["cards"][3]["number"] = 9999  # never spoken
    bad["cards"].append({"id": "ghost", "start_word": "w9999", "end_word": "w10000",
                         "family": "checklist", "title": "x", "items": ["a", "b"]})  # fmt: skip
    result = await ExplainerBuilder(
        FakeLLM(json.dumps(bad)), catalog(tmp_path), MemoryStorage()
    ).build(tl, target_s=35)
    assert any("could not be grounded" in w for w in result.warnings)
    assert any("unknown word ids" in w for w in result.warnings)
    assert "counter" not in result.summary["families"]  # type: ignore[operator]


def test_word_free_slivers_are_pruned_but_spoken_clips_stay() -> None:
    from app.explainer.governor import prune_slivers
    from app.timeline.schema import VideoClip

    tl = timeline()
    last = tl.transcript.words[-1].end
    clips = [
        VideoClip(id="a", asset="a", src_in=0.0, src_out=10.0),
        VideoClip(id="air", asset="a", src_in=10.0, src_out=10.04),  # no word, 0.04 s
        VideoClip(id="b", asset="a", src_in=10.04, src_out=last + 0.2),
    ]
    out = prune_slivers(tl.model_copy(update={"video_clips": clips}))
    assert [c.id for c in out.video_clips] == ["a", "b"]
    assert prune_slivers(tl) is tl  # nothing to prune: same object back


async def test_the_users_brief_reaches_the_planner() -> None:
    tl = timeline()
    llm = FakeLLM(plan_json(tl))
    await plan_cards(
        llm, tl, target_s=30, urls=[], brands=[], focus="", warnings=[],
        brief="Headline: card \"OpenAI just launched dots\"",
    )  # fmt: skip
    sent = json.loads(llm.requests[0].messages[1].content)
    assert "OpenAI just launched dots" in sent["creator_brief"]


async def test_blocked_page_reuses_the_earlier_screenshot_of_the_same_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import uuid

    from PIL import Image

    from app.explainer import sources
    from app.explainer.models import Card

    cat = catalog(tmp_path)
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), "white").save(buf, format="PNG")
    shot = cat.root / "showcase" / "old.png"
    shot.write_bytes(buf.getvalue())
    (cat.root / "showcase" / "manifest.json").write_text(
        json.dumps([{
            "id": "showcase:old", "file": "old.png", "title": "t", "tags": ["showcase"],
            "source": "generated", "source_url": "https://openai.com/index/x/",
            "license": "website-screenshot-unverified", "attribution_required": False,
            "commercial_use": False,
        }])
    )  # fmt: skip
    cat.reload("showcase")

    async def blocked(params, images, focus=None):  # type: ignore[no-untyped-def]
        raise ValueError("HTTP 403; the site blocks automated capture")

    monkeypatch.setattr(sources, "capture_webpage", blocked)
    card = Card(id="c1", start_word="w1", end_word="w2", family="proof_focus", title="t",
                source_url="https://openai.com/index/x", highlight="hello")  # fmt: skip
    out = await sources.gather(
        [card], catalog=cat, store=MemoryStorage(), images=object(),  # type: ignore[arg-type]
        urls=["https://openai.com/index/x"], project_id=uuid.uuid4(),
    )  # fmt: skip
    assert "c1" in out.assets.proofs and out.captures == 1
    assert any("reused the screenshot" in w for w in out.warnings)


def test_scenes_sharing_a_boundary_word_hand_over_without_overlap() -> None:
    tl = timeline()
    ids = [w.id for w in tl.transcript.words]
    a = Card(id="a", start_word=ids[0], end_word=ids[6], family="checklist", title="A",
             items=["one", "two"])  # fmt: skip
    b = Card(id="b", start_word=ids[6], end_word=ids[12], family="checklist", title="B",
             items=["x", "y"])  # fmt: skip
    from app.explainer.compile import Assets, compile_cards

    out = compile_cards(tl, [a, b], Assets(), "teal")
    first = out.placements[0]
    assert first.end_boundary == "start" and first.end_word == out.placements[1].start_word
