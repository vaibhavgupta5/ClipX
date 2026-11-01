"""Director: the tool loop. LLM proposes calls -> executor validates -> workspace persists.

The loop is bounded (``max_iters`` model turns), every call is validated before
any version is written, and at most one preview render is queued per chat turn.
Persistence and rendering go through ``Workspace`` so the loop is testable offline.
"""

import asyncio
import dataclasses
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from app.agent import coverage
from app.agent.context import timeline_state
from app.agent.critic import CriticReport, evaluate_preview
from app.agent.router import route
from app.explainer.builder import ExplainerBuilder
from app.inserts import keywords
from app.providers.base import LLMProvider
from app.providers.local import LibraryItem
from app.providers.tools import (
    AgentMessage,
    ToolCall,
    ToolCallingLLM,
    ToolResult,
    ToolTurnRequest,
    Usage,
)
from app.showcase.capture import capture_webpage
from app.showcase.images import GeneratedImageStore
from app.timeline.schema import Timeline
from app.timeline.summary import summarize
from app.tools import mvp
from app.tools.executor import (
    GENERATING_TOOLS,
    Effect,
    ToolFailure,
    ToolOutcome,
    ToolState,
    execute,
)
from app.tools.registry import ELEVENLABS_TOOLS, get_tool, tool_specs

MAX_ITERS = 14  # plan + ~10 edits + reply; flash models often make one call per turn
MAX_FAILURES_PER_TOOL = 2
SHOWCASE_TOOLS = frozenset({"generate_infographic", "annotate_image", "capture_webpage"})
# The user's own words waiving the monetisation guard (ADR-014).
CONSENT = re.compile(
    r"not (?:be )?monetis|not (?:be )?monetiz|non[- ]?monetis|non[- ]?monetiz|personal use|"
    r"non[- ]?commercial|monetized\s*=\s*false|export as is",
    re.IGNORECASE,
)

EventType = Literal[
    "token",
    "tool_call",
    "tool_result",
    "timeline_version_created",
    "preview_queued",
    "render_queued",
    "dub_queued",
    "ask",
    "done",
    "render_progress",
    "preview_ready",
    "render_ready",
    "render_failed",
    "critic_feedback",
    "meko_recall",
    "meko_stored",
    "error",
]


@dataclass(frozen=True)
class Event:
    """One streamed chat event (SSE payload)."""

    type: EventType
    data: dict[str, object] = field(default_factory=dict)


Emit = Callable[[Event], None]


class Workspace(Protocol):
    """Project state the Director may read and change."""

    async def state(self) -> ToolState:
        """Current timeline + analysis signals."""
        ...

    async def current_version(self) -> int:
        """Current version pointer."""
        ...

    async def commit(self, outcome: ToolOutcome) -> int:
        """Persist ``outcome.timeline`` as a new version; return its number."""
        ...

    async def move(self, effect: Effect) -> int:
        """Undo/redo pointer move; return the version now current."""
        ...

    async def render(self, profile: str) -> tuple[str, str]:
        """Enqueue a render of the current version; return (render_id, job_id)."""
        ...

    async def dub(self, language: str) -> str:
        """Enqueue dubbing of the current version into ``language``; return the job id."""
        ...


class AudioGenerator(Protocol):
    """Generated audio (ElevenLabs behind ``GeneratedAudioStore``; fakes in tests)."""

    async def sound(self, prompt: str, duration_s: float) -> LibraryItem:
        """A sound effect for the description (cached by content hash)."""
        ...

    async def voice(self, text: str) -> LibraryItem:
        """A voiceover of the text (cached by content hash)."""
        ...


@dataclass
class DirectorResult:
    """What one chat turn did."""

    reply: str = ""
    versions: list[int] = field(default_factory=list)
    renders: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    question: str | None = None
    iterations: int = 0
    stopped: Literal["answered", "asked", "cap", "max_tokens", "refusal", "direct"] = "answered"
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    history: list[AgentMessage] = field(default_factory=list)
    coverage_followup: list[str] = field(default_factory=list)  # gaps the model was told about
    autofixed: list[str] = field(default_factory=list)  # tools the Director applied itself
    critic_reports: list[CriticReport] = field(default_factory=list)  # critic evaluations


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _add(a: Usage, b: Usage) -> Usage:
    return Usage(
        input_tokens=a.input_tokens + b.input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
        cache_read_tokens=a.cache_read_tokens + b.cache_read_tokens,
        cache_write_tokens=a.cache_write_tokens + b.cache_write_tokens,
        thought_tokens=a.thought_tokens + b.thought_tokens,
    )


def _capture_host(call: ToolCall) -> str:
    """Host of a capture_webpage call's URL ('' for other tools or bad input)."""
    if call.name != "capture_webpage":
        return ""
    from urllib.parse import urlparse

    url = call.args.get("url")
    return (urlparse(url).hostname or "").removeprefix("www.") if isinstance(url, str) else ""


class _Turn:
    """Mutable bookkeeping for one chat turn."""

    def __init__(
        self,
        ws: Workspace,
        emit: Emit,
        result: DirectorResult,
        generator: AudioGenerator | None = None,
        message: str = "",
        explainer: ExplainerBuilder | None = None,
    ) -> None:
        self.ws = ws
        self.message = message
        self.generator = generator
        self.explainer = explainer
        self.emit = emit
        self.result = result
        self.failures: dict[str, int] = {}
        self.needs_preview = False
        self.rendered = False
        self.log: list[tuple[str, bool, str]] = []  # (tool, ok, short reason)
        self.exported_version: int | None = None  # version the last final export rendered
        self.export_monetized = True
        self.blocked_hosts: set[str] = set()  # sites that refused capture this turn
        self.completed: set[str] = set()  # includes successful read-only/no-op calls

    async def call(self, call: ToolCall) -> ToolResult:
        """Execute one tool call end to end and build the model-facing result."""
        self.emit(Event("tool_call", {"id": call.id, "name": call.name, "args": call.args}))
        self.result.tools.append(call.name)
        if self.failures.get(call.name, 0) >= MAX_FAILURES_PER_TOOL:
            return self._error(
                call, f"{call.name} failed {MAX_FAILURES_PER_TOOL} times; stop and tell the user"
            )
        export_params: mvp.ExportIn | None = None
        if call.name == "export":
            try:
                export_params = mvp.ExportIn.model_validate(call.args)
            except ValueError:
                pass  # execute() supplies the actionable validation error
        if (
            export_params is not None
            and not export_params.monetized
            and not CONSENT.search(self.message)
        ):
            # ADR-014: only the user may waive the monetisation guard.
            self.log.append((call.name, False, "needs_consent"))
            return self._error(
                call,
                "monetized=false needs the user's say-so. Fix: call ask_user whether the reel "
                "will be monetised (options: 'Not monetised, export as is' / 'Swap the "
                "personal-use assets'), then stop",
                "needs_consent",
            )
        if call.name == "export":
            pending = coverage.explicit_tools(self.message) - self.completed - {"export"}
            if pending:
                return self._error(
                    call,
                    "Complete required tools before exporting: " + ", ".join(sorted(pending)),
                    "incomplete_requirements",
                )
        if (
            call.name in coverage.COVERED_BY_EXPLAINER
            and "make_explainer" in self.completed
            and call.name not in coverage.explicit_tools(self.message)
        ):
            return self._error(
                call,
                f"make_explainer already did this ({call.name}) in this turn. Do not repeat it. "
                "Next: call review_render or preview to check the result, then export if asked, "
                "or tell the user what was built",
                "already_covered",
            )
        host = _capture_host(call)
        if host in self.blocked_hosts:
            return self._error(
                call,
                f"{host} blocks automated capture (already tried this turn, incl. its archived "
                "copy). Do not retry it. Use a different official page or a reputable news "
                "article, or continue without a screenshot for this beat",
                "site_blocked",
            )
        started = time.monotonic()
        state = await self.ws.state()
        if call.name == "make_explainer":
            state = await self._prepare_explainer(call, state)
        elif call.name in GENERATING_TOOLS or call.name in SHOWCASE_TOOLS:
            state = await self._prepare(call, state)
        if call.name == "resolve_visuals" and state.catalog is not None:
            from dataclasses import replace

            from app.settings import get_settings
            from app.storage import get_storage
            from app.tools.storyboard import ResolveVisualsIn
            from app.visuals.search import search_catalog

            try:
                query = ResolveVisualsIn.model_validate(call.args)
                candidates = await asyncio.to_thread(
                    search_catalog,
                    state.catalog,
                    state.catalog.root,
                    state.catalog.meme_dir,
                    get_storage(get_settings()),
                    query.entity,
                    query.role,
                    state.timeline.project_id,
                )
                state = replace(
                    state,
                    prepared_evidence=candidates.selected,
                    visual_rejections=candidates.rejected,
                )
            except ValueError:
                pass  # typed executor supplies malformed-query errors

        outcome = execute(call.name, call.args, state)
        if isinstance(outcome, ToolFailure):
            self.failures[call.name] = self.failures.get(call.name, 0) + 1
            code = outcome.errors[0].code if outcome.errors else "error"
            if host and "blocks automated capture" in outcome.message():
                self.blocked_hosts.add(host)
            self.log.append((call.name, False, code))
            return self._error(call, outcome.message(), code, _ms(started))
        facts = await self._apply(outcome)
        if outcome.effect != Effect.NONE:
            self.log.append((call.name, True, ""))
        payload = outcome.output(**facts).model_dump(mode="json")
        self.completed.add(call.name)
        if call.name == "make_explainer":  # its captions/music/SFX/zooms satisfy those requests
            self.completed |= coverage.COVERED_BY_EXPLAINER - coverage.explicit_tools(self.message)
        if export_params is not None:
            self.export_monetized = export_params.monetized
        result = {"id": call.id, "name": call.name, "ok": True, "result": payload}
        self.emit(Event("tool_result", {**result, "ms": _ms(started)}))
        return ToolResult(call_id=call.id, name=call.name, content=json.dumps(payload))

    async def _prepare(self, call: ToolCall, state: ToolState) -> ToolState:
        """Generate the clip a generating tool needs. Any failure leaves ``prepared`` empty
        and the executor answers with ``generation_unavailable`` plus a fallback hint."""
        try:
            params = get_tool(call.name).input_model.model_validate(call.args)
        except ValueError:
            return state  # the executor reports the validation errors
        try:
            if call.name in SHOWCASE_TOOLS:
                if state.catalog is None:
                    return state
                images = GeneratedImageStore(state.catalog.root, state.catalog.meme_dir)
                if isinstance(params, mvp.InfographicIn):
                    item = await asyncio.to_thread(images.infographic, params)
                elif isinstance(params, mvp.AnnotateIn):
                    item = await asyncio.to_thread(images.annotate, params)
                elif isinstance(params, mvp.CaptureIn):
                    item = await capture_webpage(params, images)
                else:
                    return state
                state.catalog.reload("showcase")
                return dataclasses.replace(state, prepared=item)
            if self.generator is None:
                return state
            if isinstance(params, mvp.GenerateSfxIn):
                item = await self.generator.sound(params.prompt, params.duration_s)
            elif isinstance(params, mvp.AddVoiceoverIn):
                item = await self.generator.voice(params.text)
            else:
                return state
        except Exception as exc:  # provider failures must not break the turn
            self.emit(Event("error", {"tool": call.name, "message": str(exc)[:200]}))
            return dataclasses.replace(state, preparation_error=str(exc)[:200])
        if state.catalog is not None:
            state.catalog.reload("generated")
        return dataclasses.replace(state, prepared=item)

    async def _prepare_explainer(self, call: ToolCall, state: ToolState) -> ToolState:
        """Run the builder (one model request plus local-library work) for make_explainer."""
        if self.explainer is None:
            return dataclasses.replace(state, preparation_error="no explainer builder configured")
        try:
            params = mvp.MakeExplainerIn.model_validate(call.args)
        except ValueError:
            return state  # the executor reports the validation errors
        try:
            built = await self.explainer.build(
                state.timeline,
                message=self.message,
                target_s=params.target_seconds,
                focus=params.focus,
                faces=state.faces,
            )
        except Exception as exc:  # a failed build must not break the turn
            self.emit(Event("error", {"tool": call.name, "message": str(exc)[:200]}))
            return dataclasses.replace(state, preparation_error=str(exc)[:200])
        return dataclasses.replace(state, prepared_explainer=built)

    async def _apply(self, outcome: ToolOutcome) -> dict[str, object]:
        match outcome.effect:
            case Effect.NEW_VERSION:
                version = await self.ws.commit(outcome)
                self.result.versions.append(version)
                self.needs_preview = self.needs_preview or outcome.needs_preview
                diff = outcome.diff.model_dump() if outcome.diff else {}
                self.emit(Event("timeline_version_created", {"version": version, "diff": diff}))
                return {"version": version}
            case Effect.UNDO | Effect.REDO:
                before = await self.ws.current_version()
                version = await self.ws.move(outcome.effect)
                if version != before:
                    self.result.versions.append(version)
                    self.needs_preview = True
                    self.emit(
                        Event(
                            "timeline_version_created",
                            {"version": version, "diff": {"op": outcome.effect.value}},
                        )
                    )
                state = await self.ws.state()
                return {"version": version, "summary": summarize(state.timeline)}
            case Effect.RENDER:
                profile = str(outcome.fields.get("profile", "preview"))
                render_id, job_id = await self.ws.render(profile)
                self.result.renders.append(render_id)
                self.rendered = self.rendered or profile == "preview"
                if profile == "final":
                    self.exported_version = await self.ws.current_version()
                kind: EventType = "preview_queued" if profile == "preview" else "render_queued"
                self.emit(
                    Event(kind, {"render_id": render_id, "job_id": job_id, "profile": profile})
                )
                return {"render_id": render_id, "job_id": job_id}
            case Effect.DUB:
                language = str(outcome.fields["language"])
                job_id = await self.ws.dub(language)
                self.emit(Event("dub_queued", {"job_id": job_id, "language": language}))
                return {
                    "job_id": job_id,
                    "note": f"dubbing into {language} in the background; it becomes a new "
                    "version when ready",
                }
            case Effect.ASK:
                self.result.question = str(outcome.fields["question"])
                self.emit(Event("ask", dict(outcome.fields)))
                return {}
            case _:
                return {"version": await self.ws.current_version()}

    def _error(
        self, call: ToolCall, message: str, code: str = "rejected", ms: int = 0
    ) -> ToolResult:
        data = {"id": call.id, "name": call.name, "ok": False, "error": message}
        self.emit(Event("tool_result", {**data, "code": code, "ms": ms}))
        return ToolResult(call_id=call.id, name=call.name, content=message, is_error=True)

    async def finish(self) -> None:
        """Queue one preview if this turn changed something visible and none was rendered;
        re-export if edits landed after this turn's export (it would be stale)."""
        if self.exported_version is not None:
            current = await self.ws.current_version()
            if current != self.exported_version:
                # Late edits can introduce personal-use assets. Re-enter the same
                # validator/consent path as an explicit export, never render around it.
                refreshed = await self.call(
                    ToolCall(
                        id="finish-export",
                        name="export",
                        args={"profile": "final", "monetized": self.export_monetized},
                    )
                )
                if refreshed.is_error:
                    self.result.reply += "\nFinal export needs attention: " + refreshed.content
                    self.exported_version = None
                    self.rendered = False
                    self.needs_preview = True
            if self.exported_version is not None:
                self.rendered = True  # the current final doubles as a preview
        if self.needs_preview and not self.rendered:
            render_id, job_id = await self.ws.render("preview")
            self.result.renders.append(render_id)
            self.emit(
                Event(
                    "preview_queued",
                    {"render_id": render_id, "job_id": job_id, "profile": "preview"},
                )
            )


async def run_director(
    llm: ToolCallingLLM,
    ws: Workspace,
    system: str,
    message: str,
    history: list[AgentMessage] | None = None,
    emit: Emit | None = None,
    max_iters: int = MAX_ITERS,
    generator: AudioGenerator | None = None,
    enable_critic: bool = False,
    max_critic_iters: int = 2,
    critic_llm: LLMProvider | None = None,
    explainer: ExplainerBuilder | None = None,
    memory: str = "",
) -> DirectorResult:
    """Handle one user chat message. Always terminates within ``max_iters`` model turns.

    Without a ``generator`` (no ElevenLabs key) the generated-audio tools are hidden.
    When ``enable_critic=True``, reviews the timeline after edits and self-corrects up
    to ``max_critic_iters``. ``memory`` is a fenced <creator_memory> block (ADR-030), sent
    with this turn's message so it outweighs older chat history; empty means memory off.
    """
    sink: Emit = emit or (lambda _e: None)
    result = DirectorResult(model=llm.model)
    turn = _Turn(ws, sink, result, generator, message, explainer)

    direct = route(message)
    if direct is not None:
        res = await turn.call(direct)
        await turn.finish()
        result.reply = _direct_reply(direct.name, res)
        result.stopped = "direct"
        sink(Event("done", {"reply": result.reply}))
        return result

    start_state = await ws.state()
    tl = start_state.timeline
    visuals = (
        keywords.describe(keywords.find_cues(tl, start_state.catalog))
        if start_state.catalog is not None
        else ""
    )
    parts = [message, memory, timeline_state(tl, visuals)]
    msgs = [
        *(history or []),
        AgentMessage(role="user", text="\n\n".join(p for p in parts if p)),
    ]
    tools = tool_specs(exclude=frozenset() if generator else ELEVENLABS_TOOLS)
    coverage_rounds = 0
    critic_count = 0
    for i in range(max_iters):
        result.iterations = i + 1
        reply = await llm.complete_with_tools(
            ToolTurnRequest(system=system, messages=msgs, tools=tools),
            on_text=lambda t: sink(Event("token", {"text": t})),
        )
        result.usage = _add(result.usage, reply.usage)
        result.model = reply.model or result.model
        msgs.append(reply.as_message())
        if reply.stop_reason in ("max_tokens", "refusal"):
            # never run calls from a truncated or refused turn
            result.stopped = reply.stop_reason
            result.reply = reply.text or "I couldn't complete that request."
            break
        if not reply.calls:
            gaps = coverage.missing(message, turn.completed, (await ws.state()).timeline)
            if gaps and coverage_rounds:
                # Still skipped after the follow-up: apply the safe defaults ourselves.
                await _autofix(turn, gaps, message, tl)
                gaps = coverage.missing(message, turn.completed, (await ws.state()).timeline)
                if gaps and not coverage.explicit_tools(message):
                    result.coverage_followup = gaps
                    result.reply = "Still incomplete: " + "; ".join(gaps)
                    break
            if gaps:
                # Recheck the outcome of safe defaults. Creative requirements cannot
                # silently disappear merely because the model ignored a follow-up.
                if coverage_rounds >= 3:
                    result.coverage_followup = gaps
                    result.stopped = "cap"
                    result.reply = "Still incomplete: " + "; ".join(gaps)
                    break
                coverage_rounds += 1
                result.coverage_followup = gaps
                note = (
                    "Not done yet from the user's request: " + "; ".join(gaps) + ". "
                    "Call the tools for these now. Skip one only if it is truly impossible, "
                    "and then say why."
                )
                msgs.append(AgentMessage(role="user", text=note))
                continue

            if enable_critic and critic_count < max_critic_iters and len(result.versions) > 0:
                current_tl = (await ws.state()).timeline
                report = await evaluate_preview(critic_llm, current_tl, user_prompt=message)
                result.critic_reports.append(report)
                sink(Event("critic_feedback", report.model_dump(mode="json")))
                if report.verdict == "needs_edits" and report.suggested_edits:
                    critic_count += 1
                    header = (
                        f"Video Critic Review (Score: {report.overall_score}/10, "
                        f"Verdict: {report.verdict}):\n"
                    )
                    critic_msg = (
                        header
                        + "\n".join(f"- Issue: {iss}" for iss in report.issues)
                        + "\nSuggested Fixes:\n"
                        + "\n".join(f"- {fix}" for fix in report.suggested_edits)
                        + "\nPlease call the tools to apply these improvements now."
                    )
                    msgs.append(AgentMessage(role="user", text=critic_msg))
                    continue

            result.reply = reply.text
            break
        results = [await turn.call(c) for c in reply.calls]
        msgs.append(AgentMessage(role="user", results=results))
        if result.question is not None:
            result.stopped = "asked"
            result.reply = reply.text or result.question
            break
    else:
        result.stopped = "cap"
        result.reply = "Here is what I did."
        gaps = coverage.missing(message, turn.completed, (await ws.state()).timeline)
        if gaps:  # out of steps: still deliver the requested basics (music, SFX, export...)
            result.coverage_followup = result.coverage_followup or gaps
            await _autofix(turn, gaps, message, tl)
    await turn.finish()
    result.reply = _grounded(result.reply, turn.log)
    result.history = msgs
    sink(Event("done", {"reply": result.reply, "stopped": result.stopped}))
    return result


async def _autofix(turn: _Turn, gaps: list[str], message: str, tl: Timeline) -> None:
    """Deterministic defaults for requested items the model would not do (music, SFX...)."""
    text = " ".join(w.text for w in tl.transcript.words)
    catalog = (await turn.ws.state()).catalog
    genres = catalog.genres() if catalog is not None else None
    calls = coverage.autofix_calls(gaps, message, text, genres)
    pending_creative = any(g.startswith("tool:") and g != "tool:export" for g in gaps)
    if pending_creative:
        calls = [(name, args) for name, args in calls if name != "export"]
    turn.result.autofixed = [name for name, _ in calls]
    for n, (name, args) in enumerate(calls, start=1):
        await turn.call(ToolCall(id=f"autofix{n}", name=name, args=args))


def _grounded(reply: str, log: list[tuple[str, bool, str]]) -> str:
    """Append what actually happened, so the reply can never claim an edit that failed."""
    if not log:
        return reply
    done = sorted({t for t, ok, _ in log if ok})
    failed = sorted({f"{t} ({why})" for t, ok, why in log if not ok and t not in done})
    lines = []
    if done:
        lines.append("Applied: " + ", ".join(done) + ".")
    if failed:
        lines.append("Not applied: " + ", ".join(failed) + ".")
    return f"{reply}\n\n" + " ".join(lines) if reply else " ".join(lines)


def _direct_reply(name: str, res: ToolResult) -> str:
    if res.is_error:
        return res.content
    data = json.loads(res.content)
    if name in ("undo", "redo"):
        return f"{name.capitalize()} done; now at version {data.get('version')}."
    return f"{name} queued (render {data.get('render_id')})."
