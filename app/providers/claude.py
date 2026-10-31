"""Claude (Anthropic Messages API) behind the same contracts as Gemini.

Docs: https://platform.claude.com/docs/en/api/messages (tool use, streaming) and the model
notes for ``claude-sonnet-5-5``: thinking blocks are replayed unchanged on the same model
(``AgentMessage.native``), forced ``tool_choice`` is not used, sampling parameters are not sent,
and plain completions turn thinking off with ``{"type": "between_tools"}`` at ``low`` effort so
reasoning tokens never eat the JSON output budget (the failure seen with Gemini 2.5 Flash).
"""

import base64
from collections.abc import Awaitable, Callable
from typing import Any

from app.providers.base import ChatReply, ChatRequest
from app.providers.gemini import ProviderFailed, ProviderUnavailable, QuotaExhausted
from app.providers.tools import (
    AgentMessage,
    StopReason,
    TextSink,
    ToolCall,
    ToolTurnReply,
    ToolTurnRequest,
    Usage,
)

DEFAULT_MODEL = "claude-sonnet-5-5"
TOOL_TURN_MIN_TOKENS = 16000  # adaptive thinking spends from max_tokens too
_STOP: dict[str, StopReason] = {
    "end_turn": "end_turn",
    "stop_sequence": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
    "pause_turn": "other",
}


def _blocks(m: AgentMessage) -> list[dict[str, Any]] | str:
    """One neutral history entry as Messages API content."""
    if m.role == "assistant":
        if isinstance(m.native, list):  # thinking blocks must be echoed back verbatim
            return list(m.native)
        blocks: list[dict[str, Any]] = []
        if m.text:
            blocks.append({"type": "text", "text": m.text})
        blocks += [
            {"type": "tool_use", "id": c.id, "name": c.name, "input": c.args} for c in m.calls
        ]
        return blocks
    if not m.results:
        return m.text
    blocks = [  # every result of a turn goes in ONE user message, before any text
        {
            "type": "tool_result",
            "tool_use_id": r.call_id,
            "content": r.content,
            **({"is_error": True} if r.is_error else {}),
        }
        for r in m.results
    ]
    if m.text:
        blocks.append({"type": "text", "text": m.text})
    return blocks


def to_messages(history: list[AgentMessage]) -> list[dict[str, Any]]:
    """Neutral history -> Messages API ``messages`` (empty entries dropped)."""
    out = []
    for m in history:
        content = _blocks(m)
        if content:
            out.append({"role": m.role, "content": content})
    return out


def _usage(raw: Any) -> Usage:
    u = getattr(raw, "usage", None)
    return Usage(
        input_tokens=getattr(u, "input_tokens", 0) or 0,
        output_tokens=getattr(u, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
    )


def _dump(block: Any) -> dict[str, Any]:
    """A response block as request JSON (None fields dropped; thinking signature kept)."""
    return dict(block.model_dump(mode="json", exclude_none=True))


class ClaudeLLM:
    """Director (tool calling) and plain-completion model on the Anthropic API."""

    provider_name = "claude"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        effort: str = "medium",
        client: Any | None = None,
        fallback_models: tuple[str, ...] = (),
        on_attempt: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.on_attempt = on_attempt
        self.model = model
        self.effort = effort
        self.fallback_models = fallback_models  # accepted for parity with GeminiLLM; unused
        self._api_key = api_key
        self._client = client

    def _messages(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise ProviderUnavailable("ANTHROPIC_API_KEY is empty; set it to use Claude")
            import anthropic

            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        return self._client.messages

    async def _note_attempt(self) -> None:
        """Tell the shared budget ledger a request is about to be sent."""
        if self.on_attempt is not None:
            await self.on_attempt({"model": self.model, "input": []})

    def _wrap(self, exc: Exception) -> Exception:
        """Typed SDK errors -> the app's provider errors (most specific first)."""
        import anthropic

        if isinstance(exc, anthropic.RateLimitError):
            wait = exc.response.headers.get("retry-after", "?")
            return QuotaExhausted(f"Claude rate limit on {self.model} (retry after {wait}s)")
        if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
            return ProviderUnavailable(f"Claude rejected the API key: {exc.message}")
        if isinstance(exc, anthropic.APIConnectionError):
            return ProviderUnavailable(f"cannot reach the Anthropic API: {exc}")
        if isinstance(exc, anthropic.APIStatusError):
            if exc.status_code >= 500 or exc.status_code == 529:
                return ProviderUnavailable(f"Anthropic API unavailable ({exc.status_code})")
            return ProviderFailed(f"Claude request rejected: {exc.message}")
        return exc

    def _shared(self, effort: str | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "model": self.model,
            "output_config": {"effort": effort or self.effort},
        }
        return out

    async def complete_with_tools(
        self, request: ToolTurnRequest, on_text: TextSink | None = None
    ) -> ToolTurnReply:
        """One streamed assistant turn. Tool inputs are returned unvalidated, as everywhere."""
        tools: list[dict[str, Any]] = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in request.tools
        ]
        if tools:
            tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}  # stable prefix
        kwargs = {
            **self._shared(),
            "max_tokens": max(request.max_tokens, TOOL_TURN_MIN_TOKENS),
            "system": [
                {"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": to_messages(request.messages),
            **({"tools": tools} if tools else {}),
        }
        await self._note_attempt()
        try:
            async with self._messages().stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    if on_text is not None:
                        on_text(text)
                final = await stream.get_final_message()
        except Exception as exc:
            wrapped = self._wrap(exc)
            raise wrapped from exc
        calls = [
            ToolCall(id=b.id, name=b.name, args=dict(b.input or {}))
            for b in final.content
            if b.type == "tool_use"
        ]
        return ToolTurnReply(
            text="".join(b.text for b in final.content if b.type == "text"),
            calls=calls,
            stop_reason=_STOP.get(str(final.stop_reason), "other"),
            model=getattr(final, "model", "") or self.model,
            usage=_usage(final),
            native=[_dump(b) for b in final.content],
        )

    async def complete(self, request: ChatRequest) -> ChatReply:
        """Plain completion (analysis stages, planner, visual review). JSON in, JSON out."""
        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        messages: list[dict[str, Any]] = []
        for m in request.messages:
            if m.role == "system":
                continue
            parts: list[dict[str, Any]] = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.mime_type,
                        "data": base64.b64encode(image.data).decode(),
                    },
                }
                for image in m.images
            ]
            parts.append({"type": "text", "text": m.content})
            messages.append({"role": "user" if m.role == "user" else "assistant", "content": parts})
        kwargs: dict[str, Any] = {
            **self._shared("low"),
            "max_tokens": min(max(request.max_tokens, 4096), 16000),
            "messages": messages,
            **({"system": system} if system else {}),
        }
        if self.model.startswith("claude-sonnet-5-5"):
            kwargs["thinking"] = {"type": "between_tools"}  # no reasoning tokens in the answer
        await self._note_attempt()
        try:
            raw = await self._messages().create(**kwargs)
        except Exception as exc:
            wrapped = self._wrap(exc)
            raise wrapped from exc
        if raw.stop_reason == "max_tokens":
            raise ProviderFailed(f"{self.model} ran out of output tokens; raise max_tokens")
        if raw.stop_reason == "refusal":
            raise ProviderFailed(f"{self.model} declined the request")
        usage = _usage(raw)
        return ChatReply(
            text="".join(b.text for b in raw.content if b.type == "text"),
            model=getattr(raw, "model", "") or self.model,
            tokens_used=usage.input_tokens + usage.output_tokens,
        )
