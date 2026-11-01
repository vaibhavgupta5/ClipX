"""Request coverage: phrases -> tools, negation, transition subtlety."""

from app.agent.coverage import missing, requested
from tests.unit.timeline.test_ops import _timeline

PROMPT = (
    "Make it vertical, cut the dead air, clean the noise, add sad music, captions, "
    "a few images and one meme, smooth transitions, punch-in zooms and subtle sound "
    "effects. Export."
)


def test_requested_items_are_recognised() -> None:
    labels = {r.label for r in requested(PROMPT)}
    assert labels == {
        "images / memes / GIFs", "background music", "captions", "punch-in zooms",
        "cut transitions", "sound effects", "noise reduction", "silence removal",
        "vertical 9:16 framing", "export",
    }  # fmt: skip


def test_negated_mentions_are_not_requests() -> None:
    labels = {r.label for r in requested("add captions but no music and without memes")}
    assert labels == {"captions"}


def test_missing_reports_skipped_items_and_none_transition() -> None:
    applied = {"reframe_9x16", "remove_silence", "denoise", "add_music", "set_caption_style",
               "set_transition", "add_zooms", "auto_sfx", "export"}  # fmt: skip
    tl = _timeline()  # transition defaults to "none"
    assert missing(PROMPT, applied, tl) == ["images / memes / GIFs", "cut transitions"]
    done = tl.model_copy(update={"transition": "flash"})
    assert missing(PROMPT, applied | {"add_inserts"}, done) == []


def test_explicit_checklist_tracks_registered_tools_only() -> None:
    from app.agent.coverage import explicit_tools

    message = "REQUIRED_TOOLS: get_timeline, plan_edit, generate_infographic, not_a_tool\n"
    assert explicit_tools(message) == {"get_timeline", "plan_edit", "generate_infographic"}
    assert missing(message, {"get_timeline"}, _timeline()) == [
        "tool:generate_infographic",
        "tool:plan_edit",
    ]
    assert explicit_tools("Do not use generate_infographic. Example: REQUIRED_TOOLS: trim") == set()


def test_make_explainer_satisfies_transitions_without_a_global_style() -> None:
    tl = _timeline()
    assert "cut transitions" in missing("smooth transitions", set(), tl)
    assert "cut transitions" not in missing("smooth transitions", {"make_explainer"}, tl)
