"""Register finished edits that were made outside the app (editedVideo/*.mp4) in the database.

Each file becomes a project plus a finished render, so it appears on the Studio dashboard
(Gallery) with its poster, download and credits. Idempotent: a file already registered (same
content hash) is skipped. Renders made through the app are stored by the worker already.

    python -m scripts.register_exports [--key reelforge-dev-key] [--dir editedVideo]
"""

import argparse
import asyncio
import hashlib
import shutil
import uuid
from pathlib import Path

from app import db as db_ops
from app.api.deps import get_or_create_user_id
from app.media.probe import probe_file
from app.models import Project, Render
from app.settings import get_settings
from app.storage import get_storage


def credits_for(video: Path) -> list[str]:
    """Credits next to the project that produced the video (work/<name>/credits.txt)."""
    stem = video.stem
    for suffix in ("-final", "-preview", "-reviewed"):
        stem = stem.removesuffix(suffix)
    for candidate in (
        Path("work") / stem / "credits.txt",
        Path("work") / video.stem / "credits.txt",
    ):
        if candidate.is_file():
            return [line for line in candidate.read_text().splitlines() if line.strip()]
    return []


def scan(folder: Path) -> list[tuple[Path, str]]:
    """Top-level videos with their content hash (app renders live in subfolders)."""
    return [
        (v, hashlib.sha256(v.read_bytes()).hexdigest()[:16]) for v in sorted(folder.glob("*.mp4"))
    ]


def place(video: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(video, dest)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default="reelforge-dev-key", help="workspace key (X-API-Key)")
    ap.add_argument("--dir", default="editedVideo")
    ap.add_argument("--adopt", default="", help="also move another workspace key's projects here")
    args = ap.parse_args()
    db = db_ops.get_db(get_settings())
    store = get_storage(get_settings())
    user_id = await get_or_create_user_id(db, args.key)
    if args.adopt:
        other = await get_or_create_user_id(db, args.adopt)
        if other != user_id:
            moved = await db.execute(
                "UPDATE projects SET user_id = $1 WHERE user_id = $2", user_id, other
            )
            print(f"adopted projects from {args.adopt!r}: {moved}")
    known: set[str] = set()
    for project in await db_ops.find(db, Project, {"user_id": user_id}):
        for r in await db_ops.find(db, Render, {"project_id": project.id}):
            if r.quality.get("imported"):
                known.add(r.timeline_hash)
    added = 0
    for video, sha in await asyncio.to_thread(scan, Path(args.dir)):
        if sha in known:
            continue
        info = probe_file(str(video))
        project = await db_ops.insert(
            db, Project(user_id=user_id, name=video.stem.replace("-", " ").replace("_", " "))
        )
        key = f"renders/{project.id}/{video.name}"
        await asyncio.to_thread(place, video, store.path_for(key))
        await db_ops.insert(
            db,
            Render(
                project_id=project.id,
                timeline_version_id=uuid.UUID(int=0),  # made outside the app: no timeline version
                timeline_hash=sha,
                profile="preview" if "preview" in video.stem else "final",
                status="done",
                output_url=store.public_url(key),
                output_key=key,
                attributions=credits_for(video),
                quality={
                    "imported": True,
                    "duration_s": round(info.duration_s, 2),
                    "width": info.width,
                    "height": info.height,
                    "size_bytes": video.stat().st_size,
                },
            ),
        )
        added += 1
        print(f"registered {video.name} ({info.duration_s:.1f}s, {info.width}x{info.height})")
    print(f"{added} new, {len(known)} already registered")


if __name__ == "__main__":
    asyncio.run(main())
