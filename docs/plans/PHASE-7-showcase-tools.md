# Phase 7: Project-showcase tools (infographics, web screenshots, annotation)

## Context

Owner request (2026-10-31): extend the Director beyond pure talking-head reel
editing so it can build "cool project showcase" content — custom infographics,
and screenshots of websites/projects pulled from the web and annotated to look
polished. This is new tool surface, not a scalability change, so it gets its
own phase rather than folding into Phase 6d (agent scalability/cost).

I checked the plugin catalog for an existing "hackathon-winning" skill to build
on per the owner's ask, rather than inventing from scratch. Nothing in the
catalog is confirmed as a hackathon winner for this exact combination (website
screenshot + annotate + infographic) — the web-search leads for that claim were
unverified blog listicles, and CLAUDE.md says not to fabricate things we can't
confirm. The closest real catalog matches, for reference/inspiration rather
than as hard dependencies:
- **ScreenshotOne** (Anthropic Directory, hosted MCP server) — website
  screenshot capture + clean Markdown extraction. Direct precedent for the
  screenshot-capture half of this phase.
- **appstore-screenshots** — capture -> device frame -> composite marketing
  overlays with Pillow. Closest architectural precedent for the
  capture-then-annotate pipeline below, even though it targets app stores.
- **Annotate** — interactive, localhost-only, sends marked-up pages back into
  a Claude Code session. Not usable server-side in an unattended backend, so
  not a dependency, just confirms "draw boxes/arrows/labels over a screenshot"
  is a well-trodden pattern.

Both new capabilities below produce an ordinary image asset that lands in the
Timeline through the **existing** insert/overlay pipeline (`Overlay` in
`app/timeline/schema.py`, `snap.overlay_window`, the renderer's existing
compositing) — this is new *content generation*, not a new *rendering*
primitive, which keeps CLAUDE.md rule 1 intact (LLM never touches FFmpeg; the
renderer stays deterministic over Timeline data either way).

## Decision: arbitrary URLs, gated like memes/logos

Capturing a **third party's live website** and compositing it into an export
is a different licensing situation from ADR-014's local asset libraries or
ADR-018's brand-logo tiles: a screenshot is the whole copyrighted UI of a site
the user doesn't own, not a CC-licensed asset or a nominative-use logo mark.

Owner decision (2026-10-31): allow capturing **any** URL, not just domains the
user owns, but gate it the same way ADR-014/018 gate unknown-license assets:
- Every `capture_webpage` result is recorded with `commercial_use=false` by
  default (manifest entry per generated image, same shape as
  `GeneratedAudioStore`'s manifest in ADR-017).
- `export(monetized=true)` refuses a timeline containing a captured screenshot
  unless the user's own chat message waives it — reuse `app/agent/director.py`'s
  existing `CONSENT` regex/guard verbatim, don't write a second consent check.
- Write this up as `ADR-024` when part A is implemented, with the URL/date of
  this decision, per CLAUDE.md's "record the decision" convention — this plan
  doc is the provisional record until then.

## Plan

### A. Website screenshot capture tool
- New tool `capture_webpage` (mvp.py model: `url`, optional `selector`/
  `full_page`, `viewport` preset) that renders a URL headlessly and returns an
  image asset. Needs a headless-browser dependency (Playwright Chromium is the
  standard choice; Python already has no browser automation dep today, so
  this is new, unlike the other phases which reused existing libs).
- Output lands in `AssetCatalog`/`ASSETS_DIR/generated/` the same way
  ElevenLabs-generated clips do today (ADR-017's `GeneratedAudioStore`
  pattern — mirror it for images: cache by `(url, selector, viewport)` hash,
  manifest records source URL + the open licensing question above, not a
  blank/assumed license).
- SSRF/safety: reuse the ingest pipeline's existing SSRF hardening approach
  (ADR from Phase 2: container allowlist + protocol whitelist) rather than a
  new ad hoc URL check — a tool that fetches arbitrary user-supplied URLs is
  exactly the shape that hardening was built for.

### B. Annotation tool (arrows, callouts, labels, device frame)
- New tool `annotate_image` operating on a captured screenshot or any
  existing library image: typed annotation list (`{type: "arrow"|"box"|
  "label", at: [x,y], text?, color?}`), rendered with Pillow (already a
  dependency) — not FFmpeg drawtext, which is unvalidated-string-prone and
  wrong for free-form shapes; Pillow drawing is the same approach ADR-014
  already uses for meme captions ("meme captions are drawn with Pillow, never
  ffmpeg drawtext").
- Ship a small set of presets (e.g. "browser chrome frame", "drop shadow +
  rounded corners") so the model picks a look by name instead of composing
  raw coordinates every time — keeps tool calls simple and self-correctable.

### C. Infographic tool
- New tool `generate_infographic` (title, stat list, style) renders a small
  HTML/CSS template (reuse the Playwright/Chromium capture path from A as the
  renderer — "render HTML to PNG" is the same primitive as "screenshot a
  URL," just pointed at a local `file://` template instead of a remote site)
  to a PNG, cached by content hash like every other expensive asset (rule 5).
- Templates live under `app/render/infographic_templates/` as static HTML
  files with `{{placeholders}}`, not LLM-generated markup — keeps the
  "LLM never writes raw strings that reach a renderer unvalidated" rule
  intact; the model supplies structured data (title/stats/style name), the
  template is fixed and reviewed like the ASS caption templates already are.

### Dependencies on Phase 6d
These are new tools, registered through the same `TOOLS` list / `tool_specs()`
/ `execute()` path Phase 6d is already working on — no separate registration
mechanism needed. If Phase 6d's MCP server lands first, these tools are
exposed over MCP for free, same as the other 35.

## Verification
- Unit tests offline: `annotate_image`/`generate_infographic` are pure given
  an input image/template (no network) — testable like any other tool in
  `tests/unit`, no network per CLAUDE.md rule 9.
- `capture_webpage` needs an `integration`-marked test (real network + headless
  browser), opt-in like the existing live-provider tests.
- `make golden` extended with one fixture reel that includes an infographic
  card and an annotated screenshot, so the compositing path gets an SSIM
  regression check like every other overlay type.

## Not resolved here
The licensing question above blocks capture of arbitrary third-party sites
being used in monetized exports by default — get an explicit owner decision
(or write it up as an ADR) before implementing part A for anything other than
the user's own domains.
