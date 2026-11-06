# -*- coding: utf-8 -*-
"""项目管理 API：/api/projects。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.enums import ProjectStatus, TaskStatus
from app.core.response import BizError, CODE_NOT_FOUND, CODE_STATE_CONFLICT, ok
from app.models.entities import Episode, GenerationTask, Project
from app.schemas.entities import ProjectCreate, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])


def get_project_or_404(db: Session, project_id: int) -> Project:
    """按 ID 获取项目，不存在抛 40401。

    Args:
        db: 数据库会话。
        project_id: 项目 ID。

    Returns:
        Project: 项目行。
    """
    project = db.get(Project, project_id)
    if project is None:
        raise BizError(CODE_NOT_FOUND, f"项目 {project_id} 不存在")
    return project


def _project_dict(db: Session, p: Project, with_stats: bool = False) -> dict:
    """序列化项目行。

    Args:
        db: 数据库会话。
        p: 项目行。
        with_stats: 是否附带剧集数统计。

    Returns:
        dict: 项目数据。
    """
    data = {
        "id": p.id, "name": p.name, "genre": p.genre, "audience": p.audience,
        "style_preset_id": p.style_preset_id, "world_rules": p.world_rules,
        "default_episode_duration": p.default_episode_duration,
        "description": p.description, "status": p.status,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
    if with_stats:
        data["episode_count"] = db.query(Episode).filter(Episode.project_id == p.id).count()
    return data


@router.post("")
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    """创建项目。

    Args:
        body: 项目创建请求。
        db: 数据库会话。

    Returns:
        JSONResponse: 统一成功响应，data 为新项目。
    """
    p = Project(
        name=body.name, genre=body.genre, audience=body.audience,
        style_preset_id=body.style_preset_id, world_rules=body.world_rules,
        default_episode_duration=body.default_episode_duration,
        description=body.description, status=ProjectStatus.ACTIVE.value,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return ok(_project_dict(db, p))


@router.get("")
def list_projects(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = None, db: Session = Depends(get_db),
):
    """项目列表（分页 + 关键字）。

    Args:
        page: 页码。
        page_size: 每页条数。
        keyword: 名称关键字。
        db: 数据库会话。

    Returns:
        JSONResponse: ``{total, items}``。
    """
    q = db.query(Project)
    if keyword:
        q = q.filter(Project.name.like(f"%{keyword}%"))
    total = q.count()
    items = q.order_by(Project.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return ok({"total": total, "items": [_project_dict(db, p, with_stats=True) for p in items]})


@router.get("/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)):
    """项目详情（含剧集数统计）。

    Args:
        project_id: 项目 ID。
        db: 数据库会话。

    Returns:
        JSONResponse: 项目数据。
    """
    p = get_project_or_404(db, project_id)
    return ok(_project_dict(db, p, with_stats=True))


@router.put("/{project_id}")
def update_project(project_id: int, body: ProjectUpdate, db: Session = Depends(get_db)):
    """更新项目（部分更新）。

    Args:
        project_id: 项目 ID。
        body: 更新请求。
        db: 数据库会话。

    Returns:
        JSONResponse: 更新后的项目。
    """
    p = get_project_or_404(db, project_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(p, field, value)
    db.commit()
    db.refresh(p)
    return ok(_project_dict(db, p, with_stats=True))


@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    """删除项目：存在进行中任务返回 40901。

    Args:
        project_id: 项目 ID。
        db: 数据库会话。

    Returns:
        JSONResponse: 空数据成功响应。
    """
    p = get_project_or_404(db, project_id)
    running = db.query(GenerationTask).filter(
        GenerationTask.project_id == project_id,
        GenerationTask.status.in_([TaskStatus.QUEUED.value, TaskStatus.PROCESSING.value]),
    ).count()
    if running:
        raise BizError(CODE_STATE_CONFLICT, f"项目存在 {running} 个进行中任务，请先取消任务")
    for ep in db.query(Episode).filter(Episode.project_id == project_id).all():
        db.delete(ep)
    db.delete(p)
    db.commit()
    return ok(None, "deleted")
