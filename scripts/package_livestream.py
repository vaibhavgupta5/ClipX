"""Package exact reviewed media, editable scene sources and licensed dependencies."""

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from app.storage import LocalStorage
from app.timeline.schema import Timeline
from app.visuals.evidence import evidence_metadata_key

ROOT = Path("work/livestream-impact")


def main() -> None:
    """Build a self-contained review bundle without secrets or environment settings."""
    timeline = Timeline.model_validate_json((ROOT / "timeline.json").read_text())
    report = json.loads((ROOT / "final-report.json").read_text())
    final = Path(report["artifact"])
    if hashlib.sha256(final.read_bytes()).hexdigest() != report["sha256"]:
        raise ValueError("final artifact differs from its actual reviewed bytes")
    destination = Path("editedVideo/livestream-impact-project")
    destination.mkdir(parents=True, exist_ok=True)
    copies = {
        "timeline.json": ROOT / "timeline.json",
        "timeline-v1.json": ROOT / "timeline-v1.json",
        "review.json": ROOT / "final-report.json",
        "validation-summary.json": ROOT / "validation-summary.json",
        "repair.json": ROOT / "repair.json",
        "credits.txt": ROOT / "credits.txt",
        "source-manifest.json": ROOT / "source-manifest.json",
        "transcript.json": ROOT / "transcript.json",
        "reference-recipe.json": ROOT / "reference-recipe.json",
        "source/master.mp4": ROOT / "master.mp4",
        "final.mp4": final,
        "contact-sheet.jpg": ROOT / "final-contact-sheet.jpg",
    }
    store = LocalStorage("upload", "work", "editedVideo")
    mapping = {"source_asset": "source/master.mp4", "evidence": {}, "assets": {}}
    for asset in timeline.storyboard.evidence:
        relative = "evidence/" + asset.sha256 + ".png"
        copies[relative] = store.path_for(asset.storage_key)
        mapping["evidence"][asset.storage_key] = relative
        metadata_key = evidence_metadata_key(asset)
        metadata_relative = f"evidence/{asset.sha256}.{asset.id}.metadata.json"
        copies[metadata_relative] = store.path_for(metadata_key)
        mapping["evidence"][metadata_key] = metadata_relative
    files = json.loads((ROOT / "asset-files.json").read_text())
    for i, (asset, path) in enumerate(files.items()):
        relative = f"assets/{i:02d}-{Path(path).name}"
        copies[relative] = Path(path)
        mapping["assets"][asset] = relative
    hashes = {}
    for relative, path in copies.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        hashes[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
    (destination / "portable-map.json").write_text(json.dumps(mapping, indent=2))
    (destination / "checksums.json").write_text(json.dumps(hashes, indent=2))
    (destination / "README.txt").write_text(
        "ClipZ Phase 7c editable demonstration\n\n"
        "final.mp4 is the reviewed 1080x1920 output. timeline.json contains editable "
        "storyboard, claims, evidence, word cues and all scene parameters. "
        "timeline-v1.json and repair.json preserve the one-scene revision. "
        "source/master.mp4 is the normalized original 60-second excerpt. "
        "portable-map.json resolves media dependencies without environment settings.\n\n"
        "To validate from the ClipZ repository after installing showcase/video-test "
        "extras, FFmpeg, Chromium and building visuals:\n"
        "  python -m scripts.render_bundle /absolute/path/to/extracted-bundle --check\n"
        "To render editable scene parameters without any provider upload:\n"
        "  python -m scripts.render_bundle /absolute/path/to/extracted-bundle "
        "--out work/replayed-showcase --profile final\n\n"
        "Read credits.txt and source-manifest.json before reuse. Original livestream "
        "and unverified website screenshots retain their source restrictions. "
        "The asset catalog license does not grant rights to the original livestream.\n"
    )
    archive = Path("editedVideo/livestream-impact-project.zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(destination))
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise ValueError("bundle integrity check failed")
        for name, digest in hashes.items():
            if hashlib.sha256(bundle.read(name)).hexdigest() != digest:
                raise ValueError(f"bundle checksum failed: {name}")
    print(
        json.dumps(
            {
                "bundle": str(archive.resolve()),
                "files": len(copies),
                "bytes": archive.stat().st_size,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
