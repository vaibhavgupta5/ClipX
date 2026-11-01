# Phase 7e: Make the pipeline produce reference-grade videos on its own

Status: plan, 2026-11-01. Nothing here is implemented yet.

## 1. The gap, measured

Hand edit (`scripts/devday_recipe.py`) vs. the real pipeline on the same source
(Gemini 3.1 Flash-Lite Director, local API + worker; traces in `work/pipeline-run/`):

| | Hand edit | Pipeline |
|---|---|---|
| Scenes (diagrams/proof) | 14 typed scenes, cues on exact words | 0 |
| Length control | 60.2 s (target met) | 68.3 s (target ~60 s) |
| Source screenshots | 3, captured with spacing and retries | 0 (one attempt, HTTP 403) |
| Raw-footage motion | per-cut effects, face-anchored zooms, drift | one global effect + `add_zooms` |
| Sound | 32 effects on reveals and state changes | `auto_sfx` on cuts and zooms |
| Review | ~30 frame-level look-and-fix rounds | none (`not_evaluated`) |

Renderer, scenes and motion are the same code in both. The gap is **planning, sourcing and
feedback**, not rendering.

Root causes (all observed): (1) the Director has no tool that reaches `hybrid_task`;
(2) scene authoring needs large typed schemas that the cheapest model avoids;
(3) nothing automatically sources web evidence; (4) nothing enforces the target length;
(5) nothing looks at the rendered frames and repairs; (6) cheap deterministic decisions
(motion, sound placement) are left to a model that should not make them.

## 2. Principle

Models decide **what the story is**. Code decides **everything that has a rule**.

| Decision | Owner |
|---|---|
| Which window and passages to keep, claims, shot list | model (strong, once) |
| Scene content for each beat | model, one beat per call, validated and repaired |
| Which source page proves a claim | model proposes, code fetches and verifies |
| Cut effects, zooms, drift, scene exits, entrance choice | deterministic policy |
| SFX placement, music ducking, SFX/scene sync | deterministic, from compiled scene events |
| Length, ownership, overflow, slivers, faceless zooms, caption collisions | deterministic QA gate |
| Does it look good? | model critic on real frames, bounded repair |

## 3. Target architecture

```
upload -> analysis (existing, cached)
  -> EditPlanner (strong model, 1 call): target length, window, delete ranges, hook,
     claims, beats with evidence needs                      [new]
  -> LengthGovernor (code): apply cuts, re-measure, loop until within +/-3 s   [new]
  -> SourceFinder (provider + code): per evidence need -> candidate URLs ->
     guarded capture (spaced, reading mode, phrase fallback) -> verify phrase present
     -> freeze_image                                         [new, extends M4]
  -> SceneAuthor (per beat, cheap model OK): typed spec, pydantic errors fed back,
     max 2 repairs, family chosen by the decision table       [rewrite of author_scenes]
  -> MotionPolicy + SoundPolicy (code): face-aware zooms/cuts/drift, SFX from events [new]
  -> QA gate (code): slivers, faceless zooms, overflow, ownership, length, caption band [new]
  -> preview -> Critic (images at cue frames) -> bounded repair -> final   [exists, widen]
```

The Director keeps cheap structural tool turns (silence, fillers, captions, music). Two
new tools hand off to the above: `plan_explainer` (runs EditPlanner + LengthGovernor +
SourceFinder + SceneAuthor as the existing durable job) and `review_and_repair`.

## 4. Milestones and exit gates

### M1: Connect the Director to the explainer path (highest leverage)
- Add Director tool `make_explainer` that enqueues the existing `hybrid_task` with the
  current version (reuse `/explainer` service logic; same consent and version guards).
- Add `GEMINI_PLANNER_MODEL` (default = primary) used only by planning calls.
- Make `author_scenes` validate-and-repair: on `ValidationError` feed errors back, at
  most 2 retries; per-beat calls instead of one 32-scene call.
- Exit: a real run on the DevDay excerpt produces >= 8 scenes through the product, no
  hand-authored recipe. Unit tests with a fake LLM (no network).

### M2: Length governor and edit planner
- EditPlanner returns a window plus delete ranges and a target length; code applies them
  and measures; if outside +/-3 s, re-plan with the measured length (max 2 loops).
- Exit: 5 consecutive runs within +/-3 s of target on two sources.

### M3: Source finder
- New `SearchProvider` (rule 8) behind an interface. Candidate: Gemini grounding with
  Google Search, which is documented for Gemini 3 models; read its current docs and
  record the URL in DECISIONS.md before coding (CLAUDE.md rule).
- Capture policy: primary source first, then reputable news; space requests; reading mode
  for prose; shorter-phrase fallback; reject pages missing the phrase; domains that
  return 403 are cached as blocked for the project. Observed: openai.com refused one
  burst and accepted a spaced reading-mode capture, so spacing and retries matter.
- Exit: >= 2 verified proof screenshots per launch-news source; none are error pages.

### M4: Deterministic motion and sound policy
- Promote the hand-tuned rules to code, run after scenes compile: per-clip cut effect
  (none into scenes, face punch onto speaker, whip into comic beat), `scene_exit`,
  `speaker_drift`, zooms only where face tracks show a face, SFX on every reveal and
  state change from compiled events, music duck under speech.
- Exit: golden-style unit tests on fixtures: no faceless zoom, no sliver, every scene
  reveal has a sound within 100 ms.

### M5: QA gate and render-review-repair
- QA gate fails the draft on: raw-footage slivers under 0.3 s, zoom without a face,
  text overflow, caption-band collision, length outside tolerance, empty or error
  evidence. Failures become typed repair requests, not prose.
- Critic receives frames at each scene's cue and mid points (existing image path),
  findings map to scene IDs, repair is a bounded `update_scene`. Raise the repair cap from
  1 to 2 only after measuring that the second repair improves results.
- Exit: a seeded defect (clipped label, faceless zoom, error page) is caught and fixed.

### M6: Benchmark and regression harness
- Keep the hand-made DevDay edit as the **reference**. Automatic comparison on
  measurable properties: scene count and family variety, runtime covered by graphics,
  evidence count, cut-effect coverage, length error, QA findings.
- Record/replay LLM fixtures so the planner can be regression-tested offline (rule 9).
- Blind human comparison on 3 source videos (including `testInput.mp4`, English and
  Hindi) before any claim of parity. Rubric as in Phase 7c section M7.

## 5. Model and cost

- Tool turns (cuts, captions, music): `gemini-3.1-flash-lite` (ADR-028).
- Planning: one call per project on a stronger configurable model, then one cheap
  call per beat. Token counts and prices must come from the usage log and the current
  price table, not from estimates. Free-tier limits (observed: 250k input tokens per
  minute and 20 requests per day on other models) make a paid tier necessary for runs
  of this size.
- Budget guard: reuse the existing `ModelBudget` ledger; planner calls count against it.

## 6. Risks

- Strong planner output can still invent claims: keep grounding checks (claims must
  quote transcript words; numbers must appear in speech or evidence).
- Sites block automated capture: always allow "no screenshot" and fall back to a
  labelled illustration, never to stock imagery that proves nothing.
- Overfitting to one reel: M6 benchmark uses three unlike sources.
- More moving parts: every stage persists a checkpoint (existing job model) so a
  failure resumes instead of restarting.

## 7. Definition of done

`make check` green apart from the documented golden baseline; unit tests for each new
stage with fakes; one real end-to-end run per benchmark source through the API and worker
with no hand authoring; PROGRESS.md updated with measured numbers and known gaps.
