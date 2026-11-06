# -*- coding: utf-8 -*-
"""API 契约测试：统一响应格式、错误码、项目/剧集/场景/分镜 CRUD、素材。"""
from __future__ import annotations


def test_health(client):
    """健康检查返回 code=0。"""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["message"] == "ok"


def test_project_crud(client, project):
    """项目 CRUD 全流程。"""
    # 列表
    resp = client.get("/api/projects")
    assert resp.json()["code"] == 0
    assert resp.json()["data"]["total"] == 1
    # 详情
    resp = client.get(f"/api/projects/{project['id']}")
    assert resp.json()["data"]["name"] == "测试项目"
    assert "episode_count" in resp.json()["data"]
    # 更新
    resp = client.put(f"/api/projects/{project['id']}", json={"genre": "喜剧"})
    assert resp.json()["data"]["genre"] == "喜剧"
    # 删除
    resp = client.delete(f"/api/projects/{project['id']}")
    assert resp.json()["code"] == 0
    resp = client.get(f"/api/projects/{project['id']}")
    assert resp.json()["code"] == 40401


def test_project_validation_error(client):
    """创建项目缺少 name 返回 40001。"""
    resp = client.post("/api/projects", json={})
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 40001
    assert body["data"]["errors"]


def test_episode_scene_shot_crud(client, project):
    """剧集/场景/分镜 CRUD。"""
    pid = project["id"]
    # 剧集
    resp = client.post(f"/api/projects/{pid}/script/generate", json={
        "episode": {"title": "第一集", "story_outline": "雨夜来电"},
    })
    assert resp.json()["code"] == 0
    ep_id = resp.json()["data"]["episode_id"]
    resp = client.get(f"/api/episodes/{ep_id}")
    assert resp.json()["data"]["title"] == "第一集"
    # 场景
    generated = client.get(f"/api/episodes/{ep_id}/shots").json()["data"]
    assert len(generated) == 3
    resp = client.post(f"/api/episodes/{ep_id}/scenes", json={"scene_no": 2, "purpose": "铺垫"})
    assert resp.json()["code"] == 0
    scene_id = resp.json()["data"]["id"]
    # 重复序号 → 40002
    resp = client.post(f"/api/episodes/{ep_id}/scenes", json={"scene_no": 2})
    assert resp.json()["code"] == 40002
    # 分镜
    resp = client.post(f"/api/scenes/{scene_id}/shots", json={
        "shot_no": 1, "shot_type": "近景", "camera_movement": "推",
        "dialogue": [{"character_id": 1, "text": "你终于来了。", "emotion": "紧张"}],
        "duration": 5.0,
    })
    assert resp.json()["code"] == 0
    shot_id = resp.json()["data"]["id"]
    # 更新分镜
    resp = client.put(f"/api/shots/{shot_id}", json={"action_description": "盯着电话"})
    assert resp.json()["code"] == 0
    # 时间轴数据源
    resp = client.get(f"/api/episodes/{ep_id}/shots")
    assert len(resp.json()["data"]) == len(generated) + 1
    # 删除分镜
    resp = client.delete(f"/api/shots/{shot_id}")
    assert resp.json()["code"] == 0


def test_delete_project_with_running_task(client, project, db_session):
    """存在进行中任务时删除项目返回 40901。"""
    from app.models.entities import GenerationTask
    from app.providers.base import new_uuid

    db_session.add(GenerationTask(
        uuid=new_uuid(), project_id=project["id"], type="text",
        status="queued",
    ))
    db_session.commit()
    resp = client.delete(f"/api/projects/{project['id']}")
    assert resp.status_code == 409
    assert resp.json()["code"] == 40901


def test_asset_upload_and_raw(client, project):
    """素材上传、列表、raw 文件流。"""
    pid = project["id"]
    content = b"\x89PNG\r\n\x1a\nfake-image-bytes"
    resp = client.post("/api/assets/upload",
                       files={"file": ("test.png", content, "image/png")},
                       data={"project_id": str(pid), "asset_type": "image"})
    assert resp.json()["code"] == 0
    asset = resp.json()["data"]
    # 列表
    resp = client.get("/api/assets", params={"project_id": pid, "asset_type": "image"})
    assert resp.json()["data"]["total"] == 1
    # raw
    resp = client.get(f"/api/assets/{asset['id']}/raw")
    assert resp.status_code == 200
    assert resp.content == content


def test_settings_apis(client, project):
    """角色卡/场景卡/画风预设 CRUD 与角色卡锁定。"""
    pid = project["id"]
    resp = client.post(f"/api/projects/{pid}/characters", json={"name": "林夏", "hair": "黑长直"})
    assert resp.json()["code"] == 0
    cid = resp.json()["data"]["id"]
    # 未锁定可改
    resp = client.put(f"/api/characters/{cid}", json={"clothing": "白色卫衣"})
    assert resp.json()["code"] == 0
    version_after_edit = resp.json()["data"]["version"]
    # 锁定
    resp = client.post(f"/api/characters/{cid}/confirm")
    assert resp.json()["data"]["confirmed"] == 1
    locked_version = resp.json()["data"]["version"]
    assert locked_version > version_after_edit
    # 锁定后修改 → 40901
    resp = client.put(f"/api/characters/{cid}", json={"hair": "短发"})
    assert resp.status_code == 409
    assert resp.json()["code"] == 40901
    # 场景卡
    resp = client.post(f"/api/projects/{pid}/locations", json={"name": "出租屋"})
    assert resp.json()["code"] == 0
    # 画风
    resp = client.post("/api/style-presets", json={"name": "赛博朋克", "style_prompt": "neon"})
    assert resp.json()["code"] == 0
    resp = client.get("/api/style-presets")
    assert resp.json()["data"][0]["name"] == "赛博朋克"


def test_character_reference_assets(client, project):
    """角色参考图支持主图切换，并在角色锁定后禁止变更。"""
    pid = project["id"]
    resp = client.post(f"/api/projects/{pid}/characters", json={"name": "林夏"})
    assert resp.json()["code"] == 0
    cid = resp.json()["data"]["id"]

    first = client.post(
        f"/api/characters/{cid}/assets",
        files={"file": ("front.png", b"first-image", "image/png")},
    ).json()["data"]
    second = client.post(
        f"/api/characters/{cid}/assets",
        files={"file": ("profile.png", b"second-image", "image/png")},
    ).json()["data"]
    assert first["is_primary"] is True
    assert second["is_primary"] is False

    resp = client.post(f"/api/characters/{cid}/assets/{second['asset_id']}/primary")
    assets = resp.json()["data"]
    assert assets[0]["asset_id"] == second["asset_id"]
    assert assets[0]["is_primary"] is True

    characters = client.get(f"/api/projects/{pid}/characters").json()["data"]
    assert characters[0]["reference_assets"][0]["asset_id"] == second["asset_id"]

    client.post(f"/api/characters/{cid}/confirm")
    resp = client.post(
        f"/api/characters/{cid}/assets",
        files={"file": ("locked.png", b"locked-image", "image/png")},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == 40901
    resp = client.post(f"/api/characters/{cid}/assets/{first['asset_id']}/primary")
    assert resp.status_code == 409
    assert resp.json()["code"] == 40901


def test_provider_configs(client):
    """Provider 配置读取与更新（不含密钥）。"""
    resp = client.get("/api/provider-configs")
    assert resp.json()["code"] == 0
    caps = {c["capability"] for c in resp.json()["data"]}
    assert caps == {"text", "image", "video", "audio", "asr"}
    resp = client.put("/api/provider-configs/text", json={"mode": "record", "daily_quota": 10})
    assert resp.json()["data"]["mode"] == "record"
    assert resp.json()["data"]["api_key_ref"]  # 只含变量名
