"""Deterministic fake providers for unit tests and local dev without keys."""

from collections.abc import Callable

from app.memory.calllog import CallLog
from app.memory.models import MekoCall, MemoryItem
from app.providers.base import (
    Candidate,
    ChatReply,
    ChatRequest,
    MemeTemplate,
    MusicSearchQuery,
    MusicTrack,
    SfxClip,
    VisualQuery,
)
from app.providers.tools import TextSink, ToolTurnReply, ToolTurnRequest


class FakeLLMProvider:
    """Scripted LLM: echoes the last user message (tests override per-case in Phase 5)."""

    provider_name = "fake-llm"

    async def complete(self, request: ChatRequest) -> ChatReply:
        last_user = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
        return ChatReply(text=f"[fake-llm] {last_user}", model="fake", tokens_used=7)


class FakeMusicProvider:
    """One deterministic licensed track per search."""

    provider_name = "fake-music"

    async def search(self, query: MusicSearchQuery) -> list[MusicTrack]:
        return [
            MusicTrack(
                id="fake:upbeat-bed-01",
                title=f"Fake {query.mood} bed",
                url="https://example.com/fake-bed.mp3",
                duration_s=float(query.duration_s),
                license="CC0-1.0",
                attribution_required=False,
            )
        ]

    async def download(self, track_id: str) -> bytes:
        return f"FAKE-MP3:{track_id}".encode()


class FakeImageProvider:
    """Deterministic licensed image candidates."""

    provider_name = "fake-image"

    async def search(self, query: VisualQuery) -> list[Candidate]:
        return [
            Candidate(
                id=f"fake-img:{i}",
                kind="image",
                source="fake-image",
                url=f"https://example.com/img{i}.jpg",
                width=1080,
                height=1920,
                license="CC0-1.0",
                attribution_required=False,
                tags=[query.query, query.tone],
            )
            for i in range(min(query.count, 3))
        ]


class FakeGifProvider:
    """Deterministic licensed GIF candidates."""

    provider_name = "fake-gif"

    async def search(self, query: VisualQuery) -> list[Candidate]:
        return [
            Candidate(
                id=f"fake-gif:{i}",
                kind="gif",
                source="fake-gif",
                url=f"https://example.com/anim{i}.gif",
                width=480,
                height=270,
                license="CC0-1.0",
                attribution_required=False,
                tags=[query.query],
            )
            for i in range(min(query.count, 3))
        ]


class FakeMemeTemplateProvider:
    """One built-in template with caption rendering."""

    provider_name = "fake-meme"

    async def list_templates(self, limit: int = 50) -> list[MemeTemplate]:
        return [
            MemeTemplate(
                id="fake:drake",
                name="Fake Drake",
                url="https://example.com/drake.jpg",
                license="CC0-1.0",
                attribution_required=False,
            )
        ][:limit]

    async def render_captioned(
        self, template_id: str, top_text: str, bottom_text: str
    ) -> Candidate:
        _ = (top_text, bottom_text)
        return Candidate(
            id=f"{template_id}:captioned",
            kind="meme",
            source="fake-meme",
            url=f"https://example.com/{template_id}-captioned.jpg",
            width=1080,
            height=1080,
            license="CC0-1.0",
            attribution_required=False,
        )


class FakeSfxProvider:
    """Deterministic SFX clips."""

    provider_name = "fake-sfx"

    async def search(self, hint: str, limit: int = 5) -> list[SfxClip]:
        return [
            SfxClip(
                id=f"fake-sfx:{hint}_{i}",
                name=f"Fake {hint} {i}",
                url=f"https://example.com/{hint}{i}.wav",
                duration_s=0.4,
                license="CC0-1.0",
                attribution_required=False,
            )
            for i in range(min(limit, 2))
        ]

    async def download(self, clip_id: str) -> bytes:
        return f"FAKE-WAV:{clip_id}".encode()


class ScriptedToolLLM:
    """ToolCallingLLM that replays scripted turns and records every request.

    Each script entry is a ToolTurnReply or a function of the request (to react to
    tool results). Running past the script ends the turn with no calls.
    """

    provider_name = "scripted"

    def __init__(
        self,
        script: "list[ToolTurnReply | Callable[[ToolTurnRequest], ToolTurnReply]]",
        model: str = "scripted",
    ) -> None:
        self.model = model
        self.script = list(script)
        self.requests: list[ToolTurnRequest] = []

    async def complete_with_tools(
        self, request: ToolTurnRequest, on_text: TextSink | None = None
    ) -> ToolTurnReply:
        """Pop the next scripted turn; stream its text to ``on_text``."""
        self.requests.append(request)
        step = self.script.pop(0) if self.script else ToolTurnReply(text="(script ended)")
        reply = step(request) if callable(step) else step
        if on_text is not None and reply.text:
            on_text(reply.text)
        return reply.model_copy(update={"model": reply.model or self.model})


class FakeContextProvider:
    """In-memory ContextProvider: same zones as Meko (private per agent, promoted per scope).

    ``add_turn`` "extracts" the user text as one memory when it reads like a preference,
    so the ON/OFF demo works offline. Every call is logged like the real adapter.
    """

    provider_name = "fake-context"

    def __init__(self, log: CallLog | None = None) -> None:
        self.log = log or CallLog()
        self.rows: dict[str, dict[str, MemoryItem]] = {}  # scope -> id -> item
        self._next = 0

    def _rec(self, tool: str, kind: str, scope: str, agent: str | None, n: int = 0) -> None:
        self.log.record(MekoCall(tool=tool, kind=kind, scope=scope, agent_id=agent, results=n))  # type: ignore[arg-type]

    async def scope(self, name: str) -> str:
        self.rows.setdefault(name, {})
        return f"dp-{name}"

    async def thread(self, scope: str, agent_id: str = "clipz") -> str:
        return f"conv-{scope}"

    async def list_memories(
        self, scope: str, agent_id: str | None, promoted: bool
    ) -> list[MemoryItem]:
        rows = [
            m
            for m in self.rows.get(scope, {}).values()
            if m.promoted == promoted  # like Meko: not filtered by agent_id
        ]
        self._rec("memory_get_all", "recall", scope, agent_id, len(rows))
        return [m.model_copy() for m in rows]

    async def search_shared(self, scope: str, query: str, limit: int = 5) -> list[MemoryItem]:
        words = {w for w in query.lower().split() if len(w) > 3}
        hits = [
            m
            for m in self.rows.get(scope, {}).values()
            if m.promoted and words & set(m.text.lower().split())
        ][:limit]
        self._rec("knowledgebase_search", "recall", scope, None, len(hits))
        return [m.model_copy() for m in hits]

    async def add_memory(self, scope: str, agent_id: str, text: str) -> list[MemoryItem]:
        self._next += 1
        item = MemoryItem(id=f"m{self._next}", text=text, agent_id=agent_id)
        self.rows.setdefault(scope, {})[item.id] = item
        self._rec("memory_add", "write", scope, agent_id, 1)
        return [item.model_copy()]

    async def add_turn(
        self, scope: str, agent_id: str, user: str, reply: str, seed: bool = False
    ) -> str:
        self._rec("conversation_add_message", "write", scope, agent_id, 1)
        cues = ("never", "always", "don't", "dont", "prefer", "keep", "no ", "use ", "make ")
        if any(c in user.lower() for c in cues):
            self._next += 1
            item = MemoryItem(id=f"m{self._next}", text=user.strip(), agent_id=agent_id)
            self.rows.setdefault(scope, {})[item.id] = item
        return await self.thread(scope, agent_id)

    async def update_memory(self, scope: str, agent_id: str, memory_id: str, text: str) -> None:
        self.rows[scope][memory_id].text = text
        self._rec("memory_update", "edit", scope, agent_id, 1)

    async def delete_memory(self, scope: str, agent_id: str, memory_id: str) -> None:
        self.rows.get(scope, {}).pop(memory_id, None)
        self._rec("memory_delete_by_id", "forget", scope, agent_id, 1)

    async def promote(self, scope: str, agent_id: str, memory_ids: list[str]) -> list[str]:
        done = [i for i in memory_ids if i in self.rows.get(scope, {})]
        for i in done:
            self.rows[scope][i].promoted = True
        self._rec("memory_promote", "promote", scope, agent_id, len(done))
        return done
