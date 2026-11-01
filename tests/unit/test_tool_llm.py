"""Tool-calling provider layer: Gemini Interactions mapping (offline) + scripted fake."""

from types import SimpleNamespace
from typing import Any

import pytest

from app.providers.base import ChatMessage, ChatRequest
from app.providers.fakes import ScriptedToolLLM
from app.providers.gemini import (
    GeminiLLM,
    ProviderFailed,
    ProviderUnavailable,
    build_body,
    parse_interaction,
    to_steps,
)
from app.providers.tools import (
    AgentMessage,
    ToolCall,
    ToolCallingLLM,
    ToolResult,
    ToolTurnReply,
    ToolTurnRequest,
)
from app.tools.registry import tool_specs


def _request() -> ToolTurnRequest:
    return ToolTurnRequest(
        system="You edit reels.",
        tools=tool_specs(),
        messages=[
            AgentMessage(role="user", text="remove silences"),
            AgentMessage(
                role="assistant",
                text="Cutting.",
                calls=[ToolCall(id="fc_1", name="remove_silence", args={"min_silence_ms": 500})],
            ),
            AgentMessage(
                role="user",
                results=[ToolResult(call_id="fc_1", name="remove_silence", content="{}")],
            ),
        ],
    )


def test_build_body_is_stateless_and_maps_history() -> None:
    body = build_body(_request(), "gemini-3.8-flash", "low")
    assert body["store"] is False and "previous_interaction_id" not in body
    assert body["stream"] is False
    assert body["system_instruction"] == "You edit reels."
    assert body["generation_config"] == {"max_output_tokens": 4096, "thinking_level": "low"}
    assert (
        body["tools"][0]["type"] == "function"
        and body["tools"][0]["parameters"]["type"] == "object"
    )
    assert [s["type"] for s in body["input"]] == [
        "user_input",
        "model_output",
        "function_call",
        "function_result",
    ]
    assert body["input"][2] == {
        "type": "function_call",
        "id": "fc_1",
        "name": "remove_silence",
        "arguments": {"min_silence_ms": 500},
    }
    assert body["input"][3]["call_id"] == "fc_1" and body["input"][3]["is_error"] is False


def test_native_steps_are_replayed_verbatim() -> None:
    native = [
        {"type": "thought", "signature": "c2ln"},
        {"type": "function_call", "id": "a", "name": "denoise", "arguments": {}},
    ]
    steps = to_steps([AgentMessage(role="assistant", text="ignored", native=native)])
    assert steps == native


def _interaction(status: str = "requires_action") -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        model="gemini-3.8-flash",
        steps=[
            SimpleNamespace(
                type="thought", model_dump=lambda **_: {"type": "thought", "signature": "c2ln"}
            ),
            {"type": "model_output", "content": [{"type": "text", "text": "On it."}]},
            {
                "type": "function_call",
                "id": "fc_9",
                "name": "denoise",
                "arguments": {"enabled": True},
            },
        ],
        usage=SimpleNamespace(total_input_tokens=10, total_output_tokens=5, total_cached_tokens=7),
    )


def test_parse_interaction_extracts_text_calls_usage_and_native() -> None:
    reply = parse_interaction(_interaction())
    assert reply.text == "On it." and reply.stop_reason == "tool_use"
    assert reply.calls == [ToolCall(id="fc_9", name="denoise", args={"enabled": True})]
    assert reply.usage.input_tokens == 10 and reply.usage.cache_read_tokens == 7
    assert reply.native[0] == {"type": "thought", "signature": "c2ln"}  # type: ignore[index]
    # completed but with calls still means "run the tools"
    assert parse_interaction(_interaction("completed")).stop_reason == "tool_use"
    assert parse_interaction(_interaction("incomplete")).stop_reason == "max_tokens"
    with pytest.raises(ProviderFailed):
        parse_interaction(_interaction("failed"))


class _FakeInteractions:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.bodies: list[dict[str, Any]] = []

    async def create(self, **body: Any) -> Any:
        self.bodies.append(body)
        return self.result


def _client(result: Any) -> tuple[SimpleNamespace, _FakeInteractions]:
    fake = _FakeInteractions(result)
    return SimpleNamespace(aio=SimpleNamespace(interactions=fake)), fake


async def test_gemini_tool_turn_and_text_sink() -> None:
    client, fake = _client(_interaction("completed"))
    llm = GeminiLLM(api_key="", client=client)
    assert isinstance(llm, ToolCallingLLM)
    deltas: list[str] = []
    reply = await llm.complete_with_tools(_request(), on_text=deltas.append)
    assert deltas == ["On it."] and reply.calls[0].name == "denoise"
    assert fake.bodies[0]["model"] == "gemini-3-flash-preview"


async def test_gemini_plain_completion_for_analysis() -> None:
    done = SimpleNamespace(
        status="completed",
        model="gemini-3.8-flash",
        steps=[{"type": "model_output", "content": [{"type": "text", "text": '{"beats": []}'}]}],
        usage=None,
    )
    client, fake = _client(done)
    reply = await GeminiLLM(api_key="", client=client).complete(
        ChatRequest(
            messages=[
                ChatMessage(role="system", content="Return JSON."),
                ChatMessage(role="user", content="transcript"),
            ]
        )
    )
    assert reply.text == '{"beats": []}'
    body = fake.bodies[0]
    assert "tools" not in body and body["system_instruction"] == "Return JSON."
    assert body["input"] == [
        {"type": "user_input", "content": [{"type": "text", "text": "transcript"}]}
    ]


class _FakeEventStream:
    """Stands in for the SDK's AsyncStream: async-iterable + async context manager."""

    def __init__(self, events: list[Any]) -> None:
        self.events = events
        self.closed = False

    def __aiter__(self) -> "_FakeEventStream":
        self._iter = iter(self.events)
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration from None

    async def __aenter__(self) -> "_FakeEventStream":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.closed = True


async def test_gemini_streams_text_deltas() -> None:
    final = SimpleNamespace(
        status="completed",
        model="gemini-3.8-flash",
        steps=[{"type": "model_output", "content": [{"type": "text", "text": "On it."}]}],
        usage=SimpleNamespace(total_input_tokens=1, total_output_tokens=1, total_cached_tokens=0),
    )
    events = [
        SimpleNamespace(event_type="step.delta", delta=SimpleNamespace(type="text", text="On ")),
        SimpleNamespace(event_type="step.delta", delta=SimpleNamespace(type="text", text="it.")),
        SimpleNamespace(event_type="interaction.completed", interaction=final),
    ]
    stream = _FakeEventStream(events)
    client, fake = _client(stream)
    llm = GeminiLLM(api_key="", client=client)
    deltas: list[str] = []
    reply = await llm.complete_with_tools(_request(), on_text=deltas.append)
    assert deltas == ["On ", "it."]
    assert reply.text == "On it." and reply.model == "gemini-3.8-flash"
    assert fake.bodies[0]["stream"] is True
    assert stream.closed  # the context manager closed the response


async def test_stream_assembles_live_tool_events_and_replays_thought_signature() -> None:
    final = {
        "status": "requires_action",
        "model": "gemini-2.5-flash",
        "usage": {"total_input_tokens": 12, "total_output_tokens": 5},
    }
    events = [
        {"event_type": "step.start", "index": 0, "step": {"type": "thought"}},
        {
            "event_type": "step.delta",
            "index": 0,
            "delta": {"type": "thought_signature", "signature": "opaque-provider-signature"},
        },
        {"event_type": "step.stop", "index": 0},
        {
            "event_type": "step.start",
            "index": 1,
            "step": {
                "type": "function_call",
                "id": "real-call",
                "name": "denoise",
                "arguments": {},
            },
        },
        {
            "event_type": "step.delta",
            "index": 1,
            "delta": {"type": "arguments_delta", "arguments": '{"enabled":'},
        },
        {
            "event_type": "step.delta",
            "index": 1,
            "delta": {"type": "arguments_delta", "arguments": "true}"},
        },
        {"event_type": "step.stop", "index": 1},
        {"event_type": "interaction.completed", "interaction": final},
    ]
    client, _ = _client(_FakeEventStream(events))
    reply = await GeminiLLM(api_key="", client=client).complete_with_tools(_request())
    assert reply.calls[0].name == "denoise" and reply.calls[0].args == {"enabled": True}
    assert reply.usage.input_tokens == 12 and reply.stop_reason == "tool_use"
    replay = to_steps([reply.as_message()])
    assert replay[0] == {"type": "thought", "signature": "opaque-provider-signature"}
    assert replay[1]["arguments"] == {"enabled": True}


async def test_stream_assembles_text_without_terminal_steps() -> None:
    events = [
        {
            "event_type": "step.start",
            "index": 0,
            "step": {"type": "model_output", "content": [{"type": "text", "text": "Hello "}]},
        },
        {"event_type": "step.delta", "index": 0, "delta": {"type": "text", "text": "world"}},
        {"event_type": "step.stop", "index": 0},
        {"event_type": "interaction.completed", "interaction": {"status": "completed"}},
    ]
    client, _ = _client(_FakeEventStream(events))
    chunks = []
    reply = await GeminiLLM(api_key="", client=client).complete_with_tools(
        _request(), on_text=chunks.append
    )
    assert reply.text == "Hello world" and chunks == ["Hello ", "world"]


async def test_stream_rejects_truncated_function_arguments() -> None:
    events = [
        {
            "event_type": "step.start",
            "index": 0,
            "step": {"type": "function_call", "id": "x", "name": "denoise", "arguments": {}},
        },
        {
            "event_type": "step.delta",
            "index": 0,
            "delta": {"type": "arguments_delta", "arguments": '{"enabled":'},
        },
        {"event_type": "step.stop", "index": 0},
        {"event_type": "interaction.completed", "interaction": {"status": "requires_action"}},
    ]
    client, _ = _client(_FakeEventStream(events))
    with pytest.raises(ProviderFailed, match="incomplete JSON"):
        await GeminiLLM(api_key="", client=client).complete_with_tools(_request())


async def test_gemini_stream_error_event_raises_provider_failed() -> None:
    events = [SimpleNamespace(event_type="error", error=SimpleNamespace(message="boom"))]
    client, _ = _client(_FakeEventStream(events))
    with pytest.raises(ProviderFailed, match="boom"):
        await GeminiLLM(api_key="", client=client).complete_with_tools(_request())


async def test_gemini_stream_without_completed_event_raises() -> None:
    events = [
        SimpleNamespace(event_type="step.delta", delta=SimpleNamespace(type="text", text="hi"))
    ]
    client, _ = _client(_FakeEventStream(events))
    with pytest.raises(ProviderFailed, match="without an interaction.completed"):
        await GeminiLLM(api_key="", client=client).complete_with_tools(_request())


async def test_gemini_without_key_is_unavailable() -> None:
    with pytest.raises(ProviderUnavailable, match="GEMINI_API_KEY"):
        await GeminiLLM(api_key="").complete_with_tools(_request())


async def test_scripted_llm_replays_and_records() -> None:
    def react(req: ToolTurnRequest) -> ToolTurnReply:
        last = req.messages[-1].results[0]
        return ToolTurnReply(text=f"done: {last.content}")

    llm = ScriptedToolLLM(
        [ToolTurnReply(calls=[ToolCall(id="c1", name="denoise")], stop_reason="tool_use"), react]
    )
    assert isinstance(llm, ToolCallingLLM)
    first = await llm.complete_with_tools(_request())
    assert first.calls[0].name == "denoise" and first.model == "scripted"
    second = await llm.complete_with_tools(_request())
    assert second.text == "done: {}"
    third = await llm.complete_with_tools(_request())
    assert third.calls == [] and len(llm.requests) == 3


async def test_quota_exhaustion_fails_fast_with_hint() -> None:
    from app.providers.gemini import QuotaExhausted

    class RateLimited(Exception):
        status_code = 429

        def __str__(self) -> str:
            return (
                "Error code: 429 - {'error': {'message': "
                "'Rate limit exceeded (20 requests per day). Please retry in 19h'}}"
            )

    class Failing:
        async def create(self, **_: Any) -> Any:
            raise RateLimited

    llm = GeminiLLM(api_key="", client=SimpleNamespace(aio=SimpleNamespace(interactions=Failing())))
    with pytest.raises(QuotaExhausted, match="retry in 19h"):
        await llm.complete_with_tools(_request())


async def test_quota_falls_back_to_next_model() -> None:
    class RateLimited(Exception):
        status_code = 429

    class PerModel:
        def __init__(self) -> None:
            self.models: list[str] = []

        async def create(self, **body: Any) -> Any:
            self.models.append(body["model"])
            if body["model"] == "gemini-3-flash-preview":
                raise RateLimited("{'message': 'limit: 20 requests per day'}")
            return SimpleNamespace(status="completed", model=body["model"], steps=[], usage=None)

    fake = PerModel()
    llm = GeminiLLM(
        api_key="",
        client=SimpleNamespace(aio=SimpleNamespace(interactions=fake)),
        fallback_models=("gemini-2.5-flash",),
    )
    reply = await llm.complete_with_tools(_request())
    assert fake.models == ["gemini-3-flash-preview", "gemini-2.5-flash"]
    assert reply.model == "gemini-2.5-flash"  # cost is logged against the model used


async def test_overload_is_retried_then_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.providers.gemini as gem

    monkeypatch.setattr(gem, "OVERLOAD_BACKOFF_S", (0.0, 0.0))

    class Busy(Exception):
        status_code = 503

    class Quota(Exception):
        status_code = 429

    class Flaky:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def create(self, **body: Any) -> Any:
            self.calls.append(body["model"])
            if body["model"] == "a":
                raise Quota("{'message': 'out'}")
            if len(self.calls) < 4:  # b: 503 twice, then succeeds
                raise Busy("high demand")
            return SimpleNamespace(status="completed", model=body["model"], steps=[], usage=None)

    fake = Flaky()
    llm = GeminiLLM(
        api_key="",
        model="a",
        client=SimpleNamespace(aio=SimpleNamespace(interactions=fake)),
        fallback_models=("b",),
    )
    reply = await llm.complete_with_tools(_request())
    assert fake.calls == ["a", "b", "b", "b"] and reply.model == "b"


def test_minute_limits_wait_but_daily_quotas_fall_back() -> None:
    from app.providers.gemini import minute_retry_s

    tpm = "limit: 250000 input tokens per minute on Free Tier). Please retry in 36s or upgrade"
    assert minute_retry_s(tpm) == 37.0
    assert minute_retry_s("limit: 20 requests per day on Free Tier). Please retry in 9h") is None
    assert minute_retry_s("tokens per minute. Please retry in 300s") is None


async def test_per_minute_limit_retries_same_model(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    class RateLimited(Exception):
        status_code = 429

    class PerMinute:
        def __init__(self) -> None:
            self.models: list[str] = []

        async def create(self, **body: Any) -> Any:
            self.models.append(body["model"])
            if len(self.models) == 1:
                raise RateLimited("250000 input tokens per minute. Please retry in 3s")
            return SimpleNamespace(status="completed", model=body["model"], steps=[], usage=None)

    fake = PerMinute()
    llm = GeminiLLM(
        api_key="",
        client=SimpleNamespace(aio=SimpleNamespace(interactions=fake)),
        fallback_models=("gemini-2.5-flash",),
    )
    reply = await llm.complete_with_tools(_request())
    assert fake.models == ["gemini-3-flash-preview", "gemini-3-flash-preview"]
    assert slept == [4.0] and reply.model == "gemini-3-flash-preview"
