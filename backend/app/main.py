# -*- coding: utf-8 -*-
"""FastAPI 应用入口：路由注册、统一异常处理、启动恢复。"""
from __future__ import annotations

import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.core.response import (
    BizError,
    CODE_INTERNAL,
    CODE_PARAM_INVALID,
    CODE_UNAVAILABLE,
    fail,
)

logger = logging.getLogger("ai_drama")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时恢复僵死任务（PRD 4.2.5）。

    Args:
        app: FastAPI 实例。

    Yields:
        None。
    """
    from app.core.db import SessionLocal
    from app.services.task_service import recover_stale_tasks

    try:
        with SessionLocal() as db:
            count = recover_stale_tasks(db)
        if count:
            logger.warning("恢复 %d 个僵死任务为 failed", count)
    except Exception as exc:  # noqa: BLE001 - 启动恢复失败不阻断服务
        logger.error("启动恢复失败 (%s)，请检查依赖就绪状态", type(exc).__name__)
    try:
        yield
    finally:
        from app.services.task_runner import shutdown_local_tasks
        await asyncio.to_thread(shutdown_local_tasks)


app = FastAPI(title="AI 漫剧生产系统", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5188", "http://127.0.0.1:5188"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(BizError)
async def biz_error_handler(request: Request, exc: BizError) -> JSONResponse:
    """业务异常 → 统一错误响应。

    Args:
        request: 请求。
        exc: 业务异常。

    Returns:
        JSONResponse: 统一错误结构。
    """
    return fail(exc.code, exc.message, exc.data)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """参数校验异常 → 40001 统一错误响应。

    Args:
        request: 请求。
        exc: 校验异常。

    Returns:
        JSONResponse: 40001 错误结构。
    """
    errors = [
        {"field": ".".join(str(x) for x in e.get("loc", [])), "reason": e.get("msg", "")}
        for e in exc.errors()
    ]
    return fail(CODE_PARAM_INVALID, "参数校验失败", {"errors": errors})


@app.exception_handler(Exception)
async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """未捕获异常 → 50001 统一错误响应。

    Args:
        request: 请求。
        exc: 任意异常。

    Returns:
        JSONResponse: 50001 错误结构。
    """
    logger.exception("未处理异常: %s", exc)
    return fail(CODE_INTERNAL, "服务器内部错误")


@app.exception_handler(OperationalError)
async def database_unavailable_handler(request: Request, exc: OperationalError) -> JSONResponse:
    logger.warning("Database unavailable (%s)", type(exc).__name__)
    return fail(CODE_UNAVAILABLE, "数据库暂不可用，请检查服务状态和数据库迁移")


# 路由注册
from app.api import assets, episodes, generation, health, projects, provider_configs, render, settings, stats  # noqa: E402

app.include_router(health.router)
app.include_router(projects.router)
app.include_router(episodes.router)
app.include_router(settings.router)
app.include_router(generation.router)
app.include_router(generation.project_tasks_router)
app.include_router(assets.router)
app.include_router(render.router)
app.include_router(provider_configs.router)
app.include_router(stats.router)
