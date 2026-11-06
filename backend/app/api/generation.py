# -*- coding: utf-8 -*-
"""AI 生成任务 API：统一发起入口、任务查询/取消/重试、SSE 进度。"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.config import get_settings
from app.core.enums import AssetType, ProviderMode, TaskStatus, TaskType
from app.core.response import BizError, CODE_NOT_FOUND, CODE_QUOTA_EXCEEDED, CODE_BIZ_INVALID, ok
from app.models.entities import (
    AudioTrack,
    Character,
    Episode,
    GenerationTask,
    GeneratedAsset,
    ProviderConfig,
    Scene,
    Shot,
)
from app.schemas.entities import (
    AsrRequest, GenerationAudioRequest, GenerationImageRequest,
    GenerationVideoRequest, StoryboardRequest,
)
from app.providers.registry import get_provider
from app.services import task_service
from app.services.task_runner import dispatch_task, _build_image_prompt, _frame_prompt
from app.services.character_consistency import shot_character_refs, validate_character_refs

router = APIRouter(prefix="/api/generation", tags=["generation"])


class CharacterImageRequest(BaseModel):
    provider: str | None = None
    confirm: bool = False
    variant_id: str | None = Field(None, min_length=1, max_length=64)
    params: dict = Field(default_factory=dict)


def get_task_or_404(db: Session, task_uuid: str) -> GenerationTask:
    """按 UUID 获取任务。

    Args:
        db: 数据库会话。
        task_uuid: 任务 UUID。

    Returns:
        GenerationTask: 任务行。
    """
    task = db.query(GenerationTask).filter(GenerationTask.uuid == task_uuid).first()
    if task is None:
        raise BizError(CODE_NOT_FOUND, f"任务 {task_uuid} 不存在")
    return task


def _task_dict(task: GenerationTask, with_outputs: bool = True) -> dict:
    """序列化任务行。

    Args:
        task: 任务行。
        with_outputs: 是否附带输出素材 ID。

    Returns:
        dict: 任务数据。
    """
    data = {
        "task_id": task.uuid, "type": task.type, "provider": task.provider,
        "model": task.model, "mode": task.mode, "status": task.status,
        "progress": task.progress, "error_message": task.error_message,
        "retry_count": task.retry_count, "cost": float(task.cost or 0),
        "shot_id": task.shot_id, "episode_id": task.episode_id, "project_id": task.project_id,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }
    if with_outputs:
        data["output_asset_ids"] = task.output_asset_ids or []
        data["request_payload"] = task.request_payload
        data["response_payload"] = task.response_payload
    return data


def _check_quota(db: Session, capability: str, provider: str) -> None:
    """检查每日额度，超限抛 42901。

    Args:
        db: 数据库会话。
        capability: 能力标识。
        provider: 供应商标识。

    Raises:
        BizError: 超出每日额度（42901）。
    """
    cfg = db.query(ProviderConfig).filter(
        ProviderConfig.capability == capability, ProviderConfig.provider == provider
    ).first()
    if cfg is None or not cfg.daily_quota:
        return
    today_start = datetime.combine(date.today(), datetime.min.time())
    used = db.query(GenerationTask).filter(
        GenerationTask.type == capability,
        GenerationTask.provider == provider,
        GenerationTask.created_at >= today_start,
        GenerationTask.mode != ProviderMode.REPLAY.value,
    ).count()
    if used >= cfg.daily_quota:
        raise BizError(CODE_QUOTA_EXCEEDED, f"供应商 {provider} 已达每日调用上限 {cfg.daily_quota}")


def _resolve_and_create(
    db: Session, *, capability: str, task_type: str, provider: str | None, mode: str | None,
    request_payload: dict | None, project_id: int | None,
    episode_id: int | None = None, shot_id: int | None = None,
) -> dict:
    """公共创建流程：解析 provider → 缓存检查 → 额度检查 → 落库 queued → 投递。

    Args:
        db: 数据库会话。
        capability: 能力标识。
        task_type: 任务类型。
        provider: 请求指定 provider。
        mode: 请求指定 mode。
        request_payload: 请求载荷。
        project_id: 项目 ID。
        episode_id: 剧集 ID。
        shot_id: 分镜 ID。

    Returns:
        dict: 受理结果（task_id/status/estimated_wait_s 或 require_confirm）。
    """
    settings = get_settings()
    final_mode = mode or settings.ai_mode
    final_provider = provider or getattr(settings, f"{capability}_provider", "mock")
    if settings.app_env == "mock" and capability in ("image", "video") and final_provider != "mock":
        raise BizError(CODE_BIZ_INVALID, "模拟环境只允许 Mock Provider，不会调用真实 AI API")
    if capability in ("image", "video") and final_provider == "mock":
        final_mode = ProviderMode.MOCK.value

    payload = dict(request_payload or {})
    payload.pop("confirm", None)

    # 参数哈希缓存优先：命中直接复用历史成功任务，不消费额度
    # （即使请求带 confirm 也不应绕过缓存重复扣费）
    key = task_service.compute_idempotency_key(project_id, task_type, final_provider, "default", payload)
    cached = task_service.find_cached_task(db, key)
    if cached is not None:
        return ok({"task_id": cached.uuid, "status": cached.status, "cached": True,
                   "estimated_wait_s": 0, "output_asset_ids": cached.output_asset_ids or []})

    # 真实调用确认（provider != mock 且未确认）
    if final_provider != "mock" and final_mode != ProviderMode.REPLAY.value:
        if not (request_payload or {}).get("confirm"):
            estimate = {"provider": final_provider, "mode": final_mode, "model": "default"}
            cfg = db.query(ProviderConfig).filter(
                ProviderConfig.capability == capability, ProviderConfig.provider == final_provider
            ).first()
            if cfg is not None and cfg.model:
                estimate["model"] = cfg.model
            return ok({"require_confirm": True, "estimate": estimate})

    _check_quota(db, capability, final_provider)

    task = task_service.create_task(
        db, project_id=project_id, task_type=task_type,
        provider=final_provider, mode=final_mode, model="default",
        request_payload=payload, episode_id=episode_id, shot_id=shot_id,
    )
    db.commit()
    dispatch_task(task.uuid)
    return ok({"task_id": task.uuid, "status": task.status, "estimated_wait_s": 3})


@router.post("/characters/{character_id}/image")
def generate_character_image(character_id: int, body: CharacterImageRequest, db: Session = Depends(get_db)):
    """根据角色卡创建单人设定图任务，成功后加入角色库。"""
    character = db.get(Character, character_id)
    if character is None:
        raise BizError(CODE_NOT_FOUND, f"角色 {character_id} 不存在")
    if character.confirmed:
        raise BizError(CODE_BIZ_INVALID, "角色卡已锁定，不能生成新的参考图")
    if not any([character.hair, character.face_features, character.body_shape,
                character.clothing, character.style_tokens]):
        raise BizError(CODE_BIZ_INVALID, "请先填写发型、五官、体型、服装等角色外观信息")
    if get_settings().app_env == "mock" and body.provider not in (None, "mock"):
        raise BizError(CODE_BIZ_INVALID, "模拟环境只允许 Mock Provider，不会调用真实 AI API")
    return _resolve_and_create(
        db, capability="image", task_type=TaskType.IMAGE.value,
        provider=body.provider, mode=None,
        request_payload={"character_id": character.id, "character_version": character.version,
                         "variant_id": body.variant_id or "default", "confirm": body.confirm,
                         "params": {"size": "1024*1024", **body.params}},
        project_id=character.project_id,
    )


@router.post("/image")
def generate_image(body: GenerationImageRequest, db: Session = Depends(get_db)):
    """生成关键帧。

    Args:
        body: 生成请求（shot_id/provider/params/confirm）。
        db: 数据库会话。

    Returns:
        JSONResponse: 任务受理结果。
    """
    shot = db.get(Shot, body.shot_id)
    if shot is None:
        raise BizError(CODE_NOT_FOUND, f"分镜 {body.shot_id} 不存在")
    project_id = _project_of(db, shot)
    provider_name = body.provider or get_settings().image_provider
    if get_settings().app_env == "mock" and provider_name != "mock":
        raise BizError(CODE_BIZ_INVALID, "模拟环境只允许 Mock Provider，不会调用真实 AI API")
    refs = shot_character_refs(db, project_id, shot.character_ids or [],
                               require_ready=bool(shot.character_ids) and provider_name != "mock")
    prompt = _build_image_prompt(db, shot)
    return _resolve_and_create(
        db, capability="image", task_type=TaskType.IMAGE.value,
        provider=body.provider, mode=None,
        request_payload={"shot_id": shot.id, "params": body.params or {}, "confirm": body.confirm,
                         "character_refs": refs, "prompt": prompt},
        project_id=project_id, shot_id=shot.id,
        episode_id=shot.episode_id,
    )


@router.post("/video")
def generate_video(body: GenerationVideoRequest, db: Session = Depends(get_db)):
    """生成视频片段。

    Args:
        body: 生成请求。
        db: 数据库会话。

    Returns:
        JSONResponse: 任务受理结果。
    """
    shot = db.get(Shot, body.shot_id)
    if shot is None:
        raise BizError(CODE_NOT_FOUND, f"分镜 {body.shot_id} 不存在")
    project_id = _project_of(db, shot)
    provider_name = body.provider or get_settings().video_provider
    if get_settings().app_env == "mock" and provider_name != "mock":
        raise BizError(CODE_BIZ_INVALID, "模拟环境只允许 Mock Provider，不会调用真实 AI API")
    if provider_name == "dashscope" and not 2 <= int(float(shot.duration or 5)) <= 30:
        raise BizError(CODE_BIZ_INVALID, "万相3.0单段视频时长需在 2 到 30 秒之间，请调整或拆分分镜")
    refs = shot_character_refs(db, project_id, shot.character_ids or [],
                               require_ready=bool(shot.character_ids) and provider_name != "mock")
    if provider_name != "mock" and not shot.keyframe_asset_id:
        raise BizError(CODE_BIZ_INVALID, "请先用已锁定角色生成关键帧，再生成视频")
    if provider_name != "mock" and shot.keyframe_asset_id:
        validate_character_refs(db, refs)
        keyframe = db.get(GeneratedAsset, shot.keyframe_asset_id)
        if keyframe is None or (keyframe.meta_json or {}).get("character_refs") != refs:
            raise BizError(CODE_BIZ_INVALID, "当前关键帧与分镜角色版本不一致，请重新生成关键帧")
        if not (get_settings().media_root_path / keyframe.file_path).is_file():
            raise BizError(CODE_BIZ_INVALID, "关键帧文件已丢失，请重新生成关键帧")
    movement = _frame_prompt(shot)
    return _resolve_and_create(
        db, capability="video", task_type=TaskType.VIDEO.value,
        provider=body.provider, mode=None,
        request_payload={"shot_id": shot.id, "params": body.params or {}, "confirm": body.confirm,
                         "character_refs": refs, "keyframe_asset_id": shot.keyframe_asset_id,
                         "prompt": movement, "duration": int(float(shot.duration or 5))},
        project_id=project_id, shot_id=shot.id, episode_id=shot.episode_id,
    )


@router.post("/audio")
def generate_audio(body: GenerationAudioRequest, db: Session = Depends(get_db)):
    """生成对白语音：创建/绑定音频轨并发起生成任务。

    Args:
        body: 生成请求（含 audio_track 参数）。
        db: 数据库会话。

    Returns:
        JSONResponse: 任务受理结果。
    """
    shot = db.get(Shot, body.shot_id)
    if shot is None:
        raise BizError(CODE_NOT_FOUND, f"分镜 {body.shot_id} 不存在")
    at = body.audio_track or {}
    if not isinstance(at.get("text"), str) or not at["text"].strip():
        raise BizError(CODE_BIZ_INVALID, "请先填写语音文本")
    return _resolve_and_create(
        db, capability="audio", task_type=TaskType.AUDIO.value,
        provider=body.provider, mode=None,
        request_payload={"shot_id": shot.id, "audio_track": at, "confirm": body.confirm},
        project_id=_project_of(db, shot), shot_id=shot.id, episode_id=shot.episode_id,
    )


@router.post("/asr")
def generate_asr(body: AsrRequest, db: Session = Depends(get_db)):
    """字幕识别（ASR）：为剧集音频轨生成字幕。

    Args:
        body: ASR 请求。
        db: 数据库会话。

    Returns:
        JSONResponse: 任务受理结果。
    """
    ep = db.get(Episode, body.episode_id)
    if ep is None:
        raise BizError(CODE_NOT_FOUND, f"剧集 {body.episode_id} 不存在")
    tracks = db.query(AudioTrack).filter(
        AudioTrack.episode_id == ep.id, AudioTrack.asset_id.isnot(None),
        AudioTrack.track_type.in_(["dialogue", "narration"]),
    )
    requested = set(body.audio_track_ids)
    if requested:
        tracks = tracks.filter(AudioTrack.id.in_(requested))
    tracks = tracks.order_by(AudioTrack.id).all()
    if not tracks or (requested and requested != {t.id for t in tracks}):
        raise BizError(CODE_BIZ_INVALID, "请先生成本剧集的对白语音，再生成字幕")
    return _resolve_and_create(
        db, capability="asr", task_type=TaskType.ASR.value,
        provider=body.provider, mode=None,
        request_payload={"episode_id": ep.id, "audio_track_ids": [t.id for t in tracks],
                         "audio_asset_ids": [t.asset_id for t in tracks], "confirm": body.confirm},
        project_id=ep.project_id, episode_id=ep.id,
    )


def _project_of(db: Session, shot: Shot) -> int | None:
    """由分镜反查项目 ID。

    Args:
        db: 数据库会话。
        shot: 分镜行。

    Returns:
        int | None: 项目 ID。
    """
    ep = db.get(Episode, shot.episode_id)
    return ep.project_id if ep else None


@router.post("/shots/{shot_id}/storyboard", include_in_schema=False)
def generate_storyboard_legacy(shot_id: int, db: Session = Depends(get_db)):
    """兼容路径（旧文档）：分镜提示词生成。

    Args:
        shot_id: 分镜 ID。
        db: 数据库会话。

    Returns:
        JSONResponse: 任务受理结果。
    """
    return generate_storyboard(shot_id, StoryboardRequest(), db)


@router.post("/storyboard/{shot_id}")
def generate_storyboard(shot_id: int, body: StoryboardRequest, db: Session = Depends(get_db)):
    """生成/更新分镜提示词（visual_prompt），Mock 可用。

    Args:
        shot_id: 分镜 ID。
        body: 请求。
        db: 数据库会话。

    Returns:
        JSONResponse: 任务受理结果。
    """
    shot = db.get(Shot, shot_id)
    if shot is None:
        raise BizError(CODE_NOT_FOUND, f"分镜 {shot_id} 不存在")
    return _resolve_and_create(
        db, capability="text", task_type=TaskType.TEXT.value,
        provider=body.provider, mode=None,
        request_payload={"storyboard": True, "shot_id": shot.id, "confirm": body.confirm},
        project_id=_project_of(db, shot), shot_id=shot.id, episode_id=shot.episode_id,
    )


# ---------- 任务查询与控制 ----------
@router.get("/tasks/{task_uuid}")
def get_task(task_uuid: str, db: Session = Depends(get_db)):
    """任务查询：状态、进度、错误、输出素材。

    Args:
        task_uuid: 任务 UUID。
        db: 数据库会话。

    Returns:
        JSONResponse: 任务数据。
    """
    task = get_task_or_404(db, task_uuid)
    return ok(_task_dict(task))


@router.post("/tasks/{task_uuid}/cancel")
def cancel_task(task_uuid: str, db: Session = Depends(get_db)):
    """取消任务：queued/processing 可取消，终态返回 40901。

    Args:
        task_uuid: 任务 UUID。
        db: 数据库会话。

    Returns:
        JSONResponse: 取消后的任务。
    """
    task = get_task_or_404(db, task_uuid)
    task_service.cancel_task(db, task)
    db.refresh(task)
    return ok(_task_dict(task))


@router.post("/tasks/{task_uuid}/retry")
def retry_task(task_uuid: str, db: Session = Depends(get_db)):
    """重试任务：failed/timeout/cancelled 可重试，retry_count+1。

    Args:
        task_uuid: 任务 UUID。
        db: 数据库会话。

    Returns:
        JSONResponse: 重置为 queued 的任务。
    """
    task = get_task_or_404(db, task_uuid)
    task_service.retry_task(db, task)
    db.refresh(task)
    dispatch_task(task.uuid)
    return ok(_task_dict(task))


@router.get("/tasks/{task_uuid}/events")
async def task_events(task_uuid: str, request: Request, db: Session = Depends(get_db)):
    """任务进度 SSE：progress/status/error 事件 + 15s 心跳 + Last-Event-ID 续传。

    Args:
        task_uuid: 任务 UUID。
        request: 请求对象（读取 Last-Event-ID）。
        db: 数据库会话。

    Returns:
        StreamingResponse: text/event-stream。
    """
    task = get_task_or_404(db, task_uuid)
    last_event_id = request.headers.get("last-event-id")

    async def event_stream():
        """SSE 事件生成器。

        Yields:
            str: SSE 帧文本。
        """
        last_progress = int(last_event_id) if last_event_id and last_event_id.isdigit() else -1
        last_sent_status = None
        heartbeat_at = time.time()
        while True:
            if await request.is_disconnected():
                return
            # End the previous read transaction so MySQL REPEATABLE READ and
            # the identity map cannot retain an old processing snapshot.
            db.rollback()
            db.expire_all()
            task = get_task_or_404(db, task_uuid)
            if task.progress != last_progress or task.status != last_sent_status:
                last_progress = task.progress
                last_sent_status = task.status
                if task.status in (TaskStatus.QUEUED.value, TaskStatus.PROCESSING.value):
                    yield _sse("progress", {"task_id": task.uuid, "status": task.status,
                                            "progress": task.progress}, event_id=str(task.progress))
                elif task.status == TaskStatus.SUCCEEDED.value:
                    yield _sse("status", {"task_id": task.uuid, "status": task.status,
                                          "progress": 100, "output_asset_ids": task.output_asset_ids or []})
                    return
                else:
                    yield _sse("error", {"task_id": task.uuid, "status": task.status,
                                         "error_message": task.error_message})
                    return
            if time.time() - heartbeat_at >= 15:
                heartbeat_at = time.time()
                yield ": ping\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(event: str, data: dict, event_id: str | None = None) -> str:
    """格式化 SSE 帧。

    Args:
        event: 事件类型。
        data: 事件数据。
        event_id: 事件 ID（用于 Last-Event-ID 续传）。

    Returns:
        str: SSE 帧文本。
    """
    id_part = f"id: {event_id}\n" if event_id else ""
    return f"{id_part}event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


project_tasks_router = APIRouter(tags=["generation"])


@project_tasks_router.get("/api/projects/{project_id}/generation/tasks")
def list_project_tasks(
    project_id: int,
    status: str | None = Query(None), type: str | None = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """项目维度任务列表（任务中心数据源）。

    Args:
        project_id: 项目 ID。
        status: 状态过滤。
        type: 类型过滤。
        page: 页码。
        page_size: 每页条数。
        db: 数据库会话。

    Returns:
        JSONResponse: ``{total, items}``。
    """
    q = db.query(GenerationTask).filter(GenerationTask.project_id == project_id)
    if status:
        q = q.filter(GenerationTask.status == status)
    if type:
        q = q.filter(GenerationTask.type == type)
    total = q.count()
    items = q.order_by(GenerationTask.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return ok({"total": total, "items": [_task_dict(t) for t in items]})
