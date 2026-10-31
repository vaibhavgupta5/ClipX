"""Optional browser capture with a public-only, IP-pinned HTTP transport."""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.providers.local import LibraryItem
from app.showcase.images import GeneratedImageStore
from app.showcase.models import CaptureIn


async def public_address(url: str) -> tuple[str, str]:
    """Validate every request/redirect and return its hostname and a public pinned IP."""
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 80, 443)
    ):
        raise ValueError("only public HTTP(S) URLs on ports 80/443 are allowed")
    host = parsed.hostname
    if host.lower() == "localhost" or host.lower().endswith((".localhost", ".local")):
        raise ValueError("local hosts are not allowed")
    records = await asyncio.get_running_loop().getaddrinfo(
        host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM
    )
    addresses = [str(record[4][0]) for record in records]
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError("private, reserved and mixed public/private destinations are blocked")
    return host, addresses[0]


async def capture_webpage(
    params: CaptureIn,
    store: GeneratedImageStore,
    focus_out: dict[str, tuple[float, float, float, float]] | None = None,
) -> LibraryItem:
    """Enforce a wall-clock budget including JavaScript/font waits and browser startup.

    ``focus_out["box"]`` receives the highlighted phrase's normalized (x, y, w, h) in the
    screenshot, so a scene can annotate exactly what the page says.
    """
    async with asyncio.timeout(45):
        return await _capture_public_page(params, store, focus_out)


async def _capture_public_page(
    params: CaptureIn,
    store: GeneratedImageStore,
    focus_out: dict[str, tuple[float, float, float, float]] | None = None,
) -> LibraryItem:
    """Capture a bounded viewport; browser networking only uses validated pinned requests."""
    await public_address(params.url)
    data = params.model_dump(exclude={"at_word", "duration_ms", "layout"})
    try:
        from playwright.async_api import Route, ViewportSize, async_playwright
    except ImportError:
        raise ValueError(
            "web capture needs uv sync --extra showcase; playwright install chromium"
        ) from None
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            viewport: ViewportSize = (
                {"width": 1280, "height": 1000}
                if params.viewport == "desktop"
                else {"width": 540, "height": 960}
            )
            if params.viewport == "portrait":
                viewport = {"width": 768, "height": 1024}
            context = await browser.new_context(
                viewport=viewport,
                service_workers="block",
                accept_downloads=False,
                color_scheme="dark",
                device_scale_factor=2 if params.viewport == "portrait" else 1,
            )
            # Block websockets and all browser-direct network. Host and TLS SNI stay
            # original while the HTTP transport connects to the IP we actually checked.
            await context.route_web_socket("**/*", lambda ws: ws.close())
            budget = {"requests": 0, "bytes": 0}
            semaphore = asyncio.Semaphore(8)
            async with httpx.AsyncClient(
                timeout=10, trust_env=False, follow_redirects=False
            ) as client:

                async def route_request(route: Route) -> None:
                    try:
                        if route.request.method != "GET":
                            await route.abort()
                            return
                        budget["requests"] += 1
                        if budget["requests"] > 120:
                            await route.abort()
                            return
                        async with semaphore:
                            host, ip = await public_address(route.request.url)
                            parsed = urlsplit(route.request.url)
                            ip_host = f"[{ip}]" if ":" in ip else ip
                            address = urlunsplit(
                                (parsed.scheme, ip_host, parsed.path, parsed.query, "")
                            )
                            headers = {"host": host, "user-agent": "ClipZ-Showcase/1.0"}
                            async with client.stream(
                                "GET", address, headers=headers, extensions={"sni_hostname": host}
                            ) as response:
                                chunks: list[bytes] = []
                                async for chunk in response.aiter_bytes():
                                    budget["bytes"] += len(chunk)
                                    if budget["bytes"] > 12_000_000:
                                        raise ValueError("page exceeds capture budget")
                                    chunks.append(chunk)
                                forwarded = {
                                    k: v
                                    for k, v in response.headers.items()
                                    if k.lower() in {"content-type", "location"}
                                }
                                await route.fulfill(
                                    status=response.status_code,
                                    headers=forwarded,
                                    body=b"".join(chunks),
                                )
                    except Exception:
                        await route.abort()

                await context.route("**/*", route_request)
                page = await context.new_page()
                response = await page.goto(
                    params.url, wait_until="domcontentloaded", timeout=30_000
                )
                if response is None or response.status >= 400:
                    status = "no response" if response is None else f"HTTP {response.status}"
                    blocked = response is not None and response.status in (401, 403, 429)
                    raise ValueError(
                        f"webpage did not load successfully ({status}"
                        + (
                            "; the site blocks automated capture: use another source"
                            if blocked
                            else ""
                        )
                        + ")"
                    )
                await page.evaluate("document.fonts.ready")
                # Do not export broken-image glyphs when a remote badge/CDN refuses
                # capture. Retain its source-provided alt text instead of inventing art.
                await page.evaluate("""async () => {
                    await Promise.race([
                      Promise.all([...document.images].map(img=>img.complete ? Promise.resolve() :
                        new Promise(r=>{img.addEventListener('load',r,{once:true});
                                        img.addEventListener('error',r,{once:true});}))),
                      new Promise(r=>setTimeout(r,1500))]);
                    document.querySelectorAll('img').forEach(img=>{
                      if (img.complete && img.naturalWidth===0) {
                        const alt=document.createElement('span');
                        alt.textContent=img.alt || ''; img.replaceWith(alt);
                      }
                    });
                }""")
                if params.reading_mode:
                    # A fixed reading stylesheet, never caller-provided markup/code.
                    await page.add_style_tag(
                        content="""
                        html {background:#0d1117!important;scroll-behavior:auto!important;}
                        body { background:#0d1117!important; color:#e6edf3!important;
                               font-size:32px!important; line-height:1.40!important; }
                        .markdown-body {font-size:26px!important;}
                        a {color:#8bb9f0!important;} pre,code {background:#161b22!important;}
                        p,li {max-width:38em;} h1,h2,h3 {color:#f3f5f7!important;}
                    """
                    )
                if params.highlight_text:
                    found = await page.evaluate(
                        """text => {
                        const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                        let node, combined='', positions=[];
                        while ((node = walk.nextNode())) {
                          const tag = node.parentElement?.tagName;
                          if (['SCRIPT','STYLE','MARK'].includes(tag)) continue;
                          if (!node.parentElement?.getClientRects().length) continue;
                          for (let i=0;i<node.textContent.length;i++) {
                            let c=node.textContent[i];
                            if (/\\s/.test(c)) c=' ';
                            // Case/typography-insensitive, one char per source char.
                            const low=c.toLowerCase(); if (low.length===1) c=low;
                            c=c.replace(/[\u2018\u2019]/,"'").replace(/[\u201c\u201d]/,'"').replace(/[\u2013\u2014]/,'-');
                            if (c===' ' && combined.endsWith(' ')) continue;
                            combined+=c; positions.push([node,i]);
                          }
                        }
                        const query=text.replace(/\\s+/g,' ').toLowerCase()
                          .replace(/[\u2018\u2019]/g,"'").replace(/[\u201c\u201d]/g,'"')
                          .replace(/[\u2013\u2014]/g,'-');
                        const at=combined.indexOf(query);
                        if (at<0) return false;
                        const [start,so]=positions[at], [end,eo]=positions[at+query.length-1];
                        const range=document.createRange();
                        range.setStart(start,so); range.setEnd(end,eo+1);
                        const mark=document.createElement('mark');
                        mark.id='clipz-focus';
                        mark.style.cssText='background:#f1f0e7;color:#111;'+
                          'padding:1px 3px;border-radius:2px';
                        mark.appendChild(range.extractContents()); range.insertNode(mark);
                        mark.querySelectorAll('*').forEach(el=>el.style.color='#111');
                        mark.scrollIntoView({behavior:'instant',block:'center',inline:'nearest'});
                        return true;
                    }""",
                        params.highlight_text,
                    )
                    if not found:
                        raise ValueError(
                            f"highlight_text {params.highlight_text!r} was not found on the page"
                        )
                    await page.locator("#clipz-focus").scroll_into_view_if_needed(timeout=5000)
                    await page.evaluate("""() => new Promise(resolve =>
                        requestAnimationFrame(() => requestAnimationFrame(resolve)))""")
                if params.selector:
                    target = page.locator(params.selector).first
                    await target.wait_for(timeout=5000)
                    box = await target.bounding_box()
                    dpr = 2 if params.viewport == "portrait" else 1
                    if box is None or box["width"] * box["height"] * dpr**2 > 4_000_000:
                        raise ValueError("selector is missing or exceeds 4 megapixels")
                    png = await target.screenshot(timeout=5000)
                else:
                    if focus_out is not None and params.highlight_text:
                        mark = await page.locator("#clipz-focus").bounding_box()
                        if mark is not None:
                            vw, vh = viewport["width"], viewport["height"]
                            x0, y0 = max(0.0, mark["x"] / vw), max(0.0, mark["y"] / vh)
                            focus_out["box"] = (
                                round(x0, 4),
                                round(y0, 4),
                                round(min(1 - x0, mark["width"] / vw), 4),
                                round(min(1 - y0, mark["height"] / vh), 4),
                            )
                    png = await page.screenshot(full_page=False, timeout=5000)
                return await asyncio.to_thread(store.capture, data, png, params.url)
        finally:
            await browser.close()
