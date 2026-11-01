"""Meko context provider: the hosted MCP server spoken over streamable HTTP (ADR-030).

Docs: https://docs.mekodata.ai/reference/mcp-server/ (tool list), live schemas from
``tools/list`` on https://mcp.mekodata.ai/mcp (probed 2026-11-01). Behaviour relied on:

- Every tool needs a ``conversation_id``, even ``datapack_search``; we open one per scope.
- Requests without a ``User-Agent`` are rejected.
- ``memory_get_all(promoted=true)`` returns ``promoted_memories``; promoted rows leave the
  private bucket and become knowledge-base chunks (``knowledgebase_search``,
  ``metadata_filters.source == "memory"``).
- ``memory_search`` is agent-bucketed and was ~13 s per call, so recall does not use it.

No vendor SDK: plain JSON-RPC over httpx. Every call is written to the :class:`CallLog`.
Responses are UNTRUSTED DATA (rule 6): parsed into typed models, never executed.
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

from app.memory.calllog import CallLog
from app.memory.models import MekoCall, MemoryItem

PROTOCOL_VERSION = "2025-06-18"
USER_AGENT = "clipz-meko/1.0"
BOOT_THREAD = "clipz-boot"


class MekoError(RuntimeError):
    """Meko returned an error or an unreadable response."""


def _kind(tool: str) -> str:
    if tool in ("memory_get_all", "knowledgebase_search", "memory_search", "context_search"):
        return "recall"
    if tool == "memory_promote":
        return "promote"
    if tool == "memory_delete_by_id":
        return "forget"
    if tool == "memory_update":
        return "edit"
    if tool in ("memory_add", "conversation_add_message"):
        return "write"
    return "setup"


def parse_rpc_body(raw: str) -> dict[str, Any]:
    """Decode a JSON or SSE (``data:`` lines) JSON-RPC response; the last message wins."""
    data: dict[str, Any] | None = None
    for line in raw.splitlines():
        if line.startswith("data:"):
            data = json.loads(line[5:])
    if data is None and raw.strip():
        data = json.loads(raw)
    if data is None:
        raise MekoError("empty response from Meko")
    return data


def tool_payload(rpc: dict[str, Any]) -> Any:
    """The JSON a tool returned, or raise :class:`MekoError` with the server's detail."""
    if "error" in rpc:
        raise MekoError(str(rpc["error"].get("message", rpc["error"])))
    result = rpc.get("result", {})
    content = result.get("content") or []
    text = content[0].get("text", "") if content else ""
    try:
        payload = json.loads(text) if text else {}
    except json.JSONDecodeError:
        payload = {"text": text}
    if result.get("isError"):
        raise MekoError(text[:300] or "tool error")
    if isinstance(payload, dict) and "error" in payload and len(payload) <= 3:
        raise MekoError(f"{payload['error']}: {payload.get('detail', '')}"[:300])
    return payload


def _memories(payload: Any, promoted: bool) -> list[MemoryItem]:
    rows = payload.get("promoted_memories" if promoted else "memories", []) if payload else []
    return [
        MemoryItem(
            id=str(r.get("id")),
            text=str(r.get("data") or r.get("memory") or ""),
            agent_id=r.get("agent_id"),
            promoted=promoted,
        )
        for r in rows
        if r.get("id") and (r.get("data") or r.get("memory"))
    ]


class MekoContextProvider:
    """:class:`app.providers.base.ContextProvider` backed by Meko MCP."""

    provider_name = "meko"

    def __init__(
        self,
        api_key: str,
        url: str,
        log: CallLog,
        timeout_s: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        state_path: Path | None = None,
    ) -> None:
        self._url = url
        self._log = log
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self._client = httpx.AsyncClient(timeout=timeout_s, transport=transport)
        self._session: str | None = None
        self._lock = asyncio.Lock()
        self._ids = 0
        self._scopes: dict[str, str] = {}  # name -> datapack_id
        self._threads: dict[str, str] = {}  # "scope|agent" -> conversation_id (Meko binds a
        # conversation to the agent that created it: writes from another agent are refused)
        self._inflight: dict[str, asyncio.Future[str]] = {}
        self._state_path = state_path
        self._load_state()

    # --- transport ---
    async def _post(self, body: dict[str, Any]) -> httpx.Response:
        headers = dict(self._headers)
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        return await self._client.post(self._url, json=body, headers=headers)

    async def _initialize(self) -> None:
        self._session = None
        r = await self._post(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "clipz", "version": "1.0"},
                },
            }
        )
        r.raise_for_status()
        self._session = r.headers.get("Mcp-Session-Id")
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    async def _rpc(self, tool: str, args: dict[str, Any]) -> Any:
        async with self._lock:
            if self._session is None:
                await self._initialize()
            self._ids += 1
            body = {
                "jsonrpc": "2.0",
                "id": self._ids,
                "method": "tools/call",
                "params": {"name": tool, "arguments": args},
            }
        r = await self._post(body)
        if r.status_code in (400, 404) and self._session:  # session expired: re-init once
            async with self._lock:
                await self._initialize()
            r = await self._post(body)
        if r.status_code >= 400:
            raise MekoError(f"HTTP {r.status_code} from Meko")
        return tool_payload(parse_rpc_body(r.text))

    async def _call(
        self, tool: str, args: dict[str, Any], scope: str, agent_id: str | None, detail: str = ""
    ) -> Any:
        started = time.monotonic()
        ok, results = True, 0
        try:
            payload = await self._rpc(tool, args)
            results = _count(payload)
            return payload
        except (MekoError, httpx.HTTPError, json.JSONDecodeError) as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"[:200]
            raise MekoError(detail) from exc
        finally:
            self._log.record(
                MekoCall(
                    tool=tool,
                    kind=_kind(tool),  # type: ignore[arg-type]
                    scope=scope,
                    agent_id=agent_id,
                    ok=ok,
                    ms=int((time.monotonic() - started) * 1000),
                    results=results,
                    detail=detail,
                )
            )

    # --- scopes and threads (single-flight, cached on disk: rule 5) ---
    def _load_state(self) -> None:
        if self._state_path is None or not self._state_path.is_file():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._scopes.update(data.get("scopes", {}))
            self._threads.update(data.get("threads", {}))
        except (OSError, ValueError):
            pass

    def _save_state(self) -> None:
        if self._state_path is None:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps({"scopes": self._scopes, "threads": self._threads}), encoding="utf-8"
            )
        except OSError:
            pass

    async def _once(self, key: str, make: Callable[[], Awaitable[str]]) -> str:
        """Run ``make`` once per key even when many recalls ask concurrently."""
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(make())
            self._inflight[key] = task
        try:
            return await task
        finally:
            if task.done():
                self._inflight.pop(key, None)

    async def _boot_thread(self) -> str:
        if BOOT_THREAD in self._threads:
            return self._threads[BOOT_THREAD]

        async def make() -> str:
            out = await self._call(
                "conversation_create",
                {"agent_id": BOOT_THREAD, "session_id": BOOT_THREAD, "title": "clipz boot"},
                "-",
                BOOT_THREAD,
            )
            self._threads[BOOT_THREAD] = str(out["id"])
            return self._threads[BOOT_THREAD]

        return await self._once("boot", make)

    async def scope(self, name: str) -> str:
        """Datapack id for ``name``; found by exact name, else created."""
        if name in self._scopes:
            return self._scopes[name]

        async def make() -> str:
            conv = await self._boot_thread()
            found = await self._call(
                "datapack_search", {"name": name, "conversation_id": conv, "limit": 5}, name, None
            )
            packs = found.get("datapacks", []) if isinstance(found, dict) else []
            match = next((p for p in packs if p.get("datapack_name", p.get("name")) == name), None)
            if match is None:
                made = await self._call(
                    "datapack_create",
                    {"name": name, "conversation_id": conv},
                    name,
                    None,
                    "created",
                )
                pack_id = str(made["datapack_id"])
            else:
                pack_id = str(match["datapack_id"])
            self._scopes[name] = pack_id
            self._save_state()
            return pack_id

        return await self._once(f"scope:{name}", make)

    async def thread(self, scope: str, agent_id: str = "clipz") -> str:
        """One Meko conversation per (datapack, agent); stable session_id, so Meko dedups it."""
        key = f"{scope}|{agent_id}"
        if key in self._threads:
            return self._threads[key]

        async def make() -> str:
            pack = await self.scope(scope)
            out = await self._call(
                "conversation_create",
                {
                    "agent_id": agent_id,
                    "session_id": f"clipz:{scope}:{agent_id}",
                    "datapack_id": pack,
                    "title": f"ClipZ {scope}",
                },
                scope,
                agent_id,
            )
            self._threads[key] = str(out["id"])
            self._save_state()
            return self._threads[key]

        return await self._once(f"thread:{key}", make)

    async def _args(self, scope: str, agent_id: str | None) -> dict[str, Any]:
        pack = await self.scope(scope)
        conv = await self.thread(scope, agent_id or "clipz")
        args: dict[str, Any] = {"conversation_id": conv, "datapack_id": pack}
        if agent_id:
            args["agent_id"] = agent_id
        return args

    # --- memory ---
    async def list_memories(
        self, scope: str, agent_id: str | None, promoted: bool
    ) -> list[MemoryItem]:
        """``memory_get_all``: the datapack's private memories (every agent; each row carries
        its writer's agent_id) or its promoted canon. Meko does not filter this by agent_id."""
        args = await self._args(scope, agent_id)
        args.update({"promoted": promoted, "page_size": 100})
        out = await self._call("memory_get_all", args, scope, agent_id)
        return _memories(out, promoted)

    async def search_shared(self, scope: str, query: str, limit: int = 5) -> list[MemoryItem]:
        """``knowledgebase_search``: promoted canon chunks and uploaded documents."""
        args = await self._args(scope, None)
        args.update({"query": query[:500], "limit": limit, "skip_conversation": True})
        out = await self._call("knowledgebase_search", args, scope, None)
        rows = out.get("results", []) if isinstance(out, dict) else []
        items: list[MemoryItem] = []
        for r in rows:
            meta = r.get("metadata_filters") or {}
            items.append(
                MemoryItem(
                    id=str(meta.get("memory_id") or r.get("id")),
                    text=str(r.get("chunk_text", "")),
                    agent_id=meta.get("agent_id"),
                    promoted=True,
                    score=r.get("rerank_score"),
                )
            )
        return [i for i in items if i.text]

    async def add_memory(self, scope: str, agent_id: str, text: str) -> list[MemoryItem]:
        """``memory_add`` with the text stored as given."""
        args = await self._args(scope, agent_id)
        args["text"] = text
        out = await self._call("memory_add", args, scope, agent_id, text[:80])
        rows = out.get("results", []) if isinstance(out, dict) else []
        return [
            MemoryItem(id=str(r["id"]), text=str(r.get("memory", text)), agent_id=agent_id)
            for r in rows
            if r.get("id")
        ]

    async def add_turn(
        self, scope: str, agent_id: str, user: str, reply: str, seed: bool = False
    ) -> str:
        """``conversation_add_message``: Meko extracts preferences from the user side."""
        args = await self._args(scope, agent_id)
        args.update({"input": user[:4000], "output": reply[:4000]})
        if seed:
            args["seed"] = "seeded demo history"
        await self._call("conversation_add_message", args, scope, agent_id, user[:80])
        return str(args["conversation_id"])

    async def update_memory(self, scope: str, agent_id: str, memory_id: str, text: str) -> None:
        """``memory_update``."""
        args = await self._args(scope, agent_id)
        args.update({"memory_id": memory_id, "text": text})
        await self._call("memory_update", args, scope, agent_id, text[:80])

    async def delete_memory(self, scope: str, agent_id: str, memory_id: str) -> None:
        """``memory_delete_by_id``."""
        args = await self._args(scope, agent_id)
        args["memory_id"] = memory_id
        await self._call("memory_delete_by_id", args, scope, agent_id, memory_id)

    async def promote(self, scope: str, agent_id: str, memory_ids: list[str]) -> list[str]:
        """``memory_promote`` (needs owner/maintainer on the datapack)."""
        args = await self._args(scope, agent_id)
        args["memory_ids"] = memory_ids
        out = await self._call("memory_promote", args, scope, agent_id)
        done = out.get("inserted_ids", []) + out.get("updated_ids", []) if out else []
        return [str(i) for i in done]

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()


def _count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if not isinstance(payload, dict):
        return 0
    for key in ("results", "memories", "promoted_memories", "datapacks", "inserted_ids"):
        val = payload.get(key)
        if isinstance(val, list):
            return len(val)
    return 1
