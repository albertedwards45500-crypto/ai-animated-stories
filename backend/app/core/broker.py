# -*- coding: utf-8 -*-
"""Dramatiq broker 初始化。

- broker_kind=redis（默认）：使用 Redis broker，与 API 共享 REDIS_URL；
- broker_kind=stub：使用 StubBroker，任务同步执行，供 pytest 使用。

Dramatiq 要求在导入任何 actor 前完成 broker 设置。
"""
from __future__ import annotations

import dramatiq

from app.core.config import get_settings


def _setup_broker() -> dramatiq.Broker:
    """按配置初始化 broker。

    Returns:
        dramatiq.Broker: Redis 或 Stub broker 实例。
    """
    settings = get_settings()
    if settings.broker_kind in ("stub", "thread"):
        from dramatiq.brokers.stub import StubBroker

        return StubBroker()
    from dramatiq.brokers.redis import RedisBroker

    return RedisBroker(url=settings.redis_url)


broker = _setup_broker()
dramatiq.set_broker(broker)
