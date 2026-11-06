# -*- coding: utf-8 -*-
"""pytest 公共夹具：SQLite 内存库 + stub broker + TestClient。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# 必须在导入 app 之前设置环境变量（get_settings 使用 lru_cache）
_TMP_MEDIA = tempfile.mkdtemp(prefix="ai_drama_test_media_")
os.environ.update({
    "BROKER_KIND": "stub", "MEDIA_ROOT": _TMP_MEDIA, "AI_MODE": "mock",
    "DATABASE_URL": "sqlite://", "MOCK_DEFAULT_SCENARIO": "success",
    "TEXT_PROVIDER": "mock", "IMAGE_PROVIDER": "mock", "VIDEO_PROVIDER": "mock", "AUDIO_PROVIDER": "mock",
})
_FFMPEG = Path(__file__).resolve().parents[2] / "tools" / "ffmpeg.exe"
if _FFMPEG.is_file():
    os.environ["FFMPEG_PATH"] = str(_FFMPEG)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.models.base import Base as ModelBase  # noqa: E402
from app.models import entities  # noqa: F401,E402
import app.core.db as core_db  # noqa: E402


@pytest.fixture(autouse=True)
def fast_mock(monkeypatch):
    from app.providers import mock
    monkeypatch.setattr(mock, "STEP_INTERVAL", 0)

@pytest.fixture(scope="session")
def test_engine():
    """会话级 SQLite 内存引擎。

    Yields:
        Engine: SQLite 引擎。
    """
    # 预置 Mock 素材（假文件即可：登记流程只复制与校验和，不探测内容）
    for sub, names in {
        "images": ["m1.png", "m2.png"],
        "video": ["clip.mp4"],
        "audio": ["v1.wav", "v2.wav"],
        "subtitles": ["s.srt"],
    }.items():
        d = Path(_TMP_MEDIA) / "mock" / sub
        d.mkdir(parents=True, exist_ok=True)
        for n in names:
            (d / n).write_bytes(b"fake-" + n.encode())
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ModelBase.metadata.create_all(engine)
    yield engine


@pytest.fixture()
def db_session(test_engine):
    """函数级数据库会话（每测试前清空全部数据）。

    Args:
        test_engine: SQLite 引擎。

    Yields:
        Session: 会话。
    """
    TestingSession = sessionmaker(bind=test_engine, expire_on_commit=False)
    session = TestingSession()
    # 清空数据（保留表结构）
    for table in reversed(ModelBase.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()
    # 让 app.core.db.SessionLocal 指向测试会话工厂（task_runner 内部使用）
    original = core_db.SessionLocal
    core_db.SessionLocal = TestingSession
    yield session
    session.close()
    core_db.SessionLocal = original


@pytest.fixture()
def client(db_session):
    """TestClient：覆盖 get_db 依赖。

    Args:
        db_session: 测试会话。

    Yields:
        TestClient: FastAPI 测试客户端。
    """
    from app.main import app

    def override_get_db():
        """覆写数据库依赖。

        Yields:
            Session: 测试会话。
        """
        yield db_session

    app.dependency_overrides[core_db.get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def project(client):
    """预置项目。

    Args:
        client: 测试客户端。

    Returns:
        dict: 项目数据。
    """
    resp = client.post("/api/projects", json={"name": "测试项目", "genre": "悬疑"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == 0
    return resp.json()["data"]
