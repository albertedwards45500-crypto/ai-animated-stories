"""进程存活与依赖就绪检查，不向客户端暴露连接串或凭据。"""
import logging
import shutil

from fastapi import APIRouter, Depends
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.response import CODE_UNAVAILABLE, fail, ok
from app.models.base import Base

router = APIRouter(tags=["health"])
logger = logging.getLogger("ai_drama")


def check_queue() -> dict:
    settings = get_settings()
    if settings.broker_kind in ("stub", "thread"):
        return {"status": "up", "kind": settings.broker_kind}
    from redis import Redis
    try:
        with Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1) as redis:
            redis.ping()
        # Redis reachable does not prove a Dramatiq worker is consuming messages.
        return {"status": "up", "kind": "redis", "worker": "not_checked"}
    except Exception:
        return {"status": "down", "message": "任务队列不可用，请检查 Redis 和 Worker。"}


@router.get("/api/health/live")
def live():
    return ok({"service": "ai-drama", "status": "up"})


@router.get("/api/health")
def ready(db: Session = Depends(get_db)):
    checks = {}
    try:
        db.execute(text("SELECT 1"))
        missing = sorted(set(Base.metadata.tables) - set(inspect(db.connection()).get_table_names()))
        checks["database"] = {"status": "down", "message": "数据库表未初始化，请先运行数据库迁移。", "missing_tables": missing} if missing else {"status": "up"}
    except Exception as exc:
        db.rollback()
        logger.warning("Database readiness failed (%s)", type(exc).__name__)
        checks["database"] = {"status": "down", "message": "数据库连接失败，请检查数据库服务和连接配置。"}
    checks["queue"] = check_queue()
    checks["ffmpeg"] = {"status": "up" if shutil.which(get_settings().ffmpeg_executable) else "down"}
    if checks["ffmpeg"]["status"] == "down":
        checks["ffmpeg"]["message"] = "未找到 FFmpeg，请检查 FFMPEG_PATH。"
    up = all(check["status"] == "up" for check in checks.values())
    data = {"service": "ai-drama", "status": "up" if up else "down", "profile": get_settings().app_env, "checks": checks}
    return ok(data) if up else fail(CODE_UNAVAILABLE, "服务依赖尚未就绪", data)
