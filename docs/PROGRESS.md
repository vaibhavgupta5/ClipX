# Progress

## Phase 0: Foundation (DONE — gate GO)
- Stack up: compose (pgvector pg16, redis7, Garage s3, api, worker-cpu); /readyz green.
- FastAPI health/ready, settings+logging+OTEL, SQLAlchemy 8-table model + migration r1 (upgrade/downgrade verified).
- Storage abstraction (SigV4, path-style) verified vs Garage incl. presigned round-trip.
- Provider Protocols + fakes; no-vendor-imports CI test; lavfi fixtures (5/30/89/91 s, VFR, landscape); GH Actions CI.
- Gate: docs/gates/PHASE-0.md. Gaps: real en/hi fixtures needed (user); provider choices deferred to Ph 6/7.

## Phase 1: Timeline core (DONE — gate GO)
- Frozen EDL schema, 14 pure ops, word-ID snapping, validators, versioning, LLM summary.
- 100% line coverage on app/timeline; hypothesis properties green; CRUD API with 422 actionable errors.
- Gate: docs/gates/PHASE-1.md. Gaps: transcripts client-supplied until Phase 3; asset IDs opaque until Phase 2.

## Phase 2: Ingest (DONE — gate GO)
- Presigned upload + complete + arq ingest worker + SSE progress; end-to-end verified vs compose.
- Normalization (CFR/SDR/rotation/48k stereo), 540p proxy (0.5 s GOP), 16 kHz ASR audio, waveform JSON.
- Fixture matrix green (VFR/silent/mono/91s-reject/corrupt); SSRF hardening (container allowlist + protocol whitelist).
- Gate: docs/gates/PHASE-2.md. Gaps: HDR fixture + rotation-metadata fixture need real phone clips.

## Phase 3: Analysis (DONE — gate GO)
- Bundle models/protocols/fakes; real VAD/scenes/energy/fillers; LLM beats/romanize/emphasis (strict JSON+retry).
- Lazy whisper/silero/mediapipe adapters (deps deferred to GPU track); content-hash cache (zero-call second run proven).
- analyze_asset worker + analysis/transcript endpoints; transcript-free project creation.
- Gate: docs/gates/PHASE-3.md. Gaps: real ASR untested (no speech fixtures/keys); faces empty until Phase 9.

## Phase 4: Renderer (DONE — gate GO)
- Typed filtergraph, ASS captions (EN+HI), EDL compiler, two-pass -14 LUFS audio, segment cache.
- 9 goldens (SSIM ≥ 0.98); 30 s preview 12.5 s CPU; render worker + API; injection fuzz green.
- Gate: docs/gates/PHASE-4.md. Gaps: NVENC untested; face reframe = center; animation deferred to styles.

## Phase 5: Agent core + MVP (PARTIAL GATE — live Gemini items pending a key; docs/gates/PHASE-5.md)
- Stack pivot (owner, 2026-10-10): MongoDB (ADR-011), local ./upload ./work ./editedVideo (ADR-010),
  Gemini only via the stateless Interactions API (ADR-012), local licensed asset libraries (ADR-014).
- Built: tool registry + pure executor (16 tools); Director loop (caps, validation, one preview/turn,
  literal router, fenced untrusted data); chat SSE API over a Mongo workspace; agent_runs cost log
  (ADR-013); preview/render follow-up events; 30-case eval harness (CI scripted + `make eval-live`);
  demo script verified on the live stack up to the model-driven turns; real CPU transcription.
- Assets (`make assets`): music 40 (8 genres x 5), images 38, GIFs 7, memes 39 (personal-use only;
  monetised exports refuse them). Manifests tracked, media not.
- Stubbed / gaps: Gemini non-streamed; live evals + first-token pending a key; range preview = full;
  no SFX pack; GIF library thin; Hindi real fixture needed.
- Next: run `make eval-live` + demo with GEMINI_API_KEY, then Phase 6 (music bed + ducking using the
  local music library, attribution output, SFX).

## Phase 6: Pro editing, sound design, ElevenLabs (IN PROGRESS; plan docs/plans/PHASE-6-pro-editing.md)
- Done: libraries widened (140 images in 13 categories, 92 memes, 36 SFX in 12 types); punch-in zooms
  (smoothstep envelope), cut transitions (zoom_in / flash / whip); SFX mixing + `auto_sfx` synced to
  cuts, inserts and zooms; request-coverage follow-up and re-export after late edits in the Director.
- ElevenLabs (ADR-017): httpx adapter (sound effects, speech with timestamps, dubbing); generated audio
  cached by hash in `assets/generated/` with licence by plan; tools `generate_sfx`, `add_voiceover`,
  `remove_voiceover`, `dub_video` (arq `dub_task`); renderer swaps in the dub and ducks the speaker
  under voiceovers; credits for free-plan output. All tested offline (mock transport, real ffmpeg mix).
- Gemini Video Critic: sample preview frames + transcript -> structured quality critique across 5 axes
  (hook strength, pacing, caption legibility, visual variety, audio balance); integrated 2-iteration
  self-correction loop in the Director with `critic_feedback` events.
- Stubbed / gaps: live ElevenLabs / Gemini live calls pending API keys; captions follow source transcript after dub.
- Next: Snowflake eval judge, DigitalOcean deploy, judges' pitch, DEV post, Tiger Data justification PDF.

## Phase 6b: Director quality, relevant visuals, brand icons (plan docs/plans/PHASE-6b-director-and-app.md)
- Built: keyword engine + `auto_visuals` + query-less `add_inserts` (ADR-019); 77 brand/tech logo
  tiles (ADR-018); per-kind duration caps (no more 6-15 s images); split-screen panel hand-over;
  shared overlay windows; transitions and whooshes only at real cuts; coverage autofix (music + SFX
  are always applied when asked); role-based `director.txt` + `plan_edit`.
- Studio web app at `/app` (ADR-020): upload, brainstorm -> final prompt, Director chat with
  live tool steps, plan card, results player + download, clickable subtitles, undo/redo.
  Verified live on testInput.mp4: every requested item applied (split screen, banner, captions,
  keyword visuals incl. the Claude logo, zooms, transitions, music + SFX, export).
- Integrated the other session's work-in-progress (split-screen layout, procedural B-roll videos,
  headline cards, critic) and made it pass `make check`.
- Gaps: logo tiles are personal-use until the owner decides (ADR-018); 7 curated clips unverified;
  the image library's tags limit relevance (e.g. "technology" is broad); the critic still reviews the
  timeline summary, not rendered frames.

## Phase 6c: My style + framing fixes (plan docs/plans/PHASE-6c-style-and-framing.md, ADR-021)
- Built: style learning from the user's own edited reels (`app/style/learn.py`, pure, weighted
  majority/median, exported reels 2x, habits need >= half the reels, counts sized to the new video);
  `GET /projects/{id}/style-prompt`; studio "✦ My style" button -> review card (habit chips with
  shares, editable prompt, Send to Director / Discard). Verified live on the dev workspace (7 reels,
  3 exported) and in headless Chromium.
- Fixed: transitions at every breath trim (regression), adaptive inserts never opening the split
  view without an explicit layout, adaptive segment reframe decided twice, meme caption windows;
  `make check` green again (ruff/format errors from the adaptive commit).
- Gaps: profiles are recomputed per request, not saved or named; no LLM tailoring of the draft to
  the new transcript (the Director does that); the monetised flag of past exports is not stored, so
  the draft says "export" and the consent guard asks when needed.
- Face framing (ADR-022): CPU face tracking (OpenCV YuNet, vendored MIT model) at render time,
  cached by master hash; split view and `face` mode pan smoothly to keep the speaker's face in the
  panel (head-room bias when no face is found). Verified on a real portrait vlog: heads that the
  centre crop cut are now kept. Gaps: the worker image must be rebuilt for the new dependency;
  analysis bundles still carry no faces (inserts do not avoid faces yet); one face is followed
  (the largest), not the active speaker.

## Phase 7a: Reference showcase editing and real output QA (2026-10-31)
- Reviewed Phase 6/6b/6c/6d and Phase 7 plans. Prioritized graphics/output verification;
  Phase 6d's caching, streaming, MCP and batch remain deferred.
- Inspected the supplied Varun Mayya Short, added `apply_showcase_style` and a Studio
  Showcase prompt button: black contained framing, restrained white phrase captions,
  hard cuts. New `showcase` overlay layout preserves UI text rather than cropping it.
- Added typed `generate_infographic`, `capture_webpage`, `annotate_image` tools through
  the existing Director/EDL/catalog/render path. PNG manifests are atomic and content
  addressed; annotations inherit source licensing; screenshots remain personal-use.
  Browser capture validates/pins all HTTP destinations, including subresources and
  redirects, and limits bytes/requests/pixels/time. Pillow renders local cards.
- Installed seven upstream video/verification skills; repository star counts, sources
  and the limits of the hackathon-win claim are recorded in docs/VIDEO-QUALITY.md.
- Real 60s PrimeTime livestream explanation rendered in preview and 1080x1920 final,
  with grounded Lua/Neovim cards and an annotated live screenshot. Both exports pass
  technical QA: 30fps, yuv420p, zero duration drift, -14.73 LUFS, -2.37 dBTP, full decode.
  Artifacts: work/coding-demo/{final.mp4,preview.mp4,timeline.json,quality.json,filmstrip.jpg}.
- Real output caught AAC overshoot; fixed pre-encode headroom, 48kHz/192kbps export.
  Fixed AAC padding adding a bogus energy bucket; added allowlisted macOS font paths.
  `scripts/quality_demo.py` reproduces local transcription, typed edits and measured QA.
- Verification: ruff/format/mypy green, 394 unit tests green, live browser smoke green;
  new showcase golden added. Full non-integration suite has seven historical golden
  SSIM failures on this Mac; old reference PNGs preserved, full phase gate NOT green.
- Gaps: exact reference reproduction/automatic reference analysis and continuous image
  motion are not implemented; wide source text remains small; base.en ASR needs human
  correction. API/model-driven editing and container image build are separate checks.
- Local API and Redis started; TimescaleDB image extraction failed when disk space
  reached 48MiB. Removed only this run's temporary downloads/cache/superseded outputs,
  retaining the deliverable (~619MiB free afterward). `/app` is reachable but database
  readiness remains degraded; end-to-end Studio startup needs more local disk space.
  Later cleanup released failed Docker layers (~1.6GiB free); final readiness reports
  database and Redis unavailable after Docker's extraction I/O error. Offline tests
  plus evals: 424 passed; live capture + new showcase golden: 2 passed.

## Phase 7b: Professional and reference refinements (2026-10-31)
- Inspected full reference footage and motion samples. Implemented `proof` composition:
  black gutters, protected subtitle band, slide-up entrances and per-shot pull/pan moves.
  Added portrait DPR2 capture, source text highlighting, larger-type reading mode,
  source alt-text fallback and connected flow illustrations. Speaker zoom is bounded
  and follows existing face tracks in split framing. Director/critic prompts now
  distinguish restrained page-led reference craft from viral caption styling.
- Real Gemini tests exercised 24 distinct successful tools across two runs, caught
  dropped SSE tool calls and a late re-export consent bypass; both fixed with tests.
  Interrupted model quota runs are retained as evidence, not represented as complete.
- Authored final reference recipe uses actual typed tools, real web captures, the
  deterministic renderer and the user's explicit non-commercial screenshot consent.
  Output: `work/reference-ready/final.mp4`; prior safe professional pass remains
  `work/pro-final/final.mp4`. Each keeps immutable EDL, events, preview and measured QA.
- Full local suite: 442 passed, seven existing golden mismatches, 36 deselected.
  Lint/format/mypy/compilation pass; browser capture and new proof/showcase goldens pass.
  Full phase gate remains NOT green, Studio infra remains degraded as recorded above.
  See `docs/VIDEO-QUALITY.md` for reproducibility, precise scope and remaining limits.
- Follow-up comparison caught a missed split-panel leak over proof shots in the
  delivered `reference-ready` export. Fixed chaining across full-screen proof windows
  independently of insertion order; added mixed-layout golden regression coverage.
  Corrected artifact: `work/reference-reviewed/final.mp4`. Export checks pass; 440
  unit/offline evals and five targeted proof tests pass. Creative comparison still
  shows repetitive page evidence, static diagrams and source-webcam softness.

## Phase 7c: Hybrid visual storytelling (implementation + real demo, 2026-10-31)
- Researched 12 GitHub repositories using metadata and selected source files.
  Proposed hybrid: existing ClipZ EDL/FFmpeg core plus HyperFrames visual scenes,
  persistent storyboards, cue-based state changes and actual-output review.
- Detailed recommendation, repo critiques, source links, proposed AI budgets,
  implementation milestones and quality acceptance gates are recorded in
  `docs/plans/PHASE-7c-hybrid-visual-storytelling.md`.
- Implemented strict storyboard/evidence/scene contracts, immutable artifacts,
  source-to-frame compilation, seven local HyperFrames families, state-changing
  diagrams, source-relative annotations, local fonts, protected captions and cache reuse.
- Added actual image payloads and encoded-output review, bounded repairs/checkpoints,
  optimistic version commits, API/worker/SSE integration, owned evidence imports and
  Studio storyboard/focus/thumbnail/preview controls. Existing tools/snapshots remain.
- Created a real 60-second 1080p livestream source demonstration, tightened to 53.08 s:
  `editedVideo/livestream-impact-final.mp4`. Twelve scenes combine real speaker footage,
  licensed B-roll, official screenshots, annotated proof, architecture, a preserved
  negative result, subtitles, music and SFX. Sources, editable Timeline, versions,
  actual-frame reviews and technical metrics live under `work/livestream-impact/`.
- Full-decode and all-covered-frame composition checks pass; A/V duration agreement
  is 8.97 ms, encoded mix −14.49 LUFS / −2.43 dBTP. One identified scene was repaired;
  verification reused 11/12 scenes and 12/13 segments and returned no visual findings.
- Real Postgres/Redis/Arq rendering and local Studio registration succeeded. Synthetic
  seven-family demo and a live seeded-obstruction critic smoke also succeeded.
- Lint, formatting and strict typing pass; 467 unit/offline and 17 targeted integration
  tests pass. Studio browser smoke passes focus editing, undo and scene playback.
  The portable editable ZIP includes source, evidence, audio, checksums and credits;
  `scripts/render_bundle.py` validates dependencies and renders locally.
- Full phase acceptance remains OPEN: historical goldens mismatch with reconstructed
  fixtures (8/12 in the documented local check); reference files/thresholds were not
  changed. Three-source randomized human review, production container deployment,
  real Hindi speech benchmarking and arbitrary-upload quality claims remain pending.
- See Phase 7c plan §12, ADR-026 and `docs/VIDEO-QUALITY.md` for precise scope.

## Phase 7d: Reference-grade showcase families (2026-11-01)
- Studied seven reference shorts (Varun Mayya channel); grammar recorded in
  `docs/plans/PHASE-7d-reference-grammar.md`, plan in `PHASE-7d-reference-grade-showcase.md`.
- Added `counter`, `bar_chart`, `hub`, `multi_view`, `checklist`, `impact_title` families,
  mono theme/accents, bounded entrances, 22 reviewed pictograms, nested-asset permission
  checks, Anton + JetBrains Mono (OFL). Prompts (scene author, Director, critic) now carry
  the reference grammar. ADR-027.
- Fixed: scene tween overrun (wrong frame count), hub partial-raster nondeterminism,
  negative FFmpeg fade start on overlay slivers, harness contact sheet using source time.
- Judge demo: OpenAI DevDay 2026 keynote livestream 06:18–07:46 -> 60.2 s vertical,
  `editedVideo/devday-impact-final.mp4`; recipe `scripts/devday_recipe.py`, work dir
  `work/devday-impact/`. 12 scenes, 3 overlays (CC0 chip B-roll, Noto emoji GIF, meme),
  29 CC0 SFX, CC-BY music, observed stage-screen evidence; not monetisable (meme/logos).
- Checks: ruff/format/mypy green; unit suite green except the pre-existing
  `test_golden_showcase_graphics` (SSIM 0.9746, identical before and after this phase).
- Motion pass: face-anchored zooms/cut effects, per-clip transitions, jump-cut framing; fixed slice field loss, zoom cache key and timing-hash scope (ADR-027 addendum).
- Round 3: scene-exit/drift motion on all raw footage, face-aware zoom tool, per-cut set_transition; captured OpenAI + TechCrunch proof screenshots; Director/author/critic prompts rewritten (live eval not yet run).
- Real pipeline run (2026-11-01, `scripts/pipeline_e2e.py`, local API + Arq worker + Postgres/Redis + Gemini Director) on the DevDay excerpt: analysis 78.7 s, Director stopped after 8 tool calls by the Gemini free-tier quota (20 requests/day), and the worker rendered the partial v3. Exposed and fixed: fenced-JSON beat analysis (0 beats), case-sensitive capture highlight, capture failure reason hidden from the model behind a misleading hint. Prompt lessons: no first-N-seconds trims (delete_range across the video), no stock fallback for failed sources, insert vs scene entrances, asset_id from search. testInput.mp4 run is blocked until the quota resets or the key is upgraded.
- Gemini 3.1 Flash-Lite runs (ADR-028): full Director turns on both videos through the local API/worker. testInput.mp4 -> 54.7 s (13 calls, 1 failure); DevDay -> 68.3 s (14 calls, 2 self-corrected failures). Fixes from these runs: per-minute 429 waits on the same model, Director-shaped plan_storyboard (server stamps timing/evidence, version optional), capture errors carry the HTTP status. Gaps: the Director does not reach the scene/explainer path on its own (no diagrams), overshoots the target length, and sites such as openai.com and claude.ai block automated capture (HTTP 403).
- Autonomous explainer (ADR-029): `make_explainer` through the real API/worker on free-tier Gemini produced 5-8 scenes per video within 1-2 s of the target length; DevDay excerpt rendered end to end with a captured TechCrunch proof page. New: white Studio UI + Gallery dashboard; every export registered in Postgres. Open: library B-roll/meme lookups are strict (often 'nothing in the library'); openai.com blocks capture (403); the Director sometimes re-does captions/music after `make_explainer`; golden showcase test still at SSIM 0.9746.
- Dashboard data: all 65 local projects dated 31 Oct-1 Nov 2026, none without history (16 seeded via `scripts/seed_demo_history.py`; seeded messages are flagged). Gallery lists every finished edit; standalone exports registered with `scripts/register_exports.py`.
- Gaps: live model review returned `not_evaluated` (no provider answered); Docker stack
  build blocked by a full disk (build cache pruned, 3.3 GB free); split panels show the
  stage camera when the broadcast cut to slides; library B-roll is synthetic/low-detail.

## Phases 8-10: not started

## Phase 8: Creator memory on Meko (hackCBS Track A; ADR-030)
- Built: `ContextProvider` + Meko MCP adapter + fake; `CreatorMemory` (recall, remember turn,
  explicit correction, edit, forget, approve to creator canon, share with agency); chat
  `creator` + `meko` ON/OFF fields with `meko_recall` / `meko_stored` events; `/meko/*` panel API;
  Studio Memory tab and recall card; call log; `remove_zooms` tool; `scripts/meko_seed.py`.
- Verified live: same prompt, Meko OFF gave uppercase pink captions and kept fillers/zooms; ON
  recalled 5 memories (~5 s) and gave yellow highlight captions, removed face zooms (and fillers
  in one of two runs). 33 unit tests + 1 opt-in live integration test.
- Known gaps: the model does not apply every remembered preference every run (LLM variance);
  Meko extraction also stores plain requests as "preferences" (user can forget them in the
  Memory tab); promoted canon cannot be deleted from the UI; one Meko key serves all editors;
  Critic does not read memory yet; Check T needs a second teammate's coding agent.

## Provider switch + explainer hardening (ADR-031)
- Built: `ClaudeLLM` (Director + completions), `LLM_PROVIDER` switch through registry/workers,
  Wayback fallback for bot-blocked captures, tiered library lookup, duplicate-edit guard.
- Tests: `tests/unit/providers/test_claude.py`, `tests/unit/explainer/test_lookup.py`, archive
  fallback and director guard tests. Not run live against the Anthropic API (no key in this session).
- Gaps: Claude path unverified end to end until a key is set; Wayback copies of JS-heavy pages can be
  empty shells; golden `test_golden_showcase_graphics` still fails (pre-existing).
