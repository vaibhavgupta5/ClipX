"""MekoContextProvider against a scripted MCP server (httpx.MockTransport; no network)."""

import json
from typing import Any

import httpx
import pytest

from app.memory.calllog import CallLog
from app.providers.base import ContextProvider
from app.providers.meko import MekoContextProvider, MekoError, parse_rpc_body, tool_payload


def _sse(obj: dict[str, Any]) -> str:
    return f"event: message\ndata: {json.dumps(obj)}\n\n"


def _tool(rid: int, payload: Any, is_error: bool = False) -> str:
    text = json.dumps(payload)
    return _sse(
        {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
        }
    )


class Server:
    """Answers initialize + tools/call from a {tool: payload|callable} script; records calls."""

    def __init__(self, script: dict[str, Any]) -> None:
        self.script = script
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.headers: list[httpx.Headers] = []
        self.expire_once = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.headers.append(request.headers)
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(
                200,
                text=_sse({"jsonrpc": "2.0", "id": 0, "result": {}}),
                headers={"Mcp-Session-Id": "s1"},
            )
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        name, args = body["params"]["name"], body["params"]["arguments"]
        if self.expire_once:
            self.expire_once = False
            return httpx.Response(404, text="session expired")
        self.calls.append((name, args))
        out = self.script[name]
        return httpx.Response(200, text=_tool(body["id"], out(args) if callable(out) else out))


SCRIPT: dict[str, Any] = {
    "conversation_create": {"id": "conv1"},
    "datapack_search": {
        "datapacks": [{"datapack_id": "dp-riya", "datapack_name": "t-creator-riya"}]
    },
    "datapack_create": {"datapack_id": "dp-new", "name": "t-agency"},
    "memory_get_all": lambda a: (
        {
            "promoted_memories": [
                {"id": "p1", "data": "Cut every basically", "agent_id": "clipz:curator"}
            ]
        }
        if a.get("promoted")
        else {"memories": [{"id": "m1", "memory": "no zoom cuts", "agent_id": "clipz:director"}]}
    ),
    "knowledgebase_search": {
        "results": [
            {
                "id": "c1",
                "chunk_text": "Brand: yellow captions",
                "metadata_filters": {"source": "document"},
                "rerank_score": 0.9,
            },
            {
                "id": "c2",
                "chunk_text": "Cut every basically",
                "metadata_filters": {
                    "source": "memory",
                    "memory_id": "p1",
                    "agent_id": "clipz:curator",
                },
            },
        ],
        "count": 2,
    },
    "memory_add": {"results": [{"id": "m9", "memory": "no lofi", "event": "ADD"}]},
    "conversation_add_message": {
        "status": "accepted",
        "message_id": "x",
        "conversation_id": "conv1",
    },
    "memory_promote": {"inserted_ids": ["m9"], "updated_ids": [], "not_found_ids": []},
    "memory_update": {"ok": True},
    "memory_delete_by_id": {"ok": True},
}


def _provider(server: Server) -> tuple[MekoContextProvider, CallLog]:
    log = CallLog()
    return MekoContextProvider(
        "mko_tkn_test", "https://meko.test/mcp", log, transport=httpx.MockTransport(server)
    ), log


def test_satisfies_the_provider_protocol() -> None:
    p, _ = _provider(Server(SCRIPT))
    assert isinstance(p, ContextProvider)


async def test_auth_and_user_agent_headers_are_sent() -> None:
    server = Server(SCRIPT)
    p, _ = _provider(server)
    await p.list_memories("t-creator-riya", "clipz:director", False)
    h = server.headers[-1]
    assert h["Authorization"] == "Bearer mko_tkn_test"
    assert h["User-Agent"].startswith("clipz-meko/")
    assert h["Mcp-Session-Id"] == "s1"


async def test_scope_found_by_exact_name_else_created() -> None:
    server = Server(SCRIPT)
    p, _ = _provider(server)
    assert await p.scope("t-creator-riya") == "dp-riya"
    assert await p.scope("t-agency") == "dp-new"
    assert await p.scope("t-agency") == "dp-new"  # cached
    assert [n for n, _ in server.calls].count("datapack_create") == 1


async def test_every_call_carries_conversation_and_datapack() -> None:
    server = Server(SCRIPT)
    p, _ = _provider(server)
    await p.list_memories("t-creator-riya", "clipz:director", False)
    name, args = server.calls[-1]
    assert name == "memory_get_all"
    assert args == {
        "conversation_id": "conv1",
        "datapack_id": "dp-riya",
        "agent_id": "clipz:director",
        "promoted": False,
        "page_size": 100,
    }


async def test_private_and_promoted_rows_are_mapped() -> None:
    p, _ = _provider(Server(SCRIPT))
    [private] = await p.list_memories("t-creator-riya", "clipz:director", False)
    [canon] = await p.list_memories("t-creator-riya", None, True)
    assert (private.id, private.text, private.promoted) == ("m1", "no zoom cuts", False)
    assert (canon.id, canon.text, canon.promoted) == ("p1", "Cut every basically", True)


async def test_knowledge_search_maps_memory_chunks_back_to_memory_ids() -> None:
    p, _ = _provider(Server(SCRIPT))
    doc, mem = await p.search_shared("t-creator-riya", "captions")
    assert (doc.id, doc.agent_id, doc.score) == ("c1", None, 0.9)
    assert (mem.id, mem.agent_id) == ("p1", "clipz:curator")


async def test_writes_and_promote() -> None:
    server = Server(SCRIPT)
    p, log = _provider(server)
    [row] = await p.add_memory("t-creator-riya", "clipz:curator", "no lofi")
    assert row.id == "m9"
    assert await p.promote("t-creator-riya", "clipz:curator", ["m9"]) == ["m9"]
    await p.add_turn("t-creator-riya", "clipz:director", "hi", "ok", seed=True)
    assert server.calls[-1][1]["seed"] == "seeded demo history"
    await p.update_memory("t-creator-riya", "clipz:curator", "m9", "upbeat")
    await p.delete_memory("t-creator-riya", "clipz:curator", "m9")
    kinds = [c.kind for c in log.since() if c.kind != "setup"]
    assert kinds == ["write", "promote", "write", "edit", "forget"]


async def test_tool_error_is_raised_and_logged() -> None:
    script = dict(SCRIPT, memory_get_all={"error": "conversation_id_required", "detail": "Pass it"})
    p, log = _provider(Server(script))
    with pytest.raises(MekoError, match="conversation_id_required"):
        await p.list_memories("t-creator-riya", "clipz:director", False)
    last = log.since()[-1]
    assert (last.tool, last.ok) == ("memory_get_all", False)


async def test_expired_session_is_reinitialised_once() -> None:
    server = Server(SCRIPT)
    p, _ = _provider(server)
    await p.list_memories("t-creator-riya", "clipz:director", False)
    server.expire_once = True
    [row] = await p.list_memories("t-creator-riya", "clipz:director", False)
    assert row.id == "m1"


def test_rpc_body_parsing() -> None:
    assert parse_rpc_body('{"jsonrpc":"2.0","id":1,"result":{}}')["id"] == 1
    assert parse_rpc_body(_sse({"id": 2}))["id"] == 2
    with pytest.raises(MekoError):
        parse_rpc_body("")
    with pytest.raises(MekoError, match="boom"):
        tool_payload({"error": {"message": "boom"}})
    with pytest.raises(MekoError):
        tool_payload(json.loads(_tool(1, "bad", is_error=True).split("data: ")[1]))


async def test_each_agent_writes_through_its_own_conversation() -> None:
    """Meko refuses writes into a conversation another agent created (agent_id_mismatch)."""
    script = dict(SCRIPT, conversation_create=lambda a: {"id": f"conv-{a['agent_id']}"})

    def add_message(a: dict[str, Any]) -> dict[str, Any]:
        if a["conversation_id"] != f"conv-{a['agent_id']}":
            return {"error": "agent_id_mismatch", "detail": "Use the agent that created it"}
        return {"status": "accepted"}

    script["conversation_add_message"] = add_message
    p, _ = _provider(Server(script))
    await p.list_memories("t-creator-riya", None, True)  # reader thread first
    await p.add_turn("t-creator-riya", "clipz:director", "no zooms", "ok")
    await p.add_memory("t-creator-riya", "clipz:curator", "no lofi")
