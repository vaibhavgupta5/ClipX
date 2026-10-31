"""LLM text-only stages: beats, romanization, emphasis tags.

Media-derived text is UNTRUSTED DATA (rule 6): it is framed as quoted data in
prompts, outputs are strict-JSON-validated, and timings/IDs always come from
our own transcript — never from the model.
"""

import json
from typing import Any

from app.providers.base import ChatMessage, ChatRequest, LLMProvider
from app.timeline.transcript import Transcript

MAX_BEATS = 20


def transcript_lines(transcript: Transcript) -> str:
    """LLM-format transcript: [wID] text lines."""
    return "\n".join(f"[{w.id}] {w.text}" for w in transcript.words)


async def _complete_json(llm: LLMProvider, system: str, user: str) -> Any:
    """One completion parsed as JSON (raises ValueError with the raw text)."""
    reply = await llm.complete(
        ChatRequest(
            messages=[
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=user),
            ]
        )
    )
    try:
        return json.loads(strip_code_fence(reply.text))
    except json.JSONDecodeError as exc:
        raise ValueError(f"model did not return JSON: {reply.text[:200]!r} ({exc})") from None


def strip_code_fence(text: str) -> str:
    """Models often wrap JSON in a ```json fence despite instructions; unwrap only that."""
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1] if "\n" in body else ""
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
    return body.strip()
