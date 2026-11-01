"""Anchor labels to the spoken words that name them. Pure functions, no model."""

import re

from app.timeline.transcript import Word

STOP = frozenset(
    "the and for with that this from your you are was were has have had its their they them "
    "then than into onto over about what when where which while will can could would should "
    "our out not but all any one two more most some such like just also very".split()
)
NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "hundred": 100, "thousand": 1000, "million": 10**6,
}  # fmt: skip


def norm(text: str) -> str:
    """Lowercase alphanumerics only."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def tokens(label: str) -> list[str]:
    """Content tokens of a label (stopwords and 1-2 letter words dropped, digits kept)."""
    out = [norm(t) for t in re.split(r"[\s/_-]+", label)]
    return [t for t in out if t and t not in STOP and (len(t) >= 3 or t.isdigit())]


def same_word(word: str, token: str) -> bool:
    """Exact, or a shared 5-letter stem ('computer' ~ 'computers', 'testing' ~ 'tests')."""
    if word == token:
        return True
    if len(word) >= 4 and len(token) >= 4:
        n = min(5, len(word), len(token))
        return word[:n] == token[:n]
    return False


def anchor(label: str, words: list[Word]) -> str | None:
    """First word in ``words`` that names any content token of ``label``."""
    wanted = tokens(label)
    for w in words:
        n = norm(w.text)
        if n and any(same_word(n, t) for t in wanted):
            return w.id
    return None


def anchor_all(labels: list[str], words: list[Word]) -> list[str]:
    """One word per label: where it is spoken, else an even spread across the range.

    Unmatched labels are placed between their matched neighbours so reveals stay in the order
    the card lists them and never fire before the shot starts.
    """
    if not words:
        return []
    ids = [w.id for w in words]
    index = {wid: i for i, wid in enumerate(ids)}
    found = [anchor(label, words) for label in labels]
    n = len(labels)
    result: list[int] = []
    for i, f in enumerate(found):
        spread = int((i + 0.5) * len(ids) / n)
        result.append(index[f] if f is not None else min(spread, len(ids) - 1))
    # Keep reveal order monotonic with the list so a diagram builds top to bottom.
    for i in range(1, n):
        if found[i] is None and result[i] < result[i - 1]:
            result[i] = result[i - 1]
    return [ids[i] for i in result]


def number_anchor(value: float, words: list[Word]) -> str | None:
    """Word where a spoken number begins ('4' of '4,000', or 'thousand'), else None."""
    digits = str(int(value))
    for w in words:
        n = norm(w.text)
        if n.isdigit() and digits.startswith(n):
            return w.id
        if NUMBER_WORDS.get(n) == value:
            return w.id
    return None


def number_is_spoken(value: float, words: list[Word]) -> bool:
    """Grounding: the digits (or number word) are in the retained narration."""
    digits = str(int(value))
    spoken = "".join(re.sub(r"[^0-9]", "", w.text) for w in words)
    if digits in spoken:
        return True
    return any(NUMBER_WORDS.get(norm(w.text)) == value for w in words)


def sentences(words: list[Word]) -> list[list[Word]]:
    """Split on sentence punctuation."""
    out: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        cur.append(w)
        if w.text.rstrip().endswith((".", "?", "!")):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def slug(text: str, taken: set[str], prefix: str = "") -> str:
    """Safe unique ID (letters first, no reserved scene targets)."""
    base = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:20] or "item"
    if not base[0].isalpha():
        base = "n_" + base
    base = prefix + base
    if base in {"title", "body", "result", "value", "grid", "hub", "before", "after"}:
        base = "i_" + base
    out, n = base, 2
    while out in taken:
        out, n = f"{base}_{n}", n + 1
    taken.add(out)
    return out
