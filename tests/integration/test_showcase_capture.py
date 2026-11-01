"""Opt-in real browser smoke; no network is used by the unit suite."""

from pathlib import Path

import pytest
from PIL import Image

from app.showcase.capture import capture_webpage
from app.showcase.images import GeneratedImageStore
from app.showcase.models import CaptureIn

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def isolated_stack() -> None:
    """This browser integration has no database or queue dependencies."""


async def test_public_capture_has_real_pixels_and_restricted_license(tmp_path: Path) -> None:
    store = GeneratedImageStore(tmp_path, tmp_path / "cards")
    item = await capture_webpage(CaptureIn(url="https://example.com", at_word="w1"), store)
    assert not item.commercial_use and item.source_url == "https://example.com"
    with Image.open(store.dir / item.file) as image:
        assert image.size == (1280, 1000)
        assert len(image.getcolors(maxcolors=1_000_000) or []) > 10


async def test_portrait_highlight_spans_inline_elements_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import respx

    from app.showcase import capture

    async def address(url: str) -> tuple[str, str]:
        return "proof.example", "1.1.1.1"

    monkeypatch.setattr(capture, "public_address", address)
    html = (
        "<html><body><h1>Modules</h1><p>Load the <a href='#'>cached</a> module.</p></body></html>"
    )
    store = GeneratedImageStore(tmp_path, tmp_path / "cards")
    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://1.1.1.1/").respond(200, text=html, headers={"content-type": "text/html"})
        item = await capture_webpage(
            CaptureIn(
                url="https://proof.example/",
                at_word="w1",
                viewport="portrait",
                highlight_text="Load the cached module.",
                reading_mode=True,
            ),
            store,
        )
    with Image.open(store.dir / item.file) as image:
        assert image.size == (1536, 2048)
        assert image.getpixel((0, 0)) == (13, 17, 23)
