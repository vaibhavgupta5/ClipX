"""Seed the creator-memory demo in Meko (hackCBS Track A, ADR-030). Live calls; needs MEKO_API_KEY.

    uv run python scripts/meko_seed.py            # add seeded history (skips rows already there)
    uv run python scripts/meko_seed.py --reset    # first forget seeded creators' PRIVATE memories

Everything written here is labelled seeded: chat turns go through conversation_add_message
with ``seed`` set, and this script prints each Meko call it made. Promoted canon is never
deleted (Meko promotion is one-way); re-runs skip canon lines that already exist.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.memory.models import CURATOR, DIRECTOR  # noqa: E402
from app.providers.registry import creator_memory, meko_call_log  # noqa: E402

# Past chat sessions per creator (seeded): Meko extracts the preferences from the user side.
TURNS: dict[str, list[tuple[str, str]]] = {
    "riya": [
        (
            "For all my reels: captions in yellow (#FFD400) text, big, about 96 px, two words "
            "a line, lower centre. Never zoom in on my face.",
            "Noted: yellow 96 px captions, two words a line, no face zooms.",
        ),
        (
            "The hook has to land in the first 2 seconds. Cut any intro like 'hi guys' or "
            "'welcome back'.",
            "Trimmed the greeting; the reel now opens on the first claim.",
        ),
        (
            "Music should be upbeat desi pop, never lofi, and always under my voice.",
            "Swapped to an upbeat track at -20 dB, ducked under speech.",
        ),
    ],
    "arjun": [
        (
            "My reels are calm explainers: small white captions around 56 px in the showcase "
            "position, and punch-in zooms on numbers are welcome.",
            "Noted: small white showcase captions; zooms on numbers are fine.",
        ),
        (
            "I like reels around 60 seconds. Don't cut my pauses after a number, they let it "
            "sink in.",
            "Kept the pauses after numbers; total length 58 s.",
        ),
    ],
    "kabir": [
        (
            "Food vlogs: captions in Hinglish, roman script, white with an orange highlight. "
            "Add a sizzle or crunch sound on every close-up bite.",
            "Set Hinglish roman captions with orange highlight; added SFX on bites.",
        ),
        (
            "Keep the street noise, it's the vibe. Only remove wind noise.",
            "Light denoise only; ambience kept.",
        ),
    ],
}
CORRECTIONS = {
    "riya": [
        "Remove filler words such as 'basically' and 'matlab' in every reel.",
        "End every reel on her catchphrase line; never cut the last sentence.",
    ],
    "arjun": [
        "Keep background music low and calm (lofi or ambient).",
        "Show a source screenshot whenever he cites a number or a study.",
    ],
    "kabir": ["Never add memes; his audience finds them cheap."],
}
APPROVED = {  # creator canon: added, then promoted (a person approved these in an earlier session)
    "riya": [
        "No punch-in zooms on Riya's face: remove any that exist.",
        "Riya's reels stay under 45 seconds.",
    ],
    "arjun": ["Arjun's numbers get a zoom and a riser SFX; nothing else gets a zoom."],
    "kabir": ["Kabir's thumbnails and captions never use the word 'viral'."],
}
AGENCY = [
    "Hindi captions: keep size at or under 96 px so Devanagari lines fit the 1080 px frame.",
    "Never put captions in the bottom 15% of the frame: Instagram's UI covers it.",
    "Music under speech sits about 20 dB below the voice; louder music gets reels flagged as "
    "hard to hear.",
    "Screenshots of third-party sites are personal use: ask before a monetised export.",
]


async def main(reset: bool) -> None:
    mem = creator_memory()
    if mem is None:
        raise SystemExit("MEKO_API_KEY is not set")
    p = mem.provider
    for creator in TURNS:
        scope = mem.creator_scope(creator)
        private = await p.list_memories(scope, DIRECTOR, False)
        if reset:
            for m in private:
                await p.delete_memory(scope, m.agent_id or DIRECTOR, m.id)
            private = []
        texts = {m.text for m in private}
        canon = {m.text for m in await p.list_memories(scope, None, True)}
        for user, reply in TURNS[creator]:
            await p.add_turn(scope, DIRECTOR, user, reply, seed=True)
        for text in CORRECTIONS.get(creator, []):
            if text not in texts:
                await p.add_memory(scope, CURATOR, text)
        for text in APPROVED.get(creator, []):
            if text not in canon:
                rows = await p.add_memory(scope, CURATOR, text)
                await p.promote(scope, CURATOR, [r.id for r in rows])
    agency = {m.text for m in await p.list_memories(mem.agency_scope, None, True)}
    for text in AGENCY:
        if text not in agency:
            await mem.share_with_agency(text)
    for c in meko_call_log().since():
        print(f"{c.kind:8} {c.tool:26} {c.scope:22} ok={c.ok} {c.ms:5} ms  {c.detail[:60]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reset", action="store_true", help="forget private memories first")
    asyncio.run(main(ap.parse_args().reset))
