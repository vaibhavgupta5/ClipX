"""Gemini adapter over the Interactions API (google-genai SDK), stateless (ADR-012).

History is sent as typed input steps with ``store=false`` so Google keeps nothing:
user turns -> ``user_input``, our tool results -> ``function_result``, and the
model's own earlier steps (thoughts with signatures, function calls, outputs)
are replayed verbatim from ``native``. Request building and response parsing
are pure functions, tested offline; the SDK client is created lazily.
Docs: https://ai.google.dev/gemini-api/docs/function-calling (retrieved 2026-10-10).
"""

import base64
import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.providers.base import ChatReply, ChatRequest
from app.providers.tools import (
    AgentMessage,
    StopReason,
    TextSink,
    ToolCall,
    ToolTurnReply,
    ToolTurnRequest,
    Usage,
)

DEFAULT_MODEL = "gemini-3-flash-preview"
CALL_TIMEOUT_S = 45.0
OVERLOAD_BACKOFF_S = (2.0, 5.0)  # retries for 5xx overload before trying the next model
_STATUS: dict[str, StopReason] = {
    "completed": "end_turn",
    "requires_action": "tool_use",
    "incomplete": "max_tokens",
    "budget_exceeded": "max_tokens",
}


class ProviderUnavailable(RuntimeError):
    """Key unset or SDK missing; the message says how to fix it."""


class QuotaExhausted(ProviderUnavailable):
    """Gemini rate/quota limit hit (the message includes Google's retry hint)."""


class ProviderFailed(RuntimeError):
    """The model run failed or was cancelled."""


def _text(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": text}]


def _quota_hint(exc: Exception) -> str:
    """Google's own message (limit + retry delay), trimmed."""
    import re

    text = str(exc)
    match = re.search(r"'message': '([^']+)'", text)
    return (match.group(1) if match else text)[:200]


MINUTE_RETRIES = 2  # waits on one model for per-minute (RPM/TPM) limits before falling back


def minute_retry_s(message: str) -> float | None:
    """Seconds to wait for a per-minute limit ("... per minute ... retry in 36s"), else None.

    Daily quotas and long waits return None so the caller falls back instead of hanging.
    """
    import re

    if not re.search(r"per minute", message, re.IGNORECASE):
        return None
    match = re.search(r"retry in (\d+(?:\.\d+)?)\s*s", message, re.IGNORECASE)
    if match is None or float(match.group(1)) > 60:
        return None
    return float(match.group(1)) + 1.0


def to_steps(messages: list[AgentMessage]) -> list[dict[str, Any]]:
    """Neutral history -> Interactions input steps."""
    steps: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "assistant":
            if isinstance(m.native, list):
                steps.extend(m.native)
                continue
            if m.text:
                steps.append({"type": "model_output", "content": _text(m.text)})
            steps += [
                {"type": "function_call", "id": c.id, "name": c.name, "arguments": c.args}
                for c in m.calls
            ]
            continue
        steps += [
            {
                "type": "function_result",
                "call_id": r.call_id,
                "name": r.name,
                "result": r.content,
                "is_error": r.is_error,
            }
            for r in m.results
        ]
        if m.text:
            steps.append({"type": "user_input", "content": _text(m.text)})
    return steps


def build_body(
    request: ToolTurnRequest, model: str, thinking_level: str, stream: bool = False
) -> dict[str, Any]:
    """Interactions create() body for one tool turn."""
    return {
        "model": model,
        "system_instruction": request.system,
        "input": to_steps(request.messages),
        "tools": [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            }
            for t in request.tools
        ],
        "generation_config": {
            "max_output_tokens": request.max_tokens,
            # empty = model default (2.5 Flash-Lite: no thinking; its "low" maps to an
            # invalid 256-token budget, so the field must be omitted for it)
            **({"thinking_level": thinking_level} if thinking_level else {}),
        },
        "store": False,
        "stream": stream,
    }


def _get(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _dump(step: Any) -> dict[str, Any]:
    if isinstance(step, dict):
        return step
    dumped: dict[str, Any] = step.model_dump(mode="json", by_alias=True, exclude_none=True)
    return dumped


async def _consume_stream(stream: Any, on_text: TextSink | None) -> Any:
    """Drain an Interactions SSE stream, forwarding text deltas as they arrive;
    returns the final Interaction from the ``interaction.completed`` event.

    Mid-stream errors (``error`` events, or a terminal status update with no
    completed interaction) raise ``ProviderFailed`` directly, same as a failed/
    cancelled status on the non-streamed path -- there is no model to fall back
    to mid-stream, unlike the connection-level 429/503 handling in ``_create``.
    """
    final: Any = None
    steps: dict[int, dict[str, Any]] = {}
    arguments: dict[int, str] = {}
    stopped: set[int] = set()
    async with stream:
        async for event in stream:
            kind = _get(event, "event_type")
            if kind == "error":
                raise ProviderFailed(f"gemini stream error: {_get(event, 'error')}")
            if kind == "step.start":
                index = int(_get(event, "index") or 0)
                steps[index] = _dump(_get(event, "step"))
                if on_text is not None and steps[index].get("type") == "model_output":
                    for part in steps[index].get("content", []):
                        if part.get("type") == "text" and part.get("text"):
                            on_text(str(part["text"]))
            elif kind == "step.delta":
                delta = _get(event, "delta")
                index = int(_get(event, "index") or 0)
                step = steps.get(index)
                delta_type = _get(delta, "type")
                if delta_type == "text":
                    text = _get(delta, "text")
                    if text:
                        if on_text is not None:
                            on_text(text)
                        if step is not None:
                            content = step.setdefault("content", [])
                            if content and content[-1].get("type") == "text":
                                content[-1]["text"] = content[-1].get("text", "") + text
                            else:
                                content.append({"type": "text", "text": text})
                elif delta_type == "arguments_delta":
                    arguments[index] = arguments.get(index, "") + str(
                        _get(delta, "arguments") or ""
                    )
                elif step is not None and delta_type == "thought_signature":
                    step["signature"] = _get(delta, "signature")
                elif step is not None and delta_type == "thought_summary":
                    step.setdefault("summary", []).append(_dump(_get(delta, "content")))
            elif kind == "step.stop":
                stopped.add(int(_get(event, "index") or 0))
            elif kind == "interaction.completed":
                final = _get(event, "interaction")
            elif kind == "interaction.status_update" and final is None:
                status = str(_get(event, "status") or "")
                if status in ("failed", "cancelled"):
                    raise ProviderFailed(f"gemini stream status {status}")
    if final is None:
        raise ProviderFailed("gemini stream ended without an interaction.completed event")
    # Production completed events carry status/usage, not the assembled steps.
    # Some SDK/test paths do include them; prefer that authoritative full object.
    if not _get(final, "steps") and steps:
        if set(steps) - stopped:
            raise ProviderFailed("gemini stream completed with an unfinished step")
        for index, fragments in arguments.items():
            if index not in steps or steps[index].get("type") != "function_call":
                raise ProviderFailed("gemini argument deltas have no function-call step")
            try:
                decoded = json.loads(fragments)
            except ValueError:
                raise ProviderFailed(
                    "gemini streamed function arguments are incomplete JSON"
                ) from None
            if not isinstance(decoded, dict):
                raise ProviderFailed("gemini function arguments must be a JSON object")
            steps[index]["arguments"] = decoded
        return {
            "status": _get(final, "status"),
            "model": _get(final, "model"),
            "usage": _get(final, "usage"),
            "steps": [steps[i] for i in sorted(steps)],
        }
    return final


def parse_interaction(interaction: Any) -> ToolTurnReply:
    """SDK Interaction -> neutral reply. Function-call arguments stay unvalidated."""
    status = str(_get(interaction, "status") or "")
    if status in ("failed", "cancelled"):
        raise ProviderFailed(f"gemini interaction {status}: {_get(interaction, 'errors')}")
    steps = list(_get(interaction, "steps") or [])
    texts: list[str] = []
    calls: list[ToolCall] = []
    for step in steps:
        kind = _get(step, "type")
        if kind == "function_call":
            args = _get(step, "arguments")
            calls.append(
                ToolCall(
                    id=str(_get(step, "id")),
                    name=str(_get(step, "name")),
                    args=args if isinstance(args, dict) else {},
                )
            )
        elif kind == "model_output":
            texts += [
                str(_get(c, "text"))
                for c in _get(step, "content") or []
                if _get(c, "type") == "text"
            ]
    stop = _STATUS.get(status, "other")
    if calls and stop == "end_turn":
        stop = "tool_use"
    u = _get(interaction, "usage")
    usage = Usage(
        input_tokens=int(_get(u, "total_input_tokens") or 0) if u else 0,
        output_tokens=int(_get(u, "total_output_tokens") or 0) if u else 0,
        cache_read_tokens=int(_get(u, "total_cached_tokens") or 0) if u else 0,
        thought_tokens=int(_get(u, "total_thought_tokens") or 0) if u else 0,
    )
    return ToolTurnReply(
        text="".join(texts),
        calls=calls,
        stop_reason=stop,
        model=str(_get(interaction, "model") or ""),
        usage=usage,
        native=[_dump(s) for s in steps],
    )


class GeminiLLM:
    """Gemini as both LLMProvider (analysis stages) and ToolCallingLLM (Director)."""

    provider_name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        thinking_level: str = "",
        client: Any | None = None,
        fallback_models: tuple[str, ...] = (),
        on_attempt: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.on_attempt = on_attempt
        self.model = model
        self.fallback_models = fallback_models
        self.thinking_level = thinking_level
        self._api_key = api_key
        self._client = client

    async def _create(self, body: dict[str, Any]) -> Any:
        """One Interactions call, bounded in time; on quota exhaustion the same request is
        retried on each fallback model in order (owner: 3.1 Flash-Lite -> 2.5 Flash-Lite)."""
        import asyncio

        hints: list[str] = []
        for model in (body["model"], *self.fallback_models):
            overloads = waits = 0
            while True:
                try:
                    if self.on_attempt is not None:
                        await self.on_attempt({**body, "model": model})
                    return await asyncio.wait_for(
                        self._interactions().create(**{**body, "model": model}), CALL_TIMEOUT_S
                    )
                except Exception as exc:
                    status = getattr(exc, "status_code", None)
                    if status == 429:
                        # A per-minute limit clears in seconds: wait on the same model. A daily
                        # quota will not, so move on to the next model.
                        wait = minute_retry_s(str(exc))
                        if wait is not None and waits < MINUTE_RETRIES:
                            waits += 1
                            await asyncio.sleep(wait)
                            continue
                        hints.append(f"{model}: {_quota_hint(exc)}")
                        break
                    if isinstance(status, int) and status >= 500:
                        if overloads < len(OVERLOAD_BACKOFF_S):
                            await asyncio.sleep(OVERLOAD_BACKOFF_S[overloads])  # 503 "high demand"
                            overloads += 1
                            continue
                        hints.append(f"{model}: overloaded after {overloads + 1} tries")
                        break
                    raise
        raise QuotaExhausted("Gemini unavailable on every model: " + " | ".join(hints))

    def _interactions(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise ProviderUnavailable("GEMINI_API_KEY is empty; set it to use Gemini")
            from google import genai
            from google.genai._gaos.utils.retries import RetryConfig

            self._client = genai.Client(api_key=self._api_key)
            # The SDK otherwise retries 429s with silent back-off, so an exhausted quota
            # looks like a hang; fail fast and tell the user instead.
            self._client.aio.interactions.sdk_configuration.retry_config = RetryConfig(
                "none", None, False
            )
        return self._client.aio.interactions

    async def complete_with_tools(
        self, request: ToolTurnRequest, on_text: TextSink | None = None
    ) -> ToolTurnReply:
        """One tool turn, streamed over the Interactions SSE endpoint so ``on_text``
        fires per text delta. Falls back to a single ``on_text`` call with the whole
        reply if the client (a fake/test client, or a server that ignores ``stream``)
        returns a plain Interaction instead of an event stream."""
        body = build_body(request, self.model, self.thinking_level, stream=True)
        result = await self._create(body)
        if hasattr(result, "__aiter__"):
            interaction = await _consume_stream(result, on_text)
            return parse_interaction(interaction)
        reply = parse_interaction(result)
        if on_text is not None and reply.text:
            on_text(reply.text)
        return reply

    async def complete(self, request: ChatRequest) -> ChatReply:
        """Plain completion for analysis stages (beats, romanization, emphasis)."""
        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        history = [
            AgentMessage(role="user" if m.role == "user" else "assistant", text=m.content)
            for m in request.messages
            if m.role != "system"
        ]
        body = build_body(
            ToolTurnRequest(
                system=system, messages=history, tools=[], max_tokens=request.max_tokens
            ),
            self.model,
            self.thinking_level,
        )
        body["input"] = [
            {
                "type": "user_input" if m.role == "user" else "model_output",
                "content": [
                    *_text(m.content),
                    *[
                        {
                            "type": "image",
                            "data": base64.b64encode(image.data).decode(),
                            "mime_type": image.mime_type,
                        }
                        for image in m.images
                    ],
                ],
            }
            for m in request.messages
            if m.role != "system"
        ]
        del body["tools"]
        body["generation_config"]["temperature"] = request.temperature
        reply = parse_interaction(await self._create(body))
        if reply.stop_reason == "max_tokens":
            # Thinking tokens count against the output budget; an error beats cut-off JSON.
            raise ProviderFailed(
                f"{reply.model or self.model} ran out of output tokens "
                f"({reply.usage.output_tokens} written); lower the thinking level"
            )
        return ChatReply(
            text=reply.text,
            model=reply.model or self.model,
            tokens_used=reply.usage.input_tokens + reply.usage.output_tokens,
        )
