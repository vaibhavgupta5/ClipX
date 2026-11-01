"""Evidence for cards: local library first (free), guarded web capture only for user URLs."""

import asyncio
import io
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse

from PIL import Image

from app.explainer.anchors import norm, slug
from app.explainer.compile import Assets
from app.explainer.lookup import lookup
from app.explainer.models import Card
from app.media.ffmpeg import ffmpeg_path, run_capture
from app.providers.local import AssetCatalog, LibraryItem
from app.showcase.capture import capture_webpage
from app.showcase.images import GeneratedImageStore
from app.showcase.models import CaptureIn
from app.storage import Storage
from app.storyboard.models import EvidenceAsset
from app.visuals.evidence import freeze_image

URL = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
MAX_CAPTURES = 3
CAPTURE_GAP_S = 8.0  # publishers block bursts; observed with openai.com
MAX_PIXELS = 2_500_000


def extract_urls(message: str) -> list[str]:
    """Only URLs the user typed may be visited (never ones from transcripts or the model)."""
    return list(dict.fromkeys(u.rstrip(".,;") for u in URL.findall(message)))[:6]


def _same_page(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    return pa.hostname == pb.hostname and pa.path.rstrip("/") == pb.path.rstrip("/")


def _earlier_capture(catalog: AssetCatalog, url: str) -> LibraryItem | None:
    """Newest screenshot of the same page already in the showcase library (cache, rule 5)."""
    found = [i for i in catalog.items("showcase") if i.source_url and _same_page(i.source_url, url)]
    return found[-1] if found else None


def _shrunk_jpeg(data: bytes) -> bytes:
    """Library photos are large; scenes accept at most four megapixels."""
    with Image.open(io.BytesIO(data)) as im:
        rgb = im.convert("RGB")
        rgb.thumbnail((1800, 1800))
        buf = io.BytesIO()
        rgb.save(buf, format="JPEG", quality=90)
        return buf.getvalue()


@dataclass
class Gathered:
    assets: Assets = field(default_factory=Assets)
    evidence: dict[str, EvidenceAsset] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    captures: int = 0


def _freeze_library(
    store: Storage,
    gathered: Gathered,
    item: LibraryItem,
    data: bytes,
    asset_id: str,
    entity: str,
    role: str,
    project_id: uuid.UUID,
) -> str:
    asset = freeze_image(
        store,
        data,
        asset_id=asset_id,
        source=item.source_url or item.source,
        entity=entity,
        role=role,  # type: ignore[arg-type]
        license=item.license,
        commercial_use=item.commercial_use,
        attribution=item.attribution_text,
        project_id=project_id,
    )
    gathered.evidence[asset.id] = asset
    gathered.assets.sizes[asset.id] = (asset.width, asset.height)
    return asset.id


def _icon_for(catalog: AssetCatalog, label: str) -> LibraryItem | None:
    """A real brand logo only on an exact id/alias hit (never a fuzzy guess)."""
    found = catalog.get(f"icons:{norm(label)}")
    if found is not None and found[0] == "icon":
        return found[1]
    top = catalog.match("icon", label)
    return top[0][1] if top and top[0][0] >= 10 else None


def _backdrop_for(catalog: AssetCatalog, query: str) -> tuple[LibraryItem, str] | None:
    """Backdrop for a hook/payoff: videos first (tech B-roll), then photos, widening each."""
    for kind in ("video", "image"):
        found = lookup(catalog, kind, query)
        if found is not None:
            return found[0], kind
    return None


def _library_bytes(catalog: AssetCatalog, kind: str, item: LibraryItem) -> bytes:
    path = catalog.path(kind, item)
    if kind == "video":
        png = run_capture(
            [
                ffmpeg_path(), "-v", "error", "-ss", "2", "-i", str(path),
                "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-",
            ]
        )  # fmt: skip
        return _shrunk_jpeg(png)
    return _shrunk_jpeg(path.read_bytes())


async def _capture(
    card: Card,
    store: Storage,
    images: GeneratedImageStore,
    catalog: AssetCatalog,
    gathered: Gathered,
    project_id: uuid.UUID,
    sleep: Callable[[float], Awaitable[None]],
) -> None:
    host = (urlparse(card.source_url).hostname or "").removeprefix("www.")
    prose = len(card.highlight.split()) >= 4
    attempts = [(prose, card.highlight or None), (not prose, card.highlight or None)]
    if card.highlight:
        attempts.append((prose, None))
    last = ""
    for reading, phrase in attempts:
        focus: dict[str, tuple[float, float, float, float]] = {}
        try:
            item = await capture_webpage(
                CaptureIn(
                    at_word=card.start_word,
                    url=card.source_url,
                    viewport="portrait",
                    highlight_text=phrase,
                    reading_mode=reading,
                ),
                images,
                focus,
            )
        except Exception as exc:
            last = str(exc)[:140]
            if "was not found" in last:
                await sleep(2)
                continue
            earlier = _earlier_capture(catalog, card.source_url) if "blocks" in last else None
            if earlier is None:
                break  # blocked or unreachable: more attempts only annoy the site
            item, cached = earlier, True  # reuse our own earlier capture of the same page
            focus = {}
        else:
            cached = False
        data = (catalog.path("showcase", item) if cached else images.dir / item.file).read_bytes()
        asset_id = slug(f"page_{host}_{card.id}", set(gathered.evidence))
        asset = freeze_image(
            store,
            data,
            asset_id=asset_id,
            source=card.source_url,
            entity=host or "web page",
            role="proof_focus",
            license=item.license,
            kind="observed",
            commercial_use=item.commercial_use,
            attribution=card.source_url,
            project_id=project_id,
            text=phrase or "",
        )
        gathered.evidence[asset.id] = asset
        gathered.assets.proofs[card.id] = asset.id
        gathered.assets.sizes[asset.id] = (asset.width, asset.height)
        if "box" in focus and phrase:
            gathered.assets.focus[card.id] = focus["box"]
        gathered.captures += 1
        if item.attribution_text and "Internet Archive" in item.attribution_text:
            gathered.warnings.append(
                f"{host} blocks automated capture: used its Internet Archive copy"
            )
        if cached:
            gathered.warnings.append(
                f"{host} blocked capture now: reused the screenshot taken earlier of the same page"
            )
        catalog.reload("showcase")
        return
    gathered.warnings.append(f"{host or card.source_url}: not captured ({last or 'unknown'})")


async def gather(
    cards: list[Card],
    *,
    catalog: AssetCatalog,
    store: Storage,
    images: GeneratedImageStore | None,
    urls: list[str],
    project_id: uuid.UUID,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Gathered:
    """Icons and backdrops from ``assets/`` (no cost), page captures for user URLs only."""
    out = Gathered()
    labels: dict[str, str] = {}
    for c in cards:
        if c.family == "hub":
            labels[norm(c.center)] = c.center
        if c.family in ("hub", "multi_view"):
            labels.update({norm(i): i for i in c.items})
    for key, label in labels.items():
        item = _icon_for(catalog, label)
        if item is None:
            continue
        try:
            data = _shrunk_jpeg(catalog.path("icon", item).read_bytes())
            out.assets.icons[key] = _freeze_library(
                store, out, item, data, f"icon_{slug(label, set())}", label, "hub", project_id
            )
        except Exception as exc:
            out.warnings.append(f"icon {label}: {str(exc)[:80]}")
    for c in cards:
        if c.family == "impact_title" and c.backdrop:
            hit = _backdrop_for(catalog, c.backdrop)
            if hit is None:
                out.warnings.append(f"{c.id}: no library backdrop for {c.backdrop!r}")
                continue
            item, kind = hit
            try:
                out.assets.backdrops[c.id] = _freeze_library(
                    store, out, item, _library_bytes(catalog, kind, item),
                    f"back_{slug(c.id, set())}", item.title[:60], "impact_title", project_id,
                )  # fmt: skip
            except Exception as exc:
                out.warnings.append(f"{c.id}: backdrop failed ({str(exc)[:80]})")
    first = True
    for c in cards:
        if c.family != "proof_focus":
            continue
        if not any(_same_page(c.source_url, u) for u in urls):
            out.warnings.append(f"{c.id}: URL not provided by the user, skipped")
            continue
        if images is None or out.captures >= MAX_CAPTURES:
            out.warnings.append(f"{c.id}: capture skipped")
            continue
        if not first:
            await sleep(CAPTURE_GAP_S)
        first = False
        await _capture(c, store, images, catalog, out, project_id, sleep)
    return out


def text_for_uncaptured(
    cards: list[Card], proofs: dict[str, str], warnings: list[str]
) -> list[Card]:
    """A source page that could not be captured becomes a plain title card, never a fake shot.

    The card shows the planner's claim headline with the host as its label; it carries no
    screenshot, so nothing implies the page was seen. The beat keeps its timing and SFX.
    """
    out: list[Card] = []
    for c in cards:
        if c.family != "proof_focus" or c.id in proofs:
            out.append(c)
            continue
        host = (urlparse(c.source_url).hostname or "source").removeprefix("www.")
        warnings.append(f"{c.id}: {host} could not be captured, shown as a text card instead")
        out.append(
            c.model_copy(
                update={
                    "family": "impact_title",
                    "headline": c.title[:48],
                    "kicker": host.upper()[:40],
                    "source_url": "",
                    "highlight": "",
                }
            )
        )
    return out
