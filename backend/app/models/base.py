# -*- coding: utf-8 -*-
"""SQLAlchemy 模型基类与公共混入。

所有表主键为 BIGINT 自增，均含 created_at / updated_at；
不使用物理外键（应用层维护引用，便于迁移）。
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


@compiles(BigInteger, "sqlite")
def sqlite_bigint(type_, compiler, **kw):
    """SQLite 的自增主键要求精确使用 INTEGER；MySQL 仍使用 BIGINT。"""
    return "INTEGER"


class Base(DeclarativeBase):
    """全局声明式基类。"""


class TimestampMixin:
    """created_at / updated_at 时间戳混入。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间"
    )
