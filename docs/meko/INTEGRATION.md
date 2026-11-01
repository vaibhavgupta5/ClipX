# How ClipZ uses Meko (hackCBS 9.0 · Meko Track A · team Fixem)

**One line:** ClipZ's Director agent edits vertical reels by chat. With Meko it **remembers each
creator's editing style**, applies it before it touches the timeline, and shares lessons a person
approves with every editor in the agency. Switch Meko off and the same prompt gives a generic edit.

## Persona, problem, story (A3)
- **Persona:** a small agency where several editors cut Hindi/English reels for creators like Riya.
- **Problem:** every edit starts from zero. Riya says "yellow captions, cut 'basically', no zooms
  on my face" on reel 1, and again on reel 5. A fix one editor finds never reaches the others.
- **Story:** the same clip and the same message, *"Make this reel ready to post in my usual style."*

## A1: the same flow with Meko OFF and ON (measured live on 2026-11-01)

| | Meko OFF | Meko ON |
|---|---|---|
| Recalled | nothing (`meko_recall.enabled=false`) | 5 memories in ~5 s (shown in the chat card) |
| Captions | UPPERCASE, pink `#FF007F` highlight, pop | yellow `#FFD400` highlight, no uppercase, no animation, 96 px |
| Face zooms | 2 kept | `remove_zooms` → 0 |
| Fillers | kept | `remove_fillers` (in 1 of 2 runs) |
| Reply | generic polish, then tried to export | "updated your reel to match your preferences: removed all face zooms…" |
| Stored | nothing | the turn, into `fixem-creator-riya` (`meko_stored`) |

Raw tool calls for both runs are in the session transcript, and the Meko calls are in
`work/meko/calls.jsonl`. LLM output varies between runs: ON reliably changes the captions and the
zooms, while filler removal was applied in one of the two ON runs.

## A2: Meko uses (five, each for a reason)

| # | Meko feature | Where | Why this one and not something simpler |
|---|---|---|---|
| 1 | **Datapacks as scopes** | `fixem-creator-<slug>` per creator, `fixem-agency` shared | A creator's style is private to that creator; a lesson like "Devanagari captions ≤ 96 px" belongs to every creator. Datapacks are Meko's isolation and sharing boundary. |
| 2 | **Extracted memories** | every chat turn → `conversation_add_message` (agent `clipz:director`) | Creators state preferences in passing ("never zoom on my face"). Meko extracts durable facts from the user side of the turn, so nobody fills in a settings form. |
| 3 | **Recall before reasoning** | `CreatorMemory.recall()` runs before the Director's first model call: `memory_get_all` (private + promoted) and `knowledgebase_search`, in parallel | The edit plan is decided in the first model turn. Memory has to be in that turn, not looked up afterwards. |
| 4 | **Promotion to shared knowledge** | Memory tab → *Approve for Riya* → `memory_promote` | Extraction is noisy (it also stores one-off requests). A **person** decides which memories become canon that every editor's agent reads. The agent never promotes by itself. |
| 5 | **Sharing across users and agents** | *Share with agency* → `memory_add` into `fixem-agency` + `memory_promote` | A fix found while editing one creator's reel reaches every creator and every editor. Meko has no cross-datapack promote, so this copies first (see the feature proposal). |

Also used: explicit corrections (`memory_add`, agent `clipz:curator`), edit (`memory_update`),
forget (`memory_delete_by_id`).

## A4: visible context (correct or forget)
- **Chat card** before every edit: "Memory · recalled N for riya in X s", with every item and its
  source label (*learned from chat*, *explicit correction*, *approved for this creator*, *agency
  canon*). When Meko is off, the card says "Memory off".
- **Memory tab:** counters (recall / write / promote / edit / forget / errors), what the last edit
  recalled, private memories with **Approve · Share with agency · Edit · Forget**, creator canon,
  agency canon, and a live **Meko call log** (tool, datapack, agent, rows, ms, errors).
- A "Remember" box stores an explicit correction.

## A5: honest and private
- Only what a Meko call returned is shown. The call log is written by the adapter when the call
  returns, never by the UI or the routes.
- Labels come from the `agent_id` **Meko returns on each row**. We first labelled rows by which
  query ran; `memory_get_all` turned out not to filter by agent, so a chat-extracted preference was
  shown as an "explicit correction". We fixed that.
- No personal data: creators are slugs (`riya`, `arjun`), and memories are editing preferences.
  Transcripts are never written to Meko, only the chat turn text.
- Seeded history (`scripts/meko_seed.py`) is labelled seeded (`seed` on `conversation_add_message`).
- Prompt-injection safety: memory text is fenced in `<creator_memory>` with `<`/`>` neutralised and
  framed as editing preferences only. The Director still edits only through typed tools; no memory
  text ever reaches FFmpeg (architecture rules 1 and 6).

## Architecture

```
Studio (Memory tab, creator picker, Memory ON/OFF)
   │ POST /projects/{id}/messages {text, creator, meko}
   ▼
chat.py ──► CreatorMemory.recall(creator, text) ──► ContextProvider (protocol)
   │            parallel, per-call timeout,              ├─ MekoContextProvider ─► Meko MCP (HTTP)
   │            30 s cache, partial on error             └─ FakeContextProvider (tests, no key)
   │        memory_block(recall)  → fenced <creator_memory>
   ▼
run_director(..., memory=block)  → typed tools → Timeline version → renderer
   │
   └─► CreatorMemory.remember_turn() → conversation_add_message → Meko extracts preferences
/meko/* routes ─► approve / share / edit / forget / calls       CallLog ─► /meko/calls, calls.jsonl
```

| File | Role |
|---|---|
| `app/providers/base.py` | `ContextProvider` protocol (vendor-neutral) |
| `app/providers/meko.py` | Meko MCP adapter: session reuse, single-flight datapack/conversation setup, ids cached on disk, every call logged |
| `app/providers/fakes.py` | `FakeContextProvider`: same zones as Meko, used by tests and keyless dev |
| `app/memory/service.py` | `CreatorMemory` (business logic) and `memory_block` (fenced prompt section) |
| `app/memory/models.py`, `calllog.py` | typed recall and call models; call log + JSONL replay |
| `app/api/chat.py` | `creator` + `meko` fields; `meko_recall` and `meko_stored` events |
| `app/api/memory.py` | `/meko/*` panel API |
| `app/agent/director.py`, `prompts/director.txt` | memory sent with the current turn; rule: preferences override defaults, the current message overrides preferences |
| `app/tools/*` | new `remove_zooms` tool, so "no face zooms" can be honoured |
| `app/web/index.html` | creator picker, Memory switch, recall card, Memory tab |
| `scripts/meko_seed.py` | labelled demo history |
| `tests/unit/memory/*` | 33 tests (fake + mocked MCP transport, no network) |
| `tests/integration/test_meko_live.py` | opt-in live round trip |

## What we learned building on Meko (feeds the feature proposal)
Each item was found by a live probe and is recorded in `fixem-build`:
1. Every tool needs a `conversation_id`, even `datapack_list`.
2. Conversations are bound to the agent that created them (`agent_id_mismatch`).
3. `memory_get_all` ignores `agent_id`, while `memory_search` is agent-bucketed (and took ~13 s).
4. Promotion is one-way and stays inside one datapack; there is no cross-datapack promote.
5. Extraction stores one-off requests ("restyle the captions…") as durable preferences.
6. Memories are text only: there is no way to anchor one to a frame or time range of a video.

## Built with Meko (Check T)
Coding agents connect to Meko MCP and follow the team protocol in `CLAUDE.md`: recall from
`fixem-build` before each task, save a summary after it, promote decisions. `fixem-build` holds 10+
promoted decisions tagged with their author.
