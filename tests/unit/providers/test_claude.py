"""ClaudeLLM against a fake Messages client (no network)."""

from types import SimpleNamespace as NS
from typing import Any

import pytest

from app.providers.base import ChatMessage, ChatRequest
from app.providers.claude import ClaudeLLM, to_messages
from app.providers.gemini import ProviderFailed, ProviderUnavailable
from app.providers.registry import director_llm, llm_enabled, make_llm, planner_llm
from app.providers.tools import AgentMessage, ToolCall, ToolResult, ToolSpec, ToolTurnRequest
from app.settings import Settings


class _Block(NS):
    def model_dump(self, **_: Any) -> dict[str, Any]:
        return {k: v for k, v in vars(self).items() if v is not None}


def _msg(content: list[Any], stop: str = "end_turn") -> NS:
    return NS(
        content=content,
        stop_reason=stop,
        model="claude-sonnet-5-5",
        usage=NS(
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=3,
            cache_creation_input_tokens=0,
        ),
    )


class _Stream:
    def __init__(self, final: NS) -> None:
        self.final = final

    async def __aenter__(self) -> "_Stream":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    @property
    def text_stream(self) -> Any:
        async def gen() -> Any:
            for b in self.final.content:
                if b.type == "text":
                    yield b.text

        return gen()

    async def get_final_message(self) -> NS:
        return self.final


class _Messages:
    def __init__(self, final: NS) -> None:
        self.final, self.sent = final, []

    def stream(self, **kw: Any) -> _Stream:
        self.sent.append(kw)
        return _Stream(self.final)

    async def create(self, **kw: Any) -> NS:
        self.sent.append(kw)
        return self.final


def _llm(final: NS) -> tuple[ClaudeLLM, _Messages]:
    m = _Messages(final)
    return ClaudeLLM("k", client=NS(messages=m)), m


async def test_tool_turn_returns_calls_and_replay_blob() -> None:
    final = _msg(
        [
            _Block(type="thinking", thinking="hm", signature="sig"),
            _Block(type="text", text="cutting"),
            _Block(type="tool_use", id="t1", name="cut", input={"a": 1}),
        ],
        "tool_use",
    )
    llm, m = _llm(final)
    seen: list[str] = []
    req = ToolTurnRequest(
        system="sys",
        messages=[AgentMessage(role="user", text="go")],
        tools=[ToolSpec(name="cut", description="d", input_schema={"type": "object"})],
    )
    reply = await llm.complete_with_tools(req, seen.append)
    assert reply.stop_reason == "tool_use"
    assert reply.calls == [ToolCall(id="t1", name="cut", args={"a": 1})]
    assert seen == ["cutting"] and reply.usage.cache_read_tokens == 3
    assert reply.native[0]["type"] == "thinking"  # replayed verbatim next turn
    sent = m.sent[0]
    assert "temperature" not in sent and "tool_choice" not in sent
    assert sent["tools"][-1]["cache_control"] == {"type": "ephemeral"}


def test_tool_results_share_one_user_message() -> None:
    history = [
        AgentMessage(role="user", text="go"),
        AgentMessage(
            role="assistant",
            calls=[ToolCall(id="a", name="x", args={}), ToolCall(id="b", name="y", args={})],
        ),
        AgentMessage(
            role="user",
            results=[
                ToolResult(call_id="a", name="x", content="ok"),
                ToolResult(call_id="b", name="y", content="no", is_error=True),
            ],
        ),
    ]
    msgs = to_messages(history)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    blocks = msgs[2]["content"]
    assert [b["tool_use_id"] for b in blocks] == ["a", "b"] and blocks[1]["is_error"]


async def test_complete_turns_thinking_off_and_rejects_truncation() -> None:
    llm, m = _llm(_msg([_Block(type="text", text='{"ok":1}')]))
    reply = await llm.complete(
        ChatRequest(
            messages=[
                ChatMessage(role="system", content="s"),
                ChatMessage(role="user", content="u"),
            ]
        )
    )
    assert reply.text == '{"ok":1}' and reply.tokens_used == 15
    assert m.sent[0]["thinking"] == {"type": "between_tools"} and m.sent[0]["system"] == "s"
    llm2, _ = _llm(_msg([_Block(type="text", text="{")], "max_tokens"))
    with pytest.raises(ProviderFailed):
        await llm2.complete(ChatRequest(messages=[ChatMessage(role="user", content="u")]))


async def test_missing_key_is_unavailable() -> None:
    with pytest.raises(ProviderUnavailable):
        await ClaudeLLM("").complete(ChatRequest(messages=[ChatMessage(role="user", content="u")]))


def test_registry_switches_on_llm_provider() -> None:
    claude = Settings(
        LLM_PROVIDER="claude",
        ANTHROPIC_API_KEY="k",
        GEMINI_API_KEY="g",
        CLAUDE_PLANNER_MODEL="claude-haiku-5-5",
    )
    assert isinstance(director_llm(claude), ClaudeLLM)
    planner = planner_llm(claude)
    assert isinstance(planner, ClaudeLLM) and planner.model == "claude-haiku-5-5"
    gem = Settings(LLM_PROVIDER="gemini", ANTHROPIC_API_KEY="k", GEMINI_API_KEY="")
    assert not llm_enabled(gem) and make_llm(gem) is None and planner_llm(gem) is None
