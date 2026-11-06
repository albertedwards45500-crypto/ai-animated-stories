# -*- coding: utf-8 -*-
"""统计 API：成本与调用量报表（阶段五）。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, literal_column
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.response import ok
from app.models.entities import GenerationTask

router = APIRouter(tags=["stats"])


@router.get("/api/stats/cost")
def cost_stats(project_id: int | None = Query(None), db: Session = Depends(get_db)):
    """按 provider/model 统计调用量、成功率、费用、平均耗时。

    Args:
        project_id: 项目过滤。
        db: 数据库会话。

    Returns:
        JSONResponse: 统计行数组。
    """
    if db.get_bind().dialect.name == "sqlite":
        elapsed_ms = (func.julianday(GenerationTask.finished_at) - func.julianday(GenerationTask.started_at)) * 86400000
    else:
        elapsed_ms = func.timestampdiff(literal_column("MICROSECOND"), GenerationTask.started_at, GenerationTask.finished_at) / 1000
    q = db.query(
        GenerationTask.provider,
        GenerationTask.model,
        func.count(GenerationTask.id).label("total_calls"),
        func.sum(case((GenerationTask.status == "succeeded", 1), else_=0)).label("succeeded"),
        func.sum(case((GenerationTask.status.in_(["failed", "timeout"]), 1), else_=0)).label("failed"),
        func.coalesce(func.sum(GenerationTask.cost), 0).label("total_cost"),
        func.avg(elapsed_ms).label("avg_elapsed_ms"),
    )
    if project_id is not None:
        q = q.filter(GenerationTask.project_id == project_id)
    rows = q.group_by(GenerationTask.provider, GenerationTask.model).all()
    items = []
    for r in rows:
        total = int(r.total_calls or 0)
        succeeded = int(r.succeeded or 0)
        avg_ms = r.avg_elapsed_ms
        items.append({
            "provider": r.provider or "-",
            "model": r.model or "-",
            "total_calls": total,
            "succeeded": succeeded,
            "failed": int(r.failed or 0),
            "success_rate": round(succeeded / total, 4) if total else 0,
            "total_cost": round(float(r.total_cost or 0), 4),
            "avg_elapsed_ms": round(float(avg_ms), 1) if avg_ms is not None else None,
        })
    return ok(items)
