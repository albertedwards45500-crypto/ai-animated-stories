# -*- coding: utf-8 -*-
"""剧集、场景、分镜 API：/api/projects/{id}/episodes、/api/episodes、/api/scenes、/api/shots。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.enums import EpisodeStatus, TaskType
from app.core.response import BizError, CODE_NOT_FOUND, ok
from app.models.entities import Episode, GenerationTask, Scene, Shot
from app.schemas.entities import (
    EpisodeCreate, EpisodeUpdate, SceneCreate, SceneUpdate, ScriptGenerateRequest,
    ShotCreate, ShotUpdate,
)
from app.services.task_runner import dispatch_task
from app.services import task_service
from app.providers.registry import get_provider

router = APIRouter(tags=["episodes"])


def get_episode_or_404(db: Session, episode_id: int) -> Episode:
    """按 ID 获取剧集，不存在抛 40401。

    Args:
        db: 数据库会话。
        episode_id: 剧集 ID。

    Returns:
        Episode: 剧集行。
    """
    ep = db.get(Episode, episode_id)
    if ep is None:
        raise BizError(CODE_NOT_FOUND, f"剧集 {episode_id} 不存在")
    return ep


def _episode_dict(db: Session, ep: Episode, with_scenes: bool = False) -> dict:
    """序列化剧集行。

    Args:
        db: 数据库会话。
        ep: 剧集行。
        with_scenes: 是否附带场景/分镜概要。

    Returns:
        dict: 剧集数据。
    """
    data = {
        "id": ep.id, "project_id": ep.project_id, "episode_no": ep.episode_no,
        "title": ep.title, "logline": ep.logline, "story_outline": ep.story_outline,
        "script_json": ep.script_json, "target_duration": ep.target_duration,
        "status": ep.status,
        "created_at": ep.created_at.isoformat() if ep.created_at else None,
        "updated_at": ep.updated_at.isoformat() if ep.updated_at else None,
    }
    scenes = db.query(Scene).filter(Scene.episode_id == ep.id).order_by(Scene.scene_no).all()
    data["scene_count"] = len(scenes)
    data["shot_count"] = db.query(Shot).filter(Shot.episode_id == ep.id).count()
    if with_scenes:
        data["scenes"] = [
            {
                "id": sc.id, "scene_no": sc.scene_no, "code": sc.code,
                "location_id": sc.location_id, "time_of_day": sc.time_of_day,
                "purpose": sc.purpose, "summary": sc.summary,
                "shots": [
                    {
                        "id": sh.id, "shot_no": sh.shot_no, "code": sh.code,
                        "shot_type": sh.shot_type, "camera_movement": sh.camera_movement,
                        "character_ids": sh.character_ids, "action_description": sh.action_description,
                        "dialogue": sh.dialogue, "visual_prompt": sh.visual_prompt,
                        "duration": float(sh.duration) if sh.duration is not None else None,
                        "keyframe_asset_id": sh.keyframe_asset_id,
                        "video_asset_id": sh.video_asset_id, "status": sh.status,
                    }
                    for sh in db.query(Shot).filter(Shot.scene_id == sc.id).order_by(Shot.shot_no).all()
                ],
            }
            for sc in scenes
        ]
    return data


@router.post("/api/projects/{project_id}/script/generate")
def generate_script(project_id: int, body: ScriptGenerateRequest, db: Session = Depends(get_db)):
    """生成剧本（异步任务）：落库 queued → 投递队列 → 返回任务受理结果。

    Args:
        project_id: 项目 ID。
        body: 剧集信息与 provider。
        db: 数据库会话。

    Returns:
        JSONResponse: task_id / status / poll 地址。
    """
    from app.api.projects import get_project_or_404

    get_project_or_404(db, project_id)
    # 集序号缺省自动递增
    ep_no = body.episode.episode_no
    if ep_no is None:
        max_no = db.query(Episode).filter(Episode.project_id == project_id).order_by(Episode.episode_no.desc()).first()
        ep_no = (max_no.episode_no + 1) if max_no else 1
    ep = Episode(
        project_id=project_id, episode_no=ep_no,
        title=body.episode.title, logline=body.episode.logline or "",
        story_outline=body.episode.story_outline,
        target_duration=body.episode.target_duration,
        status=EpisodeStatus.DRAFT.value,
    )
    db.add(ep)
    db.flush()

    provider_name, mode, model = _resolve("text", body.provider)
    task = task_service.create_task(
        db, project_id=project_id, task_type=TaskType.TEXT.value,
        provider=provider_name, mode=mode, model=model,
        request_payload={
            "episode_id": ep.id,
            "episode_title": ep.title,
            "story_outline": ep.story_outline,
            "target_duration": ep.target_duration or 60,
            "genre": None, "audience": None,
        },
        episode_id=ep.id,
    )
    db.commit()
    dispatch_task(task.uuid)
    return ok({
        "task_id": task.uuid, "status": task.status,
        "poll": f"/api/generation/tasks/{task.uuid}",
        "episode_id": ep.id,
    })


def _resolve(capability: str, explicit: str | None) -> tuple[str, str, str]:
    """解析 provider/mode/model（不实例化，仅用于任务落库）。

    Args:
        capability: 能力标识。
        explicit: 请求显式指定。

    Returns:
        tuple: (provider, mode, model)。
    """
    from app.core.config import get_settings

    settings = get_settings()
    mode = explicit and settings.ai_mode or settings.ai_mode
    provider = explicit or getattr(settings, f"{capability}_provider", "mock")
    return provider, mode, "mock-1"


@router.get("/api/projects/{project_id}/episodes")
def list_episodes(project_id: int, db: Session = Depends(get_db)):
    """剧集列表。

    Args:
        project_id: 项目 ID。
        db: 数据库会话。

    Returns:
        JSONResponse: 剧集数组。
    """
    eps = db.query(Episode).filter(Episode.project_id == project_id).order_by(Episode.episode_no).all()
    return ok([_episode_dict(db, ep) for ep in eps])


@router.get("/api/episodes/{episode_id}")
def get_episode(episode_id: int, db: Session = Depends(get_db)):
    """剧集详情（含 scenes/shots）。

    Args:
        episode_id: 剧集 ID。
        db: 数据库会话。

    Returns:
        JSONResponse: 剧集完整数据。
    """
    ep = get_episode_or_404(db, episode_id)
    return ok(_episode_dict(db, ep, with_scenes=True))


@router.put("/api/episodes/{episode_id}")
def update_episode(episode_id: int, body: EpisodeUpdate, db: Session = Depends(get_db)):
    """更新剧集（标题/梗概/状态等）。

    Args:
        episode_id: 剧集 ID。
        body: 更新请求。
        db: 数据库会话。

    Returns:
        JSONResponse: 更新后的剧集。
    """
    ep = get_episode_or_404(db, episode_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(ep, field, value)
    db.commit()
    db.refresh(ep)
    return ok(_episode_dict(db, ep))


@router.post("/api/episodes/{episode_id}/scenes")
def create_scene(episode_id: int, body: SceneCreate, db: Session = Depends(get_db)):
    """创建剧本场景。

    Args:
        episode_id: 剧集 ID。
        body: 场景创建请求。
        db: 数据库会话。

    Returns:
        JSONResponse: 新场景。
    """
    ep = get_episode_or_404(db, episode_id)
    exists = db.query(Scene).filter(Scene.episode_id == episode_id, Scene.scene_no == body.scene_no).first()
    if exists:
        raise BizError(40002, f"场景序号 {body.scene_no} 已存在")
    sc = Scene(
        episode_id=episode_id, scene_no=body.scene_no,
        code=body.code or f"scene_{body.scene_no:03d}",
        location_id=body.location_id, time_of_day=body.time_of_day,
        purpose=body.purpose, summary=body.summary,
    )
    db.add(sc)
    db.commit()
    db.refresh(sc)
    return ok({"id": sc.id, "episode_id": sc.episode_id, "scene_no": sc.scene_no, "code": sc.code})


@router.get("/api/episodes/{episode_id}/scenes")
def list_scenes(episode_id: int, db: Session = Depends(get_db)):
    """场景列表（含 shots 数）。

    Args:
        episode_id: 剧集 ID。
        db: 数据库会话。

    Returns:
        JSONResponse: 场景数组。
    """
    get_episode_or_404(db, episode_id)
    scenes = db.query(Scene).filter(Scene.episode_id == episode_id).order_by(Scene.scene_no).all()
    items = []
    for sc in scenes:
        items.append({
            "id": sc.id, "episode_id": sc.episode_id, "scene_no": sc.scene_no,
            "code": sc.code, "location_id": sc.location_id, "time_of_day": sc.time_of_day,
            "purpose": sc.purpose, "summary": sc.summary,
            "shot_count": db.query(Shot).filter(Shot.scene_id == sc.id).count(),
        })
    return ok(items)


@router.put("/api/scenes/{scene_id}")
def update_scene(scene_id: int, body: SceneUpdate, db: Session = Depends(get_db)):
    """更新场景。

    Args:
        scene_id: 场景 ID。
        body: 更新请求。
        db: 数据库会话。

    Returns:
        JSONResponse: 更新后的场景。
    """
    sc = db.get(Scene, scene_id)
    if sc is None:
        raise BizError(CODE_NOT_FOUND, f"场景 {scene_id} 不存在")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(sc, field, value)
    db.commit()
    db.refresh(sc)
    return ok({"id": sc.id, "scene_no": sc.scene_no, "code": sc.code, "summary": sc.summary})


@router.delete("/api/scenes/{scene_id}")
def delete_scene(scene_id: int, db: Session = Depends(get_db)):
    """删除场景（级联删除分镜）。

    Args:
        scene_id: 场景 ID。
        db: 数据库会话。

    Returns:
        JSONResponse: 空数据成功响应。
    """
    sc = db.get(Scene, scene_id)
    if sc is None:
        raise BizError(CODE_NOT_FOUND, f"场景 {scene_id} 不存在")
    db.query(Shot).filter(Shot.scene_id == scene_id).delete()
    db.delete(sc)
    db.commit()
    return ok(None, "deleted")


@router.post("/api/scenes/{scene_id}/shots")
def create_shot(scene_id: int, body: ShotCreate, db: Session = Depends(get_db)):
    """创建分镜。

    Args:
        scene_id: 场景 ID。
        body: 分镜创建请求。
        db: 数据库会话。

    Returns:
        JSONResponse: 新分镜。
    """
    sc = db.get(Scene, scene_id)
    if sc is None:
        raise BizError(CODE_NOT_FOUND, f"场景 {scene_id} 不存在")
    exists = db.query(Shot).filter(Shot.scene_id == scene_id, Shot.shot_no == body.shot_no).first()
    if exists:
        raise BizError(40002, f"镜头序号 {body.shot_no} 已存在")
    shot = Shot(
        episode_id=sc.episode_id, scene_id=scene_id, scene_no=sc.scene_no,
        shot_no=body.shot_no, code=body.code or f"shot_{body.shot_no:03d}",
        location_id=body.location_id or sc.location_id,
        character_ids=body.character_ids or [], shot_type=body.shot_type,
        camera_movement=body.camera_movement, action_description=body.action_description,
        dialogue=[d.model_dump() for d in (body.dialogue or [])],
        visual_prompt=body.visual_prompt, duration=body.duration,
        status=0,
    )
    db.add(shot)
    db.commit()
    db.refresh(shot)
    return ok({"id": shot.id, "scene_id": shot.scene_id, "code": shot.code, "status": shot.status})


@router.get("/api/episodes/{episode_id}/shots")
def list_episode_shots(episode_id: int, db: Session = Depends(get_db)):
    """跨场景按播放顺序返回分镜（时间轴数据源）。

    Args:
        episode_id: 剧集 ID。
        db: 数据库会话。

    Returns:
        JSONResponse: 分镜数组。
    """
    get_episode_or_404(db, episode_id)
    shots = db.query(Shot).filter(Shot.episode_id == episode_id).order_by(Shot.scene_no, Shot.shot_no).all()
    return ok([
        {
            "id": sh.id, "episode_id": sh.episode_id, "scene_id": sh.scene_id,
            "scene_no": sh.scene_no, "shot_no": sh.shot_no, "code": sh.code,
            "shot_type": sh.shot_type, "camera_movement": sh.camera_movement,
            "character_ids": sh.character_ids, "action_description": sh.action_description,
            "dialogue": sh.dialogue, "visual_prompt": sh.visual_prompt,
            "duration": float(sh.duration) if sh.duration is not None else None,
            "keyframe_asset_id": sh.keyframe_asset_id, "video_asset_id": sh.video_asset_id,
            "status": sh.status,
        }
        for sh in shots
    ])


@router.put("/api/shots/{shot_id}")
def update_shot(shot_id: int, body: ShotUpdate, db: Session = Depends(get_db)):
    """更新分镜（含 visual_prompt）。

    Args:
        shot_id: 分镜 ID。
        body: 更新请求。
        db: 数据库会话。

    Returns:
        JSONResponse: 更新后的分镜。
    """
    shot = db.get(Shot, shot_id)
    if shot is None:
        raise BizError(CODE_NOT_FOUND, f"分镜 {shot_id} 不存在")
    data = body.model_dump(exclude_unset=True)
    if "dialogue" in data and data["dialogue"] is not None:
        data["dialogue"] = [d if isinstance(d, dict) else d.model_dump() for d in data["dialogue"]]
    for field, value in data.items():
        setattr(shot, field, value)
    db.commit()
    db.refresh(shot)
    return ok({"id": shot.id, "code": shot.code, "status": shot.status})


@router.delete("/api/shots/{shot_id}")
def delete_shot(shot_id: int, db: Session = Depends(get_db)):
    """删除分镜。

    Args:
        shot_id: 分镜 ID。
        db: 数据库会话。

    Returns:
        JSONResponse: 空数据成功响应。
    """
    shot = db.get(Shot, shot_id)
    if shot is None:
        raise BizError(CODE_NOT_FOUND, f"分镜 {shot_id} 不存在")
    db.query(GenerationTask).filter(
        GenerationTask.shot_id == shot_id,
        GenerationTask.type == TaskType.TEXT.value,
    ).update({"shot_id": None}, synchronize_session=False)
    db.delete(shot)
    db.commit()
    return ok(None, "deleted")
