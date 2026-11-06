# -*- coding: utf-8 -*-
"""成片渲染 API：发起合成、查询、预览、下载。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.enums import TaskStatus
from app.core.response import BizError, CODE_NOT_FOUND, ok
from app.models.entities import Episode, GeneratedAsset, GenerationTask, RenderJob
from app.schemas.entities import RenderJobCreate
from app.services import render_service, task_service
from app.services.task_runner import dispatch_task
from app.providers.base import new_uuid

router = APIRouter(prefix="/api/render", tags=["render"])


def _job_dict(db: Session, job: RenderJob) -> dict:
    """序列化渲染任务行。

    Args:
        db: 数据库会话。
        job: 渲染任务行。

    Returns:
        dict: 渲染任务数据。
    """
    task = db.get(GenerationTask, job.task_id)
    return {
        "job_id": job.uuid, "episode_id": job.episode_id, "task_id": task.uuid if task else None,
        "status": job.status, "progress": task.progress if task else 0,
        "output_asset_id": job.output_asset_id, "subtitle_burn_in": bool(job.subtitle_burn_in),
        "error_message": job.error_message or task.error_message if task else job.error_message,
        "preview_url": f"/api/render/jobs/{job.uuid}/preview",
        "download_url": f"/api/render/jobs/{job.uuid}/download",
    }


@router.post("/jobs")
def create_render_job(body: RenderJobCreate, db: Session = Depends(get_db)):
    """发起合成：先校验（缺视频素材/字幕越界返回 40002），再落库 queued 并投递。

    Args:
        body: 合成请求。
        db: 数据库会话。

    Returns:
        JSONResponse: job_id / task_id / status。
    """
    ep = db.get(Episode, body.episode_id)
    if ep is None:
        raise BizError(CODE_NOT_FOUND, f"剧集 {body.episode_id} 不存在")
    # 合成前校验（素材/时长/字幕）
    context = render_service.validate_episode_for_render(db, body.episode_id)

    task = task_service.create_task(
        db, project_id=ep.project_id, task_type="render",
        provider="local", mode="mock", model="ffmpeg",
        request_payload={
            "episode_id": ep.id, "subtitle_burn_in": body.subtitle_burn_in,
            "subtitle_style": body.subtitle_style or {},
            "audio": body.audio or {}, "plan": context["plan"],
        },
        episode_id=ep.id,
    )
    job = RenderJob(
        uuid=new_uuid(), episode_id=ep.id, task_id=task.id,
        plan_json={"subtitle_style": body.subtitle_style or {}, "audio": body.audio or {}},
        subtitle_burn_in=1 if body.subtitle_burn_in else 0,
        status=TaskStatus.QUEUED.value,
    )
    db.add(job)
    db.commit()
    dispatch_task(task.uuid)
    return ok({"job_id": job.uuid, "task_id": task.uuid, "status": job.status})


@router.get("/jobs/{job_id}")
def get_render_job(job_id: str, db: Session = Depends(get_db)):
    """查询渲染任务状态与输出。

    Args:
        job_id: 渲染任务 UUID。
        db: 数据库会话。

    Returns:
        JSONResponse: 渲染任务数据。
    """
    job = _get_job_or_404(db, job_id)
    return ok(_job_dict(db, job))


@router.get("/jobs/{job_id}/preview")
def preview_render_job(job_id: str, db: Session = Depends(get_db)):
    """预览成片：302 跳转到成片文件流。

    Args:
        job_id: 渲染任务 UUID。
        db: 数据库会话。

    Returns:
        RedirectResponse: 跳转到 /api/assets/{id}/raw。
    """
    job = _get_job_or_404(db, job_id)
    if not job.output_asset_id:
        raise BizError(CODE_NOT_FOUND, "成片尚未生成")
    return RedirectResponse(url=f"/api/assets/{job.output_asset_id}/raw", status_code=302)


@router.get("/jobs/{job_id}/download")
def download_render_job(job_id: str, db: Session = Depends(get_db)):
    """下载成片（Content-Disposition 附件）。

    Args:
        job_id: 渲染任务 UUID。
        db: 数据库会话。

    Returns:
        FileResponse: 附件下载。
    """
    job = _get_job_or_404(db, job_id)
    if not job.output_asset_id:
        raise BizError(CODE_NOT_FOUND, "成片尚未生成")
    asset = db.get(GeneratedAsset, job.output_asset_id)
    path = _media_root() / asset.file_path
    if not path.exists():
        raise BizError(CODE_NOT_FOUND, f"成片文件缺失: {asset.file_path}")
    return FileResponse(path, media_type="video/mp4",
                        filename=f"episode_{job.episode_id}_{job.uuid[:8]}.mp4",
                        headers={"Content-Disposition": f'attachment; filename="render_{job.uuid[:8]}.mp4"'})


@router.get("/episodes/{episode_id}/jobs")
def list_episode_jobs(episode_id: int, db: Session = Depends(get_db)):
    """剧集的渲染任务列表。

    Args:
        episode_id: 剧集 ID。
        db: 数据库会话。

    Returns:
        JSONResponse: 渲染任务数组。
    """
    jobs = db.query(RenderJob).filter(RenderJob.episode_id == episode_id).order_by(RenderJob.id.desc()).all()
    return ok([_job_dict(db, j) for j in jobs])


def _get_job_or_404(db: Session, job_id: str) -> RenderJob:
    """按 UUID 获取渲染任务。

    Args:
        db: 数据库会话。
        job_id: 渲染任务 UUID。

    Returns:
        RenderJob: 渲染任务行。
    """
    job = db.query(RenderJob).filter(RenderJob.uuid == job_id).first()
    if job is None:
        raise BizError(CODE_NOT_FOUND, f"渲染任务 {job_id} 不存在")
    return job


def _media_root() -> Path:
    """获取媒体根目录。

    Returns:
        Path: 媒体根目录。
    """
    from app.core.config import get_settings
    return get_settings().media_root_path
