"""Analysis LLM stages accept fenced JSON (a real Gemini habit) and still reject prose."""

import json

import pytest

from app.analysis.llm_stages import strip_code_fence


def test_fenced_json_is_unwrapped() -> None:
    assert json.loads(strip_code_fence('```json\n{"beats": []}\n```')) == {"beats": []}
    assert json.loads(strip_code_fence('  {"beats": [1]}  ')) == {"beats": [1]}


def test_prose_is_still_rejected() -> None:
    with pytest.raises(json.JSONDecodeError):
        json.loads(strip_code_fence("Here are the beats you asked for"))
