"""Length governor: apply planned cuts, then trim by rule until the target is met."""

from app.explainer.anchors import sentences
from app.explainer.models import Card
from app.scenes.timing import TimingMap
from app.timeline import ops
from app.timeline.errors import OpError
from app.timeline.schema import Timeline
from app.timeline.transcript import Word


def apply_drops(
    tl: Timeline, drops: list[tuple[str, str]], warnings: list[str], floor: float = 0.0
) -> Timeline:
    """Delete planned word ranges; a bad range is reported, never fatal.

    A cut that would take the video below ``floor`` seconds is skipped (the model does not
    always count well), so the length governor never has to add anything back.
    """
    for a, b in drops:
        try:
            cut, _ = ops.delete_range(tl, a, b, pad_ms=60)
        except OpError as exc:
            warnings.append(f"cut {a}..{b} skipped: {exc}")
            continue
        if cut.duration_s < floor:
            warnings.append(f"cut {a}..{b} skipped: would drop below {floor:.0f}s")
            continue
        tl = cut
    return tl


def prune_slivers(tl: Timeline, min_s: float = 0.25) -> Timeline:
    """Drop clip fragments with no spoken word that are shorter than ``min_s``.

    Padded cuts leave 0.03-0.1 s scraps of air between kept ranges. Rendered as their own
    1-frame segments they shift the output by a frame and break scene alignment.
    """
    words = tl.transcript.words
    kept = [
        c
        for c in tl.video_clips
        if c.output_len >= min_s
        or any(w.start >= c.src_in - 1e-6 and w.end <= c.src_out + 1e-6 for w in words)
    ]
    if not kept or len(kept) == len(tl.video_clips):
        return tl
    return tl.model_copy(update={"video_clips": kept})


def _retained(tl: Timeline) -> list[Word]:
    timing = TimingMap.from_timeline(tl)
    return [w for w in tl.transcript.words if w.id in timing.words]


def _span(words: list[Word]) -> float:
    return words[-1].end - words[0].start


def govern_length(
    tl: Timeline, cards: list[Card], target_s: float, warnings: list[str], tol: float = 3.0
) -> tuple[Timeline, list[Card]]:
    """Cut whole sentences until duration <= target + tol.

    Order: sentences outside every card first (longest that does not undershoot), then the
    lowest-priority card (priority 5 is never cut). Reports what it could not fix.
    """
    cards = list(cards)
    for _ in range(30):
        need = tl.duration_s - target_s
        if need <= tol:
            return tl, cards
        words = _retained(tl)
        covered: set[str] = set()
        for c in cards:
            lo, hi = int(c.start_word[1:]), int(c.end_word[1:])
            covered |= {w.id for w in words if lo <= int(w.id[1:]) <= hi}
        free = [s for s in sentences(words) if not any(w.id in covered for w in s)]
        pick: list[Word] | None = None
        if free:
            fits = [s for s in free if _span(s) >= need - tol]
            pick = min(fits, key=_span) if fits else max(free, key=_span)
        else:
            cuttable = [c for c in cards if c.priority < 5]
            if not cuttable:
                warnings.append(f"length {tl.duration_s:.1f}s over target {target_s:.0f}s")
                return tl, cards
            victim = min(
                cuttable, key=lambda c: (c.priority, -(int(c.end_word[1:]) - int(c.start_word[1:])))
            )
            cards.remove(victim)
            lo, hi = int(victim.start_word[1:]), int(victim.end_word[1:])
            inside = [w for w in words if lo <= int(w.id[1:]) <= hi]
            pick = inside or None
        if not pick:
            continue
        try:
            tl, _ = ops.delete_range(tl, pick[0].id, pick[-1].id, pad_ms=60)
        except OpError as exc:
            warnings.append(f"length cut skipped: {exc}")
            return tl, cards
    warnings.append(f"length {tl.duration_s:.1f}s after trimming (target {target_s:.0f}s)")
    return tl, cards
