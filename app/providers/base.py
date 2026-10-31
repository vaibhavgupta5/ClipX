"""Provider contracts. Business logic depends on these Protocols, never on vendor SDKs.

Real adapters land in Phases 5 (LLM), 6 (music, sfx), 7 (image, gif, meme).
Phase 0 ships the contracts + deterministic fakes for tests.
"""

import io
from typing import Literal, Protocol, runtime_checkable

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, model_validator

from app.memory.models import MemoryItem


# --- LLM ---
class ImagePart(BaseModel):
    """Validated local pixels; never a remotely fetched model URL."""

    data: bytes = Field(min_length=1, max_length=5_000_000, repr=False)
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]

    @model_validator(mode="after")
    def validate_pixels(self) -> "ImagePart":
        try:
            with Image.open(io.BytesIO(self.data)) as image:
                if Image.MIME.get(image.format or "") != self.mime_type:
                    raise ValueError("image MIME does not match its bytes")
                if image.width * image.height > 2_000_000:
                    raise ValueError("review images must be at most two megapixels")
                image.verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("invalid image bytes") from exc
        return self

    @property
    def pixels(self) -> int:
        with Image.open(io.BytesIO(self.data)) as image:
            return image.width * image.height


class ChatMessage(BaseModel):
    """One chat turn. Content is UNTRUSTED DATA (rule 6) once it echoes media/API text."""

    role: Literal["system", "user", "assistant"] = Field(description="Message role")
    content: str = Field(description="Message text")
    images: list[ImagePart] = Field(default_factory=list, max_length=36)


class ChatRequest(BaseModel):
    """LLM completion request (tools omitted here; tool schemas live in app/tools, Phase 5)."""

    messages: list[ChatMessage] = Field(description="Conversation turns")
    max_tokens: int = Field(default=1024, ge=1, description="Response token cap")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0, description="Sampling temperature")

    @model_validator(mode="after")
    def media_budget(self) -> "ChatRequest":
        images = [image for m in self.messages for image in m.images]
        if len(images) > 36 or sum(image.pixels for image in images) > 15_000_000:
            raise ValueError("media budget exceeded (36 images / 15 MP)")
        if sum(len(image.data) for image in images) > 12_000_000:
            raise ValueError("inline media byte budget exceeded")
        if any(m.images and m.role != "user" for m in self.messages):
            raise ValueError("media belongs in an untrusted user-data message")
        return self


class ChatReply(BaseModel):
    """LLM completion response."""

    text: str = Field(description="Assistant text")
    model: str = Field(default="", description="Model that produced the reply")
    tokens_used: int = Field(default=0, ge=0, description="Input+output tokens consumed")


@runtime_checkable
class LLMProvider(Protocol):
    """Text completion model (Gemini; fakes in tests)."""

    provider_name: str

    async def complete(self, request: ChatRequest) -> ChatReply:
        """Return one assistant reply for the conversation."""
        ...


# --- Music ---
class MusicSearchQuery(BaseModel):
    """Music search criteria for reel beds."""

    mood: str = Field(description="Free-text mood, e.g. 'upbeat', 'lofi'")
    energy: float = Field(default=0.5, ge=0.0, le=1.0, description="0 calm .. 1 intense")
    bpm: int | None = Field(default=None, description="Target tempo, if known")
    genre: str | None = Field(default=None, description="Library genre label, e.g. 'lofi'")
    duration_s: int = Field(default=30, ge=1, le=90, description="Needed bed length (<= 90 s cap)")


class MusicTrack(BaseModel):
    """Licensed music track. License fields mandatory (rule 7)."""

    id: str = Field(description="Provider-scoped track id")
    title: str = Field(description="Track title")
    url: str = Field(description="Download/stream URL")
    duration_s: float = Field(description="Full track length in seconds")
    license: str = Field(description="License identifier, e.g. 'CC-BY-4.0'")
    attribution_required: bool = Field(description="Whether exports must credit the track")
    attribution_text: str = Field(default="", description="Paste-ready credit line")
    genre: str = Field(default="", description="Library genre label")
    commercial_use: bool = Field(default=True, description="False = personal use only")


@runtime_checkable
class MusicProvider(Protocol):
    """Royalty-safe music bed source (chosen in Phase 6)."""

    provider_name: str

    async def search(self, query: MusicSearchQuery) -> list[MusicTrack]:
        """Return candidate tracks matching the query."""
        ...

    async def download(self, track_id: str) -> bytes:
        """Download the full track audio bytes."""
        ...


# --- Visual candidates (images, GIFs, meme templates share one model) ---
class Candidate(BaseModel):
    """Normalized visual candidate from any source (Phase 7 ranker input)."""

    id: str = Field(description="Provider-scoped id, e.g. 'giphy:abc123'")
    kind: Literal["image", "gif", "meme", "generated", "card"] = Field(description="Asset kind")
    source: str = Field(description="Provider name")
    url: str = Field(description="Full asset URL")
    thumb_url: str = Field(default="", description="Thumbnail URL (may equal url)")
    width: int = Field(default=0, ge=0, description="Pixel width (0 = unknown)")
    height: int = Field(default=0, ge=0, description="Pixel height (0 = unknown)")
    license: str = Field(description="License identifier")
    attribution_required: bool = Field(description="Whether exports must credit the asset")
    tags: list[str] = Field(default_factory=list, description="Tone/content tags")
    attribution_text: str = Field(default="", description="Paste-ready credit line")
    commercial_use: bool = Field(default=True, description="False = personal use only")


class VisualQuery(BaseModel):
    """Candidate search criteria."""

    query: str = Field(description="Short search query, e.g. 'money burning'")
    count: int = Field(default=5, ge=1, le=20, description="Max candidates to return")
    tone: str = Field(default="", description="Tone tag: sarcastic, shocked, celebratory...")


@runtime_checkable
class ImageProvider(Protocol):
    """Stock photo/video source (chosen in Phase 7)."""

    provider_name: str

    async def search(self, query: VisualQuery) -> list[Candidate]:
        """Return image candidates."""
        ...


@runtime_checkable
class GifProvider(Protocol):
    """Reaction GIF/sticker source (chosen in Phase 7)."""

    provider_name: str

    async def search(self, query: VisualQuery) -> list[Candidate]:
        """Return GIF/sticker candidates."""
        ...


class MemeTemplate(BaseModel):
    """Classic meme template (Imgflip-style: id + caption boxes)."""

    id: str = Field(description="Provider-scoped template id")
    name: str = Field(description="Template name")
    url: str = Field(description="Blank template image URL")
    license: str = Field(description="License identifier")
    attribution_required: bool = Field(description="Whether exports must credit the source")
    commercial_use: bool = Field(default=True, description="False = personal use only")
    text_boxes: int = Field(default=2, ge=1, description="Caption boxes the template expects")


@runtime_checkable
class MemeTemplateProvider(Protocol):
    """Meme-template API with caption rendering (chosen in Phase 7)."""

    provider_name: str

    async def list_templates(self, limit: int = 50) -> list[MemeTemplate]:
        """List available templates."""
        ...

    async def render_captioned(
        self, template_id: str, top_text: str, bottom_text: str
    ) -> Candidate:
        """Render top/bottom-text meme; returns a licensed Candidate."""
        ...


# --- SFX ---
class SfxClip(BaseModel):
    """Short sound effect hit."""

    id: str = Field(description="Provider-scoped clip id, e.g. 'sfx:pop_03'")
    name: str = Field(description="Clip name")
    url: str = Field(description="Download URL")
    duration_s: float = Field(description="Clip length in seconds")
    license: str = Field(description="License identifier")
    attribution_required: bool = Field(description="Whether exports must credit the clip")


@runtime_checkable
class SfxProvider(Protocol):
    """Whoosh/pop/riser source (chosen in Phase 6)."""

    provider_name: str

    async def search(self, hint: str, limit: int = 5) -> list[SfxClip]:
        """Return clips matching a hint like 'pop' or 'whoosh'."""
        ...

    async def download(self, clip_id: str) -> bytes:
        """Download the clip audio bytes."""
        ...


# --- Context (creator memory; Meko, ADR-030) ---
@runtime_checkable
class ContextProvider(Protocol):
    """Shared memory for agents: scopes (datapacks), private memories, promoted canon.

    Every implementation logs each call to a :class:`app.memory.calllog.CallLog`, so the
    context panel shows only what a real call returned.
    """

    provider_name: str

    async def scope(self, name: str) -> str:
        """Return the id of the scope named ``name``, creating it on first use."""
        ...

    async def thread(self, scope: str, agent_id: str = "clipz") -> str:
        """Return the conversation id used for calls in ``scope`` (reused)."""
        ...

    async def list_memories(
        self, scope: str, agent_id: str | None, promoted: bool
    ) -> list[MemoryItem]:
        """All private memories in ``scope`` (each tagged with its writer's agent_id) when
        promoted=False, or the scope's promoted canon. ``agent_id`` attributes the read."""
        ...

    async def search_shared(self, scope: str, query: str, limit: int = 5) -> list[MemoryItem]:
        """Semantic search over the scope's shared knowledge (canon + documents)."""
        ...

    async def add_memory(self, scope: str, agent_id: str, text: str) -> list[MemoryItem]:
        """Store one fact verbatim; returns what the provider stored."""
        ...

    async def add_turn(
        self, scope: str, agent_id: str, user: str, reply: str, seed: bool = False
    ) -> str:
        """Store one chat turn; the provider extracts durable memories from it."""
        ...

    async def update_memory(self, scope: str, agent_id: str, memory_id: str, text: str) -> None:
        """Replace a memory's text (user correction)."""
        ...

    async def delete_memory(self, scope: str, agent_id: str, memory_id: str) -> None:
        """Forget one memory."""
        ...

    async def promote(self, scope: str, agent_id: str, memory_ids: list[str]) -> list[str]:
        """Move memories into the scope's shared canon; returns the promoted ids."""
        ...
