"""Creator-memory models: what was recalled, what was stored, and every context call made.

Vendor-neutral: the Meko adapter maps MCP responses onto these; tests use them with fakes.
Memory text is UNTRUSTED DATA (rule 6): it shapes style choices, never tool arguments verbatim.
"""

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")

DIRECTOR = "clipz:director"  # preferences Meko extracts from the creator's chat turns
CURATOR = "clipz:curator"  # explicit corrections and human-approved lessons

Source = Literal["style", "correction", "creator_canon", "agency_canon", "brand_doc"]

SOURCE_LABEL: dict[Source, str] = {
    "style": "learned from chat",
    "correction": "explicit correction",
    "creator_canon": "approved for this creator",
    "agency_canon": "agency canon",
    "brand_doc": "brand guideline",
}


class MemoryItem(BaseModel):
    """One remembered fact, as a context provider returned it."""

    id: str = Field(description="Provider memory or chunk id")
    text: str = Field(description="The fact, verbatim from the provider")
    agent_id: str | None = Field(default=None, description="Agent that wrote it")
    promoted: bool = Field(default=False, description="In the shared (institutional) zone")
    score: float | None = Field(default=None, description="Search relevance, when searched")


class RecalledItem(BaseModel):
    """A memory placed in a recall section, with where it came from."""

    source: Source
    scope: str = Field(description="Datapack name it came from")
    item: MemoryItem


class Recall(BaseModel):
    """Everything recalled for one Director turn. ``enabled=False`` is Meko OFF."""

    enabled: bool
    creator: str | None = None
    items: list[RecalledItem] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list, description="Calls that failed or timed out")
    ms: int = 0

    def count(self, source: Source) -> int:
        """How many recalled items came from ``source``."""
        return sum(1 for r in self.items if r.source == source)


class MekoCall(BaseModel):
    """One logged context-provider call (drives the visible-context panel, A4)."""

    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tool: str = Field(description="MCP tool name, e.g. memory_get_all")
    kind: Literal["write", "recall", "promote", "share", "forget", "edit", "setup"]
    scope: str = Field(description="Datapack name")
    agent_id: str | None = None
    ok: bool = True
    ms: int = 0
    results: int = Field(default=0, description="Rows returned or written")
    detail: str = Field(default="", description="Short, non-sensitive summary")


class StoredTurn(BaseModel):
    """What one chat turn wrote to memory."""

    creator: str
    scope: str
    conversation_id: str
