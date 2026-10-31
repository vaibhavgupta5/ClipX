"""Cheap role/entity ranking with deterministic rejection logs and content dedupe."""

import re
from dataclasses import dataclass

from app.scenes.models import Family
from app.storyboard.models import EvidenceAsset


@dataclass(frozen=True)
class RankedVisuals:
    selected: list[EvidenceAsset]
    rejected: dict[str, str]


def rank_visuals(
    candidates: list[EvidenceAsset],
    entity: str,
    role: Family,
    *,
    limit: int = 5,
    require_observed: bool = False,
) -> RankedVisuals:
    """Exact entity and purpose outrank generic tag similarity; no model request required."""
    rejected: dict[str, str] = {}
    ranked = []
    seen = set()
    tokens = set(re.findall(r"\w+", entity.lower()))
    for asset in sorted(candidates, key=lambda a: a.id):
        reason = ""
        match = tokens & set(re.findall(r"\w+", asset.entity.lower()))
        if asset.sha256 in seen:
            reason = "duplicate source pixels"
        elif not match:
            reason = "entity mismatch"
        elif require_observed and asset.kind != "observed":
            reason = "illustration is not observed evidence"
        elif "display" not in asset.allowed_uses:
            reason = "source does not permit display"
        elif min(asset.width, asset.height) < 320:
            reason = "focal image too small for phone reading"
        if reason:
            rejected[asset.id] = reason
            continue
        seen.add(asset.sha256)
        score = 10 * (asset.role == role) + len(match) + 2 * (asset.kind == "observed")
        ranked.append((score, asset))
    ranked.sort(key=lambda x: (-x[0], x[1].id))
    for _, asset in ranked[limit:]:
        rejected[asset.id] = "outside bounded shortlist"
    return RankedVisuals([a for _, a in ranked[:limit]], rejected)
