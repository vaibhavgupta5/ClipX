"""Provider wiring: Gemini for LLM work when keyed; local libraries land in Phase 6/7."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.memory.calllog import CallLog
from app.memory.service import CreatorMemory
from app.providers.base import (
    GifProvider,
    ImageProvider,
    LLMProvider,
    MemeTemplateProvider,
    MusicProvider,
    SfxProvider,
)
from app.providers.claude import ClaudeLLM
from app.providers.elevenlabs import ElevenLabsClient
from app.providers.fakes import (
    FakeGifProvider,
    FakeImageProvider,
    FakeLLMProvider,
    FakeMemeTemplateProvider,
    FakeMusicProvider,
    FakeSfxProvider,
)
from app.providers.gemini import GeminiLLM
from app.providers.generated import GeneratedAudioStore
from app.providers.local import (
    LocalGifProvider,
    LocalImageProvider,
    LocalMemeTemplateProvider,
    LocalMusicProvider,
)
from app.providers.meko import MekoContextProvider
from app.providers.tools import ToolCallingLLM
from app.settings import Settings, get_settings


@dataclass(frozen=True)
class ProviderRegistry:
    """All provider implementations for one process."""

    llm: LLMProvider
    music: MusicProvider
    images: ImageProvider
    gifs: GifProvider
    memes: MemeTemplateProvider
    sfx: SfxProvider


def provider_registry(settings: Settings | None = None) -> ProviderRegistry:
    """Gemini when GEMINI_API_KEY is set; local libraries when their manifests exist; else fakes."""
    settings = settings or get_settings()
    llm: GeminiLLM | ClaudeLLM | FakeLLMProvider = make_llm(settings) or FakeLLMProvider()
    root = Path(settings.ASSETS_DIR)

    def has(lib: str) -> bool:
        return (root / lib / "manifest.json").is_file()

    return ProviderRegistry(
        llm=llm,
        music=LocalMusicProvider(root) if has("music") else FakeMusicProvider(),
        images=LocalImageProvider(root) if has("images") else FakeImageProvider(),
        gifs=LocalGifProvider(root) if has("gifs") else FakeGifProvider(),
        memes=(
            LocalMemeTemplateProvider(root, Path(settings.WORK_DIR) / "cache" / "memes")
            if has("memes")
            else FakeMemeTemplateProvider()
        ),
        sfx=FakeSfxProvider(),  # no local SFX pack yet (Phase 6)
    )


def use_claude(settings: Settings) -> bool:
    """True when LLM_PROVIDER=claude (the key is checked when a model is built)."""
    return settings.LLM_PROVIDER.strip().lower() == "claude"


def llm_enabled(settings: Settings | None = None) -> bool:
    """Whether the selected provider has a key (False = deterministic fallbacks)."""
    settings = settings or get_settings()
    return bool(settings.ANTHROPIC_API_KEY if use_claude(settings) else settings.GEMINI_API_KEY)


def make_llm(
    settings: Settings | None = None,
    on_attempt: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> GeminiLLM | ClaudeLLM | None:
    """The configured model for analysis, review and scene authoring; None without a key."""
    settings = settings or get_settings()
    if not llm_enabled(settings):
        return None
    llm = _claude(settings) if use_claude(settings) else _gemini(settings)
    llm.on_attempt = on_attempt
    return llm


def director_llm(settings: Settings | None = None) -> ToolCallingLLM:
    """The Director's tool-calling model (LLM_PROVIDER). Raises when no key is configured."""
    settings = settings or get_settings()
    return _claude(settings) if use_claude(settings) else _gemini(settings)


def planner_llm(settings: Settings | None = None) -> GeminiLLM | ClaudeLLM | None:
    """Model for the single explainer planning request (None without an API key)."""
    settings = settings or get_settings()
    if not llm_enabled(settings):
        return None
    if use_claude(settings):
        llm = _claude(settings)
        if settings.CLAUDE_PLANNER_MODEL:
            llm.model = settings.CLAUDE_PLANNER_MODEL
        return llm
    gemini = _gemini(settings)
    if settings.GEMINI_PLANNER_MODEL:
        gemini.model = settings.GEMINI_PLANNER_MODEL
        gemini.thinking_level = settings.GEMINI_PLANNER_THINKING_LEVEL
    return gemini


def _claude(settings: Settings) -> ClaudeLLM:
    return ClaudeLLM(settings.ANTHROPIC_API_KEY, settings.CLAUDE_MODEL, settings.CLAUDE_LLM_EFFORT)


def _gemini(settings: Settings) -> GeminiLLM:
    fallbacks = tuple(m.strip() for m in settings.GEMINI_FALLBACK_MODELS.split(",") if m.strip())
    return GeminiLLM(
        settings.GEMINI_API_KEY,
        settings.GEMINI_MODEL,
        settings.GEMINI_THINKING_LEVEL,
        fallback_models=fallbacks,
    )


_generators: dict[str, GeneratedAudioStore] = {}


def audio_generator(settings: Settings | None = None) -> GeneratedAudioStore | None:
    """ElevenLabs-backed generated audio, or None when no key is configured.

    One store (and HTTP connection pool) per key for the life of the process.
    """
    settings = settings or get_settings()
    key = settings.ELEVENLABS_API_KEY
    if not key:
        return None
    if key not in _generators:
        _generators[key] = _new_generator(settings)
    return _generators[key]


def _new_generator(settings: Settings) -> GeneratedAudioStore:
    return GeneratedAudioStore(
        settings.ASSETS_DIR,
        ElevenLabsClient(settings.ELEVENLABS_API_KEY),
        settings.elevenlabs_plan,
        settings.ELEVENLABS_VOICE_ID,
    )


@lru_cache(maxsize=1)
def meko_call_log() -> CallLog:
    """Process-wide log of every context call (mirrored to WORK_DIR/meko/calls.jsonl)."""
    return CallLog(Path(get_settings().WORK_DIR) / "meko" / "calls.jsonl")


@lru_cache(maxsize=1)
def creator_memory() -> CreatorMemory | None:
    """Meko-backed creator memory when MEKO_API_KEY is set; None means memory is off."""
    s = get_settings()
    if not s.MEKO_API_KEY:
        return None
    provider = MekoContextProvider(
        s.MEKO_API_KEY,
        s.MEKO_MCP_URL,
        meko_call_log(),
        timeout_s=s.MEKO_TIMEOUT_S,
        state_path=Path(s.WORK_DIR) / "meko" / "ids.json",
    )
    return CreatorMemory(provider, s.MEKO_DATAPACK_PREFIX, timeout_s=s.MEKO_TIMEOUT_S)
