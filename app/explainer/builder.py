"""Explainer builder: plan (1-2 model requests) -> cut -> source -> scenes -> policy."""

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.analysis.models import FaceBox
from app.explainer.compile import compile_cards
from app.explainer.governor import apply_drops, govern_length, prune_slivers
from app.explainer.models import Card, Plan
from app.explainer.planner import plan_cards
from app.explainer.policy import apply_policy
from app.explainer.sources import extract_urls, gather, text_for_uncaptured
from app.providers.base import LLMProvider
from app.providers.local import AssetCatalog
from app.scenes.timing import timing_hash
from app.showcase.images import GeneratedImageStore
from app.storage import Storage
from app.storyboard.models import CreativeBrief, Storyboard
from app.storyboard.planner import attach_storyboard
from app.timeline.schema import Timeline
from app.timeline.validate import ensure_valid

TARGET = re.compile(r"(?:~|about|around|under|max(?:imum)?\s*)?\s*(\d{2})\s*(?:s\b|sec)", re.I)


def target_from(message: str, default: int) -> int:
    """'~60s' / '45 sec' in the user's words, clamped to what ClipZ allows."""
    match = TARGET.search(message)
    return max(20, min(90, int(match.group(1)))) if match else default


@dataclass
class ExplainerResult:
    timeline: Timeline
    summary: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _sanitize(plan: Plan, tl: Timeline, warnings: list[str]) -> Plan:
    """Drop anything pointing at words that do not exist (a model can mistype an id)."""
    known = {w.id for w in tl.transcript.words}

    def ordered(a: str, b: str) -> tuple[str, str]:
        return (a, b) if int(a[1:]) <= int(b[1:]) else (b, a)

    drops = [ordered(a, b) for a, b in plan.drop if a in known and b in known]
    cards: list[Card] = []
    for c in plan.cards:
        if c.start_word not in known or c.end_word not in known:
            warnings.append(f"{c.id}: unknown word ids, skipped")
            continue
        a, b = ordered(c.start_word, c.end_word)
        cards.append(c.model_copy(update={"start_word": a, "end_word": b}))
    extras = [e for e in plan.extras if e.at_word in known]
    return plan.model_copy(update={"drop": drops, "cards": cards, "extras": extras})


class ExplainerBuilder:
    """Everything the Director's ``make_explainer`` tool needs, injected for testability."""

    def __init__(
        self,
        llm: LLMProvider | None,
        catalog: AssetCatalog,
        store: Storage,
        images: GeneratedImageStore | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.llm, self.catalog, self.store = llm, catalog, store
        self.images, self.sleep = images, sleep

    async def build(
        self,
        tl: Timeline,
        *,
        message: str = "",
        target_s: int | None = None,
        focus: str = "",
        faces: list[FaceBox] | None = None,
    ) -> ExplainerResult:
        warnings: list[str] = []
        faces = faces or []
        urls = extract_urls(message)
        target = target_s or target_from(message, min(60, max(20, int(tl.duration_s))))
        tl = tl.model_copy(
            update={
                "storyboard": None,
                "storyboard_hash": None,
                "scenes": [],
                "scene_placements": [],
            }
        )
        brands = sorted({i.id.split(":", 1)[1] for i in self.catalog.items("icon")})
        plan: Plan | None = None
        if self.llm is not None:
            plan = await plan_cards(
                self.llm, tl, target_s=target, urls=urls, brands=brands, focus=focus,
                warnings=warnings, brief=message,
            )  # fmt: skip
        mood, accent, extras = "tech", "teal", []
        compiled_n = 0
        evidence_n = captures = 0
        if plan is not None:
            plan = _sanitize(plan, tl, warnings)
            mood, accent, extras = plan.mood, plan.accent, plan.extras
            tl = apply_drops(tl, plan.drop, warnings, floor=target - 4)
            tl, cards = govern_length(tl, plan.cards, target, warnings)
            tl = prune_slivers(tl)
            got = await gather(
                cards, catalog=self.catalog, store=self.store, images=self.images,
                urls=urls, project_id=tl.project_id, sleep=self.sleep,
            )  # fmt: skip
            warnings += got.warnings
            cards = text_for_uncaptured(cards, got.assets.proofs, warnings)
            built = compile_cards(tl, cards, got.assets, accent)
            warnings += built.warnings
            if built.specs:
                used = {e for s in built.specs for e in s.evidence_ids}
                board = Storyboard(
                    brief=CreativeBrief(
                        audience="Viewers of a short technical explainer",
                        promise=built.specs[0].title,
                        takeaway=built.specs[-1].title,
                        permitted_changes=["Cut tangents", "Add diagrams, sources, sound"],
                        source_limitations=["Spoken claims are not independently verified"],
                    ),
                    timing_hash=timing_hash(tl),
                    claims=built.claims,
                    beats=built.beats,
                    evidence=[e for k, e in got.evidence.items() if k in used],
                )
                tl = attach_storyboard(tl, board, expected_version=tl.version).model_copy(
                    update={"scenes": built.specs, "scene_placements": built.placements}
                )
                compiled_n, evidence_n = len(built.specs), len(board.evidence)
            captures = got.captures
        tl = apply_policy(
            tl, catalog=self.catalog, faces=faces, mood=mood, extras=extras, warnings=warnings
        )
        ensure_valid(tl)
        summary: dict[str, object] = {
            "duration_s": round(tl.duration_s, 1),
            "target_s": target,
            "scenes": compiled_n,
            "families": sorted({s.content.template for s in tl.scenes}),
            "evidence": evidence_n,
            "page_captures": captures,
            "overlays": len(tl.overlays),
            "zooms": len(tl.zooms),
            "sfx": len(tl.sfx),
            "music": tl.music.asset if tl.music else None,
            "planner": "model" if plan is not None else "policy-only",
        }
        return ExplainerResult(tl, summary, warnings)


def new_project_id() -> uuid.UUID:  # pragma: no cover - convenience for scripts
    return uuid.uuid4()
