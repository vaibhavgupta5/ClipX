"""End-to-end product run over HTTP: project -> upload -> analysis -> Director chat -> render.

Uses only the public API, exactly as Studio does. Writes a JSON report with every Director
tool call, tool error and the render result so a run can be compared with a hand edit.

    python -m scripts.pipeline_e2e <video> "<instruction>" --name demo --out work/pipeline-run
"""

import argparse
import json
import time
from pathlib import Path
from typing import Any

import httpx

API = "http://127.0.0.1:8000"
HEADERS = {"X-API-Key": "reelforge-dev-key"}  # the Studio's default workspace: runs show up there


def wait_for_timeline(client: httpx.Client, pid: str, timeout_s: float = 900) -> dict[str, Any]:
    """Analysis creates timeline v1; poll until it exists."""
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        r = client.get(f"/projects/{pid}/timeline")
        if r.status_code == 200:
            return dict(r.json())
        time.sleep(3)
    raise TimeoutError("analysis did not produce a timeline in time")


def chat(client: httpx.Client, pid: str, text: str) -> list[dict[str, Any]]:
    """Stream one Director turn; collect every SSE event."""
    events: list[dict[str, Any]] = []
    kind = "message"
    with client.stream(
        "POST", f"/projects/{pid}/messages", json={"text": text}, timeout=None
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith("event:"):
                kind = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1].strip() or "null")
                events.append({"type": kind, "data": data})
                if kind in ("tool_call", "tool_result", "error", "done"):
                    print(kind, json.dumps(data, default=str)[:220], flush=True)
    return events


def render(client: httpx.Client, pid: str, timeout_s: float = 1800) -> dict[str, Any]:
    r = client.post(f"/projects/{pid}/render", json={"profile": "final"})
    r.raise_for_status()
    rid = r.json()["render_id"]
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        status = client.get(f"/projects/{pid}/renders/{rid}").json()
        if status.get("status") in ("done", "failed", "error"):
            return dict(status)
        time.sleep(5)
    raise TimeoutError("render did not finish in time")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("instruction")
    ap.add_argument("--name", default="pipeline-e2e")
    ap.add_argument("--out", default="work/pipeline-run")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"video": args.video, "instruction": args.instruction}
    with httpx.Client(base_url=API, headers=HEADERS, timeout=120) as client:
        pid = client.post("/projects", json={"name": args.name, "language": "en"}).json()[
            "project_id"
        ]
        report["project_id"] = pid
        t0 = time.monotonic()
        with open(args.video, "rb") as fh:
            up = client.post(
                f"/projects/{pid}/uploads", files={"file": (Path(args.video).name, fh, "video/mp4")}
            )
        up.raise_for_status()
        report["upload"] = up.json()
        tl = wait_for_timeline(client, pid)
        report["analysis_s"] = round(time.monotonic() - t0, 1)
        report["timeline_v1"] = tl.get("summary")
        t1 = time.monotonic()
        events = chat(client, pid, args.instruction)
        report["director_s"] = round(time.monotonic() - t1, 1)
        report["events"] = events
        report["tool_calls"] = [e["data"] for e in events if e["type"] == "tool_call"]
        report["tool_errors"] = [
            e["data"]
            for e in events
            if e["type"] == "tool_result" and not (e["data"] or {}).get("ok", True)
        ]
        final = client.get(f"/projects/{pid}/timeline").json()
        report["timeline_final"] = final.get("summary")
        (out / f"{args.name}-timeline.json").write_text(json.dumps(final, indent=2))
        t2 = time.monotonic()
        report["render"] = render(client, pid)
        report["render_s"] = round(time.monotonic() - t2, 1)
    (out / f"{args.name}-report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: report[k] for k in ("project_id", "analysis_s", "director_s")}))
    print("render:", json.dumps(report["render"], default=str)[:400])


if __name__ == "__main__":
    main()
