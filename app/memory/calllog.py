"""Append-only log of every context-provider call: in memory for the UI, JSONL on disk for replay.

Nothing shown in the context panel is invented: it is read back from this log, which is
written only by the provider adapters at the moment a real call returns (rule A5).
"""

import json
from collections import deque
from datetime import datetime
from pathlib import Path

from app.memory.models import MekoCall

MAX_CALLS = 500


class CallLog:
    """Bounded in-memory call history, optionally mirrored to a JSONL file."""

    def __init__(self, path: Path | None = None, maxlen: int = MAX_CALLS) -> None:
        self._calls: deque[MekoCall] = deque(maxlen=maxlen)
        self._path = path

    def record(self, call: MekoCall) -> None:
        """Store one call; disk errors never break a chat turn."""
        self._calls.append(call)
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(call.model_dump_json() + "\n")
        except OSError:
            pass

    def since(self, at: datetime | None = None, limit: int = 200) -> list[MekoCall]:
        """Calls newer than ``at`` (all when None), oldest first, at most ``limit``."""
        rows = [c for c in self._calls if at is None or c.at > at]
        return rows[-limit:]

    def counters(self) -> dict[str, int]:
        """Totals per call kind plus errors, for the panel header."""
        out: dict[str, int] = {}
        for c in self._calls:
            out[c.kind] = out.get(c.kind, 0) + 1
            if not c.ok:
                out["errors"] = out.get("errors", 0) + 1
        return out


def load_jsonl(path: Path) -> list[MekoCall]:
    """Replay a call log written by :class:`CallLog`; skips malformed lines."""
    if not path.is_file():
        return []
    rows: list[MekoCall] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(MekoCall.model_validate(json.loads(line)))
        except (ValueError, TypeError):
            continue
    return rows
