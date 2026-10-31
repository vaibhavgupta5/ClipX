"""Bounded image-generation inputs; no model-provided markup or filter strings."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.timeline.schema import HEX_COLOR, WORD_ID, Layout


class Placement(BaseModel):
    """A generated image is placed through the ordinary licensed overlay path."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    at_word: str = Field(pattern=WORD_ID)
    duration_ms: int = Field(default=3200, ge=600, le=6000)
    layout: Layout = "showcase"
    motion: Literal["none", "push_in", "pull_out", "pan_up", "pan_down"] = "pull_out"
    entrance: Literal["cut", "slide_up"] = "slide_up"


class Stat(BaseModel):
    """A claim supplied by the user or grounded in the transcript."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    value: str = Field(min_length=1, max_length=18)
    label: str = Field(min_length=1, max_length=48)


class InfographicIn(Placement):
    """Fixed, phone-readable statistic cards."""

    title: str = Field(min_length=1, max_length=76)
    stats: list[Stat] = Field(min_length=1, max_length=3)
    style: Literal["dark", "paper", "electric"] = "dark"
    source_label: str = Field(default="", max_length=80)
    variant: Literal["auto", "code", "steps", "metrics", "flow"] = "auto"


class Annotation(BaseModel):
    """Coordinates are fractions of the source image, before framing."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["arrow", "box", "label"]
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)
    x2: float = Field(default=1, ge=0, le=1, allow_inf_nan=False)
    y2: float = Field(default=1, ge=0, le=1, allow_inf_nan=False)
    text: str = Field(default="", max_length=48)
    color: str = Field(default="#FFD400", pattern=HEX_COLOR)


class AnnotateIn(Placement):
    """Annotate a catalog image, preserving its original licensing."""

    asset_id: str = Field(min_length=1, max_length=160)
    annotations: list[Annotation] = Field(default_factory=list, max_length=12)
    frame: Literal["browser", "shadow", "none"] = "browser"


class CaptureIn(Placement):
    """Capture a public webpage; screenshots default to personal use."""

    url: str = Field(min_length=1, max_length=2048)
    selector: str | None = Field(default=None, min_length=1, max_length=200)
    viewport: Literal["desktop", "mobile", "portrait"] = "desktop"
    highlight_text: str | None = Field(default=None, min_length=1, max_length=160)
    reading_mode: bool = False
