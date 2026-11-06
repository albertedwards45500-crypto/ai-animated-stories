"""通过 HTTP 验证独立 Mock 服务；保留一个可在前端查看的验收项目。

先运行 start-mock.bat，再从 backend 运行 python -m app.tools.e2e_verify。
仅允许 /api/health 报告 profile=mock 的服务，不读取生产数据库或调用真实 Provider。
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime

import httpx

TERMINAL = {"succeeded", "failed", "timeout", "cancelled"}


def request(client: httpx.Client, method: str, path: str, **kwargs) -> dict:
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    body = response.json()
    assert body["code"] == 0, body
    return body["data"]


def wait_task(client: httpx.Client, task_id: str, expected: str = "succeeded", timeout: float = 180) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = request(client, "GET", f"/api/generation/tasks/{task_id}")
        if task["status"] in TERMINAL:
            assert task["status"] == expected, task
            return task
        time.sleep(0.25)
    raise TimeoutError(f"Task {task_id} did not finish within {timeout}s")


def verify(client: httpx.Client) -> dict:
    ready = request(client, "GET", "/api/health")
    assert ready["profile"] == "mock", "只允许独立 Mock 服务；请先运行 start-mock.bat"
    assert ready["checks"]["queue"].get("kind") == "thread", "验收需要本地异步线程队列"
    print("[PASS] Mock readiness: SQLite / thread queue / FFmpeg")
    project = request(client, "POST", "/api/projects", json={
        "name": "Mock 闭环验收 " + datetime.now().strftime("%m-%d %H:%M:%S"), "genre": "悬疑",
    })
    created = request(client, "POST", f"/api/projects/{project['id']}/script/generate", json={
        "episode": {"title": "地图的秘密", "story_outline": "两人在旧书店发现一张地图。", "target_duration": 30},
        "provider": "mock",
    })
    wait_task(client, created["task_id"])
    episode_id = created["episode_id"]
    shots = request(client, "GET", f"/api/episodes/{episode_id}/shots")
    assert len(shots) == 3 and all(shot["dialogue"] for shot in shots)
    print("[PASS] script / characters / scenes / 3 shots")
    for shot in shots:
        for capability in ("image", "video", "audio"):
            payload = {"shot_id": shot["id"], "provider": "mock"}
            if capability == "audio":
                payload["audio_track"] = shot["dialogue"][0]
            else:
                payload["params"] = {"mock_scenario": "success"}
            accepted = request(client, "POST", f"/api/generation/{capability}", json=payload)
            task = wait_task(client, accepted["task_id"])
            assert task["output_asset_ids"]
            if capability == "audio":
                cached = request(client, "POST", "/api/generation/audio", json=payload)
                assert cached.get("cached") and cached["task_id"] == accepted["task_id"]
        print(f"[PASS] shot {shot['id']}: image / video / audio / audio cache")
    asr = request(client, "POST", "/api/generation/asr", json={"episode_id": episode_id, "provider": "mock"})
    asr_task = wait_task(client, asr["task_id"])
    assert asr_task["response_payload"]["subtitle_count"] == 3
    print("[PASS] subtitles from generated audio")
    render = request(client, "POST", "/api/render/jobs", json={"episode_id": episode_id, "subtitle_burn_in": True})
    wait_task(client, render["task_id"])
    job = request(client, "GET", f"/api/render/jobs/{render['job_id']}")
    assert job["status"] == "succeeded"
    preview = client.get(job["preview_url"], follow_redirects=True)
    download = client.get(job["download_url"])
    preview.raise_for_status()
    download.raise_for_status()
    assert download.content == preview.content and download.content[4:8] == b"ftyp"
    assert "attachment" in download.headers["content-disposition"]
    partial = client.get(job["preview_url"], headers={"Range": "bytes=0-63"}, follow_redirects=True)
    assert partial.status_code == 206 and partial.content == download.content[:64]
    print(f"[PASS] FFmpeg render / preview / download / Range ({len(download.content)} bytes)")
    for scenario, expected in (("fail", "failed"), ("timeout", "timeout")):
        accepted = request(client, "POST", "/api/generation/image", json={
            "shot_id": shots[0]["id"], "provider": "mock", "params": {"mock_scenario": scenario},
        })
        wait_task(client, accepted["task_id"], expected)
        if scenario == "fail":
            retry = request(client, "POST", f"/api/generation/tasks/{accepted['task_id']}/retry")
            assert retry["retry_count"] == 1
            wait_task(client, accepted["task_id"], "succeeded")
    cancel = request(client, "POST", "/api/generation/video", json={
        "shot_id": shots[0]["id"], "provider": "mock", "params": {"mock_scenario": "success", "cancel_check": True},
    })
    request(client, "POST", f"/api/generation/tasks/{cancel['task_id']}/cancel")
    wait_task(client, cancel["task_id"], "cancelled")
    with client.stream("GET", f"/api/generation/tasks/{render['task_id']}/events") as events:
        events.raise_for_status()
        frames = "\n".join(events.iter_lines())
    assert "event: status" in frames and '"succeeded"' in frames
    stats = request(client, "GET", "/api/stats/cost", params={"project_id": project["id"]})
    assert stats and all(row["avg_elapsed_ms"] is None or row["avg_elapsed_ms"] >= 0 for row in stats)
    print("[PASS] failure / timeout / retry / cancellation / SSE / cost stats")
    return {"project_id": project["id"], "episode_id": episode_id, "render_job_id": job["job_id"],
            "output_asset_id": job["output_asset_id"], "download_bytes": len(download.content)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        result = verify(client)
    print(json.dumps(result, ensure_ascii=False))
    print("[PASS] HTTP Mock E2E complete; project retained for review")


if __name__ == "__main__":
    main()
