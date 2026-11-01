"""Memory panel routes on the fake provider (no DB, no network)."""

import uuid

from fastapi.testclient import TestClient

from app.api.deps import require_user
from app.api.memory import get_creator_memory
from app.main import create_app
from app.memory.models import MemoryItem, Recall, RecalledItem
from app.memory.service import CreatorMemory
from app.providers.fakes import FakeContextProvider


def _client(memory: CreatorMemory | None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_creator_memory] = lambda: memory
    app.dependency_overrides[require_user] = lambda: uuid.uuid4()
    return TestClient(app)


def _memory() -> CreatorMemory:
    return CreatorMemory(FakeContextProvider(), "t")


def test_status_reports_off_without_a_key() -> None:
    r = _client(None).get("/meko/status")
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert _client(None).get("/meko/creators/riya/memories").status_code == 503


def test_remember_list_edit_approve_forget_round_trip() -> None:
    c = _client(_memory())
    stored = c.post("/meko/creators/riya/memories", json={"text": "No zoom cuts"})
    assert stored.status_code == 201
    mid = stored.json()["stored"][0]["id"]
    zones = c.get("/meko/creators/riya/memories").json()
    assert [m["text"] for m in zones["private"]] == ["No zoom cuts"]
    assert zones["private"][0]["label"] == "explicit correction"

    assert c.patch(
        f"/meko/creators/riya/memories/{mid}",
        json={"text": "No zoom cuts on my face", "agent_id": "clipz:curator"},
    ).json()
    assert c.post(
        f"/meko/creators/riya/memories/{mid}/approve", json={"agent_id": "clipz:curator"}
    ).json() == {"promoted": [mid]}
    zones = c.get("/meko/creators/riya/memories").json()
    assert zones["private"] == [] and zones["creator_canon"][0]["text"] == "No zoom cuts on my face"

    c.post("/meko/creators/riya/memories", json={"text": "upbeat music"})
    mid2 = c.get("/meko/creators/riya/memories").json()["private"][0]["id"]
    assert c.delete(f"/meko/creators/riya/memories/{mid2}?agent_id=clipz:curator").json()["ok"]


def test_agency_lesson_visible_for_any_creator() -> None:
    c = _client(_memory())
    assert (
        c.post("/meko/agency/lessons", json={"text": "Keep captions under size 56"}).status_code
        == 201
    )
    assert (
        c.get("/meko/creators/arjun/memories").json()["agency_canon"][0]["source"] == "agency_canon"
    )


def test_validation_errors_are_readable() -> None:
    c = _client(_memory())
    assert c.get("/meko/creators/Bad Name/memories").status_code == 422
    assert c.post("/meko/creators/riya/memories", json={"text": ""}).status_code == 422
    r = c.post("/meko/creators/riya/memories", json={"text": "   "})
    assert r.status_code == 422 and "empty" in r.json()["detail"]
    bad_agent = c.patch("/meko/creators/riya/memories/x", json={"text": "a", "agent_id": "root"})
    assert bad_agent.status_code == 422


def test_calls_endpoint_lists_logged_calls() -> None:
    r = _client(_memory()).get("/meko/calls")
    assert r.status_code == 200 and set(r.json()) == {"calls", "counters"}


def test_recall_event_carries_only_what_was_returned() -> None:
    from app.api.chat import recall_event

    off = recall_event(Recall(enabled=False))
    assert off == {"enabled": False, "creator": None, "ms": 0, "errors": [], "items": []}
    on = recall_event(
        Recall(
            enabled=True,
            creator="riya",
            items=[
                RecalledItem(
                    source="style",
                    scope="t-creator-riya",
                    item=MemoryItem(id="m1", text="fast cuts"),
                )
            ],
        )
    )
    assert on["items"] == [
        {
            "id": "m1",
            "text": "fast cuts",
            "source": "style",
            "label": "learned from chat",
            "scope": "t-creator-riya",
            "agent_id": None,
        }
    ]


def test_chat_body_accepts_creator_and_meko_flag() -> None:
    import pytest
    from pydantic import ValidationError

    from app.api.chat import ChatRequestBody

    body = ChatRequestBody(text="make a reel", creator="riya", meko=False)
    assert (body.creator, body.meko) == ("riya", False)
    assert ChatRequestBody(text="x").meko is True
    with pytest.raises(ValidationError):
        ChatRequestBody(text="x", creator="../etc")


def test_studio_page_wires_creator_memory() -> None:
    from app.api.studio import PAGE

    html = PAGE.read_text(encoding="utf-8")
    for needle in (
        'id="creator"',
        'id="mekoOn"',
        "creator, meko",
        '"meko_recall"',
        '"meko_stored"',
        'data-tab="memory"',
        "/meko/calls",
        "/approve",
        "/meko/agency/lessons",
        'method: "DELETE"',
        'method: "PATCH"',
    ):
        assert needle in html, needle
