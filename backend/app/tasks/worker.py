# -*- coding: utf-8 -*-
"""Dramatiq Worker 入口与任务 Actor。

启动方式（backend 目录）：
    dramatiq app.tasks --processes 2 --threads 4

broker 由 app.core.broker 模块初始化（redis 或 stub）。
"""
from __future__ import annotations

import dramatiq

from app.core.broker import broker  # noqa: F401 - 导入即完成 broker 初始化
from app.services.task_runner import run_task


@dramatiq.actor(max_retries=0, time_limit=3600_000)
def process_generation_task(task_uuid: str) -> None:
    """生成任务 Actor：执行完整状态机流转。

    max_retries=0：重试由任务中心的 retry 接口显式控制（retry_count+1），
    不由 broker 自动重试，避免重复消费。

    Args:
        task_uuid: 任务 UUID。
    """
    run_task(task_uuid)
