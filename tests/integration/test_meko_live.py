"""Live Meko round trip (opt-in: -m integration, needs MEKO_API_KEY). Uses datapacks fixem-it-*."""

import os
import uuid

import pytest

from app.memory.calllog import CallLog
from app.memory.models import CURATOR
from app.memory.service import CreatorMemory
from app.providers.meko import MekoContextProvider
from app.settings import get_settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("MEKO_API_KEY") or get_settings().MEKO_API_KEY),
        reason="MEKO_API_KEY not set",
    ),
]


async def test_remember_recall_approve_forget_live() -> None:
    s = get_settings()
    log = CallLog()
    provider = MekoContextProvider(s.MEKO_API_KEY, s.MEKO_MCP_URL, log, timeout_s=60)
    mem = CreatorMemory(provider, "fixem-it", timeout_s=60)
    tag = uuid.uuid4().hex[:8]
    [row] = await mem.remember("probe", f"Integration probe {tag}: no zooms")
    recall = await mem.recall("probe", "zooms")
    assert any(tag in r.item.text and r.source == "correction" for r in recall.items)
    await mem.forget("probe", CURATOR, row.id)
    assert all(c.ok for c in log.since()), [c.detail for c in log.since() if not c.ok]
    await provider.aclose()
