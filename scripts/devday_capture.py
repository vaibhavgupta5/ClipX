"""Capture source pages for the DevDay demo through ClipZ's guarded public capture tool.

Pages are public news/announcement pages captured with the user's explicit request for
screenshots; they are recorded as personal/non-commercial evidence (never monetised).
"""

import asyncio
import json
import sys
from pathlib import Path

from app.showcase.capture import capture_webpage
from app.showcase.images import GeneratedImageStore
from app.showcase.models import CaptureIn

ROOT = Path("work/devday-impact")
PAGES = {
    "page_dots_always_on": ("https://openai.com/index/introducing-dots/", "always-on agents"),
    "page_dots_apps": ("https://openai.com/index/introducing-dots/", "over 4,000 apps"),
    "page_dots_control": ("https://openai.com/index/introducing-dots/", "always stay with you"),
    "page_techcrunch": (
        "https://techcrunch.com/2026/09/29/openai-launches-dots-its-bubbly-agentic-avatar/",
        "OpenAI launches dots",
    ),
}


async def main() -> None:
    store = GeneratedImageStore(ROOT / "captures", ROOT / "captures" / "memes")
    only = set(sys.argv[1:])
    results: dict[str, dict[str, object]] = {}
    for key, (url, phrase) in PAGES.items():
        if only and key not in only:
            continue
        if results:
            await asyncio.sleep(20)  # space requests; publishers block bursts
        # Announcement prose reads best in the tool's reading mode; news pages keep styling.
        reading = "openai.com" in url
        params = CaptureIn(
            at_word="w1", url=url, viewport="portrait", highlight_text=phrase, reading_mode=reading
        )
        try:
            item = await capture_webpage(params, store)
        except Exception as exc:  # report every page; one blocked site must not hide the rest
            results[key] = {"url": url, "error": f"{type(exc).__name__}: {exc}"[:300]}
            continue
        results[key] = {"url": url, **item.model_dump(mode="json")}
    path = ROOT / "captures.json"
    merged = json.loads(path.read_text()) if path.exists() else {}
    merged.update(results)
    path.write_text(json.dumps(merged, indent=2))
    for key, value in results.items():
        print(key, value.get("error") or value.get("file"), value.get("license", ""))


if __name__ == "__main__":
    asyncio.run(main())
