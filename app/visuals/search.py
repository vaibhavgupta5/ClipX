"""Resolve existing licensed local catalog assets into frozen project evidence."""

import hashlib
import uuid
from pathlib import Path

from app.providers.local import AssetCatalog, resolve_asset_file
from app.scenes.models import Family
from app.storage import Storage
from app.storyboard.models import EvidenceAsset
from app.visuals.evidence import freeze_image
from app.visuals.rank import RankedVisuals, rank_visuals


def search_catalog(
    catalog: AssetCatalog,
    root: Path,
    cache: Path,
    store: Storage,
    entity: str,
    role: Family,
    project_id: uuid.UUID | None = None,
) -> RankedVisuals:
    """Tag shortlist first; preserve provenance and restrictions through every transformation."""
    candidates: list[EvidenceAsset] = []
    rejected = {}
    shortlist = [
        item for kind in ("showcase", "icon", "image") for item in catalog.search(kind, entity, 5)
    ]
    for item in shortlist:
        path = resolve_asset_file(root, cache, item.id)
        if path is None:
            rejected[item.id] = "local asset missing"
            continue
        try:
            aid = "asset_" + hashlib.sha256(item.id.encode()).hexdigest()[:16]
            candidates.append(
                freeze_image(
                    store,
                    path.read_bytes(),
                    asset_id=aid,
                    source=item.source_url or item.source,
                    entity=item.title,
                    role=role,
                    license=item.license,
                    kind="observed"
                    if item.source_url and item.license == "website-screenshot-unverified"
                    else "illustrative",
                    project_id=project_id,
                    commercial_use=item.commercial_use,
                    attribution=item.attribution_text,
                    text=" ".join(item.tags),
                )
            )
        except (ValueError, OSError) as exc:
            rejected[item.id] = str(exc)
    result = rank_visuals(candidates, entity, role)
    return RankedVisuals(result.selected, {**rejected, **result.rejected})
