"""Timeline versioning: pure pointer log + Postgres persistence.

Undo/redo are pointer moves on timelines.current_version (MongoDB). Edit-after-undo
appends a new version whose parent is the pointer (old redo chain kept, unreachable).
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app import db as db_ops
from app.db import Database
from app.models import Timeline as TimelineDoc
from app.models import TimelineVersion as TimelineVersionDoc
from app.timeline.schema import Timeline


def _now() -> datetime:
    return datetime.now(UTC)


def redo_target(current: int, links: list[tuple[int, int | None]]) -> int | None:
    """Newest version whose parent is ``current`` (the branch made most recently)."""
    children = [v for v, parent in links if parent == current]
    return max(children) if children else None


@dataclass(frozen=True)
class VersionEntry:
    """One immutable snapshot reference."""

    version: int
    parent: int | None
    edl: dict[str, Any]


@dataclass(frozen=True)
class VersionLog:
    """Pure undo/redo log. All methods return new logs (immutable)."""

    entries: tuple[VersionEntry, ...] = field(default_factory=tuple)
    current: int = 0

    def append(self, tl: Timeline) -> "VersionLog":
        """Append a snapshot; parent = current pointer (None for v1)."""
        existing = [e.version for e in self.entries]
        version = (max(existing) if existing else 0) + 1
        parent = self.current or None
        entry = VersionEntry(version=version, parent=parent, edl=tl.model_dump(mode="json"))
        return VersionLog(entries=(*self.entries, entry), current=version)

    def undo(self) -> "VersionLog":
        """Move pointer to the current version's parent (no-op at the root)."""
        parent = self.parent_of(self.current)
        if parent is None:
            return self
        return VersionLog(entries=self.entries, current=parent)

    def redo(self) -> "VersionLog":
        """Move pointer to the newest child of the current version (no-op without one)."""
        target = redo_target(self.current, [(e.version, e.parent) for e in self.entries])
        if target is None:
            return self
        return VersionLog(entries=self.entries, current=target)

    def get(self, version: int) -> VersionEntry | None:
        """Fetch an entry by version number."""
        return next((e for e in self.entries if e.version == version), None)

    def parent_of(self, version: int) -> int | None:
        """Parent version number (None for v1)."""
        entry = self.get(version)
        return entry.parent if entry else None


async def save_version(
    db: Database,
    timeline_id: uuid.UUID,
    tl: Timeline,
    parent: int | None,
    *,
    expected_parent: int | None = None,
) -> tuple[int, Timeline]:
    """Persist an EDL snapshot stamped with its version; bump the current pointer.

    Row locking serializes allocation and pointer updates. expected_parent rejects
    edits based on a stale user revision. The unique index remains a final safeguard.
    """
    # Every writer takes the same row lock, including legacy tools. This prevents a
    # later unguarded writer from restoring an old pointer after a guarded scene patch.
    pool = await db.pool()
    async with pool.acquire() as conn, conn.transaction():
        current = await conn.fetchval(
            "SELECT current_version FROM timelines WHERE id=$1 FOR UPDATE", timeline_id
        )
        if current is None:
            raise ValueError(f"timeline {timeline_id} does not exist")
        if expected_parent is not None and current != expected_parent:
            raise ValueError(f"stale revision {expected_parent}; current version is {current}")
        version = await conn.fetchval(
            "SELECT COALESCE(MAX(version),0)+1 FROM timeline_versions WHERE timeline_id=$1",
            timeline_id,
        )
        stamped = tl.model_copy(update={"version": version})
        await conn.execute(
            "INSERT INTO timeline_versions (id,timeline_id,version,edl,parent_version) "
            "VALUES ($1,$2,$3,$4,$5)",
            uuid.uuid4(),
            timeline_id,
            version,
            stamped.model_dump(mode="json"),
            parent,
        )
        await conn.execute(
            "UPDATE timelines SET current_version=$2,updated_at=$3 WHERE id=$1",
            timeline_id,
            version,
            _now(),
        )
        return version, stamped


async def load_version(db: Database, timeline_id: uuid.UUID, version: int) -> Timeline:
    """Load one snapshot as a Timeline."""
    row = await db_ops.find_one(
        db, TimelineVersionDoc, {"timeline_id": timeline_id, "version": version}
    )
    if row is None:
        raise ValueError(f"timeline {timeline_id} has no version {version}")
    return Timeline.model_validate(row.edl)


async def list_versions(db: Database, timeline_id: uuid.UUID) -> list[VersionEntry]:
    """All snapshots for a timeline, oldest first."""
    rows = await db_ops.find(
        db, TimelineVersionDoc, {"timeline_id": timeline_id}, sort=[("version", 1)]
    )
    return [VersionEntry(version=r.version, parent=r.parent_version, edl=dict(r.edl)) for r in rows]


async def get_current(db: Database, timeline_id: uuid.UUID) -> int:
    """Current version pointer."""
    row = await db_ops.get(db, TimelineDoc, timeline_id)
    if row is None:
        raise ValueError(f"timeline {timeline_id} does not exist")
    return row.current_version


async def set_current(db: Database, timeline_id: uuid.UUID, version: int) -> None:
    """Move the pointer (undo/redo) without deleting history."""
    exists = await db_ops.find_one(
        db, TimelineVersionDoc, {"timeline_id": timeline_id, "version": version}
    )
    if exists is None:
        raise ValueError(f"timeline {timeline_id} has no version {version}")
    await db_ops.update(
        db, TimelineDoc, timeline_id, {"current_version": version, "updated_at": _now()}
    )


async def undo(db: Database, timeline_id: uuid.UUID) -> int:
    """Move the pointer to the current version's parent; return the version now current."""
    current = await get_current(db, timeline_id)
    entry = await db_ops.find_one(
        db, TimelineVersionDoc, {"timeline_id": timeline_id, "version": current}
    )
    target = entry.parent_version if entry and entry.parent_version else current
    if target != current:
        await set_current(db, timeline_id, target)
    return target


async def redo(db: Database, timeline_id: uuid.UUID) -> int:
    """Move the pointer to the newest child of the current version; return it."""
    current = await get_current(db, timeline_id)
    links = [(e.version, e.parent) for e in await list_versions(db, timeline_id)]
    target = redo_target(current, links) or current
    if target != current:
        await set_current(db, timeline_id, target)
    return target
