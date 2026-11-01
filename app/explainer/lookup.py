"""Forgiving library lookup for B-roll, memes, GIFs and backdrops.

``AssetCatalog.match`` is deliberately strict (every content token must be a tag), which is right
for brand icons but returned nothing for planner phrases like "server room humming". This chain
widens step by step and reports which tier hit, so a weak guess is visible in the warnings:

1. exact:  every token of the phrase is a tag/title token (scored, as before)
2. token:  any single content token, longest first ("server room humming" -> "humming", "server")
3. fuzzy:  the library's weighted tag/title/synonym search (synonyms: "chip" ~ "processor")
"""

import re
from typing import Literal

from app.providers.local import AssetCatalog, LibraryItem, content_tokens

Tier = Literal["exact", "token", "fuzzy"]
_WORD = re.compile(r"[a-z0-9+]+")


def lookup(catalog: AssetCatalog, kind: str, query: str) -> tuple[LibraryItem, Tier] | None:
    """Best library item for ``query`` in one library, widening until something fits."""
    query = query.strip()
    if not query:
        return None
    hits = catalog.match(kind, query)
    if hits:
        return hits[0][1], "exact"
    words = sorted(_WORD.findall(query.lower()), key=len, reverse=True)
    for word in words:
        if not content_tokens(word):
            continue  # filler / generic medium words never count
        hits = catalog.match(kind, word)
        if hits:
            return hits[0][1], "token"
    found = catalog.search(kind, query, 1)
    return (found[0], "fuzzy") if found else None
