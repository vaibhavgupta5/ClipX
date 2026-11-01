# Phase 8: Meko creator memory (hackCBS 9.0, Meko Track A)

Team **Fixem** (4). Track A: open project. Brief: `meko hackathon.pdf` (hackCBS 9.0, 31 Oct – 1 Nov 2026).
Organisers confirmed ClipZ is eligible.

## Pitch (A3)
**Persona:** a small agency, 3 editors cutting Hindi/English reels for 2 creators.
**Problem:** every new edit starts from zero. A creator says "no zoom on my face, yellow
captions, cut 'basically'" on reel 1, and again on reel 5. A fix one editor finds (for example "Devanagari
captions overflow at size 64") never reaches the other editors.
**Story:** the same clip and the same prompt ("make this a reel") are run with Meko OFF (a generic
edit) and Meko ON (the creator's learned style, the Critic's past rejections avoided, and the agency
canon applied). Then editor B gets a correction that editor A taught, live.

## Datapacks (keep build and run time apart; never mixed)
| Datapack | Who | Holds |
|---|---|---|
| `fixem-build` | coding agents only | team decisions, contracts, gotchas (Check T) |
| `fixem-creator-<slug>` | product: Director, Critic | one creator's private style memories, conversations |
| `fixem-agency` | product: all editors' agents | promoted canon + brand guideline docs (KB) |

Product `agent_id`s: `clipz:director`, `clipz:critic`, `clipz:curator`.

## Meko uses (A2): five, each with a reason
1. **Datapacks as scopes:** creator style is private to that creator, and canon is shared across the agency.
2. **Extracted memories:** each chat turn goes in through `conversation_add_message`; Meko extracts
   durable preferences from the user side. Explicit corrections go in through `memory_add`.
3. **Recall before reasoning:** before planning, the Director calls `context_search` on the creator pack plus
   `memory_search` on the agency pack. The Critic recalls past rejections before scoring.
4. **Promotion:** the Curator (deterministic code) spots a correction repeated across 2+ reels
   and proposes it. A human approves it in the UI, then `memory_promote` into `fixem-agency`.
5. **Documents:** a brand guideline PDF goes in through `knowledgebase_upload_document`, and
   `knowledgebase_search` reads it at plan time.

## Architecture rules kept
- Recalled text is **UNTRUSTED DATA** (rule 6): fenced in the system prompt with `_fence`, never
  executed. It only shapes which typed tools the LLM calls. Memories never become FFmpeg strings.
- Provider abstraction (rule 8): `ContextProvider` protocol in `app/providers/base.py`;
  `MekoContextProvider` (MCP over HTTP, `app/providers/meko.py`) + `FakeContextProvider` +
  `NullContextProvider` (Meko OFF). Business logic never imports an MCP client directly.
- No network in unit tests (rule 9): fakes; one opt-in `@pytest.mark.integration` test.
- Every Meko call is logged (`meko_calls` table) and powers the UI context panel.

## Work items
1. `ContextProvider` protocol + pydantic models (`Recall`, `MemoryRef`, `MekoCall`), fake and null.
2. `MekoContextProvider`: JSON-RPC over streamable HTTP, sends `User-Agent`, `MEKO_API_KEY`
   from env/settings, timeout, one retry, errors become `ProviderUnavailable` (degrade to OFF).
3. Director hook: `recall()` before the first model turn → fenced "Creator context" block in the
   system prompt; `remember()` after the turn (conversation_add_message).
4. Critic hook: recall past rejections; store new rejections as memories.
5. Curator + `/api/memory` routes: list recalled/stored, `PATCH` (memory_update), `DELETE`
   (memory_delete_by_id), `POST promote` (memory_promote, human-approved).
6. Meko ON/OFF toggle per request (`meko: bool` on `ChatRequestBody`) for the A1 demo.
7. UI context panel (A4): "Recalled 4 · Stored 2", with Edit / Forget / Promote per row.
8. Seed script: 2 creators, 3 prior reels' corrections (labelled as seeded history), brand PDF.
9. Demo script (5 min) + README in ≤5 commands + LinkedIn post.
10. Feature proposal: **media-anchored memories** (memory bound to an `artifact_put` hash +
    time range, so recall returns the visual example and not only text). Ground it in the
    friction logged in `fixem-build`.

## Split (4 people)
- A: provider + Director/Critic hooks + tests (items 1–4)
- B: API routes + Curator + ON/OFF (items 5–6)
- C: UI context panel + demo polish (item 7)
- D: seed data, brand PDF, demo script, README, proposal, LinkedIn (items 8–10)

## Check T
Each teammate's coding agent saves and promotes decisions in `fixem-build`, each naming its author.
Target: 12+ promoted decisions from all 4 teammates.

## Open questions
- Can one Meko key read and write `fixem-agency` for all editors, or is it one key per editor? (Check the
  Manage access docs; record the URL in DECISIONS.md.)
- How long does extraction take after `conversation_add_message`? If it's slow, the demo uses
  `memory_add` for explicit corrections.
