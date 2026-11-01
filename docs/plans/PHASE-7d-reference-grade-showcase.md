# Phase 7d: Reference-grade showcase families

Status: in progress, 2026-11-01. Input: `PHASE-7d-reference-grammar.md`.

## Goal

Close the visible gap between ClipZ scenes and the reference channel's grammar
(monochrome line-art scenes that build on the spoken word). Then produce a 60-second
judge demo from a real public livestream, using every insert type ClipZ supports,
each placed where the reference grammar allows it.

## Scope

1. **Scene contract (`app/scenes/models.py`)**, additive and backward compatible:
   - `DesignTokens.theme += "mono"`; `accent += "red" | "teal" | "white" | "yellow"`.
   - `SceneSpec.entrance: "cut" | "rise" | "zoom" | "flash" | "glitch"` (default `cut`).
     This is the in-scene entrance (no alpha needed), bounded to 10 frames.
   - New closed families. Each element is an ID-addressable target:
     - `counter`: an animated number (`start` → `value`, prefix/suffix, decimals) plus an optional
       cell grid that lights up with the count.
     - `bar_chart`: 2–6 labelled bars. Values must be grounded; bars grow on `reveal`.
     - `hub`: a centre plus 3–8 spokes (label and optional icon evidence). On `reveal`,
       each spoke draws its connector and sends a pulse.
     - `multi_view`: 2–4 tiles (image evidence or a short glyph) with staggered reveal and per-tile
       highlight. This is the multi-view/comparison grid.
     - `checklist`: 2–7 rows that tick from idle to accepted/rejected/unknown.
     - `impact_title`: a heavy condensed hook title over an optional graded frozen image,
       with a slow push. This is the reference's split-hook and B-roll title card.
   - `SceneSpec.asset_ids` lists every referenced image. The compiler validates all of them,
     not only `content.asset_id`, and the renderer passes all of them.
2. **Runtime (`visuals/`)**: compose branches, mono theme CSS, counter/bar/hub tweens and the
   entrance timeline. Add pinned OFL fonts (Anton for display, JetBrains Mono for labels).
   All of it stays deterministic: state objects are painted on every seek.
3. **Prompts**: scene author, Director and critic get the reference grammar (speaker 15–25%,
   motion graphics that build per phrase, proof highlight, at most one comic beat, no invented
   numbers).
4. **Judge demo**: OpenAI DevDay 2026 keynote livestream, 06:18–07:46 (`Fls_onRviPM`),
   tightened to about 60 s. It uses stage-screen crops as observed evidence; CC0 B-roll, icons,
   one meme/emoji beat, BGM, SFX and transitions; a split hook; and full scenes.

## Non-goals

No arbitrary HTML/JS, no alpha scene compositing, no overlays above full scenes (scene
ownership stays). No golden reference overwrites.

## Exit

New families have unit tests (validation, targets, asset permissions) and a real
Chromium render smoke. `make check` shows no new failures. The demo export passes `inspect_export`
and the all-frame scene-visibility check, and gets an actual-frame review.
