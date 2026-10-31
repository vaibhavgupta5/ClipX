"""One 30 FPS source-word to output-frame map; cuts invalidate editorial meaning."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.storyboard.store import content_hash

if TYPE_CHECKING:
    from app.timeline.schema import Timeline


class StalePlanError(ValueError):
    """A word or retained clip changed: re-plan against the current transcript."""


def timing_hash(timeline: "Timeline") -> str:
    """Identity of narration and retained order, independent of visual edits."""
    return content_hash(
        {
            "transcript": timeline.transcript.model_dump(mode="json"),
            # Timing fields only: cut effects and framing are visual and must not stale a plan.
            "clips": [
                c.model_dump(mode="json", include={"id", "asset", "src_in", "src_out", "speed"})
                for c in timeline.video_clips
            ],
        }
    )


@dataclass(frozen=True)
class TimingMap:
    """Half-open frame ranges for fully retained words."""

    words: dict[str, tuple[int, int]]
    frame_count: int
    clips: tuple[tuple[int, int], ...] = ()  # half-open output frame range of each clip

    @classmethod
    def from_timeline(cls, timeline: "Timeline") -> "TimingMap":
        if timeline.output.fps != 30:
            raise ValueError("visual scenes currently support exactly 30 FPS")
        words: dict[str, tuple[int, int]] = {}
        clips: list[tuple[int, int]] = []
        offset = 0.0
        for clip in timeline.video_clips:
            for word in timeline.transcript.words:
                if word.start >= clip.src_in - 1e-6 and word.end <= clip.src_out + 1e-6:
                    if word.id in words:
                        raise ValueError(f"ambiguous repeated word {word.id}")
                    start = round((offset + (word.start - clip.src_in) / clip.speed) * 30)
                    end = round((offset + (word.end - clip.src_in) / clip.speed) * 30)
                    words[word.id] = (start, max(start + 1, end))
            clips.append((round(offset * 30), round((offset + clip.output_len) * 30)))
            offset += clip.output_len
        return cls(words, round(offset * 30), tuple(clips))

    def absorb_padding(self, a: int, b: int) -> tuple[int, int]:
        """Extend a scene over its clip's silent head/tail padding.

        Clips keep ~0.1 s of air around their first and last words. A scene that starts on
        a clip's first word (or ends on its last) would otherwise leave a 2-4 frame flash of
        raw footage between two graphics. Edges only move when no retained word lies
        between the scene and the clip edge, so no spoken word changes owner.
        """
        for lo, hi in self.clips:
            if lo <= a < hi and not any(lo <= s < a for s, _ in self.words.values()):
                a = lo
            if lo < b <= hi and not any(b <= s < hi for s, _ in self.words.values()):
                b = hi
        return a, b

    def interval(self, start_word: str, end_word: str) -> tuple[int, int]:
        """Resolve only complete words. Never silently move a missing cue."""
        try:
            a, b = self.words[start_word][0], self.words[end_word][1]
        except KeyError as exc:
            raise StalePlanError(
                f"word {exc.args[0]} was removed or split; re-plan or replace its anchor"
            ) from None
        if b <= a:
            raise StalePlanError("anchors reversed in edited output; re-plan this scene")
        return a, b
