"""Cards -> typed scenes. Deterministic: labels become nodes, words become cues."""

from dataclasses import dataclass, field
from urllib.parse import urlparse

from pydantic import ValidationError

from app.explainer.anchors import (
    anchor_all,
    norm,
    number_anchor,
    number_is_spoken,
    slug,
)
from app.explainer.models import Card
from app.explainer.pictograms import pictogram_for
from app.scenes.models import (
    Bar,
    BarChartScene,
    CheckItem,
    ChecklistScene,
    CounterScene,
    HubScene,
    ImpactTitleScene,
    MultiViewScene,
    ProofScene,
    SceneAnnotation,
    ScenePlacement,
    SceneSpec,
    Spoke,
    Tile,
)
from app.scenes.timing import TimingMap
from app.storyboard.models import Claim, StoryboardBeat
from app.timeline.schema import Timeline
from app.timeline.transcript import Word

MIN_FRAMES = 30  # a scene shorter than 1 s cannot show a state change
ENTRANCE = {"counter": "zoom", "impact_title": "flash"}
ROLE = {
    "impact_title": "promise",
    "hub": "mechanism",
    "checklist": "demonstration",
    "counter": "evidence",
    "multi_view": "demonstration",
    "proof_focus": "evidence",
    "bar_chart": "evidence",
}


@dataclass
class Assets:
    """Frozen evidence the cards may use, produced by the (I/O) source stage."""

    icons: dict[str, str] = field(default_factory=dict)  # normalized label -> evidence id
    backdrops: dict[str, str] = field(default_factory=dict)  # card id -> evidence id
    proofs: dict[str, str] = field(default_factory=dict)  # card id -> evidence id
    focus: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)
    sizes: dict[str, tuple[int, int]] = field(default_factory=dict)  # evidence id -> (w, h)


@dataclass
class Compiled:
    specs: list[SceneSpec] = field(default_factory=list)
    placements: list[ScenePlacement] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    beats: list[StoryboardBeat] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _idx(word_id: str) -> int:
    return int(word_id[1:])


def card_words(tl: Timeline, timing: TimingMap, card: Card, after: int) -> list[Word]:
    """Retained words of a card, never overlapping the previous scene (``after`` = its last)."""
    lo, hi = max(_idx(card.start_word), after + 1), _idx(card.end_word)
    return [w for w in tl.transcript.words if w.id in timing.words and lo <= _idx(w.id) <= hi]


def _focus_crop(
    box: tuple[float, float, float, float] | None, size: tuple[int, int], viewport: float
) -> tuple[float, float, float, float] | None:
    """Camera window around the highlighted text, matched to the scene viewport's aspect."""
    if box is None:
        return None
    x, y, w, h = box
    iw, ih = size
    cw = min(1.0, max(w * 1.5, 0.62))
    ch = min(1.0, cw * (iw / ih) / viewport)
    cx, cy = x + w / 2, y + h / 2
    x0 = min(max(0.0, cx - cw / 2), 1 - cw)
    y0 = min(max(0.0, cy - ch / 2), 1 - ch)
    return (round(x0, 4), round(y0, 4), round(cw, 4), round(ch, 4))


def _events(card: Card, words: list[Word], ids: dict[str, list[str]]) -> list[dict[str, str]]:
    """Cue list. Every event names the word that says it; nothing fires before its word."""
    first = words[0].id
    pos = {w.id: i for i, w in enumerate(words)}

    def later(word_id: str, by: int) -> str:
        return words[min(pos[word_id] + by, len(words) - 1)].id

    def ev(target: str, action: str, word: str, state: str = "active") -> dict[str, str]:
        return {"target": target, "action": action, "word": word, "state": state}

    out: list[dict[str, str]] = []
    if card.family == "hub":
        out.append(ev("hub", "reveal", first))
        anchors = anchor_all(card.items, words)
        for sid, a in zip(ids["items"], anchors, strict=True):
            out.append(ev(sid, "reveal", a))
        if card.tone == "risk":  # the last third of the spokes turn red as the speaker warns
            for sid, a in list(zip(ids["items"], anchors, strict=True))[
                -max(1, len(anchors) // 3) :
            ]:
                out.append(ev(sid, "update", later(a, 3), "rejected"))
    elif card.family == "checklist":
        anchors = anchor_all(card.items, words)
        for sid, a in zip(ids["items"], anchors, strict=True):
            out.append(ev(sid, "reveal", a))
            out.append(ev(sid, "update", later(a, 3), "accepted"))
    elif card.family == "counter" and card.number is not None:
        at = number_anchor(card.number, words) or first
        out.append(ev("value", "reveal", at))
        if ids.get("grid"):
            out.append(ev("grid", "reveal", later(at, 1)))
    elif card.family in ("multi_view", "bar_chart"):
        for sid, a in zip(ids["items"], anchor_all(card.items, words), strict=True):
            out.append(ev(sid, "reveal", a))
    elif card.family == "proof_focus":
        out.append(ev("body", "reveal", first))
        if "src_hl" in ids.get("annotations", []):
            out.append(ev("src_hl", "reveal", later(first, 2)))
        out.append(ev("body", "focus", later(first, 4)))
    elif card.family == "impact_title":
        out.append(ev("title", "reveal", first))
    return out


def _content(
    card: Card, words: list[Word], assets: Assets, evidence: list[str], slot: str
) -> tuple[object, dict[str, list[str]]] | None:
    """Template content for one card plus the element IDs its events target."""
    taken: set[str] = set()
    ids: dict[str, list[str]] = {}
    risk = card.tone == "risk"
    if card.family == "hub":
        ids["items"] = [slug(i, taken) for i in card.items]
        center_asset = assets.icons.get(norm(card.center))
        spokes = []
        for sid, label in zip(ids["items"], card.items, strict=True):
            asset = assets.icons.get(norm(label))
            if asset:
                evidence.append(asset)
            spokes.append(
                Spoke(
                    id=sid,
                    label=label[:24],
                    asset_id=asset,
                    pictogram=None if asset else pictogram_for(label),
                )
            )
        if center_asset:
            evidence.append(center_asset)
        return (
            HubScene(
                center=card.center,
                center_asset_id=center_asset,
                center_pictogram=None
                if center_asset
                else pictogram_for(card.center, "warning" if risk else "gear"),
                spokes=spokes,
            ),
            ids,
        )
    if card.family == "checklist":
        ids["items"] = [slug(i, taken) for i in card.items]
        rows = [
            CheckItem(id=s, label=label) for s, label in zip(ids["items"], card.items, strict=True)
        ]
        return ChecklistScene(items=rows), ids
    if card.family == "counter" and card.number is not None:
        if not number_is_spoken(card.number, words):
            return None
        cells = 64 if card.number >= 100 else 0
        ids["grid"] = ["grid"] if cells else []
        return (
            CounterScene(
                value=card.number,
                decimals=0 if float(card.number).is_integer() else 1,
                prefix=card.prefix,
                suffix=card.suffix,
                label=card.number_label,
                cells=cells,
            ),
            ids,
        )
    if card.family == "multi_view":
        ids["items"] = [slug(i, taken) for i in card.items]
        tiles = []
        for sid, label in zip(ids["items"], card.items, strict=True):
            asset = assets.icons.get(norm(label))
            if asset:
                evidence.append(asset)
            tiles.append(
                Tile(
                    id=sid,
                    label=label[:32],
                    asset_id=asset,
                    pictogram=None if asset else pictogram_for(label),
                    glyph="?" if label.strip().endswith("?") else "",
                )
            )
        return MultiViewScene(tiles=tiles), ids
    if card.family == "bar_chart":
        if not all(number_is_spoken(v, words) for v in card.values):
            return None
        ids["items"] = [slug(i, taken) for i in card.items]
        bars = [
            Bar(id=s, label=label[:28], value=v, display=f"{v:g}")
            for s, label, v in zip(ids["items"], card.items, card.values, strict=True)
        ]
        return BarChartScene(bars=bars), ids
    if card.family == "proof_focus":
        proof = assets.proofs.get(card.id)
        if proof is None:
            return None
        evidence.append(proof)
        box = assets.focus.get(card.id)
        size = assets.sizes.get(proof, (1536, 2048))
        crop = _focus_crop(box, size, 940 / (700 if slot == "full" else 380))
        annotations = []
        if box is not None:
            ids["annotations"] = ["src_hl"]
            x, y, w, h = box
            pad = 0.008
            x0, y0 = max(0.0, x - pad), max(0.0, y - pad)
            annotations.append(
                SceneAnnotation(
                    id="src_hl",
                    x=round(x0, 4),
                    y=round(y0, 4),
                    width=round(min(1 - x0, w + 2 * pad), 4),
                    height=round(min(1 - y0, h + 2 * pad), 4),
                    label="SOURCE",
                )
            )
        host = (urlparse(card.source_url).hostname or "SOURCE").removeprefix("www.")
        return (
            ProofScene(
                asset_id=proof,
                excerpt=(card.highlight or card.title)[:240],
                source_label=host.upper()[:80],
                focus_crop=crop,
                annotations=annotations,
            ),
            ids,
        )
    if card.family == "impact_title":
        backdrop = assets.backdrops.get(card.id)
        if backdrop:
            evidence.append(backdrop)
        return (
            ImpactTitleScene(kicker=card.kicker, headline=card.headline, asset_id=backdrop),
            ids,
        )
    return None


def compile_cards(tl: Timeline, cards: list[Card], assets: Assets, accent: str) -> Compiled:
    """Build scenes, placements, claims and beats for the retained narration."""
    timing = TimingMap.from_timeline(tl)
    out = Compiled()
    chosen: list[tuple[Card, list[Word]]] = []
    after = 0
    for card in sorted(cards, key=lambda c: _idx(c.start_word)):
        words = card_words(tl, timing, card, after)
        if len(words) < 2:
            out.warnings.append(f"{card.id}: no retained narration left, skipped")
            continue
        frames = timing.words[words[-1].id][1] - timing.words[words[0].id][0]
        if frames < MIN_FRAMES:
            out.warnings.append(f"{card.id}: under 1 s after cuts, skipped")
            continue
        chosen.append((card, words))
        after = _idx(words[-1].id)

    retained = [w.id for w in tl.transcript.words if w.id in timing.words]
    nxt = {a: b for a, b in zip(retained, retained[1:], strict=False)}
    split_layout = tl.reframe in ("split", "split_bottom", "split_top", "adaptive")
    for n, (card, words) in enumerate(chosen):
        if split_layout:
            slot = "panel"
        else:
            slot = "panel" if n == 0 and card.family in ("impact_title", "proof_focus") else "full"
        evidence: list[str] = []
        built = _content(card, words, assets, evidence, slot)
        if built is None:
            out.warnings.append(f"{card.id}: {card.family} could not be grounded, skipped")
            continue
        content, ids = built
        try:
            spec = SceneSpec(
                id=card.id,
                title=card.title,
                eyebrow=(card.eyebrow or f"SCENE / {n + 1:02d}").upper(),
                content=content,  # type: ignore[arg-type]
                events=_events(card, words, ids),  # type: ignore[arg-type]
                tokens={"theme": "mono", "accent": "red" if card.tone == "risk" else accent},  # type: ignore[arg-type]
                entrance="glitch" if card.tone == "risk" else ENTRANCE.get(card.family, "rise"),  # type: ignore[arg-type]
                evidence_ids=list(dict.fromkeys(evidence)),
                illustrative=card.family != "proof_focus",
            )
        except ValidationError as exc:
            out.warnings.append(f"{card.id}: invalid scene ({exc.errors()[0]['msg']}), skipped")
            continue
        out.specs.append(spec)
        out.placements.append(
            ScenePlacement(
                scene_id=card.id,
                start_word=words[0].id,
                end_word=words[-1].id,
                slot=slot,  # type: ignore[arg-type]
            )
        )
        said = " ".join(w.text for w in words)[:1000]
        out.claims.append(
            Claim(
                id=f"claim_{card.id}",
                start_word=words[0].id,
                end_word=words[-1].id,
                entity=card.title[:200],
                assertion=said,
                caveat="Spoken claim; not independently verified here.",
                evidence_ids=spec.evidence_ids,
            )
        )
        role = "result" if card.family == "impact_title" and n > 0 else ROLE[card.family]
        out.beats.append(
            StoryboardBeat(
                id=f"beat_{card.id}",
                start_word=words[0].id,
                end_word=words[-1].id,
                role=role,  # type: ignore[arg-type]
                family=spec.content.template,
                understanding=card.title[:500],
                claim_ids=[f"claim_{card.id}"],
                evidence_ids=spec.evidence_ids,
                unresolved_needs=[]
                if spec.evidence_ids
                else ["Illustration of the spoken claim, not captured product output."],
                scene_id=card.id,
            )
        )

    # Adjacent scenes hand over on the next scene's first word (no raw flash between).
    fixed = []
    for i, p in enumerate(out.placements):
        following = out.placements[i + 1] if i + 1 < len(out.placements) else None
        if following is not None and (
            nxt.get(p.end_word) == following.start_word  # next word
            or p.end_word == following.start_word  # planner shared the boundary word
        ):
            p = p.model_copy(update={"end_word": following.start_word, "end_boundary": "start"})
        fixed.append(p)
    out.placements = fixed
    return out
