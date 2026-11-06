"""角色形象生成及镜头角色版本链路。"""
from __future__ import annotations

def test_character_reference_to_video_mock(client, project, db_session):
    from app.models.entities import GeneratedAsset
    from app.core.config import get_settings

    created = client.post(f"/api/projects/{project['id']}/characters", json={
        "name": "林夏", "hair": "黑色短发", "clothing": "白色外套",
    }).json()["data"]
    cid = created["id"]
    accepted = client.post(f"/api/generation/characters/{cid}/image", json={
        "params": {"mock_scenario": "success"},
    }).json()["data"]
    task = client.get(f"/api/generation/tasks/{accepted['task_id']}").json()["data"]
    assert task["status"] == "succeeded" and task["provider"] == "mock"
    assert task["cost"] == 0
    character = client.get(f"/api/projects/{project['id']}/characters").json()["data"][0]
    primary = character["reference_assets"][0]
    assert primary["is_primary"] and primary["asset_id"] in task["output_asset_ids"]
    asset = db_session.get(GeneratedAsset, primary["asset_id"])
    assert asset.meta_json["kind"] == "character_reference"
    assert (get_settings().media_root_path / asset.file_path).is_file()

    client.post(f"/api/characters/{cid}/confirm")
    episode = client.post(f"/api/projects/{project['id']}/script/generate", json={
        "episode": {"title": "第一集", "story_outline": "两人在旧书店发现地图", "target_duration": 30},
    }).json()["data"]["episode_id"]
    shot = client.get(f"/api/episodes/{episode}/shots").json()["data"][0]
    assert cid in shot["character_ids"]
    image = client.post("/api/generation/image", json={"shot_id": shot["id"],
        "params": {"mock_scenario": "success"}}).json()["data"]
    image_task = client.get(f"/api/generation/tasks/{image['task_id']}").json()["data"]
    assert image_task["status"] == "succeeded"
    shot = client.get(f"/api/episodes/{episode}/shots").json()["data"][0]
    keyframe = db_session.get(GeneratedAsset, shot["keyframe_asset_id"])
    assert keyframe.meta_json["character_refs"][0]["primary_asset_id"] == primary["asset_id"]
    video = client.post("/api/generation/video", json={"shot_id": shot["id"],
        "params": {"mock_scenario": "success"}}).json()["data"]
    video_task = client.get(f"/api/generation/tasks/{video['task_id']}").json()["data"]
    assert video_task["status"] == "succeeded" and video_task["cost"] == 0
    shot = client.get(f"/api/episodes/{episode}/shots").json()["data"][0]
    clip = db_session.get(GeneratedAsset, shot["video_asset_id"])
    assert clip.meta_json["character_refs"] == keyframe.meta_json["character_refs"]
    assert clip.meta_json["keyframe_asset_id"] == keyframe.id


def test_real_generation_requires_locked_reference_without_calling_provider(client, project, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "app_env", "development")
    cid = client.post(f"/api/projects/{project['id']}/characters", json={
        "name": "林夏", "hair": "黑色短发",
    }).json()["data"]["id"]
    episode = client.post(f"/api/projects/{project['id']}/script/generate", json={
        "episode": {"title": "第一集", "story_outline": "旧书店里的地图"},
    }).json()["data"]["episode_id"]
    shot = client.get(f"/api/episodes/{episode}/shots").json()["data"][0]
    denied = client.post("/api/generation/image", json={"shot_id": shot["id"],
        "provider": "dashscope"})
    assert denied.status_code == 400
    assert "主参考图" in denied.json()["message"]


def test_mock_environment_blocks_real_provider(client, project, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "app_env", "mock")
    cid = client.post(f"/api/projects/{project['id']}/characters", json={
        "name": "林夏", "hair": "黑色短发",
    }).json()["data"]["id"]
    denied = client.post(f"/api/generation/characters/{cid}/image", json={"provider": "dashscope"})
    assert denied.status_code == 400
    assert "模拟环境" in denied.json()["message"]


def test_dashscope_video_uses_first_frame_without_network(monkeypatch, tmp_path):
    from app.core.config import get_settings
    from app.providers import dashscope

    image = tmp_path / "frame.png"
    image.write_bytes(b"image-content")
    captured = {}

    class FakeResponse:
        status_code = 200
        def json(self):
            return {"output": {"task_id": "local-test"}}

    class FakeClient:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def post(self, url, **kwargs):
            captured["url"] = url
            captured["body"] = kwargs["json"]
            return FakeResponse()

    monkeypatch.setattr(get_settings(), "dashscope_api_key_video", "offline-test-key")
    monkeypatch.setattr(dashscope.httpx, "Client", FakeClient)
    monkeypatch.setattr(dashscope, "_poll_task", lambda *args: (True, {"video_url": "offline"}, "", False))
    monkeypatch.setattr(dashscope, "_download", lambda url, dest: True)
    result = dashscope.DashScopeVideoProvider().execute({"img_url": str(image), "prompt": "保持人物外观", "duration": 5})
    assert result.ok
    assert captured["body"]["input"]["media"][0]["type"] == "first_frame"
    assert captured["body"]["input"]["media"][0]["url"].startswith("data:image/png;base64,")
    assert captured["body"]["parameters"]["prompt_extend"] is False


def test_dashscope_image_sends_character_reference_without_network(monkeypatch, tmp_path):
    from app.core.config import get_settings
    from app.providers import dashscope

    image = tmp_path / "portrait.png"
    image.write_bytes(b"image-content")
    captured = {}

    class FakeResponse:
        status_code = 200
        def json(self):
            return {"output": {"choices": [{"message": {"content": [{"image": "offline"}]}}]}}

    class FakeClient:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def post(self, url, **kwargs):
            captured["body"] = kwargs["json"]
            return FakeResponse()

    monkeypatch.setattr(get_settings(), "dashscope_api_key_image", "offline-test-key")
    monkeypatch.setattr(dashscope.httpx, "Client", FakeClient)
    monkeypatch.setattr(dashscope, "_download", lambda url, dest: True)
    result = dashscope.DashScopeImageProvider().execute({
        "prompt": "保持林夏外观", "reference_images": [str(image)],
    })
    assert result.ok
    content = captured["body"]["input"]["messages"][0]["content"]
    assert content[0]["image"].startswith("data:image/png;base64,")
    assert content[1]["text"] == "保持林夏外观"
