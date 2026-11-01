from pathlib import Path

from app.explainer.lookup import lookup
from tests.unit.explainer.helpers import catalog


def test_widens_until_something_fits(tmp_path: Path) -> None:
    cat = catalog(tmp_path)
    exact = lookup(cat, "video", "chip")
    assert exact is not None and exact[1] == "exact"
    token = lookup(cat, "video", "a glowing chip on a board")  # strict match needs every token
    assert token is not None and token[1] == "token" and token[0].id == exact[0].id
    assert lookup(cat, "video", "") is None
    assert lookup(cat, "video", "zzzz qqqq") is None


def test_uncaptured_source_becomes_an_honest_text_card() -> None:
    from app.explainer.models import Card
    from app.explainer.sources import text_for_uncaptured

    c = Card(
        id="a",
        start_word="w1",
        end_word="w2",
        family="proof_focus",
        title="Dots always on",
        source_url="https://www.openai.com/index/dots/",
        highlight="x",
    )
    ok = c.model_copy(update={"id": "b"})
    warnings: list[str] = []
    out = text_for_uncaptured([c, ok], {"b": "ev1"}, warnings)
    assert out[0].family == "impact_title" and out[0].kicker == "OPENAI.COM"
    assert out[0].headline == "Dots always on" and out[1].family == "proof_focus"
    assert "text card" in warnings[0]
