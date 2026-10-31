"""Creator memory API: the visible-context panel (Meko Track A, A4; ADR-030).

GET    /meko/status                                  is memory on, which datapack prefix
GET    /meko/creators/{creator}/memories             everything remembered, by zone
POST   /meko/creators/{creator}/memories             "Remember this" (explicit correction)
PATCH  /meko/creators/{creator}/memories/{id}        correct a memory's text
DELETE /meko/creators/{creator}/memories/{id}        forget it
POST   /meko/creators/{creator}/memories/{id}/approve  human promotion to creator canon
POST   /meko/agency/lessons                          human-approved lesson for every editor
GET    /meko/calls                                   every Meko call this process made

All routes require the same X-API-Key as the rest of the app. Only what a real Meko call
returned is shown (A5); the call log is written by the adapter, never by these routes.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.api.deps import UserDep
from app.memory.models import SOURCE_LABEL, RecalledItem
from app.memory.service import CreatorMemory, MemoryInputError
from app.providers.meko import MekoError
from app.providers.registry import creator_memory, meko_call_log
from app.settings import get_settings

router = APIRouter(prefix="/meko")

Creator = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")]
AgentId = Literal["clipz:director", "clipz:curator"]


def get_creator_memory() -> CreatorMemory | None:
    """Dependency (overridden in tests)."""
    return creator_memory()


def _require(memory: CreatorMemory | None) -> CreatorMemory:
    if memory is None:
        raise HTTPException(503, "creator memory is off: set MEKO_API_KEY")
    return memory


MemoryDep = Annotated[CreatorMemory | None, Depends(get_creator_memory)]


class MemoryText(BaseModel):
    """A fact to remember or the corrected text of one."""

    text: str = Field(min_length=1, max_length=300, description="One short preference or fact")


class AgentRef(BaseModel):
    """Which private bucket a memory lives in."""

    agent_id: AgentId = Field(
        default="clipz:curator", description="clipz:director or clipz:curator"
    )


class EditBody(MemoryText, AgentRef):
    """New text for a memory in a given bucket."""


def _row(r: RecalledItem) -> dict[str, Any]:
    return {
        "id": r.item.id,
        "text": r.item.text,
        "source": r.source,
        "label": SOURCE_LABEL[r.source],
        "scope": r.scope,
        "agent_id": r.item.agent_id,
        "promoted": r.item.promoted,
    }


async def _guard(coro: Any) -> Any:
    try:
        return await coro
    except MemoryInputError as exc:
        raise HTTPException(422, str(exc)) from exc
    except MekoError as exc:
        raise HTTPException(502, f"Meko call failed: {exc}") from exc


@router.get("/status")
async def status(memory: MemoryDep, _: UserDep) -> dict[str, object]:
    """Whether creator memory is configured."""
    return {"enabled": memory is not None, "prefix": get_settings().MEKO_DATAPACK_PREFIX}


@router.get("/creators/{creator}/memories")
async def list_memories(creator: Creator, memory: MemoryDep, _: UserDep) -> dict[str, object]:
    """Everything remembered for ``creator``: private, creator canon, agency canon."""
    zones = await _guard(_require(memory).panel(creator))
    return {zone: [_row(r) for r in rows] for zone, rows in zones.items()}


@router.post("/creators/{creator}/memories", status_code=201)
async def remember(
    creator: Creator, body: MemoryText, memory: MemoryDep, _: UserDep
) -> dict[str, object]:
    """Store an explicit correction for ``creator``."""
    rows = await _guard(_require(memory).remember(creator, body.text))
    return {"stored": [{"id": r.id, "text": r.text, "agent_id": r.agent_id} for r in rows]}


@router.patch("/creators/{creator}/memories/{memory_id}")
async def edit(
    creator: Creator, memory_id: str, body: EditBody, memory: MemoryDep, _: UserDep
) -> dict[str, object]:
    """Correct a remembered fact."""
    await _guard(_require(memory).edit(creator, body.agent_id, memory_id, body.text))
    return {"ok": True}


@router.delete("/creators/{creator}/memories/{memory_id}")
async def forget(
    creator: Creator,
    memory_id: str,
    memory: MemoryDep,
    _: UserDep,
    agent_id: Annotated[AgentId, Query()] = "clipz:director",
) -> dict[str, object]:
    """Forget one private memory."""
    await _guard(_require(memory).forget(creator, agent_id, memory_id))
    return {"ok": True}


@router.post("/creators/{creator}/memories/{memory_id}/approve")
async def approve(
    creator: Creator, memory_id: str, body: AgentRef, memory: MemoryDep, _: UserDep
) -> dict[str, object]:
    """A person approves a memory: promoted into this creator's canon for every editor."""
    done = await _guard(_require(memory).approve(creator, body.agent_id, memory_id))
    return {"promoted": done}


@router.post("/agency/lessons", status_code=201)
async def share(body: MemoryText, memory: MemoryDep, _: UserDep) -> dict[str, object]:
    """A person approves a lesson for the whole agency (all creators, all editors)."""
    done = await _guard(_require(memory).share_with_agency(body.text))
    return {"promoted": done}


@router.get("/calls")
async def calls(
    _: UserDep,
    since: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> dict[str, object]:
    """Every Meko call this process made, oldest first, plus per-kind counters."""
    log = meko_call_log()
    return {
        "calls": [c.model_dump(mode="json") for c in log.since(since, limit)],
        "counters": log.counters(),
    }
