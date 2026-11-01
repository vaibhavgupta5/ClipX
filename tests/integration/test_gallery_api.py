"""Gallery API: finished edits across projects, scoped to the caller's workspace. Opt-in."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app import db as db_ops
from app.main import create_app
from app.models import Render

pytestmark = pytest.mark.integration


def _client(key: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=create_app()),
        base_url="http://test",
        headers={"X-API-Key": key},
    )


async def test_gallery_lists_done_renders_newest_first_and_hides_previews_by_default() -> None:
    key = f"gallery-{uuid.uuid4()}"
    async with _client(key) as c:
        pid = (await c.post("/projects", json={"name": "Gallery reel"})).json()["project_id"]
        db = db_ops.get_db()
        for profile, status in (("final", "done"), ("preview", "done"), ("final", "queued")):
            await db_ops.insert(
                db,
                Render(
                    project_id=uuid.UUID(pid),
                    timeline_version_id=uuid.UUID(int=0),
                    profile=profile,
                    status=status,
                    output_url=f"/media/renders/{pid}/{profile}.mp4",
                    output_key=f"renders/{pid}/{profile}.mp4",
                    quality={"imported": True, "duration_s": 12.5, "secret": "not exposed"},
                ),
            )
        shown = (await c.get("/renders")).json()
        assert shown["total"] == 1 and shown["renders"][0]["profile"] == "final"
        assert shown["renders"][0]["project_name"] == "Gallery reel"
        assert shown["renders"][0]["quality"] == {"imported": True, "duration_s": 12.5}
        with_previews = (await c.get("/renders?include_previews=true")).json()
        assert with_previews["total"] == 2  # queued renders never appear
    async with _client(f"other-{uuid.uuid4()}") as stranger:
        assert (await stranger.get("/renders")).json() == {"renders": [], "total": 0}


async def test_poster_of_a_missing_or_foreign_render_is_404() -> None:
    async with _client(f"gallery-{uuid.uuid4()}") as c:
        assert (await c.get(f"/renders/{uuid.uuid4()}/poster")).status_code == 404
