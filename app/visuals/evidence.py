"""Frozen evidence validation. Cropping never removes licensing restrictions."""

import hashlib
import io
import uuid
from datetime import UTC, datetime
from typing import Literal

from PIL import Image

from app.scenes.models import Family
from app.storage import Storage
from app.storyboard.models import EvidenceAsset


def freeze_image(
    store: Storage,
    data: bytes,
    *,
    asset_id: str,
    source: str,
    entity: str,
    role: Family,
    license: str,
    kind: Literal["observed", "illustrative"] = "illustrative",
    commercial_use: bool = False,
    attribution: str = "",
    project_id: uuid.UUID | None = None,
    text: str = "",
) -> EvidenceAsset:
    """Validate frozen pixels and provenance. Refuse captured browser error pages."""
    if any(
        marker in text.lower()
        for marker in (
            "this site can't be reached",
            "access denied",
            "404 not found",
            "checking your browser",
            "just a moment...",
            "err_name_not_resolved",
        )
    ):
        raise ValueError("capture is an error/interstitial page; select a meaningful source")
    with Image.open(io.BytesIO(data)) as image:
        if image.format not in ("PNG", "JPEG", "WEBP") or min(image.size) < 64:
            raise ValueError("evidence needs a readable frozen PNG/JPEG/WebP")
        width, height = image.size
        if width * height > 4_000_000:
            raise ValueError("evidence image exceeds four megapixels")
        image.verify()
    sha = hashlib.sha256(data).hexdigest()
    key = f"renders/{project_id}/evidence/{sha}.png" if project_id else f"evidence/{sha}.png"
    asset = EvidenceAsset(
        id=asset_id,
        source=source,
        captured_at=datetime.now(UTC).isoformat(),
        sha256=sha,
        storage_key=key,
        width=width,
        height=height,
        license=license,
        entity=entity,
        role=role,
        kind=kind,
        commercial_use=commercial_use,
        attribution=attribution,
        allowed_uses=["display", "crop", "annotate"],
        text=text,
    )
    store.put_bytes(key, data, "application/octet-stream")
    store.put_bytes(
        evidence_metadata_key(asset), asset.model_dump_json().encode(), "application/json"
    )
    return asset


def evidence_metadata_key(asset: EvidenceAsset) -> str:
    """Trusted provenance sidecar, distinct from editable storyboard parameters."""
    return f"{asset.storage_key}.{asset.id}.metadata.json"


def resolve_evidence(store: Storage, assets: list[EvidenceAsset]) -> dict[str, str]:
    """Verify the exact frozen bytes before any renderer sees them."""
    result = {}
    for asset in assets:
        canonical = EvidenceAsset.model_validate_json(store.get_bytes(evidence_metadata_key(asset)))
        protected = (
            "source",
            "sha256",
            "storage_key",
            "license",
            "attribution",
            "commercial_use",
            "kind",
        )
        if any(getattr(asset, k) != getattr(canonical, k) for k in protected) or set(
            asset.allowed_uses
        ) != set(canonical.allowed_uses):
            raise ValueError(f"evidence provenance/permissions changed: {asset.id}")
        data = store.get_bytes(asset.storage_key)
        if hashlib.sha256(data).hexdigest() != asset.sha256:
            raise ValueError(f"evidence checksum mismatch: {asset.id}")
        result[asset.id] = str(store.path_for(asset.storage_key))
    return result
