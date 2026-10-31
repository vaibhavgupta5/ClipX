# ClipZ Studio: design system ("Rundown")

Surface: `app/web/index.html` (single file, no build step). Mode: Operate. Priority: the chat-to-preview
edit loop. A white, ruled running-order sheet, like a newsroom rundown: content separated by rules,
not by cards or shadows; ink-black actions; one blue for focus and selection; red only for "live".

## Color (restrained: neutrals + one accent)
| Token | Value | Use |
|---|---|---|
| `--paper` | `#ffffff` | main surfaces (conversation, panes, inputs) |
| `--desk` | `#f6f6f3` | second neutral: reel list, monitor |
| `--wash` | `#efefeb` | hover, segmented-control track |
| `--ink` | `#16181d` | text, primary buttons |
| `--ink2` / `--mute` | `#464b54` / `#666b74` | secondary text (>= 4.5:1 on paper) |
| `--rule` / `--rule2` | `#e3e4e7` / `#cfd2d8` | dividers / control borders |
| `--blue` / `--blue-tint` | `#1b4fd6` / `#e8efff` | focus ring, selection, Director label |
| `--tally` | `#e5322d` | on-air tally (Director or render running), failures |
| `--ok` / `--warn` | `#14794a` / `#8f5b00` | ready, unresolved needs |

## Type
System stack (`Helvetica Neue`, `Segoe UI`, system-ui). One family; weight carries rank (550 / 600 / 650).
Monospace only for data: tool names, timecodes, word IDs. Scale 12 / 13 / 14 / 17 / 22.

## Shape and depth
Radius 8 (controls), 10 (cards/slips), 12 (monitor), pills only for quick prompts. Elevation is declared once:
borders for structure, a single soft offset shadow for the monitor and the active reel.

## Components
- **Script turn**: label column (You / Director / Notes) + text, ruled between turns; no bubbles.
- **Tool row**: status dot (running pulses blue, ok green, failed red), mono name, muted args, result below.
- **Slip card**: plan, final prompt, questions, credits; 1px rule, 10px radius.
- **Rundown row**: order number, purpose, unresolved need, thumbnail, focus text, actions.
- **Monitor**: 9:16 player, version chip, undo / redo / export.
- **Composer**: Discuss/Edit segmented control, one scrolling row of quick prompts, send.

## Behaviour
`/` focuses the composer. Enter sends. Focus rings are 2px blue. Motion 150 ms ease-out, state only
(tally, running dot); reduced-motion honoured. Below 900px one view at a time (Reels, Director, Monitor).
