"""Render an extracted editable showcase bundle locally; never upload media."""

import argparse
import asyncio
import hashlib
import json
import tempfile
from pathlib import Path

from app.render.quality import inspect_export
from app.render.render import profile_for, render_timeline
from app.storage import LocalStorage
from app.timeline.schema import Timeline


def safe_file(root: Path, relative: str) -> Path:
    """Portable manifests may refer only to files within their extracted bundle."""
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"missing or unsafe bundle file: {relative}")
    return path


async def main() -> None:
    """Validate dependencies and render typed, editable scene parameters."""
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--out", type=Path, default=Path("work/replayed-showcase"))
    parser.add_argument("--profile", choices=["preview", "final"], default="preview")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.bundle.resolve()
    mapping = json.loads((root / "portable-map.json").read_text())
    hashes = json.loads((root / "checksums.json").read_text())
    timeline = Timeline.model_validate_json((root / "timeline.json").read_text())
    dependencies = [
        mapping["source_asset"],
        *mapping["evidence"].values(),
        *mapping["assets"].values(),
    ]
    for relative in dependencies:
        path = safe_file(root, relative)
        if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[relative]:
            raise ValueError(f"media/provenance checksum mismatch: {relative}")
    if args.check:
        print(
            json.dumps({"dependencies_verified": len(dependencies), "scenes": len(timeline.scenes)})
        )
        return
    store = LocalStorage(
        str(args.out / "upload"), str(args.out / "work"), str(args.out / "exports")
    )
    store.ensure_dirs()
    for key, relative in mapping["evidence"].items():
        store.put_bytes(key, safe_file(root, relative).read_bytes(), "application/octet-stream")
    files = {key: str(safe_file(root, relative)) for key, relative in mapping["assets"].items()}
    with tempfile.TemporaryDirectory(prefix="clipz-bundle-") as work:
        profile = profile_for(args.profile)
        result = await render_timeline(
            timeline,
            str(safe_file(root, mapping["source_asset"])),
            files,
            profile,
            store,
            work,
            lambda _: None,
        )
    path = store.path_for(str(result["key"]))
    quality = await asyncio.to_thread(
        inspect_export, path, timeline.duration_s, profile.width, profile.height
    )
    print(
        json.dumps(
            {"output": str(path), "technical": quality, "creative_status": "not_evaluated"},
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
