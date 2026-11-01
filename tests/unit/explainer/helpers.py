"""Offline fixtures for the explainer: a tiny licensed library, a transcript, a fake model."""

import io
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from app.providers.base import ChatReply, ChatRequest
from app.providers.local import AssetCatalog
from app.timeline.schema import Timeline, VideoClip
from app.timeline.transcript import Transcript, Word

SENTENCES = [
    "OpenAI just launched dots today.",
    "Get our app off this legacy API before it shuts down.",
    "That API is used by the web app and the mobile app and the billing service and search.",
    "Anyway here is a long tangent about my weekend plans and lunch.",
    "Dots trace dependencies and then write code and run the tests and open pull requests.",
    "Another tangent about nothing at all really just filler words here.",
    "They work with more than 4 ,000 apps including GitHub and Gmail.",
    "And you stay in control of everything they do.",
    "Thanks for watching and see you next time everybody.",
]
KINDS = ["images", "gifs", "videos", "memes", "music", "sfx", "icons", "generated", "showcase"]


def transcript() -> Transcript:
    words, t = [], 0.0
    for s in SENTENCES:
        for text in s.split():
            words.append(
                Word(
                    id=f"w{len(words) + 1}",
                    start=round(t, 2),
                    end=round(t + 0.4, 2),
                    text=text,
                    display_text=text,
                    lang="en",
                )
            )
            t += 0.5
        t += 0.5
    return Transcript(words=words)


def timeline() -> Timeline:
    tr = transcript()
    return Timeline(
        project_id=uuid.UUID(int=7),
        transcript=tr,
        video_clips=[VideoClip(id="c1", asset="a", src_in=0.0, src_out=tr.words[-1].end + 0.2)],
    )


def wid(tl: Timeline, text: str, nth: int = 0) -> str:
    """Id of the nth word with this text."""
    return [w.id for w in tl.transcript.words if w.text == text][nth]


def _item(kind: str, name: str, **extra: object) -> dict[str, object]:
    return {
        "id": f"{kind}:{name}",
        "file": f"{name}.png" if kind == "icons" else f"{name}.bin",
        "title": name.replace("-", " ").title(),
        "tags": [name],
        "source": "test",
        "license": "CC0-1.0",
        "attribution_required": False,
        "commercial_use": True,
        **extra,
    }


def catalog(tmp: Path) -> AssetCatalog:
    root = tmp / "assets"
    for k in KINDS:
        (root / k).mkdir(parents=True)
    manifests: dict[str, list[dict[str, object]]] = {k: [] for k in KINDS}
    for name in ("github", "gmail"):
        manifests["icons"].append(_item("icons", name, aliases=[name]))
        buf = io.BytesIO()
        Image.new("RGBA", (128, 128), "white").save(buf, format="PNG")
        (root / "icons" / f"{name}.png").write_bytes(buf.getvalue())
    for kind in ("boom", "whoosh", "swoosh", "click", "pop", "ding", "riser", "glitch"):
        manifests["sfx"].append(_item("sfx", kind, sfx_type=kind, duration_s=0.5))
    manifests["music"].append(_item("music", "bed", genre="electronic", duration_s=200.0))
    manifests["videos"].append(_item("videos", "chip", tags=["chip", "hardware"]))
    manifests["memes"].append(_item("memes", "waiting", tags=["waiting", "skeleton"]))
    for k, items in manifests.items():
        (root / k / "manifest.json").write_text(json.dumps(items))
        for item in items:  # the catalog ignores entries whose media file is missing
            f = root / k / str(item["file"])
            if not f.exists():
                f.write_bytes(b"x")
    return AssetCatalog(root, tmp / "memes")


class FakeLLM:
    """Replies in order; raises when a reply is an Exception."""

    model = "fake"

    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.requests: list[ChatRequest] = []

    async def complete(self, request: ChatRequest) -> ChatReply:
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatReply(text=reply)


def plan_json(tl: Timeline, **overrides: object) -> str:
    """A realistic plan for the fixture transcript (hook, hub, checklist, counter, payoff)."""
    w = lambda text, n=0: wid(tl, text, n)  # noqa: E731
    plan: dict[str, object] = {
        "mood": "tech",
        "accent": "teal",
        "drop": [[w("Anyway"), w("lunch.")], [w("Another"), w("here.")]],
        "cards": [
            {"id": "hook", "start_word": w("OpenAI"), "end_word": w("today."),
             "family": "impact_title", "title": "OpenAI launched dots", "kicker": "BREAKING",
             "headline": "OpenAI launched dots", "priority": 5},
            {"id": "callers", "start_word": w("That"), "end_word": w("search."),
             "family": "hub", "title": "Used all over the codebase", "center": "Legacy API",
             "items": ["Web app", "Mobile app", "Billing", "Search"], "tone": "risk"},
            {"id": "steps", "start_word": w("Dots", 0), "end_word": w("requests."),
             "family": "checklist", "title": "Then it does the work",
             "items": ["Trace dependencies", "Write code", "Run tests", "Open pull requests"]},
            {"id": "apps", "start_word": w("They"), "end_word": w("Gmail."),
             "family": "counter", "title": "Works with your apps", "number": 4000,
             "suffix": "+", "number_label": "apps across ChatGPT", "priority": 4},
            {"id": "close", "start_word": w("And"), "end_word": w("do."),
             "family": "impact_title", "title": "You stay in control",
             "kicker": "THE POINT", "headline": "You stay in control", "priority": 5},
        ],
        "extras": [{"kind": "meme", "at_word": w("Get"), "query": "waiting"}],
    }  # fmt: skip
    plan.update(overrides)
    return json.dumps(plan)


def namespace(**kw: object) -> SimpleNamespace:
    return SimpleNamespace(**kw)
