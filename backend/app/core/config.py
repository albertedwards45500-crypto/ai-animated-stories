# -*- coding: utf-8 -*-
"""应用配置模块。

基于 pydantic-settings 从环境变量与项目根目录 .env 读取配置，
敏感信息（数据库密码、API Key）只经环境变量注入，不写入代码与 Git。
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

# 项目根目录（backend/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """全局配置对象。

    Attributes:
        app_env: 运行环境（development/production）。
        mysql_host/mysql_port/mysql_database/mysql_user/mysql_password: MySQL 连接参数。
        redis_url: Redis 连接串，Dramatiq broker 与缓存共用。
        ai_mode: AI Provider 全局模式（mock/record/replay）。
        text_provider/image_provider/video_provider/audio_provider: 各能力默认 provider。
        media_root: 媒体文件根目录（相对项目根）。
        ffmpeg_path: FFmpeg 可执行文件路径，留空使用 PATH。
        broker_kind: broker 类型（redis/stub），stub 供测试同步执行。
        deepseek_api_key/minimax_api_key: 真实供应商密钥（阶段三）。
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    database_url: str = Field("", repr=False)

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "ai_drama"
    mysql_user: str = "root"
    mysql_password: str = ""

    redis_url: str = "redis://127.0.0.1:6379/0"

    ai_mode: str = "mock"
    text_provider: str = "mock"
    image_provider: str = "mock"
    video_provider: str = "mock"
    audio_provider: str = "mock"

    media_root: str = "./media"
    ffmpeg_path: str = ""

    # 测试时使用 stub broker，任务同步执行
    broker_kind: str = "redis"
    mock_default_scenario: Literal["success", "fail", "timeout"] | None = None

    deepseek_api_key: str = ""
    minimax_api_key: str = ""

    # 阿里云百炼（DashScope）：图片 / 视频 / 语音
    dashscope_api_key_image: str = ""
    dashscope_api_key_video: str = ""
    dashscope_api_key_audio: str = ""
    image_model: str = "qwen-image-3.0"
    video_model: str = "wan3.0-video"
    audio_model: str = "cosyvoice-v3.5-plus"

    @property
    def sqlalchemy_url(self) -> str:
        """构造 SQLAlchemy 连接串。

        Returns:
            str: pymysql 连接串，固定 utf8mb4 字符集。
        """
        if self.database_url:
            return self.database_url
        return URL.create(
            "mysql+pymysql", username=self.mysql_user, password=self.mysql_password,
            host=self.mysql_host, port=self.mysql_port, database=self.mysql_database,
            query={"charset": "utf8mb4"},
        ).render_as_string(hide_password=False)

    @property
    def media_root_path(self) -> Path:
        """媒体根目录绝对路径。

        Returns:
            Path: 已解析的媒体根目录。
        """
        p = Path(self.media_root)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p.resolve()

    @property
    def ffmpeg_executable(self) -> str:
        """FFmpeg 可执行文件路径。

        Returns:
            str: 配置的绝对路径或空串（使用 PATH 查找）。
        """
        if self.ffmpeg_path:
            return str(Path(self.ffmpeg_path) if Path(self.ffmpeg_path).is_absolute() else PROJECT_ROOT / self.ffmpeg_path)
        return "ffmpeg"


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例。

    Returns:
        Settings: 全局配置对象。
    """
    return Settings()
