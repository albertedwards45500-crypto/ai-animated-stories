"""本地制作闭环的故障诊断、幂等和生命周期回归。"""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import OperationalError

from app.api import health
from app.core.config import get_settings
from app.models.entities import AudioTrack, GenerationTask, RenderJob
from app.providers.base import new_uuid
from app.services import task_service


def script(client, project):
    response = client.post(f"/api/projects/{project['id']}/script/generate", json={
        "episode": {"title": "地图的秘密", "story_outline": "在旧书店发现地图", "target_duration": 30},
    })
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_readiness_reports_missing_dependencies(client, monkeypatch):
    monkeypatch.setattr(health, "check_queue", lambda: {"status": "down", "message": "队列不可用"})
    monkeypatch.setattr(health.shutil, "which", lambda _: None)
    response = client.get("/api/health")
    assert response.status_code == 503
    checks = response.json()["data"]["checks"]
    assert checks["database"]["status"] == "up"
    assert checks["queue"]["status"] == checks["ffmpeg"]["status"] == "down"
    assert client.get("/api/health/live").status_code == 200


def test_readiness_sanitizes_database_error(monkeypatch):
    db = Mock()
    db.execute.side_effect = OperationalError("secret-connection-string", {}, Exception("password"))
    response = health.ready(db)
    assert response.status_code == 503
    assert b"secret-connection-string" not in response.body
    assert b"password" not in response.body
    db.rollback.assert_called_once()


def test_readiness_detects_missing_schema(db_session, monkeypatch):
    monkeypatch.setattr(health, "inspect", lambda _: SimpleNamespace(get_table_names=lambda: []))
    response = health.ready(db_session)
    assert response.status_code == 503
    assert b"missing_tables" in response.body


def test_redis_readiness_handles_connection_failure(monkeypatch):
    from redis import Redis
    monkeypatch.setattr(get_settings(), "broker_kind", "redis")
    monkeypatch.setattr(Redis, "from_url", Mock(side_effect=ConnectionError("secret")))
    assert health.check_queue()["status"] == "down"
    assert "secret" not in str(health.check_queue())


def test_cost_stats_use_milliseconds_and_project_filter(client, project, db_session):
    start = datetime(2026, 1, 1, 10, 0)
    for status, duration, cost in [("succeeded", 2, 0.2), ("failed", 4, 0.1)]:
        db_session.add(GenerationTask(uuid=new_uuid(), project_id=project["id"], type="image",
            provider="mock", model="m1", status=status, cost=cost,
            started_at=start, finished_at=start + timedelta(seconds=duration)))
    db_session.commit()
    response = client.get("/api/stats/cost", params={"project_id": project["id"]})
    assert response.status_code == 200, response.text
    row = response.json()["data"][0]
    assert row["total_calls"] == 2 and row["succeeded"] == row["failed"] == 1
    assert row["success_rate"] == 0.5 and row["total_cost"] == 0.3
    assert row["avg_elapsed_ms"] == pytest.approx(3000, abs=1)
    assert client.get("/api/stats/cost?project_id=999999").json()["data"] == []


def test_render_job_tracks_failure_retry_cancel_and_recovery(project, db_session):
    task = task_service.create_task(db_session, project_id=project["id"], task_type="render",
        provider="local", mode="mock", model="ffmpeg", request_payload={})
    job = RenderJob(uuid=new_uuid(), task_id=task.id, episode_id=1, status="queued")
    db_session.add(job)
    db_session.commit()
    assert task_service.mark_processing(db_session, task)
    assert not task_service.mark_processing(db_session, task)
    db_session.refresh(job)
    assert job.status == "processing"
    task_service.finish_task(db_session, task, status="failed", error_message="ffmpeg failed")
    db_session.refresh(job)
    assert job.status == "failed" and job.error_message == "ffmpeg failed"
    task_service.retry_task(db_session, task)
    db_session.refresh(job)
    assert job.status == "queued" and job.error_message is None
    task_service.cancel_task(db_session, task)
    # A late worker must not turn a cancelled task into succeeded.
    task_service.finish_task(db_session, task, status="succeeded")
    db_session.refresh(job)
    assert task.status == job.status == "cancelled"
    task_service.retry_task(db_session, task)
    task._attempt_retry_count = task.retry_count - 1
    task_service.finish_task(db_session, task, status="succeeded")
    db_session.refresh(task)
    db_session.refresh(job)
    assert task.status == job.status == "queued"
    task._attempt_retry_count = task.retry_count
    task_service.mark_processing(db_session, task)
    task.started_at = datetime.now() - timedelta(hours=1)
    db_session.commit()
    assert task_service.recover_stale_tasks(db_session) == 1
    db_session.refresh(job)
    assert task.status == job.status == "failed"


def test_audio_cache_does_not_duplicate_or_overwrite_other_dialogue(client, project, db_session):
    result = script(client, project)
    shot = client.get(f"/api/episodes/{result['episode_id']}/shots").json()["data"][0]
    line = shot["dialogue"][0]
    assert isinstance(line["character_id"], int)
    payload = {"shot_id": shot["id"], "audio_track": line}
    first = client.post("/api/generation/audio", json=payload).json()["data"]
    second = client.post("/api/generation/audio", json=payload).json()["data"]
    assert second["cached"] and second["task_id"] == first["task_id"]
    assert db_session.query(AudioTrack).count() == 1
    payload["audio_track"] = {**line, "text": "这是另一句对白。"}
    assert client.post("/api/generation/audio", json=payload).status_code == 200
    tracks = db_session.query(AudioTrack).order_by(AudioTrack.id).all()
    assert len(tracks) == 2 and tracks[0].text_raw == line["text"]
    # A confirmation prompt must not leave a blank track.
    payload["provider"] = "minimax"
    assert client.post("/api/generation/audio", json=payload).json()["data"]["require_confirm"]
    assert db_session.query(AudioTrack).count() == 2


def test_asr_rejects_missing_or_foreign_audio(client, project, db_session):
    result = script(client, project)
    response = client.post("/api/generation/asr", json={"episode_id": result["episode_id"]})
    assert response.status_code == 400
    assert response.json()["code"] == 40002
    response = client.post("/api/generation/asr", json={"episode_id": result["episode_id"], "audio_track_ids": [99999]})
    assert response.status_code == 400


def test_local_restart_recovers_queued_and_recent_processing(project, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "broker_kind", "thread")
    for status in ["queued", "processing"]:
        db_session.add(GenerationTask(uuid=new_uuid(), project_id=project["id"], type="image",
            status=status, started_at=datetime.now()))
    db_session.commit()
    assert task_service.recover_stale_tasks(db_session) == 2
    assert {t.status for t in db_session.query(GenerationTask).all()} == {"failed"}


@pytest.mark.parametrize("scenario, expected", [("fail", "failed"), ("timeout", "timeout")])
def test_mock_retry_succeeds_after_simulated_failure(client, project, scenario, expected):
    created = script(client, project)
    shot = client.get(f"/api/episodes/{created['episode_id']}/shots").json()["data"][0]
    accepted = client.post("/api/generation/image", json={
        "shot_id": shot["id"], "params": {"mock_scenario": scenario},
    }).json()["data"]
    task_url = f"/api/generation/tasks/{accepted['task_id']}"
    assert client.get(task_url).json()["data"]["status"] == expected
    response = client.post(task_url + "/retry")
    assert response.status_code == 200
    retried = client.get(task_url).json()["data"]
    assert retried["retry_count"] == 1
    assert retried["status"] == "succeeded", retried
