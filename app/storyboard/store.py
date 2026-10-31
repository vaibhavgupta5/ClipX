"""Content-addressed immutable JSON artifacts; survive export cleanup."""

import hashlib
import json

from pydantic import BaseModel

from app.storage import Storage


def content_hash(value: BaseModel | dict[str, object]) -> str:
    """Canonical SHA-256, independent of JSON key order."""
    doc = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return hashlib.sha256(
        json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def put_artifact(store: Storage, value: BaseModel) -> str:
    """Write an immutable artifact keyed by the complete content digest."""
    digest = content_hash(value)
    key = f"artifacts/{digest}.json"
    store.put_bytes(key, value.model_dump_json().encode(), "application/json")
    return digest


def get_artifact[T: BaseModel](store: Storage, digest: str, model: type[T]) -> T:
    """Load and verify an artifact before accepting its schema."""
    import re

    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("invalid artifact digest")
    value = model.model_validate_json(store.get_bytes(f"artifacts/{digest}.json"))
    if content_hash(value) != digest:
        raise ValueError("artifact checksum mismatch")
    return value
