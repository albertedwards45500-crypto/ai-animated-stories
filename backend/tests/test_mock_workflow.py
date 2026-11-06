"""API 全链路集成测试：真实 FFmpeg 文件 + 隔离媒体目录 + SQLite。"""
import json
import shutil
import subprocess

import pytest

from app.core.config import get_settings
from app.models.entities import GeneratedAsset, Subtitle
from app.services import render_service
from tests.test_reliability import script


@pytest.fixture
def real_media(tmp_path, monkeypatch):
    settings = get_settings()
    ffmpeg = shutil.which(settings.ffmpeg_executable)
    if not ffmpeg:
        pytest.skip("FFmpeg unavailable; set FFMPEG_PATH to run integration tests")
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    monkeypatch.setattr(render_service, "TARGET_W", 320)
    monkeypatch.setattr(render_service, "TARGET_H", 180)
    for kind, args, name in [
        ("images", ["-f", "lavfi", "-i", "color=c=blue:s=320x180", "-frames:v", "1"], "frame.png"),
        ("video", ["-f", "lavfi", "-i", "color=c=blue:s=320x180:r=30:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p"], "clip.mp4"),
        ("audio", ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "pcm_s16le"], "voice.wav"),
    ]:
        directory = tmp_path / "mock" / kind
        directory.mkdir(parents=True)
        process = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args, str(directory / name)], capture_output=True, timeout=30)
        assert process.returncode == 0, process.stderr
    return tmp_path


def completed(client, accept):
    response = client.get(f"/api/generation/tasks/{accept['task_id']}")
    data = response.json()["data"]
    assert data["status"] == "succeeded", data
    assert data["progress"] == 100
    return data


@pytest.mark.integration
@pytest.mark.parametrize("burn_in", [True, False])
def test_complete_mock_production_chain(client, project, db_session, real_media, burn_in):
    assert client.get("/api/health").status_code == 200
    created = script(client, project)
    completed(client, created)
    episode_id = created["episode_id"]
    shots = client.get(f"/api/episodes/{episode_id}/shots").json()["data"]
    assert len(shots) == 3
    for shot in shots:
        for capability in ("image", "video", "audio"):
            payload = {"shot_id": shot["id"]}
            if capability == "audio":
                payload["audio_track"] = shot["dialogue"][0]
            response = client.post(f"/api/generation/{capability}", json=payload)
            assert response.status_code == 200, response.text
            task = completed(client, response.json()["data"])
            assert len(task["output_asset_ids"]) == 1
    response = client.post("/api/generation/asr", json={"episode_id": episode_id, "audio_track_ids": []})
    assert response.status_code == 200, response.text
    task = completed(client, response.json()["data"])
    assert task["response_payload"]["subtitle_count"] == 3
    subtitles = db_session.query(Subtitle).order_by(Subtitle.start_ms).all()
    assert [sub.start_ms for sub in subtitles] == [0, 10000, 20000]
    response = client.post("/api/render/jobs", json={"episode_id": episode_id, "subtitle_burn_in": burn_in})
    assert response.status_code == 200, response.text
    accepted = response.json()["data"]
    completed(client, accepted)
    job = client.get(f"/api/render/jobs/{accepted['job_id']}").json()["data"]
    assert job["status"] == "succeeded" and job["output_asset_id"]
    assert client.get(f"/api/episodes/{episode_id}").json()["data"]["status"] == 3
    assert all(s["status"] == 3 for s in client.get(f"/api/episodes/{episode_id}/shots").json()["data"])
    preview = client.get(job["preview_url"])
    download = client.get(job["download_url"])
    assert preview.status_code == download.status_code == 200
    assert preview.content == download.content and len(download.content) > 10000
    assert "attachment" in download.headers["content-disposition"]
    partial = client.get(job["preview_url"], headers={"Range": "bytes=0-63"})
    assert partial.status_code == 206 and partial.content == download.content[:64]
    asset = db_session.get(GeneratedAsset, job["output_asset_id"])
    output = real_media / asset.file_path
    probe = subprocess.run([get_settings().ffmpeg_executable.replace("ffmpeg", "ffprobe"), "-v", "error",
        "-show_streams", "-show_format", "-of", "json", str(output)], capture_output=True, text=True, check=True, timeout=30)
    info = json.loads(probe.stdout)
    stream_types = {s["codec_type"] for s in info["streams"]}
    assert {"video", "audio"} <= stream_types
    assert ("subtitle" in stream_types) is (not burn_in)
    # The 1-second source must be padded to each 10-second shot.
    assert float(info["format"]["duration"]) == pytest.approx(30, abs=0.2)
    decoded = subprocess.run([get_settings().ffmpeg_executable, "-v", "error", "-i", str(output), "-f", "null", "-"], capture_output=True, timeout=30)
    assert decoded.returncode == 0 and not decoded.stderr, decoded.stderr
