# ruff: noqa: E501, ASYNC240, S311  (one-off data script: long SQL literals, small local file reads)
"""Demo data for the dashboard: one believable time window, and no empty projects.

1. Projects older than the window (the Oct 10 development runs) are moved into 31 Oct
   08:30-21:00 IST, with their messages, renders, assets, jobs and timeline versions rescaled
   so order and relative timing are kept.
2. Projects without history (no conversation or no timeline: empty uploads and the standalone
   exports registered by ``register_exports``) get a timeline with an undo step, the source
   assets, and a short conversation derived from what the edit really contains.

Seeded conversations are demo data: every seeded assistant message carries
``tool_calls[].seeded = true`` and the project ids are listed in work/seed-demo-manifest.json.
Idempotent. Targets whichever database ``TIGER_DATABASE_URL`` names (see register_exports).

    python -m scripts.seed_demo_history [--key reelforge-dev-key]
"""

import argparse
import asyncio
import hashlib
import json
import os
import random
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import db as db_ops
from app.api.deps import get_or_create_user_id
from app.settings import get_settings
from app.storage import get_storage
from app.timeline.schema import Timeline
from app.timeline.summary import summarize
from app.timeline.versions import save_version

IST = timezone(timedelta(hours=5, minutes=30))
WINDOW_START = datetime(2026, 10, 31, 8, 30, tzinfo=IST)
WINDOW_END = datetime(2026, 10, 31, 21, 0, tzinfo=IST)
CUTOFF = datetime(2026, 10, 31, 0, 0, tzinfo=IST)
DONOR_NAME = "Software Dev is Dead"  # a complete project made from testInput.mp4
MANIFEST = Path("work/seed-demo-manifest.json")
CHILDREN = (  # (table, timestamp columns, project filter)
    ("messages", ("created_at",), "project_id = $4"),
    ("renders", ("created_at",), "project_id = $4"),
    ("assets", ("created_at",), "project_id = $4"),
    ("public.jobs", ("created_at", "updated_at"), "project_id = $4"),
    ("timelines", ("created_at", "updated_at"), "project_id = $4"),
    ("timeline_versions", ("created_at",), "timeline_id IN (SELECT id FROM timelines WHERE project_id = $4)"),
)  # fmt: skip


async def normalise(db: db_ops.Database, user_id: uuid.UUID) -> int:
    """Rescale pre-window projects into the window; returns how many moved."""
    rows = await db.fetch(
        "SELECT id, created_at FROM projects WHERE user_id=$1 AND created_at < $2 ORDER BY created_at",
        user_id,
        CUTOFF,
    )
    n = len(rows)
    for i, row in enumerate(rows):
        base = WINDOW_START + (WINDOW_END - WINDOW_START) * (i / max(1, n - 1))
        gap = (WINDOW_END - WINDOW_START) / max(1, n - 1)
        latest = await db.fetch(
            "SELECT max(t) AS t FROM (SELECT created_at t FROM messages WHERE project_id=$1 "
            "UNION ALL SELECT created_at FROM renders WHERE project_id=$1 "
            "UNION ALL SELECT updated_at FROM timelines WHERE project_id=$1) x",
            row["id"],
        )
        span = (latest[0]["t"] - row["created_at"]).total_seconds() if latest[0]["t"] else 0.0
        scale = min(1.0, max(gap.total_seconds() * 0.9, 600.0) / span) if span > 0 else 1.0
        for table, cols, where in CHILDREN:
            sets = ", ".join(
                f"{c} = $1::timestamptz + ({c} - $2::timestamptz) * $3::float8" for c in cols
            )
            await db.execute(
                f"UPDATE {table} SET {sets} WHERE {where}",  # noqa: S608 - constants above
                base,
                row["created_at"],
                scale,
                row["id"],
            )
        await db.execute("UPDATE projects SET created_at=$1 WHERE id=$2", base, row["id"])
    return n


ASKS = (
    "Make this a tight reel about: {topic}. Remove the dead air, add word-by-word captions and some relevant visuals.",
    "Turn this into something I can post: cut the pauses, big readable captions, and a few stock or meme inserts on the key points.",
    "Clean up the audio, remove silences and filler words, then add background music with subtle sound effects.",
    "9:16 please. Punchy captions, zooms on the important lines and a couple of B-roll cutaways.",
)
FOLLOW_UPS = (
    ("Captions are good. Can you make the highlight yellow and keep the music quieter under my voice?", "Highlight set to yellow and the music bed lowered by 3 dB."),
    ("A bit busy in the middle. Fewer inserts please, but keep the first one.", "Thinned the inserts to the strongest moments."),
    ("Love it. Add a few sound effects on the zooms.", "Placed short sound effects on each zoom."),
)  # fmt: skip


def features(tl: Timeline) -> list[str]:
    """What the edit really contains, as tool names the Director would have used."""
    tools = ["remove_silence", "reframe_9x16"]
    if tl.captions.mode != "off":
        tools.append("add_captions")
    if tl.overlays:
        tools.append("add_inserts")
    if tl.zooms:
        tools.append("add_zooms")
    if tl.transition != "none":
        tools.append("set_transition")
    if tl.music:
        tools.append("add_music")
    if tl.sfx:
        tools.append("auto_sfx")
    return tools


def topic_of(tl: Timeline) -> str:
    words = [w.text for w in tl.transcript.words[:14]]
    return " ".join(words).rstrip(",;:") + "..."


def story(
    name: str, tl: Timeline, rng: random.Random, render_id: str | None, versions: int
) -> list[tuple[str, str, list[dict[str, object]] | None]]:
    """Multi-turn conversation derived from the edit's real contents (demo data)."""
    tools = features(tl)
    applied = ", ".join(["plan_edit", *tools, "preview"])
    lines = []
    if tl.scenes:
        fam = sorted({sc.content.template.replace("_", " ") for sc in tl.scenes})
        lines.append(f"{len(tl.scenes)} animated scenes ({', '.join(fam[:5])})")
    if tl.overlays:
        lines.append(f"{len(tl.overlays)} inserts")
    if tl.zooms:
        lines.append(f"{len(tl.zooms)} zooms")
    if tl.sfx:
        lines.append(f"{len(tl.sfx)} sound effects")
    if tl.music:
        lines.append("a music bed")
    result = f"Result: {tl.duration_s:.0f} s, " + ", ".join(lines) + "." if lines else ""
    if tl.scenes:
        ask = (
            "Make this an impressive ~60s vertical tech-news short for hackathon judges: split hook "
            "with a real source, line-art diagrams that build on the spoken words, source pages for "
            "claims, icons, one meme beat, small captions, music, SFX, transitions and zooms."
        )
        first = f"Here is what I did.\n\nApplied: {applied.replace('add_inserts', 'make_explainer')}. {result}"
        follow = (
            "The counter should land exactly on the spoken number, and the legacy API scene should turn red as the broken callers are named.",
            "Done. The counter now reveals on the word as it is said and the failing callers switch to red on their cue. New version created.",
        )
    else:
        ask = rng.choice(ASKS).format(topic=topic_of(tl))
        first = f"Here is what I did.\n\nApplied: {applied}. {result}"
        follow = rng.choice(FOLLOW_UPS)
    out: list[tuple[str, str, list[dict[str, object]] | None]] = [
        ("user", ask, None),
        (
            "assistant",
            first,
            [{"name": n, "seeded": True} for n in ["plan_edit", *tools, "preview"]],
        ),
        ("user", follow[0], None),
        (
            "assistant",
            f"{follow[1]} Version {versions} is ready to preview.",
            [{"name": "set_caption_style", "seeded": True}, {"name": "preview", "seeded": True}],
        ),
        ("user", "Looks good. Export the final video.", None),
        (
            "assistant",
            f"export queued (render {render_id})." if render_id else "export queued.",
            [{"name": "export", "seeded": True}],
        ),
    ]
    return out


def rehash_storyboard(tl: Timeline) -> Timeline:
    """Re-stamp the storyboard after clip assets were renamed (the timing hash covers them)."""
    if tl.storyboard is None:
        return tl
    from app.scenes.timing import timing_hash
    from app.storyboard.store import content_hash

    board = tl.storyboard.model_copy(update={"timing_hash": timing_hash(tl)})
    return tl.model_copy(update={"storyboard": board, "storyboard_hash": content_hash(board)})


def as_obj(value):  # type: ignore[no-untyped-def]
    """JSONB comes back decoded from the pool; accept raw text too."""
    return json.loads(value) if isinstance(value, str | bytes) else value


def secs(base: datetime, *deltas: float) -> list[datetime]:
    return [base + timedelta(seconds=d) for d in deltas]


async def seed(db: db_ops.Database, user_id: uuid.UUID, store) -> list[dict[str, str]]:  # type: ignore[no-untyped-def]
    seeded = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else []
    done = {s["project_id"] for s in seeded}
    donor = await db.fetch(
        "SELECT id FROM projects WHERE user_id=$1 AND name=$2", user_id, DONOR_NAME
    )
    if not donor:
        raise SystemExit(f"donor project {DONOR_NAME!r} not found; cannot seed")
    donor_id = donor[0]["id"]
    donor_assets = await db.fetch("SELECT * FROM assets WHERE project_id=$1", donor_id)
    versions = await db.fetch(
        "SELECT v.version, v.edl FROM timeline_versions v JOIN timelines t ON t.id=v.timeline_id "
        "WHERE t.project_id=$1 ORDER BY v.version",
        donor_id,
    )
    donor_first, donor_last = as_obj(versions[0]["edl"]), as_obj(versions[-1]["edl"])
    projects = await db.fetch(
        "SELECT p.id, p.name, p.created_at, "
        "(SELECT count(*) FROM messages m WHERE m.project_id=p.id) AS msgs, "
        "(SELECT count(*) FROM timelines t WHERE t.project_id=p.id) AS tls, "
        "(SELECT count(*) FROM assets a WHERE a.project_id=p.id) AS assets, "
        "(SELECT bool_or((r.quality->>'imported') = 'true') FROM renders r WHERE r.project_id=p.id) AS imported "
        "FROM projects p WHERE p.user_id=$1 ORDER BY p.created_at",
        user_id,
    )
    for p in projects:
        if str(p["id"]) in done or (p["msgs"] > 0 and p["tls"] > 0):
            continue
        pid, base, name = p["id"], p["created_at"], p["name"]
        devday = bool(p["imported"]) and name.startswith("devday")
        if p["assets"] == 0:  # no source media: give it the original upload
            if devday:
                src = Path("work/devday-impact/master.mp4")
                key = f"projects/{pid}/master.mp4"
                dest = store.path_for(key)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    try:
                        os.link(src, dest)
                    except OSError:
                        shutil.copyfile(src, dest)
                sha = hashlib.sha256(src.read_bytes()).hexdigest()
                await db.execute(
                    "INSERT INTO assets (id, created_at, project_id, kind, storage_key, sha256, source, license, "
                    "attribution_required, commercial_use, width, height, duration_ms) "
                    "VALUES ($1,$2,$3,'master',$4,$5,'upload','user-upload',false,true,1920,1080,88000)",
                    uuid.uuid4(), base + timedelta(seconds=20), pid, key, sha,
                )  # fmt: skip
            else:
                for a in donor_assets:
                    await db.execute(
                        "INSERT INTO assets (id, created_at, project_id, kind, storage_key, sha256, source_sha, source, "
                        "license, attribution_required, attribution_text, commercial_use, width, height, duration_ms) "
                        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)",
                        uuid.uuid4(), base + timedelta(seconds=20), pid, a["kind"], a["storage_key"], a["sha256"],
                        a["source_sha"], a["source"], a["license"], a["attribution_required"],
                        a["attribution_text"], a["commercial_use"], a["width"], a["height"], a["duration_ms"],
                    )  # fmt: skip
        if p["tls"] == 0:
            if devday:
                final = json.loads(Path("work/devday-impact/timeline.json").read_text())
                for c in final["video_clips"]:
                    c["asset"] = "master"
                first = json.loads(Path("work/devday-impact/transcript.json").read_text())
                clean = {**final, "scenes": [], "scene_placements": [], "storyboard": None,
                         "storyboard_hash": None, "overlays": [], "sfx": [], "music": None, "zooms": [],
                         "video_clips": [{"id": "c1", "asset": "master", "src_in": 0.0,
                                          "src_out": first["words"][-1]["end"] + 0.2}]}  # fmt: skip
            else:
                final, clean = donor_last, donor_first
                if "split" in name.lower() or "split" in (p["name"] or "").lower():
                    final = {**final, "reframe": "split_bottom"}
            if devday:
                stages = [
                    clean,
                    {**final, "scenes": [], "scene_placements": [], "storyboard": None, "storyboard_hash": None,
                     "overlays": [], "sfx": [], "zooms": []},
                    {**final, "overlays": [], "sfx": [], "zooms": []},
                    final,
                ]  # fmt: skip
            else:
                stages = [as_obj(v["edl"]) for v in versions]
                if "split" in name.lower():
                    stages[-1] = {**stages[-1], "reframe": "split_bottom"}
            row_id = uuid.uuid4()
            await db.execute(
                "INSERT INTO timelines (id, created_at, project_id, current_version, updated_at) VALUES ($1,$2,$3,0,$2)",
                row_id, base + timedelta(seconds=40), pid,
            )  # fmt: skip
            tl = None
            for n, edl in enumerate(stages, start=1):
                tl = Timeline.model_validate({**edl, "project_id": str(pid), "version": n})
                if devday:
                    tl = rehash_storyboard(tl)
                await save_version(db, row_id, tl, parent=None if n == 1 else n - 1)
            span = 380.0
            when = [
                base + timedelta(seconds=45 + span * k / max(1, len(stages) - 1))
                for k in range(len(stages))
            ]
            for n, t in enumerate(when, start=1):
                await db.execute(
                    "UPDATE timeline_versions SET created_at=$1 WHERE timeline_id=$2 AND version=$3",
                    t,
                    row_id,
                    n,
                )
            await db.execute(
                "UPDATE timelines SET created_at=$1, updated_at=$2 WHERE id=$3",
                when[0],
                when[-1],
                row_id,
            )
            assert tl is not None
            n_versions = len(stages)
        else:
            row = await db.fetch(
                "SELECT v.edl FROM timeline_versions v JOIN timelines t ON t.id=v.timeline_id "
                "WHERE t.project_id=$1 ORDER BY v.version DESC LIMIT 1",
                pid,
            )
            tl = Timeline.model_validate(as_obj(row[0]["edl"]))
            n_versions = int(tl.version)
        if p["msgs"] == 0:
            rid = await db.fetch(
                "SELECT id FROM renders WHERE project_id=$1 AND profile='final' AND status='done' ORDER BY created_at DESC LIMIT 1",
                pid,
            )
            turns = story(
                name, tl, random.Random(str(pid)), str(rid[0]["id"]) if rid else None, n_versions
            )
            t = base + timedelta(seconds=90)
            for role, content, calls in turns:
                t += timedelta(
                    seconds=random.Random(f"{pid}{content[:8]}").randint(8, 70)
                    if role == "assistant"
                    else random.Random(f"{pid}{content[:6]}").randint(35, 160)
                )
                await db.execute(
                    "INSERT INTO messages (id, created_at, project_id, role, content, tool_calls) VALUES ($1,$2,$3,$4,$5,$6)",
                    uuid.uuid4(), t, pid, role, content, calls,
                )  # fmt: skip
        seeded.append(
            {"project_id": str(pid), "name": name, "summary": summarize(tl).splitlines()[0]}
        )
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(seeded, indent=2))
    return seeded


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default="reelforge-dev-key")
    ap.add_argument(
        "--adopt-all", action="store_true", help="move every workspace's projects here first"
    )
    ap.add_argument("--reseed", action="store_true", help="redo the projects in the manifest")
    args = ap.parse_args()
    db = db_ops.get_db(get_settings())
    user_id = await get_or_create_user_id(db, args.key)
    if args.adopt_all:
        print(
            "adopted:",
            await db.execute("UPDATE projects SET user_id=$1 WHERE user_id<>$1", user_id),
        )
    if args.reseed and MANIFEST.exists():
        for item in json.loads(MANIFEST.read_text()):
            pid = uuid.UUID(item["project_id"])
            await db.execute("DELETE FROM messages WHERE project_id=$1", pid)
            await db.execute(
                "DELETE FROM timeline_versions WHERE timeline_id IN (SELECT id FROM timelines WHERE project_id=$1)",
                pid,
            )
            await db.execute("DELETE FROM timelines WHERE project_id=$1", pid)
        MANIFEST.write_text("[]")
    moved = await normalise(db, user_id)
    print(f"moved {moved} older projects into 31 Oct 2026")
    seeded = await seed(db, user_id, get_storage(get_settings()))
    print(f"{len(seeded)} projects have seeded history (see {MANIFEST})")


if __name__ == "__main__":
    asyncio.run(main())
