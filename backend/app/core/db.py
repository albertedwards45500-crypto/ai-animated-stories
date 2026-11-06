# -*- coding: utf-8 -*-
"""数据库连接与会话管理。

提供 SQLAlchemy 2.x 引擎与请求级 Session 依赖注入；
Alembic 迁移与 Dramatiq Worker 复用同一配置。
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.sqlalchemy_url,
    connect_args={"check_same_thread": False, "timeout": 30} if settings.sqlalchemy_url.startswith("sqlite:") else {"connect_timeout": 3},
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：请求级数据库会话。

    Yields:
        Session: SQLAlchemy 会话，请求结束自动关闭。
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
