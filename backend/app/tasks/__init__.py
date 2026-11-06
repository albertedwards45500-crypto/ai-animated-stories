# -*- coding: utf-8 -*-
"""Dramatiq tasks 包：导入以注册全部 Actor。

`dramatiq app.tasks` 启动时会导入本包，必须在此显式导入 worker 模块。
"""
from app.tasks.worker import process_generation_task  # noqa: F401
