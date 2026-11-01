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
