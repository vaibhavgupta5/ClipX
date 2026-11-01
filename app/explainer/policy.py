"""Motion, sound and cutaway policy. Rules, not model calls.

Hand-tuned on the DevDay demo: no zoom without a visible face, no effect where a scene
already carries the cut, sound on every reveal/state change but never stacked.
"""

from dataclasses import dataclass

from app.analysis.models import FaceBox
from app.explainer.anchors import sentences
from app.explainer.lookup import lookup
from app.explainer.models import Extra
from app.providers.local import AssetCatalog, LibraryItem
from app.scenes.compiler import CompiledScene, compile_scenes
from app.timeline import snap
from app.timeline.errors import OpError
from app.timeline.schema import (
    AudioEffect,
    CaptionConfig,
    MusicBed,
    Overlay,
    SfxHit,
    Timeline,
    Zoom,
)
from app.timeline.transcript import Word

GENRE = {
    "tech": "electronic",
    "calm": "lofi",
    "dramatic": "cinematic",
    "upbeat": "upbeat",
    "serious": "ambient",
}
MAX_SFX = 40
SFX_GAP_S = 0.22
ZOOM_GAP_S = 5.0


def face_near(faces: list[FaceBox], src_t: float) -> bool:
    """A tracked face within half a second of this source time (none tracked: assume yes)."""
    return not faces or any(abs(f.t - src_t) <= 0.5 for f in faces)


@dataclass
class Windows:
    """Where the output is a scene (graphics) rather than raw footage."""

    scenes: list[CompiledScene]

    def covered(self, t: float) -> bool:
        return any(s.start_frame / 30 - 0.05 <= t < s.end_frame / 30 for s in self.scenes)

    def next_start(self, t: float) -> float | None:
        starts = [s.start_frame / 30 for s in self.scenes if s.start_frame / 30 > t]
        return min(starts) if starts else None


def _windows(tl: Timeline) -> Windows:
    try:
        return Windows(compile_scenes(tl))
    except ValueError:
        return Windows([])


def _out(tl: Timeline, word_id: str) -> float | None:
    try:
        return snap.output_time_of(tl, word_id, "start")
    except OpError:
        return None


def _src_time(tl: Timeline, word_id: str) -> float:
    return tl.transcript.word_index[word_id].start


def _sentences(tl: Timeline) -> list[list[Word]]:
    kept = [w for w in tl.transcript.words if _out(tl, w.id) is not None]
    return sentences(kept)


def style_clips(tl: Timeline, faces: list[FaceBox], win: Windows, whip_at: set[float]) -> Timeline:
    """Cut effect per clip: none into scenes, a face punch onto the speaker, whip into a beat."""
    clips = []
    t = 0.0
    for i, clip in enumerate(tl.video_clips):
        fx = "none"
        if i > 0 and not win.covered(t + 0.1):
            fx = "zoom_in" if face_near(faces, clip.src_in + 0.2) else "none"
            if any(abs(t - w) < 0.6 for w in whip_at):
                fx = "whip"
        clips.append(clip.model_copy(update={"transition_in": fx}))
        t += clip.output_len
    return tl.model_copy(
        update={
            "video_clips": clips,
            "transition": "none",
            "scene_exit": "zoom_in",
            "speaker_drift": 0.03,
            "reframe": "face" if tl.reframe == "center" else tl.reframe,
        }
    )


def place_zooms(tl: Timeline, faces: list[FaceBox], win: Windows) -> Timeline:
    """Punch-ins on the start of raw speaker sentences where a face is on screen."""
    budget = max(1, round(tl.duration_s / 14))
    picks: list[tuple[float, str]] = []
    for s in _sentences(tl):
        t = _out(tl, s[0].id)
        end = _out(tl, s[-1].id)
        if t is None or end is None or end - t < 1.5:
            continue
        if win.covered(t) or win.covered(end) or not face_near(faces, _src_time(tl, s[0].id)):
            continue
        if all(abs(t - p) >= ZOOM_GAP_S for p, _ in picks):
            picks.append((t, s[0].id))
        if len(picks) >= budget:
            break
    zooms = [
        Zoom(id=f"z{i + 1}", anchor_word=w, scale=1.12, dur_ms=700, hold_ms=900)
        for i, (_, w) in enumerate(picks)
    ]
    return tl.model_copy(update={"zooms": zooms})


def _hit(
    tl: Timeline, item: LibraryItem, word_id: str, lead_ms: int, gain: float, max_ms: int, n: int
) -> SfxHit:
    w = tl.transcript.word_index[word_id]
    offset = max(-500, min(500, -int((w.end - w.start) * 1000) - lead_ms))
    return SfxHit(
        id=f"sfx{n:02d}",
        asset=item.id,
        anchor_word=word_id,
        offset_ms=offset,
        gain_db=gain,
        max_ms=max_ms,
        license=item.license,
        commercial_use=item.commercial_use,
        attribution_text=item.attribution_text if item.attribution_required else "",
    )


def place_sfx(tl: Timeline, catalog: AssetCatalog, extra_times: dict[str, str]) -> Timeline:
    """Sound on scene entries, reveals and state changes, from the compiled scene events."""
    plan: list[tuple[float, str, str, int, float, int]] = []  # t, kind, word, lead, gain, max
    n_scenes = len(tl.scene_placements)
    specs = {s.id: s for s in tl.scenes}
    for i, p in enumerate(tl.scene_placements):
        t0 = _out(tl, p.start_word)
        if t0 is None:
            continue
        edge = i in (0, n_scenes - 1) and specs[p.scene_id].content.template == "impact_title"
        kind = "boom" if edge else ("whoosh", "swoosh")[i % 2]
        plan.append((t0, kind, p.start_word, 250 if not edge else 300, -16 if edge else -22, 900))
        for e in specs[p.scene_id].events:
            t = _out(tl, e.word)
            if t is None:
                continue
            if e.action == "update" and e.state == "accepted":
                plan.append((t, "ding", e.word, 0, -24, 500))
            elif e.action == "update" and e.state == "rejected":
                plan.append((t, "glitch", e.word, 0, -22, 450))
            elif e.action == "reveal" and e.target == "value":
                plan.append((t, "riser", e.word, 500, -26, 1400))
            elif e.action == "reveal" and e.target not in ("title", "body"):
                plan.append((t, "click", e.word, 0, -26, 220))
    for word, kind in extra_times.items():
        t = _out(tl, word)
        if t is not None:
            plan.append((t, kind, word, 0, -22, 500))
    plan.sort(key=lambda x: x[0])
    hits: list[SfxHit] = []
    last_t = -9.0
    variants: dict[str, int] = {}
    for t, kind, word, lead, gain, max_ms in plan:
        if len(hits) >= MAX_SFX or (t - last_t < SFX_GAP_S and kind not in ("boom", "riser")):
            continue
        v = variants.get(kind, 0)
        item = catalog.sfx(kind, v)
        if item is None:
            continue
        variants[kind] = v + 1
        hits.append(_hit(tl, item, word, lead, gain, max_ms, len(hits) + 1))
        last_t = t
    return tl.model_copy(update={"sfx": hits})


def place_extras(
    tl: Timeline, catalog: AssetCatalog, win: Windows, extras: list[Extra], warnings: list[str]
) -> tuple[Timeline, dict[str, str], set[float]]:
    """Meme / emoji / B-roll from the local library, only over raw footage."""
    overlays: list[Overlay] = []
    sound: dict[str, str] = {}
    whips: set[float] = set()
    kinds = {"meme": ("meme", "meme", "pip_pop", 2600), "gif": ("gif", "gif", "pip_pop", 1600),
             "broll": ("video", "video", "cutaway_full", 2200)}  # fmt: skip
    for i, ex in enumerate(extras):
        lib, typ, layout, dur = kinds[ex.kind]
        found = lookup(catalog, lib, ex.query)
        if found is None:
            warnings.append(f"{ex.kind} {ex.query!r}: nothing in the library")
            continue
        item, tier = found
        if tier != "exact":
            warnings.append(f"{ex.kind} {ex.query!r}: closest library match is {item.title!r}")
        t = _out(tl, ex.at_word)
        if t is None or win.covered(t):
            warnings.append(f"{ex.kind} at {ex.at_word}: not over raw footage, skipped")
            continue
        nxt = win.next_start(t)
        ms = dur if nxt is None else int(min(dur, (nxt - t - 0.1) * 1000))
        if ms < 800:
            warnings.append(f"{ex.kind} at {ex.at_word}: too close to a scene, skipped")
            continue
        overlays.append(
            Overlay(
                id=f"ex{i + 1}",
                type=typ,  # type: ignore[arg-type]
                asset=item.id,
                anchor_word=ex.at_word,
                offset_ms=0,
                duration_ms=ms,
                layout=layout,  # type: ignore[arg-type]
                license=item.license,
                attribution_required=item.attribution_required,
                attribution_text=item.attribution_text,
                commercial_use=item.commercial_use,
                motion="push_in" if ex.kind == "broll" else "none",
            )
        )
        sound[ex.at_word] = "pop" if ex.kind != "broll" else "whoosh"
        if ex.kind == "meme":
            whips.add(t)
    return tl.model_copy(update={"overlays": [*tl.overlays, *overlays]}), sound, whips


def set_sound_bed(tl: Timeline, catalog: AssetCatalog, mood: str) -> Timeline:
    """Library music by mood (ducked under speech by the mixer) and loudness normalisation."""
    genre = GENRE.get(mood, "electronic")
    pool = [t for t in catalog.items("music") if t.genre == genre] or catalog.items("music")
    # Long enough first (so it never loops under a 60 s short), then the library's own order.
    pool.sort(key=lambda t: t.duration_s < tl.duration_s)
    bed = None
    if pool:
        t = pool[0]
        bed = MusicBed(
            asset=t.id,
            license=t.license,
            attribution_required=t.attribution_required,
            attribution_text=t.attribution_text,
            level_db=-23,
            commercial_use=t.commercial_use,
        )
    return tl.model_copy(
        update={
            "music": bed,
            "audio_fx": [AudioEffect(type="loudnorm", params={"lufs": -14})],
            "captions": CaptionConfig(
                mode="word_highlight",
                position="showcase",
                words_per_line=3,
                size_px=56,
                base_color="#F5F5F2",
                highlight_color="#F4E64A",
                animation="none",
            ),
        }
    )


def apply_policy(
    tl: Timeline,
    *,
    catalog: AssetCatalog,
    faces: list[FaceBox],
    mood: str,
    extras: list[Extra],
    warnings: list[str],
) -> Timeline:
    """Everything with a rule, in dependency order."""
    win = _windows(tl)
    tl, sound, whips = place_extras(tl, catalog, win, extras, warnings)
    tl = style_clips(tl, faces, win, whips)
    tl = place_zooms(tl, faces, win)
    tl = place_sfx(tl, catalog, sound)
    return set_sound_bed(tl, catalog, mood)
