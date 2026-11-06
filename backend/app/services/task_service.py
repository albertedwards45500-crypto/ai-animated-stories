# -*- coding: utf-8 -*-
"""生成任务服务：状态机、参数哈希缓存、任务创建与生命周期管理。

核心约束（贯穿所有阶段）：
- 所有生成任务先持久化为 queued，再投递 Dramatiq 队列；
- 请求/响应/耗时/费用/retry_count 全部落库；
- 参数哈希命中缓存直接返回历史任务；
- 取消仅允许 queued/processing；重试仅允许终态。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import TaskStatus
from app.core.response import BizError, CODE_STATE_CONFLICT
from app.models.entities import GenerationTask, RenderJob
from app.providers.base import new_uuid

# 服务重启后 processing 超过该秒数视为僵死任务
STALE_PROCESSING_SECONDS = 600


def canonical_payload(*parts: Any) -> str:
    """构造稳定序列化字符串（用于参数哈希）。

    Args:
        parts: 任意参与哈希的部件。

    Returns:
        str: 排序键后的稳定 JSON 字符串。
    """
    return json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)


def compute_idempotency_key(
    project_id: int | None, task_type: str, provider: str, model: str, request_payload: dict | None
) -> str:
    """计算参数哈希缓存键。

    Args:
        project_id: 项目 ID。
        task_type: 任务类型。
        provider: 供应商标识。
        model: 模型名。
        request_payload: 请求载荷。

    Returns:
        str: 64 位 SHA-256 十六进制哈希。
    """
    raw = canonical_payload(project_id, task_type, provider, model, request_payload)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def find_cached_task(db: Session, idempotency_key: str) -> GenerationTask | None:
    """查找参数哈希命中的成功任务（缓存复用）。

    Args:
        db: 数据库会话。
        idempotency_key: 参数哈希。

    Returns:
        GenerationTask | None: 最近一次同参数成功任务。
    """
    return (
        db.query(GenerationTask)
        .filter(
            GenerationTask.idempotency_key == idempotency_key,
            GenerationTask.status == TaskStatus.SUCCEEDED.value,
        )
        .order_by(GenerationTask.id.desc())
        .first()
    )


def create_task(
    db: Session,
    *,
    project_id: int | None,
    task_type: str,
    provider: str,
    mode: str,
    model: str,
    request_payload: dict | None,
    episode_id: int | None = None,
    shot_id: int | None = None,
) -> GenerationTask:
    """创建任务并落库为 queued（不投递队列，投递由调用方完成）。

    Args:
        db: 数据库会话（调用方负责提交）。
        project_id: 项目 ID。
        task_type: 任务类型（text/image/video/audio/asr/render）。
        provider: 供应商标识。
        mode: 运行模式（mock/record/replay）。
        model: 模型名。
        request_payload: 请求快照（须已脱敏）。
        episode_id: 关联剧集。
        shot_id: 关联分镜。

    Returns:
        GenerationTask: queued 状态的任务行。
    """
    key = compute_idempotency_key(project_id, task_type, provider, model, request_payload)
    task = GenerationTask(
        uuid=new_uuid(),
        project_id=project_id,
        episode_id=episode_id,
        shot_id=shot_id,
        type=task_type,
        provider=provider,
        model=model,
        mode=mode,
        status=TaskStatus.QUEUED.value,
        progress=0,
        request_payload=request_payload,
        idempotency_key=key,
    )
    db.add(task)
    db.flush()
    return task


def _sync_render_job(db: Session, task: GenerationTask) -> None:
    if task.type == "render":
        db.query(RenderJob).filter(RenderJob.task_id == task.id).update({
            "status": task.status, "error_message": task.error_message,
        }, synchronize_session="fetch")


def mark_processing(db: Session, task: GenerationTask) -> bool:
    """任务进入 processing 状态。

    Args:
        db: 数据库会话。
        task: 目标任务。
    """
    attempt = getattr(task, "_attempt_retry_count", task.retry_count or 0)
    claimed = db.query(GenerationTask).filter(
        GenerationTask.id == task.id, GenerationTask.status == TaskStatus.QUEUED.value,
        GenerationTask.retry_count == attempt,
    ).update({"status": TaskStatus.PROCESSING.value, "started_at": datetime.now(), "progress": 1}, synchronize_session=False)
    db.refresh(task, ["status", "retry_count"])
    if claimed:
        _sync_render_job(db, task)
    db.commit()
    return bool(claimed)


def mark_progress(db: Session, task: GenerationTask, progress: int) -> None:
    """更新任务进度（0~100）。

    Args:
        db: 数据库会话。
        task: 目标任务。
        progress: 进度值。

    Raises:
        TaskCancelledError: 任务已被取消时抛出，worker 据此中止。
    """
    attempt = getattr(task, "_attempt_retry_count", task.retry_count or 0)
    db.refresh(task, ["status", "retry_count"])
    if task.retry_count != attempt or task.status != TaskStatus.PROCESSING.value:
        raise TaskCancelledError(task.uuid)
    task.progress = min(100, max(task.progress, progress))
    db.commit()


def finish_task(
    db: Session,
    task: GenerationTask,
    *,
    status: str,
    response_payload: dict | None = None,
    error_message: str | None = None,
    cost: float = 0.0,
) -> None:
    """任务落终态（succeeded/failed/timeout/cancelled）。

    Args:
        db: 数据库会话。
        task: 目标任务。
        status: 终态值。
        response_payload: 响应快照。
        error_message: 错误信息。
        cost: 费用（元）。
    """
    attempt = getattr(task, "_attempt_retry_count", task.retry_count or 0)
    db.refresh(task, ["status", "retry_count"])
    if task.retry_count != attempt or task.status == TaskStatus.QUEUED.value:
        return
    if task.status == TaskStatus.CANCELLED.value:
        status = TaskStatus.CANCELLED.value
        error_message = "cancelled by user"
    task.status = status
    task.finished_at = datetime.now()
    if status == TaskStatus.SUCCEEDED.value:
        task.progress = 100
    if response_payload is not None:
        task.response_payload = response_payload
    if error_message is not None:
        task.error_message = error_message
    task.cost = round(float(task.cost or 0) + float(cost), 4)
    _sync_render_job(db, task)
    db.commit()


def cancel_task(db: Session, task: GenerationTask) -> GenerationTask:
    """取消任务：仅 queued/processing 可取消，终态返回 40901。

    Args:
        db: 数据库会话。
        task: 目标任务。

    Returns:
        GenerationTask: 取消后的任务。

    Raises:
        BizError: 任务已处于终态（40901）。
    """
    changed = db.query(GenerationTask).filter(
        GenerationTask.id == task.id,
        GenerationTask.status.in_([TaskStatus.QUEUED.value, TaskStatus.PROCESSING.value]),
    ).update({
        "status": TaskStatus.CANCELLED.value,
        "finished_at": datetime.now(),
        "error_message": "cancelled by user",
    }, synchronize_session=False)
    if not changed:
        db.refresh(task)
        raise BizError(CODE_STATE_CONFLICT, f"任务已是终态 {task.status}，无法取消")
    db.refresh(task)
    _sync_render_job(db, task)
    db.commit()
    db.refresh(task)
    return task


def retry_task(db: Session, task: GenerationTask) -> GenerationTask:
    """重试任务：仅 failed/timeout/cancelled 可重试，retry_count+1 重新入队。

    Args:
        db: 数据库会话。
        task: 目标任务。

    Returns:
        GenerationTask: 重置为 queued 的任务。

    Raises:
        BizError: 任务未处于可重试终态（40901）。
    """
    retryable = [TaskStatus.FAILED.value, TaskStatus.TIMEOUT.value, TaskStatus.CANCELLED.value]
    changed = db.query(GenerationTask).filter(
        GenerationTask.id == task.id, GenerationTask.status.in_(retryable),
    ).update({
        "status": TaskStatus.QUEUED.value,
        "progress": 0,
        "retry_count": GenerationTask.retry_count + 1,
        "error_message": None,
        "finished_at": None,
        "started_at": None,
    }, synchronize_session=False)
    if not changed:
        db.refresh(task)
        raise BizError(CODE_STATE_CONFLICT, f"任务状态 {task.status} 不可重试")
    db.refresh(task)
    _sync_render_job(db, task)
    db.commit()
    db.refresh(task)
    return task


def recover_stale_tasks(db: Session) -> int:
    """服务启动恢复：将僵死 processing 任务标记为 failed。

    按 PRD 4.2.5：服务重启后 queued/processing 任务按策略标记为 failed
    或自动重新入队。queued 消息仍在 Redis 中可被重新消费，不处理；
    processing 超过阈值视为僵死，标记 failed 供用户重试。

    Args:
        db: 数据库会话。

    Returns:
        int: 被恢复（标记 failed）的任务数。
    """
    now = datetime.now()
    local = get_settings().broker_kind == "thread"
    states = [TaskStatus.PROCESSING.value, TaskStatus.QUEUED.value] if local else [TaskStatus.PROCESSING.value]
    stale = (
        db.query(GenerationTask)
        .filter(GenerationTask.status.in_(states))
        .all()
    )
    count = 0
    for task in stale:
        started = task.started_at or task.updated_at
        if local or started is None or (now - started).total_seconds() > STALE_PROCESSING_SECONDS:
            task.status = TaskStatus.FAILED.value
            task.finished_at = now
            task.error_message = "task interrupted by service restart, please retry"
            _sync_render_job(db, task)
            count += 1
    if count:
        db.commit()
    return count


class TaskCancelledError(Exception):
    """任务被用户取消时由进度回调抛出。

    Attributes:
        task_uuid: 被取消的任务 UUID。
    """

    def __init__(self, task_uuid: str):
        """初始化取消异常。

        Args:
            task_uuid: 任务 UUID。
        """
        self.task_uuid = task_uuid
        super().__init__(f"task {task_uuid} cancelled")


def get_media_settings():
    """获取全局配置（媒体路径/FFmpeg 等）。

    Returns:
        Settings: 配置对象。
    """
    return get_settings()
