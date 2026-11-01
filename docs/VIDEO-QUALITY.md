# Reference showcase editing and output verification

## What was inspected

Reference: [Varun Mayya, “3 GitHub repos with 150,000 stars…”](https://www.youtube.com/shorts/uIiUlZZdinM),
89 seconds, inspected locally on 2026-10-31. This is a screen-led showcase: dark
GitHub/product pages, black surroundings, highlighted text, restrained white phrase
captions and changing screenshots. It is not a yellow, uppercase talking-head preset.

`apply_showcase_style` applies the supported typography/framing choices. The Studio
**Showcase** button drafts a matching Director request. It preserves the explanation;
it cannot manufacture the reference's underlying project screens from unrelated raw
footage. The user or Director must supply relevant public project URLs or images.
Pixel-identical reproduction, automatic reference-video analysis and continuous
Ken Burns screenshot animation are not implemented.

## Plan choice

Phase 6 already supplies cuts, captions, inserts, sound and framing. Phase 7 adds the
missing visual material, so it has the most immediate quality payoff. Phase 6d
(streaming, context-cache verification, MCP, batch) remains deferred, not completed.
See [the implementation plan](plans/PHASE-7a-reference-quality.md).

## New tools

- `apply_showcase_style`: contained source over black, white line captions at 48px,
  four words per line, no caption pop, no styled transitions.
- `generate_infographic`: reviewed 1080x900 Pillow layouts, one to three claims,
  dark/paper/electric palettes. Facts must come from the transcript or user.
- `capture_webpage`: optional Playwright Chromium, desktop/mobile viewport and optional
  selector. All HTTP requests, subresources and redirect destinations use public-IP
  validation and an IP-pinned HTTPX connection with the original TLS SNI. Browser
  direct networking and WebSockets are blocked; service workers and downloads are
  disabled. Captures are bounded by time, requests, bytes and dimensions.
- `annotate_image`: normalized boxes/arrows/labels, browser frame or shadow. Only
  catalog images are accepted; source licensing and credits survive annotation.

Generated PNGs live in `ASSETS_DIR/showcase/` with an atomic manifest. Rendering inputs
and template revision determine graphic hashes; screenshot pixels and annotation
source pixels/metadata are also hashed. These are ordinary Timeline overlays, with
word anchors, immutable versions and the existing monetization guard. The model never
supplies executable markup, browser scripts or FFmpeg filter strings.

Pillow also renders infographics instead of the proposed HTML templates: local graphics
need no browser dependency. Chromium is required only for actual webpage capture.

## Installed skills

Installed in `~/.codex/skills`, available to Codex on the next turn. GitHub API star
counts checked on 2026-10-31; these are repository popularity counts, not quality scores.

- [remotion-dev/skills](https://github.com/remotion-dev/skills): 5,941 stars;
  `remotion-best-practices`, `remotion-captions`, `remotion-markup`, `remotion-render`.
- [browser-use/video-use](https://github.com/browser-use/video-use): 30,237 stars;
  installed as `video-use`, including its helper scripts.
- [affaan-m/ECC](https://github.com/affaan-m/ECC): 293,656 stars;
  `video-editing`, `verification-loop`. Its README says the author won an Anthropic
  x Forum Ventures hackathon in September 2025. That is an author-reported win,
  not evidence that this video skill won a hackathon.

No third-party skill scripts or Remotion framework were added to ClipZ's production
renderer. ClipZ keeps its typed tools and deterministic FFmpeg compiler.

## Reproduce a real-video run

```sh
uv sync --extra showcase --extra video-test
uv run --extra showcase playwright install chromium
uv run --extra showcase --extra video-test python -m scripts.quality_demo INPUT.mp4 \
  --out work/my-quality-run --model base.en
```

Optional `--graphics path.json` applies a list of `{ "tool": ..., "args": ... }`
showcase calls. Read the cached `transcript.json` first to choose real word IDs. A
screenshot used by `annotate_image` must already be in that run's asset catalog.

The CLI uses no database, paid API or model-driven edit loop. It normalizes up to
90 seconds, runs local Whisper once, applies typed tools, renders both profiles and
preserves `timeline.json`, `tool-calls.json`, `quality.json`, eight review frames,
`filmstrip.jpg`, `preview.mp4` and `final.mp4`. Transcript caches include source hash,
duration, model and language. It refuses output that fails its technical checks.

On this Mac, Homebrew's FFmpeg lacks libass. A project-local FFmpeg was downloaded
from [Martin Riedl's builds](https://ffmpeg.martin-riedl.de/) into `.venv/media-bin/`
and linked as `.venv/bin/ffmpeg`; `uv run` picks it up. Run `ffmpeg -filters` in that
environment and confirm `ass` before rendering. macOS Arial/Devanagari fonts now
have allowlisted fallback paths. Docker installs libass/fonts and Chromium itself.

## Actual test material and findings

Source: [The PrimeTime, “Vibe Coding WoW Forever Mods With Esfand”](https://www.youtube.com/watch?v=dBCLS8myarc),
a past livestream. The delivered sample is 20:00–21:00, explaining Lua module
loading and a proposed reload approach. Source downloaded at 720p; exporting at
1080x1920 does not add source detail. This is test material, not a claim of ownership
or permission to redistribute/monetize the source.

Artifacts: `work/coding-demo/`. Graphics are grounded in `require()`, Neovim and the
speaker's proposed `nil` approach; the final uncertainty/correction stays in the clip.
The generated cards explicitly describe the approach as proposed. The screenshot
comes from `https://github.com/neovim/neovim`, with source restrictions preserved.

Both profiles: 60.000s, 30fps, yuv420p, zero measured A/V duration drift, full decode
successful, integrated loudness -14.73 LUFS, true peak -2.37 dBTP. Technical QA passes.
The first run exposed AAC true-peak overshoot at -0.36 dBTP; the renderer now leaves
-2.5 dBTP pre-encode headroom, encodes 192kbps AAC at 48kHz, and the rerun passes.
Energy analysis now trims codec padding to declared duration so AAC padding cannot
create a spurious final emphasis bucket.

The filmstrip was visually inspected. Wide source text is still small on a phone;
the new full-screen cards/screenshot are more readable. Local `base.en` ASR is not a
human-corrected transcript (notably the closing “hot/disk reloading” phrase). No
listening-based audio assessment or exact-reference fidelity score is claimed.

## Verification limits

Ruff, formatting, strict mypy and all 394 unit tests passed (424 including offline
Director evals). The live public-browser
capture smoke also passed. Historical golden references have seven SSIM failures
on this Mac (about 0.94–0.96 versus 0.98); two old cases pass. Their checked-in PNGs
were preserved. They show older white caption behavior while current defaults use
active-word highlights, and local fixture/font/codec output differs. Do not call the
full `make check` gate green until those references are reconciled in a controlled
render environment. A separate showcase-graphics golden covers the new compositor.

The QA thresholds check dimensions, frame rate, compatible pixel format, EDL duration,
A/V duration drift, loudness and peak headroom. They do not prove lip sync, semantic
accuracy, screenshot relevance, caption timing accuracy or aesthetic quality.

## Local app startup

Docker Desktop and ClipZ Redis were started, and the API serves `/healthz` and `/app`
at `http://127.0.0.1:8000`. The TimescaleDB image pull failed during extraction after
the local disk filled (48MiB free at the failure). Temporary archives, the unused
full Chromium download (headless Chromium retained), this session's uv cache and
superseded test runs were removed; the delivered demo was retained. About 619MiB was
free immediately afterward. Existing user files, other projects and Docker data
were not pruned.

Disk space later recovered to about 1.6GiB as the failed pull released temporary
layers. The final readiness check reports both database and Redis unavailable;
Docker services need recovery after the extraction I/O error. Other projects and
Docker data were not pruned or restarted to recover space.

The API is **degraded**, not a working end-to-end Studio: database-backed upload/chat
needs the database image and migrations. After sufficient disk space is available,
run `docker compose up -d tiger redis`, restart the API, and start the worker with
`uv run --extra showcase arq app.workers.main.WorkerSettings`. Use the local
`TIGER_DATABASE_URL` from `.env.example` for API and worker together. A complete
Docker build was not attempted after the disk-space failure.

## Professional and reference passes (2026-10-31)

The second study inspected the full 89-second reference, its thumbnail, a four-second
contact sheet and closely spaced frames around camera moves. Observable traits:
brief speaker/page split at the opening, predominantly authentic project pages and
technical diagrams on black, warm white text highlights, quiet white sentence-case
captions beneath the page, hard cuts and short slide-up / pull-out / pan moves.
The reference's polish comes from relevant evidence and timing; tool count alone
does not establish quality.

Implemented `proof` inserts with protected subtitle space and independently selected
camera motion/entrance. Camera phase survives segment boundaries. Portrait webpage
capture uses DPR 2, exact semantic text highlighting across inline elements, instant
scrolling and an optional larger-type dark reading treatment. This treatment changes
page styling; it does not reproduce the site's original appearance. Failed remote
images retain source alt text rather than invented badges. A bounded `speaker_zoom`
on split framing enlarges embedded webcams around the actual tracked face.
Added a labelled connected flow illustration alongside code, steps and metrics cards.
These are normal typed tools/EDL fields, not baked into the test video's pixels.

Real Gemini prompt runs exposed a streaming bug: terminal SSE metadata did not include
the tool steps emitted earlier. The adapter now assembles indexed events, validates
complete JSON arguments and retains native thought signatures for replay. Explicit
`REQUIRED_TOOLS` requests report successful coverage, including read-only outcomes.
Late automatic re-export re-enters the same license/consent guard. Two real prompt
runs together completed 24 distinct tools; one uninterrupted 24-tool run is **not**
claimed. Provider daily/minute quotas interrupted further creative iteration.

`work/pro-final/final.mp4` is the safe professional pass. `work/reference-match` is the
first larger-type page-led treatment. `work/reference-ready` is the final reference
refinement: a 31.8s edit from the 60s PrimeTime excerpt, with real Lua/Neovim pages,
one labelled module-loading diagram, voice cuts, music, restrained SFX, white captions,
page camera moves and speaker/page bookends. Frame review caught a GitHub listing
loading error; the bookends use the successfully captured README detail instead.
The speaker's speculative claim and
closing correction are retained. The user explicitly authorized real screenshots
for a non-commercial test; `consent.txt`, versions and tool events preserve that choice.
This final reference refinement is a deterministic authored recipe through the real
Director tools and renderer, **not** a fresh autonomous model run or automatic learning
from a reference URL. Reproduce it from saved local checkpoints with:

```bash
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m scripts.reference_pass \
  --refine-from work/reference-match/timeline.json --out work/reference-new
```

The previous reference and refined previews measured -14.44 LUFS, -2.24 dBTP and 33ms
A/V stream-duration difference, with full decode and 1080x1920/30fps output checks.
Each run saves its own encoded-output `quality-final.json`; use that file for the
exact final measurement. Frames were reviewed at opening, page, diagram and closing
shots. The source is 720p with an embedded webcam; export at 1080x1920 cannot recover
missing source detail. ASR and listening-based mix approval remain human review tasks.

Latest local verification: Ruff, format, strict mypy and Python compilation pass.
Full non-integration run: **442 passed, 7 failed, 36 deselected**, 81% aggregate coverage
for selected changed modules (capture's network/browser path is covered separately by
integration smoke, not this percentage). The seven failures are the same preserved
historical caption/layout golden baselines described above. New showcase/proof golden
renders and both real-browser capture cases pass. The full repository gate remains
not green; no reference-fidelity score or production deployment claim is made.

### Follow-up comparison and missed compositor defect

A whole-output contact sheet compared with the reference exposed a defect missed by
the previous spot checks. In `work/reference-ready/final.mp4`, the split opening page
was chained until the closing split at 28.57s. Replacing that image appended it after
the proof overlays, so it covered their upper sections from 3.74s onward. Successful
decode, loudness and duration checks did not detect the visual defect.

Fixed split-panel chaining to stop and restart around full-screen proof shots,
independent of overlay insertion order; renderer cache revision is now 12. Two unit
orders and an actual mixed-layout golden render cover the failure. The mixed render
must match the existing isolated proof golden, without replacing that baseline.
440 unit/offline eval tests and five targeted proof/interruption tests pass; Ruff,
format and strict mypy pass. The seven earlier historical goldens remain unresolved.

The corrected export is `work/reference-reviewed/final.mp4` (31.8s, 1080x1920/30fps,
-14.44 LUFS, -2.24 dBTP, 33ms A/V stream-duration difference, full decode pass).
Opening, diagram and full-output sheets were reviewed after the fix. Comparison
image: `work/reference-reviewed/comparison/reference-vs-output.jpg`.

Creative comparison still falls short: the reference uses varied project evidence,
purposeful product/diagram states and focus changes; this edit reuses five image
assets over nine authored shots and a static three-node illustration. The opening
uses roughly a half-frame split rather than the reference's taller page panel; its
two-column README leaves a narrow text column. The enlarged embedded webcam remains
soft and retains stream graphics. The speculative excerpt's closing correction
also gives a weaker explanatory payoff. Caption color, black canvas and gentle page
motion are closer. These are frame/motion/timing observations; an auditory mix
comparison and a numeric aesthetic-fidelity score are not claimed.


## Phase 7c real livestream demonstration (2026-10-31)

`editedVideo/livestream-impact-final.mp4` is the reviewed 1080×1920, 53.08-second
edit of a 60-second public technical livestream excerpt. `work/livestream-impact/`
contains its source identity, local word transcript, immutable versions, editable
scenes, provenance/credits, actual-frame review, repair record and measured reports.
The source retains its uncertainty and correction; illustrative scenes are labelled.

Reproduce locally after installing the locked Python showcase/video-test extras,
FFmpeg with libass, local assets, Chromium and the visual bundle (`cd visuals &&
npm ci && npm run build`). `scripts/livestream_impact.py --prepare` normalizes and
transcribes; `scripts/livestream_recipe.py` authors the source-specific contract;
`python -m scripts.livestream_impact --profile final --live-review` renders/reviews.
The source-specific recipe expects this exact cached transcript, not arbitrary IDs.
Live review sends selected resized frames to the configured provider.

Technical decode, 1,589 scene-frame ownership checks and encoded audio measurements
pass (−14.49 LUFS, −2.43 dBTP, 8.97 ms A/V duration agreement). A one-scene caveat
repair reused eleven other scene artifacts and twelve compositor segments. Review
sampled twelve actual encoded frames; it did not listen to audio or watch complete
playback. The human rubric and production release gates remain distinct.

The historical goldens are retained unchanged and still fail in the reconstructed
local environment. They were not reset to claim completion. English real-media and
Hindi layout checks are not a three-case bilingual human quality benchmark.

The editable deliverable is `editedVideo/livestream-impact-project.zip`. Extract it
and run `python -m scripts.render_bundle <folder> --check` from the repository to
verify sixteen media/provenance dependencies. Omit `--check` and choose `--profile
final` to render the typed scenes locally without provider uploads. The bundle
contains the exact reviewed final and its report, original source, both Timeline
versions, reference recipe, frozen evidence permissions, audio, hashes and credits.
A fresh 540×960 preview rendered from the bundle passed full decode, dimensions,
53.08-second duration and encoded audio checks. No provider inference was used.

Final code validation passes 467 unit/offline tests and seventeen targeted integration
tests, lint, formatting and strict typing. A real Chromium Studio smoke verified
focus editing, undo and scene playback with twelve scenes and no JavaScript errors.
