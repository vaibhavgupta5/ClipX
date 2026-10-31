"""Typed filtergraph builder: nodes compile to one deterministic -filter_complex script.

Only typed fields enter the script. Free text NEVER enters here — captions go
through escaped ASS files (captions_ass.py), never through filter arguments.
"""

from dataclasses import dataclass, field
from typing import Protocol

from app.render.framing import Focus, crop_xy


def _s(seconds: float) -> str:
    """Millisecond-precise timestamp."""
    return f"{seconds:.3f}"


@dataclass(frozen=True)
class Trim:
    """Cut + timestamp reset."""

    input: str
    start: float
    end: float

    def render(self, out: str) -> str:
        return (
            f"{self.input}trim=start={_s(self.start)}:end={_s(self.end)},setpts=PTS-STARTPTS{out}"
        )


@dataclass(frozen=True)
class SetPts:
    """Speed: factor multiplies presentation timestamps (video)."""

    input: str
    factor: float

    def render(self, out: str) -> str:
        return f"{self.input}setpts={self.factor}*PTS{out}"


@dataclass(frozen=True)
class ShiftPts:
    """Start an overlay input at ``at`` seconds and keep its alpha channel."""

    input: str
    at: float

    def render(self, out: str) -> str:
        return f"{self.input}setpts=PTS-STARTPTS+{_s(self.at)}/TB,format=rgba{out}"


@dataclass(frozen=True)
class Concat:
    """Concatenate segments (identical params required)."""

    inputs: tuple[str, ...]
    n: int

    def render(self, out: str) -> str:
        return f"{''.join(self.inputs)}concat=n={self.n}:v=1:a=0{out}"


@dataclass(frozen=True)
class OverlayAt:
    """Overlay with enable window in seconds. x/y accept expressions."""

    main: str
    over: str
    x: int | str
    y: int | str
    start: float
    end: float

    def render(self, out: str) -> str:
        return (
            f"{self.main}{self.over}overlay={self.x}:{self.y}:"
            f"enable='between(t,{_s(self.start)},{_s(self.end)})'{out}"
        )


@dataclass(frozen=True)
class Scale:
    """Scale (w/h accept -2 for aspect)."""

    input: str
    w: int | str
    h: int | str

    def render(self, out: str) -> str:
        return f"{self.input}scale={self.w}:{self.h}{out}"


@dataclass(frozen=True)
class Contain:
    """Fit screen recordings/cards over black without cropping text or UI."""

    input: str
    width: int
    height: int

    def render(self, out: str) -> str:
        w, h = self.width, self.height
        return (
            f"{self.input}scale={w}:{h}:force_original_aspect_ratio=decrease:"
            f"force_divisible_by=2,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1{out}"
        )


@dataclass(frozen=True)
class FrameCount:
    """Quantize each segment to its global frame interval, avoiding cumulative drift."""

    input: str
    frames: int
    fps: int = 30

    def render(self, out: str) -> str:
        if not 1 <= self.frames <= 5400 or self.fps not in (24, 25, 30, 50, 60):
            raise ValueError("invalid frame target")
        return (
            f"{self.input}fps={self.fps},tpad=stop_mode=clone:stop_duration=1,"
            f"trim=end_frame={self.frames},setpts=N/({self.fps}*TB){out}"
        )


@dataclass(frozen=True)
class ProofFrame:
    """Reference-style page shot: black canvas, protected subtitle area and a camera move."""

    input: str
    width: int
    height: int
    duration: float
    elapsed: float = 0
    motion: str = "pull_out"
    entrance: str = "slide_up"

    def render(self, out: str) -> str:
        w, h = self.width, self.height
        stem = out.strip("[]")
        panel = f"[{stem}_panel]"
        black = f"[{stem}_black]"
        fit = f"[{stem}_fit]"
        p = f"clip((t+{_s(self.elapsed)})/{_s(max(0.3, self.duration))}\\,0\\,1)"
        ease = f"({p})*({p})*(3-2*({p}))"
        zoom = "1"
        if self.motion == "pull_out":
            zoom = f"(1+0.035*(1-({ease})))"
        elif self.motion == "push_in":
            zoom = f"(1+0.025*({ease}))"
        top = f"{h * 0.075:.3f}"
        if self.motion in ("pan_up", "pan_down"):
            sign = "-" if self.motion == "pan_up" else "+"
            top += f"{sign}{h * 0.035:.3f}*({ease})"
        if self.entrance == "slide_up":
            enter = f"clip((t+{_s(self.elapsed)})/0.32\\,0\\,1)"
            top += f"+{h * 0.055:.3f}*(1-({enter}))*(1-({enter}))*(1-({enter}))"
        return (
            f"{self.input}scale={int(w * 0.90) // 2 * 2}:{int(h * 0.62) // 2 * 2}:"
            f"force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1{fit};"
            f"{fit}scale=iw*{zoom}:ih*{zoom}:eval=frame{panel};"
            f"color=c=black:s={w}x{h}:r=30{black};"
            f"{black}{panel}overlay=x=(W-w)/2:y='{top}':shortest=1{out}"
        )


@dataclass(frozen=True)
class ReframeBlur:
    """Full-frame reframe: blurred fill background + contained foreground."""

    input: str
    width: int
    height: int

    def render(self, out: str) -> str:
        w, h = self.width, self.height
        return (
            f"{self.input}split[rb][rf];"
            f"[rb]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=20[lbg];"
            f"[rf]scale={w}:{h}:force_original_aspect_ratio=decrease[lfg];"
            f"[lbg][lfg]overlay=(W-w)/2:(H-h)/2{out}"
        )


@dataclass(frozen=True)
class ReframeSplitBottom:
    """Split view: solid sleek dark top canvas + speaker video constrained to the bottom half.

    ``focus`` (face centre, normalized source coords) steers the bottom crop so a portrait
    source keeps the speaker's head in the panel; None crops the centre.
    """

    input: str
    width: int
    height: int
    focus: Focus | None = None
    speaker_zoom: float = 1.0

    def render(self, out: str) -> str:
        w, h = self.width, self.height
        half_h = h // 2
        scaled_w = int(w * self.speaker_zoom) // 2 * 2
        scaled_h = int(half_h * self.speaker_zoom) // 2 * 2
        crop = f"crop={w}:{half_h}"
        if self.focus is not None:
            x, y = crop_xy(self.focus)
            crop += f":x={x}:y={y}"
        return (
            f"{self.input}split[rsb_bg][rsb_fg];"
            f"[rsb_bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=40,"
            f"drawbox=x=0:y=0:w={w}:h={half_h}:color=0x0d0e15@1.0:t=fill[sbg];"
            f"[rsb_fg]scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase,{crop},"
            f"eq=contrast=1.12:brightness=0.01:saturation=1.18,unsharp=5:5:0.8:5:5:0.4[sfg];"
            f"[sbg][sfg]overlay=0:{half_h}{out}"
        )


@dataclass(frozen=True)
class BlurBg:
    """Contain an image over its own blurred fullscreen copy."""

    over: str
    width: int
    height: int

    def render(self, out: str) -> str:
        w, h = self.width, self.height
        return (
            f"{self.over}split[bg_in][fg_in];"
            f"[bg_in]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},boxblur=20[bg];"
            f"[bg][fg_in]overlay=(W-w)/2:(H-h)/2{out}"
        )


@dataclass(frozen=True)
class ScaleCrop:
    """Scale to fill then crop: the centre, or around ``focus`` (face framing)."""

    input: str
    width: int
    height: int
    focus: Focus | None = None

    def render(self, out: str) -> str:
        crop = f"crop={self.width}:{self.height}"
        if self.focus is not None:
            x, y = crop_xy(self.focus)
            crop += f":x={x}:y={y}"
        return (
            f"{self.input}scale={self.width}:{self.height}:"
            f"force_original_aspect_ratio=increase,{crop}{out}"
        )


@dataclass(frozen=True)
class FadeIO:
    """Fade in/out in seconds (overlay polish)."""

    input: str
    fade_in: float
    fade_out: float
    duration: float
    start: float = 0.0  # stream time the overlay appears (after ShiftPts)

    def render(self, out: str) -> str:
        # A segment boundary can leave a sliver shorter than the fades; scale them to fit
        # so FFmpeg never receives a negative start time.
        start = max(0.0, self.start)
        duration = max(0.0, self.duration)
        scale = min(1.0, duration / (self.fade_in + self.fade_out)) if duration else 0.0
        fade_in, fade_out = self.fade_in * scale, self.fade_out * scale
        end = start + duration - fade_out
        return (
            f"{self.input}fade=t=in:st={_s(start)}:d={_s(fade_in)}:alpha=1,"
            f"fade=t=out:st={_s(end)}:d={_s(fade_out)}:alpha=1{out}"
        )


@dataclass(frozen=True)
class ZoomPunch:
    """Punch-in envelope: ease in over `dur_s`, hold `hold_s`, ease out over `out_s`.

    Smoothstep easing (e*e*(3-2e)) on an animated scale + STATIC center crop (the
    target size is constant, so a fixed crop is exact). hold_s=0 keeps the old
    "zoom and stay" behaviour for the rest of the clip.
    """

    input: str
    at: float
    dur_s: float
    scale: float
    width: int
    height: int
    hold_s: float = 0.0
    out_s: float = 0.25
    anchor: tuple[float, float] = (0.5, 0.5)  # normalized point that stays fixed (the face)

    def render(self, out: str) -> str:
        if self.scale <= 1.001:
            return f"{self.input}null{out}"
        t0, d, s = _s(self.at), _s(self.dur_s), self.scale
        rise = f"clip((t-{t0})/{d}\\,0\\,1)"
        if self.hold_s > 0:
            t1 = _s(self.at + self.dur_s + self.hold_s)
            fall = f"clip(({t1}+{_s(self.out_s)}-t)/{_s(self.out_s)}\\,0\\,1)"
            env = f"min({rise}\\,{fall})"
        else:
            env = rise
        ease = f"({env})*({env})*(3-2*({env}))"
        z = f"(1+({s}-1)*{ease})"
        return (
            f"{self.input}scale=iw*{z}:ih*{z}:eval=frame,"
            f"crop={self.width}:{self.height}:{_anchor_xy(self.anchor)}{out}"
        )


def _anchor_xy(anchor: tuple[float, float]) -> str:
    """Crop offsets that keep a normalized point fixed on screen while the frame scales."""
    ax, ay = (min(1.0, max(0.0, v)) for v in anchor)
    return f"x=(iw-ow)*{ax:.3f}:y=(ih-oh)*{ay:.3f}"


@dataclass(frozen=True)
class Drift:
    """Slow camera breathing on raw footage, driven by SOURCE time so it never restarts
    at render-slice boundaries: scale = 1 + amount * (1 - cos(2*pi*src_t / period)) / 2."""

    input: str
    amount: float
    src_offset: float
    width: int
    height: int
    anchor: tuple[float, float] = (0.5, 0.42)
    period_s: float = 9.0

    def render(self, out: str) -> str:
        if self.amount <= 0.001:
            return f"{self.input}null{out}"
        phase = f"2*PI*(t+{_s(self.src_offset)})/{self.period_s:.2f}"
        z = f"(1+{self.amount:.4f}*(1-cos({phase}))/2)"
        return (
            f"{self.input}scale=iw*{z}:ih*{z}:eval=frame,"
            f"crop={self.width}:{self.height}:{_anchor_xy(self.anchor)}{out}"
        )


@dataclass(frozen=True)
class StaticZoom:
    """Hold a tighter framing for a whole clip, anchored on the face (jump-cut cover)."""

    input: str
    scale: float
    width: int
    height: int
    anchor: tuple[float, float] = (0.5, 0.42)

    def render(self, out: str) -> str:
        if self.scale <= 1.001:
            return f"{self.input}null{out}"
        w = int(self.width * self.scale) // 2 * 2
        h = int(self.height * self.scale) // 2 * 2
        return (
            f"{self.input}scale={w}:{h},"
            f"crop={self.width}:{self.height}:{_anchor_xy(self.anchor)}{out}"
        )


@dataclass(frozen=True)
class TransitionIn:
    """Incoming cut effect on a clip that is already width x height (clip-local time).

    zoom_in: starts 20% punched-in on the anchor (the face) and settles to 1.0 over 0.34 s
             with an ease-out cubic, so the move is felt on the cut and then gets out of the way.
    flash:   fades in from white over 0.15 s.
    whip:    slides in horizontally from the right with motion blur over 0.18 s.
    """

    input: str
    style: str
    width: int
    height: int
    anchor: tuple[float, float] = (0.5, 0.5)

    def render(self, out: str) -> str:
        w, h = self.width, self.height
        if self.style == "zoom_in":
            e = "clip(t/0.34\\,0\\,1)"
            z = f"(1+0.20*pow(1-({e})\\,3))"
            return (
                f"{self.input}scale=iw*{z}:ih*{z}:eval=frame,"
                f"crop={w}:{h}:{_anchor_xy(self.anchor)}{out}"
            )
        if self.style == "flash":
            return f"{self.input}fade=t=in:st=0:d=0.15:color=white{out}"
        if self.style == "whip":
            e = "clip(t/0.18\\,0\\,1)"
            x = f"(iw-ow)/2+(iw-ow)/2*(1-({e})*({e})*(3-2*({e})))"
            return (
                f"{self.input}scale={int(w * 1.25) // 2 * 2}:{int(h * 1.25) // 2 * 2},"
                f"crop={w}:{h}:x='{x}':y=(ih-oh)/2,"
                f"boxblur=luma_radius=18:luma_power=1:enable='lt(t\\,0.14)'{out}"
            )
        return f"{self.input}null{out}"


@dataclass(frozen=True)
class AssBurn:
    """Burn an ASS subtitle file (escaped upstream). Path is ours, never external."""

    input: str
    ass_path: str

    def render(self, out: str) -> str:
        safe = self.ass_path.replace("'", "'\\''").replace(":", "\\:")
        return f"{self.input}ass='{safe}'{out}"


@dataclass(frozen=True)
class AudioChain:
    """Denoise (+ optional atempo list) for one audio input."""

    input: str
    atempo: tuple[float, ...] = ()

    def render(self, out: str) -> str:
        chain = "afftdn,aresample=async=1"
        for factor in self.atempo:
            chain += f",atempo={factor}"
        return f"{self.input}{chain}{out}"


class Node(Protocol):
    """A filter node rendering to one labeled chain segment."""

    def render(self, out: str) -> str:
        """Render using input labels baked into the node; emit to `out`."""
        ...


@dataclass
class FilterGraph:
    """Ordered node list compiling to a deterministic script with [vN] labels."""

    inputs: list[str]
    _nodes: list[tuple[Node, str]] = field(default_factory=list)
    _counter: int = 0

    def add(self, node: Node) -> str:
        """Append a node; returns its output label."""
        label = f"[v{self._counter}]"
        self._counter += 1
        self._nodes.append((node, label))
        return label

    def compile(self) -> tuple[str, str]:
        """(filter_script, final_label)."""
        parts: list[str] = []
        last = self.inputs[0] if self.inputs else ""
        for node, label in self._nodes:
            parts.append(node.render(label))
            last = label
        return (";".join(parts), last)
