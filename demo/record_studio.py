"""Record the ClipZ Studio (http://127.0.0.1:8000/app) for the demo video.

    uv run python demo/record_studio.py     # the API must be running on :8000
Writes demo/build/studio.webm. Uses the dev workspace key, same as the Studio's default.
"""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

BUILD = Path(__file__).resolve().parent / "build"
URL = "http://127.0.0.1:8000/app"
KEY = "reelforge-dev-key"
PROJECT = "devday impact preview"


async def pause(page, ms: int) -> None:
    await page.wait_for_timeout(ms)


async def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"]
        )
        ctx = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=str(BUILD / "rec"),
            record_video_size={"width": 1920, "height": 1080},
        )
        page = await ctx.new_page()
        await page.goto(URL)
        await page.evaluate(f"localStorage.setItem('rf_key', JSON.stringify('{KEY}'))")
        await page.reload()
        await pause(page, 2500)
        await page.get_by_text(PROJECT, exact=True).first.click()
        await pause(page, 3000)
        for name in ("results", "subs", "original", "timeline", "memory"):
            await page.locator(f"button.tab[data-tab='{name}']").click()
            await pause(page, 2200)
        await pause(page, 2000)
        await page.locator("#creator").select_option("riya")
        await page.locator("button.tab[data-tab='memory']").click()
        await pause(page, 5000)
        await page.locator("button.tab[data-tab='storyboard']").click()
        await pause(page, 1500)
        video = page.video
        await page.close()
        await video.save_as(BUILD / "studio.webm")
        await ctx.close()
        await browser.close()
        print("saved", BUILD / "studio.webm")


asyncio.run(main())
