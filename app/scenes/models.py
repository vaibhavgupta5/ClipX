"""Closed scene contracts. Content is data; templates own all executable code."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ID = r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"
SHA = r"^[a-f0-9]{64}$"
Family = Literal[
    "proof_focus",
    "product_walkthrough",
    "architecture_flow",
    "verification_pipeline",
    "before_after",
    "metric_or_code",
    "speaker_bridge",
    "counter",
    "bar_chart",
    "hub",
    "multi_view",
    "checklist",
    "impact_title",
]


class StrictModel(BaseModel):
    """Immutable versioned artifact base; reject unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class VisualEvent(StrictModel):
    """A bounded transition on an existing named element, at a spoken word."""

    target: str = Field(pattern=ID)
    word: str = Field(pattern=r"^w\d+$")
    action: Literal["reveal", "highlight", "connect", "update", "focus", "hide"]
    preset: Literal["snap", "gentle", "emphasis"] = "gentle"
    state: Literal["idle", "active", "accepted", "rejected", "unknown"] = "active"


class Node(StrictModel):
    """One named box; the template assigns its geometry."""

    id: str = Field(pattern=ID)
    label: str = Field(min_length=1, max_length=64)
    detail: str = Field(default="", max_length=100)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)


class Edge(StrictModel):
    """An explicit relationship; never inferred by the renderer."""

    id: str = Field(pattern=ID)
    source: str = Field(pattern=ID)
    target: str = Field(pattern=ID)
    label: str = Field(default="", max_length=32)


class FlowScene(StrictModel):
    template: Literal["architecture_flow", "verification_pipeline"]
    nodes: list[Node] = Field(min_length=2, max_length=6)
    edges: list[Edge] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_graph(self) -> "FlowScene":
        ids = [n.id for n in self.nodes] + [e.id for e in self.edges]
        if len(ids) != len(set(ids)):
            raise ValueError("node and edge IDs must be unique")
        nodes = {n.id for n in self.nodes}
        if any(e.source not in nodes or e.target not in nodes for e in self.edges):
            raise ValueError("edge endpoints must name existing nodes")
        return self


class SceneAnnotation(StrictModel):
    """Source-relative focus box, animated by a named word cue."""

    id: str = Field(pattern=ID)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)
    label: str = Field(default="", max_length=48)

    @model_validator(mode="after")
    def inside(self) -> "SceneAnnotation":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("annotation must stay inside the frozen image")
        return self


class ProofScene(StrictModel):
    template: Literal["proof_focus"] = "proof_focus"
    asset_id: str = Field(pattern=ID)
    excerpt: str = Field(min_length=1, max_length=240)
    source_label: str = Field(min_length=1, max_length=80)
    # Normalized focal rectangle in the frozen source image.
    crop: tuple[float, float, float, float] = (0, 0, 1, 1)
    focus_crop: tuple[float, float, float, float] | None = None
    annotations: list[SceneAnnotation] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def crop_bounds(self) -> "ProofScene":
        for crop in (self.crop, self.focus_crop):
            if crop is None:
                continue
            x, y, w, h = crop
            if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1 or y + h > 1:
                raise ValueError("crop must lie inside source image")
        return self


class WalkthroughScene(StrictModel):
    template: Literal["product_walkthrough"] = "product_walkthrough"
    product: str = Field(min_length=1, max_length=48)
    steps: list[Node] = Field(min_length=1, max_length=4)
    illustrative: Literal[True] = True


class BeforeAfterScene(StrictModel):
    template: Literal["before_after"] = "before_after"
    before: str = Field(min_length=1, max_length=120)
    after: str = Field(min_length=1, max_length=120)
    change: str = Field(min_length=1, max_length=100)


class MetricScene(StrictModel):
    template: Literal["metric_or_code"] = "metric_or_code"
    value: str = Field(min_length=1, max_length=28)
    label: str = Field(min_length=1, max_length=80)
    code: list[str] = Field(default_factory=list, max_length=7)

    @model_validator(mode="after")
    def short_lines(self) -> "MetricScene":
        if any(len(line) > 54 for line in self.code):
            raise ValueError("code lines must fit mobile width (54 characters max)")
        return self


class BridgeScene(StrictModel):
    template: Literal["speaker_bridge"] = "speaker_bridge"
    asset_id: str | None = Field(default=None, pattern=ID)
    headline: str = Field(min_length=1, max_length=90)
    supporting: str = Field(default="", max_length=140)


def _unique(ids: list[str], what: str) -> None:
    if len(ids) != len(set(ids)):
        raise ValueError(f"{what} IDs must be unique")
    if set(ids) & RESERVED_IDS:
        raise ValueError(f"{what} IDs must not reuse reserved targets {sorted(RESERVED_IDS)}")


# Reviewed vector pictograms owned by the template; content only names one.
Pictogram = Literal[
    "browser",
    "mobile",
    "server",
    "database",
    "card",
    "search",
    "user",
    "people",
    "clock",
    "key",
    "cloud",
    "code",
    "flask",
    "chip",
    "message",
    "phone",
    "shield",
    "plug",
    "warning",
    "gear",
    "bolt",
    "doc",
]

RESERVED_IDS = {"title", "body", "result", "value", "grid", "hub", "before", "after"}


class CounterScene(StrictModel):
    """A grounded number that counts up as it is spoken, with an optional lit cell grid."""

    template: Literal["counter"] = "counter"
    value: float = Field(ge=0, le=1e12, description="Final displayed number (from evidence)")
    start: float = Field(default=0, ge=0, le=1e12)
    decimals: int = Field(default=0, ge=0, le=2)
    prefix: str = Field(default="", max_length=4)
    suffix: str = Field(default="", max_length=6, description="Unit, e.g. 'K+', '%', 'x'")
    label: str = Field(min_length=1, max_length=80)
    cells: int = Field(default=0, ge=0, le=64, description="Optional grid lit while counting")


class Bar(StrictModel):
    """One labelled, grounded quantity."""

    id: str = Field(pattern=ID)
    label: str = Field(min_length=1, max_length=28)
    value: float = Field(ge=0, le=1e12)
    display: str = Field(default="", max_length=14, description="Rendered value text")


class BarChartScene(StrictModel):
    template: Literal["bar_chart"] = "bar_chart"
    unit: str = Field(default="", max_length=32)
    bars: list[Bar] = Field(min_length=2, max_length=6)

    @model_validator(mode="after")
    def ids(self) -> "BarChartScene":
        _unique([b.id for b in self.bars], "bar")
        return self


class Spoke(StrictModel):
    """One entity around a hub; optional frozen icon evidence."""

    id: str = Field(pattern=ID)
    label: str = Field(min_length=1, max_length=24)
    asset_id: str | None = Field(default=None, pattern=ID)
    pictogram: Pictogram | None = None


class HubScene(StrictModel):
    template: Literal["hub"] = "hub"
    center: str = Field(min_length=1, max_length=24)
    center_asset_id: str | None = Field(default=None, pattern=ID)
    center_pictogram: Pictogram | None = None
    spokes: list[Spoke] = Field(min_length=3, max_length=8)

    @model_validator(mode="after")
    def ids(self) -> "HubScene":
        _unique([x.id for x in self.spokes], "spoke")
        return self


class Tile(StrictModel):
    """One view in a multi-view grid: an image or a short glyph, never markup."""

    id: str = Field(pattern=ID)
    label: str = Field(min_length=1, max_length=32)
    caption: str = Field(default="", max_length=60)
    asset_id: str | None = Field(default=None, pattern=ID)
    glyph: str = Field(default="", max_length=3, description="Short badge, e.g. '?' or '2x'")
    pictogram: Pictogram | None = None

    @model_validator(mode="after")
    def visual(self) -> "Tile":
        if not self.asset_id and not self.glyph and not self.pictogram:
            raise ValueError("tile needs an image asset_id, a pictogram or a short glyph")
        return self


class MultiViewScene(StrictModel):
    template: Literal["multi_view"] = "multi_view"
    tiles: list[Tile] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def ids(self) -> "MultiViewScene":
        _unique([t.id for t in self.tiles], "tile")
        return self


class CheckItem(StrictModel):
    id: str = Field(pattern=ID)
    label: str = Field(min_length=1, max_length=44)
    detail: str = Field(default="", max_length=24)


class ChecklistScene(StrictModel):
    template: Literal["checklist"] = "checklist"
    items: list[CheckItem] = Field(min_length=2, max_length=7)

    @model_validator(mode="after")
    def ids(self) -> "ChecklistScene":
        _unique([i.id for i in self.items], "item")
        return self


class ImpactTitleScene(StrictModel):
    """Heavy condensed hook title, optionally over a graded frozen image."""

    template: Literal["impact_title"] = "impact_title"
    kicker: str = Field(default="", max_length=40)
    headline: str = Field(min_length=1, max_length=48)
    asset_id: str | None = Field(default=None, pattern=ID)


SceneContent = Annotated[
    FlowScene
    | ProofScene
    | WalkthroughScene
    | BeforeAfterScene
    | MetricScene
    | BridgeScene
    | CounterScene
    | BarChartScene
    | HubScene
    | MultiViewScene
    | ChecklistScene
    | ImpactTitleScene,
    Field(discriminator="template"),
]


class DesignTokens(StrictModel):
    """Small reviewed art direction surface. ``mono`` is the reference line-art grammar."""

    theme: Literal["ink", "paper", "mono"] = "ink"
    accent: Literal["mint", "violet", "amber", "red", "teal", "white", "yellow"] = "mint"


class SceneSpec(StrictModel):
    """Editable scene source, retained in each immutable Timeline."""

    schema_version: Literal[1] = 1
    template_version: Literal[1] = 1
    id: str = Field(pattern=ID)
    title: str = Field(min_length=1, max_length=96)
    eyebrow: str = Field(default="VISUAL EXPLAINER", max_length=40)
    content: SceneContent
    events: list[VisualEvent] = Field(default_factory=list, max_length=48)
    tokens: DesignTokens = Field(default_factory=DesignTokens)
    entrance: Literal["cut", "rise", "zoom", "flash", "glitch"] = Field(
        default="cut", description="Bounded in-scene entrance over the first 10 frames"
    )
    evidence_ids: list[str] = Field(default_factory=list, max_length=16)
    illustrative: bool = True

    @property
    def asset_ids(self) -> set[str]:
        """Every frozen image this scene displays; each must be permitted evidence."""
        c = self.content
        ids: set[str | None] = {getattr(c, "asset_id", None)}
        if isinstance(c, HubScene):
            ids |= {c.center_asset_id} | {x.asset_id for x in c.spokes}
        if isinstance(c, MultiViewScene):
            ids |= {t.asset_id for t in c.tiles}
        return {i for i in ids if i}

    @property
    def element_ids(self) -> set[str]:
        """Stable targets exposed by the selected template."""
        ids = {"title", "body", "result"}
        if isinstance(self.content, FlowScene):
            ids |= {n.id for n in self.content.nodes} | {e.id for e in self.content.edges}
        if isinstance(self.content, WalkthroughScene):
            ids |= {n.id for n in self.content.steps}
        if isinstance(self.content, ProofScene):
            ids |= {a.id for a in self.content.annotations}
        if isinstance(self.content, BeforeAfterScene):
            ids |= {"before", "after"}
        if isinstance(self.content, CounterScene):
            ids |= {"value", "grid"}
        if isinstance(self.content, BarChartScene):
            ids |= {b.id for b in self.content.bars}
        if isinstance(self.content, HubScene):
            ids |= {"hub"} | {x.id for x in self.content.spokes}
        if isinstance(self.content, MultiViewScene):
            ids |= {t.id for t in self.content.tiles}
        if isinstance(self.content, ChecklistScene):
            ids |= {i.id for i in self.content.items}
        return ids

    @model_validator(mode="after")
    def known_targets(self) -> "SceneSpec":
        if any(e.target not in self.element_ids for e in self.events):
            raise ValueError("event target must name an element in this scene")
        if not self.illustrative and not self.evidence_ids:
            raise ValueError("observed scenes require evidence references")
        return self


class ScenePlacement(StrictModel):
    """Half-open output interval, derived from real source words."""

    scene_id: str = Field(pattern=ID)
    start_word: str = Field(pattern=r"^w\d+$")
    end_word: str = Field(pattern=r"^w\d+$")
    end_boundary: Literal["start", "end"] = "end"
    slot: Literal["full", "panel"] = "full"
    layer: Literal[10, 20] = 10


class SceneArtifact(StrictModel):
    """Verified encoded scene and complete cache identity."""

    key: str
    scene_id: str = ""
    spec_hash: str = Field(pattern=SHA)
    output_hash: str = Field(pattern=SHA)
    width: int
    height: int
    fps: Literal[30] = 30
    frame_count: int = Field(gt=0)
    runtime: str
    render_ms: int = Field(ge=0)
    cache_hit: bool = False
