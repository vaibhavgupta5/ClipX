"""Content-addressed generated images, with license provenance and atomic manifests."""

import fcntl
import hashlib
import io
import json
import math
import os
import uuid
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.providers.local import LibraryItem, resolve_asset_file
from app.render.fonts import font_for
from app.showcase.models import AnnotateIn, InfographicIn

REVISION = "showcase-3"


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_for("latin_bold")[1], size)


def _text(
    draw: ImageDraw.ImageDraw, text: str, box: tuple[int, int, int, int], size: int, color: str
) -> None:
    """Wrap and fit even an unbroken URL; never spill outside a fixed card."""
    x, y, width, height = box
    for candidate in range(size, 15, -2):
        font = _font(candidate)
        lines: list[str] = []
        current = ""
        words = text.split()
        if any(draw.textlength(word, font=font) > width for word in words):
            continue
        for word in words:
            proposed = f"{current} {word}".strip()
            if current and draw.textlength(proposed, font=font) > width:
                lines.append(current)
                current = word
            else:
                current = proposed
        if current:
            lines.append(current.rstrip())
        step = int(candidate * 1.3)
        if len(lines) * step <= height:
            for index, line in enumerate(lines):
                draw.text((x, y + index * step), line, font=font, fill=color)
            return
    raise ValueError("text cannot fit in the image; shorten it")


def infographic(params: InfographicIn) -> Image.Image:
    """Render compact editorial cards; content determines code/step/metric hierarchy."""
    if params.variant == "flow":
        return _flow_diagram(params)
    palettes = {
        "dark": ("#10171C", "#F4F3ED", "#99EFCC", "#1A252C", "#93A3AA"),
        "paper": ("#F1EDE3", "#1B282B", "#C9502E", "#E6E0D3", "#697272"),
        "electric": ("#141321", "#F6F3EE", "#C4ADFF", "#232136", "#AAA4BA"),
    }
    bg, fg, accent, panel, muted = palettes[params.style]
    count = len(params.stats)
    height = 900 + (count - 1) * 180
    image = Image.new("RGB", (1080, height), bg)
    draw = ImageDraw.Draw(image)
    # Quiet construction grid and inset rule make a deliberate composition, rather
    # than a large empty rectangle. All factual content still comes from the inputs.
    for x in range(48, 1080, 64):
        for y in range(40, height, 64):
            draw.ellipse((x, y, x + 1, y + 1), fill=panel)
    draw.line((56, 48, 1024, 48), fill=muted, width=1)
    draw.rounded_rectangle((56, 82, 70, 102), 5, fill=accent)
    _text(draw, "THE BREAKDOWN", (88, 78, 700, 46), 25, muted)
    _text(draw, f"{count:02d}", (940, 74, 84, 54), 32, accent)
    _text(draw, params.title, (56, 154, 968, 194), 78, fg)
    variant = params.variant
    if variant == "auto":
        has_code = any(
            any(ch in stat.value for ch in "().[]=") or stat.value in ("nil", "true", "false")
            for stat in params.stats
        )
        variant = "code" if has_code else "steps" if count > 1 else "metrics"
    top, bottom = 370, height - 136
    slot = (bottom - top) // count
    for index, stat in enumerate(params.stats):
        y = top + index * slot
        if variant == "code":
            code_height = min(180, slot - 92)
            draw.rounded_rectangle((56, y, 1024, y + code_height), 18, fill=panel)
            draw.line((110, y + 50, 110, y + code_height - 28), fill=muted, width=2)
            _text(draw, f"{index + 1:02d}", (72, y + 22, 62, 40), 22, muted)
            _text(draw, stat.value, (148, y + 42, 836, code_height - 44), 86, accent)
            _text(
                draw, stat.label, (64, y + code_height + 20, 948, slot - code_height - 26), 50, fg
            )
        elif variant == "steps":
            draw.ellipse((56, y + 8, 112, y + 64), fill=accent)
            _text(draw, str(index + 1), (73, y + 14, 36, 46), 30, bg)
            if index < count - 1:
                draw.line((84, y + 74, 84, y + slot - 12), fill=muted, width=2)
            _text(draw, stat.value, (148, y, 850, 86), 62, accent)
            _text(draw, stat.label, (148, y + 88, 850, slot - 102), 44, fg)
        else:
            _text(draw, stat.value, (56, y, 968, int(slot * 0.56)), 132, accent)
            _text(draw, stat.label, (64, y + int(slot * 0.60), 948, int(slot * 0.38)), 46, fg)
    draw.line((56, height - 102, 1024, height - 102), fill=muted, width=1)
    if params.source_label:
        _text(draw, params.source_label, (56, height - 78, 968, 66), 24, muted)
    return image


def _flow_diagram(params: InfographicIn) -> Image.Image:
    """A project-UI style diagram; connections and labels are illustrative, never a fake run."""
    count = len(params.stats)
    height = 660 + count * 200
    image = Image.new("RGB", (1080, height), "#0D1117")
    draw = ImageDraw.Draw(image)
    for x in range(36, 1080, 40):
        for y in range(36, height, 40):
            draw.ellipse((x, y, x + 1, y + 1), fill="#233039")
    draw.rounded_rectangle((24, 24, 1056, height - 24), 28, outline="#303940", width=2)
    draw.line((24, 112, 1056, 112), fill="#303940", width=2)
    for index, color in enumerate(("#E46B73", "#DAB56E", "#75C4A5")):
        x = 58 + index * 30
        draw.ellipse((x, 60, x + 12, 72), fill=color)
    _text(draw, "MODULE CACHE", (180, 49, 700, 48), 28, "#A6B1BA")
    _text(draw, params.title, (78, 164, 924, 160), 62, "#F0F3F5")
    top, step, node_h = 350, 218, 144
    for index, stat in enumerate(params.stats):
        y = top + index * step
        if index < count - 1:
            draw.line((540, y + node_h, 540, y + step), fill="#5E9E8C", width=3)
            draw.polygon(
                [(532, y + step - 15), (548, y + step - 15), (540, y + step - 5)], fill="#99EFCC"
            )
        draw.rounded_rectangle(
            (100, y, 980, y + node_h), 20, fill="#111B23", outline="#345447", width=2
        )
        draw.ellipse((129, y + 36, 151, y + 58), outline="#99EFCC", width=3)
        draw.ellipse((135, y + 42, 145, y + 52), fill="#99EFCC")
        _text(draw, stat.value, (182, y + 20, 748, 66), 48, "#D3F5E6")
        _text(draw, stat.label, (182, y + 89, 748, 52), 32, "#A8B6BF")
    if params.source_label:
        draw.line((78, height - 138, 1002, height - 138), fill="#303940", width=1)
        _text(draw, params.source_label, (78, height - 107, 924, 74), 26, "#A6B1BA")
    return image


def annotate(source: Path, params: AnnotateIn) -> Image.Image:
    """Draw bounded normalized annotations, then add reviewed browser/shadow chrome."""
    with Image.open(source) as opened:
        if opened.width * opened.height > 24_000_000:
            raise ValueError("image exceeds 24 megapixels")
        image = ImageOps.exif_transpose(opened).convert("RGB")
    image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    w, h = image.size
    if min(w, h) < 160:
        raise ValueError("image is too small for readable annotations (minimum side: 160px)")
    draw = ImageDraw.Draw(image)
    for mark in params.annotations:
        x, y = round(mark.x * (w - 1)), round(mark.y * (h - 1))
        x2, y2 = round(mark.x2 * (w - 1)), round(mark.y2 * (h - 1))
        stroke = max(4, w // 180)
        if mark.type == "box":
            draw.rounded_rectangle(
                (min(x, x2), min(y, y2), max(x, x2), max(y, y2)),
                radius=8,
                outline=mark.color,
                width=stroke,
            )
        elif mark.type == "arrow":
            draw.line((x, y, x2, y2), fill=mark.color, width=stroke)
            angle = math.atan2(y2 - y, x2 - x)
            points = [(x2, y2)] + [
                (x2 - 24 * math.cos(angle + a), y2 - 24 * math.sin(angle + a)) for a in (-0.5, 0.5)
            ]
            draw.polygon(points, fill=mark.color)
        if mark.text:
            label_w = min(w - 24, max(180, w // 2))
            left, top = min(x, w - label_w - 12), min(y, max(0, h - 96))
            draw.rounded_rectangle((left, top, left + label_w, top + 90), 10, fill="#111827")
            _text(draw, mark.text, (left + 12, top + 8, label_w - 24, 72), 30, mark.color)
    if params.frame == "none":
        return image
    margin, chrome = 40, 64 if params.frame == "browser" else 0
    framed = Image.new("RGB", (w + margin * 2, h + margin * 2 + chrome), "#111827")
    frame_draw = ImageDraw.Draw(framed)
    frame_draw.rounded_rectangle((32, 32, w + 48, h + chrome + 48), 18, fill="#070B14")
    framed.paste(image, (margin, margin + chrome))
    if chrome:
        frame_draw.rectangle((40, 40, w + 40, 103), fill="#263247")
        for index, color in enumerate(("#FF6058", "#FFBD2E", "#28C840")):
            frame_draw.ellipse((60 + index * 28, 62, 76 + index * 28, 78), fill=color)
    return framed


class GeneratedImageStore:
    """Store PNGs and manifests using the same catalog contract as generated audio."""

    def __init__(self, root: Path, meme_dir: Path) -> None:
        self.root, self.meme_dir = root, meme_dir
        self.dir = root / "showcase"

    def _read(self) -> list[LibraryItem]:
        path = self.dir / "manifest.json"
        return (
            [LibraryItem.model_validate(i) for i in json.loads(path.read_text())]
            if path.exists()
            else []
        )

    def get(self, asset_id: str) -> LibraryItem | None:
        return next(
            (i for i in self._read() if i.id == asset_id and (self.dir / i.file).is_file()), None
        )

    def create(
        self,
        data: dict[str, object],
        title: str,
        draw: Callable[[], Image.Image],
        source: LibraryItem | None = None,
        source_url: str | None = None,
    ) -> LibraryItem:
        """Cache by render inputs; annotation inherits every source license restriction."""
        digest = hashlib.sha256(json.dumps([REVISION, data], sort_keys=True).encode()).hexdigest()[
            :16
        ]
        asset_id = f"showcase:{digest}"
        if hit := self.get(asset_id):
            return hit
        image = draw()
        item = LibraryItem(
            id=asset_id,
            file=f"{digest}.png",
            title=title[:120],
            tags=["showcase", "image"],
            source="generated",
            source_url=source.source_url if source else source_url,
            license=source.license
            if source
            else ("website-screenshot-unverified" if source_url else "user-content"),
            license_url=source.license_url if source else None,
            attribution_required=source.attribution_required if source else False,
            attribution_text=source.attribution_text if source else "",
            commercial_use=source.commercial_use if source else source_url is None,
            width=image.width,
            height=image.height,
        )
        self.dir.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        temp = self.dir / f".{digest}.{token}.png"
        image.save(temp, "PNG")
        os.replace(temp, self.dir / item.file)
        with open(self.dir / ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            items = [i for i in self._read() if i.id != asset_id] + [item]
            manifest = self.dir / f".manifest.{token}.tmp"
            manifest.write_text(json.dumps([i.model_dump() for i in items], indent=2))
            os.replace(manifest, self.dir / "manifest.json")
        return item

    def infographic(self, params: InfographicIn) -> LibraryItem:
        """Generate a stats card (placement is excluded from the image cache)."""
        data = params.model_dump(exclude={"at_word", "duration_ms", "layout", "motion", "entrance"})
        return self.create(
            {"kind": "infographic", **data}, params.title, lambda: infographic(params)
        )

    def annotate(self, params: AnnotateIn) -> LibraryItem:
        """Resolve only licensed catalog files, and hash both pixels and source metadata."""
        path = resolve_asset_file(self.root, self.meme_dir, params.asset_id)
        if path is None:
            raise ValueError("source asset not found; use a catalog image asset ID")
        from app.providers.local import AssetCatalog

        found = AssetCatalog(self.root, self.meme_dir).get(params.asset_id)
        if found is None or found[0] not in ("image", "icon", "showcase"):
            raise ValueError("source must be an image, icon or generated showcase image")
        source = found[1]
        data = params.model_dump(exclude={"at_word", "duration_ms", "layout", "motion", "entrance"})
        data["source_hash"] = hashlib.sha256(path.read_bytes()).hexdigest()
        data["license_metadata"] = source.model_dump()
        return self.create(
            {"kind": "annotation", **data}, source.title, lambda: annotate(path, params), source
        )

    def capture(self, data: dict[str, object], png: bytes, url: str) -> LibraryItem:
        """Record a screenshot as personal-use content with its original URL."""
        return self.create(
            {"kind": "capture", "pixels": hashlib.sha256(png).hexdigest(), **data},
            url,
            lambda: Image.open(io.BytesIO(png)).convert("RGB"),
            source_url=url,
        )
