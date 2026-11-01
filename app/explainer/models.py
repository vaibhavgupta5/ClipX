"""Compact planner contract. Small on purpose: fewer tokens in, fewer ways to be wrong."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.scenes.models import ID

WORD = r"^w\d+$"
CardFamily = Literal[
    "impact_title", "hub", "checklist", "counter", "multi_view", "proof_focus", "bar_chart"
]


class Lenient(BaseModel):
    """Planner JSON: tolerate unknown keys (models add them), reject wrong types."""

    model_config = ConfigDict(frozen=True, extra="ignore", allow_inf_nan=False)


class Card(Lenient):
    """One shot: a word range, a visual family and its labels. Code builds the scene."""

    id: str = Field(pattern=ID)
    start_word: str = Field(pattern=WORD)
    end_word: str = Field(pattern=WORD)
    family: CardFamily
    title: str = Field(min_length=1, max_length=64)
    eyebrow: str = Field(default="", max_length=28)
    tone: Literal["neutral", "risk"] = "neutral"
    priority: int = Field(default=3, ge=1, le=5, description="5 = never cut for length")
    kicker: str = Field(default="", max_length=40)
    headline: str = Field(default="", max_length=48)
    backdrop: str = Field(default="", max_length=40)
    center: str = Field(default="", max_length=24)
    items: list[str] = Field(default_factory=list, max_length=8)
    values: list[float] = Field(default_factory=list, max_length=6)
    number: float | None = Field(default=None, ge=0, le=1e12)
    prefix: str = Field(default="", max_length=4)
    suffix: str = Field(default="", max_length=6)
    number_label: str = Field(default="", max_length=80)
    source_url: str = Field(default="", max_length=2048)
    highlight: str = Field(default="", max_length=160)

    @model_validator(mode="after")
    def payload(self) -> "Card":
        n = len(self.items)
        rules = {
            "impact_title": bool(self.headline),
            "hub": bool(self.center) and 3 <= n <= 8,
            "checklist": 2 <= n <= 7,
            "multi_view": 2 <= n <= 4,
            "counter": self.number is not None and bool(self.number_label),
            "proof_focus": bool(self.source_url),
            "bar_chart": 2 <= n <= 6 and len(self.values) == n,
        }
        if not rules[self.family]:
            raise ValueError(f"card {self.id}: incomplete {self.family} payload")
        if any(len(i) > 44 or not i.strip() for i in self.items):
            raise ValueError(f"card {self.id}: item labels must be 1-44 characters")
        return self


class Extra(Lenient):
    """A comic or cutaway beat on raw footage, resolved from the local library."""

    kind: Literal["meme", "gif", "broll"]
    at_word: str = Field(pattern=WORD)
    query: str = Field(min_length=2, max_length=40)


class Plan(Lenient):
    mood: Literal["tech", "calm", "dramatic", "upbeat", "serious"] = "tech"
    accent: Literal["teal", "white", "yellow", "mint", "amber"] = "teal"
    drop: list[tuple[str, str]] = Field(default_factory=list, max_length=12)
    cards: list[Card] = Field(min_length=1, max_length=16)
    extras: list[Extra] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def ids(self) -> "Plan":
        ids = [c.id for c in self.cards]
        if len(ids) != len(set(ids)):
            raise ValueError("card ids must be unique")
        for a, b in self.drop:
            if not (re.match(WORD, a) and re.match(WORD, b)):
                raise ValueError("drop ranges use word ids like w12")
        return self
