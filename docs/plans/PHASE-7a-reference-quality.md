# Reference-driven showcase editing (2026-10-31)

Owner request: review phases 6/7, install reputable video skills, match the supplied
Varun Mayya Short, and exercise a real 60-second explanation through the renderer.

## Priority

Keep Phase 6's typed EDL and deterministic FFmpeg pipeline. Phase 6d's streaming,
cache and MCP work improves operations but does not improve exported pixels; defer it
until the output-quality work is measured. Implement Phase 7's generated graphics
first, then prove they survive the ordinary insert/render/license path.

1. Inspect the supplied reference, recording observable style separately from guesses.
2. Install upstream video skills with repository/star/provenance records. Do not add
   third-party agent frameworks to the production runtime.
3. Add typed infographic, screenshot capture and annotation tools; generated images
   get content-addressed manifests and retain source licensing through annotations.
4. Use Pillow for infographics as well as annotations: the repo already uses it for
   headline cards, so this needs no browser for local graphics. Playwright is an
   optional dependency used only for webpage capture. Deny private/local networks,
   redirects and browser subresources as well as the initial URL.
5. Fix local render prerequisites (macOS fonts / libass availability), add a repeatable
   real-video edit/quality CLI and measure the actual export. Keep source/transcript,
   EDL, preview, final, measured QA and representative frames together.
6. Run `make check`, golden tests and a real 60-second smoke run. Report any remaining
   mismatch honestly: a passing test suite does not prove reference fidelity.

Do not invent factual statistics for generated cards. Use only claims in the source
or user-supplied data. Do not claim a skill or this product won a hackathon merely
because its author reports an unrelated win.
