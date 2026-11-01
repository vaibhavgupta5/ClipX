# Phase 7d: Reference visual grammar (Varun Mayya shorts)

Status: research note, 2026-11-01. Input to the 7d plan; no code yet.

Inspected (contact sheets at one frame per 1.5 s, cut counts via ffmpeg scene score;
frames stay in a scratch directory and are not committed):
`Jmy2f5HQRgU` (CPU cache timing), `thoij61UOI4` (PHP), `HCdsreVndC8` (eMudhra PKI),
`gYCZWa1EDFc` (REA), `uIiUlZZdinM` (GitHub repos), `yJv7HuSGh-c` (MacBook),
`i0kwwqXHpDQ` (OpenAI recording device). Durations 47–89 s.

## What the channel's shorts have in common

1. **Hook frame = split.** Top half shows a source page or B-roll with a heavy condensed
   title (white, sometimes red; "SCARIEST DAY EVER", "BREAKING NEWS"), and the speaker
   is in the bottom half. This lasts 2–4 s and then cuts to the story.
2. **Speaker on screen for roughly 15–25% of the runtime.** Full-frame speaker shots are
   short pivots ("It works.", "shift is this"). The speaker never shares the screen
   with a diagram.
3. **About half the runtime is minimalist motion graphics:** a black background, thin
   1–2 px outline strokes, tiny monospace uppercase labels, one accent color per video
   (white, red, teal, or yellow). Typical vocabulary:
   - device/VM/server boxes with an icon, connectors, and a pulse moving along them;
   - big counters and numbers (`4`, `115`, `253 / 255`, `14 years`, `1 0`);
   - bar charts and load-time bars; grids of cells lighting up; lists of check rows;
   - hub-and-spoke diagrams (logos/flags around a center), a padlock, a key, a cert card;
   - accepted/rejected X and check states; labels like `PATCH NOW` or `MAN-IN-THE-MIDDLE`.
   Each graphic **builds in stages, one element per spoken phrase**, then the next state replaces it.
4. **Source proof is shown as the actual page:** a tweet, an article, a GitHub README, or a
   government notice, full width on black/white. A black highlight bar with white text sweeps
   over the spoken sentence, and the camera pushes or scrolls slowly.
5. **Cinematic B-roll** (server racks, hands on keyboards, CRTs, product shots) is
   colour-graded dark/teal, sometimes with a short serif or condensed title.
6. **Captions:** 2–3 words, small, centred in the lower third, white (or a yellow chip).
   They are never large karaoke text.
7. **Pacing:** a new visual state every 1–2 s, but hard cuts are rare. The illusion of speed
   comes from elements being added to the **same** scene. Transitions are hard cuts or
   short pushes; there are no flashy wipes.
8. **Audio:** low, steady electronic bed; soft UI ticks/whooshes on reveals. No meme sounds.
9. **Memes and emoji are almost never used.** One video (PHP) uses an anime GIF sticker
   as a recurring motif inside a panel. That is the full extent.

## Gaps against ClipZ today

| Reference element | ClipZ today | Gap |
|---|---|---|
| Split hook (title over source, speaker below) | `reframe=split_bottom` + panel scene | The title style isn't heavy/condensed enough; there is no "hook" title preset |
| Monochrome line-art diagrams | `architecture_flow`, `verification_pipeline` (rounded cards) | Needs an `ink-mono` theme: thin strokes, mono labels, icons in nodes, a travelling pulse |
| Counters / bars / cell grids | `metric_or_code` (static value) | No animated counter, bar chart, or cell-grid family |
| Hub-and-spoke / multi-entity | none | No `hub` family (icons around a centre) |
| Multi-view / comparison tiles | none | No `multi_view` family (2–4 tiles with staggered reveal) |
| Sentence highlight sweep on a page | `proof_focus` annotations (boxes) | Needs a text-band highlight that sweeps with the spoken words |
| Graded B-roll + condensed title | overlay `headline_card` / video cutaway | Needs a title-over-B-roll preset and a grade |
| 2–3 word small centred captions | `word_highlight`, 3 words, 58 px | Close; needs a smaller "reference" preset |

## Implication for "make it impressive"

Judges are impressed by **density of meaning, not count of effects**. Use memes, emoji, and
flashy transitions sparingly (at most one deliberate comic beat). Range comes from many
visual families, each one building in sync with the speech.
