# Phase 6d: Agent scalability & cost (Gemini caching, streaming, MCP, batch)

## Context

The Director loop (`app/agent/director.py`) is stateless by design (ADR-012): every
model turn resends the full system prompt + all ~35 tool JSON schemas (director.txt
is ~1.4K tokens; `tool_specs()` schemas are roughly 4-6K tokens — bigger than the
prompt itself), and a chat turn can run up to `MAX_ITERS=14` model calls. That prefix
is almost perfectly stable call-to-call, but nothing in `GeminiLLM` asks for an
explicit cache — `build_body` has no `cached_content` field, so savings depend
entirely on Gemini's *implicit* caching, which is opportunistic with no guaranteed
discount. Streaming is also fake today: `complete_with_tools` awaits the whole
response and fires `on_text` exactly once, even though the SSE transport
(`app/api/chat.py`) and `Event("token", ...)` plumbing are already built for
incremental chunks. Separately, comparable high-star open-source video-editing
agents (browser-use/video-use, MakeMyClip/editor) validate the "LLM edits typed
data, deterministic renderer compiles it" architecture already in place here, and
several ship their tool registry over MCP — something `app/mcp_server/` is an
empty stub for today. This phase closes those four gaps, in the order that gives
the clearest, most measurable payoff first.

I introspected the installed SDK (`google-genai` in `.venv`) directly rather than
trust blog posts:
- **Streaming is real and available**: `AsyncInteractions.create()` returns either
  an `Interaction` or an `AsyncStream` of SSE events (`StepDelta`, `StepStart`,
  `StepStop`, `InteractionStatusUpdate`) — i.e. the SDK supports token-level
  streaming on the Interactions API today. This needs a `stream=True`-style param
  (confirm exact kwarg against current docs) but is not speculative.
- **Explicit caching is unconfirmed on Interactions**: the SDK ships a separate
  top-level `client.caches` resource (`CachedContent`, from the older
  `generate_content` API), and `Interaction.usage` already reports
  `total_cached_tokens` (read today in `parse_interaction`), which proves *some*
  caching already applies implicitly. But `CreateInteractionRequest.body` is an
  untyped passthrough dict, so there is no SDK-level proof that passing
  `cached_content: <cache_name>` in the Interactions body is honored by the
  server. Per CLAUDE.md's "never fabricate API behaviour" rule, this must be
  verified against current docs/a live call before being built as a real feature,
  not assumed.
- **Batch API**: same caveat — confirmed to exist for `generate_content`-era
  usage; not confirmed for Interactions. Needs the same doc check.

## Plan

### Step 0 — Doc verification spike (do first, blocks 1 and 4)
Read `https://ai.google.dev/gemini-api/docs/caching` and the Interactions-specific
docs/changelog for whether `cached_content` (or an Interactions-native equivalent)
and the Batch API are supported on `client.aio.interactions.create`. Record the
finding either way as a new ADR (`ADR-023`) in `docs/DECISIONS.md`, with the URL
and retrieval date, per CLAUDE.md's provider-docs rule. This gates scope for steps
1 and 4 below — if unsupported, those steps are replaced by documented no-ops
(e.g. rely on implicit caching, skip Batch) rather than built as fiction.

### Step 1 — Explicit context caching (biggest, cheapest win if Step 0 confirms it)
- `app/providers/gemini.py`: if confirmed supported, create/reuse a `CachedContent`
  (via `client.caches` or an Interactions-native path) keyed by a hash of
  `(system_instruction, tool_schemas)` — this prefix is stable across turns and
  across the whole app, so one cache entry can serve every chat. Reference it from
  `build_body`. Respect the 1,024-token minimum (already comfortably exceeded).
- New settings in `app/settings.py` next to `GEMINI_THINKING_LEVEL` (~line 58):
  `GEMINI_ENABLE_CACHING: bool` (default `True`) and `GEMINI_CACHE_TTL_S: int`
  (default e.g. 3600) — documented in `.env.example` per the settings file's own
  header rule.
- Wire through `app/providers/registry.py`'s `_gemini()` constructor.
- Extend `tests/unit/test_tool_llm.py` (the existing `build_body`/`to_steps`
  offline-mapping tests) to cover the cache-reference branch with a fake client —
  no live key needed, consistent with "no network in unit tests" (CLAUDE.md rule 9).
- Cost visibility: `Usage.cache_read_tokens`/`cache_write_tokens` already exist and
  are already logged into `agent_runs` (ADR-013) — no schema change needed, just
  confirm the numbers move once caching is live (`make eval-live`).
- If Step 0 finds explicit caching unsupported on Interactions: skip code changes,
  just record the implicit-caching reliance as the documented ADR-023 outcome.

### Step 2 — Real token streaming
- `app/providers/gemini.py`: add a streaming path in `complete_with_tools` using
  the SDK's `AsyncStream` return (confirmed above). Map `StepDelta` events to
  incremental `on_text(...)` calls instead of one call with the full text;
  `StepStop`/`InteractionCompletedEvent` finalize `usage`/`stop_reason` the same
  way `parse_interaction` does today for the non-streamed path — reuse its
  step-type dispatch logic rather than duplicating it.
- `app/agent/director.py` and `app/api/chat.py` need no structural change — `emit`
  already fires one `Event("token", ...)` per `on_text` call; it just starts
  firing more often, with smaller payloads.
- Gate behind a flag only if the streaming request shape risks breaking the
  non-streamed path; otherwise make it the default and drop the single-shot path.

### Step 3 — MCP server (no API uncertainty; pure wiring)
- Implement `app/mcp_server/` as a thin server exposing the existing
  `tool_specs()` (`app/tools/registry.py`) and `execute()`
  (`app/tools/executor.py`) — no new tool definitions, this reuses the registry
  as-is. Mirror `app/workers/main.py`'s process-entrypoint shape (startup/shutdown
  hooks, not a FastAPI HTTP app) since an MCP server is its own long-lived
  process, not a router to include in `app/main.py`.
- Validates against the same `ToolState`/executor contract the Director uses, so
  MCP calls get identical validation/self-correction behavior (CLAUDE.md rule 3)
  for free.

### Step 4 — Batch API for analysis-stage Gemini calls (only if Step 0 confirms)
- `app/workers/analyze.py`'s `run_stages`/`analyze_asset` already run inside a
  dedicated arq worker process (`app/workers/main.py:48`), fully decoupled from
  any user-facing request — the correct shape for Batch API's up-to-24h latency.
  If Step 0 confirms Batch works for Interactions (or these stages can use
  `generate_content` directly), route them through it for the ~50% discount.
  If not confirmed, skip and note as a gap in PROGRESS.md.

### Not in scope for this phase
Tool-registry decorator/category refactor — research on comparable agent
frameworks shows dynamic/deferred tool loading only pays off past ~50 tools;
at 35 tools this would be premature complexity. Revisit only if tool count grows
or `coverage.py`'s hardcoded per-requirement tool-name sets become unwieldy.

Also out of scope: the duplicate `to_gemini_schema()` in `app/tools/registry.py`
(:27) looks dead relative to `tool_specs()` (:42) — delete it as a small drive-by
cleanup while touching that file in Step 3, but it's not a scalability item on
its own.

## Verification
- `make check` after each step (ruff + mypy strict on `app/timeline`/`app/tools` +
  pytest, no network).
- New/extended unit tests for `build_body`/streaming mapping in
  `tests/unit/test_tool_llm.py`, offline against a fake client — follow the
  existing pattern (`_request()` helper, `ScriptedToolLLM` fake).
- `make eval-live` (opt-in, needs `GEMINI_API_KEY`) to confirm live: cache hit
  shows up in `agent_runs.cache_read_tokens` growing turn-over-turn within a chat;
  streaming shows multiple `token` SSE events per turn instead of one; MCP server
  boots and `tool_specs()`/`execute()` round-trip for one tool (e.g. `get_timeline`).
- Update `docs/PROGRESS.md` (Phase 6d entry: built / stubbed / gaps) and
  `docs/DECISIONS.md` (ADR-023) per CLAUDE.md's definition-of-done.
