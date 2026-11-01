"""CallLog: bounded, mirrored to JSONL, replayable."""

from pathlib import Path

from app.memory.calllog import CallLog, load_jsonl
from app.memory.models import MekoCall


def test_jsonl_round_trip_counters_and_since(tmp_path: Path) -> None:
    path = tmp_path / "meko" / "calls.jsonl"
    log = CallLog(path, maxlen=2)
    first = MekoCall(tool="memory_get_all", kind="recall", scope="s")
    log.record(first)
    log.record(MekoCall(tool="memory_add", kind="write", scope="s", ok=False))
    log.record(MekoCall(tool="memory_promote", kind="promote", scope="s"))
    assert [c.tool for c in log.since()] == ["memory_add", "memory_promote"]  # bounded
    assert log.counters() == {"write": 1, "errors": 1, "promote": 1}
    assert [c.tool for c in log.since(first.at)] == ["memory_add", "memory_promote"]
    path.write_text(path.read_text() + "not json\n")
    assert [c.tool for c in load_jsonl(path)] == ["memory_get_all", "memory_add", "memory_promote"]


def test_unwritable_path_never_raises(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    CallLog(blocker / "sub" / "calls.jsonl").record(MekoCall(tool="t", kind="setup", scope="s"))
