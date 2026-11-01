"""Showcase tools exercise provenance, immutable placement and the real Director path."""

import io
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from pydantic import ValidationError

from app.agent.context import system_prompt
from app.agent.director import run_director
from app.providers.fakes import ScriptedToolLLM
from app.providers.local import AssetCatalog, resolve_asset_file
from app.providers.tools import ToolCall, ToolTurnReply
from app.showcase.capture import public_address
from app.showcase.images import GeneratedImageStore
from app.showcase.models import AnnotateIn, Annotation, CaptureIn, InfographicIn
from app.tools.executor import ToolFailure, ToolOutcome, ToolState, execute
from tests.unit.agent.memory_ws import MemoryWorkspace
from tests.unit.timeline.test_ops import _timeline


def test_image_cache_ignores_placement_and_is_catalog_resolvable(tmp_path: Path) -> None:
    store = GeneratedImageStore(tmp_path, tmp_path / "cards")
    params = InfographicIn(
        title="Three projects", stats=[{"value": "3", "label": "Projects"}], at_word="w1"
    )
    item = store.infographic(params)
    again = store.infographic(
        params.model_copy(
            update={"at_word": "w3", "duration_ms": 1200, "motion": "pan_up", "entrance": "cut"}
        )
    )
    assert again == item
    path = resolve_asset_file(tmp_path, tmp_path / "cards", item.id)
    assert path is not None
    with Image.open(path) as image:
        assert image.size == (1080, 900)
    assert AssetCatalog(tmp_path, tmp_path / "cards").get(item.id) == ("showcase", item)
    assert len(store._read()) == 1


def test_flow_diagram_is_distinct_and_licensed_as_illustration(tmp_path: Path) -> None:
    store = GeneratedImageStore(tmp_path, tmp_path / "cards")
    params = InfographicIn(
        at_word="w1",
        variant="flow",
        title="Load and cache",
        stats=[
            {"value": "require()", "label": "Find the requested module"},
            {"value": "package.loaded", "label": "Reuse the loaded result"},
        ],
        source_label="Illustration of module loading",
    )
    item = store.infographic(params)
    other = store.infographic(params.model_copy(update={"variant": "steps"}))
    assert item.id != other.id and item.commercial_use
    with Image.open(store.dir / item.file) as image:
        assert image.size == (1080, 1060)
        # Connector passes between the two module nodes.
        assert image.getpixel((540, 530)) == (94, 158, 140)


def test_annotations_cannot_launder_a_screenshot_license(tmp_path: Path) -> None:
    store = GeneratedImageStore(tmp_path, tmp_path / "cards")
    buffer = io.BytesIO()
    Image.new("RGB", (800, 600), "#142038").save(buffer, "PNG")
    original = store.capture(
        {"url": "https://example.com"}, buffer.getvalue(), "https://example.com"
    )
    assert not original.commercial_use
    annotated = store.annotate(
        AnnotateIn(
            asset_id=original.id,
            at_word="w3",
            annotations=[
                Annotation(type="box", x=0.1, y=0.1, x2=0.5, y2=0.5, text="Feature"),
            ],
        )
    )
    assert not annotated.commercial_use and annotated.source_url == original.source_url
    catalog = AssetCatalog(tmp_path, tmp_path / "cards")
    # A 3s fixture has no post-hook word, so this test uses the split panel placement.
    out = execute(
        "annotate_image",
        {"asset_id": original.id, "at_word": "w1", "layout": "split_top"},
        ToolState(_timeline(), catalog=catalog, prepared=annotated),
    )
    assert isinstance(out, ToolOutcome) and out.timeline is not None
    refused = execute("export", {"monetized": True}, ToolState(out.timeline))
    assert isinstance(refused, ToolFailure) and refused.errors[0].code == "personal_use_assets"


def test_showcase_style_is_immutable_and_preserves_speech() -> None:
    original = _timeline()
    out = execute("apply_showcase_style", {}, ToolState(original))
    assert isinstance(out, ToolOutcome) and out.timeline is not None
    assert out.timeline.reframe == "contain" and out.timeline.captions.size_px == 48
    assert out.timeline.captions.mode == "line" and out.timeline.captions.base_color == "#FFFFFF"
    assert out.timeline.video_clips == original.video_clips
    assert original.reframe == "center" and original.captions.size_px == 84


def test_showcase_window_begins_with_its_word_and_can_open_the_video(tmp_path: Path) -> None:
    from app.timeline import snap

    store = GeneratedImageStore(tmp_path, tmp_path / "cards")
    params = InfographicIn(
        title="Projects",
        stats=[{"value": "3", "label": "Projects"}],
        at_word="w1",
        duration_ms=2600,
    )
    item = store.infographic(params)
    catalog = AssetCatalog(tmp_path, tmp_path / "cards")
    result = execute(
        "generate_infographic",
        params.model_dump(),
        ToolState(
            _timeline(),
            catalog=catalog,
            prepared=item,
        ),
    )
    assert isinstance(result, ToolOutcome) and result.timeline is not None
    overlay = result.timeline.overlays[0]
    assert snap.overlay_window(result.timeline, overlay) == (0.0, 2.6)
    assert result.output(version=2).model_dump()["asset_id"] == item.id


@pytest.mark.parametrize(
    "args",
    [
        {"type": "box", "x": -1, "y": 0},
        {"type": "label", "x": float("nan"), "y": 0},
        {"type": "label", "x": 0, "y": 0, "color": "red;filter"},
    ],
)
def test_annotation_coordinates_and_color_are_bounded(args: dict) -> None:
    with pytest.raises(ValidationError):
        Annotation.model_validate(args)


async def test_director_generates_image_without_audio_provider(tmp_path: Path) -> None:
    ws = MemoryWorkspace(_timeline())
    ws.catalog = AssetCatalog(tmp_path, tmp_path / "cards")
    args = {
        "title": "Projects",
        "stats": [{"value": "3", "label": "Projects"}],
        "at_word": "w1",
        "layout": "split_top",
    }
    llm = ScriptedToolLLM(
        [
            ToolTurnReply(
                calls=[ToolCall(id="a", name="generate_infographic", args=args)],
                stop_reason="tool_use",
            ),
            ToolTurnReply(text="Added a project card."),
        ]
    )
    result = await run_director(llm, ws, system_prompt("data"), "Add a project card")
    assert result.versions == [2] and ws.render_calls == ["preview"]
    assert ws.timeline().overlays[0].asset.startswith("showcase:")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost",
        "http://127.0.0.1",
        "http://169.254.169.254",
        "http://[::1]",
        "http://10.0.0.1",
        "https://user:pass@example.com",
        "https://example.com:8000",
    ],
)
async def test_capture_blocks_local_private_and_credential_urls(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # DNS is faked: unit tests never depend on network resolution.
    import asyncio
    import socket
    from urllib.parse import urlsplit

    host = urlsplit(url).hostname or "127.0.0.1"
    fake = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, 80))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake)
    with pytest.raises(ValueError):
        await public_address(url)


async def test_capture_rejects_mixed_dns_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import socket

    fake = AsyncMock(
        return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
            for ip in ("1.1.1.1", "127.0.0.1")
        ]
    )
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake)
    with pytest.raises(ValueError, match="mixed"):
        await public_address("https://example.com")


def test_capture_schema_never_accepts_arbitrary_browser_code() -> None:
    with pytest.raises(ValidationError):
        CaptureIn(url="https://example.com", at_word="w1", script="fetch('private')")
