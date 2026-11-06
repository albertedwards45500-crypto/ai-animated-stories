"""独立本地 Mock 模式：SQLite + 线程任务池 + 真实 FFmpeg 素材。"""
from __future__ import annotations

import argparse
import os
from pathlib import Path


def configure() -> Path:
    root = Path(__file__).resolve().parents[3]
    runtime = root / ".runtime" / "mock"
    runtime.mkdir(parents=True, exist_ok=True)
    os.environ.update({
        "APP_ENV": "mock", "DATABASE_URL": f"sqlite:///{(runtime / 'app.db').as_posix()}",
        "MEDIA_ROOT": str(runtime / "media"), "BROKER_KIND": "thread",
        "AI_MODE": "mock", "MOCK_DEFAULT_SCENARIO": "success",
        "TEXT_PROVIDER": "mock", "IMAGE_PROVIDER": "mock", "VIDEO_PROVIDER": "mock", "AUDIO_PROVIDER": "mock",
    })
    bundled = root / "tools" / "ffmpeg.exe"
    if bundled.is_file():
        os.environ["FFMPEG_PATH"] = str(bundled)
    return runtime


def prepare() -> Path:
    runtime = configure()
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.core.db import engine
    from app.models.base import Base
    from app.models import entities  # noqa: F401
    from app.tools.seed_mock_assets import seed

    # 仅初始化专用 Mock 数据库，不操作正式 MySQL 或现有媒体目录。
    Base.metadata.create_all(engine)
    media = get_settings().media_root_path
    if not all(any((media / "mock" / kind).glob("*")) for kind in ("images", "audio", "video", "subtitles")):
        seed()
    return runtime


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    runtime = prepare()
    print(f"Mock runtime ready: {runtime}")
    if not args.prepare_only:
        import uvicorn
        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
