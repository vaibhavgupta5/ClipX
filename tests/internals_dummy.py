"""Small original word fixture shared by end-to-end visual tests."""


def words() -> list[dict[str, object]]:
    return [
        {
            "id": f"w{i + 1}",
            "text": text,
            "display_text": text,
            "start": i * 0.5,
            "end": i * 0.5 + 0.4,
            "lang": "en",
        }
        for i, text in enumerate(["Inspect", "the", "source", "then", "verify", "output"])
    ]
