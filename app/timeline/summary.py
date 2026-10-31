"""Compact deterministic timeline summary for Director LLM context (~15 lines max)."""

from app.timeline.schema import Timeline


def summarize(tl: Timeline) -> str:
    """Render a token-efficient, key-order-stable summary of the timeline."""
    words = tl.transcript.words
    word_span = f"{words[0].id}..{words[-1].id}" if words else "none"
    n_clips = len(tl.video_clips)
    cuts_per_min = (n_clips - 1) / tl.duration_s * 60 if tl.duration_s > 0 else 0.0
    zoom_info = f" speaker_zoom={tl.speaker_zoom:g}" if tl.speaker_zoom != 1 else ""
    lines = [
        f"timeline v{tl.version} | {tl.duration_s:.3f}s | {n_clips} clips | "
        f"{cuts_per_min:.1f} cuts/min | words {word_span} | {len(tl.transcript.beats)} beats",
        f"captions {tl.captions.mode} {tl.captions.position} "
        f"wpl={tl.captions.words_per_line} size={tl.captions.size_px} "
        f"{tl.captions.base_color}/{tl.captions.highlight_color}",
        f"zooms {len(tl.zooms)} | "
        f"overlays {len(tl.overlays)} | music {'yes' if tl.music else 'no'} | "
        f"sfx {len(tl.sfx)} | voiceovers {len(tl.voiceovers)} | "
        f"dub {tl.dub.language if tl.dub else 'none'}",
        f"style {tl.style_id or 'none'} | reframe {tl.reframe}{zoom_info} | "
        f"audio {','.join(e.type for e in tl.audio_fx) or 'loudnorm-default'}",
    ]
    if tl.storyboard is not None:
        lines.append(
            f"storyboard {tl.storyboard_hash} | {len(tl.storyboard.beats)} beats | "
            f"{len(tl.scenes)} editable scenes"
        )
        lines.extend(
            f"scene {p.scene_id} @{p.start_word}..{p.end_word} {p.slot}"
            for p in tl.scene_placements
        )
    if tl.overlays:
        rendered = ", ".join(
            f"{o.id}({o.type}/{o.layout} @{o.anchor_word}+{o.offset_ms}ms {o.duration_ms}ms)"
            for o in tl.overlays
        )
        lines.append(f"overlays: {rendered}")
    if tl.music:
        suffix = " [attribution required]" if tl.music.attribution_required else ""
        lines.append(f"music: {tl.music.asset}{suffix}")
    if tl.voiceovers:
        lines.append(
            "voiceovers: "
            + ", ".join(f"{v.id}(@{v.anchor_word} {v.duration_ms}ms)" for v in tl.voiceovers)
        )
    return "\n".join(lines)
