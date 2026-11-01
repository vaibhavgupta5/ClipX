"""Actual DB/API/worker path for editable visual stories and honest render reviews."""

import asyncio
import hashlib
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app import db as db_ops
from app.main import create_app
from app.models import Asset, Job, Render
from app.models import Timeline as TimelineRow
from app.settings import get_settings
from app.storage import get_storage
from app.timeline.versions import get_current, load_version, save_version
from app.workers.hybrid import hybrid_task
from tests.internals_dummy import words

pytestmark = pytest.mark.integration


async def test_storyboard_api_undo_stale_writes_and_ownership() -> None:
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": "hybrid-owner"},
    ) as client:
        created = await client.post(
            "/projects",
            json={
                "name": "Visual draft",
                "transcript": {"words": words()},
                "source_asset": "master",
                "source_duration_s": 3,
            },
        )
        pid = created.json()["project_id"]
        url = f"/projects/{pid}/storyboard"
        body = {
            "expected_version": 1,
            "brief": {
                "audience": "Developers",
                "promise": "Show the steps",
                "takeaway": "Verify output",
            },
            "create_draft_scenes": True,
        }
        planned = await client.post(url, json=body)
        assert planned.status_code == 200, planned.text
        board = (await client.get(url)).json()
        assert board["scenes"] and board["version"] == 2
        assert (await client.post(url, json=body)).status_code == 409
        scene = board["scenes"][0]
        placement = board["placements"][0]
        changed = {**scene, "title": "A clearer focus"}
        update = await client.put(
            f"/projects/{pid}/scenes/{scene['id']}",
            json={"expected_version": 2, "spec": changed, "placement": placement},
        )
        assert update.status_code == 200, update.text
        await client.post(f"/projects/{pid}/undo")
        undone = (await client.get(url)).json()
        assert undone["scenes"][0]["title"] == scene["title"]
        await client.post(f"/projects/{pid}/redo")
        assert (await client.get(url)).json()["scenes"][0]["title"] == "A clearer focus"
        blocked = await client.get(url, headers={"X-API-Key": "stranger"})
        assert blocked.status_code == 404
        html = await client.get(f"/projects/{pid}/scenes/{scene['id']}/preview")
        assert html.status_code == 200 and "connect-src" in html.headers["content-security-policy"]


async def test_two_expected_revision_commits_cannot_overwrite_each_other() -> None:
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": "race-owner"},
    ) as client:
        created = await client.post(
            "/projects",
            json={
                "transcript": {"words": words()},
                "source_asset": "master",
                "source_duration_s": 3,
            },
        )
        pid = uuid.UUID(created.json()["project_id"])
        db = db_ops.get_db(get_settings())
        row = await db_ops.find_one(db, TimelineRow, {"project_id": pid})
        tl = await load_version(db, row.id, 1)

        async def save():
            try:
                return await save_version(db, row.id, tl, parent=1, expected_parent=1)
            except ValueError:
                return "stale"

        results = await asyncio.gather(save(), save())
        assert sum(r == "stale" for r in results) == 1
        assert await get_current(db, row.id) == 2


async def test_durable_explainer_worker_real_scene_and_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()
    settings = get_settings()
    db = db_ops.get_db(settings)
    store = get_storage(settings)
    app = create_app(settings)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": "worker-owner"},
    ) as client:
        created = await client.post(
            "/projects",
            json={
                "name": "Worker dummy",
                "transcript": {"words": words()},
                "source_asset": "master",
                "source_duration_s": 3,
            },
        )
        pid = uuid.UUID(created.json()["project_id"])
        source = await asyncio.to_thread(Path("fixtures/synth/bars_5s.mp4").read_bytes)
        key = f"projects/{pid}/master.mp4"
        store.put_bytes(key, source, "video/mp4")
        await db_ops.insert(
            db,
            Asset(
                project_id=pid,
                kind="master",
                storage_key=key,
                sha256=hashlib.sha256(source).hexdigest(),
                source="test-fixture",
                license="CC0",
            ),
        )
        # Queue delivery is tested by Arq separately; this invokes its actual registered worker.
        rid = uuid.uuid4()
        job = await db_ops.insert(
            db,
            Job(
                project_id=pid,
                type="visual_explainer",
                idempotency_key=f"explainer:{rid}",
                payload={
                    "expected_version": 1,
                    "render_id": str(rid),
                    "brief": {
                        "audience": "Devs",
                        "promise": "Show the steps",
                        "takeaway": "Verify the output",
                    },
                },
            ),
        )
        result = await hybrid_task({"settings": settings}, job_id=str(job.id))
        assert result["status"] == "done", result
        render = await db_ops.get(db, Render, rid)
        assert render.output_key and render.quality["technical_pass"]
        assert render.quality["creative_status"] == "not_evaluated"
        assert (
            render.quality["render_hash"]
            == hashlib.sha256(store.get_bytes(render.output_key)).hexdigest()
        )
        done = await db_ops.get(db, Job, job.id)
        assert done.payload["stage"] == "complete" and done.payload["assessment_hash"]
        assert (await hybrid_task({"settings": settings}, job_id=str(job.id)))["status"] == "done"


async def test_hindi_scene_layout_uses_local_fallback_font() -> None:
    import tempfile

    from app.render.edl_to_ffmpeg import PREVIEW
    from app.render.render import render_timeline
    from app.scenes.models import BridgeScene
    from app.storyboard.planner import update_scene
    from tests.unit.scenes.test_hybrid import planned

    tl = planned()
    spec = tl.scenes[0].model_copy(
        update={
            "title": "मॉड्यूल और कैश",
            "content": BridgeScene(headline="कैश को समझें", supporting="शब्दों के साथ दृश्य बदलते हैं।"),
        }
    )
    tl = update_scene(tl, spec, tl.scene_placements[0], expected_version=tl.version)
    store = get_storage(get_settings())
    with tempfile.TemporaryDirectory(prefix="clipz-hindi-scene-") as work:
        output = await render_timeline(
            tl,
            str(await asyncio.to_thread(Path("fixtures/synth/bars_5s.mp4").resolve)),
            {},
            PREVIEW,
            store,
            work,
            lambda _: None,
        )
        assert output["scene_visibility"]["passed"]
        assert output["scenes"][0]["frame_count"] > 0
